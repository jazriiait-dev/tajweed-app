"""A stand-in for `app.db.Database`, for running the tests on a machine where
the `psycopg` package cannot be installed.

It talks to PostgreSQL through the system's libpq library and offers the same
three calls (`one`, `all`, `run`) with the same `%s` placeholders, and returns
the same Python types psycopg does for the column types this project uses.

It is test support only. The application itself always uses psycopg, and so
do the tests whenever psycopg is installed (see `support.py`).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

_pq = ctypes.CDLL(ctypes.util.find_library("pq") or "libpq.so.5")

_p = ctypes.c_void_p
_s = ctypes.c_char_p
_i = ctypes.c_int

for _name, _restype, _argtypes in (
    ("PQconnectdb", _p, [_s]),
    ("PQstatus", _i, [_p]),
    ("PQerrorMessage", _s, [_p]),
    ("PQfinish", None, [_p]),
    ("PQexec", _p, [_p, _s]),
    ("PQexecParams", _p, [_p, _s, _i, _p, ctypes.POINTER(_s), _p, _p, _i]),
    ("PQresultStatus", _i, [_p]),
    ("PQresultErrorMessage", _s, [_p]),
    ("PQntuples", _i, [_p]),
    ("PQnfields", _i, [_p]),
    ("PQfname", _s, [_p, _i]),
    ("PQftype", ctypes.c_uint, [_p, _i]),
    ("PQgetisnull", _i, [_p, _i, _i]),
    ("PQgetvalue", _s, [_p, _i, _i]),
    ("PQcmdTuples", _s, [_p]),
    ("PQclear", None, [_p]),
):
    _fn = getattr(_pq, _name)
    _fn.restype = _restype
    _fn.argtypes = _argtypes

_COMMAND_OK, _TUPLES_OK = 1, 2
_PLACEHOLDER = re.compile(r"%s")


class DatabaseError(Exception):
    pass


def _timestamp(text: str) -> datetime:
    return datetime.fromisoformat(text)


# PostgreSQL type ids -> Python values, matching psycopg's defaults.
_DECODERS = {
    16: lambda v: v == "t",          # bool
    20: int, 21: int, 23: int,       # int8, int2, int4
    1700: Decimal,                   # numeric
    2950: uuid.UUID,                 # uuid
    1082: date.fromisoformat,        # date
    1114: _timestamp,                # timestamp
    1184: _timestamp,                # timestamptz
    114: json.loads, 3802: json.loads,  # json, jsonb
}


def _encode(value) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, int):
        return str(value).encode()
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, uuid.UUID):
        return str(value).encode()
    if isinstance(value, datetime):
        return value.isoformat().encode()
    raise TypeError(f"Parameter of type {type(value).__name__} is not supported by the test database layer.")


class _Tx:
    def __init__(self, conn):
        self._conn = conn

    def _execute(self, sql: str, params) -> tuple[list[dict], int]:
        params = list(params or ())
        if params:
            counter = iter(range(1, len(params) + 1))
            converted, used = _PLACEHOLDER.subn(lambda _: f"${next(counter)}", sql)
            if used != len(params):
                raise DatabaseError(f"The query has {used} placeholders but {len(params)} parameters.")
            encoded = [_encode(p) for p in params]
            values = (_s * len(encoded))(*encoded)
            result = _pq.PQexecParams(self._conn, converted.encode("utf-8"), len(encoded), None, values, None, None, 0)
        else:
            result = _pq.PQexec(self._conn, sql.encode("utf-8"))
        try:
            status = _pq.PQresultStatus(result)
            if status not in (_COMMAND_OK, _TUPLES_OK):
                raise DatabaseError((_pq.PQresultErrorMessage(result) or b"").decode("utf-8").strip())
            rows: list[dict] = []
            if status == _TUPLES_OK:
                columns = [
                    (_pq.PQfname(result, c).decode(), _DECODERS.get(_pq.PQftype(result, c), str))
                    for c in range(_pq.PQnfields(result))
                ]
                for r in range(_pq.PQntuples(result)):
                    row = {}
                    for c, (name, decode) in enumerate(columns):
                        if _pq.PQgetisnull(result, r, c):
                            row[name] = None
                        else:
                            row[name] = decode(_pq.PQgetvalue(result, r, c).decode("utf-8"))
                    rows.append(row)
            changed = _pq.PQcmdTuples(result) or b""
            return rows, int(changed) if changed else len(rows)
        finally:
            _pq.PQclear(result)

    def one(self, sql, params=()):
        rows, _ = self._execute(sql, params)
        return rows[0] if rows else None

    def all(self, sql, params=()):
        return self._execute(sql, params)[0]

    def run(self, sql, params=()):
        return self._execute(sql, params)[1]


class FallbackDatabase:
    """Opens one connection per transaction; simple and safe across threads."""

    def __init__(self, url: str):
        self._url = url

    def close(self) -> None:
        pass

    @contextmanager
    def transaction(self):
        conn = _pq.PQconnectdb(self._url.encode("utf-8"))
        try:
            if _pq.PQstatus(conn) != 0:
                raise DatabaseError((_pq.PQerrorMessage(conn) or b"").decode("utf-8").strip())
            tx = _Tx(conn)
            tx.run("SET client_min_messages = warning")
            tx.run("SET TIME ZONE 'UTC'")
            tx.run("BEGIN")
            try:
                yield tx
            except BaseException:
                tx.run("ROLLBACK")
                raise
            else:
                tx.run("COMMIT")
        finally:
            _pq.PQfinish(conn)
