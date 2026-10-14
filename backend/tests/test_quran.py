"""Importing, approving and reading the Quran text.

These tests use placeholder words in place of the text (see support.sample_text).
"""

import hashlib
import unittest

from app import quran_import
from app.errors import AppError, Forbidden, NotFound
from app.quran_data import EXPECTED_AYAH_COUNTS, HAFS_AYAH_COUNTS, SURAH_NAMES, SURAHS
from app.quran_import import QuranImportError
from app.schemas import ApproveRiwaya
from app.services import admin, quran

from .support import DatabaseTest, sample_text

GOOD_FILE = sample_text(HAFS_AYAH_COUNTS)


def lines_of(raw: bytes) -> list[str]:
    return raw.decode("utf-8").split("\n")


def rebuilt(lines: list[str]) -> bytes:
    return "\n".join(lines).encode("utf-8")


class SurahTable(unittest.TestCase):
    def test_there_are_114_surahs_numbered_in_order(self):
        self.assertEqual([n for n, *_ in SURAHS], list(range(1, 115)))

    def test_hafs_has_6236_ayat(self):
        self.assertEqual(sum(HAFS_AYAH_COUNTS.values()), 6236)

    def test_well_known_counts(self):
        for surah, count in ((1, 7), (2, 286), (9, 129), (18, 110), (36, 83), (55, 78), (67, 30), (108, 3), (114, 6)):
            self.assertEqual(HAFS_AYAH_COUNTS[surah], count, f"surah {surah}")

    def test_every_surah_has_an_arabic_and_a_latin_name(self):
        for number, (arabic, latin) in SURAH_NAMES.items():
            self.assertTrue(arabic.strip() and latin.strip(), f"surah {number}")
            self.assertTrue(all("\u0600" <= ch <= "\u06ff" or ch == " " for ch in arabic), f"surah {number}")
            self.assertTrue(latin.isascii(), f"surah {number}")
        self.assertEqual(len({ar for ar, _ in SURAH_NAMES.values()}), 114)
        self.assertEqual(len({latin for _, latin in SURAH_NAMES.values()}), 114)

    def test_only_hafs_numbering_is_set_up(self):
        self.assertEqual(list(EXPECTED_AYAH_COUNTS), ["hafs"])


