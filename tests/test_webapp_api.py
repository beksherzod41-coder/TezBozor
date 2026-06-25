"""Webapp (FastAPI) endpoint guard testlari — auth (401), egalik (403),
validatsiya (400/409) va asosiy happy-path (200).

Har test vaqtinchalik SQLite bazada ishlaydi (webapp_server.db monkeypatch bilan
almashtiriladi). initData test BOT_TOKEN bilan imzolanadi."""
import json
import os
import time

import pytest

# webapp_server import paytida BOT_TOKEN va backend kerak
os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
os.environ.setdefault("DB_BACKEND", "sqlite")

pytest.importorskip("fastapi")  # CI'da fastapi bo'lmasa, bu fayl o'tkazib yuboriladi
from fastapi.testclient import TestClient  # noqa: E402

import webapp_auth  # noqa: E402
import webapp_server  # noqa: E402
from database import Database  # noqa: E402

TOKEN = os.environ["BOT_TOKEN"]


def hdr(tg_id):
    init = webapp_auth.build_init_data(TOKEN, {
        "user": json.dumps({"id": tg_id, "first_name": "T"}),
        "auth_date": str(int(time.time()))})
    return {"Authorization": "tma " + init}


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = Database(db_path=str(tmp_path / "wa.db"))
    monkeypatch.setattr(webapp_server, "db", d)
    monkeypatch.setattr(webapp_server, "BOT_TOKEN", TOKEN)
    # Jarayon-bo'yicha rate-limit buketlari testlar orasida saqlanadi (user id'lar
    # qayta ishlatiladi) — har test toza limitdan boshlasin (test izolyatsiyasi).
    webapp_server._RATE.clear()
    d.create_user(telegram_id=5001, phone_number="998900000001", name="Buyer", role="buyer")
    s = d.create_user(telegram_id=5002, phone_number="998900000002", name="Seller", role="seller")
    d.create_user(telegram_id=5003, phone_number="998900000003", name="Admin", role="admin")
    p = d.create_product(seller_id=s, name="Test mahsulot", price=1000, stock_count=5)
    d.update_product_fields(p, in_stock=1, status="active")
    c = TestClient(webapp_server.app)
    c.pid = p
    return c


def test_health_no_auth(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_categories_requires_auth(client):
    assert client.get("/api/categories").status_code == 401


def test_categories_with_auth(client):
    assert client.get("/api/categories", headers=hdr(5001)).status_code == 200


def test_me_returns_profile(client):
    r = client.get("/api/me", headers=hdr(5001))
    assert r.status_code == 200 and r.json()["name"] == "Buyer"


def test_me_unregistered_403(client):
    assert client.get("/api/me", headers=hdr(99999)).status_code == 403


def test_order_bad_payment_400(client):
    r = client.post("/api/order", headers=hdr(5001),
                    json={"product_id": client.pid, "payment_method": "xxx"})
    assert r.status_code == 400


def test_order_own_product_400(client):
    r = client.post("/api/order", headers=hdr(5002),
                    json={"product_id": client.pid, "quantity": 1,
                          "delivery_type": "pickup", "payment_method": "cash"})
    assert r.status_code == 400  # own_product


def test_staff_product_under_shop_owner(client):
    """Multivendor: xodim joylagan mahsulot DO'KON EGASI nomidan chiqadi (seller_id=ega),
    lekin created_by=xodim. Xodim do'kon mahsulotlarini ko'radi va tahrirlay oladi."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5011, phone_number="998900000011", name="Xodim", role="seller")
    db.add_staff(shop_id, staff_uid, staff_role="staff", is_active=1)
    # xodim mahsulot joylaydi
    r = client.post("/api/seller/product", headers=hdr(5011), json={"name": "Xodim mahsuloti", "price": 5000})
    assert r.status_code == 200, r.text
    pid = r.json()["product_id"]
    prod = db.get_product_by_id(pid)
    assert prod["seller_id"] == owner_id      # do'kon (ega) nomidan
    assert prod["created_by"] == staff_uid    # joylagani saqlandi
    # xodim do'kon mahsulotlari ro'yxatida ko'radi (o'z id'sida emas)
    assert any(p["id"] == pid for p in client.get("/api/seller/products", headers=hdr(5011)).json())
    # xodim do'kon mahsulotini tahrirlay oladi (ruxsat)
    assert client.patch(f"/api/seller/product/{pid}", headers=hdr(5011),
                        json={"price": 6000}).status_code == 200


def test_seller_deleted_audit_list(client):
    """App «O'chirilgan» tab: o'chirilgan mahsulot product_audit orqali EGAsiga ko'rinadi,
    boshqa do'konga ko'rinmaydi."""
    db = webapp_server.db
    other = db.create_user(telegram_id=5042, phone_number="998900000042", name="Other", role="seller")
    r = client.post("/api/seller/product", headers=hdr(5002), json={"name": "Ochiriladigan", "price": 7000})
    pid = r.json()["product_id"]
    # buyurtmasi yo'q → jismonan o'chadi + audit yoziladi
    assert client.delete(f"/api/seller/product/{pid}", headers=hdr(5002)).status_code == 200
    mine = client.get("/api/seller/deleted", headers=hdr(5002)).json()
    assert any(a.get("name") == "Ochiriladigan" for a in mine)
    theirs = client.get("/api/seller/deleted", headers=hdr(5042)).json()
    assert not any(a.get("name") == "Ochiriladigan" for a in theirs)


def test_orders_carry_creator_for_staff_filter(client):
    """Taklif: buyurtmalar xodim (creator) ma'lumotini olib keladi — ega xodim bo'yicha filtrlaydi."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5017, phone_number="998900000017", name="Sherzod", role="seller")
    db.add_staff(shop_id, staff_uid, is_active=1)
    # xodim mahsulot joylaydi (seller_id=ega, created_by=xodim)
    r = client.post("/api/seller/product", headers=hdr(5017), json={"name": "Xodim mahsuloti", "price": 2000})
    spid = r.json()["product_id"]
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    db.create_order(buyer_id, owner_id, spid, 1, 2000)
    # ega buyurtmalarni ko'radi — creator (xodim) ma'lumoti bilan
    orders = client.get("/api/seller/orders", headers=hdr(5002)).json()
    target = next(o for o in orders if o["product_name"] == "Xodim mahsuloti")
    assert target["creator_id"] == staff_uid and target["creator_name"] == "Sherzod"


def test_confirm_atomic_guard_no_double_stock(client):
    """ATOMIK guard: bir buyurtmani ikki marta tasdiqlab bo'lmaydi (2-si 409) va zahira
    FAQAT bir marta kamayadi. Bot va Mini App bir vaqtda tasdiqlashidagi poygani modellaydi."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    db.create_shop(owner_id)
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    stock0 = db.get_product_by_id(client.pid)["stock_count"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 2, 2000)
    # 1-tasdiq → 200, zahira 2 ga kamayadi
    r1 = client.post(f"/api/seller/order/{oid}/action", headers=hdr(5002), json={"action": "confirm"})
    assert r1.status_code == 200, r1.text
    assert db.get_order_by_id(oid)["status"] == "confirmed"
    stock1 = db.get_product_by_id(client.pid)["stock_count"]
    assert stock1 == stock0 - 2
    # 2-tasdiq (takror/poyga) → 409, zahira O'ZGARMAYDI
    r2 = client.post(f"/api/seller/order/{oid}/action", headers=hdr(5002), json={"action": "confirm"})
    assert r2.status_code == 409
    assert db.get_product_by_id(client.pid)["stock_count"] == stock1


def test_my_orders_exposes_deadline(client):
    """Jonli sanoq (#2): pending buyurtma /api/my/orders'da `auto_cancel_at` (UTC) qaytaradi
    — frontend shu maydondan teskari sanoqni chizadi."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)
    db.set_order_deadline(oid, "2099-01-01 00:00:00")
    rows = client.get("/api/my/orders", headers=hdr(5001)).json()
    row = next(r for r in rows if r["id"] == oid)
    assert row.get("auto_cancel_at") == "2099-01-01 00:00:00"


def test_transition_order_status_atomic(client):
    """transition_order_status faqat kutilgan holatdan o'tkazadi va aynan BIR marta
    True qaytaradi (atomik guard poydevori)."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)
    assert db.transition_order_status(oid, "confirmed", "pending") is True
    # endi 'pending' emas → ikkinchi chaqiruv False
    assert db.transition_order_status(oid, "confirmed", "pending") is False
    assert db.get_order_by_id(oid)["status"] == "confirmed"


def test_admin_analytics_and_financial(client):
    """A2/A3 — admin voronka + moliyaviy hisobot endpointlari (admin-only)."""
    # admin-only
    assert client.get("/api/admin/analytics", headers=hdr(5001)).status_code == 403
    assert client.get("/api/admin/financial", headers=hdr(5002)).status_code == 403
    a = client.get("/api/admin/analytics", headers=hdr(5003)).json()
    assert "total_orders" in a and "confirm_rate" in a and "deliver_rate" in a
    f = client.get("/api/admin/financial", headers=hdr(5003)).json()
    for k in ("delivered_count", "total_revenue", "top_sellers", "by_payment", "by_delivery"):
        assert k in f, k


def test_courier_role_and_orders(client):
    """C — kuryer roli: ega xodimni kuryer qiladi; kuryer yo'ldagi yetkazishlarni ko'radi,
    yetkazib berishni yakunlaydi; oddiy xodim kuryer endpointiga 403."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    cour = db.create_user(telegram_id=5019, phone_number="998900000019", name="Kuryer", role="seller")
    sid = db.add_staff(shop_id, cour, is_active=1)
    # kuryer bo'lishidan oldin — courier endpoint 403
    assert client.get("/api/courier/orders", headers=hdr(5019)).status_code == 403
    # ega kuryer qiladi
    assert client.post(f"/api/seller/staff/{sid}/role", headers=hdr(5002),
                       json={"role": "courier"}).status_code == 200
    assert client.get("/api/me", headers=hdr(5019)).json()["is_courier"] is True
    # do'kon yetkazib berish buyurtmasi (confirmed)
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000,
                          delivery_address="Toshkent", delivery_type="delivery")
    conn = db.get_connection(); conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,)); conn.commit()
    # #3 — kuryer endi faqat O'ZIGA biriktirilgan buyurtmani ko'radi: ega biriktiradi
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5002),
                       json={"courier_id": cour}).status_code == 200
    co = client.get("/api/courier/orders", headers=hdr(5019)).json()
    assert any(o["id"] == oid for o in co)
    # kuryer yetkazib berishni yakunlaydi (perm_confirm yo'q bo'lsa ham — kuryer huquqi)
    db.update_staff(sid, perm_confirm_orders=0)
    r = client.post(f"/api/seller/order/{oid}/deliver", headers=hdr(5019),
                    json={"settlement_type": "paid", "paid": 1000})
    assert r.status_code == 200, r.text
    assert db.get_order_by_id(oid)["status"] == "delivered"


def test_courier_assignment(client):
    """#3 — buyurtmaga aniq kuryer biriktirish: faqat biriktirilgan kuryer ko'radi;
    boshqa kuryer ko'rmaydi; ega kuryerlar ro'yxatini oladi; kuryer bo'lmaganga 400."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    c1 = db.create_user(telegram_id=5031, phone_number="998900000031", name="Kuryer1", role="seller")
    c2 = db.create_user(telegram_id=5032, phone_number="998900000032", name="Kuryer2", role="seller")
    db.add_staff(shop_id, c1, staff_role="courier", is_active=1)
    db.add_staff(shop_id, c2, staff_role="courier", is_active=1)
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000,
                          delivery_address="Toshkent", delivery_type="delivery")
    conn = db.get_connection(); conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,)); conn.commit()
    # ega kuryerlar ro'yxatini oladi (ikkalasi ham)
    couriers = client.get("/api/seller/couriers", headers=hdr(5002)).json()
    assert {c["user_id"] for c in couriers} >= {c1, c2}
    # biriktirishdan oldin — hech bir kuryer bu buyurtmani ko'rmaydi
    assert not any(o["id"] == oid for o in client.get("/api/courier/orders", headers=hdr(5031)).json())
    # kuryer bo'lmagan foydalanuvchini biriktirib bo'lmaydi → 400
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5002),
                       json={"courier_id": buyer_id}).status_code == 400
    # c1 ga biriktiramiz → faqat c1 ko'radi, c2 ko'rmaydi
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5002),
                       json={"courier_id": c1}).status_code == 200
    assert any(o["id"] == oid for o in client.get("/api/courier/orders", headers=hdr(5031)).json())
    assert not any(o["id"] == oid for o in client.get("/api/courier/orders", headers=hdr(5032)).json())
    # biriktirilganda kuryerga PUSH navbatga qo'yiladi (bot fon job o'qiydi)
    assert oid in db.get_orders_awaiting_courier_notify()
    # biriktirishni bekor qilamiz → qayta hech kim ko'rmaydi + PUSH navbatdan chiqadi
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5002),
                       json={"courier_id": None}).status_code == 200
    assert not any(o["id"] == oid for o in client.get("/api/courier/orders", headers=hdr(5031)).json())
    assert oid not in db.get_orders_awaiting_courier_notify()
    # begona (boshqa do'kon yo'q) xaridor o'zga buyurtmaga kuryer biriktira olmaydi (seller_id qo'riqlovi)
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5001),
                       json={"courier_id": c1}).status_code in (400, 404)


def test_me_full_and_per_field_edit(client):
    """Profil: /api/me/full to'liq ma'lumot; har maydon ALOHIDA PATCH /api/me bilan."""
    db = webapp_server.db
    f = client.get("/api/me/full", headers=hdr(5002)).json()
    for k in ("id", "telegram_id", "role", "created_at", "buyer_orders_count"):
        assert k in f, k
    assert client.patch("/api/me", headers=hdr(5002), json={"name": "Yangi Ism"}).status_code == 200
    assert db.get_user_by_telegram_id(5002)["name"] == "Yangi Ism"
    assert client.patch("/api/me", headers=hdr(5002), json={"telegram_username": "ab"}).status_code == 400
    assert client.patch("/api/me", headers=hdr(5002), json={"telegram_username": "@my_shop1"}).status_code == 200
    assert db.get_user_by_telegram_id(5002)["telegram_username"] == "my_shop1"
    rid = db.get_regions(None)[0]["id"]
    assert client.patch("/api/me", headers=hdr(5002), json={"region_id": rid}).status_code == 200
    assert db.get_user_by_telegram_id(5002)["region_id"] == rid


def test_staff_review_reply_perm(client):
    """C3 — sharh do'kon (ega) ostida; xodim perm_reply_reviews bilan javob beradi, ruxsatsiz → 403."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5018, phone_number="998900000018", name="St", role="seller")
    db.add_staff(shop_id, staff_uid, is_active=1)
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)
    rid = db.create_review(oid, owner_id, buyer_id, 5, comment="zo'r", product_id=client.pid, product_rating=5)
    # ruxsatni o'chiramiz → 403 no_perm_reply
    db.update_staff(db.get_staff_by_user(staff_uid)["id"], perm_reply_reviews=0)
    r0 = client.post(f"/api/seller/review/{rid}/reply", headers=hdr(5018), json={"text": "Rahmat!"})
    assert r0.status_code == 403 and r0.json()["detail"] == "no_perm_reply"
    # ruxsat bilan → xodim do'kon sharhiga javob yozadi (seller_id=ega bo'lsa ham)
    db.update_staff(db.get_staff_by_user(staff_uid)["id"], perm_reply_reviews=1)
    r1 = client.post(f"/api/seller/review/{rid}/reply", headers=hdr(5018), json={"text": "Rahmat!"})
    assert r1.status_code == 200, r1.text
    assert db.get_review_by_id(rid)["seller_reply"] == "Rahmat!"


