from app.errors import AppError, Conflict, Forbidden, NotFound, NotSignedIn
from app.schemas import CreateChild, CreateTeacher, Login, SetActive, SetPassword, UpdateTeacher
from app.services import accounts, admin, children

from .support import DatabaseTest


def teacher_form(**overrides) -> CreateTeacher:
    data = dict(
        email="ustadh@example.com", password="teacher pass", display_name="Ustadh Karim",
        gender="male", credentials="Ijazah in Hafs", riwayat=["hafs"], languages=["ar", "fr"],
    )
    data.update(overrides)
    return CreateTeacher(**data)


class AdminWork(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.admin = self.make_admin()

    def add_teacher(self, **overrides) -> dict:
        return self.tx(lambda tx: admin.create_teacher(tx, self.settings, self.admin, teacher_form(**overrides)))

    def actions(self) -> list[str]:
        return [a["action"] for a in self.tx(lambda tx: admin.list_actions(tx, self.admin))]

    # --- who may use these ------------------------------------------------------

    def test_everything_here_is_for_admins_only(self):
        teacher = self.add_teacher()
        for outsider in (self.make_user(), self.make_parent(), self.make_user("t2@example.com", role="teacher")):
            for attempt in (
                lambda tx: admin.list_users(tx, outsider),
                lambda tx: admin.list_teachers(tx, outsider),
                lambda tx: admin.list_actions(tx, outsider),
                lambda tx: admin.create_teacher(tx, self.settings, outsider, teacher_form(email="x@example.com")),
                lambda tx: admin.update_teacher(tx, outsider, str(teacher["id"]), UpdateTeacher(verified=True)),
                lambda tx: admin.set_active(tx, outsider, self.admin.user_id, SetActive(active=False)),
                lambda tx: admin.set_password(tx, self.settings, outsider, self.admin.user_id,
                                              SetPassword(new_password="hijacked!")),
            ):
                with self.assertRaises(Forbidden):
                    self.tx(attempt)

    # --- teachers ---------------------------------------------------------------

    def test_create_a_teacher(self):
        teacher = self.add_teacher()
        self.assertEqual(teacher["riwayat"], ["hafs"])
        self.assertEqual(teacher["languages"], ["ar", "fr"])
        self.assertEqual(teacher["gender"], "male")
        self.assertFalse(teacher["is_verified"])
        user = self.tx(lambda tx: accounts.user_view(tx, str(teacher["id"])))
        self.assertEqual(user["roles"], ["teacher"])
        # The teacher can sign in with the password the admin set.
        self.tx(lambda tx: accounts.login(tx, self.settings, Login(email="ustadh@example.com", password="teacher pass")))
        self.assertEqual(self.actions(), ["create_teacher"])

    def test_a_teacher_needs_a_known_riwaya_and_a_free_email(self):
        with self.assertRaises(AppError) as caught:
            self.add_teacher(riwayat=["hafs", "qalun"])
        self.assertEqual(caught.exception.code, "unknown_riwaya")
        self.assertEqual(caught.exception.details, {"riwayat": ["qalun"]})

        self.add_teacher()
        with self.assertRaises(Conflict):
            self.add_teacher()
        self.assertEqual(len(self.tx(lambda tx: admin.list_teachers(tx, self.admin))), 1)

    def test_teacher_form_is_validated(self):
        for bad in ({"gender": "other"}, {"riwayat": []}, {"languages": ["de"]}, {"languages": []}):
            with self.assertRaises(ValueError, msg=str(bad)):
                teacher_form(**bad)

    def test_update_and_verify_a_teacher(self):
        teacher_id = str(self.add_teacher()["id"])
        view = self.tx(lambda tx: admin.update_teacher(
            tx, self.admin, teacher_id,
            UpdateTeacher(riwayat=["hafs", "warsh"], languages=["en"], credentials="Ijazah in Hafs and Warsh", verified=True),
        ))
        self.assertEqual(view["riwayat"], ["hafs", "warsh"])
        self.assertEqual(view["languages"], ["en"])
        self.assertTrue(view["is_verified"])
        self.assertIsNotNone(view["verified_at"])

        view = self.tx(lambda tx: admin.update_teacher(tx, self.admin, teacher_id, UpdateTeacher(verified=False)))
        self.assertFalse(view["is_verified"])
        self.assertIsNone(view["verified_at"])
        self.assertEqual(self.actions().count("verify_teacher"), 1)
        self.assertEqual(self.actions().count("unverify_teacher"), 1)

    def test_updating_someone_who_is_not_a_teacher(self):
        student = self.make_user()
        for teacher_id in (student.user_id, "not-an-id"):
            with self.assertRaises(NotFound):
                self.tx(lambda tx: admin.update_teacher(tx, self.admin, teacher_id, UpdateTeacher(verified=True)))

    # --- accounts ---------------------------------------------------------------

    def test_list_filter_and_search_users(self):
        self.make_user("amina@example.com", name="Amina")
        self.make_user("bilal@example.com", name="Bilal 100%")
        parent = self.make_parent()
        self.tx(lambda tx: children.create_child(
            tx, parent, CreateChild(display_name="Yusuf", guardian_consent=True)))
        self.add_teacher()

        everyone = self.tx(lambda tx: admin.list_users(tx, self.admin))
        self.assertEqual(everyone["total"], 6)
        students = self.tx(lambda tx: admin.list_users(tx, self.admin, role="student"))
        self.assertEqual(sorted(u["display_name"] for u in students["items"]), ["Amina", "Bilal 100%", "Yusuf"])
        found = self.tx(lambda tx: admin.list_users(tx, self.admin, search="AMINA"))
        self.assertEqual([u["email"] for u in found["items"]], ["amina@example.com"])
        # % and _ in a search are plain characters, not wildcards.
        self.assertEqual(self.tx(lambda tx: admin.list_users(tx, self.admin, search="100%"))["total"], 1)
        self.assertEqual(self.tx(lambda tx: admin.list_users(tx, self.admin, search="%"))["total"], 1)
        self.assertEqual(self.tx(lambda tx: admin.list_users(tx, self.admin, search="_"))["total"], 0)

        page = self.tx(lambda tx: admin.list_users(tx, self.admin, limit=2, offset=4))
        self.assertEqual((page["total"], len(page["items"])), (6, 2))
        with self.assertRaises(AppError):
            self.tx(lambda tx: admin.list_users(tx, self.admin, role="owner"))

    def test_disabling_an_account_signs_it_out(self):
        student = self.make_user()
        session = self.tx(lambda tx: accounts.issue_tokens(tx, self.settings, student.user_id))
        view = self.tx(lambda tx: admin.set_active(tx, self.admin, student.user_id, SetActive(active=False)))
        self.assertFalse(view["is_active"])
        # Re-enabled later, the old session still stays ended.
        self.tx(lambda tx: admin.set_active(tx, self.admin, student.user_id, SetActive(active=True)))
        with self.assertRaises(NotSignedIn):
            self.tx(lambda tx: accounts.refresh(tx, self.settings, session["refresh_token"]))
        self.assertEqual(self.actions(), ["enable_account", "disable_account"])

    def test_an_admin_cannot_disable_themselves_or_a_missing_user(self):
        with self.assertRaises(AppError) as caught:
            self.tx(lambda tx: admin.set_active(tx, self.admin, self.admin.user_id, SetActive(active=False)))
        self.assertEqual(caught.exception.code, "cannot_disable_self")
        with self.assertRaises(NotFound):
            self.tx(lambda tx: admin.set_active(
                tx, self.admin, "00000000-0000-0000-0000-000000000000", SetActive(active=False)))

    def test_setting_a_new_password_for_a_locked_out_user(self):
        student = self.make_user("amina@example.com")
        old_session = self.tx(lambda tx: accounts.issue_tokens(tx, self.settings, student.user_id))
        self.tx(lambda tx: tx.run("UPDATE users SET locked_until = now() + interval '1 hour', failed_logins = 2"))
        self.tx(lambda tx: admin.set_password(
            tx, self.settings, self.admin, student.user_id, SetPassword(new_password="brand new pass")))
        self.tx(lambda tx: accounts.login(tx, self.settings, Login(email="amina@example.com", password="brand new pass")))
        with self.assertRaises(NotSignedIn):
            self.tx(lambda tx: accounts.refresh(tx, self.settings, old_session["refresh_token"]))
        self.assertEqual(self.actions(), ["set_password"])

    def test_child_profiles_have_no_password_to_set(self):
        parent = self.make_parent()
        child = self.tx(lambda tx: children.create_child(
            tx, parent, CreateChild(display_name="Yusuf", guardian_consent=True)))
        with self.assertRaises(AppError) as caught:
            self.tx(lambda tx: admin.set_password(
                tx, self.settings, self.admin, str(child["id"]), SetPassword(new_password="12345678")))
        self.assertEqual(caught.exception.code, "no_password")

    def test_the_action_log_names_who_did_what_to_whom(self):
        student = self.make_user(name="Amina")
        self.tx(lambda tx: admin.set_active(tx, self.admin, student.user_id, SetActive(active=False)))
        entry = self.tx(lambda tx: admin.list_actions(tx, self.admin))[0]
        self.assertEqual((entry["action"], entry["admin_name"], entry["target_name"]),
                         ("disable_account", "Admin", "Amina"))

    def test_create_admin_from_the_command_line_helper(self):
        view = self.tx(lambda tx: admin.create_admin(
            tx, self.settings, email="owner@example.com", password="owner password", display_name="Owner"))
        self.assertEqual(view["roles"], ["admin"])
        with self.assertRaises(Conflict):
            self.tx(lambda tx: admin.create_admin(
                tx, self.settings, email="owner@example.com", password="owner password", display_name="Owner"))
