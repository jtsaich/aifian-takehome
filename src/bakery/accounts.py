"""Web accounts: argon2id password hashing and login checks."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.models import Account

_hasher = PasswordHasher()

# Verified against when the username is unknown, so a wrong username takes as long
# as a wrong password and the login form does not reveal which accounts exist.
_UNKNOWN_USER_HASH = _hasher.hash("unknown-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def authenticate(session: Session, username: str, password: str) -> Account | None:
    """The account for these credentials, or None if either is wrong."""
    account = session.scalar(select(Account).where(Account.username == username.strip()))
    try:
        _hasher.verify(account.password_hash if account else _UNKNOWN_USER_HASH, password)
    except (VerificationError, InvalidHashError):
        return None
    return account
