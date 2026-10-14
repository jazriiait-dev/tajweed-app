"""Apply the SQL files in `migrations/` that have not been applied yet."""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def apply_migrations(db, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in filename order. Returns the ones applied.

    Everything runs in one transaction: either all pending migrations are
    applied, or none are.
    """
    applied_now: list[str] = []
    with db.transaction() as tx:
        tx.run(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     text PRIMARY KEY,
                applied_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        # Stops two servers that start at the same moment from migrating twice.
        tx.run("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        done = {row["version"] for row in tx.all("SELECT version FROM schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.stem in done:
                continue
            tx.run(path.read_text(encoding="utf-8"))
            tx.run("INSERT INTO schema_migrations (version) VALUES (%s)", [path.stem])
            applied_now.append(path.stem)
    return applied_now
