"""The HTTP API.

This file only translates between HTTP and the functions in `services/`:
it reads the request, works out who is asking, calls one function inside a
database transaction, and turns the result or the error into JSON.
All rules about who may do what live in the services.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from . import security
from .actor import Actor, resolve_actor
from .config import Settings
from .db import Tx, run_in_tx
from .errors import AppError, NotSignedIn
from . import schemas
from .services import accounts, admin, children, quran

log = logging.getLogger("tajweed.api")

MAX_BODY_BYTES = 64 * 1024


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Cannot turn {type(value).__name__} into JSON")


def json_response(content: Any, status: int = 200) -> Response:
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    return Response(body.encode("utf-8"), status_code=status, media_type="application/json")


@dataclass
class Call:
    """Everything a route needs to do its work."""

    tx: Tx
    settings: Settings
    actor: Actor | None
    body: Any
    path: dict
    query: Any

    def int_query(self, name: str, default: int | None = None) -> int | None:
        raw = self.query.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            raise AppError("invalid_input", f"'{name}' must be a whole number.", status=422) from None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _parse_body(model, raw: bytes):
    if len(raw) > MAX_BODY_BYTES:
        raise AppError("too_large", "The request is too large.", status=413)
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as error:
        problems = [
            {"field": ".".join(str(part) for part in item["loc"]), "problem": item["msg"]}
            for item in error.errors()
        ]
        raise AppError(
            "invalid_input",
            "Some of the information is missing or not valid.",
            status=422,
            details=problems,
        ) from None


def create_app(settings: Settings, db) -> Starlette:
    def route(method: str, path: str, handler: Callable[[Call], Any], *,
              auth: str = "required", body=None, status: int = 200) -> Route:
        """Build one route.

        auth: "required" (must be signed in), "optional" (signed in or not),
        or "none" (the token is ignored).
        """

        async def endpoint(request: Request) -> Response:
            payload = _parse_body(body, await request.body()) if body is not None else None

            claims = None
            if auth != "none":
                token = _bearer_token(request)
                if token is not None:
                    claims = security.read_access_token(settings.jwt_secret, token)
                elif auth == "required":
                    raise NotSignedIn()

            def work(tx: Tx) -> Any:
                actor = resolve_actor(tx, claims) if claims is not None else None
                return handler(Call(
                    tx=tx, settings=settings, actor=actor, body=payload,
                    path=request.path_params, query=request.query_params,
                ))

            result = await run_in_threadpool(run_in_tx, db, work)
            if status == 204:
                return Response(status_code=204)
            return json_response(result, status)

        return Route(path, endpoint, methods=[method])

    # --- health ---------------------------------------------------------------

    def health(c: Call) -> dict:
        c.tx.one("SELECT 1 AS ok")
        return {"status": "ok"}

    api = [
        # Sign-up and sign-in
        route("POST", "/auth/register", lambda c: accounts.register(c.tx, c.settings, c.body),
              auth="none", body=schemas.Register, status=201),
        route("POST", "/auth/login", lambda c: accounts.login(c.tx, c.settings, c.body),
              auth="none", body=schemas.Login),
        route("POST", "/auth/refresh",
              lambda c: accounts.refresh(c.tx, c.settings, c.body.refresh_token),
              auth="none", body=schemas.RefreshToken),
        route("POST", "/auth/logout", lambda c: accounts.logout(c.tx, c.body.refresh_token),
              auth="none", body=schemas.RefreshToken, status=204),

        # My own account
        route("GET", "/me", lambda c: accounts.me(c.tx, c.actor)),
        route("PATCH", "/me", lambda c: accounts.update_me(c.tx, c.actor, c.body),
              body=schemas.UpdateProfile),
        route("POST", "/me/password",
              lambda c: accounts.change_password(c.tx, c.settings, c.actor, c.body),
              body=schemas.ChangePassword),
        route("POST", "/me/roles", lambda c: accounts.add_role(c.tx, c.actor, c.body),
              body=schemas.AddRole),

        # A parent's child profiles
        route("GET", "/children", lambda c: children.list_children(c.tx, c.actor)),
        route("POST", "/children", lambda c: children.create_child(c.tx, c.actor, c.body),
              body=schemas.CreateChild, status=201),
        route("PATCH", "/children/{child_id}",
              lambda c: children.update_child(c.tx, c.actor, c.path["child_id"], c.body),
              body=schemas.UpdateProfile),
        route("POST", "/children/{child_id}/session",
              lambda c: children.open_child_session(c.tx, c.settings, c.actor, c.path["child_id"])),

        # Reading the Quran (no account needed)
        route("GET", "/riwayat", lambda c: quran.list_riwayat(c.tx, c.actor), auth="optional"),
        route("GET", "/quran/{riwaya}/surahs",
              lambda c: quran.list_surahs(c.tx, c.actor, c.path["riwaya"]), auth="optional"),
        route("GET", "/quran/{riwaya}/surahs/{number:int}",
              lambda c: quran.get_surah(c.tx, c.actor, c.path["riwaya"], c.path["number"],
                                        c.int_query("from"), c.int_query("to")),
              auth="optional"),

        # Platform staff
        route("GET", "/admin/users",
              lambda c: admin.list_users(c.tx, c.actor, role=c.query.get("role") or None,
                                         search=c.query.get("search") or None,
                                         limit=c.int_query("limit", 50),
                                         offset=c.int_query("offset", 0))),
        route("POST", "/admin/users/{user_id}/active",
              lambda c: admin.set_active(c.tx, c.actor, c.path["user_id"], c.body),
              body=schemas.SetActive),
        route("POST", "/admin/users/{user_id}/password",
              lambda c: admin.set_password(c.tx, c.settings, c.actor, c.path["user_id"], c.body),
              body=schemas.SetPassword, status=204),
        route("GET", "/admin/teachers", lambda c: admin.list_teachers(c.tx, c.actor)),
        route("POST", "/admin/teachers",
              lambda c: admin.create_teacher(c.tx, c.settings, c.actor, c.body),
              body=schemas.CreateTeacher, status=201),
        route("PATCH", "/admin/teachers/{teacher_id}",
              lambda c: admin.update_teacher(c.tx, c.actor, c.path["teacher_id"], c.body),
              body=schemas.UpdateTeacher),
        route("GET", "/admin/actions",
              lambda c: admin.list_actions(c.tx, c.actor, limit=c.int_query("limit", 100))),
        route("POST", "/admin/riwayat/{code}/approve",
              lambda c: admin.approve_riwaya(c.tx, c.actor, c.path["code"], c.body),
              body=schemas.ApproveRiwaya),
    ]

    # --- errors ---------------------------------------------------------------

    async def on_app_error(request: Request, error: AppError) -> Response:
        return json_response(error.to_dict(), error.status)

    async def on_http_error(request: Request, error: HTTPException) -> Response:
        codes = {404: "not_found", 405: "method_not_allowed"}
        code = codes.get(error.status_code, "http_error")
        return json_response({"error": {"code": code, "message": str(error.detail)}}, error.status_code)

    async def on_crash(request: Request, error: Exception) -> Response:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return json_response(
            {"error": {"code": "server_error", "message": "Something went wrong on our side."}}, 500
        )

    middleware = []
    if settings.cors_origins:
        middleware.append(Middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        ))

    return Starlette(
        routes=[
            route("GET", "/health", health, auth="none"),
            Mount("/api/v1", routes=api),
        ],
        middleware=middleware,
        exception_handlers={AppError: on_app_error, HTTPException: on_http_error, Exception: on_crash},
    )
