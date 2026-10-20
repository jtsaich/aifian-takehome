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
    SUSPECTED_REUSE = "suspected_reuse"  # 疑似單號重複使用: phone changed AND 品項/盒數 or 取貨日 changed


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
    HELD = "held"  # not applied: the order keeps its earlier content



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

    aliases: Mapped[list[ProductAlias]] = relationship(back_populates="product")


class ProductAlias(Base):
    """品項別名: another way a 門市 writes a 品項. Unique across all products."""

    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.code"))
    alias: Mapped[str] = mapped_column(String(64), unique=True)

    product: Mapped[Product] = relationship(back_populates="aliases")


class Uploader(Base):
    """傳檔者: a LINE account that sends files. Store binding comes later (StoreBinding)."""

    __tablename__ = "uploaders"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    # Seeded accounts offered on the 模擬群組上傳 page.
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Upload(Base):
    """上傳: one file as received. Append-only: a DB trigger rejects DELETE and any
    change to the original (uploader, submitting account, filename, bytes, hash, size, time).
    store_code and reply_text are processing results, filled in after parsing."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("uploaders.id"))
    # The web account that sent the file from the 模擬群組上傳 page; NULL when it came from LINE.
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    store_code: Mapped[str | None] = mapped_column(ForeignKey("stores.code"))
    reply_text: Mapped[str | None] = mapped_column(Text)  # what the LINE reply says
    # The full reply with every finding; the LINE reply links here when it is cut short.
    report_text: Mapped[str | None] = mapped_column(Text)

    uploader: Mapped[Uploader] = relationship()
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
    phone: Mapped[str | None] = mapped_column(String(64))  # as typed; normalized later (Customer)
    received_on: Mapped[date] = mapped_column(Date)
    pickup_on: Mapped[date] = mapped_column(Date, index=True)
    banquet_on: Mapped[date | None] = mapped_column(Date)
    couple_names: Mapped[str | None] = mapped_column(String(128))
    taken_by: Mapped[str | None] = mapped_column(String(64))

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
