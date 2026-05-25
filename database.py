import sqlite3
import datetime
from typing import Optional, List, Dict, Any

class Database:
    def __init__(self, db_path: str = "marketplace.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                emoji TEXT,
                description TEXT
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
        conn.close()
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
        conn.close()

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
        conn.close()
        return uid

    def get_user_by_telegram_id(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_referral_code(self, code):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE referral_code=?", (code,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_users(self, role=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if role:
            cursor.execute("SELECT * FROM users WHERE role=? ORDER BY created_at DESC", (role,))
        else:
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
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
        conn.close()

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
        conn.close()

    # ===== SELLER REQUESTS =====
    def create_seller_request(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO seller_requests (user_id, status) VALUES (?,?)",
            (user_id, 'pending')
        )
        conn.commit()
        conn.close()

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
        conn.close()
        return [dict(r) for r in rows]

    def update_seller_request(self, request_id, status, admin_note=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE seller_requests SET status=?, admin_note=? WHERE id=?",
            (status, admin_note, request_id)
        )
        conn.commit()
        conn.close()

    def get_seller_request_by_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM seller_requests WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    # ===== CATEGORIES =====
    def get_categories(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories")
        rows = cursor.fetchall()
        conn.close()
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
        conn.close()
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
        conn.close()
        return [dict(r) for r in rows]

    def get_all_products(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def search_products(self, query=None, category_id=None, min_price=None, max_price=None):
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
            WHERE p.in_stock=1 AND u.is_approved=1
        """
        params = []
        if query:
            sql += " AND (p.name LIKE ? OR p.description LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        if category_id:
            sql += " AND p.category_id=?"
            params.append(category_id)
        if min_price:
            sql += " AND p.price>=?"
            params.append(min_price)
        if max_price:
            sql += " AND p.price<=?"
            params.append(max_price)
        sql += " ORDER BY avg_rating DESC, p.created_at DESC"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ===== ORDERS =====
    def create_order(self, buyer_id, seller_id, product_id, quantity, total_price,
                     delivery_address=None, buyer_lat=None, buyer_lon=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (buyer_id, seller_id, product_id, quantity,
                                total_price, delivery_address, buyer_lat, buyer_lon)
            VALUES (?,?,?,?,?,?,?,?)
        """, (buyer_id, seller_id, product_id, quantity, total_price,
              delivery_address, buyer_lat, buyer_lon))
        oid = cursor.lastrowid
        conn.commit()
        conn.close()
        return oid

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
        conn.close()
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
        conn.close()
        return [dict(r) for r in rows]

    def get_all_orders(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_order_status(self, order_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, order_id)
        )
        conn.commit()
        conn.close()

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
        conn.close()
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
        conn.close()
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
        conn.close()
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
        conn.close()
        return [dict(r) for r in rows]

    def get_seller_avg_rating(self, seller_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(rating) FROM reviews WHERE seller_id=?", (seller_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else 0.0