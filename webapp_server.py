"""
TezBozor Mini App backend (FastAPI) — Faza 1.

- Bot bilan AYNAN bir xil PostgreSQL bazaga ulanadi (database.py qayta ishlatiladi)
  → ma'lumot avtomatik 1:1, sinxronlash kerak emas.
- Telegram WebApp `initData` imzosini bot tokeni bilan tekshiradi (xavfsizlik).
- Mahsulot rasmlari Telegram file_id — ularni web'da ko'rsatish uchun rasm-proksi
  (getFile → yuklab → disk-cache → stream).

Ishga tushirish (lokal/sinov):
    uvicorn webapp_server:app --host 127.0.0.1 --port 8080

Kerakli paketlar:  fastapi  uvicorn[standard]  httpx
"""
import os
import html
import hashlib
import logging
from typing import Optional, List
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, Header, HTTPException, Query, File, UploadFile, Request
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

from database import Database
from webapp_auth import validate_init_data
from languages import t, get_user_lang, DEFAULT_LANG
from tezbozor_design import fmt_order_id, fmt_price
import ai_assistant

BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
except ValueError:
    ADMIN_ID = 0
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp_static")
IMG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img_cache")
os.makedirs(IMG_CACHE_DIR, exist_ok=True)

db = Database()  # DB_BACKEND / DATABASE_URL .env'dan o'qiladi
app = FastAPI(title="TezBozor Mini App API")


# ============================================================
# initData TEKSHIRUVI (Telegram WebApp xavfsizligi) — webapp_auth.py'da
# ============================================================
def require_auth(authorization: str):
    """Authorization sarlavhasi: "tma <initData>". To'g'ri bo'lmasa 401."""
    init_data = ""
    if authorization and authorization.startswith("tma "):
        init_data = authorization[4:]
    auth = validate_init_data(init_data, BOT_TOKEN)
    if not auth:
        raise HTTPException(status_code=401, detail="invalid initData")
    return auth


def _rows(result):
    """Row-larni JSON uchun dict'ga aylantiradi (PG shim _Row ham, sqlite3.Row ham)."""
    if not result:
        return []
    return [dict(r) for r in result]


# ============================================================
# API
# ============================================================
@app.get("/api/categories")
def api_categories(authorization: str = Header(None)):
    require_auth(authorization)
    return _rows(db.get_categories())


@app.get("/api/products")
def api_products(
    authorization: str = Header(None),
    q: str = Query(None),
    category_id: int = Query(None),
    sort: str = Query("rating"),
    region_id: int = Query(None),
    seller_id: int = Query(None),
):
    require_auth(authorization)
    items = db.search_products(
        query=q, category_id=category_id, sort_by=sort, region_id=region_id,
        seller_id=seller_id,
    )
    return _rows(items)


@app.get("/api/shops")
def api_shops(authorization: str = Header(None), q: str = Query(None)):
    require_auth(authorization)
    return _rows(db.search_shops(query=q))


# AI yordamchi — DeepSeek (ai_assistant.ask qayta ishlatiladi). Tarix xotirada (tg_id bo'yicha).
AI_SESSIONS = {}


class AiAsk(BaseModel):
    text: str
    mode: str = "buyer"   # 'buyer' | 'seller'


@app.post("/api/ai")
async def api_ai(body: AiAsk, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _rate_limit("ai", user.get("id"), 20, 60)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail="too_long")
    if not ai_assistant.is_enabled():
        raise HTTPException(status_code=503, detail="ai_disabled")
    # Sotuvchi rejimi — faqat seller/admin uchun; AI sotuvchi vositalarini (mahsulot
    # qo'shish/tahrirlash va h.k.) ishlatadi. Aks holda xaridor rejimi.
    if body.mode == "seller" and user.get("role") in ("seller", "admin"):
        role, seller_id = "seller", user.get("id")
    else:
        role, seller_id = "buyer", None
    ud = AI_SESSIONS.setdefault((user.get("telegram_id"), role), {})
    lang = user.get("language") or "uz"
    res = await ai_assistant.ask(db, lang, role, text, ud,
                                 seller_id=seller_id, user_name=user.get("name") or "")
    return {"text": res.get("text"), "products": _rows(res.get("products") or []) or None}


class ContactIn(BaseModel):
    text: str


@app.post("/api/contact-admin")
async def api_contact_admin(body: ContactIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _rate_limit("contact", user.get("id"), 5, 600)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="too_long")
    if not ADMIN_ID:
        raise HTTPException(status_code=503, detail="no_admin")
    uname = user.get("telegram_username")
    contact = f"@{uname}" if uname else (user.get("phone_number") or "")
    msg = (f"📩 Foydalanuvchi murojaati (Mini App)\n"
           f"👤 {html.escape(user.get('name') or '')} {html.escape(contact)}\n"
           f"🆔 {user.get('telegram_id')}\n\n{html.escape(text)}")
    await _tg_call("sendMessage", {"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"})
    return {"ok": True}


