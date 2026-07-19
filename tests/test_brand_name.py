"""BRAND_NAME — brend nomi .env orqali sozlanishi (#7).

Tarjima matnlarida {brand} yozuvi ishlatiladi, t() uni almashtiradi.
Muhim: {brand} almashtirish .format() dan OLDIN bo'lishi kerak, aks holda
{ts} kabi boshqa o'rinbosarlar bor matnlar buziladi.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import languages  # noqa: E402


def test_brand_standart_qiymat():
    assert languages.BRAND_NAME  # bo'sh emas


def test_welcome_matnida_brend_bor():
    """{brand} xom holda chiqib qolmasligi kerak."""
    for lang in ("uz", "ru"):
        txt = languages.t(lang, "welcome")
        assert "{brand}" not in txt, "o'rinbosar almashtirilmagan"
        assert languages.BRAND_NAME in txt


def test_brand_va_boshqa_orinbosar_birga():
    """backup_caption da {brand} ham, {ts} ham bor — ikkalasi ham ishlashi kerak."""
    txt = languages.t("uz", "backup_caption", ts="2026-01-01")
    assert "{brand}" not in txt
    assert "{ts}" not in txt
    assert languages.BRAND_NAME in txt
    assert "2026-01-01" in txt


def test_env_orqali_ozgaradi(monkeypatch):
    """BRAND_NAME .env dan o'qiladi — modul qayta yuklanganda yangi nom chiqadi."""
    monkeypatch.setenv("BRAND_NAME", "SinovBrend")
    mod = importlib.reload(languages)
    try:
        assert mod.BRAND_NAME == "SinovBrend"
        assert "SinovBrend" in mod.t("uz", "welcome")
        assert "TezBozor" not in mod.t("uz", "welcome")
    finally:
        monkeypatch.delenv("BRAND_NAME", raising=False)
        importlib.reload(languages)


def test_matnlarda_qattiq_yozilgan_brend_qolmagan():
    """_TEXTS ichida "TezBozor" qattiq yozilgan bo'lmasligi kerak."""
    qoldi = [k for k, v in languages._TEXTS.items()
             if any("TezBozor" in str(x) for x in v.values())]
    assert not qoldi, "qattiq yozilgan brend qolgan kalitlar: %s" % qoldi
