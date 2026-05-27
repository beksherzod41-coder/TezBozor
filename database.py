import sqlite3
import threading
import datetime
import shutil
import os
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str = "marketplace.db"):
        self.db_path = db_path
        self._local = threading.local()   # har bir thread o'z ulanishiga ega
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Thread-safe SQLite ulanishi. Har bir thread bitta ulanishni qayta ishlatadi."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
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

        # Orders jadvali uchun migratsiya — yangi ustunlar
        for col, defn in [
            ("payment_method", "TEXT"),   # 'cash' | 'card' | 'click'
            ("delivery_type", "TEXT"),    # 'delivery' | 'pickup'
        ]:
            try:
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {defn}")
            except Exception:
                pass

        # Products jadvali — stock_count (zahira soni). NULL bo'lsa cheksiz hisoblanadi.
        for col, defn in [
            ("stock_count", "INTEGER"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE products ADD COLUMN {col} {defn}")
            except Exception:
                pass

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
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass
        conn.commit()

        # Products jadvaliga region_id ustuni (sotuvchi do'koni hududi)
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN region_id INTEGER")
            conn.commit()
        except Exception:
            pass

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (seller_id) REFERENCES users(id),
                FOREIGN KEY (buyer_id) REFERENCES users(id)
            )
        """)

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

        conn.commit()
        self.insert_default_categories()

    def insert_default_categories(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cats = [
            ("Ichimliklar", "Ichimliklar", "Turli ichimliklar"),
            ("Ehtiyot Qismlar", "Ehtiyot Qismlar", "Avtomobil ehtiyot qismlari"),
            ("Xojalik Mollari", "Xojalik Mollari", "Uy-rozgor buyumlari"),
            ("Elektronika", "Elektronika", "Elektronika va gadjetlar"),
            ("Kiyimlar", "Kiyimlar", "Kiyim-kechaklar"),
            ("Oziq-ovqat", "Oziq-ovqat", "Oziq-ovqat mahsulotlari"),
            ("Taomlar", "Taomlar", "Turli taomlar"),
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

    # ===== SELLER REQUESTS =====
    def create_seller_request(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO seller_requests (user_id, status) VALUES (?,?)",
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
    def create_product(self, seller_id, name, price, category_id=None, description=None, image_url=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO products (seller_id, name, price, category_id, description, image_url) VALUES (?,?,?,?,?,?)",
            (seller_id, name, price, category_id, description, image_url)
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

    def get_all_products(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def search_products(self, query=None, category_id=None, min_price=None, max_price=None,
                        sort_by='rating', region_id=None):
        """sort_by: 'rating' | 'price_asc' | 'price_desc' | 'newest'"""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT p.*, c.name as category_name, c.emoji as category_emoji,
                   u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number,
                   (SELECT AVG(r.rating) FROM reviews r WHERE r.seller_id=p.seller_id) as avg_rating
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE p.in_stock=1 AND COALESCE(u.is_blocked,0)=0
        """
        params = []
        if query:
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
                     payment_method=None, delivery_type=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (buyer_id, seller_id, product_id, quantity,
                                total_price, delivery_address, buyer_lat, buyer_lon,
                                payment_method, delivery_type)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (buyer_id, seller_id, product_id, quantity, total_price,
              delivery_address, buyer_lat, buyer_lon, payment_method, delivery_type))
        oid = cursor.lastrowid
        conn.commit()
        return oid

    def get_order_by_id(self, order_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, p.name as product_name, p.price as product_price,
                   bu.name as buyer_name, bu.phone_number as buyer_phone, bu.telegram_id as buyer_tg,
                   su.name as seller_name, su.shop_name, su.phone_number as seller_phone,
                   su.telegram_id as seller_tg
            FROM orders o
            JOIN products p ON o.product_id=p.id
            JOIN users bu ON o.buyer_id=bu.id
            JOIN users su ON o.seller_id=su.id
            WHERE o.id=?
        """, (order_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

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
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def update_order_status(self, order_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, order_id)
        )
        conn.commit()

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

    def save_product_attributes(self, product_id, attributes: dict):
        """Mahsulot atributlarini saqlaydi. attributes = {'size': 'XL', 'color': 'Qora'}"""
        if not attributes:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        for key, value in attributes.items():
            if value is not None and str(value).strip():
                cursor.execute("""
                    INSERT INTO product_attributes (product_id, attr_key, attr_value)
                    VALUES (?,?,?)
                    ON CONFLICT(product_id, attr_key) DO UPDATE SET attr_value=excluded.attr_value
                """, (product_id, key, str(value).strip()))
        conn.commit()

    def get_product_attributes(self, product_id):
        """Mahsulotning barcha atributlari."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.attr_key, a.attr_value, t.attr_label
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

    # ===== REVIEWS =====
    def create_review(self, order_id, seller_id, buyer_id, rating, comment=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (order_id, seller_id, buyer_id, rating, comment) VALUES (?,?,?,?,?)",
            (order_id, seller_id, buyer_id, rating, comment)
        )
        rid = cursor.lastrowid
        conn.commit()
        return rid

    def get_seller_reviews(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.name as buyer_name
            FROM reviews r JOIN users u ON r.buyer_id=u.id
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

    def get_seller_stats(self, seller_id):
        """Sotuvchi statistikasi: jami, bu hafta, bu oy + sotilgan pul."""
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
                   u.is_blocked as seller_blocked,
                   (SELECT AVG(rating) FROM reviews WHERE seller_id=p.seller_id) as avg_rating
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
        """stock_count ni belgilaydi. None bo'lsa cheksiz."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if stock_count is None:
            cursor.execute("UPDATE products SET stock_count=NULL, in_stock=1 WHERE id=?", (product_id,))
        else:
            cursor.execute(
                "UPDATE products SET stock_count=?, in_stock=? WHERE id=?",
                (stock_count, 1 if stock_count > 0 else 0, product_id)
            )
        conn.commit()

    def decrement_stock_on_confirm(self, product_id, quantity):
        """Buyurtma tasdiqlanganda stock_count'ni kamaytiradi. in_stock=0 bo'lsa avtomatik yopadi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT stock_count FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            new_stock = max(0, row[0] - quantity)
            cursor.execute(
                "UPDATE products SET stock_count=?, in_stock=? WHERE id=?",
                (new_stock, 1 if new_stock > 0 else 0, product_id)
            )
            conn.commit()
            return new_stock
        return None

    def delete_product(self, product_id):
        """Mahsulotni o'chiradi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()

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

    def get_user_by_id(self, user_id):
        """DB primary key bo'yicha foydalanuvchi."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

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
        """Reyting uchun buyurtma (seller_id va buyer_id)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT seller_id, buyer_id FROM orders WHERE id=?", (order_id,))
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

    def get_all_categories(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories ORDER BY id")
        return cursor.fetchall()

    def get_product_by_id(self, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name, c.emoji as category_emoji,
                   u.shop_name, u.shop_address, u.shop_landmark,
                   u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
                   u.telegram_username, u.phone_number, u.telegram_id as seller_tg,
                   u.is_blocked as seller_blocked,
                   (SELECT AVG(rating) FROM reviews WHERE seller_id=p.seller_id) as avg_rating
            FROM products p
            LEFT JOIN categories c ON p.category_id=c.id
            LEFT JOIN users u ON p.seller_id=u.id
            WHERE p.id=?
        """, (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_product_basic(self, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

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

    def set_product_stock_count(self, product_id, stock_count):
        conn = self.get_connection()
        cursor = conn.cursor()
        if stock_count is None:
            cursor.execute("UPDATE products SET stock_count=NULL, in_stock=1 WHERE id=?", (product_id,))
        else:
            cursor.execute(
                "UPDATE products SET stock_count=?, in_stock=? WHERE id=?",
                (stock_count, 1 if stock_count > 0 else 0, product_id)
            )
        conn.commit()

    def decrement_stock_on_confirm(self, product_id, quantity):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT stock_count FROM products WHERE id=?", (product_id,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            new_stock = max(0, row[0] - quantity)
            cursor.execute(
                "UPDATE products SET stock_count=?, in_stock=? WHERE id=?",
                (new_stock, 1 if new_stock > 0 else 0, product_id)
            )
            conn.commit()
            return new_stock
        return None

    def delete_product(self, product_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()

    def update_product_fields(self, product_id, **fields):
        if not fields:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k}=?" for k in fields.keys()])
        values = list(fields.values()) + [product_id]
        cursor.execute(f"UPDATE products SET {set_clause} WHERE id=?", values)
        conn.commit()

    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_users_paginated(self, limit=15, offset=0):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(r) for r in cursor.fetchall()]
        return total, rows

    def get_user_is_blocked(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_blocked FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return bool(row[0]) if row else None

    def get_user_is_verified(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_verified FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        return bool(row[0]) if row else None

    def get_seller_messages_summary(self, seller_id, limit=20):
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

    def get_admin_products_summary(self, limit=10):
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

    # ===== HUDUDIY FILTR =====

    def init_regions(self):
        """O'zbekiston viloyatlari va tumanlarini bazaga kiritadi (bir marta)."""
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
        cursor.execute("SELECT COUNT(*) FROM regions")
        if cursor.fetchone()[0] > 0:
            return  # allaqachon to'ldirilgan — conn.close() KERAK EMAS

        regions = [
            # (name, parent_id=None => viloyat)
            ("Toshkent shahri", None, "city"),
            ("Toshkent viloyati", None, "region"),
            ("Samarqand viloyati", None, "region"),
            ("Farg'ona viloyati", None, "region"),
            ("Andijon viloyati", None, "region"),
            ("Namangan viloyati", None, "region"),
            ("Buxoro viloyati", None, "region"),
            ("Qashqadaryo viloyati", None, "region"),
            ("Surxondaryo viloyati", None, "region"),
            ("Sirdaryo viloyati", None, "region"),
            ("Jizzax viloyati", None, "region"),
            ("Navoiy viloyati", None, "region"),
            ("Xorazm viloyati", None, "region"),
            ("Qoraqalpog'iston", None, "region"),
        ]

        # Viloyatlarni qo'shamiz
        for name, _, rtype in regions:
            cursor.execute(
                "INSERT OR IGNORE INTO regions (name, parent_id, type) VALUES (?,?,?)",
                (name, None, rtype)
            )

        # Toshkent shahri tumanlari
        cursor.execute("SELECT id FROM regions WHERE name='Toshkent shahri'")
        tsh_id = cursor.fetchone()[0]
        tashkent_districts = [
            "Bektemir", "Chilonzor", "Hamza", "Mirobod", "Mirzo Ulug'bek",
            "Olmazor", "Sergeli", "Shayxontohur", "Uchtepa", "Yakkasaroy", "Yunusobod"
        ]
        for d in tashkent_districts:
            cursor.execute(
                "INSERT OR IGNORE INTO regions (name, parent_id, type) VALUES (?,?,'district')",
                (d, tsh_id)
            )

        # Toshkent viloyati tumanlari
        cursor.execute("SELECT id FROM regions WHERE name='Toshkent viloyati'")
        tv_id = cursor.fetchone()[0]
        for d in ["Angren", "Bekobod", "Bo'stonliq", "Bo'ka", "Chirchiq", "Ohangaron",
                  "Oqqo'rg'on", "Parkent", "Piskent", "Qibray", "Toshloq",
                  "Urtachi", "Yangiyo'l", "Yuqorichirchiq", "Zangiota"]:
            cursor.execute(
                "INSERT OR IGNORE INTO regions (name, parent_id, type) VALUES (?,?,'district')",
                (d, tv_id)
            )

        # Samarqand
        cursor.execute("SELECT id FROM regions WHERE name='Samarqand viloyati'")
        smq_id = cursor.fetchone()[0]
        for d in ["Samarqand shahri", "Bulung'ur", "Ishtixon", "Jomboy", "Kattaqo'rg'on",
                  "Narpay", "Nurobod", "Oqdaryo", "Pastdarg'om", "Paxtachi",
                  "Payariq", "Qo'shrabot", "Tayloq", "Urgut"]:
            cursor.execute(
                "INSERT OR IGNORE INTO regions (name, parent_id, type) VALUES (?,?,'district')",
                (d, smq_id)
            )

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
