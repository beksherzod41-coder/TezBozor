import sqlite3
import threading
import datetime
import logging
import shutil
import os
import re as _re
from typing import Optional, List, Dict, Any


# ===== TRANSLITERATSIYA (O'zbek lotin ↔ kirill) =====
_LAT_TO_CYR = {
    'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д',
    'e': 'е', 'yo': 'ё', 'j': 'ж', 'z': 'з', 'i': 'и',
    'y': 'й', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
    'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т',
    'u': 'у', 'f': 'ф', 'x': 'х', 'ts': 'ц', 'ch': 'ч',
    'sh': 'ш', "o'": 'ў', "g'": 'ғ', 'q': 'қ', 'h': 'ҳ',
    "'": 'ъ',
}

_CYR_TO_LAT = {v: k for k, v in _LAT_TO_CYR.items()}
_CYR_TO_LAT.update({'ё': 'yo', 'ж': 'j', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh',
                    'ў': "o'", 'ғ': "g'", 'қ': 'q', 'ҳ': 'h'})


def transliterate_to_latin(text):
    """Kirill → lotin transliteratsiya."""
    if not text:
        return ''
    result = []
    for ch in text.lower():
        result.append(_CYR_TO_LAT.get(ch, ch))
    return ''.join(result)


def transliterate_to_cyrillic(text):
    """Lotin → kirill transliteratsiya."""
    if not text:
        return ''
    text = text.lower()
    result = []
    i = 0
    while i < len(text):
        # 2 belgili kombinatsiyalarni avval tekshiramiz
        if i + 1 < len(text):
            digraph = text[i:i+2]
            if digraph in _LAT_TO_CYR:
                result.append(_LAT_TO_CYR[digraph])
                i += 2
                continue
        # 1 belgili
        result.append(_LAT_TO_CYR.get(text[i], text[i]))
        i += 1
    return ''.join(result)


def generate_search_variants(query):
    """Qidiruv so'zi uchun barcha variantlarni qaytaradi (lotin, kirill, asl)."""
    if not query:
        return []
    q = query.strip().lower()
    variants = {q}
    # Lotin → kirill
    cyr = transliterate_to_cyrillic(q)
    if cyr != q:
        variants.add(cyr)
    # Kirill → lotin
    lat = transliterate_to_latin(q)
    if lat != q:
        variants.add(lat)
    # Apostrof turli ko'rinishlarda yozilishi/saqlanishi mumkin: '  '  ʼ  ʻ  `
    # Har bir variantni avval bitta shaklga keltiramiz, keyin har bir shakl uchun
    # alohida variant qo'shamiz — shunda foydalanuvchi qaysi apostrofni yozsa ham topiladi.
    APOS_FORMS = ["'", "\u2019", "\u02BC", "\u02BB", "`"]
    for v in list(variants):
        norm = v
        for a in APOS_FORMS:
            norm = norm.replace(a, "'")
        for a in APOS_FORMS:
            variants.add(norm.replace("'", a))
    return list(variants)


