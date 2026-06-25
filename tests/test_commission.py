"""Platforma komissiyasi — sotuvchi/admin kesimi (#18).

Qotiriladigan kafolatlar:
- owed (qarz) faqat TO'LANMAGAN (commission_settled_at IS NULL) komissiyani sanaydi;
- paid faqat undirilgan komissiyani sanaydi;
- settle_seller_commission BARCHA ochiq qarzni atomik yopadi va to'g'ri summa/son qaytaradi;
- get_commission_by_sellers admin uchun sotuvchilar bo'yicha owed/paid'ni jamlaydi.
Bog'liq dizayn: monetization-skeleton xotirasi.
"""


def _delivered_order_with_commission(db, buyer, seller, product, price=45000, commission=4500):
    """Yetkazilgan + komissiya yozilgan buyurtma yaratadi va id qaytaradi."""
    oid = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                          quantity=1, total_price=price,
                          payment_method="cash", delivery_type="pickup")
    db.update_order_status(oid, "delivered")
    db.set_order_commission(oid, commission)
    return oid


# ===================== owed / paid ajratish =====================
def test_owed_counts_unsettled_only(db, buyer, seller, product):
    _delivered_order_with_commission(db, buyer, seller, product, commission=3000)
    _delivered_order_with_commission(db, buyer, seller, product, commission=2000)
    assert db.get_commission_owed_by_seller(seller) == 5000
    assert db.get_commission_paid_by_seller(seller) == 0


def test_non_delivered_not_counted(db, buyer, seller, product):
    # confirmed (yetkazilmagan) — komissiya bo'lsa ham sanalmaydi
    oid = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                          quantity=1, total_price=45000,
                          payment_method="cash", delivery_type="pickup")
    db.update_order_status(oid, "confirmed")
    db.set_order_commission(oid, 4500)
    assert db.get_commission_owed_by_seller(seller) == 0


# ===================== settlement (admin undiradi) =====================
def test_settle_closes_debt_and_returns_summary(db, buyer, seller, product):
    _delivered_order_with_commission(db, buyer, seller, product, commission=3000)
    _delivered_order_with_commission(db, buyer, seller, product, commission=2500)

    res = db.settle_seller_commission(seller)
    assert res["count"] == 2
    assert res["amount"] == 5500

    # Yopilgandan keyin: owed → 0, paid → 5500
    assert db.get_commission_owed_by_seller(seller) == 0
    assert db.get_commission_paid_by_seller(seller) == 5500


def test_settle_idempotent_second_call_is_noop(db, buyer, seller, product):
    _delivered_order_with_commission(db, buyer, seller, product, commission=4000)
    first = db.settle_seller_commission(seller)
    assert first["count"] == 1 and first["amount"] == 4000
    second = db.settle_seller_commission(seller)
    assert second["count"] == 0 and second["amount"] == 0  # qayta yopiladigan narsa yo'q


def test_settle_after_new_sale_reopens_only_new(db, buyer, seller, product):
    _delivered_order_with_commission(db, buyer, seller, product, commission=1000)
    db.settle_seller_commission(seller)               # eski yopildi
    _delivered_order_with_commission(db, buyer, seller, product, commission=2000)  # yangi sotuv
    assert db.get_commission_owed_by_seller(seller) == 2000   # faqat yangisi qarz
    assert db.get_commission_paid_by_seller(seller) == 1000


# ===================== admin kesimi =====================
def test_by_sellers_aggregates_owed_and_paid(db, buyer, seller, product):
    _delivered_order_with_commission(db, buyer, seller, product, commission=3000)
    paid_oid = _delivered_order_with_commission(db, buyer, seller, product, commission=1500)
    # bittasini yopamiz (lekin keyin yana ochiq qoldiramiz)
    db.settle_seller_commission(seller)
    _delivered_order_with_commission(db, buyer, seller, product, commission=2000)

    rows = db.get_commission_by_sellers()
    assert len(rows) == 1
    r = rows[0]
    assert r["seller_id"] == seller
    assert r["owed"] == 2000      # yangi sotuv ochiq
    assert r["paid"] == 4500      # avval yopilgan ikkitasi
    assert r["owed_count"] == 1


def test_drilldown_orders_list(db, buyer, seller, product):
    oid = _delivered_order_with_commission(db, buyer, seller, product, commission=900)
    rows = db.get_commission_orders_by_seller(seller)
    assert len(rows) == 1
    assert rows[0]["id"] == oid
    assert rows[0]["commission_amount"] == 900
    assert rows[0]["commission_settled_at"] is None
    assert "product_name" in rows[0]
