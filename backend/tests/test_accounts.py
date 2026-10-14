from app import security
from app.actor import resolve_actor
from app.errors import AppError, Conflict, Forbidden, NotSignedIn
from app.schemas import AddRole, ChangePassword, Login, Register, UpdateProfile
from app.services import accounts

from .support import DatabaseTest


def signup(**overrides) -> Register:
    data = dict(
        email="amina@example.com", password="correct horse", display_name="Amina",
        language="fr", timezone="Africa/Casablanca", account_type="student", confirms_adult=True,
    )
    data.update(overrides)
    return Register(**data)


class Accounts(DatabaseTest):
    def register(self, **overrides) -> dict:
        return self.tx(lambda tx: accounts.register(tx, self.settings, signup(**overrides)))

    def login(self, email="amina@example.com", password="correct horse") -> dict:
        return self.tx(lambda tx: accounts.login(tx, self.settings, Login(email=email, password=password)))

    def actor_for(self, access_token: str):
        claims = security.read_access_token(self.settings.jwt_secret, access_token)
        return self.tx(lambda tx: resolve_actor(tx, claims))

    # --- sign-up ---------------------------------------------------------------

    def test_sign_up_creates_a_student_and_signs_them_in(self):
        result = self.register()
        self.assertEqual(result["user"]["email"], "amina@example.com")
        self.assertEqual(result["user"]["roles"], ["student"])
        self.assertEqual(result["user"]["language"], "fr")
        self.assertFalse(result["user"]["is_child"])
        actor = self.actor_for(result["access_token"])
        self.assertEqual(actor.roles, frozenset({"student"}))
        self.assertFalse(actor.is_child)

    def test_email_is_stored_in_lowercase(self):
        result = self.register(email="  Amina@Example.COM ")
        self.assertEqual(result["user"]["email"], "amina@example.com")
        self.login(email="AMINA@example.com")

    def test_the_same_email_cannot_sign_up_twice(self):
        self.register()
        with self.assertRaises(Conflict) as caught:
            self.register(display_name="Someone else")
        self.assertEqual(caught.exception.code, "email_taken")

    def test_a_parent_account(self):
        self.assertEqual(self.register(account_type="parent")["user"]["roles"], ["parent"])

    def test_nobody_can_sign_up_as_teacher_or_admin(self):
        for role in ("teacher", "admin"):
            with self.assertRaises(ValueError):
                signup(account_type=role)

    def test_children_cannot_sign_up_themselves(self):
        with self.assertRaises(AppError) as caught:
            self.register(confirms_adult=False)
        self.assertEqual(caught.exception.code, "adult_required")

    def test_bad_details_are_refused(self):
        for bad in (
            {"email": "not-an-email"}, {"password": "short"}, {"display_name": "  "},
            {"language": "de"}, {"timezone": "Mars/Olympus"}, {"unexpected": "field"},
        ):
            with self.assertRaises(ValueError, msg=str(bad)):
                signup(**bad)

    def test_password_cannot_be_the_email(self):
        with self.assertRaises(AppError) as caught:
            self.register(password="amina@example.com")
        self.assertEqual(caught.exception.code, "weak_password")

    def test_the_password_is_not_stored(self):
        self.register()
        row = self.tx(lambda tx: tx.one("SELECT password_hash FROM users"))
        self.assertNotIn("correct horse", row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("scrypt$"))

    # --- sign-in ---------------------------------------------------------------

    def test_sign_in(self):
        self.register()
        result = self.login()
        self.assertEqual(result["user"]["display_name"], "Amina")
        self.assertEqual(result["expires_in"], 30 * 60)

    def test_wrong_password_and_unknown_email_give_the_same_answer(self):
        self.register()
        for email, password in (("amina@example.com", "wrong password"), ("nobody@example.com", "correct horse")):
            with self.assertRaises(NotSignedIn) as caught:
                self.login(email, password)
            self.assertEqual(caught.exception.code, "wrong_credentials")

    def test_repeated_failures_lock_the_account(self):
        self.register()
        for _ in range(self.settings.max_failed_logins):
            with self.assertRaises(NotSignedIn):
                self.login(password="wrong password")
        # Locked now, even with the right password.
        with self.assertRaises(AppError) as caught:
            self.login()
        self.assertEqual(caught.exception.code, "account_locked")
        self.assertEqual(caught.exception.status, 429)

        # After the lock expires the right password works again.
        self.tx(lambda tx: tx.run("UPDATE users SET locked_until = now() - interval '1 second'"))
        self.login()

    def test_a_successful_sign_in_resets_the_failure_count(self):
        self.register()
        with self.assertRaises(NotSignedIn):
            self.login(password="wrong password")
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT failed_logins FROM users"))["failed_logins"], 1)
        self.login()
        self.assertEqual(self.tx(lambda tx: tx.one("SELECT failed_logins FROM users"))["failed_logins"], 0)

    def test_old_password_hashes_are_upgraded_at_sign_in(self):
        self.register()
        weak = security.hash_password("correct horse", log_n=6, p=1)
        self.tx(lambda tx: tx.run("UPDATE users SET password_hash = %s", [weak]))
        self.login()
        stored = self.tx(lambda tx: tx.one("SELECT password_hash FROM users"))["password_hash"]
        self.assertTrue(stored.startswith(f"scrypt${self.settings.scrypt_log_n}$"))
        self.login()

    def test_a_disabled_account_cannot_sign_in_or_keep_working(self):
        result = self.register()
        self.tx(lambda tx: tx.run("UPDATE users SET is_active = false"))
        with self.assertRaises(Forbidden) as caught:
            self.login()
        self.assertEqual(caught.exception.code, "account_disabled")
        with self.assertRaises(Forbidden):
            self.actor_for(result["access_token"])
        with self.assertRaises(Forbidden):
            self.tx(lambda tx: accounts.refresh(tx, self.settings, result["refresh_token"]))

    # --- staying signed in -----------------------------------------------------

    def test_refresh_gives_new_tokens_and_retires_the_old_one(self):
        first = self.register()
        second = self.tx(lambda tx: accounts.refresh(tx, self.settings, first["refresh_token"]))
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.actor_for(second["access_token"])
        third = self.tx(lambda tx: accounts.refresh(tx, self.settings, second["refresh_token"]))
        self.assertNotEqual(third["refresh_token"], second["refresh_token"])

    def test_reusing_a_retired_refresh_token_signs_everything_out(self):
        first = self.register()
        second = self.tx(lambda tx: accounts.refresh(tx, self.settings, first["refresh_token"]))
        with self.assertRaises(NotSignedIn) as caught:
            self.tx(lambda tx: accounts.refresh(tx, self.settings, first["refresh_token"]))
        self.assertEqual(caught.exception.code, "refresh_token_reused")
        # The newer token no longer works either.
        with self.assertRaises(NotSignedIn):
            self.tx(lambda tx: accounts.refresh(tx, self.settings, second["refresh_token"]))

    def test_unknown_and_expired_refresh_tokens_are_refused(self):
        result = self.register()
        with self.assertRaises(NotSignedIn) as caught:
            self.tx(lambda tx: accounts.refresh(tx, self.settings, "x" * 64))
        self.assertEqual(caught.exception.code, "invalid_refresh_token")

        self.tx(lambda tx: tx.run("UPDATE refresh_tokens SET expires_at = now() - interval '1 minute'"))
        with self.assertRaises(NotSignedIn) as caught:
            self.tx(lambda tx: accounts.refresh(tx, self.settings, result["refresh_token"]))
        self.assertEqual(caught.exception.code, "session_expired")

    def test_refresh_tokens_are_stored_hashed(self):
        result = self.register()
        row = self.tx(lambda tx: tx.one("SELECT token_hash FROM refresh_tokens"))
        self.assertNotEqual(row["token_hash"], result["refresh_token"])
        self.assertEqual(row["token_hash"], security.hash_refresh_token(result["refresh_token"]))

    def test_sign_out(self):
        result = self.register()
        self.tx(lambda tx: accounts.logout(tx, result["refresh_token"]))
        with self.assertRaises(NotSignedIn) as caught:
            self.tx(lambda tx: accounts.refresh(tx, self.settings, result["refresh_token"]))
        self.assertEqual(caught.exception.code, "session_ended")
        # Signing out twice, or with a made-up token, is harmless.
        self.tx(lambda tx: accounts.logout(tx, result["refresh_token"]))
        self.tx(lambda tx: accounts.logout(tx, "y" * 64))

    # --- own profile -----------------------------------------------------------

    def test_update_own_profile(self):
        actor = self.actor_for(self.register()["access_token"])
        view = self.tx(lambda tx: accounts.update_me(
            tx, actor, UpdateProfile(display_name="Amina B.", language="ar")
        ))
        self.assertEqual((view["display_name"], view["language"], view["timezone"]),
                         ("Amina B.", "ar", "Africa/Casablanca"))

    def test_change_password_signs_out_other_devices(self):
        phone = self.register()
        laptop = self.login()
        actor = self.actor_for(laptop["access_token"])
        fresh = self.tx(lambda tx: accounts.change_password(
            tx, self.settings, actor,
            ChangePassword(current_password="correct horse", new_password="battery staple"),
        ))
        with self.assertRaises(NotSignedIn) as caught:
            self.tx(lambda tx: accounts.refresh(tx, self.settings, phone["refresh_token"]))
        self.assertEqual(caught.exception.code, "session_ended")
        # The phone's failed attempt does not disturb the laptop's new session.
        self.tx(lambda tx: accounts.refresh(tx, self.settings, fresh["refresh_token"]))
        self.login(password="battery staple")
        with self.assertRaises(NotSignedIn):
            self.login(password="correct horse")

    def test_change_password_needs_the_current_one(self):
        actor = self.actor_for(self.register()["access_token"])
        with self.assertRaises(AppError) as caught:
            self.tx(lambda tx: accounts.change_password(
                tx, self.settings, actor,
                ChangePassword(current_password="not it", new_password="battery staple"),
            ))
        self.assertEqual(caught.exception.code, "wrong_password")
        self.login()

    def test_an_adult_can_be_student_and_parent(self):
        actor = self.actor_for(self.register()["access_token"])
        view = self.tx(lambda tx: accounts.add_role(tx, actor, AddRole(role="parent")))
        self.assertEqual(view["roles"], ["parent", "student"])
        # Asking twice changes nothing; staff roles cannot be self-assigned.
        self.tx(lambda tx: accounts.add_role(tx, actor, AddRole(role="parent")))
        for role in ("teacher", "admin"):
            with self.assertRaises(ValueError):
                AddRole(role=role)

    # --- tokens for accounts that no longer exist ---------------------------------

    def test_a_token_for_a_deleted_or_made_up_user_is_refused(self):
        result = self.register()
        claims = security.read_access_token(self.settings.jwt_secret, result["access_token"])
        self.tx(lambda tx: tx.run("DELETE FROM users"))
        with self.assertRaises(NotSignedIn):
            self.tx(lambda tx: resolve_actor(tx, claims))
        with self.assertRaises(NotSignedIn):
            self.tx(lambda tx: resolve_actor(tx, {"sub": "not-a-uuid"}))
