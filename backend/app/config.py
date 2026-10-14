"""Settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

LANGUAGES = ("ar", "en", "fr")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    environment: str = "development"
    access_token_minutes: int = 30
    child_token_minutes: int = 60
    refresh_token_days: int = 30
    max_failed_logins: int = 10
    lockout_minutes: int = 15
    cors_origins: tuple[str, ...] = ()
    # Password hashing cost: scrypt with N = 2 ** scrypt_log_n, r = 8, p = scrypt_p.
    scrypt_log_n: int = 15
    scrypt_p: int = 3
    db_pool_size: int = 10

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)

    def need(name: str) -> str:
        value = env.get(name, "").strip()
        if not value:
            raise ConfigError(f"The setting {name} is missing. See .env.example.")
        return value

    def number(name: str, default: int) -> int:
        raw = env.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"The setting {name} must be a whole number, not {raw!r}.") from None

    environment = env.get("APP_ENV", "development").strip() or "development"
    secret = need("JWT_SECRET")
    if environment == "production" and (len(secret) < 32 or secret.startswith("change-me")):
        raise ConfigError(
            "JWT_SECRET must be a random value of at least 32 characters in production."
        )

    origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())

    return Settings(
        database_url=need("DATABASE_URL"),
        jwt_secret=secret,
        environment=environment,
        access_token_minutes=number("ACCESS_TOKEN_MINUTES", 30),
        child_token_minutes=number("CHILD_TOKEN_MINUTES", 60),
        refresh_token_days=number("REFRESH_TOKEN_DAYS", 30),
        max_failed_logins=number("MAX_FAILED_LOGINS", 10),
        lockout_minutes=number("LOCKOUT_MINUTES", 15),
        cors_origins=origins,
        scrypt_log_n=number("SCRYPT_LOG_N", 15),
        scrypt_p=number("SCRYPT_P", 3),
        db_pool_size=number("DB_POOL_SIZE", 10),
    )
