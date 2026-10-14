"""Database access.

The rest of the code only uses the small `Tx` interface below (`one`, `all`,
`run`), always with `%s` placeholders, so every query is plain SQL that can be
read and tested on its own.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, Protocol, Sequence, TypeVar

from .errors import AppError

T = TypeVar("T")


class Tx(Protocol):
    """One open database transaction."""

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        """Run a query and return its first row, or None."""

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        """Run a query and return every row."""

    def run(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a statement and return the number of rows it changed."""


class TransactionSource(Protocol):
    def transaction(self): ...


class Database:
    """A pool of PostgreSQL connections (psycopg 3)."""

    def __init__(self, url: str, max_size: int = 10):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(
            url,
            min_size=1,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        # The pool commits when the block ends normally and rolls back on error.
        with self._pool.connection() as conn:
            yield _PsycopgTx(conn)


class _PsycopgTx:
    def __init__(self, conn):
        self._conn = conn

    # `params or None`: with no parameters psycopg sends the SQL untouched,
    # which lets a migration file hold many statements and literal % signs.

    def one(self, sql, params=()):
        return self._conn.execute(sql, params or None).fetchone()

    def all(self, sql, params=()):
        return self._conn.execute(sql, params or None).fetchall()

    def run(self, sql, params=()):
        return self._conn.execute(sql, params or None).rowcount


def run_in_tx(db: TransactionSource, work: Callable[[Tx], T]) -> T:
    """Run `work` in one transaction.

    An AppError raised with `commit=True` keeps the changes made so far and is
    raised again after the commit. Any other error rolls everything back.
    """
    kept_error: AppError | None = None
    result: Any = None
    with db.transaction() as tx:
        try:
            result = work(tx)
        except AppError as error:
            if not error.commit:
                raise
            kept_error = error
    if kept_error is not None:
        raise kept_error
    return result
