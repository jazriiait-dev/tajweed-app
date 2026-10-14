from app import security
from app.actor import resolve_actor
from app.errors import AppError, Forbidden, NotFound, NotSignedIn
from app.schemas import ChangePassword, CreateChild, UpdateProfile
from app.services import accounts, children

from .support import DatabaseTest


def child_form(**overrides) -> CreateChild:
    data = dict(display_name="Yusuf", language="ar", timezone="Africa/Tunis", guardian_consent=True)
    data.update(overrides)
    return CreateChild(**data)


class ChildProfiles(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.parent = self.make_parent()

    def add_child(self, parent=None, **overrides) -> dict:
        parent = parent or self.parent
        return self.tx(lambda tx: children.create_child(tx, parent, child_form(**overrides)))

    def open(self, child_id, parent=None) -> dict:
        parent = parent or self.parent
        return self.tx(lambda tx: children.open_child_session(tx, self.settings, parent, child_id))

    def actor_for(self, access_token):
        claims = security.read_access_token(self.settings.jwt_secret, access_token)
        return self.tx(lambda tx: resolve_actor(tx, claims))

    def test_a_parent_creates_a_child_profile(self):
        child = self.add_child()
        self.assertTrue(child["is_child"])
        self.assertIsNone(child["email"])
        self.assertEqual(child["roles"], ["student"])
        link = self.tx(lambda tx: tx.one("SELECT guardian_id, consent_given_at FROM guardian_links"))
        self.assertEqual(str(link["guardian_id"]), self.parent.user_id)
        self.assertIsNotNone(link["consent_given_at"])

    def test_consent_is_required(self):
        with self.assertRaises(AppError) as caught:
            self.add_child(guardian_consent=False)
        self.assertEqual(caught.exception.code, "consent_required")
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT count(*) AS n FROM users WHERE is_child"))["n"], 0)

    def test_only_parents_can_create_children(self):
        student = self.make_user()
        with self.assertRaises(Forbidden):
            self.add_child(parent=student)

    def test_a_parent_sees_only_their_own_children(self):
        self.add_child(display_name="Yusuf")
        self.add_child(display_name="Maryam")
        other = self.make_parent("other@example.com")
        self.add_child(parent=other, display_name="Someone else's child")
        mine = self.tx(lambda tx: children.list_children(tx, self.parent))
        self.assertEqual([c["display_name"] for c in mine], ["Yusuf", "Maryam"])

    def test_a_parent_can_edit_their_child(self):
        child = self.add_child()
        view = self.tx(lambda tx: children.update_child(
            tx, self.parent, str(child["id"]), UpdateProfile(display_name="Yusuf A.", language="fr")
        ))
        self.assertEqual((view["display_name"], view["language"]), ("Yusuf A.", "fr"))

    def test_another_parent_cannot_reach_the_child(self):
        child = self.add_child()
        other = self.make_parent("other@example.com")
        for attempt in (
            lambda tx: children.update_child(tx, other, str(child["id"]), UpdateProfile(display_name="X")),
            lambda tx: children.open_child_session(tx, self.settings, other, str(child["id"])),
            lambda tx: children.open_child_session(tx, self.settings, other, "not-an-id"),
        ):
            with self.assertRaises(NotFound) as caught:
                self.tx(attempt)
            self.assertEqual(caught.exception.code, "child_not_found")
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT display_name FROM users WHERE is_child"))["display_name"], "Yusuf")

    def test_opening_a_child_profile_gives_a_student_session(self):
        child = self.add_child()
        session = self.open(str(child["id"]))
        self.assertNotIn("refresh_token", session)
        actor = self.actor_for(session["access_token"])
        self.assertTrue(actor.is_child)
        self.assertEqual(actor.user_id, str(child["id"]))
        self.assertEqual(actor.guardian_id, self.parent.user_id)
        self.assertEqual(actor.roles, frozenset({"student"}))
        me = self.tx(lambda tx: accounts.me(tx, actor))
        self.assertEqual(me["opened_by_parent"], self.parent.user_id)

    def test_a_child_session_cannot_do_what_parents_do(self):
        child = self.add_child()
        actor = self.actor_for(self.open(str(child["id"]))["access_token"])
        for attempt in (
            lambda tx: children.create_child(tx, actor, child_form()),
            lambda tx: children.list_children(tx, actor),
            lambda tx: accounts.update_me(tx, actor, UpdateProfile(display_name="Me")),
            lambda tx: accounts.change_password(
                tx, self.settings, actor, ChangePassword(current_password="x", new_password="12345678")),
        ):
            with self.assertRaises(Forbidden):
                self.tx(attempt)

    def test_a_child_session_ends_when_the_link_or_the_parent_goes(self):
        child = self.add_child()
        token = self.open(str(child["id"]))["access_token"]
        self.actor_for(token)

        self.tx(lambda tx: tx.run("UPDATE users SET is_active = false WHERE id = %s", [self.parent.user_id]))
        with self.assertRaises(NotSignedIn):
            self.actor_for(token)

        self.tx(lambda tx: tx.run("UPDATE users SET is_active = true WHERE id = %s", [self.parent.user_id]))
        self.actor_for(token)
        self.tx(lambda tx: tx.run("DELETE FROM guardian_links"))
        with self.assertRaises(NotSignedIn):
            self.actor_for(token)

    def test_a_child_token_must_name_the_right_parent(self):
        child = self.add_child()
        other = self.make_parent("other@example.com")
        secret = self.settings.jwt_secret
        without_parent = security.make_access_token(secret, str(child["id"]), minutes=5)
        wrong_parent = security.make_access_token(secret, str(child["id"]), minutes=5, guardian_id=other.user_id)
        adult_with_parent = security.make_access_token(secret, other.user_id, minutes=5, guardian_id=self.parent.user_id)
        for token in (without_parent, wrong_parent, adult_with_parent):
            with self.assertRaises(NotSignedIn):
                self.actor_for(token)

    def test_a_disabled_child_profile_cannot_be_opened(self):
        child = self.add_child()
        self.tx(lambda tx: tx.run("UPDATE users SET is_active = false WHERE is_child"))
        with self.assertRaises(AppError) as caught:
            self.open(str(child["id"]))
        self.assertEqual(caught.exception.code, "account_disabled")

    def test_there_is_a_limit_on_children_per_parent(self):
        for number in range(children.MAX_CHILDREN_PER_PARENT):
            self.add_child(display_name=f"Child {number}")
        with self.assertRaises(AppError) as caught:
            self.add_child(display_name="One too many")
        self.assertEqual(caught.exception.code, "too_many_children")
