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


def test_edit_product_not_owner_403(client):
    r = client.patch(f"/api/seller/product/{client.pid}", headers=hdr(5001),
                     json={"price": 500})
    assert r.status_code == 403


def test_review_not_delivered_409(client):
    ro = client.post("/api/order", headers=hdr(5001),
                     json={"product_id": client.pid, "quantity": 1,
                           "delivery_type": "pickup", "payment_method": "cash"})
    oid = ro.json()["order_id"]
    r = client.post(f"/api/order/{oid}/review", headers=hdr(5001),
                    json={"seller_rating": 5})
    assert r.status_code == 409  # not_delivered


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
