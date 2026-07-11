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
                # busy_timeout ENG BIRINCHI o'rnatiladi — keyingi PRAGMA'lar (ayniqsa
                # journal_mode=WAL'ga o'tish) ham qulf talab qiladi; timeout undan oldin
                # qo'yilmasa, WAL'ga o'tishning o'zi "database is locked" berishi mumkin
                # (bir nechta Database() bir faylda yonma-yon init bo'lganda). Audit #2.
                conn.execute("PRAGMA busy_timeout=5000")
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
            ("last_active_at", "TIMESTAMP"),   # faollik kuzatuvi (DAU/WAU/MAU; faol vs bir martalik)
            ("spam_count", "INTEGER DEFAULT 0"),  # bloklangan spam/flood urinishlari soni
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass

        # last_active_at boshlang'ich qiymati: eski yozuvlarda yo'q bo'lsa ro'yxatdan
        # o'tgan vaqtga tenglashtiramiz (faollik tarixi shu nuqtadan boshlanadi).
        try:
            cursor.execute("UPDATE users SET last_active_at = created_at WHERE last_active_at IS NULL")
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
            ("orders",   "courier_lat",       "REAL"),               # #13 yetkazib beruvchi joriy lat (jonli kuzatuv)
            ("orders",   "courier_lon",       "REAL"),               # #13 yetkazib beruvchi joriy lon
            ("orders",   "courier_updated_at", "TIMESTAMP"),         # #13 joylashuv oxirgi yangilangan vaqt (UTC)
            ("orders",   "courier_id",        "INTEGER"),            # #3 biriktirilgan KURYER user_id (NULL = biriktirilmagan)
            ("orders",   "courier_notify",    "INTEGER DEFAULT 0"),  # #3 1 = kuryerga "biriktirildi" PUSH yuborilishi kerak (bot fon job)
            ("products", "stock_count",    "INTEGER"),            # NULL = cheksiz
            ("products", "region_id",      "INTEGER"),            # do'kon hududi
            ("products", "status",         "TEXT DEFAULT 'active'"),  # active|reserve|deleted|mod_blocked
            ("products", "mod_reason",      "TEXT"),                   # #5 avto-moderatsiya bloklash sababi
            ("products", "min_price",       "REAL"),                   # #8 MAXFIY oxirgi narx (savdolashish floor'i; xaridorga ko'rinmaydi)
            ("products", "wholesale_price",   "REAL"),                  # optom (ulgurji) dona narxi (eski yagona zina; moslik)
            ("products", "wholesale_min_qty", "INTEGER"),               # optom narx amal qiladigan minimal son (eski yagona zina)
            ("products", "wholesale_tiers",   "TEXT"),                  # optom ZINALARI JSON: [{"min":int,"price":num},...] (min bo'yicha o'sib)
            ("products", "boosted_until",   "TIMESTAMP"),              # #18 boost (pullik ko'tarish) tugash vaqti (UTC); NULL/o'tgan = boost yo'q
            ("products", "ad_caption",      "TEXT"),                   # kanalga e'lon qilingan AYNAN reklama matni (App buyer sahifasi shuni ko'rsatadi — kanal pariteti)
            ("products", "ad_caption_pm",   "TEXT"),                   # ↑ reklama matni parse_mode: 'HTML' (tuzilgan) yoki NULL (AI oddiy matn)
            ("orders",   "commission_amount", "REAL"),                 # #18 platforma komissiyasi (berish paytida hisoblanadi)
            ("orders",   "commission_settled_at", "TIMESTAMP"),        # #18 komissiya admin tomonidan undirilgan (to'langan) vaqt; NULL = qarz hali ochiq
            ("users",    "pro_until",        "TIMESTAMP"),             # #18 Pro-obuna tugash vaqti (UTC); ega (owner)da saqlanadi
            ("reviews",  "product_id",     "INTEGER"),            # baho qaysi mahsulotga
            ("reviews",  "product_rating", "INTEGER"),            # mahsulot uchun 1-5
            ("reviews",  "seller_reply",   "TEXT"),               # sotuvchining ochiq javobi (NULL = javob yo'q)
            ("reviews",  "replied_at",     "TIMESTAMP"),          # javob yozilgan vaqt
            ("product_attributes", "attr_label", "TEXT"),         # ko'rsatish uchun yorliq (AI savollar uchun — shablon yo'q)
            ("orders",   "variant_label",   "TEXT"),               # variant-buyurtma: qaysi rasm/hil (masalan "#1" yoki "Qora") — NULL = oddiy buyurtma
            ("orders",   "variant_size",    "TEXT"),               # variant-buyurtma: tanlangan razmer (NULL = razmer yo'q)
            ("orders",   "variant_color",   "TEXT"),               # variant-buyurtma: tanlangan rang (NULL = rang yo'q)
            ("product_images", "label",      "TEXT"),              # har rasmga (variant/hil) ixtiyoriy nom ("Qora", "Oq"); NULL = "#N"
            ("products", "min_order_qty",   "INTEGER"),            # variant-buyurtma JAMI minimal son (NULL = eng past optom zina mini, u ham yo'q = 1)
            ("products", "sale_mode",       "TEXT DEFAULT 'dona'"), # 'dona' (donalab) | 'optom' (pachka). Eski mahsulotlar = 'dona'
            ("products", "pack_size",       "INTEGER"),            # optom: 1 pachkadagi dona soni (NULL = dona rejimi)
            ("products", "size_note",       "TEXT"),               # optom: razmer matni (butun mahsulotga; xaridor tanlamaydi)
            ("products", "delivery_available", "INTEGER DEFAULT 1"),  # 1=yetkaziladi, 0=faqat olib ketish (sotuvchi belgilaydi)
            ("users",    "delivery_min_total", "REAL"),               # do'kon: yetkazish uchun minimal buyurtma summasi (NULL/0 = cheklov yo'q)
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
                seller_reply TEXT,                 -- sotuvchining ochiq javobi (yangi bazada inline)
                replied_at TIMESTAMP,              -- javob yozilgan vaqt
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

        # Bitta mahsulot uchun bir nechta rasm (5 tagacha — har rasm = bir variant/hil).
        # Birinchi rasm (position=0) products.image_url bilan ham sinxron saqlanadi —
        # shunda eski kod (ro'yxat, havola) ham ishlayveradi.
        # label — har rasmga (variant) ixtiyoriy nom; eski bazalarda migratsiya qo'shadi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                position INTEGER DEFAULT 0,
                label TEXT,
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
                perm_add_staff     INTEGER DEFAULT 0,   -- xodim qo'shish (menejer; default O'CHIQ)
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
        # perm_add_staff — eski bazalar uchun idempotent qo'shamiz (menejerga xodim qo'shish ruxsati)
        try:
            cursor.execute("ALTER TABLE shop_staff ADD COLUMN perm_add_staff INTEGER DEFAULT 0")
        except Exception:
            pass
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
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN old_price REAL")  # chegirma: eski narx
        except Exception:
            pass
        try:
            # #20 — o'lchov birligi (dona/kg/litr/metr/tonna...). Bo'sh = "dona" deb qaraladi.
            cursor.execute("ALTER TABLE products ADD COLUMN unit TEXT")
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
            # MUHIM: rollback qilmasak, ochiq tranzaksiya yozish-qulfini ushlab qoladi
            # va shu ulanish boshqa hech narsa yoza olmaydi (init_db keyingi qadamlari
            # ham, bir faylga ulangan boshqa Database() ham qulflanadi). Audit #2.
            try:
                conn.rollback()
            except Exception:
                pass
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
            ("Oyoq kiyimlari", "👟", "Erkaklar, ayollar va bolalar oyoq kiyimlari"),
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

        # "Oyoq kiyimlari" atribut shabloni — yuqoridagi blok FAQAT bo'sh jadvalda ishlaydi,
        # bu kategoriya esa keyin qo'shilgani uchun har init'da idempotent (INSERT OR IGNORE,
        # UNIQUE(category_id, attr_key)) qo'shamiz — jonli bazada ham paydo bo'lsin.
        cursor.execute("SELECT id FROM categories WHERE name=?", ("Oyoq kiyimlari",))
        _shoe = cursor.fetchone()
        if _shoe:
            _shoe_id = _shoe[0]
            for attr_key, attr_label, attr_type, required, hint in [
                ("size",     "O'lcham (razmer)", "text",   1, "36, 37, 38, 39, 40, 41, 42, 43..."),
                ("color",    "Rangi",            "text",   1, "Qora, Oq, Jigarrang, Ko'k..."),
                ("gender",   "Jinsi",            "select", 0, "Erkak/Ayol/Bolalar/Uniseks"),
                ("brand",    "Brend",            "text",   0, "Nike, Adidas, Puma, Ecco..."),
                ("material", "Material",         "text",   0, "Charm, Zamsh, Tekstil, Rezina..."),
                ("season",   "Fasli",            "text",   0, "Yoz, Qish, Demi-sezon"),
            ]:
                cursor.execute("""
                    INSERT OR IGNORE INTO category_attribute_templates
                    (category_id, attr_key, attr_label, attr_type, is_required, hint)
                    VALUES (?,?,?,?,?,?)
                """, (_shoe_id, attr_key, attr_label, attr_type, required, hint))
            conn.commit()

        # Zamonaviy kategoriyalar atribut shablonlari — shoe bloki kabi idempotent
        # (har init'da INSERT OR IGNORE, UNIQUE(category_id, attr_key)) — jonli bazada
        # ham paydo bo'lsin. Hammasi ixtiyoriy (is_required=0) — mahsulot qo'shishni
        # yengillashtirish maqsad. Tugma-variantlar webapp_server._ATTR_PRESETS'da.
        _modern_templates = {
            "Go'zallik va parfyumeriya": [
                ("type",   "Turi",   "text",   0, "Parfyum, Krem, Pomada..."),
                ("brand",  "Brend",  "text",   0, "Chanel, Dior, Nivea..."),
                ("volume", "Hajmi",  "text",   0, "30ml, 50ml, 100ml..."),
                ("gender", "Kimga",  "select", 0, "Erkak/Ayol/Uniseks"),
            ],
            "Salomatlik va dorixona": [
                ("type",         "Turi",    "text",   0, "Dori, Vitamin, BAD..."),
                ("form",         "Shakli",  "text",   0, "Tabletka, Sirop, Malham..."),
                ("prescription", "Retsept", "select", 0, "Retseptsiz/Retsept bilan"),
            ],
            "Bolalar mahsulotlari": [
                ("type",   "Turi",  "text",   0, "O'yinchoq, Kiyim, Aravacha..."),
                ("age",    "Yosh",  "text",   0, "0-1, 1-3, 3-6 yosh..."),
                ("gender", "Kimga", "select", 0, "O'g'il bola/Qiz bola/Uniseks"),
            ],
            "Sport va dam olish": [
                ("type",   "Turi",    "text",   0, "Sport kiyim, Trenajyor, Top..."),
                ("size",   "O'lcham", "text",   0, "S, M, L, XL..."),
                ("gender", "Kimga",   "select", 0, "Erkak/Ayol/Uniseks"),
            ],
            "Uy va mebel": [
                ("type",     "Turi",     "text", 0, "Divan, Stol, Shkaf..."),
                ("material", "Material", "text", 0, "Yog'och, Metall, Plastik..."),
                ("room",     "Xona",     "text", 0, "Yotoqxona, Mehmonxona..."),
            ],
            "Kitob va kanstovarlar": [
                ("type",     "Turi", "text", 0, "Kitob, Daftar, Qalam..."),
                ("language", "Tili", "text", 0, "O'zbek, Rus, Ingliz..."),
            ],
            "Qurilish mollari": [
                ("type", "Turi",    "text", 0, "G'isht, Sement, Bo'yoq..."),
                ("unit", "O'lchov", "text", 0, "Dona, Kg, Tonna, m²..."),
            ],
            "Hayvonlar uchun": [
                ("animal", "Hayvon", "text", 0, "It, Mushuk, Qush..."),
                ("type",   "Turi",   "text", 0, "Ozuqa, O'yinchoq, Dori..."),
            ],
            "Gul va sovg'alar": [
                ("type",     "Turi",      "text", 0, "Atirgul, Buket, Sovg'a..."),
                ("occasion", "Munosabat", "text", 0, "Tug'ilgan kun, To'y, 8-mart..."),
            ],
        }
        for cat_name, attrs in _modern_templates.items():
            cursor.execute("SELECT id FROM categories WHERE name=?", (cat_name,))
            row = cursor.fetchone()
            if not row:
                continue
            cid = row[0]
            for attr_key, attr_label, attr_type, required, hint in attrs:
                cursor.execute("""
                    INSERT OR IGNORE INTO category_attribute_templates
                    (category_id, attr_key, attr_label, attr_type, is_required, hint)
                    VALUES (?,?,?,?,?,?)
                """, (cid, attr_key, attr_label, attr_type, required, hint))
        conn.commit()

        # ===== PLATFORMA SOZLAMALARI (kalit-qiymat) — monetizatsiya #22/#18 =====
        # Admin yoqadigan/o'chiradigan bayroqlar shu yerda saqlanadi (komissiya, boost,
        # obuna, Click/Payme...). HAMMASI default O'CHIQ — yoqilmaguncha foydalanuvchiga
        # hech narsa o'zgarmaydi. Qiymatlar TEXT sifatida saqlanadi (kod typed o'qiydi).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS platform_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # ===== SEVIMLILAR (#16 wishlist) — narx tushganda xabar uchun ham manba =====
        # products(id) ga ON DELETE CASCADE — mahsulot o'chsa sevimli yozuvi ham o'chadi
        # (delete_product'da FK xatosi/HTTP 500 bo'lmaydi).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(buyer_id, product_id),
                FOREIGN KEY (buyer_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        conn.commit()

        # ===== AI SAVDOLASHISH KELISHUVLARI (#8) =====
        # AI bilan savdolashishda kelishilgan narx shu yerda saqlanadi; checkout shuni
        # hurmat qiladi. Qisqa muddatli (expires_at). products(id) ON DELETE CASCADE.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS haggle_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                price REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                UNIQUE(buyer_id, product_id),
                FOREIGN KEY (buyer_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        conn.commit()

        # ===== TO'LOVLAR DAFTARI (monetizatsiya #18) =====
        # Boost / Pro-obuna uchun to'lov yozuvlari. Click/Payme webhooklari shu yozuvni
        # 'paid' qiladi va maqsadini (purpose) bajaradi (boost qo'yadi / pro_until uzaytiradi).
        # provider: 'click' | 'payme' | 'manual' (admin qo'lda/test tasdiqi).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purpose TEXT NOT NULL,            -- 'boost' | 'subscription'
                ref_id INTEGER,                   -- boost uchun product_id (obuna uchun NULL)
                amount REAL NOT NULL,
                provider TEXT,                    -- 'click' | 'payme' | 'manual'
                provider_txn_id TEXT,             -- provayder tranzaksiya ID (idempotentlik)
                provider_meta TEXT,               -- provayderga xos JSON (masalan Payme holat/vaqtlar/cancel reason)
                state TEXT DEFAULT 'pending'      -- 'pending' | 'paid' | 'cancelled'
                    CHECK(state IN ('pending','paid','cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # #18 Pro — kvota hisoblagichi: oylik bepul boost va bepul AI reels sonini
        # davr (YYYY-MM) kesimida sanaydi. Pro = cheksiz; bepul sotuvchi = limitli.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feature_usage (
                user_id INTEGER NOT NULL,
                feature TEXT NOT NULL,            -- 'boost_free' | 'reels'
                period  TEXT NOT NULL,            -- 'YYYY-MM' (UTC)
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, feature, period)
            )
        """)

        # Universal XABARNOMA — foydalanuvchiga kelgan HAR qanday xabar (murojaat javobi,
        # Pro, to'lov, nizo, e'lon...) shu yerga yoziladi → app top'da banner + Telegram push.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'info',  -- 'support' | 'pro' | 'payment' | 'dispute' | 'info'
                title TEXT,
                body TEXT,
                ref_id INTEGER,                     -- bog'liq obyekt (support_thread.id, order.id...)
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read)")

        # MUROJAAT (support) — foydalanuvchi↔admin 2 tomonlama suhbat. Thread = bitta murojaat
        # (sabab + holat), messages = yozishmalar. Admin app ichida ko'radi va javob beradi.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,           -- murojaat egasi (foydalanuvchi)
                reason TEXT,                        -- tanlangan sabab kaliti
                status TEXT NOT NULL DEFAULT 'open' -- 'open' | 'closed'
                    CHECK(status IN ('open','closed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                sender_role TEXT NOT NULL,          -- 'user' | 'admin'
                sender_id INTEGER,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES support_threads(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_msg_thread ON support_messages(thread_id)")
        conn.commit()

        # ===== INDEKSLAR (tezlik #3) =====
        # SQLite indekssiz har so'rovda to'liq jadval skan qiladi. Eng og'ir yo'l —
        # search_products: har mahsulot uchun reviews bo'yicha 3 ta korrelyatsion
        # subquery ishlaydi; reviews(seller_id)/reviews(product_id) indekslari ularni
        # skan'dan qidiruvga aylantiradi. (users.telegram_id va shop_staff.user_id
        # UNIQUE — avtomatik indekslangan, qayta qo'shilmaydi.)
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id)",
            "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id)",
            "CREATE INDEX IF NOT EXISTS idx_products_listing ON products(in_stock, status)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_seller ON reviews(seller_id)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product_id)",
            # Guruh (savat/variant) amallari — transition_group_status/get_orders_in_group/
            # agree_group_cancel/set_group_settlement doim order_group_id bo'yicha qidiradi.
            # Indekssiz bu to'liq SCAN edi (buyurtma ko'paygach sekinlashardi).
            "CREATE INDEX IF NOT EXISTS idx_orders_group ON orders(order_group_id)",
            "CREATE INDEX IF NOT EXISTS idx_shop_staff_shop ON shop_staff(shop_id)",
            "CREATE INDEX IF NOT EXISTS idx_scheduled_product ON scheduled_posts(product_id)",
            "CREATE INDEX IF NOT EXISTS idx_product_audit_product ON product_audit(product_id)",
            "CREATE INDEX IF NOT EXISTS idx_favorites_buyer ON favorites(buyer_id)",
            "CREATE INDEX IF NOT EXISTS idx_favorites_product ON favorites(product_id)",
            "CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_payments_txn ON payments(provider, provider_txn_id)",
        ]:
            try:
                cursor.execute(idx_sql)
            except Exception as e:
                logging.warning(f"indeks yaratish o'tkazib yuborildi: {e}")
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
            "INSERT INTO users (telegram_id, phone_number, name, role, referral_code, last_active_at) "
            "VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
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

    def touch_user_activity(self, user_id=None, telegram_id=None, throttle_minutes=10):
        """Foydalanuvchi faolligini (last_active_at) hozirgi vaqtga yangilaydi — THROTTLED.
        user_id YOKI telegram_id bo'yicha. Faqat oxirgi faollik throttle_minutes'dan
        eski (yoki NULL) bo'lsa yozadi — har so'rovda ortiqcha yozuvni oldini oladi.
        Bot va App'dagi har qanday harakat chaqiradi → "faol" vs "bir martalik" farqi shu."""
        if user_id is None and telegram_id is None:
            return
        col, val = ("id", user_id) if user_id is not None else ("telegram_id", telegram_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE users SET last_active_at=CURRENT_TIMESTAMP "
            f"WHERE {col}=? AND (last_active_at IS NULL "
            f"OR last_active_at < datetime('now','-{int(throttle_minutes)} minutes'))",
            (val,)
        )
        conn.commit()

    def increment_spam_count(self, value):
        """Bloklangan spam/flood urinishini foydalanuvchiga yozadi (admin statistikasi
        uchun: 'nechtasi spam qilgan'). `value` — DB id YOKI telegram_id bo'lishi mumkin;
        avval id bo'yicha urinamiz, mos kelmasa telegram_id bo'yicha (chaqiruv joylari
        ikkala turdagi raqamni uzatadi). Hech qayerga mos kelmasa — jim e'tibor bermaydi."""
        if value is None:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET spam_count = COALESCE(spam_count,0) + 1 WHERE id=?", (value,))
        if cursor.rowcount == 0:
            cursor.execute(
                "UPDATE users SET spam_count = COALESCE(spam_count,0) + 1 WHERE telegram_id=?",
                (value,))
        conn.commit()

    def delete_user_completely(self, user_id):
        """Foydalanuvchini VA u bilan bog'liq BARCHA ma'lumotni butunlay o'chiradi —
        test akkauntini '0 ga qaytarish' uchun. Keyin xuddi yangidek qayta ro'yxatdan
        o'tish mumkin. FK enforcement ON bo'lgani uchun bola qatorlar AVVAL, foydalanuvchi
        qatori ENG OXIRIDA o'chiriladi. Qaytaradi: {'ok':bool, 'deleted':{jadval:son}}.
        Eslatma: asosiy admin (ADMIN_ID) o'chirilsa ham, telegram_id o'zgarmagani uchun
        qayta ro'yxatdan o'tganda admin huquqi env orqali avtomatik tiklanadi."""
        conn = self.get_connection()
        cur = conn.cursor()
        deleted = {}

        def _run(sql, params=()):
            try:
                cur.execute(sql, params)
                return cur.rowcount or 0
            except Exception:
                return 0

        def _add(name, n):
            if n and n > 0:
                deleted[name] = deleted.get(name, 0) + n

        uid = user_id
        # 1) Shu foydalanuvchiga tegishli mahsulot va buyurtma id'lari
        cur.execute("SELECT id FROM products WHERE seller_id=? OR created_by=?", (uid, uid))
        product_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM orders WHERE buyer_id=? OR seller_id=? OR courier_id=?",
                    (uid, uid, uid))
        order_ids = {r[0] for r in cur.fetchall()}
        if product_ids:
            qm = ",".join("?" * len(product_ids))
            cur.execute(f"SELECT id FROM orders WHERE product_id IN ({qm})", product_ids)
            order_ids |= {r[0] for r in cur.fetchall()}
        order_ids = list(order_ids)

        def _del_in(table, col, ids):
            if not ids:
                return
            qm = ",".join("?" * len(ids))
            _add(table, _run(f"DELETE FROM {table} WHERE {col} IN ({qm})", list(ids)))

        # 2) Buyurtma-bog'liq bolalar
        _del_in("messages", "order_id", order_ids)
        _del_in("dispute_messages", "order_id", order_ids)
        _del_in("reviews", "order_id", order_ids)
        # 3) Mahsulot-bog'liq bolalar
        for tbl in ("product_attributes", "product_images", "product_audit",
                    "scheduled_posts", "auto_reposts", "favorites", "haggle_deals", "reviews"):
            _del_in(tbl, "product_id", product_ids)
        # 4) Buyurtmalar va mahsulotlar
        _del_in("orders", "id", order_ids)
        _del_in("products", "id", product_ids)
        # 5) Support tbranchlari (avval xabarlar, keyin tranchlar)
        try:
            cur.execute("SELECT id FROM support_threads WHERE user_id=?", (uid,))
            tids = [r[0] for r in cur.fetchall()]
        except Exception:
            tids = []
        _del_in("support_messages", "thread_id", tids)
        # 6) Foydalanuvchiga to'g'ridan-to'g'ri tegishli qolgan qatorlar
        _add("favorites", _run("DELETE FROM favorites WHERE buyer_id=?", (uid,)))
        _add("haggle_deals", _run("DELETE FROM haggle_deals WHERE buyer_id=?", (uid,)))
        _add("reviews", _run("DELETE FROM reviews WHERE seller_id=? OR buyer_id=?", (uid, uid)))
        _add("referrals", _run("DELETE FROM referrals WHERE referrer_id=? OR referred_id=?", (uid, uid)))
        _add("messages", _run("DELETE FROM messages WHERE sender_id=? OR receiver_id=?", (uid, uid)))
        _add("dispute_messages", _run("DELETE FROM dispute_messages WHERE sender_id=?", (uid,)))
        _add("payments", _run("DELETE FROM payments WHERE user_id=?", (uid,)))
        _add("feature_usage", _run("DELETE FROM feature_usage WHERE user_id=?", (uid,)))
        _add("notifications", _run("DELETE FROM notifications WHERE user_id=?", (uid,)))
        _add("seller_requests", _run("DELETE FROM seller_requests WHERE user_id=?", (uid,)))
        _add("seller_channels", _run("DELETE FROM seller_channels WHERE seller_id=?", (uid,)))
        _add("support_messages", _run("DELETE FROM support_messages WHERE sender_id=?", (uid,)))
        _add("support_threads", _run("DELETE FROM support_threads WHERE user_id=?", (uid,)))
        _add("shop_staff", _run("DELETE FROM shop_staff WHERE user_id=? OR added_by=?", (uid, uid)))
        _add("shop_invites", _run("DELETE FROM shop_invites WHERE created_by=? OR used_by=?", (uid, uid)))
        _add("shops", _run("DELETE FROM shops WHERE owner_user_id=?", (uid,)))
        _add("scheduled_posts", _run("DELETE FROM scheduled_posts WHERE seller_id=? OR created_by=?", (uid, uid)))
        _add("auto_reposts", _run("DELETE FROM auto_reposts WHERE seller_id=? OR created_by=?", (uid, uid)))
        _add("product_audit", _run("DELETE FROM product_audit WHERE seller_id=? OR deleted_by=?", (uid, uid)))
        # Boshqa foydalanuvchilar shu userni referrer sifatida ko'rsatgan bo'lsa — bog'lanishni uzamiz
        _run("UPDATE users SET referred_by=NULL WHERE referred_by=?", (uid,))
        # 7) NIHOYAT — foydalanuvchining o'zi
        n_user = _run("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        return {"ok": bool(n_user), "deleted": deleted}

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
                   u.pro_until as seller_pro_until, u.delivery_min_total,
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

        # #18 Boost — yoqilgan boost mahsulotlar har qanday saralashda eng tepada (gegemon).
        # Boostdan keyin — Pro do'konlar yengil ustunlikka ega (boostsiz ham biroz tepada).
        boost = ("(p.boosted_until IS NOT NULL AND p.boosted_until>datetime('now')) DESC, "
                 "(u.pro_until IS NOT NULL AND u.pro_until>datetime('now')) DESC, ")
        order_map = {
            'rating':     ' ORDER BY ' + boost + 'avg_rating DESC, p.created_at DESC',
            'price_asc':  ' ORDER BY ' + boost + 'p.price ASC',
            'price_desc': ' ORDER BY ' + boost + 'p.price DESC',
            'newest':     ' ORDER BY ' + boost + 'p.created_at DESC',
        }
        sql += order_map.get(sort_by, order_map['rating'])

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    # ===== KASHFIYOT (#15) — mavjud ma'lumotdan: trend / chegirma =====
    # Faol, ko'rinadigan mahsulotlar uchun umumiy filtr (search_products bilan bir xil).
    _DISCOVERY_SELECT = """
        SELECT p.*, c.name as category_name, c.emoji as category_emoji,
               u.shop_name, u.is_verified,
               (SELECT AVG(r2.product_rating) FROM reviews r2 WHERE r2.product_id=p.id AND r2.product_rating IS NOT NULL) as prod_avg_rating,
               (SELECT COUNT(*) FROM reviews r3 WHERE r3.product_id=p.id AND r3.product_rating IS NOT NULL) as prod_review_count
        FROM products p
        LEFT JOIN categories c ON p.category_id=c.id
        LEFT JOIN users u ON p.seller_id=u.id
        WHERE p.in_stock=1 AND COALESCE(p.status,'active')='active' AND COALESCE(u.is_blocked,0)=0
              AND (COALESCE(u.is_approved,0)=1 OR u.role='admin')
    """

    def get_trending_products(self, limit=12):
        """Eng ko'p buyurtma qilingan (trend) mahsulotlar. idx_orders_product'dan foydalanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = self._DISCOVERY_SELECT + """
              AND (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id) > 0
            ORDER BY (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id) DESC,
                     prod_avg_rating DESC, p.created_at DESC
            LIMIT ?"""
        cursor.execute(sql, (limit,))
        return [dict(r) for r in cursor.fetchall()]

    def get_recommendations(self, buyer_id, limit=12):
        """#1 — "Aynan siz uchun": ikki signalni birlashtiradi —
        (a) KOLLABORATIV: men olgan mahsulotlarni olgan boshqa xaridorlar yana nima olgan;
        (b) KATEGORIYA: xarid+sevimli tarixidagi yo'nalishlar.
        Kollaborativ avval (kuchliroq signal). Tarix bo'lmasa — bo'sh (trend qoladi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # (a) Co-purchase — "buni olganlar yana shuni oldi"
        cursor.execute("""
            SELECT o3.product_id, COUNT(*) AS score
            FROM orders o1
            JOIN orders o2 ON o2.product_id=o1.product_id AND o2.buyer_id != o1.buyer_id
            JOIN orders o3 ON o3.buyer_id=o2.buyer_id
            WHERE o1.buyer_id=?
              AND o3.product_id NOT IN (SELECT product_id FROM orders WHERE buyer_id=?)
            GROUP BY o3.product_id ORDER BY score DESC, o3.product_id DESC LIMIT 30
        """, (buyer_id, buyer_id))
        co_ids = [r[0] for r in cursor.fetchall()]
        # (b) Kategoriya-asosli
        cursor.execute("""
            SELECT DISTINCT category_id FROM (
                SELECT p.category_id FROM orders o JOIN products p ON o.product_id=p.id WHERE o.buyer_id=?
                UNION
                SELECT p.category_id FROM favorites f JOIN products p ON f.product_id=p.id WHERE f.buyer_id=?
            ) WHERE category_id IS NOT NULL
        """, (buyer_id, buyer_id))
        cats = [r[0] for r in cursor.fetchall()]
        cat_ids = []
        if cats:
            ph = ",".join("?" for _ in cats)
            cursor.execute(f"""
                SELECT p.id FROM products p
                WHERE COALESCE(p.status,'active')='active' AND p.in_stock=1
                  AND p.category_id IN ({ph})
                  AND p.id NOT IN (SELECT product_id FROM orders WHERE buyer_id=?)
                ORDER BY p.created_at DESC LIMIT 30
            """, cats + [buyer_id])
            cat_ids = [r[0] for r in cursor.fetchall()]
        # Birlashtirish — kollaborativ avval, dedupe
        ordered, seen = [], set()
        for i in co_ids + cat_ids:
            if i not in seen:
                seen.add(i)
                ordered.append(i)
        if not ordered:
            return []
        ordered = ordered[:limit]
        ph2 = ",".join("?" for _ in ordered)
        cursor.execute(self._DISCOVERY_SELECT + f" AND p.id IN ({ph2}) AND p.seller_id != ?",
                       ordered + [buyer_id])
        rows = {dict(r)["id"]: dict(r) for r in cursor.fetchall()}
        return [rows[i] for i in ordered if i in rows]   # birlashtirilgan tartibni saqlaymiz

    def get_fraud_signals(self):
        """AI #7 — firibgarlik shubhasi (evristik): o'z-o'ziga sharh, bitta juftlikda ko'p
        buyurtma, kam xaridordan ko'p sharh. Admin tekshiruvi uchun signal — avtomatik jazo yo'q."""
        conn = self.get_connection()
        cursor = conn.cursor()
        out = {"self_reviews": [], "order_farming": [], "few_reviewers": []}
        # 1) O'z-o'ziga sharh (sharh yozuvchi = do'kon egasi)
        cursor.execute("""
            SELECT r.id, u.name AS seller_name, r.seller_id
            FROM reviews r LEFT JOIN users u ON r.seller_id=u.id
            WHERE r.buyer_id = r.seller_id LIMIT 50
        """)
        out["self_reviews"] = [dict(r) for r in cursor.fetchall()]
        # 2) Bitta xaridor → bitta sotuvchiga ko'p buyurtma (soxta buyurtma shubhasi)
        cursor.execute("""
            SELECT o.buyer_id, o.seller_id, COUNT(*) AS cnt,
                   ub.name AS buyer_name, us.name AS seller_name
            FROM orders o
            LEFT JOIN users ub ON o.buyer_id=ub.id
            LEFT JOIN users us ON o.seller_id=us.id
            GROUP BY o.buyer_id, o.seller_id HAVING cnt >= 6
            ORDER BY cnt DESC LIMIT 50
        """)
        out["order_farming"] = [dict(r) for r in cursor.fetchall()]
        # 3) Sotuvchi sharhlari juda kam xaridordan (soxta reyting shubhasi)
        cursor.execute("""
            SELECT r.seller_id, us.name AS seller_name,
                   COUNT(*) AS reviews, COUNT(DISTINCT r.buyer_id) AS buyers
            FROM reviews r LEFT JOIN users us ON r.seller_id=us.id
            GROUP BY r.seller_id HAVING reviews >= 4 AND buyers <= 1
            ORDER BY reviews DESC LIMIT 50
        """)
        out["few_reviewers"] = [dict(r) for r in cursor.fetchall()]
        return out

    def get_category_price_stats(self, category_id, exclude_seller_id=None):
        """AI #2 — kategoriyadagi raqobatchi narx statistikasi (faol mahsulotlar).
        exclude_seller_id berilsa — o'sha sotuvchi mahsulotlari hisobga olinmaydi."""
        if not category_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """SELECT COUNT(*) AS n, AVG(p.price) AS avg_price,
                        MIN(p.price) AS min_price, MAX(p.price) AS max_price
                 FROM products p LEFT JOIN users u ON p.seller_id=u.id
                 WHERE p.category_id=? AND COALESCE(p.status,'active')='active' AND p.in_stock=1
                       AND p.price > 0 AND COALESCE(u.is_blocked,0)=0
                       AND (COALESCE(u.is_approved,0)=1 OR u.role='admin')"""
        params = [category_id]
        if exclude_seller_id:
            sql += " AND p.seller_id != ?"
            params.append(exclude_seller_id)
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        d = dict(row)
        return {"count": d["n"], "avg": round(d["avg_price"] or 0),
                "min": round(d["min_price"] or 0), "max": round(d["max_price"] or 0)}

    def get_frequently_bought_together(self, product_id, limit=8):
        """AI #10 cross-sell — shu mahsulotni olgan xaridorlar YANA nima olgan (item-to-item).
        Faol/ko'rinadigan mahsulotlar, eng ko'p birga olinganlari avval."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o2.product_id AS pid, COUNT(*) AS cnt
            FROM orders o1
            JOIN orders o2 ON o2.buyer_id=o1.buyer_id AND o2.product_id != o1.product_id
            WHERE o1.product_id=?
            GROUP BY o2.product_id ORDER BY cnt DESC, o2.product_id DESC LIMIT ?
        """, (product_id, limit))
        ids = [r[0] for r in cursor.fetchall()]
        if not ids:
            return []
        ph = ",".join("?" for _ in ids)
        cursor.execute(self._DISCOVERY_SELECT + f" AND p.id IN ({ph})", ids)
        rows = {dict(r)["id"]: dict(r) for r in cursor.fetchall()}
        return [rows[i] for i in ids if i in rows]   # birga-olinish tartibini saqlaymiz

    def get_discounted_products(self, limit=12):
        """Chegirmadagi mahsulotlar (old_price > price), eng katta chegirma % avval."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = self._DISCOVERY_SELECT + """
              AND p.old_price IS NOT NULL AND p.old_price > p.price AND p.price > 0
            ORDER BY (p.old_price - p.price)*1.0/p.old_price DESC, p.created_at DESC
            LIMIT ?"""
        cursor.execute(sql, (limit,))
        return [dict(r) for r in cursor.fetchall()]

    # ===== ORDERS =====
    def create_order(self, buyer_id, seller_id, product_id, quantity, total_price,
                     delivery_address=None, buyer_lat=None, buyer_lon=None,
                     payment_method=None, delivery_type=None, order_group_id=None,
                     variant_label=None, variant_size=None, variant_color=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (buyer_id, seller_id, product_id, quantity,
                                total_price, delivery_address, buyer_lat, buyer_lon,
                                payment_method, delivery_type, order_group_id,
                                variant_label, variant_size, variant_color)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (buyer_id, seller_id, product_id, quantity, total_price,
              delivery_address, buyer_lat, buyer_lon, payment_method, delivery_type,
              order_group_id, variant_label, variant_size, variant_color))
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
                   bu.telegram_username as buyer_username,
                   co.name as courier_name, co.phone_number as courier_phone,
                   co.telegram_id as courier_tg, co.telegram_username as courier_username
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            LEFT JOIN users co ON o.courier_id=co.id
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
        amount_due 0 ga tushsa settled_at o'rnatiladi; buyurtma topilmasa None.

        ATOMIK nisbiy UPDATE (read-modify-write EMAS) — bir vaqtda ikki to'lov kelsa ham
        qarz noto'g'ri absolute qiymat bilan ustidan yozilmaydi. MAX(0,...) qarzни manfiyга
        tushirmaydi (decrement_stock_on_confirm bilan bir naqsh)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        p = max(0.0, float(pay_amount))
        cursor.execute(
            "UPDATE orders SET "
            "amount_paid = COALESCE(amount_paid,0) + ?, "
            "amount_due = MAX(0, COALESCE(amount_due,0) - ?), "
            "settled_at = CASE WHEN COALESCE(amount_due,0) - ? <= 0 "
            "            THEN CURRENT_TIMESTAMP ELSE settled_at END "
            "WHERE id=?",
            (p, p, p, order_id))
        if cursor.rowcount == 0:
            conn.commit()
            return None
        cursor.execute("SELECT amount_due FROM orders WHERE id=?", (order_id,))
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else None

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

    def clean_old_cancelled_orders(self, days=30):
        """Bekor qilingan, `days` kundan eski buyurtmalarni o'chiradi. O'chirilgan sonni qaytaradi
        (bot admin_clean_cancelled pariteti)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM orders WHERE status='cancelled' "
            "AND created_at < datetime('now', ?)", (f"-{int(days)} days",))
        n = cursor.rowcount
        conn.commit()
        return n

    def update_order_status(self, order_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, order_id)
        )
        conn.commit()

    def transition_order_status(self, order_id, new_status, expected_status='pending',
                                cancel_by=None, cancel_reason=None):
        """Atomik holat o'tkazish: faqat hozirgi holat `expected_status` ga teng bo'lsagina
        o'zgartiradi va o'zgartirgan (yutgan) chaqiruv uchun True qaytaradi.

        Bot va Mini App AYNAN bir buyurtmani bir vaqtda tasdiqlashi/bekor qilishi yoki
        tugmani ikki marta bosish natijasida zahira ikki marta kamayishi va xaridorga
        takroriy xabar yuborilishining oldini oladi. Bitta `UPDATE ... WHERE status=?`
        — SQLite/PG darajasida atomik; faqat bitta chaqiruv rowcount=1 oladi. Chaqiruvchi
        zahirani kamaytirish/xabar yuborishni FAQAT True qaytganda bajarishi kerak.

        Bekor qilishda (new_status='cancelled') `cancel_by` ('buyer'|'seller'|'admin'|
        'system') va ixtiyoriy `cancel_reason` saqlanadi — xaridor/sotuvchi/admin
        ekranlarida "kim va nima uchun bekor qildi" ko'rsatish uchun. Mavjud qiymat
        COALESCE bilan saqlanadi (nizo oqimida allaqachon yozilgan sababni o'chirmaydi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if new_status == 'cancelled' and (cancel_by is not None or cancel_reason is not None):
            cursor.execute(
                "UPDATE orders SET status=?, "
                "cancel_by=COALESCE(?, cancel_by), "
                "cancel_reason=COALESCE(?, cancel_reason), "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status=?",
                (new_status, cancel_by, cancel_reason, order_id, expected_status)
            )
        else:
            cursor.execute(
                "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status=?",
                (new_status, order_id, expected_status)
            )
        conn.commit()
        return cursor.rowcount > 0

    def transition_group_status(self, group_id, new_status, expected_status='pending',
                                cancel_by=None, cancel_reason=None):
        """Guruh (variant/savat) buyurtmasidagi `expected_status` qatorlarni o'tkazadi.
        FAQAT shu chaqiruv HAQIQATAN o'zgartirgan (yutgan) qator id'larini qaytaradi —
        chaqiruvchi zahira/xabarni FAQAT shu id'lar uchun bajaradi (ikki marta kamaymasin).

        Har qator alohida atomik da'vo qilinadi (`UPDATE ... WHERE id=? AND status=?`):
        agar orada bir qatorni boshqa chaqiruv (masalan yakka buyurtma amali) allaqachon
        o'zgartirgan bo'lsa, u qatorda rowcount=0 → ro'yxatga QO'SHILMAYDI. Shunday qilib
        bir vaqtda guruh-bekor + yakka-amal bo'lsa ham hech bir qator ikki marta
        qayta-zahiralanmaydi/xabar olmaydi. cancel_by/cancel_reason COALESCE bilan saqlanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM orders WHERE order_group_id=? AND status=? ORDER BY id ASC",
            (str(group_id), expected_status))
        candidate_ids = [r[0] for r in cursor.fetchall()]
        if not candidate_ids:
            return []
        won = []
        for oid in candidate_ids:
            if new_status == 'cancelled' and (cancel_by is not None or cancel_reason is not None):
                cursor.execute(
                    "UPDATE orders SET status=?, "
                    "cancel_by=COALESCE(?, cancel_by), "
                    "cancel_reason=COALESCE(?, cancel_reason), "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND status=?",
                    (new_status, cancel_by, cancel_reason, oid, expected_status))
            else:
                cursor.execute(
                    "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND status=?",
                    (new_status, oid, expected_status))
            if cursor.rowcount > 0:
                won.append(oid)
        conn.commit()
        return won

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

    def request_group_cancel(self, group_id, by, reason):
        """Guruh (variant/savat) buyurtmasini bir tomon bekor qilishni so'raydi —
        barcha 'confirmed' va cancel_state bo'sh qatorlarga. rowcount>0 bo'lsa True."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE orders
               SET cancel_state='requested', cancel_by=?, cancel_reason=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE order_group_id=? AND status='confirmed' AND COALESCE(cancel_state,'')=''""",
            (by, reason, str(group_id)))
        conn.commit()
        return cursor.rowcount > 0

    def agree_group_cancel(self, group_id):
        """Guruh: ikkinchi tomon roziligi -> barcha 'requested' qatorlar bekor qilinadi.
        Bekor qilingan qator id'lar ro'yxatini qaytaradi (zahira qaytarish uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM orders WHERE order_group_id=? AND cancel_state='requested'",
            (str(group_id),))
        ids = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            """UPDATE orders
               SET status='cancelled', cancel_state=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE order_group_id=? AND cancel_state='requested'""",
            (str(group_id),))
        conn.commit()
        return ids if cursor.rowcount > 0 else []

    def dispute_group_cancel(self, group_id):
        """Guruh: ikkinchi tomon rozi emas -> barcha 'requested' qatorlar admin hakamligiga."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE orders
               SET cancel_state='disputed', updated_at=CURRENT_TIMESTAMP
               WHERE order_group_id=? AND cancel_state='requested'""",
            (str(group_id),))
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
            SELECT o.*, p.name as product_name, p.image_url as product_image,
                   p.price as product_price, p.sale_mode, p.pack_size,
                   bu.name as buyer_name, bu.telegram_id as buyer_tg,
                   bu.phone_number as buyer_phone, bu.telegram_username as buyer_username,
                   su.name as seller_name, su.shop_name, su.telegram_id as seller_tg,
                   su.phone_number as seller_phone, su.telegram_username as seller_username
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

    def get_reviews_by_buyer(self, buyer_id, limit=20):
        """Xaridor o'zi qoldirgan sharhlar (bot buyer_reviews pariteti)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.shop_name, u.name as seller_name,
                   COALESCE(po.name, pr.name) as product_name
            FROM reviews r
            JOIN users u ON r.seller_id=u.id
            LEFT JOIN orders o ON r.order_id=o.id
            LEFT JOIN products po ON o.product_id=po.id
            LEFT JOIN products pr ON r.product_id=pr.id
            WHERE r.buyer_id=?
            ORDER BY r.created_at DESC
            LIMIT ?
        """, (buyer_id, limit))
        return [dict(r) for r in cursor.fetchall()]

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

    def get_recent_reviews_with_comments(self, limit=200):
        """#6 — admin sentiment tahlili uchun: butun platforma bo'yicha izohli
        sharhlar (yangi -> eski). Faqat matnli izohi borlari."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.rating, r.product_rating, r.comment, r.created_at,
                   u.shop_name,
                   COALESCE(po.name, pr.name) as product_name
            FROM reviews r
            LEFT JOIN users u ON r.seller_id=u.id
            LEFT JOIN orders o ON r.order_id=o.id
            LEFT JOIN products po ON o.product_id=po.id
            LEFT JOIN products pr ON r.product_id=pr.id
            WHERE r.comment IS NOT NULL AND TRIM(r.comment) <> ''
            ORDER BY r.created_at DESC
            LIMIT ?
        """, (limit,))
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

    def get_moderation_queue(self):
        """#5 — avto-moderatsiya bloklagan mahsulotlar (admin tekshiruvi uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, u.name as seller_name, u.shop_name, u.telegram_id as seller_tg
            FROM products p LEFT JOIN users u ON p.seller_id=u.id
            WHERE COALESCE(p.status,'')='mod_blocked'
            ORDER BY p.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

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

    def get_product_demand_signals(self, product_id):
        """#11 Dinamik narx — bitta mahsulot bo'yicha talab/sotuv signallari.
        Qaytaradi: days_listed, sold, orders_total, pending_orders, favorites,
        stock_count, prod_rating, review_count, views (mavjud bo'lsa)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.price, p.stock_count, p.created_at,
                   CAST(julianday('now') - julianday(p.created_at) AS INTEGER) AS days_listed,
                   (SELECT COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.quantity ELSE 0 END),0)
                      FROM orders o WHERE o.product_id=p.id) AS sold,
                   (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id) AS orders_total,
                   (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id AND o.status='pending') AS pending_orders,
                   (SELECT COUNT(*) FROM favorites f WHERE f.product_id=p.id) AS favorites,
                   (SELECT AVG(product_rating) FROM reviews r WHERE r.product_id=p.id AND r.product_rating IS NOT NULL) AS prod_rating,
                   (SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id AND r.product_rating IS NOT NULL) AS review_count
            FROM products p WHERE p.id=?
        """, (product_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        return {
            "price": round(float(d.get("price") or 0)),
            "stock_count": d.get("stock_count"),
            "days_listed": max(0, int(d.get("days_listed") or 0)),
            "sold": int(d.get("sold") or 0),
            "orders_total": int(d.get("orders_total") or 0),
            "pending_orders": int(d.get("pending_orders") or 0),
            "favorites": int(d.get("favorites") or 0),
            "prod_rating": round(float(d["prod_rating"]), 1) if d.get("prod_rating") else None,
            "review_count": int(d.get("review_count") or 0),
        }

    def get_seller_time_analytics(self, seller_id):
        """#17 — "qachon sotilyapti": hafta kuni kesimida buyurtmalar + so'nggi 7 kun
        kunlik daromadi. Vaqt UTC (created_at) — MVP uchun yetarli."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Hafta kuni bo'yicha buyurtmalar soni (0=Yakshanba .. 6=Shanba)
        cursor.execute("""
            SELECT CAST(strftime('%w', created_at) AS INTEGER) as wd, COUNT(*) as n
            FROM orders WHERE seller_id=? GROUP BY wd
        """, (seller_id,))
        wd = {r[0]: r[1] for r in cursor.fetchall()}
        by_weekday = [wd.get(i, 0) for i in range(7)]
        # So'nggi 7 kun kunlik daromadi (delivered)
        cursor.execute("""
            SELECT date(created_at) as d,
                   COALESCE(SUM(CASE WHEN status='delivered' THEN total_price ELSE 0 END), 0) as rev
            FROM orders
            WHERE seller_id=? AND created_at >= datetime('now', '-7 days')
            GROUP BY d ORDER BY d
        """, (seller_id,))
        daily_7 = [{"date": r[0], "revenue": r[1]} for r in cursor.fetchall()]
        return {"by_weekday": by_weekday, "daily_7": daily_7}

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
                f"UPDATE orders SET status='cancelled', cancel_by='system', "
                f"cancel_reason=COALESCE(cancel_reason,'auto_timeout') "
                f"WHERE id IN ({','.join('?' for _ in ids)})",
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
                   u.delivery_min_total,
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

    def set_product_ad_caption(self, product_id, caption, parse_mode=None):
        """Kanalga e'lon qilingan AYNAN reklama matnini saqlaydi (App buyer sahifasi
        kanal pariteti uchun shuni ko'rsatadi). parse_mode: 'HTML' yoki None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE products SET ad_caption=?, ad_caption_pm=? WHERE id=?",
            (caption, parse_mode, product_id)
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

        # Rejalashtirilgan/avto-reklama yozuvlari products(id) ga FK bilan bog'langan,
        # lekin ON DELETE CASCADE yo'q — ularni avval tozalamasak, jismonan o'chirishda
        # FOREIGN KEY xatosi (HTTP 500) chiqadi. Mahsulot o'chsa, reja ham keraksiz.
        cursor.execute("DELETE FROM scheduled_posts WHERE product_id=?", (product_id,))
        cursor.execute("DELETE FROM auto_reposts WHERE product_id=?", (product_id,))

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

    def get_seller_product_audit(self, seller_id, limit=100):
        """Shu sotuvchining (do'konning) o'chirilgan mahsulotlari jurnali —
        App «O'chirilgan» tabi uchun (eng yangilari birinchi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, u.name as deleted_by_name
            FROM product_audit a
            LEFT JOIN users u ON a.deleted_by=u.id
            WHERE a.seller_id=?
            ORDER BY a.deleted_at DESC
            LIMIT ?
        """, (seller_id, limit))
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

    # ===== PLATFORMA SOZLAMALARI (kalit-qiymat) =====
    def get_setting(self, key, default=None):
        """platform_settings'dan bitta qiymatni o'qiydi (TEXT yoki default)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM platform_settings WHERE key=?", (key,))
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else default

    def get_all_settings(self):
        """Barcha sozlamalarni dict sifatida qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM platform_settings")
        return {r[0]: r[1] for r in cursor.fetchall()}

    def set_setting(self, key, value):
        """Bitta sozlamani yozadi (upsert). value None bo'lsa bo'sh satr saqlanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO platform_settings (key, value, updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, "" if value is None else str(value)))
        conn.commit()

    # ===== KVOTA HISOBLAGICHI (Pro bepul boost / reels #18) =====
    def get_feature_usage(self, user_id, feature, period):
        """Berilgan davr (YYYY-MM) ichida 'feature' necha marta ishlatilgan (0 agar yo'q)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT count FROM feature_usage WHERE user_id=? AND feature=? AND period=?",
            (user_id, feature, period))
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def incr_feature_usage(self, user_id, feature, period):
        """Hisoblagichni +1 qiladi (upsert) va yangi qiymatni qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO feature_usage (user_id, feature, period, count) VALUES (?,?,?,1) "
            "ON CONFLICT(user_id, feature, period) DO UPDATE SET count=count+1",
            (user_id, feature, period))
        conn.commit()
        return self.get_feature_usage(user_id, feature, period)

    def count_pending_scheduled_posts(self, seller_id):
        """Do'kon (ega) bo'yicha hozir kutilayotgan (pending) rejalashtirilgan postlar soni."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE seller_id=? AND status='pending'",
            (seller_id,))
        return int(cursor.fetchone()[0])

    # ===== XABARNOMALAR (universal inbox) =====
    def create_notification(self, user_id, kind, title, body, ref_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notifications (user_id, kind, title, body, ref_id) VALUES (?,?,?,?,?)",
            (user_id, kind, title, body, ref_id))
        conn.commit()
        return cursor.lastrowid

    def get_user_notifications(self, user_id, limit=30):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                       (user_id, limit))
        return [dict(r) for r in cursor.fetchall()]

    def count_unread_notifications(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user_id,))
        return int(cursor.fetchone()[0])

    def mark_notification_read(self, notif_id, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notif_id, user_id))
        conn.commit()
        return cursor.rowcount > 0

    def mark_all_notifications_read(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (user_id,))
        conn.commit()
        return cursor.rowcount

    # ===== MUROJAAT (support thread + messages) =====
    def create_support_thread(self, user_id, reason, text):
        """Yangi murojaat ochadi (thread + birinchi xabar). thread_id qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO support_threads (user_id, reason) VALUES (?,?)", (user_id, reason))
        tid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO support_messages (thread_id, sender_role, sender_id, text) VALUES (?,?,?,?)",
            (tid, "user", user_id, text))
        conn.commit()
        return tid

    def get_support_thread(self, thread_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM support_threads WHERE id=?", (thread_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def add_support_message(self, thread_id, sender_role, sender_id, text):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO support_messages (thread_id, sender_role, sender_id, text) VALUES (?,?,?,?)",
            (thread_id, sender_role, sender_id, text))
        cursor.execute("UPDATE support_threads SET updated_at=CURRENT_TIMESTAMP, status='open' WHERE id=?",
                       (thread_id,))
        conn.commit()
        return cursor.lastrowid

    def get_support_messages(self, thread_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM support_messages WHERE thread_id=? ORDER BY created_at ASC, id ASC",
                       (thread_id,))
        return [dict(r) for r in cursor.fetchall()]

    def list_support_threads(self, user_id=None, limit=50):
        """user_id berilsa — o'sha foydalanuvchi murojaatlari; aks holda HAMMASI (admin).
        Har thread' да oxirgi xabar va sana qaytadi (ro'yxat uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        base = """
            SELECT t.*, u.name as user_name, u.telegram_id as user_tg,
                   (SELECT text FROM support_messages m WHERE m.thread_id=t.id
                    ORDER BY m.created_at DESC, m.id DESC LIMIT 1) as last_text,
                   (SELECT created_at FROM support_messages m WHERE m.thread_id=t.id
                    ORDER BY m.created_at DESC, m.id DESC LIMIT 1) as last_at
            FROM support_threads t JOIN users u ON t.user_id=u.id
        """
        if user_id is not None:
            cursor.execute(base + " WHERE t.user_id=? ORDER BY t.updated_at DESC LIMIT ?", (user_id, limit))
        else:
            cursor.execute(base + " ORDER BY t.status='open' DESC, t.updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

    def set_support_status(self, thread_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE support_threads SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (status, thread_id))
        conn.commit()
        return cursor.rowcount > 0

    def count_open_support(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM support_threads WHERE status='open'")
        return int(cursor.fetchone()[0])

    # ===== TO'LOVLAR (monetizatsiya #18) =====
    def create_payment(self, user_id, purpose, amount, ref_id=None, provider=None):
        """Yangi 'pending' to'lov yozuvi yaratadi; id qaytaradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO payments (user_id, purpose, ref_id, amount, provider) "
            "VALUES (?,?,?,?,?)",
            (user_id, purpose, ref_id, float(amount), provider))
        conn.commit()
        return cursor.lastrowid

    def get_payment(self, payment_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE id=?", (payment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_payment_by_txn(self, provider, txn_id):
        """Provayder tranzaksiya ID bo'yicha (idempotentlik — webhook qayta kelsa)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE provider=? AND provider_txn_id=?",
                       (provider, str(txn_id)))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_payment_state(self, payment_id, state, provider=None, provider_txn_id=None, meta=None):
        """To'lov holatini yangilaydi. 'paid' bo'lsa paid_at qo'yiladi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sets = ["state=?", "updated_at=CURRENT_TIMESTAMP"]
        vals = [state]
        if provider is not None:
            sets.append("provider=?"); vals.append(provider)
        if provider_txn_id is not None:
            sets.append("provider_txn_id=?"); vals.append(str(provider_txn_id))
        if meta is not None:
            sets.append("provider_meta=?"); vals.append(meta)
        if state == "paid":
            sets.append("paid_at=CURRENT_TIMESTAMP")
        vals.append(payment_id)
        cursor.execute(f"UPDATE payments SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
        return cursor.rowcount > 0

    def mark_paid_atomic(self, payment_id, provider=None, provider_txn_id=None, meta=None):
        """Atomik: faqat hali 'paid' BO'LMAGAN to'lovni 'paid' qiladi. Bu chaqiruv YUTGAN
        (rowcount=1) bo'lsagina True qaytadi — chaqiruvchi fulfillment'ni FAQAT shunda
        bajaradi. `UPDATE ... WHERE state!='paid'` DB darajasida atomik: webhook qayta
        kelishi yoki bir nechta worker sharoitida ham Pro/boost IKKI marta berilmaydi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sets = ["state='paid'", "updated_at=CURRENT_TIMESTAMP", "paid_at=CURRENT_TIMESTAMP"]
        vals = []
        if provider is not None:
            sets.append("provider=?"); vals.append(provider)
        if provider_txn_id is not None:
            sets.append("provider_txn_id=?"); vals.append(str(provider_txn_id))
        if meta is not None:
            sets.append("provider_meta=?"); vals.append(meta)
        vals.append(payment_id)
        cursor.execute(
            f"UPDATE payments SET {', '.join(sets)} WHERE id=? AND state!='paid'", vals)
        conn.commit()
        return cursor.rowcount > 0

    def get_payments_by_user(self, user_id, limit=50):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                       (user_id, limit))
        return [dict(r) for r in cursor.fetchall()]

    def get_paid_payments_summary(self):
        """Admin moliyaviy hisobot uchun: maqsad kesimida jami to'langan summa/son."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT purpose, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total "
            "FROM payments WHERE state='paid' GROUP BY purpose")
        return [dict(r) for r in cursor.fetchall()]

    def get_payments_admin(self, state=None, limit=100):
        """Admin uchun barcha to'lovlar (sotuvchi ismi bilan), ixtiyoriy state filtri.
        Kutilayotgan to'lovlarni qo'lda tasdiqlash ekrani uchun."""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = ("SELECT p.*, u.name AS user_name, u.telegram_username, u.telegram_id, "
               "u.phone_number, u.shop_name FROM payments p LEFT JOIN users u ON p.user_id=u.id")
        params = []
        if state:
            sql += " WHERE p.state=?"
            params.append(state)
        sql += " ORDER BY p.created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    # ===== BOOST (#18 pullik ko'tarish) =====
    def set_product_boost(self, product_id, days):
        """Mahsulotni 'days' kunga boost qiladi (boosted_until = hozir + days)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE products SET boosted_until=datetime('now', ?) WHERE id=?",
            (f"+{int(days)} days", product_id))
        conn.commit()
        return cursor.rowcount > 0

    def clear_product_boost(self, product_id):
        """Boostni darhol bekor qiladi (boosted_until=NULL) — to'lov qaytarib olinganda."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET boosted_until=NULL WHERE id=?", (product_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ===== KOMISSIYA (#18) =====
    def set_order_commission(self, order_id, amount):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET commission_amount=? WHERE id=?",
                       (round(float(amount), 2), order_id))
        conn.commit()

    def get_commission_owed_by_seller(self, seller_id):
        """Sotuvchining platformaga TO'LANMAGAN (hali undirilmagan) komissiya qarzi.
        Admin 'to'landi' deb belgilagan buyurtmalar (commission_settled_at IS NOT NULL) chiqarib tashlanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(commission_amount),0) FROM orders "
            "WHERE seller_id=? AND status='delivered' AND commission_amount IS NOT NULL "
            "AND commission_settled_at IS NULL",
            (seller_id,))
        return float(cursor.fetchone()[0] or 0)

    def get_commission_paid_by_seller(self, seller_id):
        """Sotuvchidan allaqachon undirilgan (to'langan deb belgilangan) jami komissiya."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(commission_amount),0) FROM orders "
            "WHERE seller_id=? AND status='delivered' AND commission_amount IS NOT NULL "
            "AND commission_settled_at IS NOT NULL",
            (seller_id,))
        return float(cursor.fetchone()[0] or 0)

    def get_commission_orders_by_seller(self, seller_id, limit=100):
        """Sotuvchining komissiyali buyurtmalari ro'yxati (yangi → eski). Sotuvchining
        'alohida ekran'i shuni ko'rsatadi: qaysi buyurtmadan qancha, to'langan/qolgan."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.total_price, o.commission_amount, o.commission_settled_at,
                   o.created_at,
                   b.name AS buyer_name, p.name AS product_name
            FROM orders o
            LEFT JOIN users b ON o.buyer_id=b.id
            LEFT JOIN products p ON o.product_id=p.id
            WHERE o.seller_id=? AND o.status='delivered'
                  AND o.commission_amount IS NOT NULL AND o.commission_amount>0
            ORDER BY o.created_at DESC
            LIMIT ?
        """, (seller_id, limit))
        return [dict(r) for r in cursor.fetchall()]

    def get_commission_by_sellers(self):
        """Admin uchun sotuvchilar kesimida komissiya: kim qancha qarzdor (owed) va
        allaqachon to'lagan (paid). Faqat egasi (seller_id) bo'yicha jamlanadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.seller_id,
                   s.name AS seller_name, s.shop_name, s.telegram_username,
                   COALESCE(SUM(CASE WHEN o.commission_settled_at IS NULL
                                     THEN o.commission_amount ELSE 0 END),0) AS owed,
                   COALESCE(SUM(CASE WHEN o.commission_settled_at IS NOT NULL
                                     THEN o.commission_amount ELSE 0 END),0) AS paid,
                   SUM(CASE WHEN o.commission_settled_at IS NULL THEN 1 ELSE 0 END) AS owed_count,
                   COUNT(*) AS total_count
            FROM orders o
            LEFT JOIN users s ON o.seller_id=s.id
            WHERE o.status='delivered'
                  AND o.commission_amount IS NOT NULL AND o.commission_amount>0
            GROUP BY o.seller_id
            HAVING owed>0 OR paid>0
            ORDER BY owed DESC, paid DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

    def settle_seller_commission(self, seller_id):
        """Sotuvchining BARCHA ochiq komissiya qarzini 'to'landi' deb belgilaydi (admin pulni
        undirgach). Belgilangan buyurtma soni va summasini qaytaradi (atomik)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(commission_amount),0), COUNT(*) FROM orders "
            "WHERE seller_id=? AND status='delivered' AND commission_amount IS NOT NULL "
            "AND commission_settled_at IS NULL",
            (seller_id,))
        row = cursor.fetchone()
        amount, count = float(row[0] or 0), int(row[1] or 0)
        if count:
            cursor.execute(
                "UPDATE orders SET commission_settled_at=CURRENT_TIMESTAMP "
                "WHERE seller_id=? AND status='delivered' AND commission_amount IS NOT NULL "
                "AND commission_settled_at IS NULL",
                (seller_id,))
        conn.commit()
        return {"count": count, "amount": round(amount, 2)}

    # ===== PRO OBUNA (#18) =====
    def set_pro_until(self, user_id, days):
        """Pro-obunani 'days' kunga uzaytiradi (mavjud muddatdan davom ettiradi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET pro_until="
            "datetime(CASE WHEN pro_until IS NOT NULL AND pro_until>datetime('now') "
            "THEN pro_until ELSE datetime('now') END, ?) WHERE id=?",
            (f"+{int(days)} days", user_id))
        conn.commit()
        return cursor.rowcount > 0

    def clear_pro(self, user_id):
        """Pro obunani darhol bekor qiladi (pro_until=NULL) — to'lov qaytarib olinganda."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET pro_until=NULL WHERE id=?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0

    def is_pro(self, owner_id):
        """Do'kon egasining Pro-obunasi faolmi (pro_until > hozir, UTC). BOT+APP uchun
        YAGONA manba — pro_until SQLite'да UTC saqlanadi, datetime('now') ham UTC."""
        if not owner_id:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE id=? AND pro_until IS NOT NULL "
                       "AND pro_until>datetime('now') LIMIT 1", (owner_id,))
        return cursor.fetchone() is not None

    def pro_locked(self, owner_id):
        """Pro-imkoniyat qulflanganmi: obuna monetizatsiyasi YOQILGAN (master+subscription)
        va ega Pro EMAS. Obuna o'chiq bo'lsa hech narsa qulflanmaydi (bot+app bir xil qoida)."""
        s = self.get_all_settings()
        on = (s.get("mon_enabled") == "1") and (s.get("mon_subscription_enabled") == "1")
        return on and not self.is_pro(owner_id)

    def mon_limit(self, key):
        """Monetizatsiya son-limiti (mon_free_product_limit/mon_free_scheduled_limit) —
        faqat obuna monetizatsiyasi yoqilganda; aks holda 0 (limitsiz). App'dagi
        monetization_public bilan bir xil semantika."""
        s = self.get_all_settings()
        if not (s.get("mon_enabled") == "1" and s.get("mon_subscription_enabled") == "1"):
            return 0
        try:
            return int(float(s.get(key, "0")))
        except (TypeError, ValueError):
            return 0

    def count_active_products(self, seller_id):
        """Sotuvchining faol (ko'rinadigan) mahsulotlari soni — Pro limit tekshiruvi uchun."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE seller_id=? "
            "AND COALESCE(status,'active')='active'", (seller_id,))
        return int(cursor.fetchone()[0] or 0)

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

    # ===== MAHSULOT RASMLARI (bir mahsulotga 5 tagacha — har rasm = bir variant/hil) =====
    MAX_PRODUCT_IMAGES = 5

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

    def set_product_images(self, product_id, file_ids, labels=None):
        """Mahsulotning barcha rasmlarini almashtiradi (eng ko'pi MAX_PRODUCT_IMAGES ta).
        Birinchi rasm products.image_url ga ham yoziladi (NULL bo'lishi mumkin).
        labels — har rasm uchun ixtiyoriy nom (variant/hil); file_ids bilan bir tartibda,
        qisqa bo'lsa qolganlari NULL."""
        clean = [f for f in (file_ids or []) if f][: self.MAX_PRODUCT_IMAGES]
        labels = list(labels or [])
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_images WHERE product_id=?", (product_id,))
        for pos, fid in enumerate(clean):
            lbl = (str(labels[pos]).strip() or None) if pos < len(labels) and labels[pos] is not None else None
            cursor.execute(
                "INSERT INTO product_images (product_id, file_id, position, label) VALUES (?,?,?,?)",
                (product_id, fid, pos, lbl)
            )
        # Birinchi rasmni eski image_url ustuniga ham sinxronlaymiz
        primary = clean[0] if clean else None
        cursor.execute("UPDATE products SET image_url=? WHERE id=?", (primary, product_id))
        conn.commit()

    def get_product_image_variants(self, product_id):
        """Mahsulot rasmlari + nomlari (variant/hil): [{file_id, label, position}], tartib bo'yicha.
        product_images bo'sh bo'lsa eski yagona image_url'ga qaytadi (label=None)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_id, label, position FROM product_images "
            "WHERE product_id=? ORDER BY position ASC, id ASC",
            (product_id,)
        )
        out = [{"file_id": r[0], "label": r[1], "position": r[2]}
               for r in cursor.fetchall() if r[0]]
        if out:
            return out
        cursor.execute("SELECT image_url FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return [{"file_id": row[0], "label": None, "position": 0}]
        return []

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
                   u.shop_name, u.phone_number as seller_phone, u.telegram_id as seller_tg,
                   (SELECT 1 FROM reviews rv WHERE rv.order_id=o.id AND rv.buyer_id=o.buyer_id LIMIT 1) as has_review
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.seller_id=u.id
            WHERE o.buyer_id=?
            ORDER BY o.created_at DESC
        """, (buyer_id,))
        return [dict(r) for r in cursor.fetchall()]

    # ===== SEVIMLILAR (#16 wishlist) =====
    def add_favorite(self, buyer_id, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO favorites (buyer_id, product_id) VALUES (?,?)",
                       (buyer_id, product_id))
        conn.commit()
        return cursor.rowcount > 0

    def remove_favorite(self, buyer_id, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM favorites WHERE buyer_id=? AND product_id=?",
                       (buyer_id, product_id))
        conn.commit()
        return cursor.rowcount > 0

    def is_favorite(self, buyer_id, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM favorites WHERE buyer_id=? AND product_id=?",
                       (buyer_id, product_id))
        return cursor.fetchone() is not None

    def get_favorites(self, buyer_id):
        """Xaridor sevimlilari — faqat ko'rinadigan (faol) mahsulotlar, to'liq ma'lumot bilan."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name, c.emoji as category_emoji, u.shop_name,
                   (SELECT AVG(product_rating) FROM reviews WHERE product_id=p.id AND product_rating IS NOT NULL) as prod_avg_rating,
                   (SELECT COUNT(*) FROM reviews WHERE product_id=p.id AND product_rating IS NOT NULL) as prod_review_count,
                   f.created_at as faved_at
            FROM favorites f
            JOIN products p ON f.product_id=p.id
            LEFT JOIN categories c ON p.category_id=c.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE f.buyer_id=? AND COALESCE(p.status,'active')='active'
            ORDER BY f.created_at DESC
        """, (buyer_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_product_favoriters(self, product_id):
        """Mahsulotni sevimliga qo'shgan xaridorlar (tg_id + til) — narx-tushdi xabari uchun."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.telegram_id, u.language
            FROM favorites f JOIN users u ON f.buyer_id=u.id
            WHERE f.product_id=? AND u.telegram_id IS NOT NULL AND COALESCE(u.is_blocked,0)=0
        """, (product_id,))
        return [dict(r) for r in cursor.fetchall()]

    # ===== AI SAVDOLASHISH KELISHUVLARI (#8) =====
    def set_haggle_deal(self, buyer_id, product_id, price, ttl_minutes=60):
        """Kelishilgan narxni saqlaydi (mavjudini almashtiradi). ttl_minutes — amal muddati."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO haggle_deals (buyer_id, product_id, price, expires_at) "
            "VALUES (?,?,?, datetime('now', ?)) "
            "ON CONFLICT(buyer_id, product_id) DO UPDATE SET "
            "price=excluded.price, created_at=CURRENT_TIMESTAMP, expires_at=excluded.expires_at",
            (buyer_id, product_id, price, f"+{int(ttl_minutes)} minutes"))
        conn.commit()

    def get_active_haggle_price(self, buyer_id, product_id):
        """Amaldagi (muddati o'tmagan) kelishilgan narx yoki None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT price FROM haggle_deals WHERE buyer_id=? AND product_id=? "
            "AND expires_at > datetime('now')", (buyer_id, product_id))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_buyer_order_totals(self, buyer_id):
        """#16 — sodiqlik uchun: xaridorning yetkazilgan buyurtmalari soni va jami xarajati."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(CASE WHEN status='delivered' THEN 1 END) as delivered_orders,
                   COALESCE(SUM(CASE WHEN status='delivered' THEN total_price ELSE 0 END), 0) as spent
            FROM orders WHERE buyer_id=?
        """, (buyer_id,))
        row = cursor.fetchone()
        return dict(row) if row else {"delivered_orders": 0, "spent": 0}

    def update_courier_location(self, order_id, lat, lon):
        """#13 — yetkazib beruvchining joriy joylashuvini yangilaydi (UTC vaqt bilan)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET courier_lat=?, courier_lon=?, "
            "courier_updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (lat, lon, order_id))
        conn.commit()
        return cursor.rowcount > 0

    def get_seller_orders_list(self, seller_id):
        """Do'kon buyurtmalari ro'yxati. creator_id/creator_name — mahsulotni joylagan
        XODIM (multivendor: ega xodimlar bo'yicha buyurtmalarni ajratib ko'rishi uchun)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   p.image_url as product_image,
                   p.created_by as creator_id, cu.name as creator_name,
                   u.name as buyer_name, u.phone_number as buyer_phone, u.telegram_id as buyer_tg,
                   u.telegram_username as buyer_username,
                   su.shop_lat as shop_lat, su.shop_lon as shop_lon,
                   co.name as courier_name, co.phone_number as courier_phone
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users u ON o.buyer_id=u.id
            JOIN users su ON o.seller_id=su.id
            LEFT JOIN users cu ON p.created_by=cu.id
            LEFT JOIN users co ON o.courier_id=co.id
            WHERE o.seller_id=?
            ORDER BY o.created_at DESC
        """, (seller_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_shop_couriers(self, owner_user_id):
        """#3 — do'kon EGAsining FAOL kuryerlari (assign uchun). Egasi user_id'sidan
        shop_id topiladi. is_active=1 va staff_role='courier'."""
        shop = self.get_shop_by_owner(owner_user_id)
        if not shop:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT st.user_id, u.name, u.phone_number, u.telegram_id, u.telegram_username,
                   (SELECT COUNT(*) FROM orders o WHERE o.courier_id=st.user_id
                        AND o.seller_id=? AND o.status='confirmed' AND o.delivery_type='delivery') AS active_orders
            FROM shop_staff st JOIN users u ON st.user_id=u.id
            WHERE st.shop_id=? AND st.staff_role='courier' AND st.is_active=1
            ORDER BY u.name
        """, (owner_user_id, shop["id"]))
        return [dict(r) for r in cursor.fetchall()]

    def is_shop_courier(self, owner_user_id, courier_user_id):
        """courier_user_id shu do'konning (owner) FAOL kuryerimi?"""
        shop = self.get_shop_by_owner(owner_user_id)
        if not shop:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM shop_staff WHERE shop_id=? AND user_id=? "
                       "AND staff_role='courier' AND is_active=1",
                       (shop["id"], courier_user_id))
        return cursor.fetchone() is not None

    def assign_order_courier(self, order_id, courier_user_id, seller_id):
        """#3 — buyurtmaga kuryer biriktiradi (yoki None = bekor qiladi). seller_id
        EGAlik tekshiruvi: faqat o'z buyurtmasini o'zgartira oladi. Real kuryer
        biriktirilsa courier_notify=1 (bot kuryerga PUSH yuboradi). rowcount>0 = OK."""
        conn = self.get_connection()
        cursor = conn.cursor()
        notify = 1 if courier_user_id else 0
        cursor.execute("UPDATE orders SET courier_id=?, courier_notify=? WHERE id=? AND seller_id=?",
                       (courier_user_id, notify, order_id, seller_id))
        conn.commit()
        return cursor.rowcount > 0

    def get_orders_awaiting_courier_notify(self, limit=20):
        """#3 — bot fon job'i uchun: kuryerga "biriktirildi" PUSH ketmagan, hali
        yo'ldagi (confirmed) buyurtmalar id'lari."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM orders WHERE courier_notify=1 AND courier_id IS NOT NULL "
            "AND status='confirmed' ORDER BY id ASC LIMIT ?", (limit,))
        return [r[0] for r in cursor.fetchall()]

    def clear_courier_notify(self, order_id):
        """PUSH yuborilgach (yoki yuborib bo'lmasa ham — qayta spam qilmaslik uchun) belgini tozalaydi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET courier_notify=0 WHERE id=?", (order_id,))
        conn.commit()

    def get_seller_customers(self, seller_id, limit=100):
        """Sotuvchining mijozlari — buyurtma bergan xaridorlar (umumiy soni, sarflagan
        summasi va oxirgi buyurtma vaqti bilan jamlanadi)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.name, u.phone_number, u.telegram_username, u.telegram_id,
                   COUNT(o.id) AS orders_count,
                   COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.total_price ELSE 0 END), 0) AS spent,
                   MAX(o.created_at) AS last_order
            FROM orders o
            JOIN users u ON o.buyer_id = u.id
            WHERE o.seller_id = ?
            GROUP BY o.buyer_id
            ORDER BY last_order DESC
            LIMIT ?
        """, (seller_id, limit))
        return [dict(r) for r in cursor.fetchall()]

    def get_users_paginated(self, limit=15, offset=0, inactive_only=False):
        """Sahifalangan foydalanuvchilar ro'yxati.
        inactive_only=True — faqat NOFAOL (30+ kun faollik yo'q yoki hech qachon)
        foydalanuvchilar; eng nofaoli (NULL/eng eski faollik) birinchi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        where = ("WHERE last_active_at IS NULL "
                 "OR last_active_at < datetime('now','-30 days')") if inactive_only else ""
        cursor.execute(f"SELECT COUNT(*) FROM users {where}")
        total = cursor.fetchone()[0]
        order = "last_active_at ASC" if inactive_only else "created_at DESC"
        cursor.execute(f"SELECT * FROM users {where} ORDER BY {order} LIMIT ? OFFSET ?",
                       (limit, offset))
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

    def get_admin_products_full(self, q=None, limit=50, offset=0):
        """Admin «Mahsulotlar» bo'limi — TO'LIQ ma'lumot: rasm, sotuvchi/do'kon (telefon
        bilan), status, qoldiq, sotilgan soni, sana. q — nom/do'kon/sotuvchi qidiruvi.
        O'chirishdan oldin admin kimning qaysi mahsuloti ekanini aniq ko'rsin."""
        conn = self.get_connection()
        cursor = conn.cursor()
        where, params = "", []
        if q:
            like = f"%{q}%"
            where = "WHERE (p.name LIKE ? OR u.shop_name LIKE ? OR u.name LIKE ?)"
            params = [like, like, like]
        cursor.execute(f"""
            SELECT p.id, p.name, p.price, p.image_url, p.status, p.in_stock,
                   p.stock_count, p.sale_mode, p.created_at,
                   c.name as category_name,
                   u.name as seller_name, u.shop_name, u.phone_number as seller_phone,
                   (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id
                        AND o.status='delivered') as sold_count
            FROM products p
            LEFT JOIN users u ON p.seller_id=u.id
            LEFT JOIN categories c ON p.category_id=c.id
            {where}
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset])
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
        # DOIMO commit qilamiz: DELETE statement'i hech qator o'chmasa ham Python
        # sqlite3'da implicit tranzaksiyani ochadi. Avval `if rowcount > 0` shartida
        # commit qilingani uchun toza bazada (rowcount=0) ulanish OCHIQ tranzaksiya bilan
        # qolar, yozish-qulfini ushlab, shu faylga ulangan boshqa Database() ni
        # "database is locked" bilan to'sib qo'yardi (CI dagi collection xatosi). Audit #2.
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
                   u.telegram_username, u.phone_number, u.region_id, u.is_verified, u.pro_until,
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
                   u.telegram_username, u.phone_number, u.region_id, u.is_verified, u.pro_until,
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

        # Faol foydalanuvchilar (last_active_at bo'yicha — DAU/WAU/MAU) + bir martalik.
        # "inactive" = hech qachon faol bo'lmagan YOKI 30+ kun faollik yo'q
        # (bir kirib chiqib ketgan / tashlab ketgan foydalanuvchilar).
        # MUHIM: adminlar (o'zimiz/test nazorat) bu hisobdan CHIQARILADI — aks holda
        # sonlar sun'iy shishadi va "real foydalanuvchi faolligi" buziladi.
        cur.execute("""
            SELECT
                COUNT(CASE WHEN last_active_at >= datetime('now','-1 day')   THEN 1 END) as active_24h,
                COUNT(CASE WHEN last_active_at >= datetime('now','-7 days')  THEN 1 END) as active_7d,
                COUNT(CASE WHEN last_active_at >= datetime('now','-30 days') THEN 1 END) as active_30d,
                COUNT(CASE WHEN last_active_at IS NULL
                            OR last_active_at < datetime('now','-30 days')   THEN 1 END) as inactive,
                COUNT(*) as real_total
            FROM users WHERE COALESCE(role,'') != 'admin'
        """)
        act = cur.fetchone()

        # Spam/flood: nechta foydalanuvchi spam qilgan + jami bloklangan urinishlar
        # (adminlar bundan ham chiqariladi). 'spammers' = spam_count>0 bo'lganlar soni.
        cur.execute("""
            SELECT
                COUNT(CASE WHEN COALESCE(spam_count,0) > 0 THEN 1 END) as spammers,
                COALESCE(SUM(spam_count), 0) as spam_events
            FROM users WHERE COALESCE(role,'') != 'admin'
        """)
        spam = cur.fetchone()

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
            'active_24h': act[0] or 0,
            'active_7d': act[1] or 0,
            'active_30d': act[2] or 0,
            'inactive_users': act[3] or 0,
            'real_users': act[4] or 0,          # adminsiz jami (faol+nofaol bazasi)
            'spammers': spam[0] or 0,           # spam qilgan foydalanuvchilar soni
            'spam_events': spam[1] or 0,        # jami bloklangan spam/flood urinishlari
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

        # JAMI BERILGAN buyurtma (lifetime) — buyurtmaga shartnoma raqami (id)
        # berilgan bo'lsa, keyin o'chirilsa ham hisobda qolsin. id AUTOINCREMENT —
        # raqam qayta ishlatilmaydi; sqlite_sequence o'chirishga ham chidamli
        # (eng yangi buyurtma o'chsa MAX(id) tushadi, lekin seq tushmaydi).
        # PG/shim'da sqlite_sequence bo'lmasligi mumkin — MAX(id)'ga qaytamiz.
        total_issued = row[0] or 0
        try:
            cur.execute("SELECT seq FROM sqlite_sequence WHERE name='orders'")
            sr = cur.fetchone()
            if sr and sr[0]:
                total_issued = max(total_issued, sr[0])
        except Exception:
            pass
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM orders")
        total_issued = max(total_issued, cur.fetchone()[0] or 0)

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
            'total_issued': total_issued,
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
