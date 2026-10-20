"""門市綁定: which 門市 each 傳檔者 (LINE account) sends files for.

A 傳檔者's first file whose 門市 is known records a pending binding to that 門市;
the file is processed as usual. A 總部人員 confirms the binding on the web,
correcting the 門市 if needed. A bound 傳檔者 who sends another 門市's file is
still processed, with a warning: people do send for a neighbouring store.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from bakery.models import Account, BindingStatus, Store, StoreBinding, Uploader
from bakery.outcome import UploaderNotice, UploaderNoticeKind


def uploader_notice(session: Session, uploader: Uploader | None, store: Store) -> UploaderNotice | None:
    """What the reply tells `uploader` about their binding for a file of `store`.

    Records a pending binding to `store` on the account's first file. Safe when two
    files from a new account race: only one of them records (and announces) it.
    """
    if uploader is None:
        return UploaderNotice(UploaderNoticeKind.UNIDENTIFIED)
    session.flush()  # the uploader may be new
    created = session.scalar(
        insert(StoreBinding)
        .values(uploader_id=uploader.id, store_code=store.code, status=BindingStatus.PENDING)
        .on_conflict_do_nothing()
        .returning(StoreBinding.uploader_id)
    )
    if created is not None:
        return UploaderNotice(UploaderNoticeKind.NEW_BINDING, store_name=store.name)
    binding = session.get(StoreBinding, uploader.id, options=[joinedload(StoreBinding.store)])
    if binding.store_code != store.code:
        return UploaderNotice(
            UploaderNoticeKind.OTHER_STORE, store_name=store.name, bound_store_name=binding.store.name
        )
    return None


def bindings(session: Session) -> list[StoreBinding]:
    """Every binding, pending first, then oldest first."""
    pending_first = case((StoreBinding.status == BindingStatus.PENDING, 0), else_=1)
    return list(
        session.scalars(
            select(StoreBinding)
            .options(
                joinedload(StoreBinding.uploader),
                joinedload(StoreBinding.store),
                joinedload(StoreBinding.confirmed_by),
            )
            .order_by(pending_first, StoreBinding.created_at, StoreBinding.uploader_id)
        )
    )


class UnknownBinding(LookupError):
    pass


def confirm_binding(
    session: Session, *, uploader_id: int, store_code: str, account: Account, now: datetime
) -> StoreBinding:
    """A 總部人員 confirms the 傳檔者 belongs to `store_code` (which may correct the guess)."""
    binding = session.get(StoreBinding, uploader_id)
    store = session.get(Store, store_code)
    if binding is None or store is None:
        raise UnknownBinding(uploader_id)
    binding.store = store
    binding.status = BindingStatus.CONFIRMED
    binding.confirmed_by = account
    binding.confirmed_at = now
    session.commit()
    return binding
