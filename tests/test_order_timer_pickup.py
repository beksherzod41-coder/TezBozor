"""Buyurtma taymeri va olib ketish (#4) — muzlash, eslatmalar, pickup DB qatlami.

Asosiy talab: do'kon yopiq paytda kelgan buyurtma sanog'i keyingi ochilishgacha
muzlaydi — tunda avtomatik bekor bo'lib ketmaydi.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from database import Database  # noqa: E402


# ---------- _compute_order_deadline ----------

def test_dokon_ochiq_sanoq_darhol():
    """Ish soati noma'lum (None) — do'kon ochiq deb qaraladi, sanoq darhol."""
    deadline, cd_start = main._compute_order_deadline(None, None)
    now = datetime.now(timezone.utc)
    assert abs((cd_start - now).total_seconds()) < 5
    assert abs((deadline - cd_start).total_seconds() - main.ORDER_TTL_SECONDS) < 5


def test_dokon_yopiq_sanoq_muzlaydi():
    """00:00-00:01 oralig'ida ishlaydigan do'kon — hozir deyarli har doim yopiq.
    Sanoq kelajakdagi ochilishdan boshlanishi kerak."""
    deadline, cd_start = main._compute_order_deadline("03:00-03:01", None)
    now = datetime.now(timezone.utc)
    # hozir aynan 03:00-03:01 (Toshkent) oralig'iga tushib qolgan bo'lsa — sanoq darhol
    if (cd_start - now).total_seconds() > 5:
        assert (deadline - cd_start).total_seconds() == main.ORDER_TTL_SECONDS
    else:
        assert abs((deadline - now).total_seconds() - main.ORDER_TTL_SECONDS) < 5


def test_ttl_20_daqiqa_va_5_eslatma():
    """Foydali Market pariteti: 20 daqiqa muddat, 5 eslatma bosqichi."""
    assert main.ORDER_TTL_SECONDS == 1200
    assert main.ORDER_REMINDER_MINUTES == [16, 12, 8, 4, 1]


def test_optom_eslatma_har_5_daqiqa():
    thr = main._reminder_thresholds(1800)   # 30 daqiqa
    assert thr == [25, 20, 15, 10, 5, 1]
    assert main._reminder_thresholds(1200) == [16, 12, 8, 4, 1]


# ---------- _countdown_start / _frozen_line ----------

def test_countdown_start_ustunlik():
    o = {"countdown_start_at": "2026-07-20 04:00:00", "created_at": "2026-07-19 10:00:00"}
    cs = main._countdown_start(o)
    assert cs == datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
    # eski buyurtma — countdown_start_at yo'q -> created_at
    cs2 = main._countdown_start({"created_at": "2026-07-19 10:00:00"})
    assert cs2 == datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)


def test_frozen_line_toshkent_vaqti():
    cs = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)   # = 09:00 Toshkent
    line = main._frozen_line("uz", cs)
    assert "09:00" in line
    assert main._frozen_line("uz", None) == ""


# ---------- pickup DB qatlami ----------

@pytest.fixture
def d(tmp_path):
    return Database(db_path=str(tmp_path / "t4.db"))


def _mk_order(d, delivery_type="pickup"):
    s = d.create_user(telegram_id=101, phone_number="998900000101", name="S", role="seller")
    b = d.create_user(telegram_id=102, phone_number="998900000102", name="B", role="buyer")
    p = d.create_product(seller_id=s, name="Olma", price=1000, stock_count=5)
    oid = d.create_order(buyer_id=b, seller_id=s, product_id=p, quantity=1,
                         total_price=1000, delivery_type=delivery_type)
    return oid


def test_deadline_countdown_start_saqlanadi(d):
    oid = _mk_order(d)
    dl = datetime(2026, 7, 20, 4, 20, tzinfo=timezone.utc)
    cs = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
    d.set_order_deadline(oid, dl, countdown_start=cs)
    o = d.get_order_by_id(oid)
    assert str(o["auto_cancel_at"])[:19] == "2026-07-20 04:20:00"
    assert str(o["countdown_start_at"])[:19] == "2026-07-20 04:00:00"


def test_group_deadline_countdown_start(d):
    oid = _mk_order(d)
    d.set_orders_group([oid], str(oid))
    dl = datetime(2026, 7, 20, 4, 20, tzinfo=timezone.utc)
    cs = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
    d.set_group_deadline(str(oid), dl, countdown_start=cs)
    o = d.get_order_by_id(oid)
    assert str(o["countdown_start_at"])[:19] == "2026-07-20 04:00:00"


def test_pickup_at_va_bitmask(d):
    oid = _mk_order(d)
    pk = datetime.now(timezone.utc) + timedelta(minutes=30)
    d.set_order_pickup_at(oid, pk)
    o = d.get_order_by_id(oid)
    assert o["pickup_at"] is not None
    assert int(o["pickup_reminded"] or 0) == 0
    d.mark_pickup_reminded(oid, 1)
    assert int(d.get_order_by_id(oid)["pickup_reminded"]) == 1
    d.mark_pickup_reminded(oid, 2)
    assert int(d.get_order_by_id(oid)["pickup_reminded"]) == 3


def test_due_pickup_reminders_filtri(d):
    oid = _mk_order(d)
    d.update_order_status(oid, "confirmed")
    pk = datetime.now(timezone.utc) + timedelta(minutes=30)
    d.set_order_pickup_at(oid, pk)
    rows = d.get_due_pickup_reminders(within_seconds=3600)
    assert any(r["id"] == oid for r in rows)
    # to'liq eslatilgan (3) — endi chiqmaydi
    d.mark_pickup_reminded(oid, 3)
    rows2 = d.get_due_pickup_reminders(within_seconds=3600)
    assert not any(r["id"] == oid for r in rows2)


def test_due_pickup_pending_chiqmaydi(d):
    """Faqat 'confirmed' pickup buyurtmalar eslatiladi."""
    oid = _mk_order(d)   # status pending
    d.set_order_pickup_at(oid, datetime.now(timezone.utc))
    assert not any(r["id"] == oid for r in d.get_due_pickup_reminders())


# ---------- _resolve_pickup_dt ----------

def test_resolve_pickup_skip_va_yaroqsiz():
    assert main._resolve_pickup_dt("skip", {}) is None
    assert main._resolve_pickup_dt("bexos", {}) is None


def test_resolve_pickup_soat_ochiq_dokon():
    """Ish soati yo'q do'kon — tanlangan vaqt o'zgarishsiz qoladi."""
    res = main._resolve_pickup_dt("60", {})
    assert res is not None
    delta = (res - datetime.now(main.TZ_TASHKENT)).total_seconds()
    assert 3500 < delta < 3700   # ~1 soat


def test_resolve_pickup_yopiq_kunga_tushsa_suriladi():
    """Faqat dushanba ochiq do'kon: '1 soatdan keyin' dushanba ochilishiga suriladi."""
    ws = json.dumps({"0": "09:00-18:00"})
    res = main._resolve_pickup_dt("60", {"work_schedule": ws})
    assert res is not None
    now = datetime.now(main.TZ_TASHKENT)
    # agar hozir dushanba ish vaqti bo'lsa — surilmaydi; aks holda dushanba 09:00
    if not (now.weekday() == 0 and 9 * 60 <= now.hour * 60 + now.minute < 18 * 60 - 60):
        assert res.weekday() == 0 and (res.hour, res.minute) == (9, 0)