class Database:
    def __init__(self, db_path: str = "marketplace.db"):
        self.db_path = db_path
        # Backend tanlovi: DB_BACKEND=postgres -> PostgreSQL shim, aks holda SQLite.
        self.backend = (os.getenv("DB_BACKEND") or "sqlite").strip().lower()
        self.pg_dsn = os.getenv("DATABASE_URL")
        if self.backend == "postgres" and not self.pg_dsn:
            raise SystemExit("DB_BACKEND=postgres, lekin DATABASE_URL .env'da yo'q.")
        self._local = threading.local()   # har bir thread o'z ulanishiga ega
        self.init_db()

    def get_connection(self):
        """Thread-safe ulanish. Har bir thread bitta ulanishni qayta ishlatadi.
        Backend'ga qarab SQLite yoki PostgreSQL (shim orqali) qaytaradi."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            if self.backend == "postgres":
                import db_backend
                conn = db_backend.connect(self.pg_dsn)
            else:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                # Yozish unumdorligini oshirish uchun
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self):
        """Joriy thread ulanishini yopadi (odatda kerak emas)."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            self._local.conn = None

    def backup(self, backup_path: str) -> bool:
        """marketplace.db ni backup_path ga nusxalaydi. Muvaffaqiyatli bo'lsa True."""
        if self.backend == "postgres":
            # PostgreSQL backup'i pg_dump orqali qilinadi (alohida cron) — bu yerda emas.
            logging.info("PG backend: backup pg_dump orqali (bu metod o'tkazib yuborildi).")
            return False
        try:
            src = self.db_path
            # WAL rejimida to'liq consistent backup uchun sqlite3 backup API ishlatamiz
            src_conn = sqlite3.connect(src)
            dst_conn = sqlite3.connect(backup_path)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            return True
        except Exception as e:
            import logging
            logging.error(f"DB backup xatosi: {e}")
            return False

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                phone_number TEXT,
                name TEXT,
                role TEXT CHECK(role IN ('buyer', 'seller', 'admin')),
                shop_name TEXT,
                shop_address TEXT,
                shop_landmark TEXT,
                shop_lat REAL,
                shop_lon REAL,
                working_days TEXT,
                working_hours TEXT,
                telegram_username TEXT,
                is_verified BOOLEAN DEFAULT 0,
                is_blocked BOOLEAN DEFAULT 0,
                is_approved BOOLEAN DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Mavjud jadvalga ustun qo'shish (eski DB uchun)
        for col, defn in [
            ("is_approved", "BOOLEAN DEFAULT 0"),
            ("referral_code", "TEXT"),
            ("referred_by", "INTEGER"),
            ("referral_count", "INTEGER DEFAULT 0"),
            ("shop_landmark", "TEXT"),
            ("working_days", "TEXT"),
            ("working_hours", "TEXT"),
            ("telegram_username", "TEXT"),
            ("shop_lat", "REAL"),
            ("shop_lon", "REAL"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass

        # Eslatma: orders/products jadvallari uchun migratsiyalar ushbu jadvallar
        # YARATILGANDAN KEYIN bajariladi (pastdagi "MIGRATSIYALAR" blokiga qarang).
        # Avval bu yerda turardi, lekin jadvallar hali yaratilmaganidan toza bazada
        # ishlamasdi.

        # Mavjud foydalanuvchilarda referral_code yo'q bo'lsa — avtomatik yaratamiz
        import random, string
        cursor.execute("SELECT id FROM users WHERE referral_code IS NULL OR referral_code = ''")
        users_without_code = cursor.fetchall()
        for row in users_without_code:
            uid = row[0]
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                cursor.execute("SELECT id FROM users WHERE referral_code=?", (code,))
                if not cursor.fetchone():
                    break
            try:
                cursor.execute("UPDATE users SET referral_code=? WHERE id=?", (code, uid))
            except Exception:
                pass
        if users_without_code:
            conn.commit()

        # Users jadvaliga region_id ustuni
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN region_id INTEGER")
            conn.commit()
        except Exception:
            pass

        # Sotuvchi to'lov ma'lumotlari
        for col, defn in [
            ("card_number", "TEXT"),       # 16 raqamli karta raqami
            ("card_owner",  "TEXT"),       # Karta egasi ismi
            ("card_type",   "TEXT"),       # 'uzcard' | 'humo' | 'visa' | 'mastercard'
            ("language",    "TEXT DEFAULT 'uz'"),  # 'uz' | 'ru'
            ("channel_id",  "TEXT"),       # Sotuvchining shaxsiy kanali (post avtomatik shu yerga ham boradi)
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass
        conn.commit()

        # Eslatma: products.region_id va products.status migratsiyalari ham
        # jadval yaratilgandan KEYIN bajariladi (pastdagi "MIGRATSIYALAR" blokiga qarang).

        conn.commit()
        # conn.close() OLIB TASHLANDI — thread-local ulanish yopilmasin

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                emoji TEXT,
                description TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_attributes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                attr_key   TEXT NOT NULL,
                attr_value TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                UNIQUE(product_id, attr_key)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_attribute_templates (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id  INTEGER NOT NULL,
                attr_key     TEXT NOT NULL,
                attr_label   TEXT NOT NULL,
                attr_type    TEXT DEFAULT 'text',
                is_required  BOOLEAN DEFAULT 0,
                hint         TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
                UNIQUE(category_id, attr_key)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                category_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                image_url TEXT,
                in_stock BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (seller_id) REFERENCES users(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price REAL NOT NULL,
                status TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending','confirmed','delivered','cancelled')),
                delivery_address TEXT,
                buyer_lat REAL,
                buyer_lon REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (buyer_id) REFERENCES users(id),
                FOREIGN KEY (seller_id) REFERENCES users(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

        # Mahsulot o'chirish audit jurnali — mahsulot o'chirilganda (jismonan yoki
        # 'purged') uning to'liq nusxasi + kim/qachon o'chirgani saqlanadi. Bahsli
        # holatlarni tekshirishda foydalaniladi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                seller_id INTEGER,
                seller_name TEXT,
                shop_name TEXT,
                name TEXT,
                price REAL,
                category_name TEXT,
                description TEXT,
                stock_count INTEGER,
                status_before TEXT,
                order_count INTEGER,
                action TEXT,                 -- 'deleted' (jismonan) | 'purged' (yashirildi)
                deleted_by INTEGER,
                deleted_by_role TEXT,        -- 'seller' | 'admin'
                product_created_at TIMESTAMP,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Nizo yozishmalari — admin ↔ xaridor/sotuvchi (bahs uchun audit).
        # ALOHIDA jadval: oddiy 'messages' xaridor↔sotuvchi uchun umumiy ko'rinish,
        # bu yerda esa admin'ning har bir tomon bilan maxfiy suhbati saqlanadi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dispute_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                party TEXT,            -- suhbat tomoni: 'buyer' | 'seller'
                sender_role TEXT,      -- 'admin' | 'buyer' | 'seller'
                sender_id INTEGER,
                sender_name TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Rejalashtirilgan reklama postlari — sotuvchi/xodim mahsulotni belgilangan
        # sana va soatda avtomatik sotuvga qo'yishni rejalashtirsa, shu yerda saqlanadi.
        # Joblar XOTIRADA bo'lgani uchun restartda yo'qoladi — bu jadval ularni tiklash
        # manbai bo'ladi (get_pending_scheduled_posts orqali). scheduled_at — UTC.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,        -- do'kon EGASI
                created_by INTEGER,                -- rejani tuzgan xodim/ega user id
                scheduled_at TIMESTAMP NOT NULL,   -- UTC: 'YYYY-MM-DD HH:MM:SS'
                status TEXT DEFAULT 'pending',     -- pending | posted | cancelled | failed
                caption TEXT,                      -- preview'dagi AYNAN reklama matni
                parse_mode TEXT,
                image_id TEXT,                     -- preview dizayn rasmi (file_id)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (seller_id) REFERENCES users(id)
            )
        """)

        # Avto qayta-reklama — mahsulotni kuniga BIR MARTA, sotuvchi tanlagan soatda
        # kanal/guruhlarga qayta chiqaradi (yangi a'zolar ko'rsin). Eski post o'chirib,
        # yangisi chiqariladi (kanal toza qoladi). Joblar xotirada — restartda bu
        # jadvaldan (get_active_auto_reposts) tiklanadi. hour — Toshkent local soati.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_reposts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL UNIQUE,   -- bitta mahsulotga bitta avto-reklama
                seller_id INTEGER NOT NULL,           -- do'kon EGASI
                created_by INTEGER,                   -- yoqgan xodim/ega user id
                hour INTEGER NOT NULL,                -- 0..23 (Toshkent vaqti)
                caption TEXT,                         -- preview'dagi AYNAN reklama matni
                parse_mode TEXT,
                image_id TEXT,                        -- preview dizayn rasmi (file_id)
                last_message_ids TEXT,                -- JSON: [{"chat_id":..,"message_id":..}]
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,                 -- UTC: shu vaqtdan keyin avto-to'xtaydi
                last_run_at TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (seller_id) REFERENCES users(id)
            )
        """)

        # Umumiy kalit-qiymat jadvali (yengil meta-ma'lumot uchun). Masalan kunlik
        # backup'ni bir martagina yuborish kafolati (ikki instans bo'lsa ham).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # ===== MIGRATSIYALAR (jadvallar yaratilgandan KEYIN) =====
        # Eski bazada bu ustunlar allaqachon mavjud -> ALTER xato beradi va e'tiborsiz qoldiriladi
        # (hech narsa o'zgarmaydi). Toza (yangi) bazada esa ustunlar shu yerda qo'shiladi.
        _migrations = [
            ("orders",   "payment_method", "TEXT"),               # 'cash' | 'card' | 'click'
            ("orders",   "delivery_type",  "TEXT"),               # 'delivery' | 'pickup'
            ("orders",   "order_group_id", "TEXT"),               # savat (cart) — bir buyurtmadagi bir nechta mahsulotni bog'laydi (NULL = yakka buyurtma)
            ("orders",   "cancel_state",   "TEXT"),               # NULL=normal | 'requested'=bekor so'raldi | 'disputed'=admin hakamligida
            ("orders",   "cancel_reason",  "TEXT"),               # bekor qilish sababi (matn)
            ("orders",   "cancel_by",      "TEXT"),               # bekorni boshlagan tomon: 'buyer' | 'seller'
            ("orders",   "auto_cancel_at",    "TIMESTAMP"),       # UTC: avto-bekor muddati (real teskari sanoq shu vaqtga bog'langan)
            ("orders",   "notify_chat_id",    "INTEGER"),         # sotuvchi (ega) bildirishnoma xabari chat_id
            ("orders",   "notify_message_id", "INTEGER"),         # sotuvchi bildirishnoma message_id (jonli sanoq shuni tahrirlaydi)
            ("orders",   "notify_is_caption", "INTEGER"),         # 1 = rasm captionini tahrirlash, 0 = matn xabarini
            ("orders",   "notify_caption",    "TEXT"),            # bildirishnomaning statik qismi (sanoq qatorisiz)
            ("orders",   "settlement_type",   "TEXT"),            # berishdagi to'lov holati: 'paid' | 'debt' | 'installment'
            ("orders",   "amount_paid",       "REAL"),            # haqiqatda to'langan summa (berish paytida)
            ("orders",   "amount_due",        "REAL"),            # qolgan qarz summasi (0 = qarz yo'q)
            ("orders",   "settled_at",        "TIMESTAMP"),       # qarz to'liq yopilgan vaqt (NULL = ochiq)
            ("orders",   "buyer_received",    "INTEGER"),         # 1 = xaridor «oldim» bosgan, lekin sotuvchi to'lovni hali belgilamagan (status hali 'confirmed')
            ("orders",   "notify_pending",    "INTEGER DEFAULT 0"),  # 1 = Mini App yaratdi, bot sotuvchiga xabar yuborishi kerak (fon job)
            ("products", "stock_count",    "INTEGER"),            # NULL = cheksiz
            ("products", "region_id",      "INTEGER"),            # do'kon hududi
            ("products", "status",         "TEXT DEFAULT 'active'"),  # active|reserve|deleted
            ("reviews",  "product_id",     "INTEGER"),            # baho qaysi mahsulotga
            ("reviews",  "product_rating", "INTEGER"),            # mahsulot uchun 1-5
            ("reviews",  "seller_reply",   "TEXT"),               # sotuvchining ochiq javobi (NULL = javob yo'q)
            ("reviews",  "replied_at",     "TIMESTAMP"),          # javob yozilgan vaqt
            ("product_attributes", "attr_label", "TEXT"),         # ko'rsatish uchun yorliq (AI savollar uchun — shablon yo'q)
        ]
        for _tbl, _col, _defn in _migrations:
            try:
                cursor.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_defn}")
            except Exception:
                pass
        # status yangi qo'shilgan bo'lsa — mavjud mahsulotlarni in_stock asosida to'ldiramiz.
        # (Eski bazada status to'la bo'lib ketgan, shuning uchun hech bir qator o'zgarmaydi.)
        try:
            cursor.execute("UPDATE products SET status='active' WHERE status IS NULL AND in_stock=1")
            cursor.execute("UPDATE products SET status='reserve' WHERE status IS NULL AND in_stock=0")
        except Exception:
            pass
        # Eski baholarni mahsulotga bog'lash: yangilanishdan OLDIN qoldirilgan baholarda
        # product_id bo'sh edi -> izohlar mahsulot ostida ko'rinmasdi. orders'dan to'ldiramiz.
        try:
            cursor.execute("""
                UPDATE reviews
                SET product_id = (SELECT o.product_id FROM orders o WHERE o.id = reviews.order_id)
                WHERE product_id IS NULL
            """)
            # Eski yagona reytingni mahsulot reytingi sifatida ham qo'llaymiz
            # (yangi baholarda product_rating doim to'ldiriladi, shuning uchun ular o'zgarmaydi).
            cursor.execute("""
                UPDATE reviews
                SET product_rating = rating
                WHERE product_rating IS NULL AND rating IS NOT NULL
            """)
        except Exception:
            pass
        conn.commit()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                buyer_id INTEGER NOT NULL,
                rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                product_id INTEGER,
                product_rating INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (seller_id) REFERENCES users(id),
                FOREIGN KEY (buyer_id) REFERENCES users(id)
            )
        """)

        # ===== seller_requests divergensiyasini tuzatish (faqat SQLite, idempotent) =====
        # Eski bazada seller_requests boshqa schema bilan yaratilgan (telegram_id, name,
        # phone_number, ...). Hozirgi kod esa user_id/admin_note kutadi. Jadval
        # CREATE IF NOT EXISTS bo'lgani uchun eski schema o'z holicha qolib, sotuvchi
        # so'rovi yaratish buzilgan edi. Bu yerda to'g'rilaymiz.
        # (PostgreSQL'da bu kerak emas — PG to'g'rilangan SQLite'dan ko'chiriladi.)
        if self.backend != "postgres":
            try:
                _sr_cols = [r[1] for r in cursor.execute("PRAGMA table_info(seller_requests)").fetchall()]
                if _sr_cols and "user_id" not in _sr_cols:
                    _sr_cnt = cursor.execute("SELECT COUNT(*) FROM seller_requests").fetchone()[0]
                    if _sr_cnt == 0:
                        # Bo'sh — shunchaki o'chiramiz, pastdagi CREATE to'g'ri qayta yaratadi
                        cursor.execute("DROP TABLE seller_requests")
                    else:
                        # Ma'lumot bor — zaxiralab qo'yamiz, CREATE'dan keyin ko'chiramiz
                        cursor.execute("ALTER TABLE seller_requests RENAME TO seller_requests_old")
                    conn.commit()
            except Exception as e:
                logging.error(f"seller_requests divergensiya tekshiruvi xatosi: {e}")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seller_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Zaxiralangan eski seller_requests'dan ma'lumotni yangi schema'ga ko'chirish
        # (telegram_id -> users.id). Faqat eski jadval qolgan bo'lsa ishlaydi.
        if self.backend != "postgres":
            try:
                _old = cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='seller_requests_old'"
                ).fetchone()
                if _old:
                    for r in cursor.execute(
                        "SELECT telegram_id, status, created_at FROM seller_requests_old"
                    ).fetchall():
                        _urow = cursor.execute(
                            "SELECT id FROM users WHERE telegram_id=?", (r[0],)
                        ).fetchone()
                        if _urow:
                            cursor.execute(
                                "INSERT INTO seller_requests (user_id, status, created_at) VALUES (?,?,?)",
                                (_urow[0], r[1] or 'pending', r[2])
                            )
                    cursor.execute("DROP TABLE seller_requests_old")
                    conn.commit()
            except Exception as e:
                logging.error(f"seller_requests eski ma'lumotni ko'chirish xatosi: {e}")

        # Bitta mahsulot uchun bir nechta rasm (4 tagacha).
        # Birinchi rasm (position=0) products.image_url bilan ham sinxron saqlanadi —
        # shunda eski kod (ro'yxat, havola) ham ishlayveradi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        try:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_images_pid "
                "ON product_images(product_id, position)"
            )
        except Exception:
            pass

        # ===== Sotuvchi kanallari (bitta sotuvchi -> ko'p kanal) =====
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seller_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(seller_id, channel_id),
                FOREIGN KEY (seller_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        # seller_channels ga holat ustunlari (idempotent migratsiya)
        for col, defn in [
            ("is_active",     "INTEGER DEFAULT 1"),  # 1 = faol, 0 = yetim (bot kanalda yo'q/huquqsiz)
            ("last_error",    "TEXT"),               # oxirgi post xatosi qisqacha
            ("last_error_at", "TIMESTAMP"),          # oxirgi xato vaqti
            ("chat_type",     "TEXT DEFAULT 'channel'"),  # 'channel' yoki 'group' (superguruh ham 'group')
            ("is_forum",      "INTEGER DEFAULT 0"),   # 1 = mavzuli (forum) guruh
            ("thread_id",     "TEXT"),                # forum guruhda post boradigan topic (message_thread_id)
        ]:
            try:
                cursor.execute(f"ALTER TABLE seller_channels ADD COLUMN {col} {defn}")
            except Exception:
                pass
        conn.commit()

        # Eski yagona users.channel_id ni yangi jadvalga ko'chiramiz (bir martalik, idempotent)
        try:
            cursor.execute("SELECT id, channel_id FROM users WHERE channel_id IS NOT NULL AND channel_id != ''")
            for _row in cursor.fetchall():
                try:
                    cursor.execute(
                        "INSERT OR IGNORE INTO seller_channels (seller_id, channel_id) VALUES (?, ?)",
                        (_row[0], str(_row[1]))
                    )
                except Exception:
                    pass
        except Exception:
            pass

        conn.commit()

        # ===== MULTI-SOTUVCHI: bitta do'kon -> ko'p xodim =====
        # Do'kon identity'si alohida jadvalda. MUHIM: products/orders.seller_id HAR DOIM
        # do'kon EGASIga ishora qiladi (eski xaridor tomoni, reyting, brending buzilmasin);
        # xodim kimligi products.created_by + shop_staff orqali kuzatiladi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL UNIQUE,
                name TEXT,
                address TEXT,
                landmark TEXT,
                lat REAL,
                lon REAL,
                region_id INTEGER,
                working_days TEXT,
                working_hours TEXT,
                payment_mode TEXT DEFAULT 'shop',   -- 'shop' | 'staff'
                card_number TEXT,
                card_owner TEXT,
                card_type TEXT,
                moderation TEXT DEFAULT 'direct',    -- 'direct' | 'owner_approve' (admin sozlaydi)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shop_staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL UNIQUE,
                staff_role TEXT DEFAULT 'staff',     -- 'owner' | 'manager' | 'staff'
                department TEXT,
                category_id INTEGER,
                perm_add_product   INTEGER DEFAULT 1,
                perm_confirm_orders INTEGER DEFAULT 1,
                perm_edit_price    INTEGER DEFAULT 1,
                perm_reply_reviews INTEGER DEFAULT 1,
                card_number TEXT,
                card_owner TEXT,
                card_type TEXT,
                is_active INTEGER DEFAULT 0,          -- 0 = kutilmoqda, 1 = faol
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shop_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                code TEXT NOT NULL UNIQUE,
                department TEXT,
                created_by INTEGER,
                used_by INTEGER,
                is_used INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
            )
        """)
        # Yangi ustunlar (idempotent)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN shop_id INTEGER")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN created_by INTEGER")
        except Exception:
            pass
        conn.commit()

        # Backfill (bir martalik, idempotent): har bir mavjud sotuvchi uchun do'kon yaratamiz
        try:
            cursor.execute("""
                SELECT id, shop_name, shop_address, shop_landmark, shop_lat, shop_lon,
                       region_id, working_days, working_hours,
                       card_number, card_owner, card_type
                FROM users WHERE role='seller'
            """)
            for u in cursor.fetchall():
                u = dict(u)
                # Do'kon allaqachon bormi?
                cursor.execute("SELECT id FROM shops WHERE owner_user_id=?", (u['id'],))
                srow = cursor.fetchone()
                if srow:
                    shop_id = srow[0]
                else:
                    cursor.execute("""
                        INSERT INTO shops (owner_user_id, name, address, landmark, lat, lon,
                                           region_id, working_days, working_hours,
                                           card_number, card_owner, card_type)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (u['id'], u.get('shop_name'), u.get('shop_address'), u.get('shop_landmark'),
                          u.get('shop_lat'), u.get('shop_lon'), u.get('region_id'),
                          u.get('working_days'), u.get('working_hours'),
                          u.get('card_number'), u.get('card_owner'), u.get('card_type')))
                    shop_id = cursor.lastrowid
                # users.shop_id
                cursor.execute("UPDATE users SET shop_id=? WHERE id=? AND (shop_id IS NULL)",
                               (shop_id, u['id']))
                # owner shop_staff yozuvi
                cursor.execute("SELECT id FROM shop_staff WHERE user_id=?", (u['id'],))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO shop_staff (shop_id, user_id, staff_role, is_active, added_by)
                        VALUES (?,?,'owner',1,?)
                    """, (shop_id, u['id'], u['id']))
            # products.created_by ni egaga (seller_id) to'ldiramiz
            cursor.execute("UPDATE products SET created_by=seller_id WHERE created_by IS NULL")
            conn.commit()
        except Exception as e:
            logging.error(f"shops backfill xatosi: {e}")

        self.insert_default_categories()

    def insert_default_categories(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        # (name, emoji, description)
        cats = [
            ("Ichimliklar", "🥤", "Turli ichimliklar"),
            ("Ehtiyot Qismlar", "🔧", "Avtomobil ehtiyot qismlari"),
            ("Xojalik Mollari", "🏠", "Uy-ro'zg'or buyumlari"),
            ("Elektronika", "📱", "Elektronika va gadjetlar"),
            ("Kiyimlar", "👕", "Kiyim-kechaklar"),
            ("Oziq-ovqat", "🍎", "Oziq-ovqat mahsulotlari"),
            ("Taomlar", "🍽️", "Turli taomlar"),
            # Yangi zamonaviy sohalar
            ("Go'zallik va parfyumeriya", "💄", "Kosmetika, parfyumeriya, parvarish"),
            ("Salomatlik va dorixona", "💊", "Dori, vitamin, tibbiy mahsulotlar"),
            ("Bolalar mahsulotlari", "🧸", "O'yinchoq, bolalar kiyimi va anjomlari"),
            ("Sport va dam olish", "⚽", "Sport anjomlari va dam olish"),
            ("Uy va mebel", "🛋️", "Mebel va uy jihozlari"),
            ("Kitob va kanstovarlar", "📚", "Kitoblar, daftar, qalam"),
            ("Qurilish mollari", "🧱", "Qurilish va ta'mirlash mollari"),
            ("Hayvonlar uchun", "🐾", "Uy hayvonlari uchun mahsulotlar"),
            ("Gul va sovg'alar", "💐", "Gullar va sovg'alar"),
        ]
        for name, emoji, desc in cats:
            cursor.execute(
                "INSERT OR IGNORE INTO categories (name, emoji, description) VALUES (?,?,?)",
                (name, emoji, desc)
            )
        conn.commit()

        # Kategoriya atribut shablonlari (bir marta)
        cursor.execute("SELECT COUNT(*) FROM category_attribute_templates")
        if cursor.fetchone()[0] == 0:
            # Har bir kategoriya uchun tegishli atributlar
            templates = {
                "Kiyimlar":      [
                    ("size",   "O'lcham",      "text",   1, "S, M, L, XL, XXL"),
                    ("color",  "Rangi",         "text",   1, "Qora, Oq, Ko'k..."),
                    ("brand",  "Brend",          "text",   0, "Nike, Adidas, Zara..."),
                    ("gender", "Jinsi",          "select", 0, "Erkak/Ayol/Uniseks"),
                    ("season", "Fasli",          "text",   0, "Bahor, Yoz, Kuz, Qish"),
                ],
                "Elektronika":   [
                    ("brand",     "Brend",       "text",   1, "Samsung, Apple, Xiaomi..."),
                    ("model",     "Model",       "text",   1, "Galaxy S24, iPhone 15..."),
                    ("condition", "Holati",      "select", 1, "Yangi/Ishlatilgan/Qadoqda"),
                    ("warranty",  "Kafolat",     "text",   0, "6 oy, 1 yil, Yo'q"),
                    ("memory",    "Xotira",      "text",   0, "128GB, 256GB..."),
                ],
                "Ehtiyot Qismlar": [
                    ("car_make",  "Avtomobil",   "text",   1, "Nexia, Cobalt, Malibu..."),
                    ("car_year",  "Yili",        "number", 0, "2010, 2018..."),
                    ("part_type", "Qism turi",   "text",   1, "Dvigatel, Korobka..."),
                    ("condition", "Holati",      "select", 0, "Yangi/Ishlatilgan"),
                    ("oem",       "OEM/Kopiya",  "text",   0, "Original, Kopiya"),
                ],
                "Oziq-ovqat":    [
                    ("weight",   "Og'irligi",   "text",   0, "1kg, 500g, 5L..."),
                    ("freshness","Yangiligi",    "text",   0, "Bugungi, Ertangi..."),
                    ("origin",   "Kelib chiqishi","text",  0, "O'zbekiston, Import..."),
                ],
                "Taomlar":       [
                    ("serving",  "Porsiya",      "text",   0, "1 kishi, 2-3 kishi..."),
                    ("spicy",    "Achchiqlik",   "select", 0, "Achchiq/O'rta/Achchiq emas"),
                    ("ready_in", "Tayyor vaqti", "text",   0, "Hozir tayyor, 30 daqiqa..."),
                ],
                "Xojalik Mollari": [
                    ("brand",    "Brend",        "text",   0, "Ariel, Domestos..."),
                    ("weight",   "Hajmi/Og'irligi","text", 0, "1L, 5kg..."),
                ],
                "Ichimliklar":   [
                    ("volume",   "Hajmi",        "text",   1, "0.5L, 1L, 1.5L..."),
                    ("cold",     "Sovuq/Issiq",  "select", 0, "Sovuq/Issiq/Ikkalasi"),
                ],
            }
            for cat_name, attrs in templates.items():
                cursor.execute("SELECT id FROM categories WHERE name=?", (cat_name,))
                row = cursor.fetchone()
                if not row:
                    continue
                cat_id = row[0]
                for attr_key, attr_label, attr_type, required, hint in attrs:
                    cursor.execute("""
                        INSERT OR IGNORE INTO category_attribute_templates
                        (category_id, attr_key, attr_label, attr_type, is_required, hint)
                        VALUES (?,?,?,?,?,?)
                    """, (cat_id, attr_key, attr_label, attr_type, required, hint))
            conn.commit()

        # Hududlarni bir marta yuklash — kategoriyalardan keyin
        self.init_regions()

    # ===== USER =====
    def create_user(self, telegram_id, phone_number=None, name=None, role=None):
        import random, string
        ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (telegram_id, phone_number, name, role, referral_code) VALUES (?,?,?,?,?)",
            (telegram_id, phone_number, name, role, ref_code)
        )
        uid = cursor.lastrowid
        conn.commit()
        return uid

    def get_user_by_telegram_id(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_referral_code(self, code):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE referral_code=?", (code,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_users(self, role=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if role:
            cursor.execute("SELECT * FROM users WHERE role=? ORDER BY created_at DESC", (role,))
        else:
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def update_user(self, user_id, **kwargs):
        if not kwargs:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        values = list(kwargs.values()) + [user_id]
        cursor.execute(
            f"UPDATE users SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            values
        )
        conn.commit()

    def block_user(self, user_id):
        self.update_user(user_id, is_blocked=1)

    def unblock_user(self, user_id):
        self.update_user(user_id, is_blocked=0)

    def increment_referral_count(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET referral_count = referral_count + 1 WHERE id=?",
            (user_id,)
        )
        conn.commit()

    # ===== SHOPS / MULTI-SOTUVCHI =====
    def create_shop(self, owner_user_id, **fields):
        """Egasi uchun do'kon yaratadi (yoki mavjudini qaytaradi). Owner uchun shop_staff
        yozuvi ham yaratiladi, users.shop_id o'rnatiladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM shops WHERE owner_user_id=?", (owner_user_id,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cols = ['owner_user_id'] + list(fields.keys())
        vals = [owner_user_id] + list(fields.values())
        placeholders = ",".join("?" for _ in cols)
        cursor.execute(f"INSERT INTO shops ({','.join(cols)}) VALUES ({placeholders})", vals)
        shop_id = cursor.lastrowid
        cursor.execute("UPDATE users SET shop_id=? WHERE id=?", (shop_id, owner_user_id))
        cursor.execute(
            "INSERT OR IGNORE INTO shop_staff (shop_id, user_id, staff_role, is_active, added_by) "
            "VALUES (?,?,'owner',1,?)",
            (shop_id, owner_user_id, owner_user_id)
        )
        conn.commit()
        return shop_id

    def get_shop_by_id(self, shop_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shops WHERE id=?", (shop_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_shop_by_owner(self, owner_user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shops WHERE owner_user_id=?", (owner_user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_shop_for_user(self, user_id):
        """Foydalanuvchi (ega yoki xodim) tegishli do'konni qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.* FROM shops s
            JOIN shop_staff st ON st.shop_id=s.id
            WHERE st.user_id=?
        """, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_shop(self, shop_id, **kwargs):
        if not kwargs:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        cursor.execute(f"UPDATE shops SET {set_clause} WHERE id=?",
                       list(kwargs.values()) + [shop_id])
        conn.commit()

    def get_all_shops(self):
        """Admin uchun — barcha do'konlar + egasi ismi va xodimlar soni."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, u.name as owner_name, u.telegram_id as owner_tg,
                   (SELECT COUNT(*) FROM shop_staff st WHERE st.shop_id=s.id) as staff_count
            FROM shops s LEFT JOIN users u ON s.owner_user_id=u.id
            ORDER BY s.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def resolve_owner_id(self, user_id):
        """Xodim user_id'sidan do'kon EGASIning user_id'sini qaytaradi.
        Xodim/do'kon topilmasa — o'zini qaytaradi (eski xulq)."""
        shop = self.get_shop_for_user(user_id)
        return shop['owner_user_id'] if shop else user_id

    # ===== SHOP STAFF =====
    def add_staff(self, shop_id, user_id, staff_role='staff', department=None,
                  category_id=None, is_active=0, added_by=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO shop_staff (shop_id, user_id, staff_role, department,
                                              category_id, is_active, added_by)
            VALUES (?,?,?,?,?,?,?)
        """, (shop_id, user_id, staff_role, department, category_id, is_active, added_by))
        cursor.execute("UPDATE users SET shop_id=? WHERE id=?", (shop_id, user_id))
        conn.commit()
        cursor.execute("SELECT id FROM shop_staff WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_staff_by_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shop_staff WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_shop_staff(self, shop_id, include_owner=True):
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT st.*, u.name, u.telegram_id, u.telegram_username, u.phone_number
            FROM shop_staff st JOIN users u ON st.user_id=u.id
            WHERE st.shop_id=?
        """
        if not include_owner:
            sql += " AND st.staff_role != 'owner'"
        sql += " ORDER BY st.staff_role='owner' DESC, st.created_at ASC"
        cursor.execute(sql, (shop_id,))
        return [dict(r) for r in cursor.fetchall()]

    def update_staff(self, staff_id, **kwargs):
        if not kwargs:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k}=?" for k in kwargs])
        cursor.execute(f"UPDATE shop_staff SET {set_clause} WHERE id=?",
                       list(kwargs.values()) + [staff_id])
        conn.commit()

    def set_staff_active(self, staff_id, active):
        self.update_staff(staff_id, is_active=1 if active else 0)

    def remove_staff(self, staff_id):
        """Xodimni do'kondan chiqaradi. Mahsulot/buyurtmalari egada qoladi (seller_id egada)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, staff_role FROM shop_staff WHERE id=?", (staff_id,))
        row = cursor.fetchone()
        if not row or row[1] == 'owner':
            return False  # egani o'chirib bo'lmaydi
        uid = row[0]
        cursor.execute("DELETE FROM shop_staff WHERE id=?", (staff_id,))
        cursor.execute("UPDATE users SET shop_id=NULL WHERE id=?", (uid,))
        conn.commit()
        return True

    # ===== SHOP INVITES =====
    def create_invite(self, shop_id, department=None, created_by=None, expires_at=None):
        import random, string
        conn = self.get_connection()
        cursor = conn.cursor()
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
            cursor.execute("SELECT id FROM shop_invites WHERE code=?", (code,))
            if not cursor.fetchone():
                break
        cursor.execute("""
            INSERT INTO shop_invites (shop_id, code, department, created_by, expires_at)
            VALUES (?,?,?,?,?)
        """, (shop_id, code, department, created_by, expires_at))
        conn.commit()
        return code

    def get_invite_by_code(self, code):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shop_invites WHERE code=?", (code,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def mark_invite_used(self, code, used_by):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE shop_invites SET is_used=1, used_by=? WHERE code=?",
                       (used_by, code))
        conn.commit()

    def get_active_invites(self, shop_id):
        """Hali ishlatilmagan (bekor qilinmagan) takliflar."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM shop_invites WHERE shop_id=? AND COALESCE(is_used,0)=0 "
            "ORDER BY created_at DESC", (shop_id,))
        return [dict(r) for r in cursor.fetchall()]

    def delete_invite(self, invite_id, shop_id=None):
        """Taklifni bekor qiladi (o'chiradi). shop_id berilsa — faqat shu do'kon taklifini."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if shop_id is not None:
            cursor.execute("DELETE FROM shop_invites WHERE id=? AND shop_id=?", (invite_id, shop_id))
        else:
            cursor.execute("DELETE FROM shop_invites WHERE id=?", (invite_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ===== STAFF STATISTIKA (created_by bo'yicha) =====
    def get_staff_stats(self, staff_user_id):
        """Bitta xodim bo'yicha statistika — mahsulotlari (created_by) va ulardan
        kelgan buyurtmalar kesimida."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN o.status='pending' THEN 1 END) as pending_count,
                COUNT(CASE WHEN o.status='confirmed' THEN 1 END) as confirmed_count,
                COUNT(CASE WHEN o.status='delivered' THEN 1 END) as delivered_count,
                COUNT(CASE WHEN o.status='cancelled' THEN 1 END) as cancelled_count,
                COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.total_price ELSE 0 END),0) as total_revenue
            FROM orders o JOIN products p ON o.product_id=p.id
            WHERE p.created_by=?
        """, (staff_user_id,))
        total = dict(cursor.fetchone() or {})
        cursor.execute("SELECT COUNT(*) FROM products WHERE created_by=?", (staff_user_id,))
        products_count = cursor.fetchone()[0]
        return {
            'total_orders': total.get('total_orders', 0),
            'pending': total.get('pending_count', 0),
            'confirmed': total.get('confirmed_count', 0),
            'delivered': total.get('delivered_count', 0),
            'cancelled': total.get('cancelled_count', 0),
            'total_revenue': total.get('total_revenue', 0),
            'products_count': products_count,
        }

    def get_shop_staff_performance(self, shop_id):
        """Do'kondagi har bir xodim bo'yicha qisqacha ko'rsatkich (mahsulot soni,
        sotilgan dona, daromad)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT st.user_id, u.name, st.staff_role, st.department, st.is_active,
                   (SELECT COUNT(*) FROM products p WHERE p.created_by=st.user_id) as products_count,
                   (SELECT COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.quantity ELSE 0 END),0)
                      FROM orders o JOIN products p ON o.product_id=p.id WHERE p.created_by=st.user_id) as sold,
                   (SELECT COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.total_price ELSE 0 END),0)
                      FROM orders o JOIN products p ON o.product_id=p.id WHERE p.created_by=st.user_id) as revenue
            FROM shop_staff st JOIN users u ON st.user_id=u.id
            WHERE st.shop_id=?
            ORDER BY st.staff_role='owner' DESC, revenue DESC
        """, (shop_id,))
        return [dict(r) for r in cursor.fetchall()]

    # ===== SELLER CHANNELS (ko'p kanal) =====
    def add_seller_channel(self, seller_id, channel_id, channel_title=None, chat_type=None,
                           is_forum=None, thread_id=None):
        """Sotuvchiga kanal yoki guruh qo'shadi. Allaqachon bo'lsa — sarlavhasini yangilaydi.
        chat_type: 'channel' yoki 'group' (superguruh ham 'group'). None bo'lsa o'zgartirilmaydi.
        is_forum: mavzuli (forum) guruh bo'lsa True. thread_id: forum'da post boradigan topic.
        Yangi qo'shilgan bo'lsa True, avval mavjud bo'lsa False qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM seller_channels WHERE seller_id=? AND channel_id=?",
            (seller_id, str(channel_id))
        )
        existing = cursor.fetchone()
        if existing:
            # Qayta ulanganda — faollashtiramiz va eski xatoni tozalaymiz
            sets = ["is_active=1", "last_error=NULL", "last_error_at=NULL"]
            params = []
            if channel_title:
                sets.append("channel_title=?")
                params.append(channel_title)
            if chat_type:
                sets.append("chat_type=?")
                params.append(chat_type)
            if is_forum is not None:
                sets.append("is_forum=?")
                params.append(1 if is_forum else 0)
            if thread_id is not None:
                sets.append("thread_id=?")
                params.append(str(thread_id))
            params.append(existing[0])
            cursor.execute(
                f"UPDATE seller_channels SET {', '.join(sets)} WHERE id=?",
                params
            )
            conn.commit()
            return False
        cursor.execute(
            "INSERT INTO seller_channels (seller_id, channel_id, channel_title, chat_type, is_forum, thread_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (seller_id, str(channel_id), channel_title, chat_type or 'channel',
             1 if is_forum else 0, str(thread_id) if thread_id is not None else None)
        )
        conn.commit()
        return True

    def set_seller_channel_thread(self, seller_id, channel_id, thread_id):
        """Forum guruh uchun post boradigan topic (message_thread_id) ni saqlaydi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE seller_channels SET thread_id=? WHERE seller_id=? AND channel_id=?",
            (str(thread_id) if thread_id is not None else None, seller_id, str(channel_id))
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_active_seller_channels(self, seller_id):
        """Faqat FAOL kanallar (post yuborish uchun). Yetim kanallar tashlab ketiladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM seller_channels WHERE seller_id=? AND COALESCE(is_active,1)=1 "
            "ORDER BY created_at ASC, id ASC",
            (seller_id,)
        )
        return [dict(r) for r in cursor.fetchall()]

    def deactivate_seller_channel(self, seller_id, channel_id, error=None):
        """Kanalni yetim deb belgilaydi (bot kanaldan chiqarilgan/huquqi yo'q)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE seller_channels SET is_active=0, last_error=?, "
            "last_error_at=CURRENT_TIMESTAMP WHERE seller_id=? AND channel_id=?",
            ((str(error)[:200] if error else None), seller_id, str(channel_id))
        )
        conn.commit()
        return cursor.rowcount > 0

    def find_channel_owners(self, channel_id, exclude_seller_id=None):
        """Shu channel_id ni ulagan boshqa sotuvchilar ro'yxati (#5 — ogohlantirish uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = ("SELECT sc.seller_id, u.shop_name, u.name, u.telegram_username "
               "FROM seller_channels sc JOIN users u ON sc.seller_id=u.id "
               "WHERE sc.channel_id=?")
        params = [str(channel_id)]
        if exclude_seller_id is not None:
            sql += " AND sc.seller_id != ?"
            params.append(exclude_seller_id)
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_channels(self, seller_id):
        """Sotuvchining barcha ulangan kanallari ro'yxati (eng eski birinchi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM seller_channels WHERE seller_id=? ORDER BY created_at ASC, id ASC",
            (seller_id,)
        )
        return [dict(r) for r in cursor.fetchall()]

    def get_all_seller_channels(self):
        """Admin uchun — barcha ulangan kanallar, sotuvchi ma'lumotlari bilan.
        Sotuvchi bo'yicha guruhlash uchun seller_id, keyin kanal yoshi bo'yicha tartiblanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sc.channel_id, sc.channel_title, sc.created_at,
                   COALESCE(sc.is_active,1) AS is_active, sc.last_error,
                   u.id AS seller_id, u.name AS seller_name, u.shop_name,
                   u.telegram_id, u.telegram_username, u.is_approved
            FROM seller_channels sc
            JOIN users u ON sc.seller_id = u.id
            ORDER BY u.shop_name COLLATE NOCASE ASC, sc.created_at ASC, sc.id ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def remove_seller_channel(self, seller_id, channel_id):
        """Sotuvchining bitta kanalini o'chiradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM seller_channels WHERE seller_id=? AND channel_id=?",
            (seller_id, str(channel_id))
        )
        conn.commit()

    def update_seller_channel_title(self, seller_id, channel_id, title):
        """Kanal sarlavhasini yangilaydi (ko'rsatish uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE seller_channels SET channel_title=? WHERE seller_id=? AND channel_id=?",
            (title, seller_id, str(channel_id))
        )
        conn.commit()

    # ===== SELLER REQUESTS =====
    def create_seller_request(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO seller_requests (user_id, status) VALUES (?,?)",
            (user_id, 'pending')
        )
        conn.commit()

    def get_pending_seller_requests(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sr.*, u.name, u.phone_number, u.shop_name, u.shop_address,
                   u.telegram_username, u.telegram_id
            FROM seller_requests sr
            JOIN users u ON sr.user_id = u.id
            WHERE sr.status='pending'
            ORDER BY sr.created_at ASC
        """)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def update_seller_request(self, request_id, status, admin_note=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE seller_requests SET status=?, admin_note=? WHERE id=?",
            (status, admin_note, request_id)
        )
        conn.commit()

    def get_seller_request_by_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM seller_requests WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    # ===== CATEGORIES =====
    def get_categories(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ===== PRODUCTS =====
    def create_product(self, seller_id, name, price, category_id=None, description=None,
                       image_url=None, stock_count=None, created_by=None, status=None):
        """Yangi mahsulot yaratadi. stock_count: None = cheksiz, butun son = sotuvga
        qo'yiladigan miqdor (0 ga tushganda mahsulot avtomatik zaxiraga o'tadi).
        seller_id = do'kon EGASI (brending/reyting shu bo'yicha); created_by = mahsulotni
        aslida joylagan xodim (default = seller_id). status berilsa o'rnatiladi
        (masalan 'pending_owner' — ega tasdig'ini kutayotgan)."""
        if created_by is None:
            created_by = seller_id
        conn = self.get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "INSERT INTO products (seller_id, name, price, category_id, description, image_url, stock_count, created_by, status) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (seller_id, name, price, category_id, description, image_url, stock_count, created_by, status)
            )
        else:
            cursor.execute(
                "INSERT INTO products (seller_id, name, price, category_id, description, image_url, stock_count, created_by) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (seller_id, name, price, category_id, description, image_url, stock_count, created_by)
            )
        pid = cursor.lastrowid
        conn.commit()
        return pid

    def get_products_by_seller(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name, c.emoji as category_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.seller_id=?
            ORDER BY p.created_at DESC
        """, (seller_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_all_products(self, include_hidden=True):
        """Barcha mahsulotlar. include_hidden=False bo'lsa — o'chirilgan
        ('deleted') va butunlay olib tashlangan ('purged') mahsulotlar chiqariladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        where = "" if include_hidden else \
            "WHERE COALESCE(p.status,'active') NOT IN ('deleted','purged')"
        cursor.execute(f"""
            SELECT p.*,
                   u.name as seller_name, u.shop_name,
                   c.name as category_name,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=p.seller_id) as avg_rating
            FROM products p
            LEFT JOIN users u ON p.seller_id=u.id
            LEFT JOIN categories c ON p.category_id=c.id
            {where}
            ORDER BY p.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def admin_search_products(self, query, limit=200):
        """Admin uchun — BARCHA mahsulotlarni nom/tavsif bo'yicha qidiradi
        (status/approval/in_stock filtri yo'q — nomaqbul yoki olib qo'yilganlar ham topiladi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        like = f"%{query}%"
        cursor.execute("""
            SELECT p.*, u.name as seller_name, u.shop_name, c.name as category_name
            FROM products p
            LEFT JOIN users u ON p.seller_id=u.id
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.name LIKE ? OR p.description LIKE ?
            ORDER BY p.created_at DESC
            LIMIT ?
        """, (like, like, limit))
        return [dict(r) for r in cursor.fetchall()]

    def search_products(self, query=None, category_id=None, min_price=None, max_price=None,
                        sort_by='rating', region_id=None, seller_id=None):
        """sort_by: 'rating' | 'price_asc' | 'price_desc' | 'newest'
        Transliteratsiya bilan qidiradi (lotin↔kirill).
        seller_id berilsa — faqat shu do'kon (sotuvchi) mahsulotlari (do'kon ichida AI qidiruv)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT p.*, c.name as category_name, c.emoji as category_emoji,
                   u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number, u.is_verified, u.region_id as seller_region_id,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=p.seller_id) as avg_rating,
                   (SELECT AVG(r2.product_rating) FROM reviews r2 WHERE r2.product_id=p.id AND r2.product_rating IS NOT NULL) as prod_avg_rating,
                   (SELECT COUNT(*) FROM reviews r3 WHERE r3.product_id=p.id AND r3.product_rating IS NOT NULL) as prod_review_count
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE p.in_stock=1 AND COALESCE(p.status,'active')='active' AND COALESCE(u.is_blocked,0)=0
                  AND (COALESCE(u.is_approved,0)=1 OR u.role='admin')
        """
        params = []
        if query:
            # Transliteratsiya variantlari bilan qidirish
            variants = generate_search_variants(query)
            if variants:
                like_clauses = []
                for v in variants:
                    like_clauses.append("(p.name LIKE ? OR p.description LIKE ?)")
                    params += [f"%{v}%", f"%{v}%"]
                sql += " AND (" + " OR ".join(like_clauses) + ")"
            else:
                sql += " AND (p.name LIKE ? OR p.description LIKE ?)"
                params += [f"%{query}%", f"%{query}%"]
        if category_id:
            sql += " AND p.category_id=?"
            params.append(category_id)
        if min_price is not None:
            sql += " AND p.price>=?"
            params.append(min_price)
        if max_price is not None:
            sql += " AND p.price<=?"
            params.append(max_price)
        if region_id:
            # Sotuvchi yoki mahsulotning hududi mos kelsin
            sql += " AND (u.region_id=? OR p.region_id=?)"
            params += [region_id, region_id]
        if seller_id:
            sql += " AND p.seller_id=?"
            params.append(seller_id)

        order_map = {
            'rating':     ' ORDER BY avg_rating DESC, p.created_at DESC',
            'price_asc':  ' ORDER BY p.price ASC',
            'price_desc': ' ORDER BY p.price DESC',
            'newest':     ' ORDER BY p.created_at DESC',
        }
        sql += order_map.get(sort_by, order_map['rating'])

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ===== ORDERS =====
    def create_order(self, buyer_id, seller_id, product_id, quantity, total_price,
                     delivery_address=None, buyer_lat=None, buyer_lon=None,
                     payment_method=None, delivery_type=None, order_group_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (buyer_id, seller_id, product_id, quantity,
                                total_price, delivery_address, buyer_lat, buyer_lon,
                                payment_method, delivery_type, order_group_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (buyer_id, seller_id, product_id, quantity, total_price,
              delivery_address, buyer_lat, buyer_lon, payment_method, delivery_type,
              order_group_id))
        oid = cursor.lastrowid
        conn.commit()
        return oid

    def mark_order_notify_pending(self, order_id):
        """Mini App yaratgan buyurtmani 'sotuvchiga xabar yuborilishi kerak' deb belgilaydi.
        Bot fon job'i (webapp_order_dispatch_job) buni ko'rib xabar/taymerni ishga tushiradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET notify_pending=1 WHERE id=?", (order_id,))
        conn.commit()

    def get_orders_awaiting_notify(self, limit=20):
        """Bot fon job'i uchun: Mini App yaratgan, hali sotuvchiga xabar ketmagan
        pending buyurtmalar id'lari (eskidan yangiga)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM orders WHERE notify_pending=1 AND status='pending' "
            "ORDER BY id ASC LIMIT ?", (limit,))
        return [r[0] for r in cursor.fetchall()]

    def clear_order_notify_pending(self, order_id):
        """Xabar yuborilgach (yoki yuborib bo'lmasa ham, qayta urinmaslik uchun) belgini tozalaydi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET notify_pending=0 WHERE id=?", (order_id,))
        conn.commit()

    def set_orders_group(self, order_ids, group_id):
        """Bir nechta buyurtmani bitta savat guruhiga bog'laydi."""
        if not order_ids:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in order_ids)
        cursor.execute(
            f"UPDATE orders SET order_group_id=? WHERE id IN ({placeholders})",
            [str(group_id)] + list(order_ids)
        )
        conn.commit()

    def get_orders_in_group(self, group_id):
        """Savat guruhidagi barcha buyurtma qatorlari (mahsulot va sotuvchi/xaridor ma'lumotlari bilan).
        Guruhdagi barcha qatorlar bir do'kon va bir xaridorga tegishli."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   p.image_url as product_image,
                   bu.name as buyer_name, bu.phone_number as buyer_phone, bu.telegram_id as buyer_tg,
                   bu.telegram_username as buyer_username,
                   su.name as seller_name, su.shop_name, su.phone_number as seller_phone,
                   su.telegram_id as seller_tg,
                   su.shop_lat, su.shop_lon, su.shop_address, su.shop_landmark,
                   su.telegram_username as seller_username
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            WHERE o.order_group_id=?
            ORDER BY o.id ASC
        """, (str(group_id),))
        return [dict(r) for r in cursor.fetchall()]

    def get_order_by_id(self, order_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   p.image_url as product_image,
                   bu.name as buyer_name, bu.phone_number as buyer_phone, bu.telegram_id as buyer_tg,
                   su.name as seller_name, su.shop_name, su.phone_number as seller_phone,
                   su.telegram_id as seller_tg,
                   su.shop_lat, su.shop_lon, su.shop_address, su.shop_landmark,
                   su.telegram_username as seller_username,
                   bu.telegram_username as buyer_username
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            WHERE o.id=?
        """, (order_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_pending_orders_for_reschedule(self):
        """Bot restart'idan keyin eslatma/avto-bekor taymerlarini qayta rejalashtirish
        uchun — barcha 'pending' buyurtmalar (yaratilgan vaqti va kerakli maydonlar bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.created_at, o.order_group_id, o.total_price,
                   o.auto_cancel_at, o.notify_chat_id, o.notify_message_id,
                   o.notify_is_caption,
                   p.name as product_name,
                   bu.name as buyer_name, bu.telegram_id as buyer_tg,
                   su.telegram_id as seller_tg
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            WHERE o.status='pending'
            ORDER BY o.created_at ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def set_order_deadline(self, order_id, auto_cancel_at):
        """Yakka buyurtmaning avto-bekor muddatini (UTC) belgilaydi."""
        if hasattr(auto_cancel_at, 'strftime'):
            auto_cancel_at = auto_cancel_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET auto_cancel_at=? WHERE id=?", (auto_cancel_at, order_id))
        conn.commit()

    def set_group_deadline(self, group_id, auto_cancel_at):
        """Guruh (savat) buyurtmasidagi barcha qatorlar uchun avto-bekor muddati (UTC)."""
        if hasattr(auto_cancel_at, 'strftime'):
            auto_cancel_at = auto_cancel_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET auto_cancel_at=? WHERE order_group_id=?",
                       (auto_cancel_at, str(group_id)))
        conn.commit()

    def set_order_notify_ref(self, order_id, chat_id, message_id, is_caption, caption):
        """Yakka buyurtma bildirishnoma xabari ma'lumotlari (jonli sanoq tahrirlashi uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET notify_chat_id=?, notify_message_id=?, notify_is_caption=?, notify_caption=? WHERE id=?",
            (chat_id, message_id, 1 if is_caption else 0, caption, order_id))
        conn.commit()

    def set_group_notify_ref(self, group_id, chat_id, message_id, is_caption, caption):
        """Guruh buyurtmasi bildirishnoma xabari ma'lumotlari (barcha qatorlarga)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET notify_chat_id=?, notify_message_id=?, notify_is_caption=?, notify_caption=? WHERE order_group_id=?",
            (chat_id, message_id, 1 if is_caption else 0, caption, str(group_id)))
        conn.commit()

    # ===== TO'LOV HOLATI / QARZ DAFTARI =====
    def set_order_settlement(self, order_id, settlement_type, amount_paid, amount_due):
        """Yakka buyurtma berilgandagi to'lov holati. amount_due<=0 bo'lsa settled_at o'rnatiladi."""
        from datetime import datetime, timezone
        settled = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if (amount_due or 0) <= 0 else None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET settlement_type=?, amount_paid=?, amount_due=?, settled_at=? WHERE id=?",
            (settlement_type, amount_paid, amount_due, settled, order_id))
        conn.commit()

    def set_group_settlement(self, group_id, settlement_type, amount_paid, amount_due):
        """Guruh (savat) buyurtmasi to'lov holati. settlement_type barcha qatorlarga;
        summa (paid/due) faqat eng kichik id'li (vakil) qatorga yoziladi — shunda qarz
        bo'yicha SUM(amount_due) to'g'ri chiqadi. Qolgan qatorlar amount_due=0."""
        from datetime import datetime, timezone
        settled = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if (amount_due or 0) <= 0 else None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM orders WHERE order_group_id=? ORDER BY id ASC", (str(group_id),))
        ids = [r[0] for r in cursor.fetchall()]
        if not ids:
            return
        rep = ids[0]
        # Barcha qatorlar: type + 0 summa
        cursor.execute(
            "UPDATE orders SET settlement_type=?, amount_paid=0, amount_due=0, settled_at=? WHERE order_group_id=?",
            (settlement_type, settled, str(group_id)))
        # Vakil qator: haqiqiy summalar
        cursor.execute(
            "UPDATE orders SET amount_paid=?, amount_due=?, settled_at=? WHERE id=?",
            (amount_paid, amount_due, settled, rep))
        conn.commit()

    def record_debt_payment(self, order_id, pay_amount):
        """Qarzga qisman/to'liq to'lov qo'shadi. Yangi qolgan qarzni (amount_due) qaytaradi.
        amount_due 0 ga tushsa settled_at o'rnatiladi."""
        from datetime import datetime, timezone
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT amount_paid, amount_due FROM orders WHERE id=?", (order_id,))
        row = cursor.fetchone()
        if not row:
            return None
        paid = (row[0] or 0) + float(pay_amount)
        due = max(0.0, (row[1] or 0) - float(pay_amount))
        settled = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if due <= 0 else None
        cursor.execute(
            "UPDATE orders SET amount_paid=?, amount_due=?, settled_at=? WHERE id=?",
            (paid, due, settled, order_id))
        conn.commit()
        return due

    def get_seller_open_debts(self, seller_id):
        """Sotuvchining ochiq qarzlari — xaridor bo'yicha jamlangan (kim qancha qarzdor)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT bu.id as buyer_id, bu.name as buyer_name, bu.telegram_id as buyer_tg,
                   bu.telegram_username as buyer_username,
                   SUM(o.amount_due) as total_due, COUNT(*) as cnt
            FROM orders o
            JOIN users bu ON o.buyer_id = bu.id
            WHERE o.seller_id=? AND COALESCE(o.amount_due,0) > 0
                  AND o.settlement_type IN ('debt','installment')
            GROUP BY bu.id
            ORDER BY total_due DESC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_debt_orders(self, seller_id, buyer_id):
        """Bir xaridorning ochiq qarzli buyurtmalari (drill-down ro'yxati)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.order_group_id, o.total_price, o.amount_paid, o.amount_due,
                   o.settlement_type, o.created_at, p.name as product_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.seller_id=? AND o.buyer_id=? AND COALESCE(o.amount_due,0) > 0
                  AND o.settlement_type IN ('debt','installment')
            ORDER BY o.created_at ASC
        """, (seller_id, buyer_id))
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_debt_total(self, seller_id):
        """Sotuvchining jami ochiq qarzi (umumiy summa)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(amount_due),0) FROM orders "
            "WHERE seller_id=? AND COALESCE(amount_due,0) > 0 AND settlement_type IN ('debt','installment')",
            (seller_id,))
        return cursor.fetchone()[0] or 0

    def get_buyer_open_debts(self, buyer_id):
        """Xaridorning ochiq qarzlari — sotuvchi bo'yicha jamlangan (kimga qancha qarzdor)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT su.id as seller_id, su.shop_name, su.name as seller_name,
                   SUM(o.amount_due) as total_due, COUNT(*) as cnt
            FROM orders o
            JOIN users su ON o.seller_id = su.id
            WHERE o.buyer_id=? AND COALESCE(o.amount_due,0) > 0
                  AND o.settlement_type IN ('debt','installment')
            GROUP BY su.id
            ORDER BY total_due DESC
        """, (buyer_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_orders_by_buyer(self, buyer_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   u.shop_name, u.phone_number as seller_phone
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.seller_id=u.id
            WHERE o.buyer_id=?
            ORDER BY o.created_at DESC
        """, (buyer_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_orders_by_seller(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   u.name as buyer_name, u.phone_number as buyer_phone
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.buyer_id=u.id
            WHERE o.seller_id=?
            ORDER BY o.created_at DESC
        """, (seller_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_all_orders(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*,
                   b.name as buyer_name, b.phone_number as buyer_phone,
                   s.name as seller_name, s.shop_name,
                   p.name as product_name, p.price as product_price
            FROM orders o
            LEFT JOIN users b ON o.buyer_id=b.id
            LEFT JOIN users s ON o.seller_id=s.id
            LEFT JOIN products p ON o.product_id=p.id
            ORDER BY o.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def update_order_status(self, order_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, order_id)
        )
        conn.commit()

    def set_buyer_received(self, order_id):
        """Xaridor «oldim» bosdi — buyurtma YOPILMAYDI (status 'confirmed' qoladi).
        Sotuvchi to'lov holatini (to'liq/qarz/bo'lib) belgilab, yakunlashi kerak."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET buyer_received=1, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='confirmed'",
            (order_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def set_group_buyer_received(self, group_id):
        """Savat (guruh) buyurtmasi uchun: xaridor «oldim» bosdi. Status 'confirmed' qoladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET buyer_received=1, updated_at=CURRENT_TIMESTAMP "
            "WHERE order_group_id=? AND status='confirmed'",
            (str(group_id),)
        )
        conn.commit()
        return cursor.rowcount > 0

    # ===== SHARTNOMANI BEKOR QILISH (kelishuv + nizo) =====
    # Eslatma: bekor jarayoni davomida orders.status='confirmed' bo'lib turadi
    # (shartnoma hal bo'lguncha kuchda). Jarayon alohida cancel_state ustunida
    # kuzatiladi — shu sababli orders jadvali CHECK'ini buzmaymiz/qayta qurmaymiz.

    def request_order_cancel(self, order_id, by, reason):
        """Bir tomon (buyer/seller) bekor qilishni so'raydi. status o'zgarmaydi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE orders
               SET cancel_state='requested', cancel_by=?, cancel_reason=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='confirmed' AND COALESCE(cancel_state,'')=''""",
            (by, reason, order_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def agree_order_cancel(self, order_id):
        """Ikkinchi tomon roziligini beradi -> buyurtma bekor qilinadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE orders
               SET status='cancelled', cancel_state=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND cancel_state='requested'""",
            (order_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def dispute_order_cancel(self, order_id):
        """Ikkinchi tomon rozi emas -> admin hakamligiga o'tadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE orders
               SET cancel_state='disputed', updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND cancel_state='requested'""",
            (order_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def resolve_order_dispute(self, order_id, do_cancel):
        """Admin qarori: do_cancel=True -> bekor; False -> kuchda qoldiriladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if do_cancel:
            cursor.execute(
                """UPDATE orders
                   SET status='cancelled', cancel_state=NULL, updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND cancel_state='disputed'""",
                (order_id,)
            )
        else:
            # Shartnoma kuchda qoladi — bekor belgilari tozalanadi (status='confirmed' qoladi)
            cursor.execute(
                """UPDATE orders
                   SET cancel_state=NULL, cancel_reason=NULL, cancel_by=NULL,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND cancel_state='disputed'""",
                (order_id,)
            )
        conn.commit()
        return cursor.rowcount > 0

    def get_disputed_orders(self):
        """Admin paneli uchun — nizodagi (disputed) buyurtmalar ro'yxati."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name,
                   bu.name as buyer_name, bu.telegram_id as buyer_tg,
                   su.name as seller_name, su.shop_name, su.telegram_id as seller_tg
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            WHERE o.cancel_state='disputed'
            ORDER BY o.updated_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

    # ===== MAHSULOT ATRIBUTLARI =====

    def get_category_templates(self, category_id):
        """Kategoriya uchun atribut shablonlari."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT attr_key, attr_label, attr_type, is_required, hint
            FROM category_attribute_templates
            WHERE category_id=?
            ORDER BY is_required DESC, id ASC
        """, (category_id,))
        return [dict(r) for r in cursor.fetchall()]

    def save_product_attributes(self, product_id, attributes: dict, labels: dict = None):
        """Mahsulot atributlarini saqlaydi. attributes = {'size': 'XL', 'color': 'Qora'}.
        labels — ixtiyoriy {key: 'Ko'rsatiladigan yorliq'}. AI savollar uchun shablon
        bo'lmagani sababli yorliqni shu yerda saqlaymiz (aks holda raw key ko'rinadi)."""
        if not attributes:
            return
        labels = labels or {}
        conn = self.get_connection()
        cursor = conn.cursor()
        for key, value in attributes.items():
            if value is not None and str(value).strip():
                lbl = labels.get(key)
                lbl = str(lbl).strip() if lbl else None
                cursor.execute("""
                    INSERT INTO product_attributes (product_id, attr_key, attr_value, attr_label)
                    VALUES (?,?,?,?)
                    ON CONFLICT(product_id, attr_key) DO UPDATE SET
                        attr_value=excluded.attr_value,
                        attr_label=COALESCE(excluded.attr_label, product_attributes.attr_label)
                """, (product_id, key, str(value).strip(), lbl))
        conn.commit()

    def get_product_attributes(self, product_id):
        """Mahsulotning barcha atributlari. Yorliq: avval saqlangan attr_label (AI),
        bo'lmasa kategoriya shablonidan (klassik), u ham bo'lmasa — xom kalit."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.attr_key, a.attr_value,
                   COALESCE(a.attr_label, t.attr_label) AS attr_label
            FROM product_attributes a
            LEFT JOIN category_attribute_templates t
                ON t.attr_key=a.attr_key
                AND t.category_id=(SELECT category_id FROM products WHERE id=a.product_id)
            WHERE a.product_id=?
        """, (product_id,))
        return [dict(r) for r in cursor.fetchall()]

    def search_products_by_attribute(self, attr_key, attr_value, category_id=None):
        """Atribut bo'yicha mahsulot qidirish (masalan: size=XL)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT p.* FROM products p
            JOIN product_attributes a ON a.product_id=p.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE a.attr_key=? AND a.attr_value LIKE ? AND p.in_stock=1
            AND COALESCE(u.is_blocked,0)=0
        """
        params = [attr_key, f"%{attr_value}%"]
        if category_id:
            sql += " AND p.category_id=?"
            params.append(category_id)
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    # ===== MESSAGES =====
    def create_message(self, order_id, sender_id, receiver_id, message):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (order_id, sender_id, receiver_id, message) VALUES (?,?,?,?)",
            (order_id, sender_id, receiver_id, message)
        )
        mid = cursor.lastrowid
        conn.commit()
        return mid

    def get_messages_by_order(self, order_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.*, u.name as sender_name
            FROM messages m JOIN users u ON m.sender_id=u.id
            WHERE m.order_id=? ORDER BY m.created_at ASC
        """, (order_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ===== NIZO YOZISHMALARI (admin ↔ tomon, audit) =====
    def add_dispute_message(self, order_id, party, sender_role, sender_id, sender_name, message):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO dispute_messages
               (order_id, party, sender_role, sender_id, sender_name, message)
               VALUES (?,?,?,?,?,?)""",
            (order_id, party, sender_role, sender_id, sender_name, message)
        )
        conn.commit()
        return cursor.lastrowid

    def get_dispute_messages(self, order_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM dispute_messages WHERE order_id=? ORDER BY created_at ASC",
            (order_id,)
        )
        return [dict(r) for r in cursor.fetchall()]

    def count_dispute_messages(self, order_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dispute_messages WHERE order_id=?", (order_id,))
        return cursor.fetchone()[0]

    # ===== REVIEWS =====
    def create_review(self, order_id, seller_id, buyer_id, rating, comment=None,
                      product_id=None, product_rating=None):
        """Baho saqlaydi.
        rating         = sotuvchi (do'kon) uchun 1-5
        product_rating = mahsulot uchun 1-5
        comment        = mahsulot haqida izoh (ixtiyoriy)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (order_id, seller_id, buyer_id, rating, comment, product_id, product_rating) "
            "VALUES (?,?,?,?,?,?,?)",
            (order_id, seller_id, buyer_id, rating, comment, product_id, product_rating)
        )
        rid = cursor.lastrowid
        conn.commit()
        return rid

    def order_review_exists(self, order_id, buyer_id):
        """Shu buyurtmaga shu xaridor allaqachon baho qoldirganmi (dublikat oldini olish)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM reviews WHERE order_id=? AND buyer_id=? LIMIT 1",
                       (order_id, buyer_id))
        return cursor.fetchone() is not None

    def get_seller_reviews(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.name as buyer_name,
                   COALESCE(po.name, pr.name) as product_name
            FROM reviews r
            JOIN users u ON r.buyer_id=u.id
            LEFT JOIN orders o ON r.order_id=o.id
            LEFT JOIN products po ON o.product_id=po.id
            LEFT JOIN products pr ON r.product_id=pr.id
            WHERE r.seller_id=? ORDER BY r.created_at DESC
        """, (seller_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_seller_avg_rating(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(rating) FROM reviews WHERE seller_id=?", (seller_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else 0.0

    def get_review_by_id(self, review_id):
        """Bitta sharhni egasi (seller) tekshiruvi uchun qaytaradi (mahsulot/xaridor nomi bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, bu.name as buyer_name,
                   COALESCE(po.name, pr.name) as product_name
            FROM reviews r
            LEFT JOIN users bu ON r.buyer_id=bu.id
            LEFT JOIN orders o ON r.order_id=o.id
            LEFT JOIN products po ON o.product_id=po.id
            LEFT JOIN products pr ON r.product_id=pr.id
            WHERE r.id=?
        """, (review_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_review_reply(self, review_id, seller_id, reply):
        """Sotuvchining sharhga ochiq javobini saqlaydi. Egalik SQL'da tekshiriladi —
        boshqa sotuvchi begona sharhga javob yoza olmaydi. True = saqlandi."""
        reply = (reply or '').strip()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE reviews SET seller_reply=?, replied_at=CURRENT_TIMESTAMP
               WHERE id=? AND seller_id=?""",
            (reply or None, review_id, seller_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_product_avg_rating(self, product_id):
        """Mahsulot uchun (o'rtacha_reyting, baholar_soni) qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT AVG(product_rating), COUNT(product_rating) FROM reviews "
            "WHERE product_id=? AND product_rating IS NOT NULL",
            (product_id,)
        )
        row = cursor.fetchone()
        avg = row[0] if row and row[0] else 0.0
        count = row[1] if row and row[1] else 0
        return avg, count

    def get_product_reviews(self, product_id, limit=None):
        """Mahsulotga yozilgan izohlar (yangi -> eski). Faqat izohi borlari."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT r.product_rating, r.comment, r.created_at,
                   r.seller_reply, r.replied_at,
                   u.name as buyer_name
            FROM reviews r
            LEFT JOIN users u ON r.buyer_id=u.id
            WHERE r.product_id=? AND r.comment IS NOT NULL AND TRIM(r.comment) <> ''
            ORDER BY r.created_at DESC
        """
        params = [product_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_stats(self, seller_id):
        """Sotuvchi statistikasi: buyurtmalar, daromad, mahsulotlar soni
        (hafta / oy / jami kesimida)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Jami statistika
        cursor.execute("""
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status='pending' THEN 1 END) as pending_count,
                COUNT(CASE WHEN status='confirmed' THEN 1 END) as confirmed_count,
                COUNT(CASE WHEN status='delivered' THEN 1 END) as delivered_count,
                COUNT(CASE WHEN status='cancelled' THEN 1 END) as cancelled_count,
                COALESCE(SUM(CASE WHEN status='delivered' THEN total_price ELSE 0 END), 0) as total_revenue
            FROM orders WHERE seller_id=?
        """, (seller_id,))
        row = cursor.fetchone()
        total = dict(row) if row else {}

        # So'nggi 7 kun
        cursor.execute("""
            SELECT
                COUNT(*) as week_orders,
                COALESCE(SUM(CASE WHEN status='delivered' THEN total_price ELSE 0 END), 0) as week_revenue
            FROM orders
            WHERE seller_id=? AND created_at >= datetime('now', '-7 days')
        """, (seller_id,))
        row = cursor.fetchone()
        week = dict(row) if row else {}

        # So'nggi 30 kun
        cursor.execute("""
            SELECT
                COUNT(*) as month_orders,
                COALESCE(SUM(CASE WHEN status='delivered' THEN total_price ELSE 0 END), 0) as month_revenue
            FROM orders
            WHERE seller_id=? AND created_at >= datetime('now', '-30 days')
        """, (seller_id,))
        row = cursor.fetchone()
        month = dict(row) if row else {}

        # Mahsulotlar soni
        cursor.execute("SELECT COUNT(*) FROM products WHERE seller_id=?", (seller_id,))
        products_count = cursor.fetchone()[0]

        return {
            'total_orders': total.get('total_orders', 0),
            'pending': total.get('pending_count', 0),
            'confirmed': total.get('confirmed_count', 0),
            'delivered': total.get('delivered_count', 0),
            'cancelled': total.get('cancelled_count', 0),
            'total_revenue': total.get('total_revenue', 0),
            'week_orders': week.get('week_orders', 0),
            'week_revenue': week.get('week_revenue', 0),
            'month_orders': month.get('month_orders', 0),
            'month_revenue': month.get('month_revenue', 0),
            'products_count': products_count,
        }

    def get_seller_product_performance(self, seller_id):
        """Sotuvchining har bir mahsuloti bo'yicha sotuv ko'rsatkichi.
        Qaytaradi: [{'id', 'name', 'price', 'sold', 'revenue'}, ...]
        'sold' — yetkazilgan (delivered) buyurtmalardagi jami dona soni."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.name, p.price,
                   COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.quantity ELSE 0 END), 0) as sold,
                   COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.total_price ELSE 0 END), 0) as revenue
            FROM products p
            LEFT JOIN orders o ON o.product_id=p.id
            WHERE p.seller_id=?
            GROUP BY p.id
            ORDER BY sold DESC, p.created_at DESC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def auto_cancel_stale_orders(self, days=3):
        """3 kun ichida tasdiqlanmagan buyurtmalarni avtomatik bekor qiladi.
        Bekor qilingan buyurtmalar ro'yxatini qaytaradi (bildirishnoma uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, buyer_id, seller_id, product_id FROM orders
            WHERE status='pending' AND created_at < datetime('now', '-{int(days)} days')
        """)
        stale = [dict(r) for r in cursor.fetchall()]
        if stale:
            ids = [str(s['id']) for s in stale]
            cursor.execute(
                f"UPDATE orders SET status='cancelled' WHERE id IN ({','.join('?' for _ in ids)})",
                ids
            )
            conn.commit()
        return stale
    # ===== QO'SHIMCHA METODLAR (main.py dagi xom SQL uchun) =====

    def get_all_categories(self):
        """Barcha kategoriyalarni qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories ORDER BY id")
        return cursor.fetchall()

    def get_product_by_id(self, product_id):
        """Mahsulotni barcha ma'lumotlari bilan qaytaradi (sotuvchi ma'lumotlari bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name, c.emoji as category_emoji,
                   u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number, u.telegram_id as seller_tg,
                   u.is_blocked as seller_blocked, u.region_id as seller_region_id,
                   (SELECT AVG(rating) FROM reviews WHERE seller_id=p.seller_id) as avg_rating,
                   (SELECT AVG(product_rating) FROM reviews WHERE product_id=p.id AND product_rating IS NOT NULL) as prod_avg_rating,
                   (SELECT COUNT(*) FROM reviews WHERE product_id=p.id AND product_rating IS NOT NULL) as prod_review_count
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE p.id=?
        """, (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_product_basic(self, product_id):
        """Mahsulot asosiy ma'lumotlari (seller_product_menu uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_seller_products_by_status(self, seller_id, status='active', search=None):
        """Sotuvchi mahsulotlarini status bo'yicha qaytaradi.
        status: 'active' | 'reserve' | 'deleted'
        search: nom bo'yicha qidiruv (ixtiyoriy)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = "SELECT * FROM products WHERE seller_id=? AND COALESCE(status,'active')=?"
        params = [seller_id, status]
        if search:
            sql += " AND name LIKE ?"
            params.append(f"%{search}%")
        sql += " ORDER BY name ASC"
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def count_seller_products_by_status(self, seller_id):
        """Har bir status uchun mahsulotlar sonini qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(status,'active') as st, COUNT(*) as cnt
            FROM products WHERE seller_id=?
            GROUP BY COALESCE(status,'active')
        """, (seller_id,))
        result = {'active': 0, 'reserve': 0, 'deleted': 0}
        for row in cursor.fetchall():
            result[row[0]] = row[1]
        return result

    def set_product_status(self, product_id, status):
        """Mahsulot statusini o'zgartiradi: 'active' | 'reserve' | 'deleted'.
        active bo'lsa in_stock=1, aks holda 0."""
        conn = self.get_connection()
        cursor = conn.cursor()
        in_stock = 1 if status == 'active' else 0
        cursor.execute(
            "UPDATE products SET status=?, in_stock=? WHERE id=?",
            (status, in_stock, product_id)
        )
        conn.commit()

    # ===== REJALASHTIRILGAN POSTLAR (avtomatik sotuvga qo'yish) =====
    def create_scheduled_post(self, product_id, seller_id, scheduled_at, created_by=None,
                              caption=None, parse_mode=None, image_id=None):
        """Yangi rejalashtirilgan post yaratadi. scheduled_at — UTC ('YYYY-MM-DD HH:MM:SS'
        satr yoki datetime). Yaratilgan yozuv id sini qaytaradi."""
        if hasattr(scheduled_at, 'strftime'):
            scheduled_at = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO scheduled_posts "
            "(product_id, seller_id, created_by, scheduled_at, status, caption, parse_mode, image_id) "
            "VALUES (?,?,?,?,'pending',?,?,?)",
            (product_id, seller_id, created_by, scheduled_at, caption, parse_mode, image_id)
        )
        sid = cursor.lastrowid
        conn.commit()
        return sid

    def get_scheduled_post(self, sched_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduled_posts WHERE id=?", (sched_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_pending_scheduled_posts(self):
        """Barcha 'pending' rejalashtirilgan postlar (restartda joblarni tiklash uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at ASC"
        )
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_scheduled_posts(self, seller_id):
        """Sotuvchining (egasining) kutilayotgan rejalari — mahsulot nomi bilan."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sp.*, p.name as product_name
            FROM scheduled_posts sp
            JOIN products p ON sp.product_id = p.id
            WHERE sp.seller_id=? AND sp.status='pending'
            ORDER BY sp.scheduled_at ASC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def mark_scheduled_post(self, sched_id, status, posted_at=None):
        """Reja holatini o'zgartiradi: posted | cancelled | failed."""
        if posted_at is not None and hasattr(posted_at, 'strftime'):
            posted_at = posted_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scheduled_posts SET status=?, posted_at=COALESCE(?, posted_at) WHERE id=?",
            (status, posted_at, sched_id)
        )
        conn.commit()

    def cancel_scheduled_post(self, sched_id, seller_id=None):
        """Rejani bekor qiladi (faqat 'pending' bo'lsa). seller_id berilsa — egalik
        tekshiriladi. Bekor qilingan yozuvni (dict) qaytaradi, aks holda None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if seller_id is not None:
            cursor.execute(
                "SELECT * FROM scheduled_posts WHERE id=? AND seller_id=? AND status='pending'",
                (sched_id, seller_id))
        else:
            cursor.execute(
                "SELECT * FROM scheduled_posts WHERE id=? AND status='pending'", (sched_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("UPDATE scheduled_posts SET status='cancelled' WHERE id=?", (sched_id,))
        conn.commit()
        return dict(row)

    # ===== AVTO QAYTA-REKLAMA (kuniga bir marta avtomatik qayta chiqarish) =====
    def upsert_auto_repost(self, product_id, seller_id, hour, *, created_by=None,
                           caption=None, parse_mode=None, image_id=None, expires_at=None):
        """Mahsulot uchun avto qayta-reklamani yoqadi (yoki mavjudini yangilaydi).
        Bitta mahsulotga bitta yozuv (UNIQUE product_id). Yozuv id sini qaytaradi."""
        if expires_at is not None and hasattr(expires_at, 'strftime'):
            expires_at = expires_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO auto_reposts
                (product_id, seller_id, created_by, hour, caption, parse_mode, image_id,
                 last_message_ids, is_active, expires_at, last_run_at)
            VALUES (?,?,?,?,?,?,?, NULL, 1, ?, NULL)
            ON CONFLICT(product_id) DO UPDATE SET
                seller_id=excluded.seller_id, created_by=excluded.created_by,
                hour=excluded.hour, caption=excluded.caption,
                parse_mode=excluded.parse_mode, image_id=excluded.image_id,
                is_active=1, expires_at=excluded.expires_at
        """, (product_id, seller_id, created_by, hour, caption, parse_mode, image_id, expires_at))
        conn.commit()
        cursor.execute("SELECT id FROM auto_reposts WHERE product_id=?", (product_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_auto_repost(self, repost_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auto_reposts WHERE id=?", (repost_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_active_auto_reposts(self):
        """Barcha faol avto qayta-reklamalar (restartda joblarni tiklash uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auto_reposts WHERE is_active=1")
        return [dict(r) for r in cursor.fetchall()]

    # ===== META / ATOMIK KUNLIK QULF =====
    def claim_daily_once(self, key, today):
        """Berilgan kalit uchun 'bugun' ATOMIK tarzda bir marta band qiladi.
        True qaytarsa — SHU chaqiruv birinchi bo'lib band qildi (ish bajarilsin).
        False — bugun allaqachon band qilingan (ikkinchi/takror chaqiruv, o'tkazib yubor).
        Ikki instans bir DB ishlatsa ham SQLite yozuvni serializatsiya qiladi —
        shu sababli backup/xabar faqat bir marta ketadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value "
            "WHERE app_meta.value <> excluded.value",
            (key, today))
        conn.commit()
        return cursor.rowcount > 0

    def get_auto_repost_by_product(self, product_id):
        """Mahsulotning FAOL avto qayta-reklamasi (bor bo'lsa) — menyuda holatni
        ko'rsatish uchun. Yo'q bo'lsa None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auto_reposts WHERE product_id=? AND is_active=1", (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_seller_auto_reposts(self, seller_id):
        """Sotuvchining (egasining) faol avto qayta-reklamalari — mahsulot nomi bilan."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ar.*, p.name as product_name
            FROM auto_reposts ar
            JOIN products p ON ar.product_id = p.id
            WHERE ar.seller_id=? AND ar.is_active=1
            ORDER BY ar.hour ASC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def update_auto_repost_run(self, repost_id, last_message_ids, last_run_at=None):
        """Bajarilgandan keyin: oxirgi yuborilgan xabar id lari va vaqtni saqlaydi."""
        if last_run_at is not None and hasattr(last_run_at, 'strftime'):
            last_run_at = last_run_at.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE auto_reposts SET last_message_ids=?, last_run_at=COALESCE(?, last_run_at) WHERE id=?",
            (last_message_ids, last_run_at, repost_id))
        conn.commit()

    def deactivate_auto_repost(self, repost_id):
        """Avto qayta-reklamani o'chiradi (avto-to'xtash: sotilgan/o'chirilgan/muddati tugagan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE auto_reposts SET is_active=0 WHERE id=?", (repost_id,))
        conn.commit()

    def cancel_auto_repost(self, repost_id, seller_id=None):
        """Sotuvchi o'chirsa: egalik tekshirib, faol yozuvni o'chiradi va (dict) qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if seller_id is not None:
            cursor.execute(
                "SELECT * FROM auto_reposts WHERE id=? AND seller_id=? AND is_active=1",
                (repost_id, seller_id))
        else:
            cursor.execute("SELECT * FROM auto_reposts WHERE id=? AND is_active=1", (repost_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("UPDATE auto_reposts SET is_active=0 WHERE id=?", (repost_id,))
        conn.commit()
        return dict(row)

    def search_seller_products(self, seller_id, search_text):
        """Sotuvchining barcha mahsulotlari ichidan qidiradi (o'chirilganlardan tashqari)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM products
            WHERE seller_id=? AND COALESCE(status,'active') NOT IN ('deleted','purged')
            AND name LIKE ?
            ORDER BY name ASC
        """, (seller_id, f"%{search_text}%"))
        return [dict(r) for r in cursor.fetchall()]

    def toggle_product_stock(self, product_id):
        """in_stock ni 0→1 yoki 1→0 ga o'zgartiradi. Yangi qiymatni qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT in_stock FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if not row:
            return None
        new_val = 0 if row[0] else 1
        cursor.execute("UPDATE products SET in_stock=? WHERE id=?", (new_val, product_id))
        conn.commit()
        return new_val

    def set_product_stock_count(self, product_id, stock_count):
        """stock_count ni belgilaydi. None bo'lsa cheksiz.
        Zahira > 0 bo'lsa va mahsulot zahirada bo'lsa — avtomatik sotuvga qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if stock_count is None:
            cursor.execute(
                "UPDATE products SET stock_count=NULL, in_stock=1, status='active' WHERE id=?",
                (product_id,)
            )
        elif stock_count > 0:
            # Zahira to'ldirildi — sotuvga qaytaramiz (agar o'chirilmagan bo'lsa)
            cursor.execute("SELECT status FROM products WHERE id=?", (product_id,))
            row = cursor.fetchone()
            current_status = (row[0] if row else 'active') or 'active'
            new_status = 'active' if current_status != 'deleted' else 'deleted'
            in_stock = 1 if new_status == 'active' else 0
            cursor.execute(
                "UPDATE products SET stock_count=?, in_stock=?, status=? WHERE id=?",
                (stock_count, in_stock, new_status, product_id)
            )
        else:
            # 0 — zahiraga o'tkazamiz
            cursor.execute(
                "UPDATE products SET stock_count=0, in_stock=0, status='reserve' WHERE id=?",
                (product_id,)
            )
        conn.commit()

    def decrement_stock_on_confirm(self, product_id, quantity):
        """Buyurtma tasdiqlanganda stock_count'ni kamaytiradi.
        Zahira 0 ga tushsa — mahsulot avtomatik 'reserve' (zahira) statusiga o'tadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Atomar kamaytirish: bir vaqtda ikki buyurtma kelsa ham oversell bo'lmaydi.
        # Faqat cheklangan zahirali (stock_count NULL emas) mahsulotni kamaytiramiz.
        cursor.execute(
            "UPDATE products SET stock_count = MAX(0, stock_count - ?) "
            "WHERE id=? AND stock_count IS NOT NULL",
            (quantity, product_id)
        )
        if cursor.rowcount == 0:
            conn.commit()
            return None  # cheksiz zahira yoki mahsulot topilmadi
        cursor.execute("SELECT stock_count FROM products WHERE id=?", (product_id,))
        new_stock = cursor.fetchone()[0]
        if new_stock > 0:
            # Hali bor — sotuvda qoladi
            cursor.execute(
                "UPDATE products SET in_stock=1, status='active' WHERE id=?",
                (product_id,)
            )
        else:
            # Tugadi — avtomatik zahiraga o'tadi (sotuvchi keyin to'ldiradi)
            cursor.execute(
                "UPDATE products SET in_stock=0, status='reserve' WHERE id=?",
                (product_id,)
            )
        conn.commit()
        return new_stock

    def restock_on_cancel(self, product_id, quantity):
        """Tasdiqlangan buyurtma bekor qilinganda zaxirani qaytaradi.
        Faqat cheklangan zahirali (stock_count NULL emas) mahsulotga ta'sir qiladi.
        Zaxira qayta musbat bo'lsa — mahsulot avtomatik 'active' holatga qaytadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE products SET stock_count = stock_count + ? "
            "WHERE id=? AND stock_count IS NOT NULL",
            (quantity, product_id)
        )
        if cursor.rowcount == 0:
            conn.commit()
            return None  # cheksiz zahira yoki mahsulot topilmadi
        # Zaxira qaytgach — agar 'reserve' (zahira) holatda turgan bo'lsa, sotuvga qaytaramiz.
        # 'deleted'/'purged' mahsulotlarni tiriltirmaymiz.
        cursor.execute(
            "UPDATE products SET in_stock=1, status='active' "
            "WHERE id=? AND stock_count > 0 AND COALESCE(status,'active')='reserve'",
            (product_id,)
        )
        cursor.execute("SELECT stock_count FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else None

    def delete_product(self, product_id, deleted_by=None, deleted_by_role=None):
        """Mahsulotni butunlay o'chiradi va audit jurnaliga yozadi.

        Buyurtma tarixi (orders) bo'lsa, products(id) ga FOREIGN KEY mavjudligi
        sababli jismonan DELETE qilib bo'lmaydi (buyurtma yozuvi yo'qoladi). Bu
        holatda mahsulot 'purged' deb belgilanadi — u na sotuvchiga, na xaridorga,
        na hech qaysi ro'yxatga ko'rinmaydi, lekin buyurtma tarixi saqlanadi.
        Buyurtmasi bo'lmasa — to'liq jismonan o'chiriladi.

        deleted_by / deleted_by_role — o'chirayotgan foydalanuvchi (audit uchun).
        True qaytaradi — jismonan o'chirildi; False — 'purged' yoki topilmadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # O'chirishdan OLDIN to'liq nusxa olamiz
        cursor.execute("""
            SELECT p.*, u.name as seller_name, u.shop_name, c.name as category_name
            FROM products p
            LEFT JOIN users u ON p.seller_id=u.id
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.id=?
        """, (product_id,))
        prow = cursor.fetchone()
        if not prow:
            return False  # allaqachon yo'q (mas. ikki marta bosildi)
        p = dict(prow)
        cursor.execute("SELECT COUNT(*) FROM orders WHERE product_id=?", (product_id,))
        order_count = cursor.fetchone()[0]
        has_orders = order_count > 0
        action = 'purged' if has_orders else 'deleted'

        # Audit jurnaliga yozamiz
        cursor.execute("""
            INSERT INTO product_audit
                (product_id, seller_id, seller_name, shop_name, name, price,
                 category_name, description, stock_count, status_before, order_count,
                 action, deleted_by, deleted_by_role, product_created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (product_id, p.get('seller_id'), p.get('seller_name'), p.get('shop_name'),
              p.get('name'), p.get('price'), p.get('category_name'), p.get('description'),
              p.get('stock_count'), p.get('status'), order_count, action,
              deleted_by, deleted_by_role, p.get('created_at')))

        if has_orders:
            cursor.execute(
                "UPDATE products SET status='purged', in_stock=0 WHERE id=?",
                (product_id,)
            )
        else:
            # product_images / product_attributes ON DELETE CASCADE bilan o'chadi
            cursor.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
        return not has_orders

    def get_product_audit(self, limit=100):
        """O'chirilgan mahsulotlar jurnali (eng yangilari birinchi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, u.name as deleted_by_name
            FROM product_audit a
            LEFT JOIN users u ON a.deleted_by=u.id
            ORDER BY a.deleted_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]

    def get_product_audit_entry(self, audit_id):
        """Bitta audit yozuvining to'liq ma'lumoti."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, u.name as deleted_by_name
            FROM product_audit a
            LEFT JOIN users u ON a.deleted_by=u.id
            WHERE a.id=?
        """, (audit_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_product_fields(self, product_id, **fields):
        """Mahsulot maydonlarini yangilaydi. fields — dict ko'rinishida."""
        if not fields:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k}=?" for k in fields.keys()])
        values = list(fields.values()) + [product_id]
        cursor.execute(f"UPDATE products SET {set_clause} WHERE id=?", values)
        conn.commit()

    # ===== MAHSULOT RASMLARI (bir mahsulotga 4 tagacha) =====
    MAX_PRODUCT_IMAGES = 4

    def get_product_images(self, product_id):
        """Mahsulot rasmlari (file_id) ro'yxati, tartib bo'yicha.
        Agar product_images jadvalida yozuv bo'lmasa — eski products.image_url
        qiymatiga qaytadi (eski mahsulotlar uchun moslik)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_id FROM product_images WHERE product_id=? ORDER BY position ASC, id ASC",
            (product_id,)
        )
        rows = [r[0] for r in cursor.fetchall() if r[0]]
        if rows:
            return rows
        # Fallback: eski yagona rasm
        cursor.execute("SELECT image_url FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return [row[0]]
        return []

    def count_product_images(self, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM product_images WHERE product_id=?", (product_id,))
        n = cursor.fetchone()[0]
        if n:
            return n
        cursor.execute("SELECT image_url FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        return 1 if (row and row[0]) else 0

    def set_product_images(self, product_id, file_ids):
        """Mahsulotning barcha rasmlarini almashtiradi (eng ko'pi 4 ta).
        Birinchi rasm products.image_url ga ham yoziladi (NULL bo'lishi mumkin)."""
        file_ids = [f for f in (file_ids or []) if f][: self.MAX_PRODUCT_IMAGES]
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_images WHERE product_id=?", (product_id,))
        for pos, fid in enumerate(file_ids):
            cursor.execute(
                "INSERT INTO product_images (product_id, file_id, position) VALUES (?,?,?)",
                (product_id, fid, pos)
            )
        # Birinchi rasmni eski image_url ustuniga ham sinxronlaymiz
        primary = file_ids[0] if file_ids else None
        cursor.execute("UPDATE products SET image_url=? WHERE id=?", (primary, product_id))
        conn.commit()

    def add_product_image(self, product_id, file_id):
        """Mahsulotga bitta rasm qo'shadi (limitni hisobga oladi). True — qo'shildi."""
        if not file_id:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(position), -1) FROM product_images WHERE product_id=?", (product_id,))
        max_pos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM product_images WHERE product_id=?", (product_id,))
        if cursor.fetchone()[0] >= self.MAX_PRODUCT_IMAGES:
            return False
        new_pos = max_pos + 1
        cursor.execute(
            "INSERT INTO product_images (product_id, file_id, position) VALUES (?,?,?)",
            (product_id, file_id, new_pos)
        )
        if new_pos == 0:
            cursor.execute("UPDATE products SET image_url=? WHERE id=?", (file_id, product_id))
        conn.commit()
        return True

    def delete_product_attribute(self, product_id, attr_key):
        """Mahsulotning bitta atributini o'chiradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM product_attributes WHERE product_id=? AND attr_key=?",
            (product_id, attr_key)
        )
        conn.commit()

    def get_buyer_orders_list(self, buyer_id):
        """Xaridor buyurtmalari ro'yxati (qisqa ma'lumot bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   u.shop_name, u.phone_number as seller_phone, u.telegram_id as seller_tg
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.seller_id=u.id
            WHERE o.buyer_id=?
            ORDER BY o.created_at DESC
        """, (buyer_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_orders_list(self, seller_id):
        """Sotuvchi buyurtmalari ro'yxati."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   u.name as buyer_name, u.phone_number as buyer_phone, u.telegram_id as buyer_tg
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.buyer_id=u.id
            WHERE o.seller_id=?
            ORDER BY o.created_at DESC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_users_paginated(self, limit=15, offset=0):
        """Sahifalangan foydalanuvchilar ro'yxati."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(r) for r in cursor.fetchall()]
        return total, rows

    def get_user_is_blocked(self, user_id):
        """Foydalanuvchi bloklangan yoki yo'qligini qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_blocked FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return bool(row[0]) if row else None

    def get_user_is_verified(self, user_id):
        """Foydalanuvchi tasdiqlangan yoki yo'qligini qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_verified FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return bool(row[0]) if row else None

    def search_users(self, query, limit=20):
        """Foydalanuvchilarni ism, telefon yoki do'kon nomi bo'yicha qidirish."""
        conn = self.get_connection()
        cursor = conn.cursor()
        q = f"%{query}%"
        cursor.execute("""
            SELECT * FROM users
            WHERE name LIKE ? OR phone_number LIKE ? OR shop_name LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (q, q, q, limit))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_seller_messages_summary(self, seller_id, limit=20):
        """Sotuvchi uchun xabarli buyurtmalar (oxirgi xabar vaqti bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT o.id, p.name as product_name, bu.name as buyer_name,
                   MAX(m.created_at) as last_msg
            FROM messages m
            JOIN orders o ON m.order_id=o.id
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            WHERE o.seller_id=?
            GROUP BY o.id
            ORDER BY last_msg DESC
            LIMIT ?
        """, (seller_id, limit))
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def get_order_by_id_for_rating(self, order_id):
        """Reyting uchun buyurtma (seller_id, buyer_id, product_id)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT seller_id, buyer_id, product_id FROM orders WHERE id=?", (order_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_admin_products_summary(self, limit=10):
        """Admin uchun mahsulotlar statistikasi (sotilgan soni bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.name, p.price, COUNT(o.id) as order_count
            FROM products p
            LEFT JOIN orders o ON o.product_id=p.id AND o.status='delivered'
            GROUP BY p.id
            ORDER BY order_count DESC
            LIMIT ?
        """, (limit,))
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    # ===== QO'SHIMCHA METODLAR (main.py dagi xom SQL uchun) =====

    def toggle_product_in_stock(self, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT in_stock FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if not row:
            return None
        new_val = 0 if row[0] else 1
        cursor.execute("UPDATE products SET in_stock=? WHERE id=?", (new_val, product_id))
        conn.commit()
        return new_val

    def init_regions(self):
        """O'zbekiston barcha viloyat va tumanlarini bazaga kiritadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER,
                type TEXT DEFAULT 'district'
            )
        """)

        # Barcha tumanlar ma'lumotlari
        ALL_REGIONS = {
            ("Toshkent shahri", "city"): [
                "Bektemir", "Chilonzor", "Hamza", "Mirobod",
                "Mirzo Ulug'bek", "Olmazor", "Sergeli", "Shayxontohur",
                "Uchtepa", "Yakkasaroy", "Yunusobod"
            ],
            ("Toshkent viloyati", "region"): [
                "Angren", "Bekobod", "Bo'stonliq", "Bo'ka", "Chirchiq",
                "Ohangaron", "Oqqo'rg'on", "Parkent", "Piskent", "Qibray",
                "Toshloq", "Urtachi", "Yangiyo'l", "Yuqorichirchiq", "Zangiota"
            ],
            ("Samarqand viloyati", "region"): [
                "Samarqand shahri", "Bulung'ur", "Ishtixon", "Jomboy",
                "Kattaqo'rg'on", "Narpay", "Nurobod", "Oqdaryo",
                "Pastdarg'om", "Paxtachi", "Payariq", "Qo'shrabot", "Tayloq", "Urgut"
            ],
            ("Farg'ona viloyati", "region"): [
                "Farg'ona shahri", "Beshariq", "Bog'dod", "Buvayda",
                "Dang'ara", "Furqat", "Hamza", "Marg'ilon", "Oltiariq",
                "Quva", "Qo'qon", "Rishton", "So'x", "Toshloq", "Uchko'prik",
                "Uzbekiston", "Yozyovon"
            ],
            ("Andijon viloyati", "region"): [
                "Andijon shahri", "Asaka", "Baliqchi", "Bo'z", "Buloqboshi",
                "Jalaquduq", "Izboskan", "Xo'jaobod", "Marhamat",
                "Oltinko'l", "Paxtaobod", "Qo'rg'ontepa", "Shahrixon",
                "Ulug'nor"
            ],
            ("Namangan viloyati", "region"): [
                "Namangan shahri", "Chortoq", "Chust", "Kosonsoy",
                "Mingbuloq", "Norin", "Pop", "To'raqo'rg'on",
                "Tuproqqo'rg'on", "Uychi", "Yangiqo'rg'on"
            ],
            ("Buxoro viloyati", "region"): [
                "Buxoro shahri", "Alat", "Buxoro tumani", "G'ijduvon",
                "Jondor", "Kogon", "Qorovulbozor", "Romitan",
                "Shofirkon", "Vobkent"
            ],
            ("Qashqadaryo viloyati", "region"): [
                "Qarshi shahri", "Chiroqchi", "Dehqonobod", "G'uzor",
                "Kamashi", "Kasbi", "Kitob", "Koson", "Mirishkor",
                "Muborak", "Nishon", "Shahrisabz", "Yakkabog'"
            ],
            ("Surxondaryo viloyati", "region"): [
                "Termiz shahri", "Angor", "Bandixon", "Boysun",
                "Denov", "Jarqo'rg'on", "Muzrabot", "Oltinsoy",
                "Qiziriq", "Qumqo'rg'on", "Sariosiyo", "Sherobod",
                "Sho'rchi", "Uzun"
            ],
            ("Sirdaryo viloyati", "region"): [
                "Guliston shahri", "Boyovut", "Guliston tumani",
                "Mirzaobod", "Oqoltin", "Sardoba", "Sayxunobod",
                "Shirin", "Xovos"
            ],
            ("Jizzax viloyati", "region"): [
                "Jizzax shahri", "Arnasoy", "Baxmal", "Do'stlik",
                "Forish", "G'allaorol", "Mirzacho'l", "Paxtakor",
                "Yangiobod", "Zarbdor", "Zafarobod", "Zomin"
            ],
            ("Navoiy viloyati", "region"): [
                "Navoiy shahri", "Karmana", "Konimex", "Navbahor",
                "Nurota", "Qiziltepa", "Tomdi", "Uchquduq",
                "Xatirchi", "Zarafshon"
            ],
            ("Xorazm viloyati", "region"): [
                "Urganch shahri", "Bog'ot", "Gurlan", "Xazorasp",
                "Xiva", "Xo'jayli", "Qo'shko'pir", "Shovot",
                "Tuproqqal'a", "Yangiariq", "Yangibozor"
            ],
            ("Qoraqalpog'iston", "region"): [
                "Nukus shahri", "Amudaryo", "Beruniy", "Chimboy",
                "Ellikkala", "Kegeyli", "Mo'ynoq", "Nukus tumani",
                "Qanliko'l", "Qo'ng'irot", "Shumanay", "Taxtako'pir",
                "To'rtko'l", "Xo'jayli"
            ],
        }

        for (region_name, rtype), districts in ALL_REGIONS.items():
            # Viloyatni qo'shamiz yoki topamiz
            cursor.execute("SELECT id FROM regions WHERE name=? AND parent_id IS NULL", (region_name,))
            row = cursor.fetchone()
            if row:
                region_id = row[0]
            else:
                cursor.execute(
                    "INSERT INTO regions (name, parent_id, type) VALUES (?,NULL,?)",
                    (region_name, rtype)
                )
                region_id = cursor.lastrowid

            # Tumanlarni qo'shamiz (yo'q bo'lsa)
            for d in districts:
                cursor.execute(
                    "INSERT OR IGNORE INTO regions (name, parent_id, type) VALUES (?,?,'district')",
                    (d, region_id)
                )

        conn.commit()

        # Takror tumanlarni tozalash (INSERT OR IGNORE ishlamagan holatlarda)
        cursor.execute("""
            DELETE FROM regions WHERE id NOT IN (
                SELECT MIN(id) FROM regions
                GROUP BY parent_id, name
            ) AND parent_id IS NOT NULL
        """)
        if cursor.rowcount > 0:
            conn.commit()

    def get_regions(self, parent_id=None):
        """Viloyatlar (parent_id=None) yoki tumanlar (parent_id=viloyat_id)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if parent_id is None:
            cursor.execute("SELECT * FROM regions WHERE parent_id IS NULL ORDER BY name")
        else:
            cursor.execute("SELECT * FROM regions WHERE parent_id=? ORDER BY name", (parent_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_region_by_id(self, region_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM regions WHERE id=?", (region_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_region_label(self, region_id):
        """region_id -> o'qiladigan hudud matni: 'Viloyat → Tuman' yoki 'Viloyat'.
        Topilmasa None qaytaradi."""
        if not region_id:
            return None
        r = self.get_region_by_id(region_id)
        if not r:
            return None
        if r.get('parent_id'):
            parent = self.get_region_by_id(r['parent_id'])
            return f"{parent['name']} → {r['name']}" if parent else r['name']
        return r['name']

    def search_shops(self, query=None, region_id=None):
        """Do'konlarni qidirish (nomi yoki manzili bo'yicha).
        Tasdiqlangan (is_verified) do'konlar birinchi ko'rsatiladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT u.id, u.name, u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number, u.region_id, u.is_verified,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=u.id) as avg_rating,
                   (SELECT COUNT(*) FROM products p WHERE p.seller_id=u.id
                    AND p.in_stock=1 AND COALESCE(p.status,'active')='active') as product_count
            FROM users u
            WHERE u.role='seller' AND u.is_blocked=0 AND u.shop_name IS NOT NULL
                  AND COALESCE(u.is_approved,0)=1
        """
        params = []
        if query:
            variants = generate_search_variants(query)
            if variants:
                like_clauses = []
                for v in variants:
                    like_clauses.append("(u.shop_name LIKE ? OR u.name LIKE ? OR u.shop_address LIKE ?)")
                    params += [f"%{v}%", f"%{v}%", f"%{v}%"]
                sql += " AND (" + " OR ".join(like_clauses) + ")"
            else:
                sql += " AND (u.shop_name LIKE ? OR u.name LIKE ?)"
                params += [f"%{query}%", f"%{query}%"]
        if region_id:
            sql += " AND u.region_id=?"
            params.append(region_id)
        # Tasdiqlangan do'konlar birinchi, keyin reyting bo'yicha
        sql += " ORDER BY u.is_verified DESC, avg_rating DESC, product_count DESC"
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def get_shop_products(self, seller_id):
        """Bitta do'konning barcha sotuvdagi mahsulotlari.
        Har bir mahsulot uchun mahsulot reytingi va baholar soni ham qaytadi
        (Uzum uslubidagi rasmli kartochka katalogida ko'rsatish uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name, c.emoji as category_emoji,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=p.seller_id) as avg_rating,
                   (SELECT AVG(r2.product_rating) FROM reviews r2
                      WHERE r2.product_id=p.id AND r2.product_rating IS NOT NULL) as prod_avg_rating,
                   (SELECT COUNT(*) FROM reviews r3
                      WHERE r3.product_id=p.id AND r3.product_rating IS NOT NULL) as prod_review_count
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.seller_id=? AND p.in_stock=1 AND COALESCE(p.status,'active')='active'
            ORDER BY p.created_at DESC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_similar_products(self, product_id, limit=3):
        """Berilgan mahsulotga o'xshash mahsulotlar — sotuvni oshirish uchun taklif.
        Shu do'kondan, avval bir xil kategoriya, keyin narxga eng yaqinlari.
        (Savat bitta do'kon uchun bo'lgani sabab faqat shu do'kondan tanlanadi.)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT seller_id, category_id, price FROM products WHERE id=?", (product_id,))
        base = cursor.fetchone()
        if not base:
            return []
        cursor.execute("""
            SELECT p.*, c.emoji as category_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.seller_id=? AND p.id!=? AND p.in_stock=1
                  AND COALESCE(p.status,'active')='active'
            ORDER BY (p.category_id IS NOT NULL AND p.category_id=?) DESC,
                     ABS(p.price - ?) ASC
            LIMIT ?
        """, (base['seller_id'], product_id, base['category_id'], base['price'], limit))
        return [dict(r) for r in cursor.fetchall()]

    def get_seller_public_info(self, seller_id):
        """Sotuvchi ommaviy ma'lumotlari (xaridor uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.name, u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number, u.region_id, u.is_verified,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=u.id) as avg_rating,
                   (SELECT COUNT(*) FROM products p WHERE p.seller_id=u.id
                    AND p.in_stock=1 AND COALESCE(p.status,'active')='active') as product_count,
                   (SELECT COUNT(*) FROM orders o WHERE o.seller_id=u.id
                    AND o.status='delivered') as delivered_count
            FROM users u WHERE u.id=?
        """, (seller_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_admin_stats_summary(self):
        """Admin statistikasi — bitta efficient so'rovlar to'plami."""
        conn = self.get_connection()
        cur = conn.cursor()

        # Foydalanuvchilar soni (rollar bo'yicha)
        cur.execute("""
            SELECT role, COUNT(*) as cnt FROM users GROUP BY role
        """)
        role_counts = {r[0]: r[1] for r in cur.fetchall()}

        # Mahsulotlar soni
        cur.execute("SELECT COUNT(*) FROM products")
        products_count = cur.fetchone()[0]

        # Buyurtmalar holati bo'yicha soni + aylanma
        cur.execute("""
            SELECT status, COUNT(*) as cnt, COALESCE(SUM(total_price), 0) as revenue
            FROM orders GROUP BY status
        """)
        order_stats = {r[0]: {'count': r[1], 'revenue': r[2]} for r in cur.fetchall()}

        # Vaqt bo'yicha aylanma (delivered)
        cur.execute("""
            SELECT
                SUM(CASE WHEN DATE(created_at)=DATE('now') THEN total_price ELSE 0 END) as today,
                SUM(CASE WHEN created_at>=DATE('now','-7 days') THEN total_price ELSE 0 END) as week,
                SUM(CASE WHEN created_at>=DATE('now','-30 days') THEN total_price ELSE 0 END) as month,
                SUM(total_price) as total,
                COUNT(CASE WHEN DATE(created_at)=DATE('now') THEN 1 END) as today_cnt,
                COUNT(CASE WHEN created_at>=DATE('now','-7 days') THEN 1 END) as week_cnt,
                COUNT(CASE WHEN created_at>=DATE('now','-30 days') THEN 1 END) as month_cnt
            FROM orders WHERE status='delivered'
        """)
        rev = cur.fetchone()

        # Top sotuvchi
        cur.execute("""
            SELECT u.name, COUNT(o.id) as cnt
            FROM orders o JOIN users u ON o.seller_id=u.id
            WHERE o.status='delivered'
            GROUP BY o.seller_id ORDER BY cnt DESC LIMIT 1
        """)
        top = cur.fetchone()

        return {
            'buyers': role_counts.get('buyer', 0),
            'sellers': role_counts.get('seller', 0),
            'admins': role_counts.get('admin', 0),
            'total_users': sum(role_counts.values()),
            'products': products_count,
            'pending': order_stats.get('pending', {}).get('count', 0),
            'confirmed': order_stats.get('confirmed', {}).get('count', 0),
            'delivered': order_stats.get('delivered', {}).get('count', 0),
            'cancelled': order_stats.get('cancelled', {}).get('count', 0),
            'total_orders': sum(s['count'] for s in order_stats.values()),
            'today_revenue': float(rev[0] or 0),
            'week_revenue': float(rev[1] or 0),
            'month_revenue': float(rev[2] or 0),
            'total_revenue': float(rev[3] or 0),
            'today_count': rev[4] or 0,
            'week_count': rev[5] or 0,
            'month_count': rev[6] or 0,
            'top_seller': top[0] if top else None,
            'top_seller_count': top[1] if top else 0,
        }

    def get_analytics_funnel(self):
        """Conversion funnel: buyurtma → tasdiqlangan → yetkazilgan.
        Haftalik va oylik ko'rsatkichlar."""
        conn = self.get_connection()
        cur = conn.cursor()

        # Umumiy funnel
        cur.execute("""
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status IN ('confirmed','delivered') THEN 1 END) as confirmed_total,
                COUNT(CASE WHEN status='delivered' THEN 1 END) as delivered_total,
                COUNT(CASE WHEN status='cancelled' THEN 1 END) as cancelled_total
            FROM orders
        """)
        row = cur.fetchone()
        total = row[0] or 1  # 0 ga bo'lishdan himoya

        # Haftalik funnel
        cur.execute("""
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status IN ('confirmed','delivered') THEN 1 END) as confirmed,
                COUNT(CASE WHEN status='delivered' THEN 1 END) as delivered,
                COUNT(CASE WHEN status='cancelled' THEN 1 END) as cancelled
            FROM orders
            WHERE created_at >= datetime('now', '-7 days')
        """)
        week = cur.fetchone()
        week_total = week[0] or 1

        # Oylik funnel
        cur.execute("""
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status IN ('confirmed','delivered') THEN 1 END) as confirmed,
                COUNT(CASE WHEN status='delivered' THEN 1 END) as delivered,
                COUNT(CASE WHEN status='cancelled' THEN 1 END) as cancelled
            FROM orders
            WHERE created_at >= datetime('now', '-30 days')
        """)
        month = cur.fetchone()
        month_total = month[0] or 1

        # O'rtacha buyurtma qiymati
        cur.execute("""
            SELECT AVG(total_price) FROM orders WHERE status='delivered'
        """)
        avg_order = cur.fetchone()[0] or 0

        # Eng faol soatlar (buyurtma berilgan vaqt)
        cur.execute("""
            SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour, COUNT(*) as cnt
            FROM orders
            GROUP BY hour
            ORDER BY cnt DESC
            LIMIT 5
        """)
        peak_hours = [(r[0], r[1]) for r in cur.fetchall()]

        # Eng ko'p buyurtma berilgan kunlar (hafta kuni)
        cur.execute("""
            SELECT CAST(strftime('%w', created_at) AS INTEGER) as weekday, COUNT(*) as cnt
            FROM orders
            GROUP BY weekday
            ORDER BY cnt DESC
        """)
        day_names = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba',
                     'Payshanba', 'Juma', 'Shanba']
        peak_days = [(day_names[r[0]], r[1]) for r in cur.fetchall()]

        # Yangi foydalanuvchilar (hafta/oy)
        cur.execute("""
            SELECT
                COUNT(CASE WHEN created_at >= datetime('now', '-7 days') THEN 1 END) as week_users,
                COUNT(CASE WHEN created_at >= datetime('now', '-30 days') THEN 1 END) as month_users
            FROM users
        """)
        new_users = cur.fetchone()

        # Top kategoriyalar (buyurtma soni bo'yicha)
        cur.execute("""
            SELECT c.name, c.emoji, COUNT(o.id) as cnt
            FROM orders o
            JOIN products p ON o.product_id=p.id
            LEFT JOIN categories c ON p.category_id=c.id
            WHERE o.status='delivered'
            GROUP BY p.category_id
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_categories = [(r[1] or '', r[0] or 'Boshqa', r[2]) for r in cur.fetchall()]

        # Top mahsulotlar (buyurtma soni bo'yicha)
        cur.execute("""
            SELECT p.name, COUNT(o.id) as cnt, SUM(o.total_price) as revenue
            FROM orders o
            JOIN products p ON o.product_id=p.id
            WHERE o.status='delivered'
            GROUP BY o.product_id
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_products = [(r[0], r[1], r[2]) for r in cur.fetchall()]

        return {
            'total_orders': row[0] or 0,
            'confirmed_total': row[1] or 0,
            'delivered_total': row[2] or 0,
            'cancelled_total': row[3] or 0,
            'confirm_rate': round((row[1] or 0) / total * 100, 1),
            'deliver_rate': round((row[2] or 0) / total * 100, 1),
            'cancel_rate': round((row[3] or 0) / total * 100, 1),
            'week_orders': week[0] or 0,
            'week_confirmed': week[1] or 0,
            'week_delivered': week[2] or 0,
            'week_cancelled': week[3] or 0,
            'week_confirm_rate': round((week[1] or 0) / week_total * 100, 1),
            'week_deliver_rate': round((week[2] or 0) / week_total * 100, 1),
            'month_orders': month[0] or 0,
            'month_confirmed': month[1] or 0,
            'month_delivered': month[2] or 0,
            'month_cancelled': month[3] or 0,
            'month_confirm_rate': round((month[1] or 0) / month_total * 100, 1),
            'month_deliver_rate': round((month[2] or 0) / month_total * 100, 1),
            'avg_order_value': avg_order,
            'peak_hours': peak_hours,
            'peak_days': peak_days,
            'new_users_week': new_users[0] or 0,
            'new_users_month': new_users[1] or 0,
            'top_categories': top_categories,
            'top_products': top_products,
        }
