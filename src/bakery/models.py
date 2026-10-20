"""Database schema (SQLAlchemy 2.0 typed ORM). Alembic migrations mirror these tables."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class LineStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"  # 取消: marked explicitly in the 狀態 column, never inferred


class ChangeKind(StrEnum):
    """修改類型. One 修改 can carry several, except 疑似單號重複使用, which stands alone."""

    ADD_QTY = "add_qty"  # 追加: more 盒, a new 品項, or a 取消 line back in production
    REDUCE_QTY = "reduce_qty"  # 減量: fewer 盒, still above 0
    PICKUP_DATE = "pickup_date"  # 改取貨日
    CANCEL = "cancel"  # 取消: 狀態 newly marked 取消
    INFO_FIX = "info_fix"  # 資料更正: fields that don't affect production (phone-only included)
    SUSPECTED_REUSE = "suspected_reuse"  # 疑似單號重複使用: phone changed AND the set of 品項 or 取貨日 changed


class ChangeField(StrEnum):
    """A field a change log entry records. Line fields come with the entry's product_code."""

    ORDERER_NAME = "orderer_name"
    PHONE = "phone"
    RECEIVED_ON = "received_on"
    PICKUP_ON = "pickup_on"
    BANQUET_ON = "banquet_on"
    COUPLE_NAMES = "couple_names"
    TAKEN_BY = "taken_by"
    QUANTITY = "quantity"
    NOTE = "note"
    STATUS = "status"


class ChangeDecision(StrEnum):
    """What happened to a change when its 上傳 was processed. Decided by bakery.changes.decide."""

    APPLIED = "applied"
    HELD = "held"  # 待確認: not applied; the order keeps its earlier content until 總部 confirms


class ReviewStatus(StrEnum):
    """Where a 待確認 stands. Only 總部人員 move it out of pending (bakery.reviews)."""

    PENDING = "pending"  # waiting for 總部
    CONFIRMED = "confirmed"  # applied to the order
    REJECTED = "rejected"  # 退回: the order keeps its earlier content
    # The 門市 sent this 喜餅訂單 again with other content (or back as it is on record)
    # before 總部 decided: the later file is what counts, nothing left to decide.
    SUPERSEDED = "superseded"


DEFAULT_CUTOFF_DAYS = 7


class Settings(Base):
    """What 總部 tunes on the web. A single row (id 1), seeded with the defaults."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("cutoff_days >= 0", name="cutoff_days_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 修改截止點: 取貨日前 N 天 (bakery.changes.past_cutoff).
    cutoff_days: Mapped[int] = mapped_column(default=DEFAULT_CUTOFF_DAYS)
    # The 總部人員 who last set cutoff_days, and when; NULL while it is the seeded default.
    cutoff_days_set_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    cutoff_days_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cutoff_days_set_by: Mapped[Account | None] = relationship()


class Role(StrEnum):
    """Who a web account belongs to. Which pages each role sees: bakery.web.auth.ACCESS."""

    HQ = "hq"  # 總部人員: one account per person, so every confirmation names who did it
    KITCHEN = "kitchen"  # 廚房: one shared account
    OWNER = "owner"  # 老闆


class Account(Base):
    """A web login. 門市 have none: they only use the 範本 and LINE."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="role",
        )
    )
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2id, never the password
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Store(Base):
    """門市."""

    __tablename__ = "stores"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class Product(Base):
    """品項."""

    __tablename__ = "products"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # The 總部人員 who added it on the web; NULL for the seeded catalog.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    aliases: Mapped[list[ProductAlias]] = relationship(back_populates="product")
    created_by: Mapped[Account | None] = relationship()


class ProductAlias(Base):
    """品項別名: another way a 門市 writes a 品項. Unique across all products."""

    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.code"))
    alias: Mapped[str] = mapped_column(String(64), unique=True)
    # The 總部人員 who added it on the web; NULL for seeded aliases.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    product: Mapped[Product] = relationship(back_populates="aliases")
    created_by: Mapped[Account | None] = relationship()


class Uploader(Base):
    """傳檔者: a LINE account that sends files. Which 門市 it belongs to: StoreBinding."""

    __tablename__ = "uploaders"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    # Seeded accounts offered on the 模擬群組上傳 page.
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    binding: Mapped[StoreBinding | None] = relationship(back_populates="uploader")


class BindingStatus(StrEnum):
    PENDING = "pending"  # recorded from the 傳檔者's first upload; 總部 has not confirmed yet
    CONFIRMED = "confirmed"


