"""End-to-end RUNTIME oqim testlari — haqiqiy webapp endpoint kodini TestClient bilan
jonli bosadi (real temp-SQLite, imzolangan initData). 2026-06-21 runtime auditidan
rasmiylashtirilgan: atomik guard, settlement, nizo, xodim, to'lov zanjiri, auth himoyasi.

Maqsad: "ulangan ≠ ishlaydi" — bu testlar XULQNI tasdiqlaydi, shunchaki route mavjudligini emas.
Har deployda avtomatik bosiladi → "soxta tugadi" regressiyasini ushlaydi."""
import json
import os
import time

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
os.environ.setdefault("DB_BACKEND", "sqlite")

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import webapp_auth  # noqa: E402
import webapp_server  # noqa: E402
from database import Database  # noqa: E402

TOKEN = os.environ["BOT_TOKEN"]


def hdr(tg_id):
    init = webapp_auth.build_init_data(TOKEN, {
        "user": json.dumps({"id": tg_id, "first_name": "U"}),
        "auth_date": str(int(time.time()))})
    return {"Authorization": "tma " + init}


def rows(j):
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ("items", "orders", "payments", "disputes", "debts", "reviews", "staff"):
            if isinstance(j.get(k), list):
                return j[k]
    return []


@pytest.fixture
def env(tmp_path, monkeypatch):
    """To'liq sozlangan, TASDIQLANGAN sotuvchi + do'kon + xaridor + admin + mahsulot.
    Telegram chaqiruvlari mock (tarmoqqa chiqmaydi)."""
    d = Database(db_path=str(tmp_path / "rt.db"))
    monkeypatch.setattr(webapp_server, "db", d)
    monkeypatch.setattr(webapp_server, "BOT_TOKEN", TOKEN)
    webapp_server._RATE.clear()

    async def _tg(method, payload, **kw):
        return {"ok": True, "result": {"message_id": 1}}
    monkeypatch.setattr(webapp_server, "_tg_call", _tg)
    if hasattr(webapp_server, "_tg_send_document"):
        async def _doc(*a, **k):
            return True
        monkeypatch.setattr(webapp_server, "_tg_send_document", _doc)

    seller = d.create_user(telegram_id=7002, phone_number="998900000002", name="Seller", role="seller")
    d.update_user(seller, is_approved=1, shop_name="Do'kon")
    admin = d.create_user(telegram_id=7003, phone_number="998900000003", name="Admin", role="admin")
    buyer = d.create_user(telegram_id=7001, phone_number="998900000001", name="Buyer", role="buyer")
    shop = d.create_shop(seller)
    pid = d.create_product(seller_id=seller, name="Mahsulot", price=10000, stock_count=5)
    d.update_product_fields(pid, in_stock=1, status="active")

    c = TestClient(webapp_server.app)
    c.db = d
    c.SELLER, c.ADMIN, c.BUYER, c.SHOP, c.PID = seller, admin, buyer, shop, pid
    return c


def _place_and_confirm(c, qty=2):
    r = c.post("/api/order", headers=hdr(7001), json={
        "product_id": c.PID, "quantity": qty, "delivery_type": "pickup", "payment_method": "cash"})
    assert r.status_code == 200, r.text
    oid = r.json()["order_id"]
    r = c.post(f"/api/seller/order/{oid}/action", headers=hdr(7002), json={"action": "confirm"})
    assert r.status_code == 200, r.text
    return oid


# ---------------- KATALOG / DETAL ----------------
def test_approved_seller_product_visible(env):
    r = env.get("/api/products", headers=hdr(7001))
    assert r.status_code == 200
    assert any(p.get("id") == env.PID for p in rows(r.json()))


def test_secret_min_price_never_exposed(env):
    r = env.get(f"/api/products/{env.PID}", headers=hdr(7001))
    assert r.status_code == 200 and "min_price" not in r.json()


# ---------------- BUYURTMA + TAYMER ----------------
def test_order_total_and_live_timer(env):
    r = env.post("/api/order", headers=hdr(7001), json={
        "product_id": env.PID, "quantity": 2, "delivery_type": "pickup", "payment_method": "cash"})
    assert r.status_code == 200 and r.json()["total"] == 20000
    oid = r.json()["order_id"]
    mo = rows(env.get("/api/my/orders", headers=hdr(7001)).json())
    o = next((x for x in mo if x.get("id") == oid), None)
    assert o and o.get("auto_cancel_at"), "jonli taymer uchun auto_cancel_at ko'rinishi shart"


