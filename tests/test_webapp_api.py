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
