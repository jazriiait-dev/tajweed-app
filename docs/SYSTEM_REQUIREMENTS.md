# System requirements

What is needed to run the service as it stands (roadmap phase 1), and what
later phases will add.

## Server

| Need | Requirement |
| --- | --- |
| Operating system | A current Linux server, for example Ubuntu 24.04 LTS |
| Size to start | 2 CPU cores, 4 GB memory, 40 GB SSD disk |
| Software | Docker Engine with the Compose plugin. Everything else runs in containers |
| Network | A public IP address, with ports 80 and 443 open |
| Domain | A domain or subdomain pointing at the server, for example `api.yourschool.org` |
| HTTPS | Automatic. The Caddy container obtains and renews the certificate |

This size is a starting point for a school with hundreds of students. Signing
in is the heaviest operation today, at roughly a quarter of a second of one
CPU core per sign-in.

## Software versions

| Component | Version |
| --- | --- |
| Python | 3.13 |
| PostgreSQL | 16 |
| Starlette | 1.6.0 |
| Uvicorn | 0.53.0 |
| Pydantic | 2.13.5 |
| PyJWT | 2.14.0 |
| psycopg | 3.2.3 or later, below 4 |
| Caddy | 2 |

## Two ways to host it

1. **A managed platform** that builds the Dockerfile from GitHub and offers a
   managed PostgreSQL database with backups (Render, Railway and Fly.io are
   examples). There is no server to maintain. This is the easier choice
   for an owner without technical staff.
2. **Your own server** with `docker-compose.yml` from this repository. It
   costs less at small scale, but someone must apply security updates and
   look after backups. `DEPLOYMENT.md` covers this route.

Check providers' current prices and regions before choosing. If students are
mostly in one region, pick a data centre near them.

## Accounts to open

| Account | Needed for | When |
| --- | --- | --- |
| GitHub | Holding the code and running the automated tests | Now |
| Domain registrar | The service's web address | Before first deployment |
| Hosting provider | The server or managed platform | Before first deployment |
| Apple Developer Program | Publishing the iOS app. An organization account needs a D-U-N-S number | Before the app is submitted |
| Google Play Console | Publishing the Android app | Before the app is submitted |
| Email sending service | Password reset and notification emails | Before launch |
| File storage (S3-compatible) | Student recordings and teacher voice corrections | Roadmap phase 3 |

## People

- **Someone technical** for the first deployment and for updates afterwards.
  A few hours a month once it is running.
- **A qualified Quran reviewer** to check the imported text and the surah
  table before either is shown to students.
- **An admin** to create teacher accounts and handle account requests.

## Security and privacy requirements the code already meets

- Passwords are stored only as salted scrypt hashes.
- Ten wrong passwords in a row lock an account for 15 minutes.
- Sign-in tokens last 30 minutes. The longer-lived token that renews them is
  stored only as a hash, is replaced at every use, and signs the account out
  everywhere if a retired copy is ever presented.
- Children have no email or password. A parent creates the profile, gives
  consent, and opens it from their own account.
- A parent can reach only their own children's profiles.
- Teachers and admins cannot sign themselves up.
- Every admin action on an account is recorded.
- The Quran text cannot be changed except by the import command.

## Requirements for operating it

- **Backups.** Daily at least, copied off the server, with a restore tried
  before launch. `scripts/backup.sh` makes the copy.
- **Secrets.** The `.env` file holds the database password and the token
  secret. It must never be shared or put on GitHub.
- **Updates.** Operating system and Docker image updates applied regularly.
- **Monitoring.** `GET /health` answers `{"status":"ok"}` when the API and
  database are both working. Point an uptime checker at it.
- **Legal.** Privacy policy, terms of use, and parental consent wording,
  reviewed for each launch country.

## Required before launch, not built yet

- Password reset by email, and confirmation of email addresses
- A limit on requests per address, set at the proxy
- Account deletion and data export on request
- The phone and tablet versions the app will support, set when the app is built
