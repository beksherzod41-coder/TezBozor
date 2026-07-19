"""Do'kon "Aloqa bloki" (#6) — reklamaga qo'shiladigan murojaat tugmalari.

Telegram inline tugma faqat http(s)/tg:// havolani qabul qiladi, shuning uchun
noto'g'ri qiymat tugmani umuman qo'shmasligi kerak (post buzilmasin).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


# ---------- _norm_contact_url ----------

def test_instagram_username_havolaga_aylanadi():
    assert main._norm_contact_url("@dokonim", "instagram") == "https://instagram.com/dokonim"
    assert main._norm_contact_url("dokonim", "instagram") == "https://instagram.com/dokonim"


def test_telegram_username_havolaga_aylanadi():
    assert main._norm_contact_url("@kanalim", "telegram") == "https://t.me/kanalim"
    assert main._norm_contact_url("t.me/kanalim", "telegram") == "https://t.me/kanalim"


def test_tayyor_havola_ozgarmaydi():
    for kind in ("instagram", "telegram", "website"):
        assert main._norm_contact_url("https://example.com/x", kind) == "https://example.com/x"


def test_website_domen_https_oladi():
    assert main._norm_contact_url("example.com", "website") == "https://example.com"


def test_yaroqsiz_qiymat_none():
    """Domen ko'rinishida bo'lmagan matn tugmaga aylanmasligi kerak."""
    assert main._norm_contact_url("", "website") is None
    assert main._norm_contact_url(None, "website") is None
    assert main._norm_contact_url("shunchaki matn", "website") is None
    assert main._norm_contact_url("@", "instagram") is None


# ---------- _call_bridge_url ----------

def test_call_bridge_url(monkeypatch):
    monkeypatch.setattr(main, "MINIAPP_URL", "https://example.com")
    assert main._call_bridge_url("+998 94 006 88 11") == "https://example.com/call/998940068811"
    assert main._call_bridge_url("123") is None      # juda qisqa
    assert main._call_bridge_url("") is None
    assert main._call_bridge_url(None) is None


def test_call_bridge_miniapp_url_yoq(monkeypatch):
    """MINIAPP_URL yo'q bo'lsa qo'ng'iroq tugmasi umuman chiqmaydi."""
    monkeypatch.setattr(main, "MINIAPP_URL", None)
    assert main._call_bridge_url("+998940068811") is None


# ---------- _shop_contact_buttons ----------

def test_toldirilgan_maydonlar_tugma_boladi(monkeypatch):
    monkeypatch.setattr(main, "MINIAPP_URL", "https://example.com")
    rows = main._shop_contact_buttons({
        "shop_phone": "+998940068811",
        "shop_telegram": "@kanalim",
        "shop_instagram": "@dokonim",
    })
    labels = [b.text for r in rows for b in r]
    assert "📞 Qo'ng'iroq" in labels
    assert "📢 Telegram" in labels
    assert "📸 Instagram" in labels
    # qator boshiga 2 tadan joylashadi
    assert all(len(r) <= 2 for r in rows)


def test_bosh_dokon_tugmasiz(monkeypatch):
    monkeypatch.setattr(main, "MINIAPP_URL", "https://example.com")
    assert main._shop_contact_buttons({}) == []
    assert main._shop_contact_buttons({"shop_phone": "", "shop_telegram": None}) == []


def test_yaroqsiz_havola_tugma_qoshmaydi(monkeypatch):
    """Buzuq qiymat butun postni yiqitmasligi kerak — shunchaki tugma bo'lmaydi."""
    monkeypatch.setattr(main, "MINIAPP_URL", "https://example.com")
    rows = main._shop_contact_buttons({"shop_website": "shunchaki matn"})
    assert rows == []


def test_barcha_tugmalar_url_ga_ega(monkeypatch):
    """Telegram inline tugma url'siz bo'lsa xato beradi."""
    monkeypatch.setattr(main, "MINIAPP_URL", "https://example.com")
    rows = main._shop_contact_buttons({
        "shop_phone": "+998940068811", "shop_telegram": "@k",
        "shop_instagram": "@i", "shop_website": "example.com",
    })
    for r in rows:
        for b in r:
            assert b.url and b.url.startswith(("http://", "https://", "tg://"))