class ParsingASourceFile(unittest.TestCase):
    def refused(self, raw: bytes, riwaya="hafs") -> str:
        with self.assertRaises(QuranImportError) as caught:
            quran_import.parse(raw, riwaya)
        return str(caught.exception)

    def test_a_complete_file_is_accepted(self):
        parsed = quran_import.parse(GOOD_FILE, "hafs")
        self.assertEqual(len(parsed.ayahs), 6236)
        self.assertEqual(parsed.ayahs[0], (1, 1, "placeholder 1:1"))
        self.assertEqual(parsed.ayahs[-1], (114, 6, "placeholder 114:6"))
        self.assertEqual(parsed.notice, "Sample text for automated tests")
        self.assertEqual(parsed.file_sha256, hashlib.sha256(GOOD_FILE).hexdigest())

    def test_text_is_kept_exactly_as_written(self):
        lines = lines_of(GOOD_FILE)
        lines[0] = "1|1|  spaces kept | pipes kept\u200d \u0670  "
        parsed = quran_import.parse(rebuilt(lines), "hafs")
        self.assertEqual(parsed.ayahs[0][2], "  spaces kept | pipes kept\u200d \u0670  ")

    def test_windows_line_endings_and_a_byte_order_mark_are_tolerated(self):
        windows = b"\xef\xbb\xbf" + GOOD_FILE.replace(b"\n", b"\r\n")
        parsed = quran_import.parse(windows, "hafs")
        self.assertEqual(parsed.ayahs[0], (1, 1, "placeholder 1:1"))
        self.assertEqual(len(parsed.ayahs), 6236)

    def test_a_missing_ayah_is_refused(self):
        lines = lines_of(GOOD_FILE)
        del lines[10]  # 2:4
        message = self.refused(rebuilt(lines))
        self.assertIn("Surah 2 has 285 ayat in the file; 286 are expected.", message)
        self.assertIn("Surah 2 is missing ayah 4.", message)

    def test_an_extra_ayah_is_refused(self):
        lines = lines_of(GOOD_FILE)
        lines.insert(7, "1|8|extra")
        self.assertIn("Surah 1 has 8 ayat in the file; 7 are expected.", self.refused(rebuilt(lines)))

    def test_a_repeated_ayah_is_refused(self):
        lines = lines_of(GOOD_FILE)
        lines.insert(1, lines[0])
        self.assertIn("ayah 1:1 appears twice", self.refused(rebuilt(lines)))

    def test_ayat_out_of_order_are_refused(self):
        lines = lines_of(GOOD_FILE)
        lines[0], lines[1] = lines[1], lines[0]
        self.assertIn("Ayah 1:1 comes after ayah 1:2; the file is out of order.", self.refused(rebuilt(lines)))

    def test_surahs_out_of_order_are_refused(self):
        lines = lines_of(GOOD_FILE)
        fatihah, rest = lines[:7], lines[7:]
        message = self.refused(rebuilt(rest[:286] + fatihah + rest[286:]))
        self.assertEqual(message.count("\n"), 1, message)
        self.assertIn("Ayah 1:1 comes after ayah 2:286; the file is out of order.", message)

    def test_an_empty_ayah_or_a_malformed_line_is_refused(self):
        lines = lines_of(GOOD_FILE)
        lines[3] = "1|4|   "
        self.assertIn("ayah 1:4 has no text", self.refused(rebuilt(lines)))
        lines = lines_of(GOOD_FILE)
        lines[3] = "this is not an ayah line"
        self.assertIn("Line 4 is not in the form surah|ayah|text.", self.refused(rebuilt(lines)))

    def test_a_surah_number_outside_the_quran_is_refused(self):
        lines = lines_of(GOOD_FILE)
        lines.insert(6236, "115|1|extra surah")
        self.assertIn("Surah 115 is not one of the 114 surahs.", self.refused(rebuilt(lines)))

    def test_a_file_that_is_not_text_is_refused(self):
        self.assertIn("not UTF-8", self.refused(b"\xff\xfe\x00\x01"))
        self.assertIn("Surah 1 has 0 ayat", self.refused(b""))

    def test_long_lists_of_problems_are_shortened(self):
        message = self.refused(b"1|1|only one ayah\n")
        self.assertIn("and ", message)
        self.assertLess(len(message.splitlines()), 30)

    def test_warsh_is_refused_until_its_numbering_is_set_up(self):
        self.assertIn("has not been set up yet", self.refused(GOOD_FILE, riwaya="warsh"))