def test_staff_confirms_shop_order(client):
    """Multivendor: xodim do'kon (bot/kanal) buyurtmasini app orqali tasdiqlaydi (perm bilan);
    perm_confirm_orders yo'q bo'lsa → 403. Buyurtma seller_id=ega (do'kon)."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5016, phone_number="998900000016", name="St", role="seller")
    db.add_staff(shop_id, staff_uid, is_active=1)
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)   # bot/kanal buyurtmasi (ega ostida)
    # xodim do'kon buyurtmasini ko'radi
    assert any(o["id"] == oid for o in client.get("/api/seller/orders", headers=hdr(5016)).json())
    # ruxsat bilan tasdiqlaydi
    r = client.post(f"/api/seller/order/{oid}/action", headers=hdr(5016), json={"action": "confirm"})
    assert r.status_code == 200, r.text
    assert db.get_order_by_id(oid)["status"] == "confirmed"
    # ruxsatsiz xodim → 403
    db.update_staff(db.get_staff_by_user(staff_uid)["id"], perm_confirm_orders=0)
    oid2 = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)
    assert client.post(f"/api/seller/order/{oid2}/action", headers=hdr(5016),
                       json={"action": "confirm"}).status_code == 403


def test_manager_can_add_staff_with_perm(client):
    """B — perm_add_staff'li MENEJER taklif yarata oladi; oddiy xodim — yo'q (403)."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    mgr = db.create_user(telegram_id=5013, phone_number="998900000013", name="Mgr", role="seller")
    db.add_staff(shop_id, mgr, staff_role="manager", is_active=1)
    # ruxsatsiz menejer — 403
    assert client.post("/api/seller/staff/invite", headers=hdr(5013)).status_code == 403
    # ega ruxsat beradi
    db.update_staff(db.get_staff_by_user(mgr)["id"], perm_add_staff=1)
    r = client.post("/api/seller/staff/invite", headers=hdr(5013))
    assert r.status_code == 200 and r.json().get("code")
    # /api/me — menejer endi xodim boshqara oladi
    assert client.get("/api/me", headers=hdr(5013)).json()["can_manage_staff"] is True
    # ruxsat berish (perm) esa FAQAT egada — menejer perm o'zgartira olmaydi (owner-only)
    sid_other = db.add_staff(shop_id, db.create_user(telegram_id=5014, phone_number="998900000014", name="W", role="seller"), is_active=1)
    assert client.post(f"/api/seller/staff/{sid_other}/perm", headers=hdr(5013),
                       json={"key": "add"}).status_code == 403


def test_staff_my_card(client):
    """A — payment_mode='staff' bo'lsa xodim o'z kartasini qo'sha oladi; 'shop' rejimda — yo'q."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5015, phone_number="998900000015", name="St", role="seller")
    db.add_staff(shop_id, staff_uid, is_active=1)
    # default 'shop' rejim — karta qo'shib bo'lmaydi
    assert client.get("/api/seller/my-card", headers=hdr(5015)).json()["applicable"] is False
    assert client.patch("/api/seller/my-card", headers=hdr(5015),
                        json={"card_number": "8600123412341234"}).status_code == 409
    # ega 'staff' rejimga o'tkazadi
    db.update_shop(shop_id, payment_mode="staff")
    assert client.get("/api/seller/my-card", headers=hdr(5015)).json()["applicable"] is True
    assert client.patch("/api/seller/my-card", headers=hdr(5015),
                        json={"card_number": "8600 1234 1234 1234", "card_owner": "St"}).status_code == 200
    assert dict(db.get_staff_by_user(staff_uid))["card_number"] == "8600123412341234"


def test_staff_no_add_permission_403(client):
    """Xodimga 'mahsulot qo'shish' ruxsati berilmagan bo'lsa — 403."""
    db = webapp_server.db
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    shop_id = db.create_shop(owner_id)
    staff_uid = db.create_user(telegram_id=5012, phone_number="998900000012", name="X2", role="seller")
    db.add_staff(shop_id, staff_uid, staff_role="staff", is_active=1)
    db.update_staff(db.get_staff_by_user(staff_uid)["id"], perm_add_product=0)
    r = client.post("/api/seller/product", headers=hdr(5012), json={"name": "X", "price": 1000})
    assert r.status_code == 403 and r.json()["detail"] == "no_perm_add"


def test_edit_product_not_owner_403(client):
    r = client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5001),
                     json={"price": 500})
    assert r.status_code == 403


def test_product_unit_roundtrip(client):
    """#20 — o'lchov birligi (unit) saqlanadi va mahsulot detalida qaytadi."""
    # yangi mahsulotda unit
    r = client.post("/api/seller/product", headers=hdr(5002),
                    json={"name": "Olma", "price": 12000, "unit": "kg"})
    assert r.status_code == 200, r.text
    pid = r.json()["product_id"]
    assert client.get(f"/api/products/{pid}", headers=hdr(5001)).json()["unit"] == "kg"
    # tahrirda o'zgartirish
    assert client.patch(f"/api/seller/product/{pid}", headers=hdr(5002),
                        json={"unit": "dona"}).status_code == 200
    assert client.get(f"/api/products/{pid}", headers=hdr(5001)).json()["unit"] == "dona"


def test_delete_product_with_scheduled_post_ok(client):
    """#1 — rejalashtirilgan post/avto-reklamasi bor mahsulotni o'chirish 500 bermasin.
    scheduled_posts/auto_reposts products(id) ga FK (CASCADE'siz) — avval tozalanishi shart."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.create_scheduled_post(client.pid, seller_id=sid,
                             scheduled_at="2099-01-01 00:00:00", created_by=sid)
    r = client.delete(f"/api/seller/product/{client.pid}", headers=hdr(5002))
    assert r.status_code == 200, r.text
    assert db.get_product_by_id(client.pid) is None  # buyurtmasiz — jismonan o'chdi


def test_edit_shop_non_owner_403(client):
    """#10 — do'kon sozlamalarini do'kon EGASI bo'lmagan sotuvchi o'zgartira olmasin."""
    # 5002 sotuvchi, lekin hech qaysi do'kon egasi emas (shops yozuvi yo'q)
    r = client.patch("/api/seller/shop", headers=hdr(5002), json={"shop_name": "X"})
    assert r.status_code == 403 and r.json()["detail"] == "not_owner"


def test_edit_shop_owner_ok(client):
    """#10 — do'kon EGASI sozlamalarni o'zgartira oladi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.create_shop(sid)
    r = client.patch("/api/seller/shop", headers=hdr(5002), json={"shop_name": "Yangi nom"})
    assert r.status_code == 200, r.text


def test_edit_shop_region(client):
    """#2 — do'kon egasi hududni (viloyat/tuman) tanlay/o'zgartira oladi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.create_shop(sid)
    regions = db.get_regions(None)
    assert regions, "test bazasida hududlar bo'lishi kerak"
    rid = regions[0]["id"]
    r = client.patch("/api/seller/shop", headers=hdr(5002), json={"shop_name": "Sh", "region_id": rid})
    assert r.status_code == 200, r.text
    assert db.get_product_by_id(client.pid)  # sanity
    got = client.get("/api/seller/shop", headers=hdr(5002)).json()
    assert got["region_id"] == rid and got["region_label"]
    # noma'lum hudud → 400
    bad = client.patch("/api/seller/shop", headers=hdr(5002), json={"shop_name": "Sh", "region_id": 999999})
    assert bad.status_code == 400


def test_edit_shop_telegram_username(client):
    """Sotuvchi kontakt username (bot edit_telegram pariteti): saqlash, '@'/bo'shliq
    tozalanishi, GET'da qaytishi, yaroqsizi 400, bo'sh qiymat tozalashi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.create_shop(sid)
    # '@' va bo'shliqlar bilan — tozalanib saqlanishi kerak
    r = client.patch("/api/seller/shop", headers=hdr(5002),
                     json={"shop_name": "Sh", "telegram_username": " @tezbozor_sotuvchi "})
    assert r.status_code == 200, r.text
    got = client.get("/api/seller/shop", headers=hdr(5002)).json()
    assert got["telegram_username"] == "tezbozor_sotuvchi"
    # yaroqsiz (juda qisqa / taqiqlangan belgi) → 400
    bad = client.patch("/api/seller/shop", headers=hdr(5002),
                       json={"shop_name": "Sh", "telegram_username": "a!"})
    assert bad.status_code == 400
    # bo'sh qiymat → tozalanadi
    clr = client.patch("/api/seller/shop", headers=hdr(5002),
                       json={"shop_name": "Sh", "telegram_username": ""})
    assert clr.status_code == 200
    assert not client.get("/api/seller/shop", headers=hdr(5002)).json().get("telegram_username")


def test_me_reports_owner_flag(client):
    """#9 — /api/me egalik bayrog'ini qaytaradi (frontend rejim/sozlama uchun)."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    assert client.get("/api/me", headers=hdr(5002)).json()["is_owner"] is False
    db.create_shop(sid)
    assert client.get("/api/me", headers=hdr(5002)).json()["is_owner"] is True


def test_cancel_invite(client):
    """#8 — do'kon egasi adashib yuborilgan taklifni bekor qila oladi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    shop_id = db.create_shop(sid)
    db.create_invite(shop_id, created_by=sid)
    invites = db.get_active_invites(shop_id)
    assert len(invites) == 1
    inv_id = invites[0]["id"]
    # boshqa foydalanuvchi (ega emas) bekor qila olmaydi
    assert client.delete(f"/api/seller/staff/invite/{inv_id}", headers=hdr(5001)).status_code == 403
    # ega bekor qiladi
    r = client.delete(f"/api/seller/staff/invite/{inv_id}", headers=hdr(5002))
    assert r.status_code == 200, r.text
    assert db.get_active_invites(shop_id) == []


def test_perf_indexes_exist(client):
    """Tezlik #3 — issiq yo'l indekslari yaratilgan bo'lsin (search_products reviews subquery)."""
    conn = webapp_server.db.get_connection()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    for expected in ("idx_reviews_product", "idx_reviews_seller",
                     "idx_products_seller", "idx_orders_product"):
        assert expected in names, f"{expected} indeksi yo'q"


def test_review_not_delivered_409(client):
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    r = client.post(f"/api/order/{oid}/review", headers=hdr(5001),
                    json={"seller_rating": 5})
    assert r.status_code == 409  # not_delivered


def test_haggle_min_price_hidden(client):
    """#8 — maxfiy min_price hech qachon xaridorga (detail/qidiruv) yuborilmaydi."""
    db = webapp_server.db
    db.update_product_fields(client.pid, min_price=700)
    # xaridor detali — min_price yo'q, lekin haggle_on=True
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert "min_price" not in d and d["haggle_on"] is True
    assert d["is_own"] is False   # xaridor — o'zi emas
    # sotuvchi o'z mahsulotini ko'rsa is_own=True (savdolashish tugmasi yashiriladi)
    assert client.get(f"/api/products/{client.pid}", headers=hdr(5002)).json()["is_own"] is True
    # sotuvchi o'z mahsuloti bilan savdolasholmaydi → 400 own_product
    bad = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5002),
                      json={"message": "arzon ber"})
    assert bad.status_code == 400 and bad.json()["detail"] == "own_product"
    # qidiruv ro'yxatida ham min_price yo'q
    for p in client.get("/api/products", headers=hdr(5001)).json():
        assert "min_price" not in p
    # EGA (sotuvchi) detalida min_price ko'rinadi (tahrir formasi uchun)
    assert client.get(f"/api/products/{client.pid}", headers=hdr(5002)).json().get("min_price") == 700


