#!/bin/bash
# Jonli SQLite bazasini (marketplace.db) xavfsiz online-backup qiladi + OFFSITE:
# gzip nusxani admin Telegram'iga yuboradi (BOT_TOKEN+ADMIN_ID /root/.env dan).
# Python sqlite3 .backup API — WAL bilan ham izchil nusxa (oddiy cp'dan xavfsizroq).
# Cron: 5 3 * * * /root/sqlite_backup.sh >> /root/db_backups/backup.log 2>&1
#
# DIQQAT: jonli backend SQLite (marketplace.db). Eski /root/pg_backup.sh postgres'ni
# zaxiralaydi — u FAOL BACKEND EMAS, shuning uchun bu skript haqiqiy ma'lumotni saqlaydi.
set -e
DB="${1:-/root/marketplace.db}"
DIR="${2:-/root/db_backups}"
ENV_FILE="${3:-/root/.env}"
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
GZ="${OUT}.gz"
# 21 kundan eski mahalliy nusxalarni o'chir
find "$DIR" -name "*.db.gz" -mtime +21 -delete

# --- OFFSITE: Telegram admin'ga yuborish (token/id .env dan; tirnoqlar tozalanadi) ---
_val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
BOT_TOKEN="$(_val BOT_TOKEN)"
ADMIN_ID="$(_val ADMIN_ID)"
if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    if curl -sf --max-time 60 \
        -F "chat_id=${ADMIN_ID}" \
        -F "document=@${GZ}" \
        -F "caption=🗄 TezBozor DB backup ${TS} ($(du -h "$GZ" | cut -f1))" \
        "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" >/dev/null; then
        echo "$(date '+%F %T') offsite OK: Telegram admin ${ADMIN_ID}"
    else
        echo "$(date '+%F %T') offsite XATO: Telegram yuborilmadi (mahalliy nusxa saqlandi)"
    fi
else
    echo "$(date '+%F %T') offsite SKIP: BOT_TOKEN/ADMIN_ID topilmadi"
fi
