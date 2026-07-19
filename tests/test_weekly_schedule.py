"""Haftalik ish jadvali (#5) — per-kun soat, qisqa/yopiq kunlar.

Asosiy talab: qisqa kunda (masalan yakshanba 12:30 gacha) kelgan buyurtma
AVTOMATIK BEKOR BO'LMAYDI — sanoq keyingi ochilishgacha muzlaydi.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tezbozor_design import (  # noqa: E402
    CLOSED, TZ_TASHKENT, is_shop_open_now, next_shop_open_datetime,
    normalize_schedule, parse_working_days, resolve_schedule,
)

# 2026-07-19 — yakshanba (weekday 6), 2026-07-20 — dushanba
YAKSHANBA = datetime(2026, 7, 19, tzinfo=TZ_TASHKENT)
WS_QISQA_YAKSHANBA = json.dumps({str(i): "09:00-21:00" for i in range(6)} | {"6": "09:00-12:30"})


# ---------- resolve_schedule ----------

def test_per_kun_jadval_ustun():
    """work_schedule bo'lsa working_hours e'tiborga olinmaydi."""
    sched = resolve_schedule(WS_QISQA_YAKSHANBA, working_hours="00:00-23:59")
    assert sched[0] == (9 * 60, 21 * 60)
    assert sched[6] == (9 * 60, 12 * 60 + 30)   # yakshanba qisqa


def test_jadvalda_yoq_kun_yopiq():
    sched = resolve_schedule(json.dumps({"0": "09:00-18:00"}))
    assert sched[0] == (9 * 60, 18 * 60)
    for wd in range(1, 7):
        assert sched[wd] == CLOSED


def test_jadval_yoq_bolsa_eski_soatga_qaytadi():
    """Orqaga moslik: work_schedule bo'lmasa yagona working_hours ishlaydi."""
    sched = resolve_schedule(None, working_hours="09:00-21:00")
    assert all(sched[wd] == (9 * 60, 21 * 60) for wd in range(7))


def test_buzuq_json_fallback():
    sched = resolve_schedule("{buzuq", working_hours="09:00-21:00")
    assert sched[0] == (9 * 60, 21 * 60)


def test_24_soat_none():
    """Bir xil boshlanish/tugash = 24 soat → None (ochiq, muzlatilmaydi)."""
    sched = resolve_schedule(json.dumps({"0": "00:00-00:00"}))
    assert sched[0] is None


# ---------- normalize_schedule ----------

def test_normalize_kanonik_format():
    out = normalize_schedule({"0": "9-18", "6": ""})
    data = json.loads(out)
    assert data["0"] == "09:00-18:00"
    assert "6" not in data          # yopiq kun kalitga kirmaydi


def test_normalize_bosh_none():
    assert normalize_schedule({}) is None
    assert normalize_schedule({"0": "", "1": ""}) is None
    assert normalize_schedule("buzuq") is None
    assert normalize_schedule(None) is None


def test_normalize_json_matn_ham_qabul_qiladi():
    out = normalize_schedule('{"0": "09:00-21:00"}')
    assert json.loads(out)["0"] == "09:00-21:00"


# ---------- parse_working_days ----------

def test_parse_working_days_erkin_matn():
    assert parse_working_days("Har kuni") == {0, 1, 2, 3, 4, 5, 6}
    assert parse_working_days("Ish kunlari") == {0, 1, 2, 3, 4}
    assert parse_working_days("Dushanba-Juma") == {0, 1, 2, 3, 4}
    assert parse_working_days("") is None
    assert parse_working_days(None) is None


def test_shanba_seshanba_ichida_adashtirmaydi():
    """'shanba' 'seshanba' ichida bor — uzun nom avval mos kelishi kerak."""
    assert parse_working_days("Seshanba") == {1}
    assert parse_working_days("Yakshanba") == {6}


# ---------- next_shop_open_datetime: ASOSIY HOLAT ----------

def test_qisqa_yakshanba_dushanbagacha_muzlaydi():
    """Yakshanba 14:00 (12:30 da yopilgan) → keyingi ochilish dushanba 09:00."""
    now = YAKSHANBA.replace(hour=14)
    nxt = next_shop_open_datetime(now=now, work_schedule=WS_QISQA_YAKSHANBA)
    assert nxt is not None, "yopiq bo'lsa keyingi ochilish qaytishi kerak"
    assert nxt.weekday() == 0                      # dushanba
    assert (nxt.hour, nxt.minute) == (9, 0)
    assert nxt.day == 20


def test_qisqa_yakshanba_ish_vaqtida_ochiq():
    """Yakshanba 10:00 — hali ochiq → None (buyurtma darhol boshlanadi)."""
    now = YAKSHANBA.replace(hour=10)
    assert next_shop_open_datetime(now=now, work_schedule=WS_QISQA_YAKSHANBA) is None


def test_yopiq_kun_tashlab_ketiladi():
    """Faqat dushanba ochiq: seshanba kelgan buyurtma keyingi dushanbani kutadi."""
    ws = json.dumps({"0": "09:00-18:00"})
    seshanba = datetime(2026, 7, 21, 10, 0, tzinfo=TZ_TASHKENT)   # seshanba
    nxt = next_shop_open_datetime(now=seshanba, work_schedule=ws)
    assert nxt is not None and nxt.weekday() == 0
    assert nxt.day == 27          # keyingi dushanba


def test_soat_nomalum_bolsa_ochiq():
    """Hech qanday soat belgilanmagan → None (doim ochiq, muzlatilmaydi)."""
    assert next_shop_open_datetime(now=YAKSHANBA.replace(hour=3)) is None


def test_naive_datetime_ham_ishlaydi():
    """tz-siz vaqt berilsa Toshkent vaqti deb qabul qilinadi (crash bo'lmasin)."""
    naive = datetime(2026, 7, 19, 14, 0)
    nxt = next_shop_open_datetime(now=naive, work_schedule=WS_QISQA_YAKSHANBA)
    assert nxt is not None and nxt.weekday() == 0


# ---------- is_shop_open_now orqaga moslik ----------

def test_is_shop_open_now_eski_imzo_ishlaydi():
    """Eski chaqiruv (bitta pozitsion argument) buzilmasligi kerak."""
    assert is_shop_open_now("00:00-00:00") is None      # 24 soat -> noma'lum
    assert is_shop_open_now(None) is None
    assert is_shop_open_now("") is None
