"""What platform staff can do: manage teachers and accounts, approve the Quran text."""

from __future__ import annotations

from .. import security
from ..actor import Actor, as_uuid
from ..config import Settings
from ..db import Tx
from ..errors import AppError, NotFound
from ..schemas import ApproveRiwaya, CreateTeacher, SetActive, SetPassword, UpdateTeacher
from . import accounts

ROLES = ("student", "parent", "teacher", "admin")


def _user_not_found() -> NotFound:
    return NotFound("user_not_found", "This user does not exist.")


def _log(tx: Tx, actor: Actor, action: str, target_user_id: str | None = None, detail: str = "") -> None:
    tx.run(
        "INSERT INTO admin_actions (admin_id, action, target_user_id, detail) VALUES (%s, %s, %s, %s)",
        [actor.user_id, action, target_user_id, detail],
    )


def create_admin(tx: Tx, settings: Settings, *, email: str, password: str, display_name: str) -> dict:
    """Create an admin account. Only reachable from the command line."""
    user_id = accounts.create_login_user(
        tx, settings, email=email, password=password, display_name=display_name,
        language="en", timezone="UTC", role="admin",
    )
    return accounts.user_view(tx, user_id)


# --- accounts ----------------------------------------------------------------

def list_users(tx: Tx, actor: Actor, *, role: str | None = None, search: str | None = None,
               limit: int = 50, offset: int = 0) -> dict:
    actor.require("admin")
    if role is not None and role not in ROLES:
        raise AppError("unknown_role", "This role does not exist.")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    where, params = ["true"], []
    if role:
        where.append("EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = %s)")
        params.append(role)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(u.display_name ILIKE %s OR u.email ILIKE %s)")
        params += [f"%{escaped}%", f"%{escaped}%"]
    condition = " AND ".join(where)

    total = tx.one(f"SELECT count(*) AS n FROM users u WHERE {condition}", params)
    rows = tx.all(
        f"""
        SELECT u.id, u.email, u.display_name, u.language, u.is_child, u.is_active, u.created_at,
               coalesce((SELECT string_agg(r.role, ',' ORDER BY r.role)
                         FROM user_roles r WHERE r.user_id = u.id), '') AS roles
        FROM users u
        WHERE {condition}
        ORDER BY u.created_at DESC, u.id
        LIMIT %s::int OFFSET %s::int
        """,
        params + [limit, offset],
    )
    for row in rows:
        row["roles"] = [r for r in row["roles"].split(",") if r]
    return {"total": total["n"], "items": rows}


def set_active(tx: Tx, actor: Actor, user_id: str, data: SetActive) -> dict:
    actor.require("admin")
    user_id = as_uuid(user_id, error=_user_not_found())
    if user_id == actor.user_id and not data.active:
        raise AppError("cannot_disable_self", "You cannot disable your own account.")
    changed = tx.run("UPDATE users SET is_active = %s WHERE id = %s", [data.active, user_id])
    if changed == 0:
        raise _user_not_found()
    if not data.active:
        accounts.revoke_all_tokens(tx, user_id)
    _log(tx, actor, "enable_account" if data.active else "disable_account", user_id)
    return accounts.user_view(tx, user_id)


def set_password(tx: Tx, settings: Settings, actor: Actor, user_id: str, data: SetPassword) -> None:
    """Give an account a new password, for someone who is locked out."""
    actor.require("admin")
    user_id = as_uuid(user_id, error=_user_not_found())
    user = tx.one("SELECT email, is_child FROM users WHERE id = %s FOR UPDATE", [user_id])
    if user is None:
        raise _user_not_found()
    if user["is_child"]:
        raise AppError("no_password", "Child profiles have no password; a parent opens them.")
    tx.run(
        """
        UPDATE users
        SET password_hash = %s, failed_logins = 0, locked_until = NULL
        WHERE id = %s
        """,
        [security.hash_password(data.new_password, log_n=settings.scrypt_log_n, p=settings.scrypt_p),
         user_id],
    )
    accounts.revoke_all_tokens(tx, user_id)
    _log(tx, actor, "set_password", user_id)


def list_actions(tx: Tx, actor: Actor, *, limit: int = 100) -> list[dict]:
    actor.require("admin")
    return tx.all(
        """
        SELECT a.id, a.action, a.detail, a.created_at,
               a.admin_id, admin.display_name AS admin_name,
               a.target_user_id, target.display_name AS target_name
        FROM admin_actions a
        JOIN users admin ON admin.id = a.admin_id
        LEFT JOIN users target ON target.id = a.target_user_id
        ORDER BY a.created_at DESC, a.id
        LIMIT %s::int
        """,
        [max(1, min(limit, 500))],
    )


# --- teachers ----------------------------------------------------------------

def _check_riwayat(tx: Tx, codes: list[str]) -> list[str]:
    known = {row["code"] for row in tx.all("SELECT code FROM riwayat")}
    codes = sorted(set(codes))
    unknown = [code for code in codes if code not in known]
    if unknown:
        raise AppError("unknown_riwaya", "This riwaya is not set up.", details={"riwayat": unknown})
    return codes


def _replace_riwayat(tx: Tx, user_id: str, codes: list[str]) -> None:
    tx.run("DELETE FROM teacher_riwayat WHERE user_id = %s", [user_id])
    for code in codes:
        tx.run("INSERT INTO teacher_riwayat (user_id, riwaya_code) VALUES (%s, %s)", [user_id, code])


