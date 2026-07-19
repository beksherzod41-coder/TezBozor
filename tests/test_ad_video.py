"""🎬 AI video-reklama testlari.

1) ad_video moduli — kichik o'lchamda haqiqiy ffmpeg render (ffmpeg yo'q bo'lsa
   skip), emoji tozalash, deterministik zaxira hook.
2) /adclip va /ad-publish endpointlari — auth/egalik/no_photo guardlari va
   happy-path (ffmpeg va Telegram monkeypatch bilan soxtalashtiriladi).
"""
import io
import json
import os
import time

import pytest

# webapp_server import paytida BOT_TOKEN kerak (.env gotcha — import OLDIDAN).
# Bu fayl alifbo bo'yicha test_main_handlers'dan OLDIN turadi — webapp_server
# importi .env'dagi haqiqiy ADMIN_ID'ni yuklab, keyingi testlardagi
# setdefault("ADMIN_ID","1") ni buzmasin.
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
os.environ.setdefault("DB_BACKEND", "sqlite")

import ad_video  # noqa: E402
import ai_assistant  # noqa: E402


# ============ 1) modul testlari ============

def _sample_jpeg(color=(180, 60, 70)):
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    img = Image.new("RGB", (400, 500), color)
    b = io.BytesIO()
    img.save(b, "JPEG")
    return b.getvalue()


def test_strip_emoji():
    assert ad_video.strip_emoji("Yangi 🔥 keldi ✨") == "Yangi keldi"
    assert ad_video.strip_emoji("") == ""
    assert ad_video.strip_emoji(None) == ""


def test_clip_fallback_hook_deterministic():
    a = ai_assistant.clip_fallback_hook("Telefon", "uz", seed=7)
    b = ai_assistant.clip_fallback_hook("Telefon", "uz", seed=7)
    assert a == b and a  # bo'sh emas va barqaror
    assert ai_assistant.clip_fallback_hook("X", "ru", seed=1)  # ru ham ishlaydi
    assert ai_assistant.clip_fallback_hook("X", "de", seed=1)  # noma'lum til -> uz


@pytest.mark.skipif(not ad_video.is_enabled(), reason="ffmpeg yoki Pillow yo'q")
def test_build_ad_clip_renders_mp4():
    data = ad_video.build_ad_clip(
        [_sample_jpeg()],
        hook_text="Bunaqasi kam topiladi",
        price_text="45 000 so'm", shop_text="Test Do'kon",
        optom_text="OPTOM", brand_text="TezBozor",
        out_w=160, out_h=284, fps=8, seg_dur=0.8, xfade=0.25)
    assert data and len(data) > 1000
    # MP4 konteyner belgisi (faststart bilan 'ftyp' fayl boshida)
    assert data[4:8] == b"ftyp"


@pytest.mark.skipif(not ad_video.is_enabled(), reason="ffmpeg yoki Pillow yo'q")
def test_build_ad_clip_bad_image_returns_none():
    assert ad_video.build_ad_clip([b"bu rasm emas"]) is None


def test_build_ad_clip_empty_returns_none():
    assert ad_video.build_ad_clip([]) is None


# ============ 2) endpoint testlari ============

pytest.importorskip("fastapi")
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
    webapp_server._RATE.clear()
    d.create_user(telegram_id=5001, phone_number="998900000001", name="Buyer", role="buyer")
    s = d.create_user(telegram_id=5002, phone_number="998900000002", name="Seller", role="seller")
    p = d.create_product(seller_id=s, name="Test mahsulot", price=1000, stock_count=5)
    d.update_product_fields(p, in_stock=1, status="active")
    c = TestClient(webapp_server.app)
    c.pid = p
    c.db = d
    return c


