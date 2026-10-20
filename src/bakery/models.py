"""Database schema (SQLAlchemy 2.0 typed ORM). Alembic migrations mirror these tables."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
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


class Upload(Base):
    """上傳: one file as received. Append-only: a DB trigger rejects DELETE and any
    change to the original (uploader, submitting account, filename, bytes, hash, size, time).
    store_code, reply_text, report_text and failure_reason are processing results,
    filled in after parsing."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL when LINE did not say which account sent the file (userId is not always included).
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("uploaders.id"))
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
