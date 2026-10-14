"""Shared helpers for the tests.

The tests need a PostgreSQL database they are free to wipe. Point
TEST_DATABASE_URL at it (never at a database with real data).
"""

from __future__ import annotations

import os
import unittest

from app.actor import Actor
from app.config import Settings
from app.db import run_in_tx
from app.migrate import apply_migrations
from app.services import accounts

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/tajweed_test"
)

# Cheap password hashing so the tests run quickly.
SETTINGS = Settings(
    database_url=TEST_DATABASE_URL,
    jwt_secret="test-secret-that-is-long-enough-for-hs256",
    environment="test",
    scrypt_log_n=8,
    scrypt_p=1,
    max_failed_logins=3,
)

_db = None


def database():
    """The test database, wiped and migrated once per test run."""
    global _db
    if _db is None:
        if "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1]:
            raise RuntimeError("Refusing to run: the test database name must contain 'test'.")
        try:
            from app.db import Database
            db = Database(TEST_DATABASE_URL, max_size=4)
        except ImportError:
            from .libpq_fallback import FallbackDatabase
            db = FallbackDatabase(TEST_DATABASE_URL)
        with db.transaction() as tx:
            tx.run("DROP SCHEMA public CASCADE")
            tx.run("CREATE SCHEMA public")
        apply_migrations(db)
        _db = db
    return _db


def wipe(db) -> None:
    """Empty every table, keeping the two riwayat rows."""
    with db.transaction() as tx:
        tx.run("SET LOCAL tajweed.quran_import = 'on'")
        tx.run("TRUNCATE ayahs")
        tx.run("SET LOCAL tajweed.quran_import = 'off'")
        tx.run(
            """
            UPDATE riwayat SET status = 'empty', ayah_count = NULL, text_source = NULL,
                text_notice = NULL, file_sha256 = NULL, content_sha256 = NULL, imported_at = NULL,
                reviewer_name = NULL, approved_by = NULL, approved_at = NULL
            """
        )
        tx.run("DELETE FROM admin_actions")
        tx.run("DELETE FROM users")


class DatabaseTest(unittest.TestCase):
    """Base class: each test starts with an empty database."""

    settings = SETTINGS

    def setUp(self):
        self.db = database()
        wipe(self.db)

    def tx(self, work):
        return run_in_tx(self.db, work)

    # --- ready-made people ---------------------------------------------------

    def make_user(self, email="student@example.com", role="student", password="correct horse",
                  name="Test User") -> Actor:
        def work(tx):
            user_id = accounts.create_login_user(
                tx, self.settings, email=email, password=password, display_name=name,
                language="en", timezone="UTC", role=role,
            )
            return Actor(user_id=user_id, roles=frozenset({role}))
        return self.tx(work)

    def make_admin(self, email="admin@example.com") -> Actor:
        return self.make_user(email=email, role="admin", name="Admin")

    def make_parent(self, email="parent@example.com") -> Actor:
        return self.make_user(email=email, role="parent", name="Parent")


def sample_text(riwaya_counts: dict[int, int], *, notice: str = "# Sample text for automated tests") -> bytes:
    """Build a file in the import format with the right number of ayat.

    The lines hold placeholder words, never real Quran text, so the tests can
    never be mistaken for a source of it.
    """
    lines = [
        f"{surah}|{ayah}|placeholder {surah}:{ayah}"
        for surah, count in sorted(riwaya_counts.items())
        for ayah in range(1, count + 1)
    ]
    return ("\n".join(lines) + "\n\n" + notice + "\n").encode("utf-8")
