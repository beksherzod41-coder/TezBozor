r"""Bekor-kelishuv / nizo holat-mashinasi (tasdiqlangan buyurtmani bekor qilish).

Tasdiqlangan buyurtma (status='confirmed') faqat ikki tomon kelishuvi yoki admin
hakamligi orqali bekor bo'ladi. Har o'tish FAQAT to'g'ri holatdan ishlaydi —
poyga/takror bosish noto'g'ri o'tkazmasligi kerak. Sof DB, Telegram'siz.

Holat oqimi:
  confirmed --request--> requested --agree----> cancelled
                                    \--dispute-> disputed --resolve(True)--> cancelled
                                                          \-resolve(False)-> confirmed
"""


def _confirmed_order(db, buyer, seller, product, price=45000):
    oid = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                          quantity=1, total_price=price,
                          payment_method="cash", delivery_type="pickup")
    assert db.transition_order_status(oid, "confirmed", "pending") is True
    return oid


# ===================== request_order_cancel =====================
def test_request_requires_confirmed(db, buyer, seller, product):
    oid = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                          quantity=1, total_price=1000,
                          payment_method="cash", delivery_type="pickup")  # 'pending'
    assert db.request_order_cancel(oid, "buyer", "fikrim o'zgardi") is False
    assert (db.get_order_by_id(oid).get("cancel_state") or "") == ""


def test_request_on_confirmed_sets_requested(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    assert db.request_order_cancel(oid, "buyer", "fikrim o'zgardi") is True
    o = db.get_order_by_id(oid)
    assert o["cancel_state"] == "requested"
    assert o["cancel_by"] == "buyer"
    assert o["cancel_reason"] == "fikrim o'zgardi"
    assert o["status"] == "confirmed"  # hali bekor emas


def test_request_twice_second_fails(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    assert db.request_order_cancel(oid, "buyer", "a") is True
    assert db.request_order_cancel(oid, "seller", "b") is False  # allaqachon so'ralgan
    assert db.get_order_by_id(oid)["cancel_by"] == "buyer"  # o'zgarmagan


# ===================== agree_order_cancel =====================
def test_agree_cancels_order(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    assert db.agree_order_cancel(oid) is True
    o = db.get_order_by_id(oid)
    assert o["status"] == "cancelled"
    assert o["cancel_state"] is None


def test_agree_without_request_fails(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    assert db.agree_order_cancel(oid) is False  # 'requested' emas
    assert db.get_order_by_id(oid)["status"] == "confirmed"


def test_agree_twice_second_fails(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    assert db.agree_order_cancel(oid) is True
    assert db.agree_order_cancel(oid) is False  # allaqachon bekor


# ===================== dispute_order_cancel =====================
def test_dispute_moves_to_disputed(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    assert db.dispute_order_cancel(oid) is True
    assert db.get_order_by_id(oid)["cancel_state"] == "disputed"


def test_dispute_without_request_fails(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    assert db.dispute_order_cancel(oid) is False


def test_agree_after_dispute_fails(db, buyer, seller, product):
    """Holat 'disputed'ga o'tgach, oddiy 'agree' ishlamaydi — faqat admin hal qiladi."""
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    db.dispute_order_cancel(oid)
    assert db.agree_order_cancel(oid) is False
    assert db.get_order_by_id(oid)["status"] == "confirmed"


# ===================== resolve_order_dispute (admin) =====================
def test_resolve_dispute_cancel(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    db.dispute_order_cancel(oid)
    assert db.resolve_order_dispute(oid, do_cancel=True) is True
    o = db.get_order_by_id(oid)
    assert o["status"] == "cancelled" and o["cancel_state"] is None


def test_resolve_dispute_keep_in_force(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    db.dispute_order_cancel(oid)
    assert db.resolve_order_dispute(oid, do_cancel=False) is True
    o = db.get_order_by_id(oid)
    assert o["status"] == "confirmed"
    assert o["cancel_state"] is None
    assert o["cancel_reason"] is None  # belgilar tozalandi


def test_resolve_requires_disputed(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")  # 'requested', 'disputed' emas
    assert db.resolve_order_dispute(oid, do_cancel=True) is False
    assert db.get_order_by_id(oid)["status"] == "confirmed"


def test_get_disputed_orders_lists_it(db, buyer, seller, product):
    oid = _confirmed_order(db, buyer, seller, product)
    db.request_order_cancel(oid, "buyer", "x")
    db.dispute_order_cancel(oid)
    disputed = db.get_disputed_orders()
    ids = [o["id"] for o in disputed]
    assert oid in ids
    row = next(o for o in disputed if o["id"] == oid)
    assert "product_name" in row and "buyer_name" in row