def _replace_languages(tx: Tx, user_id: str, languages: list[str]) -> None:
    tx.run("DELETE FROM teacher_languages WHERE user_id = %s", [user_id])
    for language in sorted(set(languages)):
        tx.run("INSERT INTO teacher_languages (user_id, language) VALUES (%s, %s)", [user_id, language])


def teacher_view(tx: Tx, teacher_id: str) -> dict:
    row = tx.one(
        """
        SELECT u.id, u.email, u.display_name, u.language, u.timezone, u.is_active,
               t.gender, t.credentials, t.is_verified, t.verified_at,
               coalesce((SELECT string_agg(riwaya_code, ',' ORDER BY riwaya_code)
                         FROM teacher_riwayat WHERE user_id = u.id), '') AS riwayat,
               coalesce((SELECT string_agg(language, ',' ORDER BY language)
                         FROM teacher_languages WHERE user_id = u.id), '') AS languages
        FROM teacher_profiles t
        JOIN users u ON u.id = t.user_id
        WHERE t.user_id = %s
        """,
        [teacher_id],
    )
    if row is None:
        raise NotFound("teacher_not_found", "This teacher does not exist.")
    row["riwayat"] = [c for c in row["riwayat"].split(",") if c]
    row["languages"] = [c for c in row["languages"].split(",") if c]
    return row


def create_teacher(tx: Tx, settings: Settings, actor: Actor, data: CreateTeacher) -> dict:
    actor.require("admin")
    riwayat = _check_riwayat(tx, data.riwayat)
    user_id = accounts.create_login_user(
        tx, settings, email=data.email, password=data.password, display_name=data.display_name,
        language=data.language, timezone=data.timezone, role="teacher",
    )
    tx.run(
        "INSERT INTO teacher_profiles (user_id, gender, credentials) VALUES (%s, %s, %s)",
        [user_id, data.gender, data.credentials],
    )
    _replace_riwayat(tx, user_id, riwayat)
    _replace_languages(tx, user_id, list(data.languages))
    _log(tx, actor, "create_teacher", user_id)
    return teacher_view(tx, user_id)


def list_teachers(tx: Tx, actor: Actor) -> list[dict]:
    actor.require("admin")
    ids = tx.all(
        """
        SELECT t.user_id FROM teacher_profiles t
        JOIN users u ON u.id = t.user_id
        ORDER BY u.display_name, t.user_id
        """
    )
    return [teacher_view(tx, str(row["user_id"])) for row in ids]


def update_teacher(tx: Tx, actor: Actor, teacher_id: str, data: UpdateTeacher) -> dict:
    actor.require("admin")
    not_found = NotFound("teacher_not_found", "This teacher does not exist.")
    teacher_id = as_uuid(teacher_id, error=not_found)
    profile = tx.one(
        "SELECT is_verified FROM teacher_profiles WHERE user_id = %s FOR UPDATE", [teacher_id]
    )
    if profile is None:
        raise not_found

    if data.gender is not None:
        tx.run("UPDATE teacher_profiles SET gender = %s WHERE user_id = %s", [data.gender, teacher_id])
    if data.credentials is not None:
        tx.run(
            "UPDATE teacher_profiles SET credentials = %s WHERE user_id = %s",
            [data.credentials, teacher_id],
        )
    if data.riwayat is not None:
        _replace_riwayat(tx, teacher_id, _check_riwayat(tx, data.riwayat))
    if data.languages is not None:
        _replace_languages(tx, teacher_id, list(data.languages))

    if data.verified is True and not profile["is_verified"]:
        tx.run(
            """
            UPDATE teacher_profiles
            SET is_verified = true, verified_by = %s, verified_at = now()
            WHERE user_id = %s
            """,
            [actor.user_id, teacher_id],
        )
        _log(tx, actor, "verify_teacher", teacher_id)
    elif data.verified is False and profile["is_verified"]:
        tx.run(
            """
            UPDATE teacher_profiles
            SET is_verified = false, verified_by = NULL, verified_at = NULL
            WHERE user_id = %s
            """,
            [teacher_id],
        )
        _log(tx, actor, "unverify_teacher", teacher_id)
    return teacher_view(tx, teacher_id)


# --- Quran text sign-off -----------------------------------------------------

def approve_riwaya(tx: Tx, actor: Actor, code: str, data: ApproveRiwaya) -> dict:
    """Record that a qualified reviewer has checked the imported text.

    Until this is done the text is visible to admins only.
    """
    actor.require("admin")
    riwaya = tx.one("SELECT status FROM riwayat WHERE code = %s FOR UPDATE", [code])
    if riwaya is None:
        raise NotFound("riwaya_not_found", "This riwaya is not set up.")
    if riwaya["status"] == "empty":
        raise AppError("no_text", "Import the text for this riwaya before approving it.")
    if riwaya["status"] == "approved":
        raise AppError("already_approved", "This text has already been approved.")
    tx.run(
        """
        UPDATE riwayat
        SET status = 'approved', reviewer_name = %s, approved_by = %s, approved_at = now()
        WHERE code = %s
        """,
        [data.reviewer_name, actor.user_id, code],
    )
    _log(tx, actor, "approve_riwaya", None, f"{code}, reviewed by {data.reviewer_name}")
    return tx.one(
        "SELECT code, status, ayah_count, reviewer_name, approved_at FROM riwayat WHERE code = %s",
        [code],
    )
