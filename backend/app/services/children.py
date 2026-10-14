"""Child profiles, created and controlled by a parent account."""

from __future__ import annotations

from .. import security
from ..actor import Actor, as_uuid
from ..config import Settings
from ..db import Tx
from ..errors import AppError, NotFound
from ..schemas import CreateChild, UpdateProfile
from . import accounts

MAX_CHILDREN_PER_PARENT = 10

def _child_not_found() -> NotFound:
    return NotFound("child_not_found", "This child profile does not exist.")


def _require_parent(actor: Actor) -> None:
    actor.require_adult()
    actor.require("parent")


def _owned_child_id(tx: Tx, actor: Actor, child_id: str) -> str:
    """Return the id if this child belongs to the parent, else raise not found.

    A child that belongs to someone else gets the same answer as one that
    does not exist, so ids cannot be probed.
    """
    child_id = as_uuid(child_id, error=_child_not_found())
    link = tx.one(
        "SELECT 1 AS ok FROM guardian_links WHERE guardian_id = %s AND child_id = %s",
        [actor.user_id, child_id],
    )
    if link is None:
        raise _child_not_found()
    return child_id


def create_child(tx: Tx, actor: Actor, data: CreateChild) -> dict:
    _require_parent(actor)
    if not data.guardian_consent:
        raise AppError(
            "consent_required",
            "A parent or guardian must give consent to create a child profile.",
        )
    count = tx.one(
        "SELECT count(*) AS n FROM guardian_links WHERE guardian_id = %s", [actor.user_id]
    )
    if count["n"] >= MAX_CHILDREN_PER_PARENT:
        raise AppError("too_many_children", "This account has the maximum number of child profiles.")

    child = tx.one(
        """
        INSERT INTO users (display_name, language, timezone, is_child)
        VALUES (%s, %s, %s, true)
        RETURNING id
        """,
        [data.display_name, data.language, data.timezone],
    )
    child_id = str(child["id"])
    tx.run("INSERT INTO user_roles (user_id, role) VALUES (%s, 'student')", [child_id])
    tx.run(
        "INSERT INTO guardian_links (guardian_id, child_id, consent_given_at) VALUES (%s, %s, now())",
        [actor.user_id, child_id],
    )
    return accounts.user_view(tx, child_id)


def list_children(tx: Tx, actor: Actor) -> list[dict]:
    _require_parent(actor)
    return tx.all(
        """
        SELECT u.id, u.display_name, u.language, u.timezone, u.is_active,
               g.consent_given_at, u.created_at
        FROM guardian_links g
        JOIN users u ON u.id = g.child_id
        WHERE g.guardian_id = %s
        ORDER BY u.created_at, u.id
        """,
        [actor.user_id],
    )


def update_child(tx: Tx, actor: Actor, child_id: str, data: UpdateProfile) -> dict:
    _require_parent(actor)
    child_id = _owned_child_id(tx, actor, child_id)
    return accounts.update_profile(tx, child_id, data)


def open_child_session(tx: Tx, settings: Settings, actor: Actor, child_id: str) -> dict:
    """Give the parent's device a short-lived token that acts as the child."""
    _require_parent(actor)
    child_id = _owned_child_id(tx, actor, child_id)
    child = accounts.user_view(tx, child_id)
    if not child["is_active"]:
        raise AppError("account_disabled", "This profile has been disabled.", status=403)
    return {
        "user": child,
        "access_token": security.make_access_token(
            settings.jwt_secret, child_id,
            minutes=settings.child_token_minutes, guardian_id=actor.user_id,
        ),
        "expires_in": settings.child_token_minutes * 60,
    }
