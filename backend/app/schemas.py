"""Shapes of the data the API accepts. Anything else is rejected."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["ar", "en", "fr"]
Gender = Literal["male", "female"]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Name = Annotated[str, Field(min_length=1, max_length=80)]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("This is not a valid email address.")
    return value


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except Exception:
        raise ValueError("This is not a known time zone, for example Africa/Casablanca.") from None
    return value


class Register(Input):
    email: str
    password: Password
    display_name: Name
    language: Language = "ar"
    timezone: str = "UTC"
    account_type: Literal["student", "parent"]
    # Children do not sign up themselves; a parent creates their profile.
    confirms_adult: bool

    _email = field_validator("email")(_check_email)
    _timezone = field_validator("timezone")(_check_timezone)


class Login(Input):
    email: str
    password: Annotated[str, Field(min_length=1, max_length=128)]

    _email = field_validator("email")(_check_email)


class RefreshToken(Input):
    refresh_token: Annotated[str, Field(min_length=20, max_length=200)]


class UpdateProfile(Input):
    display_name: Optional[Name] = None
    language: Optional[Language] = None
    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value):
        return None if value is None else _check_timezone(value)


class ChangePassword(Input):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class AddRole(Input):
    role: Literal["student", "parent"]


class CreateChild(Input):
    display_name: Name
    language: Language = "ar"
    timezone: str = "UTC"
    guardian_consent: bool

    _timezone = field_validator("timezone")(_check_timezone)


class CreateTeacher(Input):
    email: str
    password: Password
    display_name: Name
    language: Language = "ar"
    timezone: str = "UTC"
    gender: Gender
    credentials: Annotated[str, Field(max_length=2000)] = ""
    riwayat: Annotated[list[str], Field(min_length=1, max_length=20)]
    languages: Annotated[list[Language], Field(min_length=1, max_length=3)]

    _email = field_validator("email")(_check_email)
    _timezone = field_validator("timezone")(_check_timezone)


class UpdateTeacher(Input):
    gender: Optional[Gender] = None
    credentials: Optional[Annotated[str, Field(max_length=2000)]] = None
    riwayat: Optional[Annotated[list[str], Field(min_length=1, max_length=20)]] = None
    languages: Optional[Annotated[list[Language], Field(min_length=1, max_length=3)]] = None
    verified: Optional[bool] = None


class SetActive(Input):
    active: bool


class SetPassword(Input):
    new_password: Password


class ApproveRiwaya(Input):
    reviewer_name: Annotated[str, Field(min_length=2, max_length=120)]
