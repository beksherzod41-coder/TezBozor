#!/bin/bash
# Jonli SQLite bazasini (marketplace.db) xavfsiz online-backup qiladi.
# Python sqlite3 .backup API — WAL bilan ham izchil nusxa (oddiy cp'dan xavfsizroq).
# Cron: 5 3 * * * /root/sqlite_backup.sh >> /root/db_backups/backup.log 2>&1
#
# DIQQAT: jonli backend SQLite (marketplace.db). Eski /root/pg_backup.sh postgres'ni
# zaxiralaydi — u FAOL BACKEND EMAS, shuning uchun bu skript haqiqiy ma'lumotni saqlaydi.
set -e
DB="${1:-/root/marketplace.db}"
DIR="${2:-/root/db_backups}"
mkdir -p "$DIR"
TS=$(date +%Y%m%d_%H%M)
OUT="$DIR/marketplace_${TS}.db"
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close(); dst.close()
PY
gzip -f "$OUT"
# 21 kundan eski nusxalarni o'chir
find "$DIR" -name "*.db.gz" -mtime +21 -delete