class StoreBinding(Base):
    """門市綁定: the one 門市 a 傳檔者 sends files for (a 門市 may have many 傳檔者).

    Recorded as pending from the first upload whose 門市 is known; a 總部人員
    confirms it, correcting the 門市 if the guess was wrong."""

    __tablename__ = "store_bindings"

    uploader_id: Mapped[int] = mapped_column(ForeignKey("uploaders.id"), primary_key=True)
    store_code: Mapped[str] = mapped_column(ForeignKey("stores.code"))
    status: Mapped[BindingStatus] = mapped_column(
        Enum(
            BindingStatus,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="binding_status",
        ),
        default=BindingStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploader: Mapped[Uploader] = relationship(back_populates="binding")
    store: Mapped[Store] = relationship()
    confirmed_by: Mapped[Account | None] = relationship()


class LineWebhookEvent(Base):
    """A LINE webhook event already taken, by its webhookEventId. LINE may deliver one
    event more than once (redelivery, network retries); only the first is processed."""

    __tablename__ = "line_webhook_events"

    webhook_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    # The file could not be fetched from LINE: the 傳檔者 was asked to send it again.
    download_failed: Mapped[bool] = mapped_column(default=False, server_default=false())


class Upload(Base):
    """上傳: one file as received. Append-only: a DB trigger rejects DELETE and any
    change to the original (uploader, submitting account, filename, bytes, hash, size,
    time, whether it was a 歷史資料 import).
    store_code, reply_text, report_text and failure_reason are processing results,
    filled in after parsing."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL when LINE did not say which account sent the file (userId is not always
    # included), and for a 歷史資料匯入, which no 傳檔者 sent.
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("uploaders.id"))
    # The web account that sent the file (模擬群組上傳 or 歷史資料匯入); NULL when it came from LINE.
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    # A 歷史資料匯入 by a 總部人員: no 傳檔者, no LINE reply (reply_text stays NULL).
    is_historical: Mapped[bool] = mapped_column(default=False, server_default=false())
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    store_code: Mapped[str | None] = mapped_column(ForeignKey("stores.code"))
    reply_text: Mapped[str | None] = mapped_column(Text)  # what the LINE reply says
    # The full reply with every finding; the LINE reply links here when it is cut short.
    report_text: Mapped[str | None] = mapped_column(Text)
    # Why processing broke (exception type and code location, never cell content); NULL if it didn't.
    failure_reason: Mapped[str | None] = mapped_column(Text)

    uploader: Mapped[Uploader | None] = relationship()
    submitted_by: Mapped[Account | None] = relationship()
    store: Mapped[Store | None] = relationship()


class Order(Base):
    """喜餅訂單: identified by 門市 + 單號; exactly one 取貨日."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("store_code", "order_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_code: Mapped[str] = mapped_column(ForeignKey("stores.code"))
    order_no: Mapped[str] = mapped_column(String(64))
    orderer_name: Mapped[str | None] = mapped_column(String(128))
    # As typed. The 客人 is derived from it on read (bakery.customers), never stored.
    phone: Mapped[str | None] = mapped_column(String(64))
    received_on: Mapped[date] = mapped_column(Date)
    pickup_on: Mapped[date] = mapped_column(Date, index=True)
    banquet_on: Mapped[date | None] = mapped_column(Date)
    couple_names: Mapped[str | None] = mapped_column(String(128))
    taken_by: Mapped[str | None] = mapped_column(String(64))
    # 歷史資料: imported from a 門市's pre-go-live Excel. Never part of production (廚房彙總),
    # but part of 客人資料.
    is_historical: Mapped[bool] = mapped_column(default=False, server_default=false())

    store: Mapped[Store] = relationship()
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", order_by="OrderLine.id", cascade="all, delete-orphan"
    )


class OrderLine(Base):
    """訂單明細: one 品項 of a 喜餅訂單 (one template row). One line per 品項 per order."""

    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "product_code"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_code: Mapped[str] = mapped_column(ForeignKey("products.code"))
    quantity: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LineStatus] = mapped_column(
        Enum(
            LineStatus,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="line_status",
        ),
        default=LineStatus.ACTIVE,
    )

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Change(Base):
    """修改紀錄: one 喜餅訂單 as one 上傳 brought it in, new (is_new_order) or with different
    content. Unchanged orders get none. Uploader and time come from the upload.
    Append-only: a DB trigger rejects UPDATE and DELETE."""

    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    is_new_order: Mapped[bool]
    kinds: Mapped[list[str]] = mapped_column(ARRAY(String(32)))  # ChangeKind values; empty for 新單
    decision: Mapped[ChangeDecision] = mapped_column(
        Enum(
            ChangeDecision,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="change_decision",
        )
    )

    upload: Mapped[Upload] = relationship()
    order: Mapped[Order] = relationship()
    entries: Mapped[list[ChangeEntry]] = relationship(order_by="ChangeEntry.id")
    # Set for a HELD change: its 待確認.
    review: Mapped[PendingReview | None] = relationship(back_populates="change")

    @property
    def change_kinds(self) -> tuple[ChangeKind, ...]:
        return tuple(ChangeKind(k) for k in self.kinds)


class ChangeEntry(Base):
    """One field of a Change: old → new, as text (dates ISO, 盒數 digits, 狀態 a LineStatus value;
    NULL = empty, or no such 訂單明細 yet). Append-only like Change."""

    __tablename__ = "change_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    field: Mapped[ChangeField] = mapped_column(
        Enum(
            ChangeField,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="change_field",
        )
    )
    product_code: Mapped[str | None] = mapped_column(ForeignKey("products.code"))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product | None] = relationship()


class PendingReview(Base):
    """待確認: a HELD Change waiting for (or decided by) a 總部人員.

    The Change itself never changes (append-only); its fate is recorded here. Confirming
    applies the change's entries to the order; 退回 leaves the order as it was."""

    __tablename__ = "pending_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), unique=True)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            name="review_status",
        ),
        default=ReviewStatus.PENDING,
        index=True,
    )
    # Who confirmed or rejected it, and when (NULL while pending, and when superseded).
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The 門市's next upload, whose reply told them the decision (no push). NULL until then.
    reported_upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))

    change: Mapped[Change] = relationship(back_populates="review")
    decided_by: Mapped[Account | None] = relationship()
    reported_upload: Mapped[Upload | None] = relationship()
