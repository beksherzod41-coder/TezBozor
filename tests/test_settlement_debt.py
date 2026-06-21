"""Settlement / qarz daftari — real pul (kim kimga qancha qarzdor).

Sof DB darajasida, Telegram'siz. Qotiriladigan kafolatlar: to'liq/qarz/bo'lib
belgilash, qisman to'lov qarzni to'g'ri kamaytirishi, qarzning xaridor+sotuvchi
bo'yicha jamlanishi, va GURUH (savat) qarzi IKKI marta sanalmasligi (vakil-qator
naqshi). Bog'liq dizayn: settlement-debt-ledger xotirasi.
"""


def _order(db, buyer, seller, product, price=45000, qty=1):
    return db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                           quantity=qty, total_price=price,
                           payment_method="cash", delivery_type="pickup")


# ===================== Yakka buyurtma settlement =====================
def test_paid_settlement_marks_settled(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.set_order_settlement(oid, "paid", 45000, 0)
    o = db.get_order_by_id(oid)
    assert o["settlement_type"] == "paid"
    assert o["amount_due"] == 0
    assert o["settled_at"] is not None


def test_debt_settlement_stays_open(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", 0, 45000)
    o = db.get_order_by_id(oid)
    assert o["amount_due"] == 45000
    assert o["settled_at"] is None  # ochiq qarz — yakunlanmagan


# ===================== Qisman / to'liq to'lov =====================
def test_partial_then_full_payment(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", 0, 45000)

    rem = db.record_debt_payment(oid, 20000)
    assert rem == 25000
    o = db.get_order_by_id(oid)
    assert o["amount_paid"] == 20000 and o["settled_at"] is None

    rem2 = db.record_debt_payment(oid, 25000)
    assert rem2 == 0
    o2 = db.get_order_by_id(oid)
    assert o2["amount_paid"] == 45000 and o2["settled_at"] is not None


def test_overpayment_clamps_to_zero(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product, price=10000)
    db.set_order_settlement(oid, "debt", 0, 10000)
    assert db.record_debt_payment(oid, 999999) == 0  # manfiyga tushmaydi
    assert db.get_order_by_id(oid)["settled_at"] is not None


def test_record_payment_on_missing_order_is_none(db):
    assert db.record_debt_payment(999999, 100) is None


# ===================== Jami qarz / jamlash =====================
def test_seller_debt_total_counts_open_only(db, buyer, seller, product):
    o1 = _order(db, buyer, seller, product)
    o2 = _order(db, buyer, seller, product)
    db.set_order_settlement(o1, "debt", 0, 30000)   # ochiq
    db.set_order_settlement(o2, "paid", 45000, 0)   # yopiq — sanalmaydi
    assert db.get_seller_debt_total(seller) == 30000


def test_seller_open_debts_aggregated_by_buyer(db, buyer, seller, product):
    o1 = _order(db, buyer, seller, product)
    o2 = _order(db, buyer, seller, product)
    db.set_order_settlement(o1, "debt", 0, 10000)
    db.set_order_settlement(o2, "installment", 5000, 20000)
    debts = db.get_seller_open_debts(seller)
    assert len(debts) == 1
    assert debts[0]["buyer_id"] == buyer
    assert debts[0]["total_due"] == 30000
    assert debts[0]["cnt"] == 2


def test_buyer_open_debts_aggregated_by_seller(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", 0, 15000)
    debts = db.get_buyer_open_debts(buyer)
    assert len(debts) == 1
    assert debts[0]["seller_id"] == seller
    assert debts[0]["total_due"] == 15000


def test_seller_debt_orders_drilldown(db, buyer, seller, product):
    oid = _order(db, buyer, seller, product)
    db.set_order_settlement(oid, "debt", 0, 12000)
    rows = db.get_seller_debt_orders(seller, buyer)
    assert len(rows) == 1
    assert rows[0]["id"] == oid
    assert rows[0]["amount_due"] == 12000
    assert "product_name" in rows[0]


# ===================== GURUH (savat) qarzi — ikki marta sanalmaydi =====================
def test_group_settlement_no_double_count(db, buyer, seller, product):
    o1 = _order(db, buyer, seller, product, price=30000)
    o2 = _order(db, buyer, seller, product, price=20000)
    group_id = str(min(o1, o2))
    db.set_orders_group([o1, o2], group_id)

    # Butun guruh 50000 qarz — vakil-qatorga yoziladi, qolganlar due=0
    db.set_group_settlement(group_id, "debt", 0, 50000)

    # SUM(amount_due) AYNAN 50000 (100000 emas)
    assert db.get_seller_debt_total(seller) == 50000

    a, b = db.get_order_by_id(o1), db.get_order_by_id(o2)
    assert a["settlement_type"] == "debt" and b["settlement_type"] == "debt"
    dues = sorted([a["amount_due"], b["amount_due"]])
    assert dues == [0, 50000]  # bittasi 0, bittasi to'liq


def test_group_settlement_paid_marks_all_settled(db, buyer, seller, product):
    o1 = _order(db, buyer, seller, product, price=30000)
    o2 = _order(db, buyer, seller, product, price=20000)
    group_id = str(min(o1, o2))
    db.set_orders_group([o1, o2], group_id)
    db.set_group_settlement(group_id, "paid", 50000, 0)
    assert db.get_seller_debt_total(seller) == 0
    for oid in (o1, o2):
        assert db.get_order_by_id(oid)["settled_at"] is not None