def test_haggle_deal_applied_and_floor_protected(client, monkeypatch):
    """#8 — AI kelishsa narx checkout'da qo'llanadi; server floor'dan past saqlamaydi."""
    db = webapp_server.db
    db.update_product_fields(client.pid, min_price=700)   # listed=1000, floor=700
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    # AI floor'dan PAST (500) qabul qildi deb qaytaradi — server 700 ga ko'taradi
    async def fake_haggle(*, listed_price, floor_price, history, buyer_message, lang="uz"):
        return {"reply": "Mayli", "offer_price": 500, "accepted": True}
    monkeypatch.setattr(webapp_server.ai_assistant, "haggle", fake_haggle)
    r = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5001),
                    json={"message": "500 ga ber"})
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert r.json()["agreed_price"] == 700   # floor'ga clamp, pastga tushmadi
    # buyurtma shu narxda yaratiladi
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 2,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    assert db.get_order_by_id(oid)["total_price"] == 1400   # 2 × 700 (kelishilgan)


def test_haggle_fallback_when_ai_fails(client, monkeypatch):
    """#8 — AI muvaffaqiyatsiz (None) bo'lsa savdolashish 502 bermaydi: deterministik
    zaxira ishlaydi. Narx BIRDANIGA floor'ga tushmaydi (bosqichma-bosqich), floor
    hech qachon buzilmaydi, listed'dan oshmaydi."""
    db = webapp_server.db
    db.update_product_fields(client.pid, min_price=700)   # listed=1000, floor=700
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    async def dead_haggle(*, listed_price, floor_price, history, buyer_message, lang="uz"):
        return None   # DeepSeek bo'sh/timeout
    monkeypatch.setattr(webapp_server.ai_assistant, "haggle", dead_haggle)

    # 1-raund past taklif (500) → birdaniga floor (700) ga TUSHMAYDI: listed'ga
    # yaqin, faqat ozgina chegirma; floor < taklif <= listed oralig'ida
    r = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5001),
                    json={"message": "500 ga ber aka", "history": []})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["accepted"] is False
    assert 700 < j["offer_price"] <= 1000   # floor'ga sakramadi
    first = j["offer_price"]

    # ko'p raund qistalsa → narx asta-sekin floor'ga yaqinlashadi (lekin tushmaydi)
    hist = [{"role": "assistant", "content": "x"}] * 5
    r2 = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5003),
                     json={"message": "500 dan oshmayman", "history": hist})
    assert r2.status_code == 200
    later = r2.json()["offer_price"]
    assert later < first and later >= 700   # pasaydi, ammo floor'dan past emas

    # listed'dan yuqori/teng taklif → darhol kelishuv, lekin listed'dan oshmaydi
    r3 = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5001),
                     json={"message": "1200 ga olaman", "history": []})
    assert r3.status_code == 200
    assert r3.json()["accepted"] is True and r3.json()["agreed_price"] == 1000

    # raqamsiz xabar → narx so'raydi, 502 emas
    r4 = client.post(f"/api/product/{client.pid}/haggle", headers=hdr(5003),
                     json={"message": "arzonroq qiling", "history": []})
    assert r4.status_code == 200 and r4.json()["accepted"] is False


def test_shop_ai_answer_rag(client, monkeypatch):
    """#3 AI-menejer — savolga do'kon faktlaridan javob (AI mock bilan)."""
    captured = {}
    async def fake_answer(*, question, facts, lang="uz"):
        captured["facts"] = facts
        captured["q"] = question
        return "Ha, yetkazib beramiz."
    monkeypatch.setattr(webapp_server.ai_assistant, "answer_shop_question", fake_answer)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    r = client.post(f"/api/product/{client.pid}/ask", headers=hdr(5001),
                    json={"question": "Yetkazib berasizmi?"})
    assert r.status_code == 200 and r.json()["answer"] == "Ha, yetkazib beramiz."
    # RAG: faktlar matniga mahsulot nomi kiritilgan
    assert "Test mahsulot" in captured["facts"]
    # bo'sh savol → 400
    assert client.post(f"/api/product/{client.pid}/ask", headers=hdr(5001),
                       json={"question": "  "}).status_code == 400


def test_moderation_blocks_and_admin_approves(client, monkeypatch):
    """#5 — AI taqiqlangan deb belgilasa mahsulot bloklanadi; admin tasdiqlaydi → active."""
    async def fake_mod(*, name, description="", lang="uz"):
        return {"flagged": True, "category": "weapon", "reason": "taqiqlangan tovar"}
    monkeypatch.setattr(webapp_server.ai_assistant, "moderate_product", fake_mod)
    db = webapp_server.db
    r = client.post("/api/seller/product", headers=hdr(5002),
                    json={"name": "Shubhali", "price": 1000})
    assert r.status_code == 200 and r.json()["blocked"] is True
    pid = r.json()["product_id"]
    prod = db.get_product_by_id(pid)
    assert prod["status"] == "mod_blocked" and prod["in_stock"] == 0
    # admin moderatsiya navbatida ko'rinadi
    q = client.get("/api/admin/moderation", headers=hdr(5003)).json()
    assert any(p["id"] == pid for p in q)
    # oddiy sotuvchi navbatni ko'ra olmaydi
    assert client.get("/api/admin/moderation", headers=hdr(5002)).status_code == 403
    # admin tasdiqlaydi → active
    assert client.post(f"/api/admin/moderation/{pid}/approve", headers=hdr(5003)).status_code == 200
    assert db.get_product_by_id(pid)["status"] == "active"


def test_edit_moderation_blocks(client, monkeypatch):
    """#5 — TAHRIRDA ham: nom/tavsif taqiqlangan bo'lsa mahsulot bloklanadi."""
    async def fake_mod(*, name, description="", lang="uz"):
        return {"flagged": True, "category": "drug", "reason": "taqiqlangan"}
    monkeypatch.setattr(webapp_server.ai_assistant, "moderate_product", fake_mod)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    db = webapp_server.db
    assert db.get_product_by_id(client.pid)["status"] == "active"
    r = client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002),
                     json={"name": "Shubhali nom"})
    assert r.status_code == 200 and r.json()["blocked"] is True
    assert db.get_product_by_id(client.pid)["status"] == "mod_blocked"


def test_detail_shows_deal_price(client, monkeypatch):
    """#8 — checkout uchun: kelishilgan narx mahsulot detalida (deal_price) qaytadi."""
    db = webapp_server.db
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    db.set_haggle_deal(buyer_id, client.pid, 750, ttl_minutes=60)
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert d["deal_price"] == 750
    # boshqa xaridorda kelishuv yo'q
    assert client.get(f"/api/products/{client.pid}", headers=hdr(5003)).json()["deal_price"] is None


def test_moderation_clean_passes(client, monkeypatch):
    """AI toza deb topsa — mahsulot darhol active."""
    async def fake_mod(*, name, description="", lang="uz"):
        return {"flagged": False, "category": "", "reason": ""}
    monkeypatch.setattr(webapp_server.ai_assistant, "moderate_product", fake_mod)
    r = client.post("/api/seller/product", headers=hdr(5002),
                    json={"name": "Olma", "price": 1000})
    assert r.json()["blocked"] is False
    assert webapp_server.db.get_product_by_id(r.json()["product_id"])["status"] == "active"


def test_seller_route_optimization(client):
    """AI #12 — bir nechta yetkazib berish buyurtmasi eng qisqa tartibda qaytadi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.update_user(sid, shop_lat=41.30, shop_lon=69.24)   # do'kon boshlanish nuqtasi
    # 3 ta delivery buyurtma — turli koordinata
    coords = [(41.40, 69.30), (41.31, 69.25), (41.36, 69.28)]
    for i, (la, lo) in enumerate(coords):
        ro = client.post("/api/order", headers=hdr(5001),
                         json={"product_id": client.pid, "quantity": 1,
                               "delivery_type": "delivery", "address": f"Manzil {i}",
                               "lat": la, "lon": lo})
        oid = ro.json()["order_id"]
        conn = db.get_connection()
        conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,))
        conn.commit()
    d = client.get("/api/seller/route", headers=hdr(5002)).json()
    assert len(d["stops"]) == 3
    assert d["has_start"] is True and d["total_km"] > 0
    assert [s["seq"] for s in d["stops"]] == [1, 2, 3]   # ketma-ket raqamlangan
    assert d["maps_url"] and "google.com/maps/dir" in d["maps_url"]
    # eng yaqin to'xtov (do'konga 41.30,69.24) birinchi bo'lishi kerak: 41.31,69.25
    assert abs(d["stops"][0]["lat"] - 41.31) < 0.001


def test_delivery_tracking(client):
    """#13 — yetkazib beruvchi joylashuv ulashadi; xaridor masofa+ETA oladi."""
    db = webapp_server.db
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "delivery", "address": "Toshkent",
                           "lat": 41.31, "lon": 69.24})
    assert ro.status_code == 200, ro.text
    oid = ro.json()["order_id"]
    conn = db.get_connection()
    conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,))
    conn.commit()
    # xaridor (sotuvchi emas) joylashuv ulay olmaydi
    assert client.post(f"/api/seller/order/{oid}/location", headers=hdr(5001),
                       json={"lat": 41.35, "lon": 69.28}).status_code == 403
    # sotuvchi joylashuvni ulashadi
    assert client.post(f"/api/seller/order/{oid}/location", headers=hdr(5002),
                       json={"lat": 41.35, "lon": 69.28}).status_code == 200
    # xaridor kuzatuvni oladi — masofa va ETA hisoblanadi
    t = client.get(f"/api/order/{oid}/tracking", headers=hdr(5001)).json()
    assert t["courier_lat"] == 41.35
    assert t["distance_km"] is not None and t["eta_min"] is not None


def test_favorites_add_list_remove(client):
    """#16 — sevimliga qo'shish/ro'yxat/o'chirish va detalda is_favorite holati."""
    # boshda bo'sh
    assert client.get("/api/favorites", headers=hdr(5001)).json() == []
    # qo'shish
    assert client.post(f"/api/favorites/{client.pid}", headers=hdr(5001)).json()["is_favorite"] is True
    lst = client.get("/api/favorites", headers=hdr(5001)).json()
    assert len(lst) == 1 and lst[0]["id"] == client.pid
    # detalda is_favorite=True
    assert client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()["is_favorite"] is True
    # o'chirish
    assert client.delete(f"/api/favorites/{client.pid}", headers=hdr(5001)).json()["is_favorite"] is False
    assert client.get("/api/favorites", headers=hdr(5001)).json() == []


def test_favorite_survives_product_delete(client):
    """Sevimliga qo'shilgan mahsulot o'chirilsa — CASCADE bilan favorites tozalanadi (500 emas)."""
    db = webapp_server.db
    client.post(f"/api/favorites/{client.pid}", headers=hdr(5001))
    # buyurtmasiz mahsulot — jismonan o'chadi; favorites CASCADE bilan ketadi
    r = client.delete(f"/api/seller/product/{client.pid}", headers=hdr(5002))
    assert r.status_code == 200, r.text
    assert client.get("/api/favorites", headers=hdr(5001)).json() == []


def test_price_drop_does_not_error(client):
    """#16 — narx pasaytirilganda tahrirlash 200 qaytaradi (xabar fonda, favoriter bo'lsa ham)."""
    client.post(f"/api/favorites/{client.pid}", headers=hdr(5001))
    r = client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"price": 500})
    assert r.status_code == 200, r.text


def test_loyalty_points_and_tier(client):
    """#16 — sodiqlik: boshda bronza/0; yetkazilgan buyurtmadan keyin ball oshadi."""
    d = client.get("/api/me/loyalty", headers=hdr(5001)).json()
    assert d["tier"] == "bronze" and d["points"] == 0
    assert d["next_tier"] == "silver" and d["progress"] is not None
    # buyurtma yaratib, yetkazilgan holatga o'tkazamiz → ball oshishi kerak
    db = webapp_server.db
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 2,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    conn = db.get_connection()
    conn.execute("UPDATE orders SET status='delivered' WHERE id=?", (oid,))
    conn.commit()
    d2 = client.get("/api/me/loyalty", headers=hdr(5001)).json()
    assert d2["points"] >= 5  # kamida yetkazilgan_buyurtma*5
    assert d2["breakdown"]["delivered_orders"] == 1


def test_seller_analytics(client):
    """#17 — sotuvchi tahlili: tuzilma (top_products/by_weekday/daily_7) qaytadi."""
    a = client.get("/api/seller/analytics", headers=hdr(5002)).json()
    assert "top_products" in a and isinstance(a["top_products"], list)
    assert isinstance(a["by_weekday"], list) and len(a["by_weekday"]) == 7
    assert isinstance(a["daily_7"], list)
    # buyurtma berilgach by_weekday yig'indisi oshadi
    before = sum(a["by_weekday"])
    client.post("/api/order", headers=hdr(5001),
                json={"product_id": client.pid, "quantity": 1,
                      "delivery_type": "pickup", "payment_method": "cash"})
    after = sum(client.get("/api/seller/analytics", headers=hdr(5002)).json()["by_weekday"])
    assert after == before + 1


