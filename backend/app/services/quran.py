"""Reading the Quran text. Open to everyone, signed in or not."""

from __future__ import annotations

from ..actor import Actor
from ..db import Tx
from ..errors import AppError, NotFound
from ..quran_data import SURAH_NAMES


def _is_admin(actor: Actor | None) -> bool:
    return actor is not None and actor.has("admin")


def list_riwayat(tx: Tx, actor: Actor | None) -> list[dict]:
    rows = tx.all(
        """
        SELECT code, name_ar, name_en, name_fr, status, ayah_count, text_source,
               imported_at, reviewer_name, approved_at
        FROM riwayat
        ORDER BY sort_order
        """
    )
    result = []
    for row in rows:
        item = {
            "code": row["code"],
            "name": {"ar": row["name_ar"], "en": row["name_en"], "fr": row["name_fr"]},
            "available": row["status"] == "approved",
        }
        if _is_admin(actor):
            item.update(
                status=row["status"], ayah_count=row["ayah_count"], text_source=row["text_source"],
                imported_at=row["imported_at"], reviewer_name=row["reviewer_name"],
                approved_at=row["approved_at"],
            )
        result.append(item)
    return result


def _readable_riwaya(tx: Tx, actor: Actor | None, code: str) -> dict:
    """Return the riwaya if this person may read its text.

    Everyone can read an approved text. Admins can also read an imported
    text that is still waiting for approval, so it can be checked.
    """
    row = tx.one(
        "SELECT code, status, text_source, text_notice FROM riwayat WHERE code = %s", [code]
    )
    readable = row is not None and (
        row["status"] == "approved" or (row["status"] == "imported" and _is_admin(actor))
    )
    if not readable:
        raise NotFound("riwaya_not_available", "This riwaya is not available yet.")
    return row


def list_surahs(tx: Tx, actor: Actor | None, code: str) -> dict:
    riwaya = _readable_riwaya(tx, actor, code)
    counts = tx.all(
        """
        SELECT surah_number, count(*) AS ayah_count
        FROM ayahs WHERE riwaya_code = %s
        GROUP BY surah_number ORDER BY surah_number
        """,
        [code],
    )
    return {
        "riwaya": code,
        "approved": riwaya["status"] == "approved",
        # Shown in the app, as the publisher of the text asks.
        "text_source": riwaya["text_source"],
        "text_notice": riwaya["text_notice"],
        "surahs": [
            {
                "number": row["surah_number"],
                "name_ar": SURAH_NAMES[row["surah_number"]][0],
                "name_latin": SURAH_NAMES[row["surah_number"]][1],
                "ayah_count": row["ayah_count"],
            }
            for row in counts
        ],
    }


def get_surah(tx: Tx, actor: Actor | None, code: str, number: int,
              first: int | None = None, last: int | None = None) -> dict:
    riwaya = _readable_riwaya(tx, actor, code)
    if number not in SURAH_NAMES:
        raise NotFound("surah_not_found", "Surah numbers run from 1 to 114.")
    first = 1 if first is None else first
    if first < 1 or (last is not None and last < first):
        raise AppError("bad_range", "The ayah range is not valid.")

    total = tx.one(
        "SELECT count(*) AS n FROM ayahs WHERE riwaya_code = %s AND surah_number = %s::smallint",
        [code, number],
    )["n"]
    rows = tx.all(
        """
        SELECT ayah_number, text FROM ayahs
        WHERE riwaya_code = %s AND surah_number = %s::smallint
          AND ayah_number >= %s::int AND ayah_number <= %s::int
        ORDER BY ayah_number
        """,
        [code, number, first, total if last is None else last],
    )
    if not rows:
        raise AppError("bad_range", "The ayah range is not valid.")
    return {
        "riwaya": code,
        "approved": riwaya["status"] == "approved",
        "number": number,
        "name_ar": SURAH_NAMES[number][0],
        "name_latin": SURAH_NAMES[number][1],
        "ayah_count": total,
        "ayahs": [{"number": row["ayah_number"], "text": row["text"]} for row in rows],
    }
