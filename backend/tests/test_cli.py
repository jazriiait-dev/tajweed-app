"""The maintenance commands, run the way an operator would run them."""

import contextlib
import io
import os
import tempfile
from pathlib import Path

from app import cli
from app.quran_data import HAFS_AYAH_COUNTS
from app.schemas import Login
from app.services import accounts

from .support import DatabaseTest, sample_text


class Commands(DatabaseTest):
    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(list(argv), settings=self.settings, db=self.db, out=out)
        return code, out.getvalue(), err.getvalue()

    def test_migrate_reports_when_nothing_is_pending(self):
        code, out, _ = self.run_cli("migrate")
        self.assertEqual((code, out.strip()), (0, "The database is already up to date."))

    def test_create_admin(self):
        os.environ["TEST_ADMIN_PASSWORD"] = "owner password"
        try:
            code, out, _ = self.run_cli("create-admin", "--email", "Owner@Example.com", "--name", "Owner",
                                        "--password-env", "TEST_ADMIN_PASSWORD")
            self.assertEqual(code, 0)
            self.assertIn("owner@example.com", out)
            session = self.tx(lambda tx: accounts.login(
                tx, self.settings, Login(email="owner@example.com", password="owner password")))
            self.assertEqual(session["user"]["roles"], ["admin"])

            code, _, err = self.run_cli("create-admin", "--email", "owner@example.com", "--name", "Owner",
                                        "--password-env", "TEST_ADMIN_PASSWORD")
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
        finally:
            del os.environ["TEST_ADMIN_PASSWORD"]

        code, _, err = self.run_cli("create-admin", "--email", "a@example.com", "--name", "A",
                                    "--password-env", "NO_SUCH_VARIABLE")
        self.assertEqual(code, 1)
        self.assertIn("NO_SUCH_VARIABLE", err)

    def test_import_and_verify_the_quran_text(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.txt"
            good.write_bytes(sample_text(HAFS_AYAH_COUNTS))
            bad = Path(folder) / "bad.txt"
            bad.write_bytes(sample_text({**HAFS_AYAH_COUNTS, 2: 285}))

            code, _, err = self.run_cli("import-quran", "--riwaya", "hafs", "--file", str(bad), "--source", "x")
            self.assertEqual(code, 1)
            self.assertIn("Surah 2 has 285 ayat in the file; 286 are expected.", err)

            code, _, err = self.run_cli("verify-quran", "--riwaya", "hafs")
            self.assertEqual(code, 1)
            self.assertIn("No text has been imported", err)

            code, out, _ = self.run_cli("import-quran", "--riwaya", "hafs", "--file", str(good),
                                        "--source", "Test source")
            self.assertEqual(code, 0)
            self.assertIn("Imported 6236 ayat", out)
            self.assertIn("waiting for a qualified reviewer", out)

            code, _, err = self.run_cli("import-quran", "--riwaya", "hafs", "--file", str(good), "--source", "x")
            self.assertEqual(code, 1)
            self.assertIn("--replace", err)
            code, _, _ = self.run_cli("import-quran", "--riwaya", "hafs", "--file", str(good),
                                      "--source", "x", "--replace")
            self.assertEqual(code, 0)

            code, out, _ = self.run_cli("verify-quran", "--riwaya", "hafs")
            self.assertEqual(code, 0)
            self.assertIn("6236 ayat, unchanged since import", out)

            self.tx(lambda tx: (tx.run("SET LOCAL tajweed.quran_import = 'on'"),
                                tx.run("UPDATE ayahs SET text = 'changed' WHERE surah_number = 1 AND ayah_number = 1")))
            code, _, err = self.run_cli("verify-quran", "--riwaya", "hafs")
            self.assertEqual(code, 2)
            self.assertIn("does not match", err)

            code, _, err = self.run_cli("import-quran", "--riwaya", "hafs", "--file",
                                        str(Path(folder) / "missing.txt"), "--source", "x")
            self.assertEqual(code, 1)
            self.assertIn("does not exist", err)
