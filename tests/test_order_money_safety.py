"""Pul yo'lining YURAGI: atomik holat-guard + zahira matematikasi.

Bu testlar Telegram'siz, sof DB darajasida ishlaydi — eng qimmat kafolatlarni
qotiradi: buyurtmani ikki marta tasdiqlash (bot+Mini App bir vaqtda yoki tugmani
ikki marta bosish) zahirani IKKI marta kamaytirmasligi va oversell (zahiradan
ortiq sotish) bo'lmasligi. Aynan shu mantiq main.py:5206 (won_orders guard) va
database.py:transition_order_status/decrement_stock_on_confirm da yashaydi.
"""


def _order(db, buyer, seller, product, qty=1, price=45000):
    return db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                           quantity=qty, total_price=price,
                           payment_method="cash", delivery_type="pickup")


# ============================ Yangi buyurtma holati ============================
def test_new_order_is_pending(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    assert db.get_order_by_id(oid)["status"] == "pending"


# ===================== ATOMIK GUARD: transition_order_status =====================
def test_transition_only_first_caller_wins(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    # Birinchi chaqiruv yutadi, ikkinchisi (takroriy bosish) yutmaydi
    assert db.transition_order_status(oid, "confirmed", "pending") is True
    assert db.transition_order_status(oid, "confirmed", "pending") is False
    assert db.get_order_by_id(oid)["status"] == "confirmed"


def test_transition_wrong_expected_is_noop(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.transition_order_status(oid, "confirmed", "pending")  # endi 'confirmed'
    # 'pending' kutib bekor qilishga urinish — o'tmaydi, holat o'zgarmaydi
    assert db.transition_order_status(oid, "cancelled", "pending") is False
    assert db.get_order_by_id(oid)["status"] == "confirmed"


# ===================== ZAHIRA: decrement_stock_on_confirm =====================
def test_decrement_reduces_stock(db, seller):
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=10)
    assert db.decrement_stock_on_confirm(pid, 3) == 7
    p = db.get_product_by_id(pid)
    assert p["stock_count"] == 7 and p["in_stock"] == 1 and p["status"] == "active"


def test_decrement_to_zero_moves_to_reserve(db, seller):
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=10)
    assert db.decrement_stock_on_confirm(pid, 10) == 0
    p = db.get_product_by_id(pid)
    assert p["stock_count"] == 0 and p["in_stock"] == 0 and p["status"] == "reserve"


def test_decrement_never_oversells(db, seller):
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=2)
    # 2 ta bor, 5 so'ralsa — manfiyga tushmaydi (MAX(0, ...))
    assert db.decrement_stock_on_confirm(pid, 5) == 0
    assert db.get_product_by_id(pid)["stock_count"] == 0


def test_decrement_unlimited_stock_is_noop(db, seller):
    pid = db.create_product(seller_id=seller, name="Cheksiz", price=1000)  # stock_count=None
    assert db.get_product_by_id(pid)["stock_count"] is None
    assert db.decrement_stock_on_confirm(pid, 99) is None
    assert db.get_product_by_id(pid)["stock_count"] is None


# ============== HEADLINE: ikki marta tasdiq = BIR marta kamayish ==============
def test_double_confirm_decrements_stock_once(db, buyer, seller):
    """main.py:5206 guard mantig'i: takroriy tasdiq zahirani ikki marta kamaytirmaydi."""
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=10)
    oid = _order(db, buyer, seller, pid, qty=3)

    # 1-tasdiq (yutadi) → zahira kamayadi
    if db.transition_order_status(oid, "confirmed", "pending"):
        db.decrement_stock_on_confirm(pid, 3)

    # 2-tasdiq (takroriy bosish / bot+app poyga) → guard bloklaydi, kamaymaydi
    won = db.transition_order_status(oid, "confirmed", "pending")
    if won:
        db.decrement_stock_on_confirm(pid, 3)

    assert won is False
    assert db.get_product_by_id(pid)["stock_count"] == 7  # 10 - 3, FAQAT bir marta


# ============== Bekor qilinganda zahira qaytadi ==============
def test_restock_on_cancel_restores(db, seller):
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=10)
    db.decrement_stock_on_confirm(pid, 4)            # 6 qoldi
    assert db.restock_on_cancel(pid, 4) == 10        # qaytdi
    assert db.get_product_by_id(pid)["stock_count"] == 10


def test_restock_revives_reserved_product(db, seller):
    pid = db.create_product(seller_id=seller, name="P", price=1000, stock_count=2)
    db.decrement_stock_on_confirm(pid, 2)            # 0 → 'reserve'
    assert db.get_product_by_id(pid)["status"] == "reserve"
    db.restock_on_cancel(pid, 2)                     # qaytgach yana sotuvga
    p = db.get_product_by_id(pid)
    assert p["stock_count"] == 2 and p["in_stock"] == 1 and p["status"] == "active"