def _fake_clip_env(monkeypatch, clip=b"x" * 2000, file_id="VIDFID123"):
    """ffmpeg/Telegram'siz happy-path: render va upload soxtalashtiriladi."""
    monkeypatch.setattr(webapp_server.ad_video, "is_enabled", lambda: True)
    monkeypatch.setattr(webapp_server.ad_video, "build_ad_clip",
                        lambda *a, **k: clip)

    async def fake_bytes(fid):
        return _sample_jpeg()

    async def fake_upload(chat_id, data, filename="clip.mp4"):
        return file_id

    async def fake_hook(**kw):
        return "TEST HOOK"

    monkeypatch.setattr(webapp_server, "_tg_file_bytes", fake_bytes)
    monkeypatch.setattr(webapp_server, "_tg_upload_video", fake_upload)
    monkeypatch.setattr(webapp_server.ai_assistant, "generate_clip_hook", fake_hook)


def test_adclip_requires_auth(client):
    assert client.post(f"/api/seller/product/{client.pid}/adclip").status_code == 401


def test_adclip_not_owner_403(client, monkeypatch):
    _fake_clip_env(monkeypatch)
    r = client.post(f"/api/seller/product/{client.pid}/adclip", headers=hdr(5001))
    assert r.status_code == 403


def test_adclip_disabled_503(client, monkeypatch):
    monkeypatch.setattr(webapp_server.ad_video, "is_enabled", lambda: False)
    r = client.post(f"/api/seller/product/{client.pid}/adclip", headers=hdr(5002))
    assert r.status_code == 503


def test_adclip_no_photo_400(client, monkeypatch):
    _fake_clip_env(monkeypatch)
    r = client.post(f"/api/seller/product/{client.pid}/adclip", headers=hdr(5002))
    assert r.status_code == 400 and r.json()["detail"] == "no_photo"


def test_adclip_happy_path(client, monkeypatch):
    _fake_clip_env(monkeypatch)
    client.db.add_product_image(client.pid, "IMG_FID_1")
    r = client.post(f"/api/seller/product/{client.pid}/adclip", headers=hdr(5002))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["file_id"] == "VIDFID123"
    assert body["hook"] == "TEST HOOK"
    # klip /api/video disk-keshiga oldindan yozilgan bo'lishi kerak
    import hashlib
    cache = os.path.join(webapp_server.IMG_CACHE_DIR,
                         hashlib.sha256(b"VIDFID123").hexdigest() + ".mp4")
    assert os.path.exists(cache)
    os.remove(cache)


def test_adclip_render_failure_502(client, monkeypatch):
    _fake_clip_env(monkeypatch, clip=None)
    client.db.add_product_image(client.pid, "IMG_FID_1")
    r = client.post(f"/api/seller/product/{client.pid}/adclip", headers=hdr(5002))
    assert r.status_code == 502 and r.json()["detail"] == "clip_failed"


def test_ad_publish_saves_video_id(client):
    r = client.post(f"/api/seller/product/{client.pid}/ad-publish",
                    headers=hdr(5002), json={"video_id": "VIDFID123"})
    assert r.status_code == 200
    prod = client.db.get_product_by_id(client.pid)
    assert prod["ad_video_file_id"] == "VIDFID123"


def test_ad_publish_without_video_keeps_null(client):
    r = client.post(f"/api/seller/product/{client.pid}/ad-publish",
                    headers=hdr(5002), json={})
    assert r.status_code == 200
    prod = client.db.get_product_by_id(client.pid)
    assert not prod.get("ad_video_file_id")


def test_ad_preview_prefers_ad_clip(client, monkeypatch):
    """ad_video_file_id o'rnatilgach preview post bilan mos — video ko'rsatadi."""
    client.db.set_product_ad_video(client.pid, "VIDFID123")

    async def fake_caption(prod, length, lang):
        return "matn", None

    monkeypatch.setattr(webapp_server, "_build_ad_caption_web", fake_caption)
    r = client.get(f"/api/seller/product/{client.pid}/ad-preview", headers=hdr(5002))
    assert r.status_code == 200
    d = r.json()
    assert d["has_video"] is True and d["video_file_id"] == "VIDFID123"
