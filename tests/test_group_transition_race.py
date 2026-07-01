"""transition_group_status — faqat SHU chaqiruv o'zgartirgan qatorlarni qaytaradi.

Bug bo'lgan: guruh SELECT ids → keyin bitta UPDATE; qaytarilgan `ids` SELECT paytidagi
ro'yxat edi. Agar orada bir qatorni boshqa chaqiruv (yakka amal) o'zgartirsa, bu chaqiruv
o'zi flip qilmagan id'ni ham qaytarib, u qator IKKI marta restock/xabar olardi. Endi
har qator atomik da'vo qilinadi va faqat yutgan (rowcount=1) id qaytadi.
"""


def test_group_returns_only_rows_it_flipped(db, buyer, seller, product):
    gid = "grp-1"
    o1 = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                         quantity=1, total_price=45000, order_group_id=gid)
    o2 = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                         quantity=1, total_price=45000, order_group_id=gid)
    o3 = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                         quantity=1, total_price=45000, order_group_id=gid)

    # Poygani taqlid qilamiz: o2 ni BOSHQA chaqiruv allaqachon 'confirmed' qildi.
    assert db.transition_order_status(o2, "confirmed", "pending") is True

    # Guruh-bekor endi FAQAT hali 'pending' bo'lgan o1, o3 ni qaytarishi kerak — o2 EMAS.
    won = db.transition_group_status(gid, "cancelled", "pending",
                                     cancel_by="buyer", cancel_reason="text:fikr")
    assert set(won) == {o1, o3}
    assert o2 not in won


def test_group_double_call_no_overlap(db, buyer, seller, product):
    """Guruhni ketma-ket ikki marta bekor qilsak — 2-chi bo'sh qaytadi (qayta restock yo'q)."""
    gid = "grp-2"
    o1 = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                         quantity=1, total_price=45000, order_group_id=gid)
    o2 = db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                         quantity=1, total_price=45000, order_group_id=gid)
    first = db.transition_group_status(gid, "cancelled", "pending", cancel_by="seller")
    second = db.transition_group_status(gid, "cancelled", "pending", cancel_by="seller")
    assert set(first) == {o1, o2}
    assert second == []  # hech narsa qolmadi — ikki marta restock bo'lmaydi