def test_fraud_signals(client):
    """AI #7 — firibgarlik: bitta xaridor→sotuvchiga ko'p buyurtma signal beradi; admin-only."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    for _ in range(6):
        db.create_order(buyer_id, sid, client.pid, 1, 1000)
    d = client.get("/api/admin/fraud", headers=hdr(5003)).json()
    assert any(x["buyer_id"] == buyer_id and x["seller_id"] == sid and x["cnt"] >= 6
               for x in d["order_farming"])
    # oddiy sotuvchi ko'ra olmaydi
    assert client.get("/api/admin/fraud", headers=hdr(5002)).status_code == 403


def test_price_insight(client):
    """AI #2 — raqobatchi narx maslahati: kategoriya o'rtachasiga nisbatan baho."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.update_user(sid, is_approved=1)
    cid = db.get_all_categories()[0][0]
    db.update_product_fields(client.pid, category_id=cid)   # narxi 1000
    # boshqa sotuvchi shu kategoriyada arzon mahsulot (raqobatchi)
    s2 = db.create_user(telegram_id=5009, phone_number="998900000009", name="S2", role="seller")
    db.update_user(s2, is_approved=1)
    comp = db.create_product(seller_id=s2, name="Comp", price=500, category_id=cid, stock_count=5)
    db.update_product_fields(comp, in_stock=1, status="active")
    d = client.get(f"/api/seller/product/{client.pid}/price-insight", headers=hdr(5002)).json()
    assert d["available"] is True and d["count"] == 1 and d["avg"] == 500
    assert d["verdict"] == "expensive" and d["diff_pct"] == 100   # 1000 vs 500


def test_related_bought_together(client):
    """AI #10 — "bular bilan olishadi": shu mahsulotni olgan xaridor olgan boshqa mahsulot chiqadi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.update_user(sid, is_approved=1)
    other = db.create_product(seller_id=sid, name="Aksessuar", price=300, stock_count=5)
    db.update_product_fields(other, in_stock=1, status="active")
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    # bitta xaridor ikkalasini ham oldi → ular "birga olinadi"
    db.create_order(buyer_id, sid, client.pid, 1, 1000)
    db.create_order(buyer_id, sid, other, 1, 300)
    rel = client.get(f"/api/products/{client.pid}/related", headers=hdr(5003)).json()
    assert any(p["id"] == other for p in rel)
    assert all(p["id"] != client.pid for p in rel)   # o'zini tavsiya qilmaydi


def test_recommendations_for_you(client):
    """#1 — shaxsiy tavsiya: xarid qilingan kategoriyadagi boshqa (olinmagan) mahsulot chiqadi."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.update_user(sid, is_approved=1)
    cats = db.get_all_categories()
    assert cats, "kategoriyalar seed bo'lishi kerak"
    cid = cats[0][0]
    a = db.create_product(seller_id=sid, name="A", price=1000, category_id=cid, stock_count=5)
    db.update_product_fields(a, in_stock=1, status="active")
    b = db.create_product(seller_id=sid, name="B", price=2000, category_id=cid, stock_count=5)
    db.update_product_fields(b, in_stock=1, status="active")
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    db.create_order(buyer_id, sid, a, 1, 1000)   # A ni "sotib oldi"
    ids = [p["id"] for p in client.get("/api/discover", headers=hdr(5001)).json()["for_you"]]
    assert b in ids and a not in ids   # o'sha kategoriyadan B tavsiya, A (olingan) chiqmaydi


def test_discover_sections(client):
    """#15 — Kashfiyot: trend (buyurtmadan), chegirma (old_price), yaqin (hudud)."""
    db = webapp_server.db
    sid = db.get_product_by_id(client.pid)["seller_id"]
    db.update_user(sid, is_approved=1)   # kashfiyot faqat tasdiqlangan sotuvchi mahsulotini ko'rsatadi
    # chegirmali mahsulot
    dp = db.create_product(seller_id=sid, name="Chegirma mahsulot", price=800, stock_count=5)
    db.update_product_fields(dp, in_stock=1, status="active", old_price=1000)
    # asosiy mahsulotga buyurtma → trendga tushadi
    client.post("/api/order", headers=hdr(5001),
                json={"product_id": client.pid, "quantity": 1,
                      "delivery_type": "pickup", "payment_method": "cash"})
    d = client.get("/api/discover", headers=hdr(5001)).json()
    assert "trending" in d and "discounts" in d and "nearby" in d
    assert any(p["id"] == client.pid for p in d["trending"]), "buyurtma qilingan mahsulot trendda"
    assert any(p["id"] == dp for p in d["discounts"]), "chegirmali mahsulot chegirmalarda"


def test_me_pending_counts(client):
    """#23 — kutilayotgan ishlar: bo'sh holatda 0; pending buyurtma sotuvchida ko'rinadi."""
    db = webapp_server.db
    # boshda hech kimda kutilayotgan ish yo'q
    assert client.get("/api/me/pending", headers=hdr(5002)).json()["total"] == 0
    # xaridor buyurtma beradi → sotuvchida 'pending' (tasdiqlash kutadi)
    client.post("/api/order", headers=hdr(5001),
                json={"product_id": client.pid, "quantity": 1,
                      "delivery_type": "pickup", "payment_method": "cash"})
    d = client.get("/api/me/pending", headers=hdr(5002)).json()
    assert d["total"] >= 1
    assert any(i["key"] == "seller_confirm" and i["tab"] == "seller" for i in d["items"])
    # admin uchun ham endpoint ishlaydi (xato bermaydi)
    assert client.get("/api/me/pending", headers=hdr(5003)).status_code == 200


def test_backup_admin_grant_and_revoke(client):
    """#21 — admin boshqa foydalanuvchini admin qiladi va keyin huquqni qaytarib oladi."""
    db = webapp_server.db
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    # admin (5003) buyerni admin qiladi
    assert client.post(f"/api/admin/user/{buyer_id}/grant-admin", headers=hdr(5003)).status_code == 200
    assert db.get_user_by_id(buyer_id)["role"] == "admin"
    # ro'yxatda ko'rinadi
    admins = client.get("/api/admin/admins", headers=hdr(5003)).json()["admins"]
    assert any(a["id"] == buyer_id for a in admins)
    # qayta admin qilish → 409
    assert client.post(f"/api/admin/user/{buyer_id}/grant-admin", headers=hdr(5003)).status_code == 409
    # huquqni olib tashlash → buyerga qaytadi (do'koni yo'q)
    r = client.post(f"/api/admin/user/{buyer_id}/revoke-admin", headers=hdr(5003))
    assert r.status_code == 200 and r.json()["role"] == "buyer"
    assert db.get_user_by_id(buyer_id)["role"] == "buyer"


def test_backup_admin_guards(client):
    """Zahira admin himoyalari: non-admin yo'q; o'zini olib tashlay olmaydi; asosiy himoyalangan."""
    db = webapp_server.db
    admin_id = db.get_user_by_telegram_id(5003)["id"]
    seller_id = db.get_user_by_telegram_id(5002)["id"]
    # non-admin grant qila olmaydi
    assert client.post(f"/api/admin/user/{seller_id}/grant-admin", headers=hdr(5001)).status_code == 403
    # admin o'zini revoke qila olmaydi
    assert client.post(f"/api/admin/user/{admin_id}/revoke-admin", headers=hdr(5003)).status_code == 400
    # asosiy admin (ADMIN_ID) himoyalangan
    import webapp_server as ws
    old = ws.ADMIN_ID
    ws.ADMIN_ID = 5003   # 5003 ni asosiy admin qilamiz
    try:
        assert client.post(f"/api/admin/user/{admin_id}/revoke-admin", headers=hdr(5003)).status_code in (400, 403)
    finally:
        ws.ADMIN_ID = old


def test_monetization_default_all_off(client):
    """#22 — monetizatsiya default barcha BAYROQ o'chiq (foydalanuvchiga bepul)."""
    cfg = client.get("/api/admin/monetization", headers=hdr(5003)).json()
    assert cfg["mon_enabled"] is False
    # Barcha *_enabled bayroqlari o'chiq, narxlar 0 (muddat/limit kabi sozlamalar bundan mustasno)
    for k, v in cfg.items():
        if k.endswith("_enabled") or k.endswith("_price") or k.endswith("_percent"):
            assert v in (False, 0, 0.0), k
    # /api/me public bayroqlari ham o'chiq
    mon = client.get("/api/me", headers=hdr(5001)).json()["monetization"]
    assert mon["enabled"] is False and mon["commission"] is False
    assert mon["boost"] is False and mon["subscription"] is False


def test_monetization_admin_only(client):
    """Faqat admin o'qiy/yoza oladi."""
    assert client.get("/api/admin/monetization", headers=hdr(5001)).status_code == 403
    assert client.post("/api/admin/monetization", headers=hdr(5002),
                       json={"mon_enabled": True}).status_code == 403


def test_monetization_toggle_and_validate(client):
    """Admin yoqadi; foiz 0..100 tekshiriladi; partial update ishlaydi."""
    r = client.post("/api/admin/monetization", headers=hdr(5003),
                    json={"mon_enabled": True, "mon_commission_enabled": True,
                          "mon_commission_percent": 5})
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["mon_enabled"] is True and cfg["mon_commission_percent"] == 5.0
    # me public endi yoqilgan deb ko'rsatadi
    mon = client.get("/api/me", headers=hdr(5001)).json()["monetization"]
    assert mon["enabled"] is True and mon["commission"] is True and mon["commission_percent"] == 5.0
    # 100 dan katta foiz → 400
    assert client.post("/api/admin/monetization", headers=hdr(5003),
                       json={"mon_commission_percent": 150}).status_code == 400
    # manfiy narx → 400
    assert client.post("/api/admin/monetization", headers=hdr(5003),
                       json={"mon_boost_price": -10}).status_code == 400


# ===== #18 BOOST / OBUNA / KOMISSIYA / TO'LOV =====
def _enable_mon(client, **flags):
    body = {"mon_enabled": True}
    body.update(flags)
    assert client.post("/api/admin/monetization", headers=hdr(5003), json=body).status_code == 200


def test_boost_disabled_403(client):
    """Bayroq o'chiq bo'lsa boost 403."""
    assert client.post(f"/api/seller/boost/{client.pid}", headers=hdr(5002)).status_code == 403


def test_boost_flow_dev_confirm_and_ordering(client):
    """Boost yoqilgan: to'lov yaratiladi, dev-confirm bilan tasdiqlanadi va mahsulot tepaga chiqadi."""
    db = webapp_server.db
    _enable_mon(client, mon_boost_enabled=True, mon_boost_price=5000, mon_boost_days=7)
    # boshqa (boostsiz) yangiroq mahsulot — boostsiz holatda u oldinda turishi mumkin
    s = db.get_user_by_telegram_id(5002)["id"]
    db.update_user(s, is_approved=1)   # search_products faqat tasdiqlangan sotuvchini ko'rsatadi
    other = db.create_product(seller_id=s, name="Boshqa mahsulot", price=2000, stock_count=5)
    db.update_product_fields(other, in_stock=1, status="active")
    # to'lov boshlash
    r = client.post(f"/api/seller/boost/{client.pid}", headers=hdr(5002))
    assert r.status_code == 200, r.text
    pay_id = r.json()["payment_id"]
    assert r.json()["amount"] == 5000
    # oddiy sotuvchiga dev_confirm berilmaydi (faqat admin)
    assert r.json().get("dev_confirm") is None
    # qo'lda tasdiqlash FAQAT admin (5003)
    assert client.post(f"/api/pay/dev-confirm/{pay_id}", headers=hdr(5002)).status_code == 403
    assert client.post(f"/api/pay/dev-confirm/{pay_id}", headers=hdr(5003)).status_code == 200
    prod = db.get_product_by_id(client.pid)
    assert prod["boosted_until"] is not None
    # qidiruvda boost qilingani tepada
    rows = db.search_products(sort_by="newest")
    ids = [p["id"] for p in rows]
    assert ids[0] == client.pid


def test_subscribe_pro_and_free_limit(client):
    """Obuna yoqilib bepul limit 1 bo'lsa: 2-mahsulot 403; Pro olgach — ruxsat."""
    db = webapp_server.db
    _enable_mon(client, mon_subscription_enabled=True, mon_subscription_price=20000,
                mon_subscription_days=30, mon_free_product_limit=1)
    # fixture'da 1 ta faol mahsulot bor → limit (1) ga yetgan
    r = client.post("/api/seller/product", headers=hdr(5002), json={"name": "Ikkinchi", "price": 3000})
    assert r.status_code == 403 and r.json()["detail"] == "free_limit_reached"
    # Pro obuna ol → admin dev-confirm bilan tasdiqlaydi (egasi 5002 uchun faollashadi)
    sub = client.post("/api/seller/subscribe", headers=hdr(5002)).json()
    assert client.post(f"/api/pay/dev-confirm/{sub['payment_id']}", headers=hdr(5003)).status_code == 200
    me = client.get("/api/me", headers=hdr(5002)).json()
    assert me["pro"]["active"] is True
    # endi mahsulot qo'shsa bo'ladi
    assert client.post("/api/seller/product", headers=hdr(5002),
                       json={"name": "Ikkinchi", "price": 3000}).status_code == 200


def test_commission_accrued_on_delivery(client):
    """Komissiya yoqilgan: yetkazilganda orders.commission_amount yoziladi + sotuvchiga ko'rinadi."""
    db = webapp_server.db
    _enable_mon(client, mon_commission_enabled=True, mon_commission_percent=10)
    owner_id = db.get_user_by_telegram_id(5002)["id"]
    buyer_id = db.get_user_by_telegram_id(5001)["id"]
    oid = db.create_order(buyer_id, owner_id, client.pid, 1, 1000)
    db.transition_order_status(oid, "confirmed", "pending")
    r = client.post(f"/api/seller/order/{oid}/deliver", headers=hdr(5002),
                    json={"settlement_type": "paid", "paid": 1000})
    assert r.status_code == 200, r.text
    assert db.get_commission_owed_by_seller(owner_id) == 100.0   # 1000*10%
    me = client.get("/api/me", headers=hdr(5002)).json()
    assert me["commission_owed"] == 100.0


