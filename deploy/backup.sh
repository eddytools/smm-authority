#!/usr/bin/env bash
# Consistent online backup of the SQLite database (safe while the app is running). Keeps the newest 14.
set -euo pipefail
DB=/var/lib/smm/smm.db
OUT=/var/backups/smm
mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
sqlite3 "$DB" ".backup '$OUT/smm-$STAMP.db'"
gzip -f "$OUT/smm-$STAMP.db"
ls -1t "$OUT"/smm-*.db.gz | tail -n +15 | xargs -r rm --
echo "backup ok: $OUT/smm-$STAMP.db.gz"
