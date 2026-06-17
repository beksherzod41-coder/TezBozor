"""
Telegram WebApp initData tekshiruvi — xavfsizlikning markaziy qismi.

Bog'liqliksiz (faqat stdlib) — alohida unit-test qilinadi.
Telegram rasmiy algoritmi: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400):
    """initData imzosini bot tokeni bilan tekshiradi.
    To'g'ri bo'lsa — {'user': ..., 'raw': {...}} qaytaradi, aks holda None.

    max_age=0 bo'lsa — vaqt tekshiruvi o'chiriladi (test uchun)."""
    if not init_data or not bot_token:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None
    received = parsed.pop("hash", None)
    if not received:
        return None
    # data_check_string: kalitlar alifbo tartibida, 'key=value' \n bilan birlashtiriladi
    dcs = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    # auth_date yangiligini tekshirish (qayta yuborilgan eski initData'ni rad etish)
    if max_age:
        try:
            if time.time() - int(parsed.get("auth_date", "0")) > max_age:
                return None
        except ValueError:
            return None
    user = None
    if "user" in parsed:
        try:
            user = json.loads(parsed["user"])
        except Exception:
            pass
    return {"user": user, "raw": parsed}


def build_init_data(bot_token: str, fields: dict) -> str:
    """TEST uchun: berilgan maydonlardan to'g'ri imzolangan initData yasaydi.
    (Telegram mijozi aynan shunday imzolaydi.)"""
    from urllib.parse import urlencode
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})