def test_payme_webhook_perform(client, monkeypatch):
    """Payme JSON-RPC: auth → Check → Create → Perform; PerformTransaction maqsadni bajaradi."""
    import base64 as _b64
    monkeypatch.setattr(webapp_server, "PAYME_MERCHANT_ID", "M1")
    monkeypatch.setattr(webapp_server, "PAYME_KEY", "secretkey")
    _enable_mon(client, mon_subscription_enabled=True, mon_subscription_price=20000,
                mon_pay_payme_enabled=True)
    db = webapp_server.db
    sub = client.post("/api/seller/subscribe", headers=hdr(5002)).json()
    pid = sub["payment_id"]
    auth = "Basic " + _b64.b64encode(b"Paycom:secretkey").decode()
    tiyin = 20000 * 100
    # noto'g'ri auth → -32504
    bad = client.post("/api/pay/payme", json={"id": 1, "method": "CheckPerformTransaction",
                      "params": {"amount": tiyin, "account": {"payment_id": pid}}})
    assert bad.json()["error"]["code"] == -32504
    h = {"Authorization": auth}
    chk = client.post("/api/pay/payme", headers=h, json={"id": 1, "method": "CheckPerformTransaction",
                      "params": {"amount": tiyin, "account": {"payment_id": pid}}})
    assert chk.json()["result"]["allow"] is True
    cr = client.post("/api/pay/payme", headers=h, json={"id": 2, "method": "CreateTransaction",
                     "params": {"id": "TXN1", "time": 1700000000000, "amount": tiyin,
                                "account": {"payment_id": pid}}})
    assert cr.json()["result"]["state"] == 1
    pf = client.post("/api/pay/payme", headers=h, json={"id": 3, "method": "PerformTransaction",
                     "params": {"id": "TXN1"}})
    assert pf.json()["result"]["state"] == 2
    # maqsad bajarildi: Pro faollashdi
    assert db.get_payment(pid)["state"] == "paid"
    me = client.get("/api/me", headers=hdr(5002)).json()
    assert me["pro"]["active"] is True
    # idempotent: qayta Perform → yana state 2, xato yo'q
    pf2 = client.post("/api/pay/payme", headers=h, json={"id": 4, "method": "PerformTransaction",
                      "params": {"id": "TXN1"}})
    assert pf2.json()["result"]["state"] == 2


def test_paynet_webhook_perform(client, monkeypatch):
    """Paynet JSON-RPC: auth (LOGIN:PASSWORD) → Create → Perform maqsadni bajaradi."""
    import base64 as _b64
    monkeypatch.setattr(webapp_server, "PAYNET_MERCHANT_ID", "PM1")
    monkeypatch.setattr(webapp_server, "PAYNET_LOGIN", "login1")
    monkeypatch.setattr(webapp_server, "PAYNET_PASSWORD", "pass1")
    _enable_mon(client, mon_subscription_enabled=True, mon_subscription_price=20000,
                mon_pay_paynet_enabled=True)
    db = webapp_server.db
    sub = client.post("/api/seller/subscribe", headers=hdr(5002)).json()
    pid = sub["payment_id"]
    tiyin = 20000 * 100
    auth = "Basic " + _b64.b64encode(b"login1:pass1").decode()
    # noto'g'ri auth → -32504
    assert client.post("/api/pay/paynet", json={"id": 1, "method": "CheckPerformTransaction",
                       "params": {"amount": tiyin, "account": {"payment_id": pid}}}
                       ).json()["error"]["code"] == -32504
    h = {"Authorization": auth}
    cr = client.post("/api/pay/paynet", headers=h, json={"id": 2, "method": "CreateTransaction",
                     "params": {"id": "PN1", "time": 1700000000000, "amount": tiyin,
                                "account": {"payment_id": pid}}})
    assert cr.json()["result"]["state"] == 1
    pf = client.post("/api/pay/paynet", headers=h, json={"id": 3, "method": "PerformTransaction",
                     "params": {"id": "PN1"}})
    assert pf.json()["result"]["state"] == 2
    assert db.get_payment(pid)["state"] == "paid"
    assert client.get("/api/me", headers=hdr(5002)).json()["pro"]["active"] is True


def test_dev_confirm_not_allowed_for_stranger(client):
    """Begona foydalanuvchi boshqaning to'lovini tasdiqlay olmaydi (admin emas)."""
    _enable_mon(client, mon_subscription_enabled=True, mon_subscription_price=1000)
    sub = client.post("/api/seller/subscribe", headers=hdr(5002)).json()
    # 5001 (buyer) — na admin, na ega
    assert client.post(f"/api/pay/dev-confirm/{sub['payment_id']}", headers=hdr(5001)).status_code == 403


# ===== ADMIN paneli (faqat admin rolli foydalanuvchi) =====
def test_admin_stats_requires_auth(client):
    assert client.get("/api/admin/stats").status_code == 401


def test_admin_stats_buyer_403(client):
    assert client.get("/api/admin/stats", headers=hdr(5001)).status_code == 403


def test_admin_stats_seller_403(client):
    assert client.get("/api/admin/stats", headers=hdr(5002)).status_code == 403


def test_admin_stats_admin_200(client):
    r = client.get("/api/admin/stats", headers=hdr(5003))
    assert r.status_code == 200 and "total_users" in r.json()


def test_admin_users_admin_200(client):
    r = client.get("/api/admin/users", headers=hdr(5003))
    assert r.status_code == 200 and isinstance(r.json()["users"], list)


def test_admin_seller_requests_admin_200(client):
    assert client.get("/api/admin/seller-requests", headers=hdr(5003)).status_code == 200


def test_admin_disputes_admin_200(client):
    assert client.get("/api/admin/disputes", headers=hdr(5003)).status_code == 200


def test_admin_block_buyer_by_admin_200(client):
    s5001 = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.post(f"/api/admin/user/{s5001}/block", headers=hdr(5003),
                    json={"block": True})
    assert r.status_code == 200 and r.json()["is_blocked"] == 1


def test_admin_cant_block_admin_400(client):
    a = webapp_server.db.get_user_by_telegram_id(5003)["id"]
    r = client.post(f"/api/admin/user/{a}/block", headers=hdr(5003), json={"block": True})
    assert r.status_code == 400


def test_admin_broadcast_empty_400(client):
    r = client.post("/api/admin/broadcast", headers=hdr(5003), json={"text": ""})
    assert r.status_code == 400


