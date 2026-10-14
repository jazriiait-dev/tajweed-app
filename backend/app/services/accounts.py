"""Sign-up, sign-in and a person's own profile."""

from __future__ import annotations

from functools import lru_cache

from .. import security
from ..actor import Actor
from ..config import Settings
from ..db import Tx
from ..errors import AppError, Conflict, Forbidden, NotFound, NotSignedIn
from ..schemas import AddRole, ChangePassword, Login, Register, UpdateProfile


def user_view(tx: Tx, user_id: str) -> dict:
    row = tx.one(
        """
        SELECT u.id, u.email, u.display_name, u.language, u.timezone, u.is_child,
               u.is_active, u.created_at,
               coalesce((SELECT string_agg(r.role, ',' ORDER BY r.role)
                         FROM user_roles r WHERE r.user_id = u.id), '') AS roles
        FROM users u
        WHERE u.id = %s
        """,
        [user_id],
    )
    if row is None:
        raise NotFound("user_not_found", "This user does not exist.")
    row["roles"] = [role for role in row["roles"].split(",") if role]
    return row


def _hash(settings: Settings, password: str) -> str:
    return security.hash_password(password, log_n=settings.scrypt_log_n, p=settings.scrypt_p)


@lru_cache(maxsize=4)
def _decoy_hash(log_n: int, p: int) -> str:
    return security.hash_password("no-such-account", log_n=log_n, p=p)


