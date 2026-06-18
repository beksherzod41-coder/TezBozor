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
