"""Password hashing and sign-in tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .errors import NotSignedIn

_SCRYPT_R = 8
_KEY_LENGTH = 32
_MAX_LOG_N = 20  # refuse absurd costs if a stored hash is ever corrupted


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    n = 2 ** log_n
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=128 * n * r * 2 + 1024 * 1024,
        dklen=_KEY_LENGTH,
    )


def hash_password(password: str, *, log_n: int = 15, p: int = 3) -> str:
    """Return a salted scrypt hash, with its cost settings stored alongside."""
    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt, log_n, _SCRYPT_R, p)
    return f"scrypt${log_n}${_SCRYPT_R}${p}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, log_n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        log_n, r, p = int(log_n), int(r), int(p)
        if not (1 <= log_n <= _MAX_LOG_N and 1 <= r <= 32 and 1 <= p <= 16):
            return False
        expected = base64.b64decode(key)
        actual = _scrypt(password, base64.b64decode(salt), log_n, r, p)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def password_needs_rehash(stored: str, *, log_n: int, p: int) -> bool:
    """True when a hash was made with weaker settings than the current ones."""
    try:
        _, stored_log_n, _, stored_p, _, _ = stored.split("$")
        return int(stored_log_n) < log_n or int(stored_p) < p
    except ValueError:
        return True


# --- access tokens (short-lived, signed) ------------------------------------

def make_access_token(secret: str, user_id: str, *, minutes: int,
                      guardian_id: str | None = None,
                      now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    if guardian_id is not None:
        # Set when a parent has opened one of their child profiles.
        claims["gdn"] = str(guardian_id)
    return jwt.encode(claims, secret, algorithm="HS256")


def read_access_token(secret: str, token: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise NotSignedIn("session_expired", "Your session has expired. Sign in again.") from None
    except jwt.InvalidTokenError:
        raise NotSignedIn("invalid_token", "This sign-in token is not valid.") from None
    if claims.get("typ") != "access":
        raise NotSignedIn("invalid_token", "This sign-in token is not valid.")
    return claims


# --- refresh tokens (long-lived, random, stored hashed) ----------------------

def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
