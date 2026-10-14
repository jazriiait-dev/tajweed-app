"""Load the Quran text for a riwaya from a verified source file.

The file format is one ayah per line, as published by the Tanzil project
("text with aya numbers"):

    1|1|<text of the ayah>
    1|2|<text of the ayah>
    ...
    # comment lines, such as the publisher's copyright notice

Rules this module follows:

* The text is stored exactly as it is in the file. Nothing is trimmed,
  normalised or corrected.
* A file is refused unless every surah is present, in order, with exactly the
  expected number of ayat.
* Two fingerprints are kept: one of the file, and one of the stored text, so
  the database can be re-checked at any time with `verify`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .db import Tx
from .errors import AppError
from .quran_data import EXPECTED_AYAH_COUNTS

_MAX_PROBLEMS_SHOWN = 20
_BATCH = 200


class QuranImportError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        shown = problems[:_MAX_PROBLEMS_SHOWN]
        more = len(problems) - len(shown)
        text = "\n".join(f"- {p}" for p in shown)
        if more > 0:
            text += f"\n- and {more} more"
        super().__init__(f"The file was refused:\n{text}")


@dataclass(frozen=True)
class ParsedText:
    riwaya: str                        # the riwaya this file was checked against
    ayahs: list[tuple[int, int, str]]  # (surah, ayah, text)
    notice: str                        # the publisher's comment block
    file_sha256: str


def content_fingerprint(ayahs) -> str:
    """A fingerprint of the text itself, independent of the file it came from."""
    digest = hashlib.sha256()
    for surah, ayah, text in ayahs:
        digest.update(f"{surah}|{ayah}|{text}\n".encode("utf-8"))
    return digest.hexdigest()


def parse(raw: bytes, riwaya: str) -> ParsedText:
    """Read and check a source file. Raises QuranImportError if anything is off."""
    expected = EXPECTED_AYAH_COUNTS.get(riwaya)
    if expected is None:
        raise QuranImportError(
            [f"The ayah numbering for '{riwaya}' has not been set up yet, so its text cannot be checked."]
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise QuranImportError(["The file is not UTF-8 text."]) from None

    problems: list[str] = []
    ayahs: list[tuple[int, int, str]] = []
    notice_lines: list[str] = []
    seen: set[tuple[int, int]] = set()

    for line_number, line in enumerate(text.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            notice_lines.append(line.lstrip()[1:].strip())
            continue
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            problems.append(f"Line {line_number} is not in the form surah|ayah|text.")
            continue
        surah, ayah, body = int(parts[0]), int(parts[1]), parts[2]
        if not body.strip():
            problems.append(f"Line {line_number}: ayah {surah}:{ayah} has no text.")
            continue
        if (surah, ayah) in seen:
            problems.append(f"Line {line_number}: ayah {surah}:{ayah} appears twice.")
            continue
        seen.add((surah, ayah))
        ayahs.append((surah, ayah, body))

    # Every ayah belongs to a real surah, and each surah has ayat 1..n with n
    # as expected.
    found: dict[int, set[int]] = {}
    for surah, ayah, _ in ayahs:
        found.setdefault(surah, set()).add(ayah)
    for surah in sorted(set(found) - set(expected)):
        problems.append(f"Surah {surah} is not one of the 114 surahs.")
    for surah, want in sorted(expected.items()):
        have = found.get(surah, set())
        if len(have) != want:
            problems.append(f"Surah {surah} has {len(have)} ayat in the file; {want} are expected.")
        missing = sorted(set(range(1, want + 1)) - have)
        if missing and have:
            listed = ", ".join(str(n) for n in missing[:5]) + (" ..." if len(missing) > 5 else "")
            problems.append(f"Surah {surah} is missing ayah {listed}.")

    # The file runs from 1:1 to 114:6 in order.
    for previous, current in zip(ayahs, ayahs[1:]):
        if current[:2] < previous[:2]:
            problems.append(
                f"Ayah {current[0]}:{current[1]} comes after ayah {previous[0]}:{previous[1]}; "
                "the file is out of order."
            )
            break

    if problems:
        raise QuranImportError(problems)

    return ParsedText(
        riwaya=riwaya,
        ayahs=ayahs,
        notice="\n".join(notice_lines).strip(),
        file_sha256=hashlib.sha256(raw).hexdigest(),
    )


def load(tx: Tx, parsed: ParsedText, *, source: str, replace: bool = False) -> dict:
    """Store a parsed text. The riwaya then waits for a reviewer's approval."""
    riwaya = parsed.riwaya
    current = tx.one("SELECT status FROM riwayat WHERE code = %s FOR UPDATE", [riwaya])
    if current is None:
        raise AppError("riwaya_not_found", f"The riwaya '{riwaya}' is not set up.")
    if current["status"] != "empty" and not replace:
        raise AppError(
            "text_exists",
            f"'{riwaya}' already has a text. Run the import again with --replace to overwrite it; "
            "it will then need approving again.",
        )

    # Unlocks the read-only guard on the ayahs table for this transaction only.
    tx.run("SET LOCAL tajweed.quran_import = 'on'")
    tx.run("DELETE FROM ayahs WHERE riwaya_code = %s", [riwaya])
    for start in range(0, len(parsed.ayahs), _BATCH):
        batch = parsed.ayahs[start:start + _BATCH]
        values = ", ".join(["(%s, %s::smallint, %s::smallint, %s)"] * len(batch))
        params: list = []
        for surah, ayah, text in batch:
            params += [riwaya, surah, ayah, text]
        tx.run(
            f"INSERT INTO ayahs (riwaya_code, surah_number, ayah_number, text) VALUES {values}",
            params,
        )
    tx.run("SET LOCAL tajweed.quran_import = 'off'")

    tx.run(
        """
        UPDATE riwayat
        SET status = 'imported', ayah_count = %s::int, text_source = %s, text_notice = %s,
            file_sha256 = %s, content_sha256 = %s, imported_at = now(),
            reviewer_name = NULL, approved_by = NULL, approved_at = NULL
        WHERE code = %s
        """,
        [len(parsed.ayahs), source, parsed.notice, parsed.file_sha256,
         content_fingerprint(parsed.ayahs), riwaya],
    )
    return verify(tx, riwaya)


def verify(tx: Tx, riwaya: str) -> dict:
    """Re-read the stored text and compare it with the fingerprint taken at import."""
    info = tx.one(
        "SELECT status, ayah_count, content_sha256, file_sha256, text_source FROM riwayat WHERE code = %s",
        [riwaya],
    )
    if info is None:
        raise AppError("riwaya_not_found", f"The riwaya '{riwaya}' is not set up.")
    if info["status"] == "empty":
        raise AppError("no_text", f"No text has been imported for '{riwaya}'.")
    rows = tx.all(
        """
        SELECT surah_number, ayah_number, text FROM ayahs
        WHERE riwaya_code = %s
        ORDER BY surah_number, ayah_number
        """,
        [riwaya],
    )
    actual = content_fingerprint((r["surah_number"], r["ayah_number"], r["text"]) for r in rows)
    return {
        "riwaya": riwaya,
        "status": info["status"],
        "source": info["text_source"],
        "ayah_count": len(rows),
        "file_sha256": info["file_sha256"],
        "content_sha256": actual,
        "intact": actual == info["content_sha256"] and len(rows) == info["ayah_count"],
    }
