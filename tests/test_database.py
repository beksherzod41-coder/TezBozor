"""Bazaning kritik (pul/buyurtma) mantig'i uchun testlar."""
from conftest import make_order


# ===== Foydalanuvchi / mahsulot / buyurtma asoslari =====

def test_create_and_fetch_user(db):
    uid = db.create_user(telegram_id=555, name="Ali", role="buyer")
    u = db.get_user_by_telegram_id(555)
    assert u is not None
    assert u["id"] == uid
    assert u["name"] == "Ali"


def test_user_activity_tracking(db):
    """Faollik kuzatuvi: yangi user faol; eski (bir martalik) nofaol sanaladi; touch qaytadan faol qiladi."""
    db.create_user(telegram_id=777, name="Faol", role="buyer")
    s = db.get_admin_stats_summary()
    assert s["active_24h"] >= 1           # yangi yaratilgan — faol
    # Bir martalik (40 kun oldin kelib ketgan) userni simulyatsiya qilamiz
    old_uid = db.create_user(telegram_id=778, name="Eski", role="buyer")
    conn = db.get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET last_active_at = datetime('now','-40 days') WHERE id=?", (old_uid,))
    conn.commit()
    assert db.get_admin_stats_summary()["inactive_users"] >= 1
    # touch — uni qaytadan "faol" qiladi (throttle eski bo'lgani uchun yoziladi)
    db.touch_user_activity(user_id=old_uid)
    assert db.get_user_by_telegram_id(778)["last_active_at"] is not None
    assert db.get_admin_stats_summary()["active_24h"] >= 2
    # telegram_id bo'yicha touch ham ishlaydi
    db.touch_user_activity(telegram_id=777)


def test_users_paginated_inactive_filter(db):
    """Nofaol filtri: 30+ kun faollik yo'q user qaytadi, faol user chiqmaydi."""
    faol = db.create_user(telegram_id=901, name="Faol", role="buyer")     # last_active = hozir
    nofaol = db.create_user(telegram_id=902, name="Nofaol", role="buyer")
    conn = db.get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET last_active_at = datetime('now','-40 days') WHERE id=?", (nofaol,))
    conn.commit()
    total, rows = db.get_users_paginated(inactive_only=True)
    ids = [r["id"] for r in rows]
    assert nofaol in ids
    assert faol not in ids


def test_increment_spam_count(db):
    """Spam hisoblagichi: DB id bo'yicha ham, telegram_id bo'yicha ham ortadi;
    admin statistikasida 'spammers' va 'spam_events' to'g'ri chiqadi."""
    uid = db.create_user(telegram_id=555, name="Spammer", role="buyer")
    db.increment_spam_count(uid)               # DB id bo'yicha
    db.increment_spam_count(telegram_id := 555)  # telegram_id bo'yicha (id mos kelmasa fallback)
    u = db.get_user_by_id(uid)
    assert u["spam_count"] == 2
    s = db.get_admin_stats_summary()
    assert s["spammers"] >= 1
    assert s["spam_events"] >= 2
    # mos kelmaydigan qiymat — jim e'tibor bermaydi (xato bermaydi)
    db.increment_spam_count(99999999)


def test_admin_stats_excludes_admins(db):
    """Adminlar faol/nofaol/spam hisobidan CHIQARILADI (sonlar shishmasligi uchun)."""
    db.create_user(telegram_id=10, name="Admin", role="admin")
    db.create_user(telegram_id=11, name="Xaridor", role="buyer")
    s = db.get_admin_stats_summary()
    assert s["real_users"] == 1            # faqat buyer sanaladi, admin emas
    assert s["active_24h"] == 1            # yangi buyer faol; admin hisobga olinmaydi


def test_delete_user_completely(db, buyer, seller, product):
    """To'liq o'chirish: foydalanuvchi VA uning butun ma'lumoti (mahsulot, buyurtma,
    sevimli, sharh...) yo'qoladi; boshqa foydalanuvchilar va FK butunligi buzilmaydi."""
    oid = make_order(db, buyer, seller, product)
    db.add_favorite(buyer, product) if hasattr(db, "add_favorite") else None
    # Sotuvchini o'chiramiz — uning mahsuloti va shu mahsulotga bog'liq buyurtma ham ketadi
    res = db.delete_user_completely(seller)
    assert res["ok"] is True
    assert db.get_user_by_id(seller) is None
    assert db.get_product_by_id(product) is None
    assert db.get_order_by_id(oid) is None
    # Xaridor (boshqa user) joyida qoladi
    assert db.get_user_by_id(buyer) is not None
    # Orphan qatorlar qolmaganini tekshiramiz (FK butunligi)
    conn = db.get_connection(); cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_check")
    assert cur.fetchall() == []


