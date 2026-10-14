#!/bin/sh
# Save a compressed copy of the database into ./backups.
# Run from the project folder:  ./scripts/backup.sh
# Copy the files in ./backups to another place as well; a backup that lives
# only on the same server is lost with the server.
set -eu
mkdir -p backups
file="backups/tajweed-$(date +%Y-%m-%d-%H%M).sql.gz"
docker compose exec -T db pg_dump -U tajweed tajweed | gzip > "$file"
echo "Saved $file"
# Keep the 30 most recent backups.
ls -1t backups/tajweed-*.sql.gz | tail -n +31 | xargs -r rm --