def test_admin_broadcast_plain_text_and_app_banner(client, monkeypatch):
    """Matn parse_mode'siz oddiy yuborilsin (apostrof &#x27; ga aylanmasin) va
    HAMMA foydalanuvchi app-banner xabarnomasini olsin (push xato bo'lsa ham)."""
    sent_payloads = []

    async def _fake(method, payload):
        sent_payloads.append(payload)
        return {"ok": True}

    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    text = "TezBozor yangilandi — bozor cho'ntagingizda!"
    r = client.post("/api/admin/broadcast", headers=hdr(5003), json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # App-banner hammaga (push muvaffaqiyatidan qat'i nazar)
    assert data["app_notified"] >= data["sent"] >= 1
    # Matn AYNAN yuborilsin — html.escape yo'q, parse_mode yo'q
    assert any(p.get("text") == text for p in sent_payloads)
    assert all("parse_mode" not in p for p in sent_payloads)
    assert all("&#x27;" not in (p.get("text") or "") for p in sent_payloads)
    # Qabul qiluvchida app-banner notification yaratilganini tasdiqlash
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    notifs = webapp_server.db.get_user_notifications(sid)
    assert any(text in (n.get("body") or "") for n in notifs)


def test_admin_seller_request_decide_by_seller_403(client):
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.post(f"/api/admin/seller-request/{sid}", headers=hdr(5002),
                    json={"approve": True})
    assert r.status_code == 403


# ===== XARIDOR nizo oqimi (bekor so'rash / javob) =====
def _confirmed_order(client):
    """Tasdiqlangan buyurtma yaratadi (buyer 5001, seller 5002)."""
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    webapp_server.db.update_order_status(oid, "confirmed")
    return oid


def test_admin_force_cancel_restocks_confirmed(client):
    """Bug B: admin 'confirmed' buyurtmani majburan bekor qilsa, zahira QAYTADI
    (avval restock yo'q edi → zahira butunlay yo'qolardi)."""
    db = webapp_server.db
    db.create_shop(db.get_user_by_telegram_id(5002)["id"])
    stock0 = db.get_product_by_id(client.pid)["stock_count"]
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    client.post(f"/api/seller/order/{oid}/action", headers=hdr(5002), json={"action": "confirm"})
    assert db.get_product_by_id(client.pid)["stock_count"] == stock0 - 1   # tasdiqда kamaydi
    r = client.post(f"/api/admin/order/{oid}/force-cancel", headers=hdr(5003))
    assert r.status_code == 200, r.text
    assert db.get_order_by_id(oid)["status"] == "cancelled"
    assert db.get_product_by_id(client.pid)["stock_count"] == stock0       # zahira qaytdi


def test_buyer_cancel_after_confirm_409(client):
    """Bug A (atomik): sotuvchi tasdiqlagandan keyin xaridorning eski bekori 'confirmed'ni
    bosib o'tkazmaydi — 409 oladi, status 'confirmed' qoladi."""
    db = webapp_server.db
    db.create_shop(db.get_user_by_telegram_id(5002)["id"])
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    client.post(f"/api/seller/order/{oid}/action", headers=hdr(5002), json={"action": "confirm"})
    r = client.post(f"/api/order/{oid}/cancel", headers=hdr(5001))
    assert r.status_code == 409
    assert db.get_order_by_id(oid)["status"] == "confirmed"


def test_deliver_atomic_guard_no_double(client):
    """ATOMIK: tasdiqlangan buyurtmani ikki marta berib bo'lmaydi (2-si 409). Bot
    settlement oqimi bilan poygadan himoya — qarama-qarshi to'lov holatining oldini oladi."""
    db = webapp_server.db
    db.create_shop(db.get_user_by_telegram_id(5002)["id"])
    oid = _confirmed_order(client)
    r1 = client.post(f"/api/seller/order/{oid}/deliver", headers=hdr(5002),
                     json={"settlement_type": "paid", "paid": 1000})
    assert r1.status_code == 200, r1.text
    assert db.get_order_by_id(oid)["status"] == "delivered"
    # takror berish (boshqa to'lov holati bilan) → 409, 1-chi holat saqlanadi
    r2 = client.post(f"/api/seller/order/{oid}/deliver", headers=hdr(5002),
                     json={"settlement_type": "debt", "paid": 0})
    assert r2.status_code == 409
    assert db.get_order_by_id(oid)["settlement_type"] == "paid"


def test_request_cancel_on_pending_409(client):
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    r = client.post(f"/api/order/{oid}/request-cancel", headers=hdr(5001),
                    json={"reason": "x"})
    assert r.status_code == 409  # faqat confirmed uchun


def test_request_cancel_confirmed_200(client):
    oid = _confirmed_order(client)
    r = client.post(f"/api/order/{oid}/request-cancel", headers=hdr(5001),
                    json={"reason": "fikrim o'zgardi"})
    assert r.status_code == 200
    assert webapp_server.db.get_order_by_id(oid)["cancel_state"] == "requested"


def test_request_cancel_not_owner_403(client):
    oid = _confirmed_order(client)
    r = client.post(f"/api/order/{oid}/request-cancel", headers=hdr(5002),
                    json={"reason": "x"})
    assert r.status_code == 403


def test_cancel_respond_own_request_409(client):
    """Xaridor o'zi so'ragan bo'lsa, o'z so'roviga javob bera olmaydi."""
    oid = _confirmed_order(client)
    client.post(f"/api/order/{oid}/request-cancel", headers=hdr(5001), json={"reason": "x"})
    r = client.post(f"/api/order/{oid}/cancel-respond", headers=hdr(5001),
                    json={"agree": True})
    assert r.status_code == 409  # cancel_wait_other


def test_cancel_respond_agree_cancels(client):
    """Sotuvchi so'ragan -> xaridor rozi -> bekor."""
    oid = _confirmed_order(client)
    webapp_server.db.request_order_cancel(oid, "seller", "yo'q")
    r = client.post(f"/api/order/{oid}/cancel-respond", headers=hdr(5001),
                    json={"agree": True})
    assert r.status_code == 200
    assert webapp_server.db.get_order_by_id(oid)["status"] == "cancelled"


# ===== SOTUVCHI tomoni nizo/bekor (#2) =====
def test_seller_request_cancel_confirmed_200(client):
    """Sotuvchi tasdiqlangan buyurtmani bekor qilishni so'raydi."""
    oid = _confirmed_order(client)
    r = client.post(f"/api/seller/order/{oid}/request-cancel", headers=hdr(5002),
                    json={"reason": "zahira tugadi"})
    assert r.status_code == 200
    o = webapp_server.db.get_order_by_id(oid)
    assert o["cancel_state"] == "requested" and o["cancel_by"] == "seller"


def test_seller_request_cancel_not_owner_403(client):
    """Boshqa sotuvchi/xaridor bu buyurtmaga bekor so'rolmaydi."""
    oid = _confirmed_order(client)
    r = client.post(f"/api/seller/order/{oid}/request-cancel", headers=hdr(5001),
                    json={"reason": "x"})
    assert r.status_code == 403


def test_seller_request_cancel_on_pending_409(client):
    """Faqat confirmed buyurtma uchun."""
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    r = client.post(f"/api/seller/order/{oid}/request-cancel", headers=hdr(5002),
                    json={"reason": "x"})
    assert r.status_code == 409


def test_seller_cancel_respond_own_request_409(client):
    """Sotuvchi o'zi so'ragan bo'lsa, o'z so'roviga javob bera olmaydi."""
    oid = _confirmed_order(client)
    webapp_server.db.request_order_cancel(oid, "seller", "x")
    r = client.post(f"/api/seller/order/{oid}/cancel-respond", headers=hdr(5002),
                    json={"agree": True})
    assert r.status_code == 409  # cancel_wait_other


def test_seller_cancel_respond_agree_cancels(client):
    """Xaridor so'ragan -> sotuvchi rozi -> bekor."""
    oid = _confirmed_order(client)
    webapp_server.db.request_order_cancel(oid, "buyer", "fikrim o'zgardi")
    r = client.post(f"/api/seller/order/{oid}/cancel-respond", headers=hdr(5002),
                    json={"agree": True})
    assert r.status_code == 200
    assert webapp_server.db.get_order_by_id(oid)["status"] == "cancelled"


def test_seller_cancel_respond_deny_disputes(client):
    """Xaridor so'ragan -> sotuvchi rad -> nizo (disputed)."""
    oid = _confirmed_order(client)
    webapp_server.db.request_order_cancel(oid, "buyer", "x")
    r = client.post(f"/api/seller/order/{oid}/cancel-respond", headers=hdr(5002),
                    json={"agree": False})
    assert r.status_code == 200
    assert webapp_server.db.get_order_by_id(oid)["cancel_state"] == "disputed"


# ===== ADMIN CHALALARI (#6 kanallar, #7 do'kon mod, #8 o'chirilgan, #9 sozlamalar) =====
def test_admin_channels_buyer_403(client):
    assert client.get("/api/admin/channels", headers=hdr(5001)).status_code == 403


def test_admin_channels_admin_200(client):
    r = client.get("/api/admin/channels", headers=hdr(5003))
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_admin_deleted_products_admin_200(client):
    r = client.get("/api/admin/deleted-products", headers=hdr(5003))
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_admin_settings_admin_200(client):
    r = client.get("/api/admin/settings", headers=hdr(5003))
    assert r.status_code == 200 and "users" in r.json() and "orders" in r.json()


def test_admin_settings_seller_403(client):
    assert client.get("/api/admin/settings", headers=hdr(5002)).status_code == 403


def test_admin_clean_cancelled_admin_200(client):
    r = client.post("/api/admin/clean-cancelled", headers=hdr(5003))
    assert r.status_code == 200 and r.json()["deleted"] >= 0


def test_admin_shop_detail_404(client):
    assert client.get("/api/admin/shop/999999", headers=hdr(5003)).status_code == 404


def test_admin_shop_toggle_mod_flips(client):
    sid = webapp_server.db.create_shop(2, name="Do'kon", moderation="direct")
    r = client.post(f"/api/admin/shop/{sid}/toggle-mod", headers=hdr(5003))
    assert r.status_code == 200 and r.json()["moderation"] == "owner_approve"
    r2 = client.post(f"/api/admin/shop/{sid}/toggle-mod", headers=hdr(5003))
    assert r2.json()["moderation"] == "direct"


def test_admin_shop_detail_buyer_403(client):
    assert client.get("/api/admin/shop/1", headers=hdr(5001)).status_code == 403


# ===== #4 MENING SHARHLARIM =====
def test_my_reviews_requires_auth(client):
    assert client.get("/api/my/reviews").status_code == 401


def test_my_reviews_buyer_200(client):
    r = client.get("/api/my/reviews", headers=hdr(5001))
    assert r.status_code == 200 and isinstance(r.json(), list)


# ===== #5 KOD BILAN QO'SHILISH =====
def test_join_code_empty_400(client):
    r = client.post("/api/join-with-code", headers=hdr(5001), json={"code": ""})
    assert r.status_code == 400


def test_join_code_invalid_404(client):
    r = client.post("/api/join-with-code", headers=hdr(5001), json={"code": "NOPE12"})
    assert r.status_code == 404


def test_join_code_admin_409(client):
    sid = webapp_server.db.create_shop(2, name="Do'kon")
    code = webapp_server.db.create_invite(sid)
    r = client.post("/api/join-with-code", headers=hdr(5003), json={"code": code})
    assert r.status_code == 409  # admin_cannot_join


def test_join_code_success(client):
    """Yangi xaridor (6001) kod bilan xodim bo'ladi: role=seller, is_approved, staff qo'shiladi."""
    sid = webapp_server.db.create_shop(2, name="Do'kon")
    code = webapp_server.db.create_invite(sid)
    uid = webapp_server.db.create_user(telegram_id=6001, phone_number="998900000099",
                                       name="Newbie", role="buyer")
    r = client.post("/api/join-with-code", headers=hdr(6001), json={"code": code})
    assert r.status_code == 200
    u = dict(webapp_server.db.get_user_by_id(uid))
    assert u["role"] == "seller" and u["is_approved"]
    assert webapp_server.db.get_staff_by_user(uid) is not None
    # Kod ishlatilgan -> qayta urinish 404
    r2 = client.post("/api/join-with-code", headers=hdr(6001), json={"code": code})
    assert r2.status_code == 404


def test_staff_invite_info_valid(client):
    """2-bosqich: App start_param=staff_<kod> tasdiq ekrani uchun do'kon nomini oladi.
    Ro'yxatdan o'tmagan (DB'da yo'q) user ham ko'ra oladi — require_auth yetarli."""
    sid = webapp_server.db.create_shop(2, name="Mega Do'kon")
    code = webapp_server.db.create_invite(sid)
    r = client.get("/api/staff/invite-info", params={"code": code}, headers=hdr(7001))
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True and body["shop_name"] == "Mega Do'kon"


def test_staff_invite_info_invalid(client):
    r = client.get("/api/staff/invite-info", params={"code": "NOPE000000"}, headers=hdr(7002))
    assert r.status_code == 200 and r.json()["valid"] is False


def test_staff_invite_info_used(client):
    """Ishlatilgan kod -> valid=False (qayta qo'shilib bo'lmaydi)."""
    sid = webapp_server.db.create_shop(2, name="Do'kon")
    code = webapp_server.db.create_invite(sid)
    webapp_server.db.mark_invite_used(code, 999)
    r = client.get("/api/staff/invite-info", params={"code": code}, headers=hdr(7003))
    assert r.status_code == 200 and r.json()["valid"] is False


# ===== #3 XODIM STATISTIKASI / DETALI =====
def _shop_with_staff(client):
    """Seller(5002) egasi do'kon + xodim(6002) qo'shadi. (shop_id, staff_id, staff_uid)."""
    sid = webapp_server.db.create_shop(2, name="Do'kon")
    uid = webapp_server.db.create_user(telegram_id=6002, phone_number="998900000077",
                                       name="Xodim", role="seller")
    stid = webapp_server.db.add_staff(sid, uid, staff_role="staff", is_active=1)
    return sid, stid, uid


def test_staff_list_has_stats(client):
    _shop_with_staff(client)
    r = client.get("/api/seller/staff", headers=hdr(5002))
    assert r.status_code == 200
    st = r.json()["staff"]
    assert st and "revenue" in st[0] and "products_count" in st[0]


def test_staff_detail_200(client):
    _, stid, _ = _shop_with_staff(client)
    r = client.get(f"/api/seller/staff/{stid}", headers=hdr(5002))
    assert r.status_code == 200
    body = r.json()
    assert "stats" in body and "perms" in body
    assert set(body["perms"].keys()) == {"add", "conf", "price", "rev", "staff"}


def test_staff_detail_not_owner_403(client):
    _, stid, _ = _shop_with_staff(client)
    assert client.get(f"/api/seller/staff/{stid}", headers=hdr(5001)).status_code == 403


def test_staff_role_toggle(client):
    _, stid, _ = _shop_with_staff(client)
    r = client.post(f"/api/seller/staff/{stid}/role", headers=hdr(5002))
    assert r.status_code == 200 and r.json()["staff_role"] == "manager"
    r2 = client.post(f"/api/seller/staff/{stid}/role", headers=hdr(5002))
    assert r2.json()["staff_role"] == "staff"


def test_staff_dept_set(client):
    _, stid, _ = _shop_with_staff(client)
    r = client.post(f"/api/seller/staff/{stid}/dept", headers=hdr(5002),
                    json={"department": "Telefonlar"})
    assert r.status_code == 200 and r.json()["department"] == "Telefonlar"


def test_staff_perm_toggle(client):
    _, stid, _ = _shop_with_staff(client)
    # Ruxsatlar standart yoqilgan (DEFAULT 1) — toggle uni teskari qiladi
    r = client.post(f"/api/seller/staff/{stid}/perm", headers=hdr(5002),
                    json={"key": "add"})
    assert r.status_code == 200
    v1 = r.json()["value"]
    r2 = client.post(f"/api/seller/staff/{stid}/perm", headers=hdr(5002),
                     json={"key": "add"})
    assert r2.json()["value"] is (not v1)  # ikkinchi marta teskari
    # noma'lum kalit -> 400
    rb = client.post(f"/api/seller/staff/{stid}/perm", headers=hdr(5002),
                     json={"key": "bad"})
    assert rb.status_code == 400


def test_cancel_respond_deny_disputes(client):
    """Sotuvchi so'ragan -> xaridor rad -> nizo (disputed)."""
    oid = _confirmed_order(client)
    webapp_server.db.request_order_cancel(oid, "seller", "yo'q")
    r = client.post(f"/api/order/{oid}/cancel-respond", headers=hdr(5001),
                    json={"agree": False})
    assert r.status_code == 200
    assert webapp_server.db.get_order_by_id(oid)["cancel_state"] == "disputed"


# ===== SOTUVCHI mijozlar ekrani =====
def test_seller_customers_requires_auth(client):
    assert client.get("/api/seller/customers").status_code == 401


def test_seller_customers_lists_buyer(client):
    """Xaridor buyurtma bergach, sotuvchi mijozlar ro'yxatida ko'rinadi."""
    client.post("/api/order", headers=hdr(5001),
                json={"product_id": client.pid, "quantity": 1,
                      "delivery_type": "pickup", "payment_method": "cash"})
    r = client.get("/api/seller/customers", headers=hdr(5002))
    assert r.status_code == 200
    rows = r.json()
    assert any(c["name"] == "Buyer" and c["orders_count"] >= 1 for c in rows)


# ===== App ichida ro'yxatdan o'tish =====
def test_register_requires_auth(client):
    assert client.post("/api/register", json={"name": "X", "phone": "998901112233"}).status_code == 401


def test_me_unregistered_403_then_register_200(client):
    # Yangi tg_id — avval ro'yxatda yo'q
    assert client.get("/api/me", headers=hdr(6001)).status_code == 403
    r = client.post("/api/register", headers=hdr(6001),
                    json={"name": "Yangi Xaridor", "phone": "901234567", "language": "uz"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # Endi ro'yxatda — /api/me ishlaydi, telefon normallashgan
    me = client.get("/api/me", headers=hdr(6001))
    assert me.status_code == 200 and me.json()["phone"] == "+998901234567"


def test_register_bad_phone_400(client):
    r = client.post("/api/register", headers=hdr(6002),
                    json={"name": "Test User", "phone": "123"})
    assert r.status_code == 400


def test_register_idempotent_for_existing(client):
    # Mavjud foydalanuvchi (5001) — qayta yaratilmaydi, ok qaytaradi
    r = client.post("/api/register", headers=hdr(5001),
                    json={"name": "X", "phone": "998901112233"})
    assert r.status_code == 200 and r.json().get("already") is True


def test_register_with_referral_applies(client):
    """Mini App ro'yxati ?ref=<kod> bilan kelsa — referral bog'lanadi va hisob oshadi
    (bot /start REF... parite)."""
    db = webapp_server.db
    referrer_id = db.get_user_by_telegram_id(5002)["id"]
    db.update_user(referrer_id, referral_code="TESTREF1", referral_count=0)
    r = client.post("/api/register", headers=hdr(6010),
                    json={"name": "Referral Test", "phone": "901112233",
                          "language": "uz", "ref": "TESTREF1"})
    assert r.status_code == 200 and r.json()["ok"] is True
    new_uid = r.json()["id"]
    assert db.get_user_by_id(new_uid)["referred_by"] == referrer_id
    assert db.get_user_by_id(referrer_id)["referral_count"] == 1


# ===== REKLAMA generatori (preview + hozir e'lon qilish) =====
def test_ad_preview_requires_auth(client):
    assert client.get(f"/api/seller/product/{client.pid}/ad-preview").status_code == 401


def test_ad_preview_not_owner_403(client):
    # Xaridor (5001) sotuvchining mahsuloti reklamasini ko'ra olmaydi
    r = client.get(f"/api/seller/product/{client.pid}/ad-preview", headers=hdr(5001))
    assert r.status_code == 403


def test_ad_preview_owner_200(client, monkeypatch):
    # AI'ni o'chiramiz -> tuzilgan HTML fallback matn (deterministik, tarmoqsiz)
    async def _no_ai(**kw):
        return None
    monkeypatch.setattr(webapp_server.ai_assistant, "generate_ad_caption", _no_ai)
    r = client.get(f"/api/seller/product/{client.pid}/ad-preview", headers=hdr(5002))
    assert r.status_code == 200
    body = r.json()
    assert body["caption"] and "Test mahsulot" in body["caption"]
    assert body["has_design"] is False  # test mahsulotda image_url yo'q


def test_ad_publish_not_owner_403(client):
    r = client.post(f"/api/seller/product/{client.pid}/ad-publish", headers=hdr(5001),
                    json={"caption": "x"})
    assert r.status_code == 403


def test_ad_publish_creates_scheduled_post(client):
    # Ega e'lon qiladi -> hozirgi vaqtga pending post (caption bilan, image_id=None)
    r = client.post(f"/api/seller/product/{client.pid}/ad-publish", headers=hdr(5002),
                    json={"caption": "Mening reklama matnim", "length": "long"})
    assert r.status_code == 200 and r.json()["ok"] is True
    pend = webapp_server.db.get_pending_scheduled_posts()
    assert any(p["product_id"] == client.pid and p["caption"] == "Mening reklama matnim"
               and p["image_id"] is None for p in pend)


# ===== Mahsulot savollari (atributlar) — 3 rejim =====
def test_product_questions_requires_auth(client):
    assert client.get("/api/seller/product-questions").status_code == 401


def test_product_questions_buyer_403(client):
    assert client.get("/api/seller/product-questions", headers=hdr(5001)).status_code == 403


def test_product_questions_classic_seller_200(client, monkeypatch):
    # AI'ni o'chiramiz -> har rejim klassikga qaytadi (deterministik, tarmoqsiz)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    r = client.get("/api/seller/product-questions?mode=ai_guided&name=Telefon",
                   headers=hdr(5002))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["questions"], list) and body["source"].startswith("classic")
    assert isinstance(body["known"], dict)


def test_create_product_with_attributes(client):
    r = client.post("/api/seller/product", headers=hdr(5002), json={
        "name": "Atributli mahsulot", "price": 2000,
        "attributes": [{"key": "color", "value": "Qora", "label": "Rang"},
                       {"key": "size", "value": "", "label": "O'lcham"}]})  # bo'sh -> tashlanadi
    assert r.status_code == 200
    pid = r.json()["product_id"]
    attrs = webapp_server.db.get_product_attributes(pid)
    by_key = {a["attr_key"]: a for a in attrs}
    assert by_key["color"]["attr_value"] == "Qora" and by_key["color"]["attr_label"] == "Rang"
    assert "size" not in by_key  # bo'sh qiymat saqlanmaydi


def test_edit_product_attributes_and_detail(client):
    # PATCH bilan atribut qo'shamiz, so'ng detail uni qaytaradi
    client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002),
                 json={"attributes": [{"key": "brand", "value": "Sony", "label": "Brend"}]})
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert any(a["attr_key"] == "brand" and a["attr_value"] == "Sony" for a in d["attributes"])


