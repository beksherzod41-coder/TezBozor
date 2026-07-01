"""To'lov idempotentligi — mark_paid_atomic aynan BIR marta yutadi (double-fulfill himoyasi).

Bug bo'lgan: _mark_paid_and_fulfill get_payment (o'qish) va set_payment_state (yozish)
orasida guard yo'q edi — webhook retry / ko'p worker sharoitida ikkala chaqiruv ham
state=pending ko'rib, Pro/boost IKKI marta berilardi (set_pro_until additive → 2× kun).
Yechim: `UPDATE ... WHERE state!='paid'` atomik da'vo; faqat yutgan chaqiruv fulfillment.
"""


def test_mark_paid_atomic_wins_exactly_once(db, seller):
    pid = db.create_payment(user_id=seller, purpose="subscription", amount=30000)
    # 1-chi da'vo (masalan Click webhook) — YUTADI
    assert db.mark_paid_atomic(pid, provider="click", provider_txn_id="tx1") is True
    # 2-chi da'vo (webhook retry yoki boshqa worker) — allaqachon paid, YUTMAYDI
    assert db.mark_paid_atomic(pid, provider="click", provider_txn_id="tx1") is False
    assert db.mark_paid_atomic(pid, provider="payme", provider_txn_id="tx2") is False
    p = db.get_payment(pid)
    assert p["state"] == "paid"
    # Birinchi (yutgan) chaqiruv provayderi saqlanadi, keyingilar ustidan yozmaydi
    assert p["provider"] == "click"


def test_mark_paid_atomic_unknown_payment(db):
    # Mavjud bo'lmagan to'lov — hech kim yutmaydi (rowcount=0)
    assert db.mark_paid_atomic(999999, provider="click") is False


def test_pro_extended_once_not_twice(db, seller):
    """Yakuniy kafolat: bitta to'lov uchun Pro faqat BIR marta uzaytiriladi.
    mark_paid_atomic yutmagan chaqiruv fulfillment qilmasligi kerak (chaqiruvchi shartga
    amal qiladi) — shu yerda DB darajasida yutish faqat bir marta ekanini qotiramiz."""
    pid = db.create_payment(user_id=seller, purpose="subscription", amount=30000)
    won = [db.mark_paid_atomic(pid, provider="click") for _ in range(5)]
    assert won.count(True) == 1  # 5 marta chaqirilsa ham faqat bittasi yutadi
