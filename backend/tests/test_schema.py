"""The rules the database itself enforces, whatever the application code does."""

from app.migrate import apply_migrations

from .support import DatabaseTest


class SchemaRules(DatabaseTest):
    def assertRefused(self, sql, params=(), setup=()):
        def work(tx):
            for statement in setup:
                tx.run(statement)
            tx.run(sql, params)
        with self.assertRaises(Exception) as caught:
            self.tx(work)
        return str(caught.exception)

    def test_migrations_are_applied_once(self):
        self.assertEqual(apply_migrations(self.db), [])
        versions = self.tx(lambda tx: tx.all("SELECT version FROM schema_migrations"))
        self.assertEqual([v["version"] for v in versions], ["001_foundations"])

    def test_two_riwayat_are_set_up_and_empty(self):
        rows = self.tx(lambda tx: tx.all("SELECT code, status FROM riwayat ORDER BY sort_order"))
        self.assertEqual(rows, [{"code": "hafs", "status": "empty"}, {"code": "warsh", "status": "empty"}])

    def test_an_adult_account_needs_email_and_password(self):
        self.assertRefused("INSERT INTO users (display_name) VALUES ('No login')")
        self.assertRefused("INSERT INTO users (display_name, email) VALUES ('Half', 'a@example.com')")

    def test_a_child_profile_cannot_have_a_login(self):
        self.assertRefused(
            "INSERT INTO users (display_name, is_child, email, password_hash) "
            "VALUES ('Child', true, 'c@example.com', 'x')"
        )

    def test_email_must_be_lowercase_and_unique(self):
        self.assertRefused(
            "INSERT INTO users (display_name, email, password_hash) VALUES ('A', 'Mixed@Example.com', 'x')"
        )
        self.make_user(email="same@example.com")
        self.assertRefused(
            "INSERT INTO users (display_name, email, password_hash) VALUES ('B', 'same@example.com', 'x')"
        )

    def test_only_supported_languages(self):
        self.assertRefused(
            "INSERT INTO users (display_name, email, password_hash, language) "
            "VALUES ('A', 'a@example.com', 'x', 'de')"
        )

    def test_a_child_can_only_be_a_student(self):
        child = self.tx(lambda tx: tx.one(
            "INSERT INTO users (display_name, is_child) VALUES ('Child', true) RETURNING id"
        ))
        self.tx(lambda tx: tx.run(
            "INSERT INTO user_roles (user_id, role) VALUES (%s, 'student')", [child["id"]]
        ))
        for role in ("parent", "teacher", "admin"):
            message = self.assertRefused(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, %s)", [child["id"], role]
            )
            self.assertIn("child profile", message)

    def test_unknown_roles_are_refused(self):
        user = self.make_user()
        self.assertRefused(
            "INSERT INTO user_roles (user_id, role) VALUES (%s, 'owner')", [user.user_id]
        )

    def test_quran_text_cannot_be_written_outside_an_import(self):
        message = self.assertRefused(
            "INSERT INTO ayahs (riwaya_code, surah_number, ayah_number, text) VALUES ('hafs', 1, 1, 'x')"
        )
        self.assertIn("read-only", message)

        unlock = "SET LOCAL tajweed.quran_import = 'on'"
        self.tx(lambda tx: (tx.run(unlock), tx.run(
            "INSERT INTO ayahs (riwaya_code, surah_number, ayah_number, text) VALUES ('hafs', 1, 1, 'x')"
        )))
        # The unlock lasted for that transaction only.
        for statement in (
            "UPDATE ayahs SET text = 'changed'",
            "DELETE FROM ayahs",
            "TRUNCATE ayahs",
        ):
            self.assertIn("read-only", self.assertRefused(statement))
        stored = self.tx(lambda tx: tx.one("SELECT text FROM ayahs"))
        self.assertEqual(stored["text"], "x")

    def test_ayah_numbers_must_be_in_range(self):
        unlock = ("SET LOCAL tajweed.quran_import = 'on'",)
        insert = "INSERT INTO ayahs (riwaya_code, surah_number, ayah_number, text) VALUES ('hafs', %s, %s, %s)"
        self.assertRefused(insert, [115, 1, "x"], setup=unlock)
        self.assertRefused(insert, [0, 1, "x"], setup=unlock)
        self.assertRefused(insert, [1, 0, "x"], setup=unlock)
        self.assertRefused(insert, [1, 1, ""], setup=unlock)

    def test_a_riwaya_cannot_be_marked_approved_without_a_review(self):
        self.assertRefused("UPDATE riwayat SET status = 'approved' WHERE code = 'hafs'")
        self.assertRefused("UPDATE riwayat SET status = 'imported' WHERE code = 'hafs'")