# ===== Hudud (region) filtri =====
def test_regions_requires_auth(client):
    assert client.get("/api/regions").status_code == 401


def test_regions_list_200(client):
    r = client.get("/api/regions", headers=hdr(5001))
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_shops_accepts_region_id(client):
    r = client.get("/api/shops?region_id=1", headers=hdr(5001))
    assert r.status_code == 200 and isinstance(r.json(), list)


# ===== Admin foydalanuvchi rol filtri =====
def test_admin_users_role_filter(client):
    r = client.get("/api/admin/users?role=seller", headers=hdr(5003))
    assert r.status_code == 200
    body = r.json()
    assert body.get("role") == "seller"
    assert all(u["role"] == "seller" for u in body["users"])


def test_admin_users_role_buyer_excludes_seller(client):
    r = client.get("/api/admin/users?role=buyer", headers=hdr(5003))
    assert r.status_code == 200
    assert all(u["role"] == "buyer" for u in r.json()["users"])


# ===== Foydalanuvchi to'liq ma'lumot + AI askfill + Excel =====
def test_admin_user_detail_200(client):
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.get(f"/api/admin/user/{sid}", headers=hdr(5003))
    assert r.status_code == 200
    b = r.json()
    assert b["id"] == sid and isinstance(b.get("missing"), list)


def test_admin_user_detail_not_admin_403(client):
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    assert client.get(f"/api/admin/user/{sid}", headers=hdr(5002)).status_code == 403


def test_admin_fill_preview_ai_off_503(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.get(f"/api/admin/user/{sid}/fill-preview", headers=hdr(5003))
    assert r.status_code == 503  # kamchilik bor, lekin AI o'chiq


def test_admin_sendfill_empty_400(client):
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.post(f"/api/admin/user/{sid}/sendfill", headers=hdr(5003), json={"message": ""})
    assert r.status_code == 400


def test_admin_sendfill_ok(client, monkeypatch):
    async def _fake(method, payload):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    sid = webapp_server.db.get_user_by_telegram_id(5001)["id"]
    r = client.post(f"/api/admin/user/{sid}/sendfill", headers=hdr(5003), json={"message": "Salom"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_admin_export_bad_kind_400(client):
    assert client.post("/api/admin/export/xxx", headers=hdr(5003)).status_code == 400


def test_admin_export_not_admin_403(client):
    assert client.post("/api/admin/export/users", headers=hdr(5002)).status_code == 403


# ===== Reklama ekrani: rejalashtirish caption + dizayn (image_id=None) =====
def test_schedule_with_caption_image_none(client):
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = client.post(f"/api/seller/product/{client.pid}/schedule", headers=hdr(5002),
                    json={"scheduled_at": future, "caption": "Mening matnim"})
    assert r.status_code == 200
    sp = [p for p in webapp_server.db.get_pending_scheduled_posts() if p["product_id"] == client.pid]
    assert sp and sp[-1]["caption"] == "Mening matnim" and sp[-1]["image_id"] is None


def test_autorepost_with_caption(client):
    r = client.post(f"/api/seller/product/{client.pid}/autorepost", headers=hdr(5002),
                    json={"hour": 9, "caption": "Avto matn"})
    assert r.status_code == 200 and r.json()["ok"] is True


# ===== Chegirma (old_price) + tez zahira + sotuvchi Excel =====
def test_create_product_with_old_price(client):
    r = client.post("/api/seller/product", headers=hdr(5002),
                    json={"name": "Chegirmali", "price": 8000, "old_price": 12000})
    assert r.status_code == 200
    pid = r.json()["product_id"]
    d = client.get(f"/api/products/{pid}", headers=hdr(5001)).json()
    assert float(d["old_price"]) == 12000


def test_edit_old_price_clear(client):
    client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"old_price": 5000})
    client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"old_price": 0})
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert not d.get("old_price")


def test_quick_stock_patch(client):
    r = client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"stock_count": 42})
    assert r.status_code == 200
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert d["stock_count"] == 42


def test_seller_export_bad_kind_400(client):
    assert client.post("/api/seller/export/xxx", headers=hdr(5002)).status_code == 400


def test_seller_export_buyer_403(client):
    assert client.post("/api/seller/export/orders", headers=hdr(5001)).status_code == 403


# ===== Sotuvchi qarz daftari + to'lov qabul =====
def test_seller_debts_requires_auth(client):
    assert client.get("/api/seller/debts").status_code == 401


def test_seller_debts_empty_ok(client):
    d = client.get("/api/seller/debts", headers=hdr(5002)).json()
    assert isinstance(d["debts"], list) and "total" in d


def test_seller_debt_pay_flow(client, monkeypatch):
    async def _fake(method, payload):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    monkeypatch.setattr(webapp_server, "_rate_limit", lambda *a, **k: None)  # full-suite 429 oldini oladi
    # qarzli (delivered) buyurtma yaratamiz
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    webapp_server.db.update_order_status(oid, "delivered")
    webapp_server.db.set_order_settlement(oid, "debt", 0, 1000)
    # ro'yxatda ko'rinadi
    d = client.get("/api/seller/debts", headers=hdr(5002)).json()
    assert d["total"] >= 1000
    # boshqa sotuvchi to'lay olmaydi
    assert client.post(f"/api/seller/debt/{oid}/pay", headers=hdr(5001),
                       json={"amount": 100}).status_code == 403
    # qisman
    r = client.post(f"/api/seller/debt/{oid}/pay", headers=hdr(5002), json={"amount": 400})
    assert r.status_code == 200 and r.json()["remaining"] == 600
    # qolganini (ortig'i cheklanadi)
    r2 = client.post(f"/api/seller/debt/{oid}/pay", headers=hdr(5002), json={"amount": 9999})
    assert r2.json()["remaining"] == 0
    # qarz yopilgan -> 409
    assert client.post(f"/api/seller/debt/{oid}/pay", headers=hdr(5002),
                       json={"amount": 50}).status_code == 409


# ===== Sotuvchi bo'lish — to'liq onboarding =====
def test_become_seller_requires_shop_name(client, monkeypatch):
    monkeypatch.setattr(webapp_server, "_rate_limit", lambda *a, **k: None)
    r = client.post("/api/become-seller", headers=hdr(5001), json={})
    assert r.status_code == 400


def test_become_seller_saves_shop_fields(client, monkeypatch):
    monkeypatch.setattr(webapp_server, "_rate_limit", lambda *a, **k: None)
    async def _fake(m, p):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    r = client.post("/api/become-seller", headers=hdr(5001),
                    json={"shop_name": "Test Do'kon", "shop_address": "Chilonzor 5",
                          "working_hours": "09:00-21:00"})
    assert r.status_code == 200
    u = dict(webapp_server.db.get_user_by_telegram_id(5001))
    assert u["shop_name"] == "Test Do'kon" and u["shop_address"] == "Chilonzor 5"
    req = webapp_server.db.get_seller_request_by_user(u["id"])
    assert req and dict(req)["status"] == "pending"


# ===== Xaridor «oldim» tasdig'i (pickup) =====
def test_confirm_pickup_flow(client, monkeypatch):
    monkeypatch.setattr(webapp_server, "_rate_limit", lambda *a, **k: None)
    async def _fake(m, p):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    # pending -> 409
    assert client.post(f"/api/order/{oid}/confirm-pickup", headers=hdr(5001)).status_code == 409
    webapp_server.db.update_order_status(oid, "confirmed")
    # not buyer -> 403
    assert client.post(f"/api/order/{oid}/confirm-pickup", headers=hdr(5002)).status_code == 403
    # buyer ok
    assert client.post(f"/api/order/{oid}/confirm-pickup", headers=hdr(5001)).status_code == 200
    assert dict(webapp_server.db.get_order_by_id(oid))["buyer_received"] == 1
    # qaytadan -> 409
    assert client.post(f"/api/order/{oid}/confirm-pickup", headers=hdr(5001)).status_code == 409


# ===== Admin chuqurligi: audit / force-cancel / verify =====
def test_admin_audit_buyer_403(client):
    assert client.get("/api/admin/audit", headers=hdr(5001)).status_code == 403


def test_admin_audit_admin_200(client):
    r = client.get("/api/admin/audit", headers=hdr(5003))
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_admin_force_cancel(client, monkeypatch):
    monkeypatch.setattr(webapp_server, "_rate_limit", lambda *a, **k: None)
    async def _f(m, p):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _f)
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    webapp_server.db.update_order_status(oid, "confirmed")
    assert client.post(f"/api/admin/order/{oid}/force-cancel", headers=hdr(5003)).status_code == 200
    assert dict(webapp_server.db.get_order_by_id(oid))["status"] == "cancelled"
    assert client.post(f"/api/admin/order/{oid}/force-cancel", headers=hdr(5003)).status_code == 409


def test_admin_verify_freeze_seller(client, monkeypatch):
    async def _f(m, p):
        return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _f)
    sid = dict(webapp_server.db.get_user_by_telegram_id(5002))["id"]
    webapp_server.db.update_user(sid, shop_name="Do'kon", is_approved=1)
    r = client.post(f"/api/admin/user/{sid}/verify", headers=hdr(5003))
    assert r.status_code == 200 and r.json()["is_approved"] == 0
    r2 = client.post(f"/api/admin/user/{sid}/verify", headers=hdr(5003))
    assert r2.json()["is_approved"] == 1


# ===== #5: cheksiz zahira (-1) + AI sharh-javob guard =====
def test_edit_stock_unlimited_sentinel(client):
    client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"stock_count": 5})
    client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5002), json={"stock_count": -1})
    d = client.get(f"/api/products/{client.pid}", headers=hdr(5001)).json()
    assert d["stock_count"] is None  # cheksiz


def test_review_ai_reply_requires_auth(client):
    assert client.get("/api/seller/review/1/ai-reply").status_code == 401


def test_review_ai_reply_not_owner_403(client):
    # mavjud bo'lmagan/begona sharh -> 403
    assert client.get("/api/seller/review/99999/ai-reply", headers=hdr(5002)).status_code == 403


# ===== AI 2-to'lqin: #9 sheva qidiruv, #4 reels, #6 sentiment =====
def test_ai_search_requires_auth(client):
    assert client.get("/api/products/ai-search?q=test").status_code == 401


def test_ai_search_disabled_returns_empty(client, monkeypatch):
    # AI o'chiq bo'lsa — xato emas, bo'sh natija (oddiy qidiruv fallback'i sifatida)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    r = client.get("/api/products/ai-search?q=chotki", headers=hdr(5001))
    assert r.status_code == 200
    assert r.json() == {"interpreted": "", "items": []}


def test_ai_search_interprets_and_finds(client, monkeypatch):
    # search_products faqat tasdiqlangan sotuvchi mahsulotini qaytaradi
    sid = dict(webapp_server.db.get_user_by_telegram_id(5002))["id"]
    webapp_server.db.update_user(sid, is_approved=1)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    async def _interp(query, categories=None, lang="uz"):
        return {"keywords": ["mahsulot"], "category": ""}
    monkeypatch.setattr(webapp_server.ai_assistant, "interpret_search_query", _interp)
    r = client.get("/api/products/ai-search?q=chotki mahsulot", headers=hdr(5001))
    assert r.status_code == 200
    d = r.json()
    assert d["interpreted"] == "mahsulot"
    assert any(it["id"] == client.pid for it in d["items"])  # "Test mahsulot" topiladi


def test_reels_requires_auth(client):
    assert client.get(f"/api/seller/product/{client.pid}/reels").status_code == 401