# ---------------- ATOMIK GUARD (eng muhim) ----------------
def test_double_confirm_atomic_no_double_stock(env):
    r = env.post("/api/order", headers=hdr(7001), json={
        "product_id": env.PID, "quantity": 2, "delivery_type": "pickup", "payment_method": "cash"})
    oid = r.json()["order_id"]
    before = env.db.get_product_by_id(env.PID)["stock_count"]
    r1 = env.post(f"/api/seller/order/{oid}/action", headers=hdr(7002), json={"action": "confirm"})
    r2 = env.post(f"/api/seller/order/{oid}/action", headers=hdr(7002), json={"action": "confirm"})
    assert r1.status_code == 200 and r2.status_code == 409, "takroriy tasdiq 409 bo'lishi shart"
    after = env.db.get_product_by_id(env.PID)["stock_count"]
    assert before - after == 2, "zahira FAQAT bir marta kamayishi shart (poyga himoyasi)"


# ---------------- BERISH + QARZ ----------------
def test_deliver_with_debt_settlement(env):
    oid = _place_and_confirm(env, qty=2)
    r = env.post(f"/api/seller/order/{oid}/deliver", headers=hdr(7002),
                 json={"settlement_type": "debt", "paid": 5000})
    assert r.status_code == 200, r.text
    assert r.json()["due"] == 15000 and r.json()["paid"] == 5000
    assert env.db.get_order_by_id(oid)["status"] == "delivered"
    debts = rows(env.get("/api/my/debts", headers=hdr(7001)).json())
    assert any(float(x.get("total_due") or 0) >= 15000 for x in debts)


# ---------------- SHARH ----------------
def test_review_and_duplicate_block(env):
    oid = _place_and_confirm(env, qty=1)
    env.post(f"/api/seller/order/{oid}/deliver", headers=hdr(7002),
             json={"settlement_type": "paid", "paid": 10000})
    r = env.post(f"/api/order/{oid}/review", headers=hdr(7001),
                 json={"seller_rating": 5, "product_rating": 4, "comment": "Zo'r"})
    assert r.status_code == 200
    r2 = env.post(f"/api/order/{oid}/review", headers=hdr(7001), json={"seller_rating": 5})
    assert r2.status_code == 409, "takroriy sharh 409"
    assert len(rows(env.get("/api/my/reviews", headers=hdr(7001)).json())) >= 1


# ---------------- NIZO ----------------
def test_dispute_flow(env):
    oid = _place_and_confirm(env, qty=1)
    r = env.post(f"/api/seller/order/{oid}/request-cancel", headers=hdr(7002), json={"reason": "Tugadi"})
    assert r.status_code == 200
    assert env.db.get_order_by_id(oid)["cancel_state"] == "requested"
    r = env.post(f"/api/order/{oid}/cancel-respond", headers=hdr(7001), json={"agree": False})
    assert r.status_code == 200 and r.json().get("disputed") is True
    assert env.db.get_order_by_id(oid)["cancel_state"] == "disputed"
    # admin nizo ro'yxatida ko'rinadi
    dl = rows(env.get("/api/admin/disputes", headers=hdr(7003)).json())
    assert any(o.get("id") == oid for o in dl)


# ---------------- XODIM RUXSATLARI ----------------
def test_staff_invite_and_perm_toggle(env):
    r = env.post("/api/seller/staff/invite", headers=hdr(7002))
    assert r.status_code == 200 and r.json().get("code")
    staff_u = env.db.create_user(telegram_id=7004, phone_number="998900000004", name="Xodim", role="seller")
    sid = env.db.add_staff(shop_id=env.SHOP, user_id=staff_u, staff_role="staff")
    slist = rows(env.get("/api/seller/staff", headers=hdr(7002)).json())
    assert any(s.get("id") == sid for s in slist)
    d0 = env.get(f"/api/seller/staff/{sid}", headers=hdr(7002)).json()
    r = env.post(f"/api/seller/staff/{sid}/perm", headers=hdr(7002), json={"key": "price"})
    assert r.status_code == 200
    d1 = env.get(f"/api/seller/staff/{sid}", headers=hdr(7002)).json()
    assert json.dumps(d0) != json.dumps(d1), "ruxsat HAQIQATAN o'zgarishi shart"


