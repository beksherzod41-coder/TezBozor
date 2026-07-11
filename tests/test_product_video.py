"""Mahsulot video MVP testlari — 1 ta ixtiyoriy video (Telegram file_id).

Qoidalar:
  • create/edit'da video_file_id saqlanadi; bo'sh satr = o'chirish (NULL);
  • detail API xaridorga video_file_id qaytaradi;
  • upload: hajm chegarasi 413; Telegram davomiyligi >60s bo'lsa 400 video_too_long.
"""
import io
import json
import os
import time

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
# webapp_server importi .env yuklaydi — ADMIN_ID'ni keyingi testlar uchun qotiramiz
# (tafsilot: tests/test_delivery_rules.py dagi izoh).
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
    d = Database(db_path=str(tmp_path / "vid.db"))
    monkeypatch.setattr(webapp_server, "db", d)
    monkeypatch.setattr(webapp_server, "BOT_TOKEN", TOKEN)
    webapp_server._RATE.clear()

    async def _tg(method, payload, **kw):
        return {"ok": True, "result": {"message_id": 1}}
    monkeypatch.setattr(webapp_server, "_tg_call", _tg)

    seller = d.create_user(telegram_id=9002, phone_number="998900000022", name="Seller", role="seller")
    d.update_user(seller, is_approved=1, shop_name="Video Do'kon")
    buyer = d.create_user(telegram_id=9001, phone_number="998900000021", name="Buyer", role="buyer")
    d.create_shop(seller)

    c = TestClient(webapp_server.app)
    c.db = d
    c.SELLER, c.BUYER = seller, buyer
    return c


def test_create_edit_and_expose_video(env):
    r = env.post("/api/seller/product", headers=hdr(9002), json={
        "name": "Ko'ylak", "price": 120000, "video_file_id": "VID_abc123"})
    assert r.status_code == 200
    pid = r.json()["product_id"]
    assert env.db.get_product_by_id(pid)["video_file_id"] == "VID_abc123"
    # Xaridor detail'da videoni ko'radi
    d = env.get(f"/api/products/{pid}", headers=hdr(9001)).json()
    assert d["video_file_id"] == "VID_abc123"
    # Bo'sh satr — videoni o'chiradi
    r = env.patch(f"/api/seller/product/{pid}", headers=hdr(9002), json={"video_file_id": ""})
    assert r.status_code == 200
    assert env.db.get_product_by_id(pid)["video_file_id"] is None


def test_video_upload_size_limit(env, monkeypatch):
    monkeypatch.setattr(webapp_server, "MAX_VIDEO_BYTES", 10)   # sinov uchun kichraytamiz
    r = env.post("/api/seller/product/video", headers=hdr(9002),
                 files={"file": ("clip.mp4", io.BytesIO(b"x" * 100), "video/mp4")})
    assert r.status_code == 413 and r.json()["detail"] == "too_large"


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    """httpx.AsyncClient o'rni — sendVideo javobini oldindan belgilangan payload bilan qaytaradi."""
    payload = {}

    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        if "sendVideo" in url:
            return _FakeResp(type(self).payload)
        return _FakeResp({"ok": True})


def _upload(env):
    return env.post("/api/seller/product/video", headers=hdr(9002),
                    files={"file": ("clip.mp4", io.BytesIO(b"videobytes"), "video/mp4")})


def test_video_upload_rejects_long_video(env, monkeypatch):
    _FakeClient.payload = {"ok": True, "result": {
        "message_id": 5, "video": {"file_id": "VID_long", "duration": 95}}}
    monkeypatch.setattr(webapp_server.httpx, "AsyncClient", _FakeClient)
    r = _upload(env)
    assert r.status_code == 400 and r.json()["detail"] == "video_too_long"


def test_video_upload_ok(env, monkeypatch):
    _FakeClient.payload = {"ok": True, "result": {
        "message_id": 6, "video": {"file_id": "VID_ok", "duration": 42}}}
    monkeypatch.setattr(webapp_server.httpx, "AsyncClient", _FakeClient)
    r = _upload(env)
    assert r.status_code == 200
    assert r.json() == {"file_id": "VID_ok", "duration": 42}
