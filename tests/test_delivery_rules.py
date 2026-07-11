"""Yetkazib berish boshqaruvi testlari — mahsulot darajasidagi delivery_available
va do'kon darajasidagi delivery_min_total (yetkazish uchun minimal buyurtma summasi).

Qoidalar:
  • delivery_available=0 mahsulotga 'delivery' buyurtma 400 delivery_not_available;
  • do'kon delivery_min_total qo'ygan bo'lsa, jami summa yetmasa 400 delivery_min_<N>;
  • pickup bu qoidalarga bog'liq emas (har doim mumkin);
  • savat (cart) va variant-buyurtma ham xuddi shu himoyaga ega.
"""
import json
import os
import time

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
# MUHIM: webapp_server importi .env'ni yuklaydi (load_dotenv mavjud qiymatni bosmaydi).
# Bu fayl alifbo bo'yicha test_main_handlers'dan OLDIN turadi — ADMIN_ID/DB_BACKEND'ni
# oldindan test qiymatiga qotirib qo'yamiz, aks holda .env'dagi haqiqiy ADMIN_ID
# keyingi testlardagi setdefault("ADMIN_ID","1") ni buzadi.
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DB_BACKEND", "sqlite")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


@pytest.fixture
def env(tmp_path, monkeypatch):
    d = Database(db_path=str(tmp_path / "dlv.db"))
    monkeypatch.setattr(webapp_server, "db", d)
    monkeypatch.setattr(webapp_server, "BOT_TOKEN", TOKEN)
    webapp_server._RATE.clear()

    async def _tg(method, payload, **kw):
        return {"ok": True, "result": {"message_id": 1}}
    monkeypatch.setattr(webapp_server, "_tg_call", _tg)

    seller = d.create_user(telegram_id=8002, phone_number="998900000012", name="Seller", role="seller")
    d.update_user(seller, is_approved=1, shop_name="Dlv Do'kon")
    buyer = d.create_user(telegram_id=8001, phone_number="998900000011", name="Buyer", role="buyer")
    d.create_shop(seller)
    pid = d.create_product(seller_id=seller, name="Yetkazilmas", price=10000, stock_count=50)
    d.update_product_fields(pid, in_stock=1, status="active")

    c = TestClient(webapp_server.app)
    c.db = d
    c.SELLER, c.BUYER, c.PID = seller, buyer, pid
    return c


def _order(c, dlv="delivery", qty=1, pid=None):
    body = {"product_id": pid or c.PID, "quantity": qty,
            "delivery_type": dlv, "payment_method": "cash"}
    if dlv == "delivery":
        body.update({"lat": 41.0, "lon": 69.0, "address": "Test ko'cha 1"})
    return c.post("/api/order", headers=hdr(8001), json=body)


def test_pickup_only_product_rejects_delivery(env):
    env.db.update_product_fields(env.PID, delivery_available=0)
    r = _order(env, "delivery")
    assert r.status_code == 400 and r.json()["detail"] == "delivery_not_available"
    # pickup esa bemalol
    assert _order(env, "pickup").status_code == 200


def test_delivery_min_total_enforced(env):
    env.db.update_user(env.SELLER, delivery_min_total=50000)
    r = _order(env, "delivery", qty=2)   # 20 000 < 50 000
    assert r.status_code == 400 and r.json()["detail"] == "delivery_min_50000"
    # yetarli summa — o'tadi
    assert _order(env, "delivery", qty=5).status_code == 200


def test_old_products_deliverable_by_default(env):
    # delivery_available tegilmagan (DEFAULT 1) — yetkazish ochiq
    assert _order(env, "delivery").status_code == 200


def test_shop_patch_sets_and_clears_min(env):
    r = env.patch("/api/seller/shop", headers=hdr(8002), json={"delivery_min_total": 75000})
    assert r.status_code == 200
    assert env.get("/api/seller/shop", headers=hdr(8002)).json()["delivery_min_total"] == 75000
    r = env.patch("/api/seller/shop", headers=hdr(8002), json={"delivery_min_total": 0})
    assert r.status_code == 200
    assert env.get("/api/seller/shop", headers=hdr(8002)).json()["delivery_min_total"] is None


def test_product_create_and_edit_delivery_flag(env):
    r = env.post("/api/seller/product", headers=hdr(8002), json={
        "name": "Og'ir mebel", "price": 900000, "delivery_available": 0})
    assert r.status_code == 200
    pid = r.json()["product_id"]
    assert env.db.get_product_by_id(pid)["delivery_available"] == 0
    r = env.patch(f"/api/seller/product/{pid}", headers=hdr(8002),
                  json={"delivery_available": 1})
    assert r.status_code == 200
    assert env.db.get_product_by_id(pid)["delivery_available"] == 1


def test_cart_checkout_blocked_by_pickup_only_item(env):
    pid2 = env.db.create_product(seller_id=env.SELLER, name="Ikkinchi", price=5000, stock_count=9)
    env.db.update_product_fields(pid2, in_stock=1, status="active", delivery_available=0)
    r = env.post("/api/cart/checkout", headers=hdr(8001), json={
        "seller_id": env.SELLER,
        "items": [{"product_id": env.PID, "quantity": 1}, {"product_id": pid2, "quantity": 1}],
        "delivery_type": "delivery", "payment_method": "cash",
        "lat": 41.0, "lon": 69.0, "address": "Test"})
    assert r.status_code == 400 and r.json()["detail"] == "delivery_not_available"
    # hech bitta buyurtma yaratilmagan bo'lishi shart (yarim guruh qolmasin)
    assert not env.db.get_buyer_orders_list(env.BUYER)
    # pickup bilan o'tadi
    r = env.post("/api/cart/checkout", headers=hdr(8001), json={
        "seller_id": env.SELLER,
        "items": [{"product_id": env.PID, "quantity": 1}, {"product_id": pid2, "quantity": 1}],
        "delivery_type": "pickup", "payment_method": "cash"})
    assert r.status_code == 200 and r.json()["count"] == 2


def test_variant_order_respects_delivery_min(env):
    env.db.update_user(env.SELLER, delivery_min_total=100000)
    r = env.post("/api/order/variants", headers=hdr(8001), json={
        "product_id": env.PID, "lines": [{"label": "#1", "qty": 2}],
        "delivery_type": "delivery", "payment_method": "cash",
        "lat": 41.0, "lon": 69.0, "address": "Test"})
    assert r.status_code == 400 and r.json()["detail"] == "delivery_min_100000"


def test_admin_products_full_fields(env):
    admin = env.db.create_user(telegram_id=8003, phone_number="998900000013",
                               name="Admin", role="admin")
    assert admin
    r = env.get("/api/admin/products", headers=hdr(8003))
    assert r.status_code == 200
    items = r.json()
    assert items, "kamida bitta mahsulot bo'lishi kerak"
    p = items[0]
    for field in ("id", "name", "price", "image_url", "status", "in_stock",
                  "stock_count", "created_at", "shop_name", "seller_name",
                  "seller_phone", "sold_count"):
        assert field in p, f"admin mahsulot kartasida '{field}' yo'q"
    # qidiruv ishlaydi
    r = env.get("/api/admin/products?q=Yetkazilmas", headers=hdr(8003))
    assert any(x["id"] == env.PID for x in r.json())
    r = env.get("/api/admin/products?q=bunday-mahsulot-yoq", headers=hdr(8003))
    assert r.json() == []