class ImportingAndReading(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.admin = self.make_admin()
        self.student = self.make_user()

    def load(self, raw=GOOD_FILE, **options) -> dict:
        parsed = quran_import.parse(raw, "hafs")
        options.setdefault("source", "Test source v1")
        return self.tx(lambda tx: quran_import.load(tx, parsed, **options))

    def approve(self):
        return self.tx(lambda tx: admin.approve_riwaya(
            tx, self.admin, "hafs", ApproveRiwaya(reviewer_name="Shaykh Reviewer")))

    def test_import_stores_every_ayah_and_waits_for_review(self):
        report = self.load()
        self.assertEqual(report["ayah_count"], 6236)
        self.assertEqual(report["status"], "imported")
        self.assertTrue(report["intact"])
        self.assertEqual(report["file_sha256"], hashlib.sha256(GOOD_FILE).hexdigest())
        row = self.tx(lambda tx: tx.one(
            "SELECT text FROM ayahs WHERE riwaya_code = 'hafs' AND surah_number = 114 AND ayah_number = 6"))
        self.assertEqual(row["text"], "placeholder 114:6")

    def test_stored_text_is_identical_to_the_file_including_arabic_marks(self):
        # Vowel marks, joiners and mushaf signs must survive the round trip
        # untouched. (An everyday word plus loose signs, not Quran text.)
        marks = "\u0645\u064e\u062f\u0652\u0631\u064e\u0633\u064e\u0629\u064c \u0671 \u0670\u200d \u06de \u06e9"
        lines = lines_of(GOOD_FILE)
        lines[0] = "1|1|" + marks
        self.load(rebuilt(lines))
        row = self.tx(lambda tx: tx.one(
            "SELECT text FROM ayahs WHERE riwaya_code = 'hafs' AND surah_number = 1 AND ayah_number = 1"))
        self.assertEqual(row["text"], marks)
        self.assertEqual([ord(c) for c in row["text"]], [ord(c) for c in marks])

    def test_unreviewed_text_is_hidden_from_everyone_but_admins(self):
        self.load()
        for reader in (None, self.student):
            for attempt in (
                lambda tx: quran.list_surahs(tx, reader, "hafs"),
                lambda tx: quran.get_surah(tx, reader, "hafs", 1),
            ):
                with self.assertRaises(NotFound) as caught:
                    self.tx(attempt)
                self.assertEqual(caught.exception.code, "riwaya_not_available")
        preview = self.tx(lambda tx: quran.get_surah(tx, self.admin, "hafs", 1))
        self.assertFalse(preview["approved"])
        self.assertEqual(len(preview["ayahs"]), 7)

        listing = self.tx(lambda tx: quran.list_riwayat(tx, None))
        self.assertEqual([(r["code"], r["available"]) for r in listing], [("hafs", False), ("warsh", False)])
        self.assertNotIn("status", listing[0])
        self.assertEqual(self.tx(lambda tx: quran.list_riwayat(tx, self.admin))[0]["status"], "imported")

    def test_approval_makes_the_text_public(self):
        self.load()
        result = self.approve()
        self.assertEqual((result["status"], result["reviewer_name"]), ("approved", "Shaykh Reviewer"))
        listing = self.tx(lambda tx: quran.list_riwayat(tx, None))
        self.assertTrue(listing[0]["available"])
        self.assertEqual(listing[0]["name"]["fr"], "Hafs d'après Asim")

        surahs = self.tx(lambda tx: quran.list_surahs(tx, None, "hafs"))
        self.assertTrue(surahs["approved"])
        self.assertEqual(surahs["text_source"], "Test source v1")
        self.assertEqual(surahs["text_notice"], "Sample text for automated tests")
        self.assertEqual(len(surahs["surahs"]), 114)
        self.assertEqual(surahs["surahs"][1], {
            "number": 2, "name_ar": "البقرة", "name_latin": "Al-Baqarah", "ayah_count": 286})
        self.assertEqual(sum(s["ayah_count"] for s in surahs["surahs"]), 6236)

    def test_only_an_admin_can_approve_and_only_once(self):
        with self.assertRaises(AppError) as caught:
            self.approve()
        self.assertEqual(caught.exception.code, "no_text")
        self.load()
        with self.assertRaises(Forbidden):
            self.tx(lambda tx: admin.approve_riwaya(
                tx, self.student, "hafs", ApproveRiwaya(reviewer_name="Me")))
        self.approve()
        with self.assertRaises(AppError) as caught:
            self.approve()
        self.assertEqual(caught.exception.code, "already_approved")
        with self.assertRaises(NotFound):
            self.tx(lambda tx: admin.approve_riwaya(
                tx, self.admin, "qalun", ApproveRiwaya(reviewer_name="Shaykh Reviewer")))
        log = self.tx(lambda tx: admin.list_actions(tx, self.admin))
        self.assertEqual([(a["action"], a["detail"]) for a in log],
                         [("approve_riwaya", "hafs, reviewed by Shaykh Reviewer")])

    def test_reading_a_surah_and_a_range_of_ayat(self):
        self.load()
        self.approve()
        surah = self.tx(lambda tx: quran.get_surah(tx, None, "hafs", 112))
        self.assertEqual((surah["name_latin"], surah["ayah_count"]), ("Al-Ikhlas", 4))
        self.assertEqual([a["number"] for a in surah["ayahs"]], [1, 2, 3, 4])
        self.assertEqual(surah["ayahs"][2]["text"], "placeholder 112:3")

        part = self.tx(lambda tx: quran.get_surah(tx, self.student, "hafs", 2, 255, 257))
        self.assertEqual([a["number"] for a in part["ayahs"]], [255, 256, 257])
        self.assertEqual(part["ayah_count"], 286)
        tail = self.tx(lambda tx: quran.get_surah(tx, None, "hafs", 2, 285))
        self.assertEqual([a["number"] for a in tail["ayahs"]], [285, 286])

    def test_bad_surah_numbers_and_ranges(self):
        self.load()
        self.approve()
        for number in (0, 115):
            with self.assertRaises(NotFound):
                self.tx(lambda tx: quran.get_surah(tx, None, "hafs", number))
        for first, last in ((0, 3), (5, 2), (8, 9)):
            with self.assertRaises(AppError) as caught:
                self.tx(lambda tx: quran.get_surah(tx, None, "hafs", 1, first, last))
            self.assertEqual(caught.exception.code, "bad_range")
        with self.assertRaises(NotFound):
            self.tx(lambda tx: quran.get_surah(tx, None, "nope", 1))

    def test_a_second_import_needs_replace_and_a_new_review(self):
        self.load()
        self.approve()
        with self.assertRaises(AppError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "text_exists")
        self.assertTrue(self.tx(lambda tx: quran.list_riwayat(tx, None))[0]["available"])

        lines = lines_of(GOOD_FILE)
        lines[0] = "1|1|corrected placeholder"
        report = self.load(rebuilt(lines), source="Test source v2", replace=True)
        self.assertEqual((report["status"], report["source"], report["ayah_count"]),
                         ("imported", "Test source v2", 6236))
        self.assertFalse(self.tx(lambda tx: quran.list_riwayat(tx, None))[0]["available"])
        row = self.tx(lambda tx: tx.one(
            "SELECT reviewer_name, approved_at FROM riwayat WHERE code = 'hafs'"))
        self.assertEqual((row["reviewer_name"], row["approved_at"]), (None, None))
        self.assertEqual(self.tx(lambda tx: quran.get_surah(tx, self.admin, "hafs", 1))["ayahs"][0]["text"],
                         "corrected placeholder")

    def test_a_failed_import_leaves_nothing_behind(self):
        parsed = quran_import.parse(GOOD_FILE, "hafs")

        def load_then_crash(tx):
            quran_import.load(tx, parsed, source="x")
            tx.run("SELECT 1 / 0")

        with self.assertRaises(Exception):
            self.tx(load_then_crash)
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT count(*) AS n FROM ayahs"))["n"], 0)
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT status FROM riwayat WHERE code = 'hafs'"))["status"], "empty")

    def test_a_text_is_stored_under_the_riwaya_it_was_checked_for(self):
        self.load()
        counts = self.tx(lambda tx: tx.all("SELECT riwaya_code, count(*) AS n FROM ayahs GROUP BY riwaya_code"))
        self.assertEqual(counts, [{"riwaya_code": "hafs", "n": 6236}])

    def test_verify_detects_any_change_to_the_stored_text(self):
        self.load()
        self.assertTrue(self.tx(lambda tx: quran_import.verify(tx, "hafs"))["intact"])

        def tamper(statement):
            self.tx(lambda tx: (tx.run("SET LOCAL tajweed.quran_import = 'on'"), tx.run(statement)))

        tamper("UPDATE ayahs SET text = text || ' ' WHERE surah_number = 50 AND ayah_number = 1")
        self.assertFalse(self.tx(lambda tx: quran_import.verify(tx, "hafs"))["intact"])
        self.load(replace=True)
        tamper("DELETE FROM ayahs WHERE surah_number = 114 AND ayah_number = 6")
        self.assertFalse(self.tx(lambda tx: quran_import.verify(tx, "hafs"))["intact"])

        with self.assertRaises(AppError) as caught:
            self.tx(lambda tx: quran_import.verify(tx, "warsh"))
        self.assertEqual(caught.exception.code, "no_text")