def test_create_order_defaults(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    order = db.get_order_by_id(oid)
    assert order["status"] == "pending"
    assert order["quantity"] == 1
    assert float(order["total_price"]) == 45000
    # Yangi buyurtmada xaridor hali «oldim» bosmagan
    assert not order.get("buyer_received")


def test_update_order_status(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.update_order_status(oid, "confirmed")
    assert db.get_order_by_id(oid)["status"] == "confirmed"


# ===== Xaridor «oldim» bosishi (buyer_received) =====

def test_set_buyer_received_requires_confirmed(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    # pending holatda — buyer_received qo'yilmaydi
    assert db.set_buyer_received(oid) is False
    assert not db.get_order_by_id(oid).get("buyer_received")

    # confirmed bo'lgach — qo'yiladi, lekin status delivered BO'LMAYDI
    db.update_order_status(oid, "confirmed")
    assert db.set_buyer_received(oid) is True
    order = db.get_order_by_id(oid)
    assert order["buyer_received"] == 1
    assert order["status"] == "confirmed"   # MUHIM: avtomatik yopilmaydi


def test_set_group_buyer_received(db, buyer, seller, product):
    o1 = make_order(db, buyer, seller, product)
    o2 = make_order(db, buyer, seller, product)
    db.set_orders_group([o1, o2], "777")
    db.update_order_status(o1, "confirmed")
    db.update_order_status(o2, "confirmed")
    db.set_group_buyer_received("777")
    for oid in (o1, o2):
        order = db.get_order_by_id(oid)
        assert order["buyer_received"] == 1
        assert order["status"] == "confirmed"


# ===== To'lov holati (settlement) =====

def test_settlement_paid_closes_debt(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.set_order_settlement(oid, "paid", amount_paid=45000, amount_due=0)
    order = db.get_order_by_id(oid)
    assert order["settlement_type"] == "paid"
    assert float(order["amount_due"]) == 0
    assert order["settled_at"] is not None


def test_settlement_debt_keeps_due_open(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", amount_paid=20000, amount_due=25000)
    order = db.get_order_by_id(oid)
    assert order["settlement_type"] == "debt"
    assert float(order["amount_due"]) == 25000
    assert order["settled_at"] is None


def test_record_debt_payment_partial_then_full(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", amount_paid=0, amount_due=45000)

    remaining = db.record_debt_payment(oid, 15000)
    assert float(remaining) == 30000
    assert db.get_order_by_id(oid)["settled_at"] is None

    remaining = db.record_debt_payment(oid, 30000)
    assert float(remaining) == 0
    assert db.get_order_by_id(oid)["settled_at"] is not None


def test_group_settlement_aggregates_due(db, buyer, seller, product):
    o1 = make_order(db, buyer, seller, product, price=45000)
    o2 = make_order(db, buyer, seller, product, price=30000)
    db.set_orders_group([o1, o2], "900")
    db.set_group_settlement("900", "debt", amount_paid=10000, amount_due=65000)
    # Guruh bo'yicha jami qarz vakil qatordan o'qiladi
    total_due = sum(float(db.get_order_by_id(o)["amount_due"] or 0) for o in (o1, o2))
    assert total_due == 65000


# ===== Qarz daftari ko'rinishlari =====

def test_seller_debt_views(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", amount_paid=5000, amount_due=40000)

    assert float(db.get_seller_debt_total(seller)) == 40000

    debts = db.get_seller_open_debts(seller)
    assert len(debts) == 1
    assert debts[0]["buyer_id"] == buyer
    assert float(debts[0]["total_due"]) == 40000

    orders = db.get_seller_debt_orders(seller, buyer)
    assert len(orders) == 1
    assert float(orders[0]["amount_due"]) == 40000
    assert orders[0]["product_name"] == "Telefon korpusi"


def test_paid_orders_not_in_debts(db, buyer, seller, product):
    oid = make_order(db, buyer, seller, product)
    db.set_order_settlement(oid, "paid", amount_paid=45000, amount_due=0)
    assert db.get_seller_open_debts(seller) == []
    assert float(db.get_seller_debt_total(seller)) == 0


# ===== Zahira (stock) =====

def test_decrement_stock_and_reserve(db, seller):
    pid = db.create_product(seller_id=seller, name="Mahsulot", price=1000, stock_count=2)
    left = db.decrement_stock_on_confirm(pid, 1)
    assert left == 1
    left = db.decrement_stock_on_confirm(pid, 1)
    assert left == 0
    # Zahira tugaganda mahsulot 'reserve' (zahira) statusiga o'tishi kerak
    prod = db.get_product_basic(pid)
    assert prod["status"] == "reserve"


# ===== Backup =====

def test_backup_creates_file(db, tmp_path):
    dst = tmp_path / "backup.db"
    assert db.backup(str(dst)) is True
    assert dst.exists()
    assert dst.stat().st_size > 0
