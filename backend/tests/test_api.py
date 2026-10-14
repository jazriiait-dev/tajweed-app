"""The API over HTTP, end to end: request in, JSON out, real database."""

import re

from starlette.testclient import TestClient

from app import quran_import
from app.api import create_app
from app.config import Settings
from app.quran_data import HAFS_AYAH_COUNTS

from .support import DatabaseTest, sample_text

SIGNUP = {
    "email": "amina@example.com", "password": "correct horse", "display_name": "Amina",
    "language": "fr", "timezone": "Africa/Casablanca", "account_type": "student", "confirms_adult": True,
}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class Api(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.http = TestClient(create_app(self.settings, self.db))

    def sign_up(self, **overrides) -> dict:
        response = self.http.post("/api/v1/auth/register", json={**SIGNUP, **overrides})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def admin_token(self) -> str:
        self.make_admin()
        response = self.http.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct horse"})
        return response.json()["access_token"]

    def assertError(self, response, status: int, code: str):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["error"]["code"], code, response.text)

    # --- basics -----------------------------------------------------------------

    def test_health(self):
        response = self.http.get("/health")
        self.assertEqual((response.status_code, response.json()), (200, {"status": "ok"}))

    def test_unknown_paths_and_methods_answer_in_json(self):
        self.assertError(self.http.get("/api/v1/nope"), 404, "not_found")
        self.assertError(self.http.delete("/api/v1/me"), 405, "method_not_allowed")

    def test_sign_up_then_read_own_profile(self):
        session = self.sign_up()
        self.assertEqual(session["user"]["roles"], ["student"])
        me = self.http.get("/api/v1/me", headers=bearer(session["access_token"]))
        self.assertEqual(me.status_code, 200)
        body = me.json()
        self.assertEqual((body["email"], body["language"], body["opened_by_parent"]),
                         ("amina@example.com", "fr", None))
        # Dates are sent as UTC in ISO 8601.
        self.assertRegex(body["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
        self.assertNotIn("password_hash", body)

    def test_arabic_text_is_sent_as_is(self):
        session = self.sign_up(display_name="أمينة")
        raw = self.http.get("/api/v1/me", headers=bearer(session["access_token"])).content
        self.assertIn("أمينة".encode("utf-8"), raw)

    def test_invalid_input_names_the_fields(self):
        response = self.http.post("/api/v1/auth/register", json={**SIGNUP, "email": "nope", "password": "x"})
        self.assertError(response, 422, "invalid_input")
        fields = {problem["field"] for problem in response.json()["error"]["details"]}
        self.assertEqual(fields, {"email", "password"})
        self.assertError(self.http.post("/api/v1/auth/register", json={**SIGNUP, "role": "admin"}),
                         422, "invalid_input")
        self.assertError(self.http.post("/api/v1/auth/register", content=b"not json"), 422, "invalid_input")
        self.assertError(self.http.post("/api/v1/auth/login", content=b"x" * 70_000), 413, "too_large")

    def test_duplicate_sign_up(self):
        self.sign_up()
        self.assertError(self.http.post("/api/v1/auth/register", json=SIGNUP), 409, "email_taken")

    # --- signing in ---------------------------------------------------------------

    def test_private_routes_need_a_valid_token(self):
        for path in ("/api/v1/me", "/api/v1/children", "/api/v1/admin/users"):
            self.assertError(self.http.get(path), 401, "not_signed_in")
        self.assertError(self.http.get("/api/v1/me", headers=bearer("garbage")), 401, "invalid_token")
        self.assertError(self.http.get("/api/v1/me", headers={"Authorization": "Basic abc"}), 401, "not_signed_in")

    def test_expired_tokens_are_reported_so_the_app_can_refresh(self):
        self.sign_up()
        expired = Settings(**{**self.settings.__dict__, "access_token_minutes": -1})
        short_lived = TestClient(create_app(expired, self.db))
        session = short_lived.post(
            "/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]}).json()
        self.assertError(self.http.get("/api/v1/me", headers=bearer(session["access_token"])), 401, "session_expired")
        renewed = self.http.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
        self.assertEqual(renewed.status_code, 200)
        self.assertEqual(self.http.get("/api/v1/me", headers=bearer(renewed.json()["access_token"])).status_code, 200)

    def test_sign_in_failures_and_lockout_survive_the_error(self):
        self.sign_up()
        wrong = {"email": SIGNUP["email"], "password": "wrong password"}
        for _ in range(self.settings.max_failed_logins):
            self.assertError(self.http.post("/api/v1/auth/login", json=wrong), 401, "wrong_credentials")
        right = {"email": SIGNUP["email"], "password": SIGNUP["password"]}
        self.assertError(self.http.post("/api/v1/auth/login", json=right), 429, "account_locked")

    def test_sign_out(self):
        session = self.sign_up()
        token = {"refresh_token": session["refresh_token"]}
        response = self.http.post("/api/v1/auth/logout", json=token)
        self.assertEqual((response.status_code, response.content), (204, b""))
        self.assertError(self.http.post("/api/v1/auth/refresh", json=token), 401, "session_ended")

    def test_profile_and_password_changes(self):
        session = self.sign_up()
        auth = bearer(session["access_token"])
        updated = self.http.patch("/api/v1/me", headers=auth, json={"language": "ar"})
        self.assertEqual(updated.json()["language"], "ar")
        self.assertError(self.http.patch("/api/v1/me", headers=auth, json={"language": "de"}), 422, "invalid_input")
        self.assertError(self.http.patch("/api/v1/me", headers=auth, json={"email": "new@example.com"}),
                         422, "invalid_input")
        changed = self.http.post("/api/v1/me/password", headers=auth,
                                 json={"current_password": "correct horse", "new_password": "battery staple"})
        self.assertEqual(changed.status_code, 200)
        self.assertIn("refresh_token", changed.json())
        self.assertError(self.http.post("/api/v1/me/password", headers=auth,
                                        json={"current_password": "correct horse", "new_password": "another one"}),
                         403, "wrong_password")

    # --- parents and children -------------------------------------------------------

    def test_parent_and_child_flow(self):
        parent = bearer(self.sign_up(account_type="parent")["access_token"])
        created = self.http.post("/api/v1/children", headers=parent,
                                 json={"display_name": "Yusuf", "guardian_consent": True})
        self.assertEqual(created.status_code, 201, created.text)
        child_id = created.json()["id"]
        self.assertEqual([c["id"] for c in self.http.get("/api/v1/children", headers=parent).json()], [child_id])
        self.assertError(self.http.post("/api/v1/children", headers=parent,
                                        json={"display_name": "Maryam", "guardian_consent": False}),
                         400, "consent_required")

        renamed = self.http.patch(f"/api/v1/children/{child_id}", headers=parent, json={"display_name": "Yusuf A."})
        self.assertEqual(renamed.json()["display_name"], "Yusuf A.")

        opened = self.http.post(f"/api/v1/children/{child_id}/session", headers=parent)
        self.assertEqual(opened.status_code, 200, opened.text)
        child = bearer(opened.json()["access_token"])
        me = self.http.get("/api/v1/me", headers=child).json()
        self.assertEqual((me["id"], me["is_child"], me["roles"]), (child_id, True, ["student"]))
        self.assertIsNotNone(me["opened_by_parent"])

        # A child session is limited to what a student can do.
        self.assertError(self.http.get("/api/v1/children", headers=child), 403, "managed_by_parent")
        self.assertError(self.http.patch("/api/v1/me", headers=child, json={"display_name": "Me"}),
                         403, "managed_by_parent")
        self.assertError(self.http.get("/api/v1/admin/users", headers=child), 403, "not_allowed")

    def test_students_cannot_create_children_or_reach_others(self):
        student = bearer(self.sign_up()["access_token"])
        self.assertError(self.http.post("/api/v1/children", headers=student,
                                        json={"display_name": "Yusuf", "guardian_consent": True}),
                         403, "not_allowed")
        parent = bearer(self.sign_up(email="parent@example.com", account_type="parent")["access_token"])
        child_id = self.http.post("/api/v1/children", headers=parent,
                                  json={"display_name": "Yusuf", "guardian_consent": True}).json()["id"]
        other = bearer(self.sign_up(email="other@example.com", account_type="parent")["access_token"])
        self.assertError(self.http.post(f"/api/v1/children/{child_id}/session", headers=other), 404, "child_not_found")
        self.assertError(self.http.post("/api/v1/children/not-an-id/session", headers=other), 404, "child_not_found")

    def test_a_student_can_also_become_a_parent(self):
        auth = bearer(self.sign_up()["access_token"])
        response = self.http.post("/api/v1/me/roles", headers=auth, json={"role": "parent"})
        self.assertEqual(response.json()["roles"], ["parent", "student"])
        self.assertError(self.http.post("/api/v1/me/roles", headers=auth, json={"role": "admin"}), 422, "invalid_input")

    # --- staff ----------------------------------------------------------------------

    def test_admin_routes(self):
        student = bearer(self.sign_up()["access_token"])
        admin = bearer(self.admin_token())
        for path in ("/api/v1/admin/users", "/api/v1/admin/teachers", "/api/v1/admin/actions"):
            self.assertError(self.http.get(path, headers=student), 403, "not_allowed")
            self.assertEqual(self.http.get(path, headers=admin).status_code, 200)

        teacher = self.http.post("/api/v1/admin/teachers", headers=admin, json={
            "email": "ustadha@example.com", "password": "teacher pass", "display_name": "Ustadha Salma",
            "gender": "female", "riwayat": ["hafs"], "languages": ["ar", "en"],
        })
        self.assertEqual(teacher.status_code, 201, teacher.text)
        teacher_id = teacher.json()["id"]
        verified = self.http.patch(f"/api/v1/admin/teachers/{teacher_id}", headers=admin, json={"verified": True})
        self.assertTrue(verified.json()["is_verified"])
        self.assertError(self.http.post("/api/v1/admin/teachers", headers=student, json={
            "email": "x@example.com", "password": "teacher pass", "display_name": "X",
            "gender": "male", "riwayat": ["hafs"], "languages": ["ar"]}), 403, "not_allowed")

        users = self.http.get("/api/v1/admin/users?role=teacher&limit=10", headers=admin).json()
        self.assertEqual((users["total"], users["items"][0]["email"]), (1, "ustadha@example.com"))
        self.assertError(self.http.get("/api/v1/admin/users?limit=many", headers=admin), 422, "invalid_input")

        student_id = self.http.get("/api/v1/me", headers=student).json()["id"]
        disabled = self.http.post(f"/api/v1/admin/users/{student_id}/active", headers=admin, json={"active": False})
        self.assertFalse(disabled.json()["is_active"])
        self.assertError(self.http.get("/api/v1/me", headers=student), 403, "account_disabled")

        reset = self.http.post(f"/api/v1/admin/users/{teacher_id}/password", headers=admin,
                               json={"new_password": "new teacher pass"})
        self.assertEqual(reset.status_code, 204)
        self.assertEqual(self.http.post("/api/v1/auth/login", json={
            "email": "ustadha@example.com", "password": "new teacher pass"}).status_code, 200)

        actions = [a["action"] for a in self.http.get("/api/v1/admin/actions", headers=admin).json()]
        self.assertEqual(sorted(actions), ["create_teacher", "disable_account", "set_password", "verify_teacher"])

    # --- reading the Quran ------------------------------------------------------------

    def test_quran_reader_from_import_to_public(self):
        listing = self.http.get("/api/v1/riwayat").json()
        self.assertEqual([(r["code"], r["available"]) for r in listing], [("hafs", False), ("warsh", False)])
        self.assertError(self.http.get("/api/v1/quran/hafs/surahs"), 404, "riwaya_not_available")

        parsed = quran_import.parse(sample_text(HAFS_AYAH_COUNTS), "hafs")
        self.tx(lambda tx: quran_import.load(tx, parsed, source="Test source"))
        admin = bearer(self.admin_token())
        self.assertError(self.http.get("/api/v1/quran/hafs/surahs/1"), 404, "riwaya_not_available")
        self.assertEqual(self.http.get("/api/v1/quran/hafs/surahs/1", headers=admin).status_code, 200)

        student = bearer(self.sign_up()["access_token"])
        self.assertError(self.http.post("/api/v1/admin/riwayat/hafs/approve", headers=student,
                                        json={"reviewer_name": "Me"}), 403, "not_allowed")
        approved = self.http.post("/api/v1/admin/riwayat/hafs/approve", headers=admin,
                                  json={"reviewer_name": "Shaykh Reviewer"})
        self.assertEqual(approved.json()["status"], "approved")

        # Now open to everyone, with or without an account.
        surahs = self.http.get("/api/v1/quran/hafs/surahs").json()
        self.assertEqual(len(surahs["surahs"]), 114)
        self.assertEqual(surahs["surahs"][0]["name_ar"], "الفاتحة")
        surah = self.http.get("/api/v1/quran/hafs/surahs/2?from=255&to=256", headers=student).json()
        self.assertEqual([a["number"] for a in surah["ayahs"]], [255, 256])
        self.assertEqual(self.http.get("/api/v1/riwayat").json()[0]["available"], True)

        self.assertError(self.http.get("/api/v1/quran/hafs/surahs/115"), 404, "surah_not_found")
        self.assertError(self.http.get("/api/v1/quran/hafs/surahs/abc"), 404, "not_found")
        self.assertError(self.http.get("/api/v1/quran/hafs/surahs/1?from=9"), 400, "bad_range")
        self.assertError(self.http.get("/api/v1/quran/hafs/surahs/1?from=x"), 422, "invalid_input")
        self.assertError(self.http.get("/api/v1/quran/warsh/surahs"), 404, "riwaya_not_available")

    def test_cross_origin_requests_only_from_listed_sites(self):
        allowed = Settings(**{**self.settings.__dict__, "cors_origins": ("https://app.example.com",)})
        client = TestClient(create_app(allowed, self.db))
        ok = client.get("/health", headers={"Origin": "https://app.example.com"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "https://app.example.com")
        other = client.get("/health", headers={"Origin": "https://evil.example.com"})
        self.assertIsNone(other.headers.get("access-control-allow-origin"))

    def test_a_crash_is_reported_without_details(self):
        class BrokenDatabase:
            def transaction(self):
                raise RuntimeError("secret connection string")

        client = TestClient(create_app(self.settings, BrokenDatabase()), raise_server_exceptions=False)
        with self.assertLogs("tajweed.api", level="ERROR"):
            response = client.get("/health")
        self.assertError(response, 500, "server_error")
        self.assertFalse(re.search("secret", response.text))
