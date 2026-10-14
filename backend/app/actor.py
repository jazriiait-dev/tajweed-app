"""Who is making a request, and what they are allowed to do."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .db import Tx
from .errors import Forbidden, NotSignedIn


@dataclass(frozen=True)
class Actor:
    user_id: str
    roles: frozenset[str]
    is_child: bool = False
    # The parent who opened this child profile, when is_child is true.
    guardian_id: str | None = None

    def has(self, role: str) -> bool:
        return role in self.roles

    def require(self, role: str) -> None:
        if role not in self.roles:
            raise Forbidden()

    def require_adult(self) -> None:
        if self.is_child:
            raise Forbidden("managed_by_parent", "A parent manages this for a child profile.")


def as_uuid(value: object, *, error: Exception) -> str:
    """Return `value` as a canonical id string, or raise `error`."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise error from None


def resolve_actor(tx: Tx, claims: dict) -> Actor:
    """Turn the contents of a valid access token into an Actor.

    Roles and account status are read fresh on every request, so disabling an
    account or removing a child link takes effect immediately.
    """
    invalid = NotSignedIn("invalid_token", "This sign-in token is not valid.")
    user_id = as_uuid(claims.get("sub"), error=invalid)

    user = tx.one("SELECT id, is_child, is_active FROM users WHERE id = %s", [user_id])
    if user is None:
        raise invalid
    if not user["is_active"]:
        raise Forbidden("account_disabled", "This account has been disabled.")

    guardian_id = None
    if user["is_child"]:
        guardian_id = as_uuid(claims.get("gdn"), error=invalid)
        link = tx.one(
            """
            SELECT 1 AS ok
            FROM guardian_links g
            JOIN users parent ON parent.id = g.guardian_id
            WHERE g.child_id = %s AND g.guardian_id = %s AND parent.is_active
            """,
            [user_id, guardian_id],
        )
        if link is None:
            raise invalid
    elif "gdn" in claims:
        raise invalid

    roles = tx.all("SELECT role FROM user_roles WHERE user_id = %s", [user_id])
    return Actor(
        user_id=user_id,
        roles=frozenset(row["role"] for row in roles),
        is_child=bool(user["is_child"]),
        guardian_id=guardian_id,
    )
