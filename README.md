# Quran memorization and tajweed app

This repository holds the server side of the app: the database, sign-in,
the roles (student, parent, teacher, admin) and the Quran reader data.
The mobile and web app is not here yet.

The product is described in the version 1 specification. This repository
covers phase 1 of its roadmap, "Foundations".

## What is here

| Part | Where | State |
| --- | --- | --- |
| Database tables | `backend/migrations/` | Run and tested on PostgreSQL 16 |
| API (sign-up, sign-in, child profiles, teachers, admin, Quran reader) | `backend/app/` | Run and tested, 129 automated tests |
| Quran text importer and integrity check | `backend/app/quran_import.py` | Run and tested with placeholder text |
| Server setup (Docker, HTTPS, backups) | `docker-compose.yml`, `Caddyfile`, `scripts/` | Written, **not yet run** |
| Automated tests on GitHub | `.github/workflows/tests.yml` | Written, **not yet run** |
| Mobile and web app | not started | |

Two things could not be checked where this code was written, because that
machine could not download software:

1. The link between the code and the database uses the `psycopg` library
   (`backend/app/db.py`, about 30 lines). The tests were run through a
   stand-in (`backend/tests/libpq_fallback.py`) that sends the same SQL to the
   same PostgreSQL. The first run with `psycopg` itself will be the GitHub
   test run or the first `docker compose up`.
2. The Docker files have not been built.

Expect to fix small things the first time either of those runs.

## The Quran text

The text is not in this repository and was not typed by hand. It is loaded
from the publisher's file with a command that:

- refuses the file unless all 114 surahs are present, in order, with the
  expected number of ayat (6,236 for Hafs),
- stores every ayah exactly as it is in the file,
- keeps a fingerprint, so the stored text can be re-checked at any time,
- leaves the text hidden from students until an admin records that a
  qualified reviewer has checked it.

The database itself refuses any other change to the text.

Only Hafs can be imported today. Warsh numbers its ayat differently and needs
its own verified table of ayah counts first.

## Documents

- [docs/SYSTEM_REQUIREMENTS.md](docs/SYSTEM_REQUIREMENTS.md): what is needed to run the service
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): putting it on a server, step by step
- [docs/API.md](docs/API.md): the API, for whoever builds the app

## For developers

Requirements: Python 3.13 and PostgreSQL 16.

```sh
cd backend
pip install -r requirements.txt -r requirements-dev.txt

# The tests wipe the database they are given. Its name must contain "test".
createdb tajweed_test
export TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/tajweed_test
python -m unittest discover -s tests -t .

# Run the API locally
export DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/tajweed
export JWT_SECRET=$(openssl rand -hex 32)
python -m app.cli migrate
uvicorn app.main:app --reload
```

How the code is laid out:

- `app/api.py` turns HTTP requests into calls to the functions in `app/services/`.
  It holds no rules of its own.
- `app/services/` holds the rules: who may do what, and the SQL.
- `app/actor.py` works out who is asking, fresh on every request.
- `app/db.py` is the only file that touches the database driver.
- `migrations/` holds plain SQL files, applied in order by `python -m app.cli migrate`.
  Add a new file for each change; never edit one that has been applied.

The API is built on Starlette, the framework underneath FastAPI. Moving to
FastAPI later is a small job, because the route handlers hold no logic.

## Not built yet

- The mobile and web app
- Password reset by email (for now an admin sets a new password)
- Email address confirmation at sign-up
- Juz, hizb and page navigation in the reader
- Account deletion and data export
- A second parent or guardian on the same child profile
- Everything in roadmap phases 2 to 5: recitation checking, recordings,
  teacher reviews, class chatrooms, progress tracking
