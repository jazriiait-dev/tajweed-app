import unittest
from datetime import datetime, timedelta, timezone

import jwt

from app import security
from app.config import ConfigError, load_settings
from app.errors import NotSignedIn

SECRET = "a-secret-that-is-long-enough-for-hs256-tests"


class Passwords(unittest.TestCase):
    def test_a_password_matches_its_own_hash_only(self):
        stored = security.hash_password("correct horse", log_n=8, p=1)
        self.assertTrue(security.verify_password("correct horse", stored))
        self.assertFalse(security.verify_password("correct horsf", stored))
        self.assertFalse(security.verify_password("", stored))

    def test_the_same_password_hashes_differently_each_time(self):
        self.assertNotEqual(
            security.hash_password("same", log_n=8, p=1),
            security.hash_password("same", log_n=8, p=1),
        )

    def test_the_hash_does_not_contain_the_password(self):
        self.assertNotIn("correct horse", security.hash_password("correct horse", log_n=8, p=1))

    def test_non_latin_passwords_work(self):
        stored = security.hash_password("كلمة السر ١٢٣", log_n=8, p=1)
        self.assertTrue(security.verify_password("كلمة السر ١٢٣", stored))

    def test_damaged_or_missing_hashes_never_match(self):
        for stored in (None, "", "plain", "scrypt$8$8$1$bad", "md5$8$8$1$AAAA$AAAA", "scrypt$99$8$1$AAAA$AAAA"):
            self.assertFalse(security.verify_password("anything", stored))

    def test_production_strength_settings_work(self):
        stored = security.hash_password("correct horse")  # default cost
        self.assertTrue(stored.startswith("scrypt$15$8$3$"))
        self.assertTrue(security.verify_password("correct horse", stored))

    def test_weaker_hashes_are_flagged_for_upgrade(self):
        weak = security.hash_password("x", log_n=8, p=1)
        self.assertTrue(security.password_needs_rehash(weak, log_n=15, p=3))
        self.assertFalse(security.password_needs_rehash(weak, log_n=8, p=1))


class AccessTokens(unittest.TestCase):
    def test_round_trip(self):
        token = security.make_access_token(SECRET, "user-1", minutes=5)
        claims = security.read_access_token(SECRET, token)
        self.assertEqual(claims["sub"], "user-1")
        self.assertNotIn("gdn", claims)

    def test_child_token_names_the_parent(self):
        token = security.make_access_token(SECRET, "child-1", minutes=5, guardian_id="parent-1")
        self.assertEqual(security.read_access_token(SECRET, token)["gdn"], "parent-1")

    def test_expired_tokens_are_refused(self):
        long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        token = security.make_access_token(SECRET, "user-1", minutes=5, now=long_ago)
        with self.assertRaises(NotSignedIn) as caught:
            security.read_access_token(SECRET, token)
        self.assertEqual(caught.exception.code, "session_expired")

    def test_tokens_signed_with_another_secret_are_refused(self):
        token = security.make_access_token("another-secret-of-sufficient-length-123", "user-1", minutes=5)
        with self.assertRaises(NotSignedIn) as caught:
            security.read_access_token(SECRET, token)
        self.assertEqual(caught.exception.code, "invalid_token")

    def test_unsigned_and_malformed_tokens_are_refused(self):
        unsigned = jwt.encode({"sub": "user-1", "typ": "access", "exp": 9999999999}, "", algorithm="none")
        for token in (unsigned, "not-a-token", ""):
            with self.assertRaises(NotSignedIn):
                security.read_access_token(SECRET, token)

    def test_other_kinds_of_token_are_refused(self):
        other = jwt.encode({"sub": "user-1", "typ": "refresh", "exp": 9999999999}, SECRET, algorithm="HS256")
        with self.assertRaises(NotSignedIn):
            security.read_access_token(SECRET, other)


class RefreshTokens(unittest.TestCase):
    def test_tokens_are_long_random_and_stored_as_a_hash(self):
        first, second = security.new_refresh_token(), security.new_refresh_token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 60)
        self.assertEqual(len(security.hash_refresh_token(first)), 64)
        self.assertNotIn(first, security.hash_refresh_token(first))


class SettingsLoading(unittest.TestCase):
    BASE = {"DATABASE_URL": "postgresql://x/y", "JWT_SECRET": "s" * 40}

    def test_defaults(self):
        settings = load_settings(self.BASE)
        self.assertEqual(settings.access_token_minutes, 30)
        self.assertEqual(settings.cors_origins, ())
        self.assertFalse(settings.is_production)

    def test_missing_values_are_reported_by_name(self):
        with self.assertRaises(ConfigError) as caught:
            load_settings({"JWT_SECRET": "s" * 40})
        self.assertIn("DATABASE_URL", str(caught.exception))

    def test_production_refuses_a_weak_or_placeholder_secret(self):
        for secret in ("short", "change-me-" + "x" * 40):
            with self.assertRaises(ConfigError):
                load_settings({**self.BASE, "APP_ENV": "production", "JWT_SECRET": secret})
        self.assertTrue(load_settings({**self.BASE, "APP_ENV": "production"}).is_production)

    def test_lists_and_numbers_are_parsed(self):
        settings = load_settings({
            **self.BASE,
            "CORS_ORIGINS": "https://a.example, https://b.example",
            "ACCESS_TOKEN_MINUTES": "10",
        })
        self.assertEqual(settings.cors_origins, ("https://a.example", "https://b.example"))
        self.assertEqual(settings.access_token_minutes, 10)
        with self.assertRaises(ConfigError):
            load_settings({**self.BASE, "ACCESS_TOKEN_MINUTES": "ten"})


if __name__ == "__main__":
    unittest.main()