@app.post("/api/become-seller")
async def api_become_seller(authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _rate_limit("become_seller", user.get("id"), 3, 3600)
    if user.get("role") in ("seller", "admin") or user.get("is_approved"):
        raise HTTPException(status_code=409, detail="already_seller")
    existing = db.get_seller_request_by_user(user["id"])
    if existing and existing.get("status") == "pending":
        raise HTTPException(status_code=409, detail="already_pending")
    db.create_seller_request(user["id"])
    try:
        if ADMIN_ID:
            await _tg_call("sendMessage", {
                "chat_id": ADMIN_ID,
                "text": (f"🏪 Yangi sotuvchi arizasi (Mini App)\n"
                         f"👤 {html.escape(user.get('name') or '')}\n🆔 {user.get('telegram_id')}"),
                "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"become-seller notify xato: {e}")
    return {"ok": True}


@app.get("/api/products/{product_id}")
def api_product_detail(product_id: int, authorization: str = Header(None)):
    require_auth(authorization)
    product = db.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="not found")
    product = dict(product)
    product["images"] = db.get_product_images(product_id)  # file_id ro'yxati
    return product


# ============================================================
# BUYURTMA YARATISH (to'liq app ichida — sotuvchiga xabarni bot fon job'i yuboradi)
# ============================================================
ORDER_TTL_SECONDS = 600
_VALID_DELIVERY = {"delivery", "pickup"}
_VALID_PAYMENT = {"cash", "terminal", "p2p"}


class OrderIn(BaseModel):
    product_id: int
    quantity: int = 1
    delivery_type: str = "pickup"
    payment_method: str = "cash"
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.post("/api/order")
def api_create_order(order: OrderIn, authorization: str = Header(None)):
    auth = require_auth(authorization)
    tg_id = (auth.get("user") or {}).get("id")
    if not tg_id:
        raise HTTPException(status_code=401, detail="no user")
    buyer = db.get_user_by_telegram_id(tg_id)
    if not buyer:
        raise HTTPException(status_code=403, detail="not_registered")
    _rate_limit("order", buyer["id"], 15, 60)

    if order.quantity < 1 or order.quantity > 999:
        raise HTTPException(status_code=400, detail="bad_quantity")
    if order.delivery_type not in _VALID_DELIVERY:
        raise HTTPException(status_code=400, detail="bad_delivery_type")
    if order.payment_method not in _VALID_PAYMENT:
        raise HTTPException(status_code=400, detail="bad_payment_method")

    product = db.get_product_by_id(order.product_id)
    if not product or not product.get("in_stock"):
        raise HTTPException(status_code=404, detail="product_unavailable")
    if buyer["id"] == product["seller_id"]:
        raise HTTPException(status_code=400, detail="own_product")
    stock = product.get("stock_count")
    if stock is not None and order.quantity > stock:
        raise HTTPException(status_code=409, detail=f"only_{stock}_available")

    total = order.quantity * float(product["price"])
    if order.delivery_type == "delivery":
        address = (order.address or "").strip() or None
        lat, lon = order.lat, order.lon
    else:
        address, lat, lon = None, None, None

    order_id = db.create_order(
        buyer_id=buyer["id"], seller_id=product["seller_id"],
        product_id=product["id"], quantity=order.quantity, total_price=total,
        delivery_address=address, buyer_lat=lat, buyer_lon=lon,
        payment_method=order.payment_method, delivery_type=order.delivery_type,
    )
    # Avto-bekor muddati (bot order_confirm'i bilan bir xil) + bot fon job'i xabar yuboradi
    deadline = datetime.now(timezone.utc) + timedelta(seconds=ORDER_TTL_SECONDS)
    db.set_order_deadline(order_id, deadline)
    db.mark_order_notify_pending(order_id)
    return {"ok": True, "order_id": order_id, "total": total}


class CartItemIn(BaseModel):
    product_id: int
    quantity: int = 1


class CartCheckoutIn(BaseModel):
    seller_id: int
    items: List[CartItemIn]
    delivery_type: str = "pickup"
    payment_method: str = "cash"
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.post("/api/cart/checkout")
def api_cart_checkout(co: CartCheckoutIn, authorization: str = Header(None)):
    """Savat (bitta sotuvchi, ko'p mahsulot) -> guruh buyurtma. Bot fon job'i sotuvchiga
    BITTA guruh bildirishnomasi yuboradi."""
    buyer = dict(_buyer_from_auth(authorization))
    _rate_limit("cart", buyer["id"], 10, 60)
    if not co.items:
        raise HTTPException(status_code=400, detail="empty_cart")
    if co.delivery_type not in _VALID_DELIVERY:
        raise HTTPException(status_code=400, detail="bad_delivery_type")
    if co.payment_method not in _VALID_PAYMENT:
        raise HTTPException(status_code=400, detail="bad_payment_method")
    if co.delivery_type == "delivery":
        address = (co.address or "").strip() or None
        lat, lon = co.lat, co.lon
    else:
        address, lat, lon = None, None, None

    created, grand = [], 0.0
    for it in co.items:
        if it.quantity < 1:
            continue
        product = db.get_product_by_id(it.product_id)
        if not product or not product.get("in_stock") or product.get("status") == "deleted":
            continue
        if product.get("seller_id") != co.seller_id:   # savat = bitta sotuvchi
            continue
        if buyer["id"] == product["seller_id"]:
            continue
        qty = it.quantity
        stock = product.get("stock_count")
        if stock is not None:
            qty = min(qty, int(stock))
        if qty <= 0:
            continue
        line = qty * float(product["price"])
        grand += line
        oid = db.create_order(
            buyer_id=buyer["id"], seller_id=co.seller_id, product_id=it.product_id,
            quantity=qty, total_price=line, delivery_address=address,
            buyer_lat=lat, buyer_lon=lon, payment_method=co.payment_method,
            delivery_type=co.delivery_type,
        )
        created.append(oid)

    if not created:
        raise HTTPException(status_code=409, detail="nothing_available")
    group_id = str(created[0])
    db.set_orders_group(created, group_id)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=ORDER_TTL_SECONDS)
    db.set_group_deadline(group_id, deadline)
    for oid in created:
        db.mark_order_notify_pending(oid)
    return {"ok": True, "group_id": group_id, "count": len(created), "total": grand}


import time as _time
_RATE = {}  # (bucket, user_id) -> [timestamps]


def _rate_limit(bucket, user_id, max_calls, window):
    """Oddiy xotira-ichi throttle (jarayon bo'yicha). Limitdan oshsa 429.
    Spam/cost himoyasi: AI (DeepSeek puli), admin/seller spam, buyurtma toshqini."""
    now = _time.time()
    key = (bucket, user_id)
    arr = [t for t in _RATE.get(key, ()) if now - t < window]
    if len(arr) >= max_calls:
        raise HTTPException(status_code=429, detail="too_many_requests")
    arr.append(now)
    _RATE[key] = arr
    # vaqti-vaqti bilan eski kalitlarni tozalaymiz (xotira o'smasin)
    if len(_RATE) > 5000:
        for k in [k for k, v in list(_RATE.items()) if not any(now - t < window for t in v)]:
            _RATE.pop(k, None)


def _buyer_from_auth(authorization):
    """initData'dan xaridorni (DB user) qaytaradi yoki 401/403 ko'taradi."""
    auth = require_auth(authorization)
    tg_id = (auth.get("user") or {}).get("id")
    if not tg_id:
        raise HTTPException(status_code=401, detail="no_user")
    buyer = db.get_user_by_telegram_id(tg_id)
    if not buyer:
        raise HTTPException(status_code=403, detail="not_registered")
    return buyer


@app.get("/api/me")
def api_me(authorization: str = Header(None)):
    b = dict(_buyer_from_auth(authorization))
    return {
        "id": b.get("id"), "name": b.get("name"), "phone": b.get("phone_number"),
        "username": b.get("telegram_username"), "role": b.get("role"),
        "language": b.get("language"), "created_at": b.get("created_at"),
        "is_approved": b.get("is_approved"),
        "referral_code": b.get("referral_code"), "referral_count": b.get("referral_count"),
    }


@app.get("/api/my/orders")
def api_my_orders(authorization: str = Header(None)):
    buyer = _buyer_from_auth(authorization)
    return _rows(db.get_buyer_orders_list(buyer["id"]))


@app.get("/api/my/debts")
def api_my_debts(authorization: str = Header(None)):
    buyer = _buyer_from_auth(authorization)
    return _rows(db.get_buyer_open_debts(buyer["id"]))


class ReviewIn(BaseModel):
    seller_rating: int
    product_rating: Optional[int] = None
    comment: Optional[str] = None


@app.post("/api/order/{order_id}/review")
async def api_review(order_id: int, body: ReviewIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    if order.get("buyer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="not_your_order")
    if order.get("status") != "delivered":
        raise HTTPException(status_code=409, detail="not_delivered")
    if db.order_review_exists(order_id, user["id"]):
        raise HTTPException(status_code=409, detail="already_reviewed")
    sr = body.seller_rating
    if not isinstance(sr, int) or not (1 <= sr <= 5):
        raise HTTPException(status_code=400, detail="bad_rating")
    pr = body.product_rating
    if pr is not None and not (1 <= pr <= 5):
        raise HTTPException(status_code=400, detail="bad_product_rating")
    comment = (body.comment or "").strip() or None
    db.create_review(order_id, order["seller_id"], user["id"], sr, comment,
                     order.get("product_id"), pr)
    try:
        if order.get("seller_tg"):
            stars = "⭐" * sr
            txt = f"{stars} {fmt_order_id(order_id)} — yangi baho"
            if comment:
                txt += f"\n💬 {html.escape(comment)}"
            await _tg_call("sendMessage", {"chat_id": order["seller_tg"], "text": txt, "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"review notify xato (order {order_id}): {e}")
    return {"ok": True}


@app.post("/api/order/{order_id}/cancel")
async def api_buyer_cancel(order_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    if order.get("buyer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="not_your_order")
    if order.get("status") != "pending":
        raise HTTPException(status_code=409, detail="not_pending")
    if order.get("order_group_id"):
        # Guruh (savat) buyurtmasini app'dan yakka bekor qilish hozircha qo'llanmaydi
        raise HTTPException(status_code=409, detail="group_cancel_unsupported")
    db.update_order_status(order_id, "cancelled")
    try:
        seller = db.get_user_by_id(order["seller_id"]) if order.get("seller_id") else None
        slang = get_user_lang(seller) if seller else DEFAULT_LANG
        if order.get("seller_tg"):
            await _tg_call("sendMessage", {
                "chat_id": order["seller_tg"],
                "text": t(slang, "order_cancelled_notify", oid=fmt_order_id(order_id),
                          pname=html.escape(order.get("product_name") or "")),
                "parse_mode": "HTML"})
        cid = order.get("notify_chat_id")
        mid = order.get("notify_message_id")
        if cid and mid:
            final = (order.get("notify_caption") or "") + "\n\n❌ Xaridor bekor qildi"
            await _tg_call("editMessageText", {
                "chat_id": cid, "message_id": mid, "text": final,
                "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}})
    except Exception as e:
        logging.warning(f"buyer cancel notify xato (order {order_id}): {e}")
    return {"ok": True}


class CancelReqIn(BaseModel):
    reason: Optional[str] = None


@app.post("/api/order/{order_id}/request-cancel")
async def api_request_cancel(order_id: int, body: CancelReqIn, authorization: str = Header(None)):
    """Xaridor TASDIQLANGAN buyurtmani bekor qilishni so'raydi (nizo oqimi boshlanishi).
    Sotuvchiga rozilik so'rovi (rozi/rad tugmalari) yuboriladi — bot ularni ushlaydi."""
    user = dict(_buyer_from_auth(authorization))
    _rate_limit("cancel_req", user["id"], 10, 60)
    reason = (body.reason or "").strip() or ("—")
    if len(reason) > 500:
        raise HTTPException(status_code=400, detail="too_long")
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    if order.get("buyer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="not_your_order")
    if order.get("status") != "confirmed" or (order.get("cancel_state") or ""):
        raise HTTPException(status_code=409, detail="cancel_not_available")
    if not db.request_order_cancel(order_id, "buyer", reason):
        raise HTTPException(status_code=409, detail="cancel_not_available")
    try:
        seller = db.get_user_by_id(order["seller_id"]) if order.get("seller_id") else None
        slang = get_user_lang(seller) if seller else DEFAULT_LANG
        if order.get("seller_tg"):
            await _tg_call("sendMessage", {
                "chat_id": order["seller_tg"],
                "text": t(slang, "cancel_request_notify", oid=fmt_order_id(order_id),
                          pname=html.escape(order.get("product_name") or ""),
                          reason=html.escape(reason)),
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": [
                    [{"text": t(slang, "btn_cancel_agree"), "callback_data": f"cclagree_{order_id}"}],
                    [{"text": t(slang, "btn_cancel_deny"), "callback_data": f"ccldeny_{order_id}"}]]}})
    except Exception as e:
        logging.warning(f"request-cancel notify xato (order {order_id}): {e}")
    return {"ok": True}


class CancelRespondIn(BaseModel):
    agree: bool


@app.post("/api/order/{order_id}/cancel-respond")
async def api_cancel_respond(order_id: int, body: CancelRespondIn, authorization: str = Header(None)):
    """Xaridor SOTUVCHI boshlagan bekor so'roviga javob beradi: rozi (bekor) yoki rad (nizo)."""
    user = dict(_buyer_from_auth(authorization))
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    if order.get("buyer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="not_your_order")
    if order.get("cancel_state") != "requested":
        raise HTTPException(status_code=409, detail="cancel_already_handled")
    if order.get("cancel_by") == "buyer":
        raise HTTPException(status_code=409, detail="cancel_wait_other")  # o'zi so'ragan
    oid = fmt_order_id(order_id)
    pname = html.escape(order.get("product_name") or "")
    seller = db.get_user_by_id(order["seller_id"]) if order.get("seller_id") else None
    slang = get_user_lang(seller) if seller else DEFAULT_LANG
    if body.agree:
        if db.agree_order_cancel(order_id):
            try:
                db.restock_on_cancel(order["product_id"], order.get("quantity") or 1)
            except Exception as e:
                logging.warning(f"cancel-respond restock xato (order {order_id}): {e}")
        if order.get("seller_tg"):
            await _tg_call("sendMessage", {"chat_id": order["seller_tg"],
                           "text": t(slang, "cancel_agreed_notify", oid=oid, pname=pname),
                           "parse_mode": "HTML"})
        return {"ok": True, "cancelled": True}
    # rad — admin hakamligiga
    db.dispute_order_cancel(order_id)
    if order.get("seller_tg"):
        await _tg_call("sendMessage", {"chat_id": order["seller_tg"],
                       "text": t(slang, "cancel_denied_notify", oid=oid, pname=pname),
                       "parse_mode": "HTML"})
    try:
        if ADMIN_ID:
            await _tg_call("sendMessage", {"chat_id": ADMIN_ID,
                           "text": t(DEFAULT_LANG, "admin_dispute_notify", oid=oid, pname=pname,
                                     by=html.escape(user.get("name") or "xaridor"),
                                     reason=html.escape(order.get("cancel_reason") or "—")),
                           "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"cancel-respond admin notify xato (order {order_id}): {e}")
    return {"ok": True, "disputed": True}


def _order_party_or_403(user, order):
    if user.get("id") not in (order.get("buyer_id"), order.get("seller_id")) \
       and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_your_order")


@app.get("/api/order/{order_id}/messages")
def api_order_messages(order_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    _order_party_or_403(user, order)
    cp = order.get("shop_name") if user["id"] == order.get("buyer_id") else order.get("buyer_name")
    return {"me": user["id"], "counterparty": cp or "—",
            "messages": _rows(db.get_messages_by_order(order_id))}


class MsgIn(BaseModel):
    text: str


@app.post("/api/order/{order_id}/message")
async def api_send_message(order_id: int, body: MsgIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="too_long")
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    _order_party_or_403(user, order)

    if user["id"] == order.get("buyer_id"):
        receiver_id = order.get("seller_id")
        receiver_tg = order.get("seller_tg")
        sender_is_buyer = True
    else:
        receiver_id = order.get("buyer_id")
        receiver_tg = order.get("buyer_tg")
        sender_is_buyer = False
    db.create_message(order_id, user["id"], receiver_id, text)

    # Qabul qiluvchini Telegram orqali xabardor qilamiz (uning tilida) + bot'dan javob tugmasi
    try:
        receiver = db.get_user_by_id(receiver_id) if receiver_id else None
        rlang = get_user_lang(receiver) if receiver else DEFAULT_LANG
        if sender_is_buyer:
            sender_label = t(rlang, "sender_label_buyer", name=html.escape(user.get("name") or ""))
        else:
            sender_label = t(rlang, "sender_label_seller",
                             name=html.escape(user.get("shop_name") or user.get("name") or ""))
        if receiver_tg:
            await _tg_call("sendMessage", {
                "chat_id": receiver_tg,
                "text": t(rlang, "new_message_notify", oid=fmt_order_id(order_id),
                          sender=sender_label, msg=html.escape(text)),
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": [[
                    {"text": t(rlang, "btn_reply"), "callback_data": f"order_msg_{order_id}"}]]},
            })
    except Exception as e:
        logging.error(f"xabar bildirishnomasi xato (order {order_id}): {e}")
    return {"ok": True}


class MeEdit(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None


@app.patch("/api/me")
def api_edit_me(p: MeEdit, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    fields = {}
    if p.name is not None:
        nm = p.name.strip()
        if not nm or len(nm) > 60:
            raise HTTPException(status_code=400, detail="bad_name")
        fields["name"] = nm
    if p.phone is not None and p.phone.strip():
        ph = p.phone.strip()
        digits = ph.lstrip("+")
        if not digits.isdigit() or not (7 <= len(digits) <= 15):
            raise HTTPException(status_code=400, detail="bad_phone")
        fields["phone_number"] = ph
    if p.language is not None:
        if p.language not in ("uz", "ru"):
            raise HTTPException(status_code=400, detail="bad_language")
        fields["language"] = p.language
    if fields:
        db.update_user(user["id"], **fields)
    return {"ok": True}


# ============================================================
# SOTUVCHI PANELI (D bo'lagi)
# ============================================================
async def _tg_call(method, payload):
    """Telegram Bot API'ga to'g'ridan-to'g'ri chaqiruv (webapp bot token bilan)."""
    if not BOT_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload)
            return r.json()
    except Exception as e:
        logging.warning(f"Telegram {method} xato: {e}")
        return None


@app.get("/api/seller/orders")
def api_seller_orders(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_orders_list(user["id"]))


@app.get("/api/seller/products")
def api_seller_products(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_products_by_seller(user["id"]))


@app.get("/api/seller/reviews")
def api_seller_reviews(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_reviews(user["id"]))


@app.get("/api/seller/customers")
def api_seller_customers(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_customers(user["id"]))


@app.get("/api/seller/channels")
def api_seller_channels(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_channels(user["id"]))


class ChannelRemove(BaseModel):
    channel_id: str


@app.post("/api/seller/channel/remove")
def api_remove_channel(body: ChannelRemove, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    db.remove_seller_channel(user["id"], body.channel_id)
    return {"ok": True}


# ---- Xodimlar (multivendor) — faqat do'kon egasi ----
def _owner_shop(user):
    shop = db.get_shop_by_owner(user["id"])
    if not shop:
        raise HTTPException(status_code=403, detail="not_owner")
    return dict(shop)


def _staff_in_shop(shop_id, staff_id):
    for s in db.get_shop_staff(shop_id):
        if s.get("id") == staff_id:
            return s
    return None


@app.get("/api/seller/staff")
def api_staff(authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    shop = _owner_shop(user)
    return {"staff": _rows(db.get_shop_staff(shop["id"], include_owner=False)),
            "invites": _rows(db.get_active_invites(shop["id"]))}


@app.post("/api/seller/staff/invite")
def api_staff_invite(authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    shop = _owner_shop(user)
    code = db.create_invite(shop["id"], created_by=user["id"])
    return {"ok": True, "code": code}


@app.post("/api/seller/staff/{staff_id}/toggle")
def api_staff_toggle(staff_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    shop = _owner_shop(user)
    s = _staff_in_shop(shop["id"], staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="not_found")
    if s.get("staff_role") == "owner":
        raise HTTPException(status_code=400, detail="cant_owner")
    db.set_staff_active(staff_id, 0 if s.get("is_active") else 1)
    return {"ok": True, "is_active": 0 if s.get("is_active") else 1}


@app.delete("/api/seller/staff/{staff_id}")
def api_staff_remove(staff_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    shop = _owner_shop(user)
    s = _staff_in_shop(shop["id"], staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="not_found")
    if not db.remove_staff(staff_id):
        raise HTTPException(status_code=400, detail="cant_remove")
    return {"ok": True}


# ---- Rejalashtirilgan postlar ----
def _parse_dt(raw):
    from datetime import datetime, timezone
    raw = (raw or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None


class ScheduleIn(BaseModel):
    scheduled_at: str


@app.get("/api/seller/scheduled")
def api_seller_scheduled(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_scheduled_posts(user["id"]))


@app.post("/api/seller/product/{product_id}/schedule")
def api_schedule_product(product_id: int, body: ScheduleIn, authorization: str = Header(None)):
    from datetime import datetime, timezone
    user = dict(_buyer_from_auth(authorization))
    prod = _own_product_or_403(user, product_id)
    if prod.get("status") in ("deleted", "purged"):
        raise HTTPException(status_code=409, detail="product_unavailable")
    dt = _parse_dt(body.scheduled_at)
    if not dt:
        raise HTTPException(status_code=400, detail="bad_time")
    dt = dt.astimezone(timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="time_in_past")
    sa = dt.strftime("%Y-%m-%d %H:%M:%S")
    db.create_scheduled_post(product_id, prod["seller_id"], sa,
                             created_by=user["id"], image_id=prod.get("image_url"))
    db.set_product_status(product_id, "scheduled")  # belgilangan vaqtgacha yashiriladi
    return {"ok": True}


@app.post("/api/seller/scheduled/{sched_id}/cancel")
def api_cancel_scheduled(sched_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    sp = db.cancel_scheduled_post(sched_id, user["id"])
    if not sp:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        if sp.get("product_id"):
            db.set_product_status(sp["product_id"], "active")  # bekor -> mahsulot jonli bo'ladi
    except Exception as e:
        logging.warning(f"cancel schedule status xato: {e}")
    return {"ok": True}


# ---- Avto qayta-reklama (har kuni belgilangan soatda kanal/guruhga qayta post) ----
@app.get("/api/seller/autoreposts")
def api_seller_autoreposts(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_auto_reposts(user["id"]))


class AutoRepostIn(BaseModel):
    hour: int


@app.post("/api/seller/product/{product_id}/autorepost")
def api_set_autorepost(product_id: int, body: AutoRepostIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    prod = _own_product_or_403(user, product_id)
    if not isinstance(body.hour, int) or not (0 <= body.hour <= 23):
        raise HTTPException(status_code=400, detail="bad_hour")
    rid = db.upsert_auto_repost(product_id, prod["seller_id"], body.hour,
                                created_by=user["id"], image_id=prod.get("image_url"))
    return {"ok": True, "id": rid}


@app.post("/api/seller/autorepost/{repost_id}/cancel")
def api_cancel_autorepost(repost_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    db.cancel_auto_repost(repost_id, user["id"])
    return {"ok": True}


class ReplyIn(BaseModel):
    text: str


@app.post("/api/seller/review/{review_id}/reply")
async def api_review_reply(review_id: int, body: ReplyIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail="too_long")
    if not db.set_review_reply(review_id, user["id"], text):
        raise HTTPException(status_code=403, detail="not_your_review")
    try:
        rev = db.get_review_by_id(review_id)
        buyer = db.get_user_by_id(rev["buyer_id"]) if rev and rev.get("buyer_id") else None
        if buyer and buyer.get("telegram_id"):
            blang = get_user_lang(buyer)
            pname = html.escape(rev.get("product_name") or "")
            if blang == "ru":
                msg = f"💬 Продавец ответил на ваш отзыв ({pname}):\n\n{html.escape(text)}"
            else:
                msg = f"💬 Sotuvchi sharhingizga javob berdi ({pname}):\n\n{html.escape(text)}"
            await _tg_call("sendMessage", {"chat_id": buyer["telegram_id"], "text": msg,
                                           "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"review reply notify xato (review {review_id}): {e}")
    return {"ok": True}


@app.get("/api/seller/pending")
def api_seller_pending(authorization: str = Header(None)):
    """Ega tasdig'ini kutayotgan (xodim joylagan) mahsulotlar."""
    user = _buyer_from_auth(authorization)
    return _rows(db.get_seller_products_by_status(user["id"], "pending_owner"))


class ApproveIn(BaseModel):
    approve: bool = True


@app.post("/api/seller/product/{product_id}/approve")
def api_approve_product(product_id: int, body: ApproveIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    prod = db.get_product_by_id(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="not_found")
    if prod.get("seller_id") != user.get("id") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_owner")
    if prod.get("status") != "pending_owner":
        raise HTTPException(status_code=409, detail="not_pending")
    db.set_product_status(product_id, "active" if body.approve else "deleted")
    return {"ok": True}


@app.get("/api/seller/stats")
def api_seller_stats(authorization: str = Header(None)):
    user = _buyer_from_auth(authorization)
    raw = db.get_seller_stats(user["id"]) or {}
    stats = dict(raw)
    try:
        stats["avg_rating"] = round(float(db.get_seller_avg_rating(user["id"]) or 0), 1)
    except Exception:
        stats["avg_rating"] = 0
    debts = db.get_seller_open_debts(user["id"]) or []
    stats["open_debt_total"] = sum(float(d.get("total_due") or 0) for d in debts)
    stats["open_debt_count"] = len(debts)
    return stats


_SHOP_FIELDS = ("shop_name", "shop_address", "shop_landmark", "working_days",
                "working_hours", "phone_number", "card_number", "card_owner",
                "card_type", "shop_lat", "shop_lon")
_VALID_CARD = {"uzcard", "humo", "visa", "mastercard"}


@app.get("/api/seller/shop")
def api_get_shop(authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    out = {k: user.get(k) for k in _SHOP_FIELDS}
    shop = db.get_shop_by_owner(user["id"])
    out["payment_mode"] = (dict(shop).get("payment_mode") if shop else None) or "shop"
    out["is_owner"] = bool(shop)
    return out


class ShopEdit(BaseModel):
    shop_name: Optional[str] = None
    shop_address: Optional[str] = None
    shop_landmark: Optional[str] = None
    working_days: Optional[str] = None
    working_hours: Optional[str] = None
    phone: Optional[str] = None
    card_number: Optional[str] = None
    card_owner: Optional[str] = None
    card_type: Optional[str] = None
    payment_mode: Optional[str] = None   # 'shop' | 'staff' (multivendor karta yo'nalishi)
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.patch("/api/seller/shop")
def api_edit_shop(p: ShopEdit, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    if user.get("role") not in ("seller", "admin") and not user.get("is_approved"):
        raise HTTPException(status_code=403, detail="not_seller")
    fields = {}
    if p.shop_name is not None:
        nm = p.shop_name.strip()
        if not nm:
            raise HTTPException(status_code=400, detail="name_required")
        fields["shop_name"] = nm
    for attr, col in (("shop_address", "shop_address"), ("shop_landmark", "shop_landmark"),
                      ("working_days", "working_days"), ("working_hours", "working_hours"),
                      ("card_owner", "card_owner")):
        v = getattr(p, attr)
        if v is not None:
            fields[col] = v.strip() or None
    if p.phone is not None and p.phone.strip():
        ph = p.phone.strip()
        digits = ph.lstrip("+")
        if not digits.isdigit() or not (7 <= len(digits) <= 15):
            raise HTTPException(status_code=400, detail="bad_phone")
        fields["phone_number"] = ph
    if p.card_number is not None:
        cn = p.card_number.replace(" ", "").strip()
        if cn:
            if not cn.isdigit() or not (12 <= len(cn) <= 19):
                raise HTTPException(status_code=400, detail="bad_card")
            fields["card_number"] = cn
        else:
            fields["card_number"] = None
    if p.card_type is not None:
        if p.card_type and p.card_type not in _VALID_CARD:
            raise HTTPException(status_code=400, detail="bad_card_type")
        fields["card_type"] = p.card_type or None
    if p.lat is not None:
        fields["shop_lat"] = p.lat
    if p.lon is not None:
        fields["shop_lon"] = p.lon
    if fields:
        db.update_user(user["id"], **fields)
    # payment_mode shops jadvalida (faqat ega)
    if p.payment_mode is not None and p.payment_mode in ("shop", "staff"):
        shop = db.get_shop_by_owner(user["id"])
        if shop:
            db.update_shop(dict(shop)["id"], payment_mode=p.payment_mode)
    return {"ok": True}


class OrderAction(BaseModel):
    action: str  # 'confirm' | 'reject'


@app.post("/api/seller/order/{order_id}/action")
async def api_seller_order_action(order_id: int, body: OrderAction,
                                  authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    if body.action not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="bad_action")
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    # Egalik: faqat shu buyurtma sotuvchisi (egasi) yoki admin
    if not (order.get("seller_id") == user.get("id") or user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="not_your_order")
    # Faqat 'pending' holatdagiga ishlov beramiz (ikki marta tasdiq/bekorni oldini olamiz)
    if order.get("status") != "pending":
        raise HTTPException(status_code=409, detail="already_processed")

    new_status = "confirmed" if body.action == "confirm" else "cancelled"
    if new_status == "confirmed":
        try:
            db.decrement_stock_on_confirm(order["product_id"], order["quantity"])
        except Exception as e:
            logging.error(f"stock kamaytirish xato (order {order_id}): {e}")
    db.update_order_status(order_id, new_status)

    # Xaridorga bildirishnoma (xaridor tilida) — bot order_confirm bilan bir xil matn
    try:
        buyer = db.get_user_by_id(order["buyer_id"])
        blang = get_user_lang(buyer) if buyer else DEFAULT_LANG
        is_pickup = order.get("delivery_type") == "pickup"
        oid = fmt_order_id(order_id)
        pname = html.escape(order.get("product_name") or "")
        if new_status == "confirmed":
            key = "order_confirmed_pickup" if is_pickup else "order_confirmed_delivery"
        else:
            key = "order_cancelled_notify"
        txt = t(blang, key, oid=oid, pname=pname)
        if order.get("buyer_tg") and txt:
            await _tg_call("sendMessage", {
                "chat_id": order["buyer_tg"], "text": txt, "parse_mode": "HTML"})
    except Exception as e:
        logging.error(f"xaridorga xabar xato (order {order_id}): {e}")

    # Sotuvchining bildirishnoma xabaridagi tugmalarni olib tashlaymiz (eski tugma bosilmasin)
    try:
        chat_id = order.get("notify_chat_id")
        msg_id = order.get("notify_message_id")
        if chat_id and msg_id:
            final = (order.get("notify_caption") or "")
            final += "\n\n" + ("✅ Tasdiqlandi" if new_status == "confirmed" else "❌ Bekor qilindi")
            await _tg_call("editMessageText", {
                "chat_id": chat_id, "message_id": msg_id, "text": final,
                "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}})
    except Exception as e:
        logging.warning(f"sotuvchi xabarini tahrirlash xato (order {order_id}): {e}")

    return {"ok": True, "status": new_status}


class DeliverIn(BaseModel):
    settlement_type: str  # 'paid' | 'debt' | 'installment'
    paid: float = 0


@app.post("/api/seller/order/{order_id}/deliver")
async def api_deliver(order_id: int, body: DeliverIn, authorization: str = Header(None)):
    """Berish + to'lov holati (to'liq/qarz/bo'lib). Tasdiqlangan buyurtmani 'delivered'
    qiladi, settlement saqlaydi, xaridorga xabar (qarz bo'lsa qarz ham) yuboradi.
    Guruh (savat) buyurtmasi bo'lsa — butun guruhga."""
    user = dict(_buyer_from_auth(authorization))
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    if not (order.get("seller_id") == user.get("id") or user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="not_your_order")
    if order.get("status") != "confirmed":
        raise HTTPException(status_code=409, detail="not_confirmed")
    st = body.settlement_type
    if st not in ("paid", "debt", "installment"):
        raise HTTPException(status_code=400, detail="bad_settlement")

    gid = order.get("order_group_id")
    if gid:
        group_orders = db.get_orders_in_group(gid)
        total = sum(float(o.get("total_price") or 0) for o in group_orders)
    else:
        group_orders = None
        total = float(order.get("total_price") or 0)
    paid = max(0.0, min(float(body.paid or 0), total))
    due = round(total - paid, 2)
    eff = "paid" if due <= 0 else st

    if gid:
        for o in group_orders:
            db.update_order_status(o["id"], "delivered")
        db.set_group_settlement(gid, eff, paid, due)
        disp = fmt_order_id(int(gid))
    else:
        db.update_order_status(order_id, "delivered")
        db.set_order_settlement(order_id, eff, paid, due)
        disp = fmt_order_id(order_id)

    try:
        buyer = db.get_user_by_id(order["buyer_id"]) if order.get("buyer_id") else None
        blang = get_user_lang(buyer) if buyer else DEFAULT_LANG
        seller = db.get_user_by_id(order["seller_id"]) if order.get("seller_id") else None
        is_pickup = order.get("delivery_type") == "pickup"
        if gid:
            txt = t(blang, "grp_delivered_pickup" if is_pickup else "grp_delivered_delivery",
                    oid=disp, n=len(group_orders))
        else:
            txt = t(blang, "order_delivered_pickup" if is_pickup else "order_delivered_delivery",
                    oid=disp, pname=html.escape(order.get("product_name") or ""))
        if due > 0:
            shop = html.escape((seller.get("shop_name") or seller.get("name") or "") if seller else "")
            txt += t(blang, "buyer_debt_notify", shop=shop, due=fmt_price(due))
        if order.get("buyer_tg"):
            await _tg_call("sendMessage", {
                "chat_id": order["buyer_tg"], "text": txt, "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": [[
                    {"text": t(blang, "btn_leave_rating"), "callback_data": f"order_rate_{order_id}"}]]}})
    except Exception as e:
        logging.warning(f"deliver buyer notify xato (order {order_id}): {e}")
    return {"ok": True, "total": total, "paid": paid, "due": due}


# ---- Mahsulot boshqaruvi (D2) ----
MAX_PHOTO_BYTES = 6 * 1024 * 1024


def _own_product_or_403(user, product_id):
    prod = db.get_product_by_id(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="not_found")
    if not (prod.get("seller_id") == user.get("id") or user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="not_your_product")
    return prod


@app.post("/api/seller/product/photo")
async def api_product_photo(file: UploadFile = File(...), authorization: str = Header(None)):
    """Rasmni Telegram'ga yuborib file_id oladi (so'ng xabarni o'chiradi — file_id amal qiladi).
    Shunday qilib web upload (baytlar) bot ishlatadigan Telegram file_id'ga aylanadi."""
    user = dict(_buyer_from_auth(authorization))
    seller_tg = user.get("telegram_id")
    if not seller_tg:
        raise HTTPException(status_code=400, detail="no_chat")
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="no_token")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="too_large")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": str(seller_tg)},
                files={"photo": (file.filename or "photo.jpg", data,
                                 file.content_type or "image/jpeg")},
            )
            res = r.json()
    except Exception as e:
        logging.error(f"sendPhoto xato: {e}")
        raise HTTPException(status_code=502, detail="upload_failed")
    if not res.get("ok") or not (res.get("result") or {}).get("photo"):
        raise HTTPException(status_code=502, detail="telegram_rejected")
    msg = res["result"]
    file_id = msg["photo"][-1]["file_id"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
                              json={"chat_id": seller_tg, "message_id": msg["message_id"]})
    except Exception:
        pass
    return {"file_id": file_id}


class ProductIn(BaseModel):
    name: str
    price: float
    category_id: Optional[int] = None
    description: Optional[str] = None
    stock_count: Optional[int] = None
    image_url: Optional[str] = None  # eski: bitta file_id (moslik uchun)
    images: Optional[List[str]] = None  # galereya: file_id ro'yxati (1-chi = asosiy)


def _images_list(p):
    """ProductIn/ProductEdit'dan rasm ro'yxatini chiqaradi (images ustun, bo'lmasa image_url)."""
    if p.images is not None:
        return [f for f in p.images if f][:4]
    if p.image_url:
        return [p.image_url]
    return None


@app.post("/api/seller/product")
def api_create_product(p: ProductIn, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    name = (p.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name_required")
    if p.price is None or p.price <= 0:
        raise HTTPException(status_code=400, detail="bad_price")
    if p.stock_count is not None and p.stock_count < 0:
        raise HTTPException(status_code=400, detail="bad_stock")
    imgs = _images_list(p)
    pid = db.create_product(
        seller_id=user["id"], name=name, price=float(p.price),
        category_id=p.category_id, description=(p.description or "").strip() or None,
        image_url=(imgs[0] if imgs else None), stock_count=p.stock_count, created_by=user["id"],
    )
    if imgs:
        try:
            db.set_product_images(pid, imgs)
        except Exception as e:
            logging.warning(f"set_product_images xato (pid {pid}): {e}")
    fields = {"in_stock": 1, "status": "active"}
    if user.get("region_id"):
        fields["region_id"] = user["region_id"]
    try:
        db.update_product_fields(pid, **fields)
    except Exception as e:
        logging.warning(f"product post-fields xato (pid {pid}): {e}")
    return {"ok": True, "product_id": pid}


class ProductEdit(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    stock_count: Optional[int] = None
    image_url: Optional[str] = None
    images: Optional[List[str]] = None


@app.patch("/api/seller/product/{product_id}")
def api_edit_product(product_id: int, p: ProductEdit, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _own_product_or_403(user, product_id)
    fields = {}
    if p.name is not None:
        nm = p.name.strip()
        if not nm:
            raise HTTPException(status_code=400, detail="name_required")
        fields["name"] = nm
    if p.price is not None:
        if p.price <= 0:
            raise HTTPException(status_code=400, detail="bad_price")
        fields["price"] = float(p.price)
    if p.description is not None:
        fields["description"] = p.description.strip() or None
    if p.stock_count is not None:
        if p.stock_count < 0:
            raise HTTPException(status_code=400, detail="bad_stock")
        fields["stock_count"] = p.stock_count
    if fields:
        db.update_product_fields(product_id, **fields)
    # Rasmlar (galereya) — berilgan bo'lsa to'liq almashtiramiz (image_url ham sinxronlanadi)
    if p.images is not None:
        db.set_product_images(product_id, [f for f in p.images if f][:4])
    elif p.image_url is not None:
        db.update_product_fields(product_id, image_url=p.image_url)
    return {"ok": True}


@app.post("/api/seller/product/{product_id}/toggle")
def api_toggle_product(product_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _own_product_or_403(user, product_id)
    return {"ok": True, "in_stock": db.toggle_product_in_stock(product_id)}


@app.delete("/api/seller/product/{product_id}")
def api_delete_product(product_id: int, authorization: str = Header(None)):
    user = dict(_buyer_from_auth(authorization))
    _own_product_or_403(user, product_id)
    db.delete_product(product_id, deleted_by=user.get("id"), deleted_by_role=user.get("role"))
    return {"ok": True}


@app.get("/api/image/{file_id}")
async def api_image(file_id: str, request: Request = None):
    """Telegram file_id'ni haqiqiy rasmga aylantiradi (getFile → yuklab → cache → stream).
    Autentifikatsiyasiz (img-teglar header yubora olmaydi), lekin cache-miss (Telegram'ga
    yangi so'rov) IP bo'yicha cheklanadi — proksi sifatida suiiste'molni cheklaydi (audit #4)."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="no token")
    # Disk-cache (getFile rate-limitiga tushmaslik uchun) — keshlangan rasm cheklanmaydi
    safe = hashlib.sha256(file_id.encode()).hexdigest()
    cache_path = os.path.join(IMG_CACHE_DIR, safe + ".jpg")
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=604800"})
    # Cache-miss: Telegram'ga yangi so'rov — IP bo'yicha 60/min (hammerlashning oldini oladi)
    if request is not None:
        ip = (request.headers.get("x-forwarded-for") or
              (request.client.host if request.client else "?")).split(",")[0].strip()
        _rate_limit("img", ip, 60, 60)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            meta = await client.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                params={"file_id": file_id},
            )
            data = meta.json()
            if not data.get("ok"):
                raise HTTPException(status_code=404, detail="file not found")
            path = data["result"]["file_path"]
            img = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
            img.raise_for_status()
            content = img.content
        with open(cache_path, "wb") as f:
            f.write(content)
        return Response(content=content, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"image proxy xatosi ({file_id[:12]}...): {e}")
        raise HTTPException(status_code=502, detail="image fetch failed")


_bot_username_cache = {"value": None}


@app.get("/api/config")
async def api_config(authorization: str = Header(None)):
    require_auth(authorization)
    # bot username — buyurtma tugmasi bot'ga deep-link qilishi uchun (getMe, keshlanadi)
    if _bot_username_cache["value"] is None and BOT_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
                d = r.json()
                if d.get("ok"):
                    _bot_username_cache["value"] = d["result"]["username"]
        except Exception:
            pass
    return {"bot_username": _bot_username_cache["value"]}


@app.get("/api/health")
def api_health():
    return {"ok": True, "backend": db.backend}


# ============================================================
# ADMIN PANELI (G bo'lagi) — faqat admin rolli foydalanuvchi
# Bot main.py'dagi admin handlerlarning to'liq parite ko'chirmasi.
# ============================================================
def _admin_from_auth(authorization):
    """initData'dan adminni (DB user) qaytaradi yoki 403. Admin = role=='admin' yoki ADMIN_ID."""
    user = dict(_buyer_from_auth(authorization))
    if user.get("role") != "admin" and user.get("telegram_id") != ADMIN_ID:
        raise HTTPException(status_code=403, detail="not_admin")
    return user


@app.get("/api/admin/stats")
def api_admin_stats(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return dict(db.get_admin_stats_summary() or {})


@app.get("/api/admin/seller-requests")
def api_admin_seller_requests(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return _rows(db.get_pending_seller_requests())


class SellerReqDecision(BaseModel):
    approve: bool = True


@app.post("/api/admin/seller-request/{user_id}")
async def api_admin_seller_decide(user_id: int, body: SellerReqDecision,
                                  authorization: str = Header(None)):
    """Sotuvchi arizasini tasdiqlash/rad etish — bot approve_seller/reject_seller bilan bir xil."""
    admin = _admin_from_auth(authorization)
    _rate_limit("admin_seller", admin["id"], 30, 60)
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="user_not_found")
    target = dict(target)
    if body.approve:
        db.update_user(user_id, is_approved=1, role="seller")
        # Tasdiqlangan sotuvchida do'kon bo'lishini kafolatlaymiz (idempotent, xodim bo'lmasa)
        try:
            if not db.get_staff_by_user(user_id):
                db.create_shop(
                    user_id,
                    name=target.get("shop_name"), address=target.get("shop_address"),
                    landmark=target.get("shop_landmark"), lat=target.get("shop_lat"),
                    lon=target.get("shop_lon"), working_days=target.get("working_days"),
                    working_hours=target.get("working_hours"), region_id=target.get("region_id"),
                    card_number=target.get("card_number"), card_owner=target.get("card_owner"),
                    card_type=target.get("card_type"),
                )
        except Exception as e:
            logging.error(f"admin approve: do'kon yaratilmadi (uid {user_id}): {e}")
    else:
        db.update_user(user_id, is_approved=0, role="buyer")
    req = db.get_seller_request_by_user(user_id)
    if req:
        db.update_seller_request(dict(req)["id"], "approved" if body.approve else "rejected")
    # Foydalanuvchiga uning tilida xabar
    try:
        if target.get("telegram_id"):
            tlang = get_user_lang(target)
            key = "approve_seller_notify" if body.approve else "reject_seller_notify"
            await _tg_call("sendMessage", {"chat_id": target["telegram_id"],
                                           "text": t(tlang, key), "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"admin seller decide notify xato (uid {user_id}): {e}")
    return {"ok": True, "approved": body.approve}


@app.get("/api/admin/users")
def api_admin_users(authorization: str = Header(None), q: str = Query(None),
                    offset: int = Query(0)):
    _admin_from_auth(authorization)
    q = (q or "").strip()
    if q:
        return {"total": None, "offset": 0, "users": _rows(db.search_users(q, limit=30))}
    total, rows = db.get_users_paginated(limit=ADMIN_PAGE, offset=max(0, offset))
    return {"total": total, "offset": offset, "users": _rows(rows)}


ADMIN_PAGE = 15


class UserBlockIn(BaseModel):
    block: bool


@app.post("/api/admin/user/{user_id}/block")
def api_admin_block_user(user_id: int, body: UserBlockIn, authorization: str = Header(None)):
    admin = _admin_from_auth(authorization)
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="user_not_found")
    if dict(target).get("role") == "admin":
        raise HTTPException(status_code=400, detail="cant_block_admin")
    db.update_user(user_id, is_blocked=1 if body.block else 0)
    return {"ok": True, "is_blocked": 1 if body.block else 0}


@app.get("/api/admin/disputes")
def api_admin_disputes(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return _rows(db.get_disputed_orders())


@app.get("/api/admin/dispute/{order_id}/messages")
def api_admin_dispute_messages(order_id: int, authorization: str = Header(None)):
    _admin_from_auth(authorization)
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    return {"messages": _rows(db.get_dispute_messages(order_id))}


class DisputeResolveIn(BaseModel):
    cancel: bool   # True -> buyurtmani bekor; False -> kuchda qoldirish


@app.post("/api/admin/dispute/{order_id}/resolve")
async def api_admin_resolve_dispute(order_id: int, body: DisputeResolveIn,
                                    authorization: str = Header(None)):
    """Nizoni hal qilish — bot admin_resolve_dispute bilan bir xil (ikkala tomonga xabar)."""
    _admin_from_auth(authorization)
    order = db.get_order_by_id(order_id)
    if not order or order.get("cancel_state") != "disputed":
        raise HTTPException(status_code=404, detail="dispute_not_found")
    do_cancel = bool(body.cancel)
    if not db.resolve_order_dispute(order_id, do_cancel):
        raise HTTPException(status_code=409, detail="not_resolved")
    if do_cancel:
        # Bekorda omborni qaytaramiz (confirmed buyurtma stokni kamaytirgan edi)
        try:
            db.restock_on_cancel(order["product_id"], order.get("quantity") or 1)
        except Exception as e:
            logging.warning(f"dispute restock xato (order {order_id}): {e}")
    oid = fmt_order_id(order_id)
    pname = html.escape(order.get("product_name") or "")
    key = "dispute_resolved_cancel" if do_cancel else "dispute_resolved_keep"
    for uid_key, tg_key in (("buyer_id", "buyer_tg"), ("seller_id", "seller_tg")):
        try:
            u = db.get_user_by_id(order[uid_key]) if order.get(uid_key) else None
            ulang = get_user_lang(u) if u else DEFAULT_LANG
            if order.get(tg_key):
                await _tg_call("sendMessage", {"chat_id": order[tg_key],
                               "text": t(ulang, key, oid=oid, pname=pname), "parse_mode": "HTML"})
        except Exception as e:
            logging.warning(f"dispute resolve notify xato (order {order_id}): {e}")
    return {"ok": True, "cancelled": do_cancel}


class DisputeMsgIn(BaseModel):
    text: str
    party: str   # 'buyer' | 'seller' — kimga (qaysi tomonga) yoziladi


@app.post("/api/admin/dispute/{order_id}/message")
async def api_admin_dispute_message(order_id: int, body: DisputeMsgIn,
                                    authorization: str = Header(None)):
    """Admin nizo bo'yicha tomonga xabar yozadi (bot admin_dispute_msg bilan bir xil)."""
    admin = _admin_from_auth(authorization)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="too_long")
    if body.party not in ("buyer", "seller"):
        raise HTTPException(status_code=400, detail="bad_party")
    order = db.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="not_found")
    db.add_dispute_message(order_id, body.party, "admin", admin["id"],
                           admin.get("name") or "Admin", text)
    try:
        tg = order.get("buyer_tg") if body.party == "buyer" else order.get("seller_tg")
        uid = order.get("buyer_id") if body.party == "buyer" else order.get("seller_id")
        u = db.get_user_by_id(uid) if uid else None
        ulang = get_user_lang(u) if u else DEFAULT_LANG
        if tg:
            oid = fmt_order_id(order_id)
            await _tg_call("sendMessage", {"chat_id": tg,
                           "text": t(ulang, "dispute_admin_message", oid=oid, msg=html.escape(text)),
                           "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"dispute admin msg notify xato (order {order_id}): {e}")
    return {"ok": True}


@app.get("/api/admin/shops")
def api_admin_shops(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return _rows(db.get_all_shops())


@app.get("/api/admin/orders")
def api_admin_orders(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return _rows(db.get_all_orders())


@app.get("/api/admin/products")
def api_admin_products(authorization: str = Header(None)):
    _admin_from_auth(authorization)
    return _rows(db.get_admin_products_summary(limit=30))


@app.delete("/api/admin/product/{product_id}")
def api_admin_delete_product(product_id: int, authorization: str = Header(None)):
    admin = _admin_from_auth(authorization)
    prod = db.get_product_by_id(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="not_found")
    db.delete_product(product_id, deleted_by=admin["id"], deleted_by_role="admin")
    return {"ok": True}


class BroadcastIn(BaseModel):
    text: str
    target: str = "all"   # 'all' | 'buyer' | 'seller'


@app.post("/api/admin/broadcast")
async def api_admin_broadcast(body: BroadcastIn, authorization: str = Header(None)):
    """Ommaviy xabar — barcha (yoki rol bo'yicha) foydalanuvchilarga yuboradi."""
    admin = _admin_from_auth(authorization)
    _rate_limit("admin_broadcast", admin["id"], 3, 600)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="too_long")
    role = body.target if body.target in ("buyer", "seller") else None
    users = db.get_all_users(role=role)
    sent, failed = 0, 0
    for u in users:
        u = dict(u)
        tg = u.get("telegram_id")
        if not tg or u.get("is_blocked"):
            continue
        res = await _tg_call("sendMessage", {"chat_id": tg, "text": html.escape(text)})
        if res and res.get("ok"):
            sent += 1
        else:
            failed += 1
    return {"ok": True, "sent": sent, "failed": failed, "total": len(users)}


# ============================================================
# FRONTEND (static)
# ============================================================
@app.get("/")
def index():
    # no-cache: Mini App HTML yangilansa, Telegram darhol yangi versiyani olsin
    # (aks holda eski dizayn keshda qolib ketadi).
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
