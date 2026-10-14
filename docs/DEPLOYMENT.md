# Deployment guide

How to put the service on your own Linux server with Docker.

**These steps and the Docker files have not been run yet.** They were written
on a machine that could not download or run Docker. Treat the first
deployment as a test, on a server with no real users, and expect to adjust
small things.

You will need the items in `SYSTEM_REQUIREMENTS.md`: a server, a domain, and
someone comfortable typing commands into a terminal.

## 1. Point the domain at the server

At your domain registrar, create an `A` record for the name you chose (for
example `api.yourschool.org`) with the server's IP address. HTTPS cannot be
set up until this has taken effect.

## 2. Install Docker

Connect to the server and install Docker Engine with the Compose plugin,
following Docker's instructions for your Linux version at
https://docs.docker.com/engine/install/ .

Check it worked:

```sh
docker compose version
```

## 3. Put the code on the server

Once the code is on GitHub:

```sh
git clone https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git tajweed-app
cd tajweed-app
```

Before then, upload the project folder and `cd` into it.

## 4. Fill in the settings

```sh
cp .env.example .env
openssl rand -hex 24    # use the output as POSTGRES_PASSWORD
openssl rand -hex 32    # use the output as JWT_SECRET
nano .env
```

Set `DOMAIN` to the name from step 1. Keep a copy of this file somewhere
safe and private; without `POSTGRES_PASSWORD` the database cannot be opened.

## 5. Start the service

```sh
docker compose up -d --build
```

The first start takes a few minutes. It creates the database tables by
itself. Then check:

```sh
curl https://YOUR-DOMAIN/health
```

The answer should be `{"status":"ok"}`. If it is not:

```sh
docker compose ps
docker compose logs api
docker compose logs caddy
```

## 6. Create the first admin account

```sh
docker compose exec api python -m app.cli create-admin --email you@example.com --name "Your Name"
```

It asks for a password twice. Admins create all teacher accounts.

## 7. Import the Quran text (Hafs)

1. Download the Uthmani text from the Tanzil project, https://tanzil.net/download/ ,
   choosing the output format with ayah numbers, where each line looks like
   `1|1|text`.
2. Read Tanzil's terms of use on that site. As far as we know they allow
   verbatim copies, forbid any change to the text, and require the app to
   name Tanzil as the source with a link. Confirm the current wording.
3. Put the file in the `quran-text` folder of the project.
4. Import it, naming the source and its version:

```sh
docker compose exec api python -m app.cli import-quran \
    --riwaya hafs \
    --file /srv/quran-text/quran-uthmani.txt \
    --source "Tanzil, Uthmani text, version X.Y"
```

The command refuses the file unless all 114 surahs and 6,236 ayat are
present and in order. It prints the file's fingerprint; keep it with your
records.

The text now waits for review. Students cannot see it until an admin records
the reviewer's name through the API (`POST /api/v1/admin/riwayat/hafs/approve`).
The review screen comes with the app.

Two points for the reviewer:

- The file may carry the basmala at the start of the first ayah of each
  surah. The text is stored exactly as published, so how the basmala is
  shown is decided in the app.
- The surah names and ayah counts in `backend/app/quran_data.py` were entered
  by hand and should be checked as well.

To confirm later that the stored text is unchanged:

```sh
docker compose exec api python -m app.cli verify-quran --riwaya hafs
```

## 8. Backups

```sh
./scripts/backup.sh
```

This saves a compressed copy of the database in `backups/` and keeps the 30
most recent. To run it every night at 02:00, add this line with `crontab -e`,
using the project's real path:

```
0 2 * * * cd /home/USER/tajweed-app && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Copy the backups to another place too, and try restoring one before launch:

```sh
gunzip -c backups/FILE.sql.gz | docker compose exec -T db psql -U tajweed tajweed
```

Restore into an empty database, not over a live one.

## 9. Updating

```sh
git pull
docker compose up -d --build
```

New database changes are applied by themselves when the API starts.

## On a managed platform instead

The same pieces apply: build `backend/Dockerfile`, attach a PostgreSQL 16
database, and set `APP_ENV=production`, `DATABASE_URL`, `JWT_SECRET` and
`CORS_ORIGINS`. The platform provides HTTPS and backups, so `Caddyfile`,
`docker-compose.yml` and `scripts/backup.sh` are not used. Run the commands
in steps 6 and 7 from the platform's shell.