def test_reels_ai_disabled_503(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    assert client.get(f"/api/seller/product/{client.pid}/reels", headers=hdr(5002)).status_code == 503


def test_reels_not_owner_403(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    # xaridor (5001) — egasi emas
    assert client.get(f"/api/seller/product/{client.pid}/reels", headers=hdr(5001)).status_code == 403


def test_reels_owner_gets_script(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    async def _script(**kw):
        return "🎬 HOOK: zo'r mahsulot!"
    monkeypatch.setattr(webapp_server.ai_assistant, "generate_video_script", _script)
    r = client.get(f"/api/seller/product/{client.pid}/reels", headers=hdr(5002))
    assert r.status_code == 200 and "HOOK" in r.json()["script"]


def test_sentiment_admin_only(client):
    assert client.get("/api/admin/sentiment", headers=hdr(5001)).status_code == 403
    assert client.get("/api/admin/sentiment", headers=hdr(5002)).status_code == 403


def test_sentiment_no_reviews(client):
    r = client.get("/api/admin/sentiment", headers=hdr(5003))
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is False and j["reason"] == "no_reviews"


def test_sentiment_report(client, monkeypatch):
    # Izohli sharh yaratamiz: buyurtma -> delivered -> review
    d = webapp_server.db
    bid = dict(d.get_user_by_telegram_id(5001))["id"]
    sid = dict(d.get_user_by_telegram_id(5002))["id"]
    oid = d.create_order(buyer_id=bid, seller_id=sid, product_id=client.pid,
                         quantity=1, total_price=1000, delivery_type="pickup",
                         payment_method="cash")
    d.create_review(order_id=oid, seller_id=sid, buyer_id=bid, rating=2,
                    comment="Yetkazib berish juda sekin edi", product_rating=2)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    async def _an(reviews, lang="uz"):
        return {"summary": "Sekin yetkazish", "complaints": ["sekin yetkazish"],
                "praises": [], "suggestions": ["kuryer qo'shing"]}
    monkeypatch.setattr(webapp_server.ai_assistant, "analyze_sentiment", _an)
    r = client.get("/api/admin/sentiment", headers=hdr(5003))
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is True and j["total"] == 1 and j["low_count"] == 1
    assert "sekin yetkazish" in j["complaints"]


# ===== AI 3-to'lqin: #11 dinamik narx =====
def test_dynamic_price_requires_auth(client):
    assert client.get(f"/api/seller/product/{client.pid}/dynamic-price").status_code == 401


def test_dynamic_price_ai_disabled_503(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    assert client.get(f"/api/seller/product/{client.pid}/dynamic-price",
                      headers=hdr(5002)).status_code == 503


def test_dynamic_price_not_owner_403(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    assert client.get(f"/api/seller/product/{client.pid}/dynamic-price",
                      headers=hdr(5001)).status_code == 403


def test_dynamic_price_returns_advice(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    captured = {}
    async def _adv(**kw):
        captured.update(kw)
        return {"verdict": "lower", "suggested_price": 900, "change_pct": -10,
                "reason": "Uzoq turibdi", "confidence": "high"}
    monkeypatch.setattr(webapp_server.ai_assistant, "dynamic_price_advice", _adv)
    r = client.get(f"/api/seller/product/{client.pid}/dynamic-price", headers=hdr(5002))
    assert r.status_code == 200
    j = r.json()
    assert j["verdict"] == "lower" and j["suggested_price"] == 900
    assert j["current_price"] == 1000
    # AI'ga real signallar uzatildi (demand signals)
    assert "signals" in j and "days_listed" in captured["signals"]


def test_demand_signals_shape(client):
    s = webapp_server.db.get_product_demand_signals(client.pid)
    assert s is not None
    for k in ("price", "days_listed", "sold", "orders_total", "favorites", "stock_count"):
        assert k in s
    assert s["price"] == 1000 and s["stock_count"] == 5


# ===== #17 sovg'a yordamchisi + kuryer xaridor ma'lumotlari =====
def test_gift_requires_auth(client):
    assert client.post("/api/gift-assistant", json={"recipient": "onam"}).status_code == 401


def test_gift_ai_disabled_503(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: False)
    r = client.post("/api/gift-assistant", headers=hdr(5001), json={"recipient": "onam"})
    assert r.status_code == 503


def test_gift_empty_400(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    r = client.post("/api/gift-assistant", headers=hdr(5001), json={})
    assert r.status_code == 400


def test_gift_returns_ideas_with_products(client, monkeypatch):
    # mahsulot ko'rinishi uchun sotuvchi tasdiqlangan bo'lsin
    sid = dict(webapp_server.db.get_user_by_telegram_id(5002))["id"]
    webapp_server.db.update_user(sid, is_approved=1)
    monkeypatch.setattr(webapp_server.ai_assistant, "is_enabled", lambda: True)
    async def _gift(**kw):
        return {"intro": "Mana g'oyalar", "ideas": [
            {"title": "Sovg'a 1", "reason": "yaxshi", "keywords": ["mahsulot"]}]}
    monkeypatch.setattr(webapp_server.ai_assistant, "gift_advisor", _gift)
    r = client.post("/api/gift-assistant", headers=hdr(5001),
                    json={"recipient": "onam", "budget": 5000})
    assert r.status_code == 200
    j = r.json()
    assert j["intro"] == "Mana g'oyalar" and len(j["ideas"]) == 1
    assert any(p["id"] == client.pid for p in j["ideas"][0]["products"])


def test_courier_orders_expose_buyer_contact_and_location(client):
    """Kuryer xaridor lokatsiyasi + bog'lanish ma'lumotini ko'rishi uchun
    seller_orders_list buyer_username/buyer_tg + buyer_lat/lon qaytaradi."""
    d = webapp_server.db
    bid = dict(d.get_user_by_telegram_id(5001))["id"]
    sid = dict(d.get_user_by_telegram_id(5002))["id"]
    d.update_user(bid, telegram_username="buyer_un")
    oid = d.create_order(buyer_id=bid, seller_id=sid, product_id=client.pid,
                         quantity=1, total_price=1000, delivery_type="delivery",
                         payment_method="cash", delivery_address="Ko'cha 1",
                         buyer_lat=41.31, buyer_lon=69.24)
    rows = d.get_seller_orders_list(sid)
    o = next(r for r in rows if r["id"] == oid)
    assert o["buyer_username"] == "buyer_un"
    assert o["buyer_lat"] == 41.31 and o["buyer_lon"] == 69.24
    assert o["delivery_address"] == "Ko'cha 1"


def test_courier_buyer_chat(client):
    """#13 — biriktirilgan kuryer buyurtma chatida ishtirok etadi: xabar yozadi,
    o'qiydi; tracking esa xaridorga kuryer kontaktini qaytaradi."""
    d = webapp_server.db
    owner_id = d.get_user_by_telegram_id(5002)["id"]
    shop_id = d.create_shop(owner_id)
    cour = d.create_user(telegram_id=5051, phone_number="998900000051", name="Kuryer", role="seller")
    d.add_staff(shop_id, cour, staff_role="courier", is_active=1)
    buyer_id = d.get_user_by_telegram_id(5001)["id"]
    oid = d.create_order(buyer_id, owner_id, client.pid, 1, 1000,
                         delivery_address="Toshkent", delivery_type="delivery",
                         buyer_lat=41.31, buyer_lon=69.24)
    conn = d.get_connection(); conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,)); conn.commit()
    # biriktirishdan oldin — kuryer chatga kira olmaydi (ishtirokchi emas)
    assert client.get(f"/api/order/{oid}/messages", headers=hdr(5051)).status_code == 403
    # ega kuryerni biriktiradi
    assert client.post(f"/api/seller/order/{oid}/assign-courier", headers=hdr(5002),
                       json={"courier_id": cour}).status_code == 200
    # kuryer endi chatni ko'radi va xabar yozadi
    assert client.get(f"/api/order/{oid}/messages", headers=hdr(5051)).status_code == 200
    assert client.post(f"/api/order/{oid}/message", headers=hdr(5051),
                       json={"text": "Yo'ldaman, 10 daqiqada yetib boraman"}).status_code == 200
    # xaridor xabarni ko'radi va javob yozadi
    bm = client.get(f"/api/order/{oid}/messages", headers=hdr(5001)).json()
    assert any("Yo'ldaman" in m["message"] for m in bm["messages"])
    assert bm["counterparty"] == "Kuryer"   # suhbatdosh — kuryer
    assert client.post(f"/api/order/{oid}/message", headers=hdr(5001),
                       json={"text": "Kutyapman"}).status_code == 200
    cm = client.get(f"/api/order/{oid}/messages", headers=hdr(5051)).json()
    assert any("Kutyapman" in m["message"] for m in cm["messages"])
    # tracking — xaridorga kuryer kontakti ko'rinadi (telegram_id sizib chiqmaydi)
    trk = client.get(f"/api/order/{oid}/tracking", headers=hdr(5001)).json()
    assert trk["has_courier"] is True and trk["courier_name"] == "Kuryer"
    assert trk["courier_phone"] == "998900000051"
    assert "courier_tg" not in trk


# ===== Yetkazib berishda joylashuv MAJBURIY =====
def test_order_delivery_requires_location(client):
    # lat/lon'siz delivery -> 400 location_required
    r = client.post("/api/order", headers=hdr(5001),
                    json={"product_id": client.pid, "quantity": 1,
                          "delivery_type": "delivery", "address": "Toshkent",
                          "payment_method": "cash"})
    assert r.status_code == 400 and r.json()["detail"] == "location_required"


def test_order_delivery_with_location_ok(client):
    r = client.post("/api/order", headers=hdr(5001),
                    json={"product_id": client.pid, "quantity": 1,
                          "delivery_type": "delivery", "address": "Toshkent",
                          "lat": 41.31, "lon": 69.24, "payment_method": "cash"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_order_pickup_no_location_ok(client):
    # pickup'da joylashuv shart emas
    r = client.post("/api/order", headers=hdr(5001),
                    json={"product_id": client.pid, "quantity": 1,
                          "delivery_type": "pickup", "payment_method": "cash"})
    assert r.status_code == 200


def test_cart_delivery_requires_location(client):
    r = client.post("/api/cart/checkout", headers=hdr(5001),
                    json={"seller_id": dict(webapp_server.db.get_user_by_telegram_id(5002))["id"],
                          "items": [{"product_id": client.pid, "quantity": 1}],
                          "delivery_type": "delivery", "payment_method": "cash"})
    assert r.status_code == 400 and r.json()["detail"] == "location_required"


# ===== PRO/BOOST XABARLARI: (1) sotib olish boshlanganda tasdiq, (2) admin tasdiqlagach yakuniy =====
def test_subscribe_notifies_seller_pending(client, monkeypatch):
    """Sotuvchi 'Pro sotib olish' tugmasini bosganda — unga DARHOL 'so'rovingiz qabul
    qilindi, admin to'lov bo'yicha bog'lanadi' tasdig'i (app banner + Telegram push).
    Endpoint await bilan yuboradi → TestClient'da deterministik."""
    calls = []
    async def _fake(method, payload):
        calls.append((method, payload)); return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    _enable_mon(client, mon_subscription_enabled=True, mon_subscription_price=20000)
    r = client.post("/api/seller/subscribe", headers=hdr(5002))
    assert r.status_code == 200, r.text
    sid = webapp_server.db.get_user_by_telegram_id(5002)["id"]
    notifs = webapp_server.db.get_user_notifications(sid)
    assert any("qabul qilindi" in (n["title"] or "") for n in notifs), notifs
    # Sotuvchining o'ziga (chat_id=5002) Telegram push ketdi
    assert any(c[0] == "sendMessage" and c[1].get("chat_id") == 5002 for c in calls), calls


def test_boost_notifies_seller_pending(client, monkeypatch):
    """Boost 'sotib olish' bosilganda ham sotuvchiga tasdiq xabari yetadi."""
    calls = []
    async def _fake(method, payload):
        calls.append((method, payload)); return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    _enable_mon(client, mon_boost_enabled=True, mon_boost_price=5000, mon_boost_days=7)
    r = client.post(f"/api/seller/boost/{client.pid}", headers=hdr(5002))
    assert r.status_code == 200, r.text
    sid = webapp_server.db.get_user_by_telegram_id(5002)["id"]
    notifs = webapp_server.db.get_user_notifications(sid)
    assert any("qabul qilindi" in (n["title"] or "") for n in notifs), notifs
    assert any(c[0] == "sendMessage" and c[1].get("chat_id") == 5002 for c in calls), calls


@pytest.mark.parametrize("purpose", ["subscription", "boost"])
def test_payment_done_notifies_seller_final(client, monkeypatch, purpose):
    """Admin to'lovni tasdiqlagach (paid) sotuvchiga YAKUNIY 'faollashtirildi' xabari
    (app banner + Telegram push) yetadi. _notify_payment_done bevosita tekshiriladi —
    jonli (uvicorn) loop'da dev-confirm uni create_task bilan aynan shu funksiyani chaqiradi."""
    import asyncio
    db = webapp_server.db
    sid = db.get_user_by_telegram_id(5002)["id"]
    ref = client.pid if purpose == "boost" else None
    pid = db.create_payment(sid, purpose, 30000, ref_id=ref)
    db.set_payment_state(pid, "paid", provider="manual")
    payment = db.get_payment(pid)
    calls = []
    async def _fake(method, payload):
        calls.append((method, payload)); return {"ok": True}
    monkeypatch.setattr(webapp_server, "_tg_call", _fake)
    asyncio.run(webapp_server._notify_payment_done(payment))
    # App banner (DB) sotuvchiga yozildi
    assert any(n["kind"] == "payment" for n in db.get_user_notifications(sid)), purpose
    # Telegram push sotuvchining chat_id'siga ketdi
    assert any(c[0] == "sendMessage" and c[1].get("chat_id") == 5002 for c in calls), (purpose, calls)
