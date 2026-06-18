"""Telegram WebApp initData imzo tekshiruvi (webapp_auth) testlari.

Bu xavfsizlikning markaziy qismi — imzo to'g'ri tekshirilmasa, kimdir o'zini
boshqa foydalanuvchi qilib ko'rsatishi mumkin. Sof funksiyalar (DB kerak emas)."""
import json
import time

from webapp_auth import validate_init_data, build_init_data

TOKEN = "123456:TEST-BOT-TOKEN"


def _init(token=TOKEN, age=0, with_user=True):
    fields = {"auth_date": str(int(time.time()) - age)}
    if with_user:
        fields["user"] = json.dumps({"id": 7, "first_name": "Ali"})
    return build_init_data(token, fields)


def test_valid_signature():
    d = validate_init_data(_init(), TOKEN)
    assert d is not None
    assert d["user"]["id"] == 7


def test_tampered_hash_rejected():
    init = _init()
    bad = init[:-1] + ("0" if init[-1] != "0" else "1")  # oxirgi hash belgisini buzamiz
    assert validate_init_data(bad, TOKEN) is None


def test_wrong_token_rejected():
    assert validate_init_data(_init(), "999999:OTHER-TOKEN") is None


def test_old_auth_date_rejected():
    # 2 kun eski initData — max_age (24s) dan oshadi
    assert validate_init_data(_init(age=2 * 86400), TOKEN, max_age=86400) is None


def test_empty_rejected():
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data(_init(), "") is None


def test_missing_hash_rejected():
    from urllib.parse import urlencode
    raw = urlencode({"auth_date": str(int(time.time())),
                     "user": json.dumps({"id": 1})})  # hash YO'Q
    assert validate_init_data(raw, TOKEN) is None
