"""Maintenance commands.

    python -m app.cli migrate
    python -m app.cli create-admin --email you@example.com --name "Your Name"
    python -m app.cli import-quran --riwaya hafs --file quran-uthmani.txt --source "Tanzil, Uthmani text"
    python -m app.cli verify-quran --riwaya hafs
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import quran_import
from .config import ConfigError, load_settings
from .db import run_in_tx
from .errors import AppError
from .migrate import apply_migrations
from .schemas import Register
from .services import admin


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Maintenance commands.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Create or update the database tables.")

    create = commands.add_parser("create-admin", help="Create an admin account.")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument(
        "--password-env", metavar="VARIABLE",
        help="Read the password from this environment variable instead of asking for it.",
    )

    load = commands.add_parser("import-quran", help="Load the Quran text for a riwaya from a file.")
    load.add_argument("--riwaya", required=True)
    load.add_argument("--file", required=True, type=Path)
    load.add_argument("--source", required=True,
                      help='Where the file came from, for example "Tanzil, Uthmani text, version 1.1".')
    load.add_argument("--replace", action="store_true",
                      help="Overwrite a text that is already loaded. It must then be approved again.")

    check = commands.add_parser("verify-quran", help="Check the stored text has not changed since import.")
    check.add_argument("--riwaya", required=True)
    return parser


def _read_password(args) -> str:
    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            raise AppError("no_password", f"The environment variable {args.password_env} is empty.")
        return password
    first = getpass.getpass("Password (at least 8 characters): ")
    if first != getpass.getpass("Repeat the password: "):
        raise AppError("mismatch", "The two passwords are not the same.")
    return first


def main(argv: list[str] | None = None, *, settings=None, db=None, out=sys.stdout) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = settings or load_settings()
        owns_db = db is None
        if owns_db:
            from .db import Database
            db = Database(settings.database_url, max_size=2)
        try:
            return _run(args, settings, db, out)
        finally:
            if owns_db:
                db.close()
    except (AppError, ConfigError, quran_import.QuranImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


def _run(args, settings, db, out) -> int:
    if args.command == "migrate":
        applied = apply_migrations(db)
        print("Applied: " + ", ".join(applied) if applied else "The database is already up to date.", file=out)
        return 0

    if args.command == "create-admin":
        password = _read_password(args)
        # Reuse the sign-up rules for email, name and password length.
        checked = Register(
            email=args.email, password=password, display_name=args.name,
            account_type="student", confirms_adult=True,
        )
        user = run_in_tx(db, lambda tx: admin.create_admin(
            tx, settings, email=checked.email, password=checked.password,
            display_name=checked.display_name,
        ))
        print(f"Admin account created for {user['email']}.", file=out)
        return 0

    if args.command == "import-quran":
        if not args.file.is_file():
            raise AppError("no_file", f"The file {args.file} does not exist.")
        parsed = quran_import.parse(args.file.read_bytes(), args.riwaya)
        report = run_in_tx(db, lambda tx: quran_import.load(
            tx, parsed, source=args.source, replace=args.replace,
        ))
        print(
            f"Imported {report['ayah_count']} ayat for '{args.riwaya}'.\n"
            f"File fingerprint (SHA-256): {report['file_sha256']}\n"
            "The text is now waiting for a qualified reviewer. It stays hidden from students\n"
            "until an admin records the review.",
            file=out,
        )
        return 0

    if args.command == "verify-quran":
        report = run_in_tx(db, lambda tx: quran_import.verify(tx, args.riwaya))
        if report["intact"]:
            print(f"'{args.riwaya}': {report['ayah_count']} ayat, unchanged since import "
                  f"(status: {report['status']}).", file=out)
            return 0
        print(f"WARNING: the stored text for '{args.riwaya}' does not match its import fingerprint.",
              file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