# ---------------- MONETIZATSIYA (to'lov → fulfillment zanjiri) ----------------
def test_boost_payment_to_fulfillment_chain(env):
    # default o'chiq → 403
    assert env.post(f"/api/seller/boost/{env.PID}", headers=hdr(7002), json={}).status_code == 403
    # admin yoqadi
    env.post("/api/admin/monetization", headers=hdr(7003),
             json={"mon_enabled": True, "mon_boost_enabled": True, "mon_boost_price": 5000})
    r = env.post(f"/api/seller/boost/{env.PID}", headers=hdr(7002), json={})
    assert r.status_code == 200 and r.json().get("payment_id")
    pay_id = r.json()["payment_id"]
    # dev-confirm FAQAT admin (provayder yo'qda bepul-boost teshigini yopadi)
    assert env.post(f"/api/pay/dev-confirm/{pay_id}", headers=hdr(7002), json={}).status_code == 403
    assert env.post(f"/api/pay/dev-confirm/{pay_id}", headers=hdr(7003), json={}).status_code == 200
    assert env.db.get_payment(pay_id)["state"] == "paid"
    assert env.db.get_product_by_id(env.PID).get("boosted_until"), "to'langach boost qo'llanishi shart"


# ---------------- SOTUVCHI TO'LOVLAR TARIXI (yangi UI endpoint, 2026-06-21) ----------------
def test_seller_payments_history(env):
    env.post("/api/admin/monetization", headers=hdr(7003),
             json={"mon_enabled": True, "mon_boost_enabled": True, "mon_boost_price": 5000})
    r = env.post(f"/api/seller/boost/{env.PID}", headers=hdr(7002), json={})
    env.post(f"/api/pay/dev-confirm/{r.json()['payment_id']}", headers=hdr(7003), json={})
    r = env.get("/api/seller/payments", headers=hdr(7002))
    assert r.status_code == 200
    pays = rows(r.json())
    assert any(p.get("purpose") == "boost" and p.get("state") == "paid" for p in pays), \
        "sotuvchi to'lov tarixi boost to'lovini ko'rsatishi shart"


# ---------------- ADMIN KUTILAYOTGAN TO'LOVNI TASDIQLAYDI (2026-06-21) ----------------
def test_admin_sees_and_confirms_pending_payment(env):
    """Provayder ulanmaganda sotuvchining boost to'lovi 'pending' qoladi → admin
    /api/admin/payments'da ko'radi va dev-confirm bilan tasdiqlaydi → 'paid' bo'ladi."""
    env.post("/api/admin/monetization", headers=hdr(7003),
             json={"mon_enabled": True, "mon_boost_enabled": True, "mon_boost_price": 5000})
    r = env.post(f"/api/seller/boost/{env.PID}", headers=hdr(7002), json={})
    pay_id = r.json()["payment_id"]
    # admin pending ro'yxatida ko'rinadi (sotuvchi ismi bilan)
    pend = rows(env.get("/api/admin/payments?state=pending", headers=hdr(7003)).json())
    row = next((p for p in pend if p.get("id") == pay_id), None)
    assert row and row.get("state") == "pending" and row.get("user_name"), "admin pending to'lovni ko'rishi shart"
    # xaridor bu endpointga kira olmaydi
    assert env.get("/api/admin/payments", headers=hdr(7001)).status_code == 403
    # admin tasdiqlaydi
    assert env.post(f"/api/pay/dev-confirm/{pay_id}", headers=hdr(7003), json={}).status_code == 200
    # endi pending'da yo'q, paid'da bor
    pend2 = rows(env.get("/api/admin/payments?state=pending", headers=hdr(7003)).json())
    paid = rows(env.get("/api/admin/payments?state=paid", headers=hdr(7003)).json())
    assert not any(p.get("id") == pay_id for p in pend2), "tasdiqlangach pending'dan chiqishi shart"
    assert any(p.get("id") == pay_id for p in paid)


# ---------------- AUTH HIMOYASI ----------------
def test_auth_guards(env):
    assert env.get("/api/me").status_code == 401                      # imzosiz
    bad = {"Authorization": "tma user=%7B%22id%22%3A9%7D&hash=dead&auth_date=" + str(int(time.time()))}
    assert env.get("/api/me", headers=bad).status_code == 401         # soxta imzo
    assert env.get("/api/admin/stats", headers=hdr(7001)).status_code == 403   # xaridor→admin
