# Faza 0 — SQLite → PostgreSQL ko'chirish

Mini App uchun bot va web bitta **PostgreSQL** bazaga ulanadi (ma'lumot 100% 1:1).
Bu hujjat — VPS'da test va ko'chirish bosqichlari.

## Tarkib

| Fayl | Vazifa |
|------|--------|
| `db_backend.py` | PostgreSQL shim — sqlite3 API'sini taqlid qiladi (`?`→`%s`, `lastrowid`→`RETURNING id`, `INSERT OR IGNORE`→`ON CONFLICT`, `CURRENT_TIMESTAMP`→`to_char(...)`, savepoint-per-execute). |
| `pg_migrate.py` | Jonli SQLite'dan PG DDL generatsiya + ma'lumot ko'chirish + tekshiruv. |
| `database.py` | `DB_BACKEND` env'ga qarab SQLite yoki shim tanlaydi (default: sqlite). |

**Tip parisiteti:** INTEGER→BIGINT, REAL→DOUBLE PRECISION, BOOLEAN→**SMALLINT** (0/1 int),
TIMESTAMP→**TEXT** ('YYYY-MM-DD HH:MM:SS'). Maqsad — psycopg aynan hozirgi Python
tiplarini qaytarsin, biznes-mantiq o'zgarmasin.

## Lokalda tasdiqlangan (PG'siz)
- `pg_migrate.py --dry-run` → to'g'ri PG DDL.
- `translate_sql` 10/10 unit-test.
- SQLite rejimi buzilmagan (row[0] / row['col'] / dict(row) ishlaydi).

## VPS'da test (PostgreSQL bor joyda)

```bash
# 1) PostgreSQL o'rnatish
apt update && apt install -y postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE USER tezbozor WITH PASSWORD 'KUCHLI_PAROL';"
sudo -u postgres psql -c "CREATE DATABASE marketplace OWNER tezbozor;"

# 2) Kutubxona
pip install 'psycopg[binary]>=3.1'

# 3) TEST bazasiga ko'chirish (jonli PG'ga emas — alohida test DB)
sudo -u postgres psql -c "CREATE DATABASE marketplace_test OWNER tezbozor;"
python pg_migrate.py --pg-dsn "postgresql://tezbozor:KUCHLI_PAROL@localhost:5432/marketplace_test"
#  -> oxirida "HAMMASI MOS ✓" chiqishi kerak (har jadval qator soni mos)

# 4) Botni TEST bazasida ishga tushirib sinash (dublikat token bilan)
#    .env'da:
#      DB_BACKEND=postgres
#      DATABASE_URL=postgresql://tezbozor:KUCHLI_PAROL@localhost:5432/marketplace_test
#    Sinash: /start, mahsulot ko'rish, buyurtma berish, qarz, taymer.
```

## Cutover (haqiqiy o'tkazish — sinovdan keyin)

```bash
# 1) Botni to'xtatish
systemctl stop tezbozor-bot
# 2) Oxirgi ma'lumotni HAQIQIY PG bazaga ko'chirish
python pg_migrate.py --pg-dsn "postgresql://tezbozor:KUCHLI_PAROL@localhost:5432/marketplace"
# 3) .env: DB_BACKEND=postgres + DATABASE_URL (haqiqiy 'marketplace')
# 4) Botni yoqish + smoke-test
systemctl start tezbozor-bot
#    SQLite faylini (marketplace.db) zaxira sifatida saqlab qolish (rollback uchun).
```

## Hali test qilinmagan (VPS'da tekshiriladi)
- Shimning ulanish/tranzaksiya/savepoint xatti-harakati (PG kerak).
- `init_db()` ning PG'da to'liq ishlashi (CREATE/ALTER tarjimasi).
- Sana mantig'i (taymer `auto_cancel_at`, `scheduled_at`) TEXT-timestamp bilan.

## Ko'chirish tartibi (MUHIM)
`seller_requests` divergensiyasi `init_db` da tuzatiladi (eski schema'ni avtomatik
to'g'rilaydi). Shuning uchun:
1. Yangi kodni VPS'ga deploy qiling va botni **bir marta SQLite rejimida qayta yoqing**
   → `init_db` jonli `marketplace.db` dagi `seller_requests` ni to'g'rilaydi.
2. **Keyin** `pg_migrate.py` ni ishga tushiring (to'g'rilangan bazani o'qiydi → to'g'ri PG schema).

## Ma'lum cheklovlar
- CHECK cheklovlari ko'chirilmaydi (ma'lumot toza, app o'zi tekshiradi).
- PG backup `pg_dump` orqali (alohida cron) — `Database.backup()` PG'da no-op.