def issue_tokens(tx: Tx, settings: Settings, user_id: str) -> dict:
    refresh_token = security.new_refresh_token()
    tx.run(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, now() + make_interval(days => %s::int))
        """,
        [user_id, security.hash_refresh_token(refresh_token), settings.refresh_token_days],
    )
    return {
        "access_token": security.make_access_token(
            settings.jwt_secret, user_id, minutes=settings.access_token_minutes
        ),
        "expires_in": settings.access_token_minutes * 60,
        "refresh_token": refresh_token,
    }


def revoke_all_tokens(tx: Tx, user_id: str) -> None:
    tx.run(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
        [user_id],
    )


def create_login_user(tx: Tx, settings: Settings, *, email: str, password: str,
                      display_name: str, language: str, timezone: str, role: str) -> str:
    """Create an adult account with one role. Raises Conflict if the email is taken."""
    if password.lower() == email:
        raise AppError("weak_password", "Choose a password that is not your email address.")
    row = tx.one(
        """
        INSERT INTO users (email, password_hash, display_name, language, timezone)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (email) DO NOTHING
        RETURNING id
        """,
        [email, _hash(settings, password), display_name, language, timezone],
    )
    if row is None:
        raise Conflict("email_taken", "An account with this email already exists.")
    user_id = str(row["id"])
    tx.run("INSERT INTO user_roles (user_id, role) VALUES (%s, %s)", [user_id, role])
    return user_id


def register(tx: Tx, settings: Settings, data: Register) -> dict:
    if not data.confirms_adult:
        raise AppError(
            "adult_required",
            "Only adults can sign up. A parent can create a profile for a child.",
        )
    user_id = create_login_user(
        tx, settings,
        email=data.email, password=data.password, display_name=data.display_name,
        language=data.language, timezone=data.timezone, role=data.account_type,
    )
    return {"user": user_view(tx, user_id), **issue_tokens(tx, settings, user_id)}


def login(tx: Tx, settings: Settings, data: Login) -> dict:
    wrong = NotSignedIn("wrong_credentials", "The email or password is not correct.")
    row = tx.one(
        """
        SELECT id, password_hash, is_active, failed_logins,
               coalesce(locked_until > now(), false) AS is_locked
        FROM users
        WHERE email = %s
        FOR UPDATE
        """,
        [data.email],
    )
    if row is None:
        # Spend the same time as a real check, so replies do not reveal
        # which emails have accounts.
        security.verify_password(data.password, _decoy_hash(settings.scrypt_log_n, settings.scrypt_p))
        raise wrong

    user_id = str(row["id"])
    if row["is_locked"]:
        raise AppError(
            "account_locked",
            "Too many failed attempts. Try again in a few minutes.",
            status=429,
        )

    if not security.verify_password(data.password, row["password_hash"]):
        failed = row["failed_logins"] + 1
        if failed >= settings.max_failed_logins:
            tx.run(
                """
                UPDATE users
                SET failed_logins = 0,
                    locked_until = now() + make_interval(mins => %s::int)
                WHERE id = %s
                """,
                [settings.lockout_minutes, user_id],
            )
        else:
            tx.run("UPDATE users SET failed_logins = %s WHERE id = %s", [failed, user_id])
        wrong.commit = True  # keep the failed-attempt count
        raise wrong

    if not row["is_active"]:
        raise Forbidden("account_disabled", "This account has been disabled.")

    tx.run("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", [user_id])
    if security.password_needs_rehash(
        row["password_hash"], log_n=settings.scrypt_log_n, p=settings.scrypt_p
    ):
        tx.run(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            [_hash(settings, data.password), user_id],
        )
    return {"user": user_view(tx, user_id), **issue_tokens(tx, settings, user_id)}


def refresh(tx: Tx, settings: Settings, refresh_token: str) -> dict:
    row = tx.one(
        """
        SELECT t.id, t.user_id, t.revoked_at IS NOT NULL AS is_revoked, t.was_rotated,
               t.expires_at <= now() AS is_expired, u.is_active
        FROM refresh_tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.token_hash = %s
        FOR UPDATE OF t
        """,
        [security.hash_refresh_token(refresh_token)],
    )
    if row is None:
        raise NotSignedIn("invalid_refresh_token", "Sign in again.")

    user_id = str(row["user_id"])
    if row["is_revoked"]:
        if row["was_rotated"]:
            # A token that was already exchanged is being presented again. It
            # may have been copied, so every session of this account is ended.
            revoke_all_tokens(tx, user_id)
            raise NotSignedIn("refresh_token_reused", "Sign in again.", commit=True)
        # Ended on purpose: signed out, password changed, or account disabled.
        raise NotSignedIn("session_ended", "Sign in again.")
    if row["is_expired"]:
        raise NotSignedIn("session_expired", "Your session has expired. Sign in again.")
    if not row["is_active"]:
        raise Forbidden("account_disabled", "This account has been disabled.")

    tx.run(
        "UPDATE refresh_tokens SET revoked_at = now(), was_rotated = true WHERE id = %s",
        [str(row["id"])],
    )
    return issue_tokens(tx, settings, user_id)


def logout(tx: Tx, refresh_token: str) -> None:
    tx.run(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
        [security.hash_refresh_token(refresh_token)],
    )


def me(tx: Tx, actor: Actor) -> dict:
    view = user_view(tx, actor.user_id)
    view["opened_by_parent"] = actor.guardian_id
    return view


def update_profile(tx: Tx, user_id: str, data: UpdateProfile) -> dict:
    changes = data.model_dump(exclude_none=True)
    for column in ("display_name", "language", "timezone"):
        if column in changes:
            # Column names come from the fixed tuple above, never from input.
            tx.run(f"UPDATE users SET {column} = %s WHERE id = %s", [changes[column], user_id])
    return user_view(tx, user_id)


def update_me(tx: Tx, actor: Actor, data: UpdateProfile) -> dict:
    actor.require_adult()
    return update_profile(tx, actor.user_id, data)


def change_password(tx: Tx, settings: Settings, actor: Actor, data: ChangePassword) -> dict:
    actor.require_adult()
    row = tx.one(
        "SELECT email, password_hash FROM users WHERE id = %s FOR UPDATE", [actor.user_id]
    )
    if row is None or not security.verify_password(data.current_password, row["password_hash"]):
        raise AppError("wrong_password", "The current password is not correct.", status=403)
    if data.new_password.lower() == row["email"]:
        raise AppError("weak_password", "Choose a password that is not your email address.")
    tx.run(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        [_hash(settings, data.new_password), actor.user_id],
    )
    # Sign out every device, then sign this one back in.
    revoke_all_tokens(tx, actor.user_id)
    return issue_tokens(tx, settings, actor.user_id)


def add_role(tx: Tx, actor: Actor, data: AddRole) -> dict:
    """Let an adult be both a student and a parent."""
    actor.require_adult()
    tx.run(
        "INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [actor.user_id, data.role],
    )
    return user_view(tx, actor.user_id)
