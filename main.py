import logging
import math
import html
import os
import io
import asyncio

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit(
        "❌ BOT_TOKEN topilmadi. Uni .env faylida belgilang:  BOT_TOKEN=...\n"
        "   (Token endi kodda saqlanmaydi — xavfsizlik uchun.)"
    )
ADMIN_ID = int(os.getenv("ADMIN_ID", "722266370"))

# Markaziy kanal — mahsulotlar avtomatik shu yerga post qilinadi.
# .env faylida belgilang:  CHANNEL_ID=@TezBozorUz24
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Rasmiy kanal havolasi (panellardagi "kanalga o'tish" tugmasi uchun).
# @username bo'lsa — t.me havolasiga aylantiramiz.
CHANNEL_URL = f"https://t.me/{str(CHANNEL_ID).lstrip('@')}" if CHANNEL_ID and str(CHANNEL_ID).startswith('@') else None

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler, PicklePersistence
from telegram.error import Forbidden, BadRequest
from database import Database
from languages import t, LANGS, DEFAULT_LANG, get_user_lang, region_name, category_name, all_labels as _lang_labels
from tezbozor_design import (fmt_price, fmt_phone, fmt_order_id, fmt_status, fmt_rating,
                             fmt_datetime, is_shop_open_now, M,
                             human_address, best_location_text, maps_link, looks_like_coords)
import ai_assistant
import ad_design
from telegram.constants import ChatAction

logging.basicConfig(level=logging.INFO)

db = Database()


# ============================================================
# TIL (i18n) YORDAMCHILARI
# ============================================================
# Foydalanuvchi tilini ishonchli aniqlash: sessiya keshi -> DB -> default.
# T(update, context, 'kalit', ...) — joriy til bo'yicha matn qaytaradi.

def get_lang(update, context):
    """Joriy foydalanuvchi tili: context kesh -> DB -> 'uz'."""
    try:
        if context is not None:
            cached = context.user_data.get('lang')
            if cached in LANGS:
                return cached
    except Exception:
        pass
    try:
        u = db.get_user_by_telegram_id(update.effective_user.id)
        if u and (u.get('language') in LANGS):
            if context is not None:
                context.user_data['lang'] = u['language']
            return u['language']
    except Exception:
        pass
    return DEFAULT_LANG


def T(update, context, key, **kwargs):
    """Qisqartma: joriy til bo'yicha tarjima qaytaradi."""
    return t(get_lang(update, context), key, **kwargs)


def set_user_lang(update, context, lang):
    """Tilni tanlaydi: sessiya keshi + DB (foydalanuvchi mavjud bo'lsa)."""
    if lang not in LANGS:
        lang = DEFAULT_LANG
    if context is not None:
        context.user_data['lang'] = lang
    try:
        u = db.get_user_by_telegram_id(update.effective_user.id)
        if u:
            db.update_user(u['id'], language=lang)
    except Exception as e:
        logging.error(f"Til saqlanmadi: {e}")
    return lang


# Pastki (Reply) klaviatura tugmalari — har bir kalit ikkala tilda ham mavjud.
# Foydalanuvchi qaysi tilda yozsa ham, tugmani kanonik harakat (action) ga aylantiramiz.
_BOTTOM_BTN_KEYS = [
    'btn_search_menu', 'btn_search', 'btn_categories', 'btn_my_orders', 'btn_profile',
    'btn_add_product', 'btn_my_products', 'btn_orders',
    'btn_home', 'btn_contact_admin',
]


def bottom_action(text):
    """Pastki menyu tugma matni (uz yoki ru) -> kanonik kalit yoki None."""
    for key in _BOTTOM_BTN_KEYS:
        if text in _lang_labels(key):
            return key
    return None


def all_bottom_menu_texts():
    """Barcha tillardagi pastki menyu tugma matnlari (cancel_filter uchun)."""
    texts = []
    for key in _BOTTOM_BTN_KEYS:
        texts.extend(_lang_labels(key))
    return texts


def buyer_bottom_kb(lang):
    """Xaridor rejimidagi pastki Reply klaviatura (tanlangan tilda)."""
    return ReplyKeyboardMarkup([
        [KeyboardButton(t(lang, 'btn_search_menu'))],
        [KeyboardButton(t(lang, 'btn_my_orders')), KeyboardButton(t(lang, 'btn_profile'))],
        [KeyboardButton(t(lang, 'btn_contact_admin')), KeyboardButton(t(lang, 'btn_home'))],
    ], resize_keyboard=True)


def seller_bottom_kb(lang):
    """Sotuvchi rejimidagi pastki Reply klaviatura (tanlangan tilda)."""
    return ReplyKeyboardMarkup([
        [KeyboardButton(t(lang, 'btn_add_product')), KeyboardButton(t(lang, 'btn_my_products'))],
        [KeyboardButton(t(lang, 'btn_orders')), KeyboardButton(t(lang, 'btn_profile'))],
        [KeyboardButton(t(lang, 'btn_contact_admin')), KeyboardButton(t(lang, 'btn_home'))],
    ], resize_keyboard=True)


def haversine_km(lat1, lon1, lat2, lon2):
    """Ikki nuqta orasidagi taxminiy yo'l masofasi (km).
    Haversine (qush uchishi) + 1.35 koeffitsient = yo'l masofasi taxmini."""
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2) ** 2)
    straight = 2 * R * math.asin(math.sqrt(a))
    # Yo'l masofasi taxminan 35% uzoqroq (O'zbekiston yo'llari uchun)
    return round(straight * 1.35, 1)


# ============================================================
# XARIDOR LOKATSIYASINI ESLAB QOLISH (masofani izchil ko'rsatish uchun)
# ============================================================
# Muammo: masofa qidiruv ro'yxatida ko'rinardi, lekin mahsulot/ do'kon
# sahifasida yo'qolardi (lokatsiya saqlanmagani uchun). Xaridor lokatsiyani
# bir marta yuborsa — uni eslab qolamiz va hamma joyda masofani ko'rsatamiz.

def remember_buyer_geo(context, lat, lon):
    """Xaridor yuborgan lokatsiyani eslab qoladi (keyingi ekranlarda masofa uchun)."""
    try:
        if lat is None or lon is None:
            return
        context.user_data['buyer_geo'] = {'lat': float(lat), 'lon': float(lon)}
    except (TypeError, ValueError):
        pass


def get_buyer_geo(context):
    """Eslab qolingan xaridor lokatsiyasi -> (lat, lon) yoki (None, None)."""
    g = context.user_data.get('buyer_geo') or {}
    return g.get('lat'), g.get('lon')


def distance_line_to_shop(context, shop_lat, shop_lon, prefix="\n📏 Masofa: ~"):
    """Eslab qolingan xaridor lokatsiyasidan do'kongacha masofa qatori.
    Lokatsiya yoki koordinata bo'lmasa — bo'sh satr."""
    b_lat, b_lon = get_buyer_geo(context)
    if b_lat is None or b_lon is None or shop_lat is None or shop_lon is None:
        return ""
    d = haversine_km(b_lat, b_lon, shop_lat, shop_lon)
    if d is None:
        return ""
    return f"{prefix}{d:.1f} km"


# ============================================================
# REVERSE GEOCODING — koordinatani o'qiladigan manzilga aylantirish
# ============================================================
# Lokatsiya yuborilganda uni "Chilonzor t., Bunyodkor ko'chasi" kabi matnga
# aylantiramiz, shunda foydalanuvchi joyni tushunadi (xom raqamlar emas).
#
# Sukut bo'yicha bepul OpenStreetMap Nominatim ishlatiladi (kalit kerak emas).
# O'zbekiston uchun aniqroq natija xohlasangiz, pastdagi YANDEX bloki izohini
# oching va YANDEX_GEOCODER_KEY ni .env ga qo'shing.
#
# MUHIM: bu funksiya HECH QACHON xato tashlamaydi — tarmoq ishlamasa None
# qaytaradi va manzil ko'rsatuvi mo'ljal + xarita havolasiga "tushadi".

GEOCODER_ENABLED = True            # False qilsangiz — tarmoqqa umuman chiqmaydi
_GEO_CACHE = {}                    # {(lat5, lon5): "manzil matni"} — oddiy xotira keshi


async def reverse_geocode(lat, lon):
    """Koordinata -> o'qiladigan qisqa manzil (eng yaxshi harakat). Aks holda None."""
    if not GEOCODER_ENABLED or lat is None or lon is None:
        return None
    try:
        key = (round(float(lat), 5), round(float(lon), 5))
    except (TypeError, ValueError):
        return None
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]

    text = None
    try:
        import httpx  # python-telegram-bot bilan birga keladi

        # --- YANDEX (ixtiyoriy, aniqroq) -------------------------------------
        # yandex_key = os.getenv("YANDEX_GEOCODER_KEY")
        # if yandex_key:
        #     async with httpx.AsyncClient(timeout=6.0) as client:
        #         r = await client.get(
        #             "https://geocode-maps.yandex.ru/1.x/",
        #             params={"apikey": yandex_key, "format": "json",
        #                     "geocode": f"{key[1]},{key[0]}", "lang": "uz_UZ"},
        #         )
        #         if r.status_code == 200:
        #             fm = (r.json()["response"]["GeoObjectCollection"]
        #                   ["featureMember"])
        #             if fm:
        #                 text = fm[0]["GeoObject"]["metaDataProperty"] \
        #                     ["GeocoderMetaData"]["text"]
        # ---------------------------------------------------------------------

        if not text:
            # OpenStreetMap Nominatim (bepul, kalitsiz)
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": key[0], "lon": key[1], "format": "jsonv2",
                        "accept-language": "uz,ru,en",
                        "zoom": "18", "addressdetails": "1",
                    },
                    headers={"User-Agent": "TezBozorBot/1.0 (Telegram marketplace)"},
                )
                if r.status_code == 200:
                    data = r.json()
                    addr = data.get("address") or {}
                    road = (addr.get("road") or addr.get("pedestrian")
                            or addr.get("residential"))
                    house = addr.get("house_number")
                    district = (addr.get("city_district") or addr.get("suburb")
                                or addr.get("county") or addr.get("town")
                                or addr.get("village"))
                    city = addr.get("city") or addr.get("state")
                    parts = []
                    if road:
                        parts.append(f"{road} {house}".strip() if house else road)
                    if district:
                        parts.append(district)
                    if city and city not in parts:
                        parts.append(city)
                    text = ", ".join(p for p in parts if p) or data.get("display_name")
    except Exception as e:
        logging.warning(f"reverse_geocode xatosi: {e}")
        text = None

    if text:
        text = text.strip()[:200]
        _GEO_CACHE[key] = text
    return text


async def resolve_shop_address(lat, lon):
    """Lokatsiyadan saqlash uchun manzil matnini qaytaradi.
    Geocoding ishlasa — o'qiladigan manzil; aks holda None (xom koordinata SAQLANMAYDI)."""
    return await reverse_geocode(lat, lon)


import time as _time

# ============================================================
# SPAM / FLOOD HIMOYASI
# ============================================================

# Global flood tracker — bir foydalanuvchi juda ko'p so'rov yuborsa bloklash
_flood_tracker = {}  # {user_id: [timestamp, timestamp, ...]}
FLOOD_WINDOW = 10       # 10 soniya ichida
FLOOD_MAX_REQUESTS = 15  # 15 tadan ko'p so'rov = flood
FLOOD_BAN_DURATION = 60  # 60 soniya ban


def is_flood(user_id: int) -> bool:
    """Foydalanuvchi flood qilyaptimi? True bo'lsa — bloklash kerak."""
    now = _time.monotonic()
    if user_id not in _flood_tracker:
        _flood_tracker[user_id] = []

    # Eski yozuvlarni tozalaymiz
    _flood_tracker[user_id] = [t for t in _flood_tracker[user_id] if now - t < FLOOD_WINDOW]
    _flood_tracker[user_id].append(now)

    return len(_flood_tracker[user_id]) > FLOOD_MAX_REQUESTS


# Flood ban ro'yxati: {user_id: ban_expire_time}
_flood_bans = {}


def check_flood_ban(user_id: int) -> bool:
    """Foydalanuvchi flood ban da bo'lsa True qaytaradi."""
    now = _time.monotonic()
    if user_id in _flood_bans:
        if now < _flood_bans[user_id]:
            return True
        else:
            del _flood_bans[user_id]
    return False


def apply_flood_ban(user_id: int):
    """Foydalanuvchini vaqtincha ban qiladi."""
    _flood_bans[user_id] = _time.monotonic() + FLOOD_BAN_DURATION


def rate_limit(min_interval: float = 1.0):
    """Decorator: foydalanuvchi min_interval soniyadan tez-tez so'rov yuborsa, bloklanadi.
    Faqat CallbackQuery va Message handler'larda ishlaydi."""
    def decorator(func):
        import functools
        @functools.wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                # Flood ban tekshiruvi
                if check_flood_ban(uid):
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(T(update, context, 'flood_ban'), show_alert=True)
                        except Exception:
                            pass
                    return

                # Flood detection
                if is_flood(uid):
                    apply_flood_ban(uid)
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(T(update, context, 'flood_detected'), show_alert=True)
                        except Exception:
                            pass
                    elif update.message:
                        try:
                            await update.message.reply_text(T(update, context, 'flood_too_many'))
                        except Exception:
                            pass
                    return

                key = f'_rl_{func.__name__}'
                last = context.user_data.get(key, 0)
                now = _time.monotonic()
                if now - last < min_interval:
                    # Telegram'ga "loading" ko'rinmasligi uchun callback_query'ga javob beramiz
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(T(update, context, 'please_wait'))
                        except Exception:
                            pass
                    return
                context.user_data[key] = now
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


# Buyurtma spam oldini olish: bir foydalanuvchi bir mahsulotga 5 daqiqa ichida qayta buyurtma bera olmaydi
ORDER_COOLDOWN = 300  # 5 daqiqa


def check_order_spam(context, buyer_id: int, product_id: int) -> bool:
    """True bo'lsa — spam, buyurtma berish mumkin emas."""
    key = f'_order_cd_{buyer_id}_{product_id}'
    last = context.bot_data.get(key, 0)
    now = _time.monotonic()
    if now - last < ORDER_COOLDOWN:
        return True
    return False


def mark_order_placed(context, buyer_id: int, product_id: int):
    """Buyurtma berilganini belgilaymiz."""
    key = f'_order_cd_{buyer_id}_{product_id}'
    context.bot_data[key] = _time.monotonic()


def is_seller_capable(user):
    """Bir foydalanuvchi sotuvchi bo'lib ishlay oladimi? Do'kon nomi to'ldirilgan bo'lsa — ha."""
    return bool(user and user.get('shop_name'))


def get_active_mode(user, context):
    """Foydalanuvchi hozir qaysi rejimda ishlayapti: 'admin' | 'seller' | 'buyer'.
    Admin har doim admin. Boshqalar — sessiyadagi active_mode yoki role bo'yicha default."""
    if not user:
        return 'buyer'
    if user['role'] == 'admin':
        return 'admin'
    return context.user_data.get('active_mode') or user['role']


import re as _re


def normalize_phone(raw):
    """Telefonni standartlashtirish. Yaroqsiz bo'lsa None qaytaradi.
    Misol: '901234567' → '+998901234567'; '+998 90 123 45 67' → '+998901234567'"""
    if not raw:
        return None
    digits = _re.sub(r'\D', '', str(raw))
    if len(digits) == 9:
        digits = '998' + digits
    if len(digits) == 12 and digits.startswith('998'):
        return '+' + digits
    # Boshqa mamlakat raqamlari uchun ham bo'sh joy qoldiramiz: 10-15 raqam
    if 10 <= len(digits) <= 15:
        return '+' + digits
    return None


def normalize_telegram_username(raw):
    """Telegram username'ni standartlashtirish. Yaroqsiz bo'lsa None.
    '@user' yoki 'user' → 'user'. Faqat lotin harf/raqam/_; 5–32 belgi."""
    if not raw:
        return None
    u = str(raw).strip().lstrip('@')
    if 5 <= len(u) <= 32 and _re.match(r'^[A-Za-z][A-Za-z0-9_]{4,31}$', u):
        return u
    return None


def normalize_name(raw, min_len=2, max_len=50):
    """Ismni standartlashtirish. Bo'sh joylarni qisqartiradi."""
    if not raw:
        return None
    n = ' '.join(str(raw).split())
    if min_len <= len(n) <= max_len:
        return n
    return None


# Ruxsat etilgan ism belgilari: lotin/kirill harflar, bo'shliq, apostrof, defis, nuqta
_NAME_RE = _re.compile(r"^[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ'’‘ʻ.\- ]+$")


def validate_fullname(raw, max_len=60):
    """To'liq F.I.SH validatsiyasi.
    Talab: kamida 2 so'z (Familiya + Ism), har biri ≥2 harf, faqat harflar,
    umumiy uzunlik 5–{max_len}. Yaroqsiz bo'lsa None qaytaradi."""
    if not raw:
        return None
    n = ' '.join(str(raw).split())
    if not (5 <= len(n) <= max_len):
        return None
    if not _NAME_RE.match(n):
        return None
    # Kamida 2 ta mazmunli so'z (har biri 2+ harf)
    words = [w for w in n.split() if len(w) >= 2]
    if len(words) < 2:
        return None
    return n

# ============================================================
# CONVERSATION STATES
# Har bir ConversationHandler o'z alohida state raqamlarini ishlatishi kerak
# Aks holda state'lar bir-birini ustidan yozib ketadi (BUG FIX #1)
# ============================================================
(PHONE, NAME, ROLE, SELLER_CATEGORY, SHOP_NAME, SHOP_LANDMARK,
 SHOP_ADDRESS, WORKING_DAYS, WORKING_HOURS, TELEGRAM_USERNAME) = range(10)

# Til tanlash (ro'yxatdan o'tishdan oldin) — alohida raqam, boshqa banddagilar bilan to'qnashmaydi
SELECT_LANG = 200

(PRODUCT_NAME, PRODUCT_PRICE, PRODUCT_CATEGORY, PRODUCT_DESC, PRODUCT_PHOTO, PRODUCT_ATTRS) = range(10, 16)

# Mahsulotni tahrirlash — endi "bir oyna + qaysi qismni tanlash" usulida.
# Har bir maydon alohida fokuslangan tahrir holatiga ega.
(EDIT_FIELD_NAME, EDIT_FIELD_PRICE, EDIT_FIELD_CATEGORY,
 EDIT_FIELD_DESC, EDIT_FIELD_PHOTOS, EDIT_FIELD_ATTR) = range(20, 26)

(ORDER_QUANTITY, ORDER_DELIVERY_TYPE, ORDER_ADDRESS, ORDER_PAYMENT, ORDER_CONFIRM) = range(30, 35)

MESSAGE_TEXT = 40

(PRODUCT_RATING, PRODUCT_COMMENT, SELLER_RATING) = range(50, 53)

(EDIT_PROFILE_NAME, EDIT_PROFILE_PHONE,
 EDIT_SHOP_NAME, EDIT_SHOP_LANDMARK, EDIT_SHOP_ADDRESS,
 EDIT_WORKING_DAYS, EDIT_WORKING_HOURS, EDIT_TELEGRAM_USERNAME) = range(60, 68)

(EDIT_CARD_TYPE, EDIT_CARD_NUMBER, EDIT_CARD_OWNER) = range(70, 73)

(SELLER_PRODUCT_SEARCH,) = range(80, 81)
(CONTACT_ADMIN_MSG,) = range(90, 91)

# Savat (cart) rasmiylashtirish oqimi — yakka buyurtma oqimidan ALOHIDA holatlar,
# shunda mavjud order_conv'ga umuman tegmaymiz.
(CART_DELIVERY_TYPE, CART_ADDRESS, CART_PAYMENT, CART_CONFIRM) = range(100, 104)
LINK_CHANNEL_WAIT = 110  # Sotuvchi kanalini ulash holati (forward kutilmoqda)


# ============================================================
# START & REGISTRATION
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Referral kod tekshiruvi — faqat yangi foydalanuvchi uchun
    # /start REF12345 ko'rinishida kelishi mumkin (context.args ichida)
    if not user and context.args:
        ref_code = context.args[0].strip()
        # Deeplink emas — referral
        if not ref_code.startswith("product_"):
            referrer = db.get_user_by_referral_code(ref_code)
            if referrer:
                context.user_data['referred_by'] = referrer['id']
                logging.info(f"New user referred by {referrer['name']} (code={ref_code})")

    # Deeplink: /start product_123 — mahsulot sahifasiga o'tish
    if user and context.args:
        arg = context.args[0].strip()
        if arg.startswith("product_"):
            try:
                product_id = int(arg.replace("product_", ""))
                product = db.get_product_by_id(product_id)
                if product and product.get('in_stock'):
                    # Mahsulot sahifasini ko'rsatamiz
                    context.user_data['active_mode'] = 'buyer'
                    # Fake callback_query yaratish imkoni yo'q, shuning uchun to'g'ridan-to'g'ri
                    # mahsulot ma'lumotlarini yuboramiz
                    await _show_product_deeplink(update, context, product)
                    return ConversationHandler.END
                else:
                    await update.message.reply_text(
                        T(update, context, 'deeplink_product_unavailable'),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(T(update, context, 'btn_home'), callback_data="buyer_panel")
                        ]])
                    )
                    return ConversationHandler.END
            except (ValueError, TypeError):
                pass

    if user and user['role'] != 'admin' and update.effective_user.id == ADMIN_ID:
        db.update_user(user['id'], role='admin')
        user['role'] = 'admin'
        await update.message.reply_text(T(update, context, 'you_are_admin'))

    if user:
        if user['is_blocked']:
            await update.message.reply_text(t(user, 'blocked'))
            return ConversationHandler.END

        # Avvalgi conversation state'ni tozalaymiz (tilni saqlab qolamiz)
        context.user_data.clear()
        lang = get_user_lang(user)
        context.user_data['lang'] = lang

        # ReplyKeyboard ni yangilaymiz — har doim to'g'ri tugmalar ko'rinsin
        active = get_active_mode(user, context)
        if user['role'] == 'admin':
            await admin_panel(update, context)
        elif active == 'seller' or user['role'] == 'seller':
            await update.message.reply_text(
                t(lang, 'bottom_hint'),
                reply_markup=seller_bottom_kb(lang)
            )
            await seller_panel(update, context)
        else:
            await update.message.reply_text(
                t(lang, 'bottom_hint'),
                reply_markup=buyer_bottom_kb(lang)
            )
            await buyer_panel(update, context)
        return ConversationHandler.END
    else:
        return await registration_start(update, context)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    if not user:
        await update.message.reply_text(T(update, context, 'not_registered'))
        return ConversationHandler.END

    if user['role'] != 'admin' and update.effective_user.id == ADMIN_ID:
        db.update_user(user['id'], role='admin')
        user['role'] = 'admin'

    if user['role'] != 'admin':
        await update.message.reply_text(t(user, 'not_admin'))
        return ConversationHandler.END

    # Conversation state'ni tozalaymiz — /admin dan keyin bot ro'yxat jarayonida qolmasin
    context.user_data.clear()

    await admin_panel(update, context)
    return ConversationHandler.END


async def registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ro'yxatdan o'tishning birinchi qadami — tilni tanlash
    keyboard = [
        [InlineKeyboardButton(LANGS['uz'], callback_data="reglang_uz")],
        [InlineKeyboardButton(LANGS['ru'], callback_data="reglang_ru")],
    ]
    await update.message.reply_text(
        "🌐 Tilni tanlang / Выберите язык:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_LANG


async def registration_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Til tanlandi — endi telefon so'raymiz (tanlangan tilda)."""
    query = update.callback_query
    await query.answer()
    lang = query.data.split("_")[1]  # "reglang_uz" -> "uz"
    if lang not in LANGS:
        lang = DEFAULT_LANG
    context.user_data['lang'] = lang  # DB hali yo'q — sessiyada saqlaymiz

    keyboard = [[KeyboardButton(t(lang, 'phone_button'), request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await query.message.reply_text(
        t(lang, 'welcome_ask_phone'),
        reply_markup=reply_markup
    )
    return PHONE


async def registration_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        raw = update.message.contact.phone_number
    elif update.message.text:
        raw = update.message.text
    else:
        await update.message.reply_text(T(update, context, 'phone_send_prompt'))
        return PHONE

    phone = normalize_phone(raw)
    if not phone:
        await update.message.reply_text(T(update, context, 'phone_invalid'))
        return PHONE

    context.user_data['phone'] = phone
    logging.info(f"Phone normalized: {phone}")

    await update.message.reply_text(
        T(update, context, 'ask_name'),
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME


async def registration_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = validate_fullname(update.message.text, max_len=60)
    if not name:
        await update.message.reply_text(T(update, context, 'name_invalid'))
        return NAME

    context.user_data['name'] = name

    keyboard = [
        [InlineKeyboardButton(T(update, context, 'role_buyer'), callback_data="reg_buyer")],
        [InlineKeyboardButton(T(update, context, 'role_seller'), callback_data="reg_seller")],
    ]
    await update.message.reply_text(
        T(update, context, 'name_thanks_role', name=name),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ROLE


async def registration_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    role = query.data.split("_")[1]  # "reg_buyer" -> "buyer"
    context.user_data['role'] = role

    if role == 'seller':
        lang = get_lang(update, context)
        categories = db.get_all_categories()
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(f"{cat[2]} {category_name(cat[1], lang)}", callback_data=f"regcat_{cat[0]}")])

        await query.edit_message_text(
            T(update, context, 'seller_category_ask'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELLER_CATEGORY
    else:
        # Xaridor uchun ro'yxatdan o'tishni yakunlaymiz
        user_id = db.create_user(
            telegram_id=update.effective_user.id,
            phone_number=context.user_data['phone'],
            name=context.user_data['name'],
            role=role
        )
        # Tanlangan tilni saqlaymiz
        db.update_user(user_id, language=context.user_data.get('lang', DEFAULT_LANG))
        await query.edit_message_text(T(update, context, 'registration_success'))
        await buyer_panel(update, context)
        return ConversationHandler.END


async def registration_seller_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    context.user_data['seller_category'] = category_id

    await query.edit_message_text(T(update, context, 'shop_name_ask'))
    return SHOP_NAME


async def registration_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 80:
        await update.message.reply_text(T(update, context, 'shop_name_invalid'))
        return SHOP_NAME
    context.user_data['shop_name'] = name
    await update.message.reply_text(T(update, context, 'shop_landmark_ask'))
    return SHOP_LANDMARK


async def registration_shop_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    landmark = update.message.text.strip()
    if len(landmark) > 200:
        await update.message.reply_text(T(update, context, 'shop_landmark_too_long'))
        return SHOP_LANDMARK
    context.user_data['shop_landmark'] = landmark

    keyboard = [[KeyboardButton(T(update, context, 'send_location_button'), request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        T(update, context, 'shop_address_ask'),
        reply_markup=reply_markup
    )
    return SHOP_ADDRESS


async def registration_shop_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        # Koordinatani o'qiladigan manzilga aylantiramiz (xom raqam saqlamaymiz)
        address = await resolve_shop_address(lat, lon)
        if address:
            await update.message.reply_text(T(update, context, 'address_detected', address=address))
    else:
        address = update.message.text.strip()
        if len(address) < 5 or len(address) > 200:
            await update.message.reply_text(T(update, context, 'address_invalid'))
            return SHOP_ADDRESS
        lat, lon = None, None

    context.user_data['shop_address'] = address
    context.user_data['shop_lat'] = lat
    context.user_data['shop_lon'] = lon

    await update.message.reply_text(
        T(update, context, 'working_days_ask'),
        reply_markup=ReplyKeyboardRemove()
    )
    return WORKING_DAYS


async def registration_working_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = update.message.text.strip()
    if len(days) > 100:
        await update.message.reply_text(T(update, context, 'working_days_too_long'))
        return WORKING_DAYS
    context.user_data['working_days'] = days
    await update.message.reply_text(T(update, context, 'working_hours_ask'))
    return WORKING_HOURS


async def registration_working_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hours = update.message.text.strip()
    # Vaqtni qattiq validatsiya qilmaymiz (turli formatlar bo'lishi mumkin: "09-21", "9:00 dan 21:00 gacha")
    # Lekin parse qilib ko'ramiz, agar formatga to'g'ri kelsa — keyinchalik ish vaqti tekshiruvi uchun ishlatamiz.
    if len(hours) > 50:
        await update.message.reply_text(T(update, context, 'working_hours_too_long'))
        return WORKING_HOURS
    context.user_data['working_hours'] = hours
    await update.message.reply_text(T(update, context, 'username_ask'))
    return TELEGRAM_USERNAME


async def registration_telegram_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    if raw == '-' or raw.lower() in ('yoq', "yo'q", "yoʼq", 'no', 'none'):
        context.user_data['telegram_username'] = None
    else:
        u = normalize_telegram_username(raw)
        if not u:
            await update.message.reply_text(T(update, context, 'username_invalid'))
            return TELEGRAM_USERNAME
        context.user_data['telegram_username'] = u

    await complete_registration(update, context)
    return ConversationHandler.END


async def complete_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = context.user_data.get('role', 'buyer')

    # Admin tekshiruvi
    if update.effective_user.id == ADMIN_ID:
        role = 'admin'

    user_id = db.create_user(
        telegram_id=update.effective_user.id,
        phone_number=context.user_data['phone'],
        name=context.user_data['name'],
        role=role
    )
    # Tanlangan tilni saqlaymiz
    db.update_user(user_id, language=context.user_data.get('lang', DEFAULT_LANG))

    # Referral — agar /start REF... orqali kelgan bo'lsa
    referred_by = context.user_data.get('referred_by')
    if referred_by:
        try:
            db.update_user(user_id, referred_by=referred_by)
            db.increment_referral_count(referred_by)
            # Taklif qiluvchiga bildirishnoma (uning tilida)
            referrer = db.get_user_by_id(referred_by)
            if referrer and referrer.get('telegram_id'):
                try:
                    await context.bot.send_message(
                        chat_id=referrer['telegram_id'],
                        text=t(referrer, 'new_referral',
                               name=html.escape(context.user_data['name'])),
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logging.error(f"Referrerga bildirishnoma ketmadi: {e}")
        except Exception as e:
            logging.error(f"Referral saqlanmadi: {e}")

    shop_name = context.user_data.get('shop_name')
    if shop_name:
        db.update_user(
            user_id,
            shop_name=shop_name,
            shop_address=context.user_data.get('shop_address'),
            shop_landmark=context.user_data.get('shop_landmark'),
            shop_lat=context.user_data.get('shop_lat'),
            shop_lon=context.user_data.get('shop_lon'),
            working_days=context.user_data.get('working_days'),
            working_hours=context.user_data.get('working_hours'),
            telegram_username=context.user_data.get('telegram_username'),
            is_verified=1
        )

    # Sotuvchi uchun — admin tasdiqlashi kerak
    if role == 'seller':
        db.create_seller_request(user_id)
        db.update_user(user_id, is_approved=0)

        await update.message.reply_text(T(update, context, 'reg_success_seller'))

        # Adminga bildirishnoma (admin tilida — odatda matn maydon nomlari saqlanadi)
        try:
            user_name = html.escape(context.user_data.get('name') or '')
            shop = html.escape(shop_name or '')
            phone = context.user_data.get('phone') or ''
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🆕 <b>Yangi sotuvchi so'rovi!</b>\n\n"
                    f"👤 Ism: {user_name}\n"
                    f"📞 Telefon: {phone}\n"
                    f"🏪 Do'kon: {shop}\n"
                    f"📍 Manzil: {html.escape(context.user_data.get('shop_address') or '')}\n\n"
                    f"Tasdiqlash uchun: Admin panel → Sotuvchi so'rovlari"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_seller_{user_id}")],
                    [InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_seller_{user_id}")],
                ])
            )
        except Exception as e:
            logging.error(f"Admin bildirishnomasi ketmadi: {e}")

        await buyer_panel(update, context)
    elif role == 'admin':
        await update.message.reply_text(T(update, context, 'registration_success'))
        await admin_panel(update, context)
    else:
        await update.message.reply_text(T(update, context, 'registration_success'))
        await buyer_panel(update, context)

    return ConversationHandler.END


# ============================================================
# ROL ALMASHTIRISH (Xaridor ↔ Sotuvchi)
# Bitta akkaunt — ikkala rejim. role ustuni asosiy rolni saqlaydi,
# active_mode esa hozir qaysi panel ko'rsatilayotganini belgilaydi.
# ============================================================

async def switch_to_buyer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rol o'zgartirishdan oldin tasdiqlash so'raydi (sotuvchi → xaridor)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)
    await query.edit_message_text(
        t(lang, 'switch_to_buyer_confirm_text'),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_yes_to_buyer'), callback_data="do_switch_buyer")],
            [InlineKeyboardButton(t(lang, 'btn_no_stay'), callback_data="seller_panel")],
        ])
    )


async def switch_to_seller_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rol o'zgartirishdan oldin tasdiqlash so'raydi (xaridor → sotuvchi)."""
    query = update.callback_query
    await query.answer()
    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Do'kon yo'q bo'lsa — to'g'ridan-to'g'ri become_seller oqimiga (tasdiqsiz)
    if not is_seller_capable(user):
        await switch_to_seller(update, context)
        return

    lang = get_lang(update, context)
    await query.edit_message_text(
        t(lang, 'switch_to_seller_confirm_text'),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_yes_to_seller'), callback_data="do_switch_seller")],
            [InlineKeyboardButton(t(lang, 'btn_no_stay'), callback_data="buyer_panel")],
        ])
    )


async def switch_to_buyer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['active_mode'] = 'buyer'
    lang = get_lang(update, context)
    await buyer_panel(update, context)
    # Pastki menyuni ham xaridor variantiga o'tkazamiz
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t(lang, 'in_buyer_mode'),
        reply_markup=buyer_bottom_kb(lang)
    )


async def switch_to_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_by_telegram_id(update.effective_user.id)
    lang = get_lang(update, context)

    if is_seller_capable(user):
        # Do'kon ma'lumotlari bor — to'g'ridan-to'g'ri sotuvchi paneliga
        context.user_data['active_mode'] = 'seller'
        await seller_panel(update, context)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'in_seller_mode'),
            reply_markup=seller_bottom_kb(lang)
        )
        return

    # Do'kon yo'q — sotuvchi bo'lishni taklif qilamiz
    kb = [
        [InlineKeyboardButton(t(lang, 'btn_yes_become_seller'), callback_data="become_seller")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="buyer_panel")],
    ]
    await query.edit_message_text(
        t(lang, 'become_seller_prompt'),
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def become_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Sotuvchi bo'lish' jarayonini boshlaydi — mavjud akkauntga do'kon ma'lumotlari qo'shamiz."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(T(update, context, 'become_seller_start_text'))
    return SHOP_NAME


async def become_seller_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jarayonning so'nggi qadami — telegram username va DB ga yozish."""
    context.user_data['telegram_username'] = update.message.text.strip()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(
        user['id'],
        role='seller',
        shop_name=context.user_data.get('shop_name'),
        shop_address=context.user_data.get('shop_address'),
        shop_landmark=context.user_data.get('shop_landmark'),
        shop_lat=context.user_data.get('shop_lat'),
        shop_lon=context.user_data.get('shop_lon'),
        working_days=context.user_data.get('working_days'),
        working_hours=context.user_data.get('working_hours'),
        telegram_username=context.user_data.get('telegram_username'),
        is_verified=1,
        is_approved=0,
    )

    # Admin tasdiqlashi uchun so'rov yaratamiz
    db.create_seller_request(user['id'])

    await update.message.reply_text(T(update, context, 'become_seller_saved'))

    # Adminga bildirishnoma
    try:
        user_name = html.escape(user.get('name') or '')
        shop = html.escape(context.user_data.get('shop_name') or '')
        phone = user.get('phone_number') or ''
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🆕 <b>Yangi sotuvchi so'rovi!</b>\n\n"
                f"👤 Ism: {user_name}\n"
                f"📞 Telefon: {phone}\n"
                f"🏪 Do'kon: {shop}\n"
                f"📍 Manzil: {html.escape(context.user_data.get('shop_address') or '')}\n\n"
                f"Tasdiqlash uchun: Admin panel → Sotuvchi so'rovlari"
            ),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_seller_{user['id']}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_seller_{user['id']}")],
            ])
        )
    except Exception as e:
        logging.error(f"Admin bildirishnomasi ketmadi: {e}")

    context.user_data['active_mode'] = 'buyer'
    await buyer_panel(update, context)
    return ConversationHandler.END


async def reapply_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rad etilgan sotuvchi qayta so'rov yuboradi."""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text(T(update, context, 'user_not_found'))
        return

    lang = get_lang(update, context)

    # Yangi so'rov yaratish
    db.create_seller_request(user['id'])
    db.update_user(user['id'], is_approved=0, role='seller')

    await query.edit_message_text(
        t(lang, 'reapply_sent'),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_buyer_mode'), callback_data="do_switch_buyer")],
        ])
    )

    # Adminga bildirishnoma
    try:
        user_name = html.escape(user.get('name') or '')
        shop = html.escape(user.get('shop_name') or '')
        phone = user.get('phone_number') or ''
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🔄 <b>Qayta sotuvchi so'rovi!</b>\n\n"
                f"👤 Ism: {user_name}\n"
                f"📞 Telefon: {phone}\n"
                f"🏪 Do'kon: {shop}\n"
                f"📍 Manzil: {html.escape(user.get('shop_address') or '')}\n\n"
                f"Tasdiqlash uchun: Admin panel → Sotuvchi so'rovlari"
            ),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_seller_{user['id']}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_seller_{user['id']}")],
            ])
        )
    except Exception as e:
        logging.error(f"Admin bildirishnomasi ketmadi: {e}")


# ============================================================
# BUYER PANEL
# ============================================================

async def buyer_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    context.user_data['active_mode'] = 'buyer'
    context.user_data.pop('shop_ctx', None)  # do'kon konteksti tugadi
    lang = get_lang(update, context)

    # Sotuvchi rejimi tugmasi: agar do'koni bo'lsa — to'g'ri rejimga o'tadi;
    # bo'lmasa — "sotuvchi bo'lish" jarayonini boshlaydi
    seller_btn_label = t(lang, 'btn_seller_mode') if is_seller_capable(user) else t(lang, 'btn_become_seller')

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_search_menu'), callback_data="buyer_search_menu")],
        [InlineKeyboardButton(t(lang, 'btn_my_orders'), callback_data="buyer_orders")],
        [InlineKeyboardButton(t(lang, 'btn_messages'), callback_data="buyer_messages")],
        [InlineKeyboardButton(t(lang, 'btn_reviews'), callback_data="buyer_reviews")],
        [InlineKeyboardButton(t(lang, 'btn_profile'), callback_data="buyer_profile")],
        [InlineKeyboardButton(seller_btn_label, callback_data="switch_to_seller_confirm")],
        [InlineKeyboardButton(t(lang, 'btn_ai_assistant'), callback_data="ai_assistant")],
        [InlineKeyboardButton(t(lang, 'btn_contact_admin'), callback_data="contact_admin")],
    ]
    if CHANNEL_URL:
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_official_channel'), url=CHANNEL_URL)])

    text = t(lang, 'buyer_panel_title')

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await update.message.reply_text(
            t(lang, 'bottom_hint'),
            reply_markup=buyer_bottom_kb(lang)
        )


async def buyer_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yaxlit qidiruv tugmasi — ichida 3 ta qidiruv bo'limi:
    mahsulot qidirish, do'kon qidirish va kategoriya bo'yicha qidirish."""
    context.user_data.pop('shop_ctx', None)
    lang = get_lang(update, context)

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_search'), callback_data="buyer_search")],
        [InlineKeyboardButton(t(lang, 'btn_shop_search'), callback_data="buyer_shop_search")],
        [InlineKeyboardButton(t(lang, 'btn_categories'), callback_data="buyer_categories")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")],
    ]
    text = t(lang, 'search_menu_title')

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
            )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )


async def buyer_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    context.user_data.pop('shop_ctx', None)  # do'kon konteksti tugadi

    lang = get_lang(update, context)
    categories = db.get_all_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"{cat[2]} {category_name(cat[1], lang)}", callback_data=f"cat_{cat[0]}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    title = t(lang, 'categories_title')
    if query:
        await query.answer()
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(title, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_category_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop('shop_ctx', None)  # do'kon konteksti tugadi

    # callback_data: 'cat_ID' yoki 'cat_ID_pg_N'
    parts = query.data.split("_")
    category_id = int(parts[1])
    page = int(parts[3]) if len(parts) >= 4 and parts[2] == 'pg' else 0

    lang = get_lang(update, context)
    products = db.search_products(category_id=category_id)

    if not products:
        await query.edit_message_text(
            t(lang, 'category_empty'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_categories")]])
        )
        return

    total = len(products)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    keyboard = []
    for product in products[start:end]:
        rating = product.get('prod_avg_rating') or product.get('avg_rating') or 0
        keyboard.append([InlineKeyboardButton(
            f"⭐{rating:.1f} | {product['name']} — {fmt_price(product['price'])}",
            callback_data=f"prod_{product['id']}"
        )])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"cat_{category_id}_pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"cat_{category_id}_pg_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_categories")])

    await query.edit_message_text(
        t(lang, 'products_page', total=total, page=page+1, pages=total_pages),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _send_product_card(context, chat_id, images, text, keyboard):
    """Mahsulot kartochkasini yuboradi. images — file_id ro'yxati (0..4 ta).
    • 0 rasm  → faqat matn
    • 1 rasm  → rasm + caption (eski xatti-harakat)
    • 2-4 rasm → albom (media group) + alohida tugmali xabar.
      (Albomga tugma biriktirib bo'lmaydi va caption 1024 belgidan oshmasligi kerak,
       shuning uchun matn alohida xabarda yuboriladi.)"""
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    images = [i for i in (images or []) if i][:4]
    if len(images) <= 1:
        if images:
            await context.bot.send_photo(
                chat_id=chat_id, photo=images[0], caption=text,
                reply_markup=markup, parse_mode='HTML'
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=markup, parse_mode='HTML'
            )
        return
    media = [InputMediaPhoto(media=images[0])]
    for fid in images[1:]:
        media.append(InputMediaPhoto(media=fid))
    try:
        await context.bot.send_media_group(chat_id=chat_id, media=media)
    except Exception as e:
        logging.error(f"send_media_group xatosi: {e}")
    await context.bot.send_message(
        chat_id=chat_id, text=text, reply_markup=markup, parse_mode='HTML'
    )


async def buyer_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])
    lang = get_lang(update, context)

    product = db.get_product_by_id(product_id)

    if not product:
        await query.edit_message_text(t(lang, 'product_not_found'))
        return

    # Ko'rish tarixini yangilaymiz
    _track_viewed(context, product_id, product.get('category_id'))

    rating = product['avg_rating'] or 0          # do'kon (sotuvchi) reytingi
    prod_avg = product.get('prod_avg_rating') or 0   # mahsulot reytingi
    prod_count = product.get('prod_review_count') or 0

    map_link = ""
    if product.get('shop_lat') and product.get('shop_lon'):
        _url = f"https://www.google.com/maps/search/?api=1&query={product['shop_lat']},{product['shop_lon']}"
        map_link = t(lang, 'frag_map', url=_url)

    keyboard = []
    # Do'kon qidirish ichida bo'lsa (shu do'kon konteksti) — savatga qo'shish imkoni
    in_shop_ctx = context.user_data.get('shop_ctx') == product.get('seller_id')
    if in_shop_ctx and product.get('in_stock'):
        cart = _cart(context)
        in_cart = None
        if cart and cart.get('seller_id') == product.get('seller_id'):
            in_cart = cart.get('items', {}).get(str(product_id))
        if in_cart:
            keyboard.append([
                InlineKeyboardButton("➖", callback_data=f"cart_dec_{product_id}"),
                InlineKeyboardButton(t(lang, 'btn_in_cart_qty', n=in_cart['qty']), callback_data="cart_view"),
                InlineKeyboardButton("➕", callback_data=f"cart_inc_{product_id}"),
            ])
        else:
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_add_to_cart'), callback_data=f"cart_add_{product_id}"
            )])
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_view_cart_n', n=_cart_count(context)), callback_data="cart_view"
        )])

    keyboard += [
        [InlineKeyboardButton(t(lang, 'btn_order'), callback_data=f"order_{product_id}")],
        [InlineKeyboardButton(t(lang, 'btn_send_message'), callback_data=f"msg_{product_id}")],
    ]
    if prod_count > 0:
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_product_reviews', n=prod_count), callback_data=f"pcomm_{product_id}"
        )])
    if product.get('telegram_username'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_tg_label', u=product['telegram_username']),
            url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
        )])
    if product.get('phone_number'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_phone_label', p=product['phone_number']),
            callback_data=f"call_{product['id']}"
        )])

    # Recommendation tugmasi — agar tarix bo'lsa
    history = context.user_data.get('_view_history', [])
    if len(history) >= 2:  # kamida 2 ta ko'rilgan bo'lsa
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_recommend'),
            callback_data=f"recommend_{product_id}"
        )])

    # Orqaga — do'kon kontekstida do'konga, aks holda kategoriyalarga
    if in_shop_ctx:
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_back_to_shop'), callback_data=f"shop_products_{product['seller_id']}_0"
        )])
    else:
        keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_categories")])

    # HTML rejimi — foydalanuvchi matnida `*`, `_`, `[` bo'lsa ham crash bo'lmaydi
    name = html.escape(product['name'] or '')
    shop_name = html.escape(product.get('shop_name') or t(lang, 'unknown_word'))
    verified_badge = " ✅" if product.get('is_verified') else ""
    addr_text = human_address(product.get('shop_address'))
    manzil_line = t(lang, 'frag_address', addr=html.escape(addr_text)) if addr_text else ""
    shop_landmark = html.escape(product.get('shop_landmark') or t(lang, 'not_specified'))
    working_hours = html.escape(product.get('working_hours') or t(lang, 'not_specified'))
    working_days = html.escape(product.get('working_days') or t(lang, 'not_specified'))
    desc = html.escape(product.get('description') or t(lang, 'none_word'))

    # Hudud va masofa
    region_lbl = region_label_l(product.get('seller_region_id'), lang)
    region_line = t(lang, 'frag_region', label=html.escape(region_lbl)) if region_lbl else ""
    dist_raw = distance_line_to_shop(context, product.get('shop_lat'), product.get('shop_lon'),
                                     prefix=t(lang, 'dist_from_you'))
    dist_line = (dist_raw.lstrip("\n") + "\n") if dist_raw else ""

    # Hozir ochiq/yopiqmi (faqat working_hours parse qilinsa)
    open_status = is_shop_open_now(product.get('working_hours'))
    if open_status is True:
        open_line = "  " + t(lang, 'open_now')
    elif open_status is False:
        open_line = "  " + t(lang, 'closed_now')
    else:
        open_line = ""

    stock_line = ""
    if product.get('stock_count') is not None:
        stock_line = t(lang, 'frag_stock', n=product['stock_count'])

    # Dinamik atributlar
    attrs = db.get_product_attributes(product['id'])
    attrs_text = ""
    if attrs:
        lines = []
        for a in attrs:
            label = a.get('attr_label') or a['attr_key']
            lines.append(f"• {label}: {a['attr_value']}")
        attrs_text = t(lang, 'frag_attrs_title') + "\n".join(lines)

    rating_cnt = (t(lang, 'frag_rating_count', n=prod_count) if prod_count
                  else t(lang, 'frag_no_rating'))
    text = t(lang, 'product_card',
             name=name, price=fmt_price(product['price']), stock=stock_line,
             shop=shop_name, verified=verified_badge,
             region=region_line, address=manzil_line,
             landmark=shop_landmark, map=map_link, dist=dist_line,
             prod_rating=f"{prod_avg:.1f}", rating_cnt=rating_cnt,
             shop_rating=f"{rating:.1f}", wh=working_hours, open=open_line,
             wd=working_days, desc=desc, attrs=attrs_text)

    # Rasm(lar) bo'lsa — alohida xabar(lar) bilan yuboramiz, keyin batafsil ma'lumotni
    # (edit_message_text rasm bilan ishlamaydi, shuning uchun eski xabarni o'chiramiz)
    images = db.get_product_images(product_id)
    if images:
        try:
            await query.message.delete()
        except Exception:
            pass
        await _send_product_card(context, update.effective_chat.id, images, text, keyboard)
    else:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )


async def product_reviews_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulotga yozilgan izohlar ro'yxati (callback: pcomm_{product_id})."""
    query = update.callback_query
    # button_handler allaqachon query.answer() chaqirgan

    try:
        product_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):
        return

    lang = get_lang(update, context)
    product = db.get_product_basic(product_id)
    pname = html.escape(product.get('name')) if product else t(lang, 'product_word')
    prod_avg, prod_count = db.get_product_avg_rating(product_id)
    reviews = db.get_product_reviews(product_id)

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_back_to_product'), callback_data=f"prod_{product_id}")]
    ])

    if not reviews:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'reviews_none_for_product', name=pname),
            reply_markup=back_kb, parse_mode='HTML'
        )
        return

    lines = [
        t(lang, 'reviews_header', name=pname),
        t(lang, 'reviews_product_rating', avg=f"{prod_avg:.1f}", count=prod_count),
    ]
    for r in reviews:
        pr = r.get('product_rating') or 0
        stars = "⭐" * pr + "☆" * (5 - pr) if pr else ""
        buyer = html.escape(r.get('buyer_name') or t(lang, 'anonymous'))
        comment = html.escape(r.get('comment') or '')
        date = fmt_datetime(r.get('created_at'))
        block = f"\n{stars}\n👤 {buyer} · {date}"
        if comment:
            block += f"\n💬 {comment}"
        lines.append(block)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + t(lang, 'reviews_old_cut')

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text, reply_markup=back_kb, parse_mode='HTML'
    )


async def skip_search_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Lokatsiyasiz qidirish' tugmasi — lokatsiyasiz natijalarni ko'rsatadi (pagination bilan)."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    q_text = context.user_data.pop('search_query', None)
    context.user_data.pop('search_state', None)

    if not q_text:
        await query.edit_message_text(t(lang, 'search_cancelled'))
        return

    await query.edit_message_text(t(lang, 'searching_for', q=q_text))
    region_id = context.user_data.get('search_region_id')
    products = db.search_products(query=q_text, region_id=region_id)
    await _render_search_page(update.effective_chat.id, context, products,
                              page=0, sort_by='rating', query_text=q_text,
                              buyer_lat=None)


PAGE_SIZE = 10  # sahifadagi mahsulotlar soni
HISTORY_LIMIT = 20  # ko'rilgan mahsulotlar tarixi


async def _show_product_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, product):
    """Deeplink orqali kelgan foydalanuvchiga mahsulot sahifasini ko'rsatadi."""
    product_id = product['id']
    _track_viewed(context, product_id, product.get('category_id'))

    lang = get_lang(update, context)
    rating = product['avg_rating'] or 0              # do'kon reytingi
    prod_avg = product.get('prod_avg_rating') or 0   # mahsulot reytingi
    prod_count = product.get('prod_review_count') or 0
    map_link = ""
    if product.get('shop_lat') and product.get('shop_lon'):
        _url = f"https://www.google.com/maps/search/?api=1&query={product['shop_lat']},{product['shop_lon']}"
        map_link = t(lang, 'frag_map', url=_url)

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_order'), callback_data=f"order_{product_id}")],
        [InlineKeyboardButton(t(lang, 'btn_send_message'), callback_data=f"msg_{product_id}")],
    ]
    if prod_count > 0:
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_product_reviews', n=prod_count), callback_data=f"pcomm_{product_id}"
        )])
    if product.get('telegram_username'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_tg_label', u=product['telegram_username']),
            url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")])

    name = html.escape(product['name'] or '')
    shop_name = html.escape(product.get('shop_name') or t(lang, 'unknown_word'))
    loc_text = best_location_text(product.get('shop_address'), product.get('shop_landmark'))
    if loc_text:
        manzil_line = t(lang, 'frag_address', addr=html.escape(loc_text) + map_link)
    elif map_link:
        manzil_line = t(lang, 'frag_address_map', map=map_link)
    else:
        manzil_line = ""
    desc = html.escape(product.get('description') or t(lang, 'none_word'))
    working_hours = html.escape(product.get('working_hours') or t(lang, 'not_specified'))

    # Hudud (viloyat → tuman) — xaridor qaysi joydan ekanini ko'rsin
    region_lbl = region_label_l(product.get('seller_region_id'), lang)
    region_line = t(lang, 'frag_region', label=html.escape(region_lbl)) if region_lbl else ""
    # Xaridor lokatsiyasi eslab qolingan bo'lsa — masofa
    dist_raw = distance_line_to_shop(context, product.get('shop_lat'), product.get('shop_lon'),
                                     prefix=t(lang, 'dist_from_you'))
    dist_line = (dist_raw.lstrip("\n") + "\n") if dist_raw else ""

    rating_cnt = (t(lang, 'frag_rating_count', n=prod_count) if prod_count
                  else t(lang, 'frag_no_rating'))
    text = t(lang, 'product_card_deeplink',
             name=name, price=fmt_price(product['price']), shop=shop_name,
             region=region_line, address=manzil_line, dist=dist_line,
             prod_rating=f"{prod_avg:.1f}", rating_cnt=rating_cnt,
             shop_rating=f"{rating:.1f}", wh=working_hours, desc=desc)

    images = db.get_product_images(product['id'])
    if images:
        await _send_product_card(context, update.effective_chat.id, images, text, keyboard)
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # Masofa hali noma'lum (xaridor joylashuvi yo'q) va do'kon koordinatasi bor bo'lsa —
    # xaridordan joylashuvini so'raymiz, keyin sotuvchigacha masofani ko'rsatamiz.
    b_lat, b_lon = get_buyer_geo(context)
    if (b_lat is None or b_lon is None) and product.get('shop_lat') and product.get('shop_lon'):
        context.user_data['_dist_pending_product'] = product_id
        loc_kb = ReplyKeyboardMarkup(
            [[KeyboardButton(t(lang, 'btn_send_location'), request_location=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
        await update.message.reply_text(t(lang, 'deeplink_ask_location'), reply_markup=loc_kb)


def _track_viewed(context, product_id, category_id):
    """Xaridor ko'rgan mahsulotlarni kuzatib boradi (recommendation uchun)."""
    history = context.user_data.setdefault('_view_history', [])
    # Takrorlashni oldini olamiz
    entry = {'pid': product_id, 'cid': category_id}
    history = [h for h in history if h['pid'] != product_id]
    history.insert(0, entry)
    context.user_data['_view_history'] = history[:HISTORY_LIMIT]


def _get_recommendations(context, db, current_product_id, limit=5):
    """Ko'rish tarixiga qarab tavsiya qilinadigan mahsulotlar."""
    history = context.user_data.get('_view_history', [])
    if not history:
        return []

    # Ko'rilgan kategoriyalar (eng ko'p ko'rilganidan)
    from collections import Counter
    cat_counts = Counter(h['cid'] for h in history if h.get('cid'))
    seen_pids = {h['pid'] for h in history}
    seen_pids.add(current_product_id)

    recommendations = []
    for cat_id, _ in cat_counts.most_common(3):
        products = db.search_products(category_id=cat_id, sort_by='rating')
        for p in products:
            if p['id'] not in seen_pids and len(recommendations) < limit:
                recommendations.append(p)
                seen_pids.add(p['id'])

    return recommendations[:limit]


async def _render_search_page(chat_id, context, products, page=0, sort_by='rating',
                              query_text='', buyer_lat=None):
    """Qidiruv natijalarini sahifa bo'yicha ko'rsatadi (pagination + sort)."""
    lang = get_lang(None, context)
    total = len(products)
    if total == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, 'search_no_results_q', q=query_text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])
        )
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    # State'ni saqlaymiz — sahifa va sort almashtirilganda qayta qidirish kerak emas
    context.user_data['_search_products'] = products
    context.user_data['_search_query'] = query_text
    context.user_data['_search_sort'] = sort_by
    context.user_data['_search_buyer_lat'] = buyer_lat
    # buyer_lon ni alohida saqlamasak ham, products ichida _distance_km bor

    for product in products[start:end]:
        rating = product.get('avg_rating') or 0          # do'kon reytingi
        prod_avg = product.get('prod_avg_rating') or 0   # mahsulot reytingi
        prod_count = product.get('prod_review_count') or 0
        map_link = ""
        if product.get('shop_lat') and product.get('shop_lon'):
            _url = (f"https://www.google.com/maps/search/?api=1&"
                    f"query={product['shop_lat']},{product['shop_lon']}")
            map_link = t(lang, 'frag_map', url=_url)

        distance_line = ""
        if product.get('_distance_km') is not None:
            distance_line = t(lang, 'frag_distance', km=f"{product['_distance_km']:.1f}")

        contact_keyboard = []
        if product.get('telegram_username'):
            contact_keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_telegram'),
                url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
            )])
        if product.get('phone_number'):
            contact_keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_phone'), callback_data=f"call_{product['id']}"
            )])
        contact_keyboard.append([InlineKeyboardButton(t(lang, 'btn_details'), callback_data=f"prod_{product['id']}")])
        if prod_count > 0:
            contact_keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_reviews_n', n=prod_count), callback_data=f"pcomm_{product['id']}"
            )])

        emoji = product.get('category_emoji') or '📦'
        name = html.escape(product['name'] or '')
        shop_name = html.escape(product.get('shop_name') or t(lang, 'unknown_word'))
        region_lbl = region_label_l(product.get('seller_region_id'), lang)
        region_line = f"🌍 {html.escape(region_lbl)}\n" if region_lbl else ""
        loc_text = best_location_text(product.get('shop_address'), product.get('shop_landmark'))
        if loc_text:
            manzil_line = f"📍 {html.escape(loc_text)}{map_link}{distance_line}\n"
        elif map_link or distance_line:
            manzil_line = f"{t(lang, 'map_see_line')}{map_link}{distance_line}\n"
        else:
            manzil_line = ""
        rating_cnt = (t(lang, 'srch_rating_cnt', n=prod_count) if prod_count
                      else t(lang, 'srch_no_rating'))
        caption = t(lang, 'search_item_card',
                    emoji=emoji, name=name, price=fmt_price(product['price']),
                    shop=shop_name, region=region_line, address=manzil_line,
                    prod_rating=f"{prod_avg:.1f}", rating_cnt=rating_cnt,
                    shop_rating=f"{rating:.1f}")

        if product.get('image_url'):
            try:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=product['image_url'],
                    caption=caption, parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(contact_keyboard)
                )
            except Exception:
                # Rasm yuborilmasa — oddiy matn
                await context.bot.send_message(
                    chat_id=chat_id, text=caption, parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(contact_keyboard)
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=caption, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(contact_keyboard)
            )

    # Sort + pagination tugmalari
    sort_labels = {
        'rating': t(lang, 'sort_rating'),
        'price_asc': t(lang, 'sort_price_asc'),
        'price_desc': t(lang, 'sort_price_desc'),
        'newest': t(lang, 'sort_newest'),
    }
    sort_buttons = []
    for key, label in sort_labels.items():
        marker = "✅ " if key == sort_by else ""
        sort_buttons.append(InlineKeyboardButton(f"{marker}{label}", callback_data=f"srt_{key}"))
    # 2x2 grid uchun bo'lamiz
    sort_kb = [sort_buttons[i:i+2] for i in range(0, len(sort_buttons), 2)]

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(t(lang, 'btn_prev'), callback_data=f"pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(t(lang, 'btn_next'), callback_data=f"pg_{page+1}"))

    footer_kb = sort_kb + ([nav] if nav else []) + [
        [InlineKeyboardButton(t(lang, 'btn_main_menu'), callback_data="buyer_panel")]
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=t(lang, 'search_results_count', q=html.escape(query_text),
               total=total, page=page+1, pages=total_pages),
        reply_markup=InlineKeyboardMarkup(footer_kb),
        parse_mode='HTML'
    )


async def search_sort_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi sort tartibini o'zgartirsa."""
    query = update.callback_query
    await query.answer()

    sort_by = query.data.replace("srt_", "")
    q_text = context.user_data.get('_search_query', '')
    buyer_lat = context.user_data.get('_search_buyer_lat')

    # Saqlangan natijalardan masofalarni olib o'tish uchun avval eski natijalarni saqlab qo'yamiz
    old_products = context.user_data.get('_search_products') or []
    distances = {p['id']: p.get('_distance_km') for p in old_products}

    # Yangi sort bilan qayta qidiramiz
    products = db.search_products(query=q_text, sort_by=sort_by)
    # Eski masofalarni qayta yopishtiramiz
    for p in products:
        p['_distance_km'] = distances.get(p['id'])

    await _render_search_page(update.effective_chat.id, context, products,
                              page=0, sort_by=sort_by, query_text=q_text,
                              buyer_lat=buyer_lat)


async def search_page_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sahifa o'zgartirish."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.replace("pg_", ""))
    products = context.user_data.get('_search_products') or []
    if not products:
        await query.edit_message_text(T(update, context, 'search_results_gone'))
        return

    sort_by = context.user_data.get('_search_sort', 'rating')
    q_text = context.user_data.get('_search_query', '')
    buyer_lat = context.user_data.get('_search_buyer_lat')

    await _render_search_page(update.effective_chat.id, context, products,
                              page=page, sort_by=sort_by, query_text=q_text,
                              buyer_lat=buyer_lat)


async def _show_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               query_text: str, buyer_lat=None, buyer_lon=None):
    """Qidiruv natijalarini ko'rsatadi (eski wrapper — pagination versiyasini chaqiradi)."""
    region_id = context.user_data.get('search_region_id')
    products = db.search_products(query=query_text, region_id=region_id)

    # Lokatsiya bo'lsa — masofani hisoblaymiz va saralaymiz
    if buyer_lat is not None and buyer_lon is not None:
        for p in products:
            d = None
            if p.get('shop_lat') and p.get('shop_lon'):
                d = haversine_km(buyer_lat, buyer_lon, p['shop_lat'], p['shop_lon'])
            p['_distance_km'] = d
        products.sort(key=lambda p: (p['_distance_km'] is None, p['_distance_km'] or 0))

    chat_id = update.effective_chat.id if update.effective_chat else update.message.chat.id
    await _render_search_page(chat_id, context, products, page=0,
                              sort_by='rating' if buyer_lat is None else 'distance',
                              query_text=query_text, buyer_lat=buyer_lat)


async def buyer_shop_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor do'kon qidiradi."""
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data['shop_search_state'] = 'awaiting_query'

    text = T(update, context, 'shop_search_prompt')
    if query:
        await query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def buyer_shop_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Do'konlar ro'yxatini ko'rsatadi (callback: shop_list_{page})."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[2])
    shops = context.user_data.get('_shop_results') or []

    if not shops:
        await query.edit_message_text(
            T(update, context, 'shops_not_found'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T(update, context, 'back'), callback_data="buyer_panel")]])
        )
        return

    await _render_shop_list(query, context, shops, page)


async def _render_shop_list(target, context, shops, page=0):
    """Do'konlar ro'yxatini sahifalab ko'rsatadi."""
    total = len(shops)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    lang = get_lang(None, context)
    keyboard = []
    for shop in shops[start:end]:
        rating = shop.get('avg_rating') or 0
        count = shop.get('product_count') or 0
        verified = "✅ " if shop.get('is_verified') else ""
        cnt_lbl = t(lang, 'shop_count_label', n=count)
        label = f"⭐{rating:.1f} | {verified}🏪 {shop['shop_name']} ({cnt_lbl})"[:50]
        keyboard.append([InlineKeyboardButton(label, callback_data=f"shop_{shop['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"shop_list_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"shop_list_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    text = t(lang, 'shops_page', total=total, page=page+1, pages=total_pages)

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await target.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_shop_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Do'kon sahifasi — ma'lumotlar va mahsulotlar."""
    query = update.callback_query
    await query.answer()

    seller_id = int(query.data.split("_")[1])
    lang = get_lang(update, context)
    shop = db.get_seller_public_info(seller_id)

    if not shop:
        await query.edit_message_text(
            t(lang, 'shop_not_found'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])
        )
        return

    # Do'kon konteksti — mahsulot sahifasida "savatga qo'shish" tugmasi shu do'kon uchun chiqsin
    context.user_data['shop_ctx'] = seller_id

    rating = shop.get('avg_rating') or 0
    product_count = shop.get('product_count') or 0
    delivered = shop.get('delivered_count') or 0
    verified_badge = " ✅" if shop.get('is_verified') else ""

    map_link = ""
    if shop.get('shop_lat') and shop.get('shop_lon'):
        _url = f"https://www.google.com/maps/search/?api=1&query={shop['shop_lat']},{shop['shop_lon']}"
        map_link = t(lang, 'frag_map', url=_url)

    open_status = is_shop_open_now(shop.get('working_hours'))
    if open_status is True:
        open_line = "  " + t(lang, 'open_now')
    elif open_status is False:
        open_line = "  " + t(lang, 'closed_now')
    else:
        open_line = ""

    # Hudud (viloyat → tuman) — xaridor do'kon qayerdaligini ko'rsin
    region_lbl = region_label_l(shop.get('region_id'), lang)
    region_line = t(lang, 'frag_region', label=html.escape(region_lbl)) if region_lbl else ""
    # Masofa — xaridor lokatsiyasi bo'lsa
    dist_line = distance_line_to_shop(context, shop.get('shop_lat'), shop.get('shop_lon'),
                                      prefix=t(lang, 'dist_from_you'))
    if dist_line:
        dist_line = dist_line.lstrip("\n") + "\n"

    addr_text = human_address(shop.get('shop_address'))
    manzil_line = t(lang, 'frag_address', addr=html.escape(addr_text) + map_link) if addr_text else ""
    # Haqiqiy manzil bo'lmasa — xarita havolasini mo'ljal qatoriga biriktiramiz
    landmark_map = "" if addr_text else map_link
    text = t(lang, 'shop_detail_card',
             shop=html.escape(shop.get('shop_name') or ''), verified=verified_badge,
             seller=html.escape(shop.get('name') or ''),
             region=region_line, address=manzil_line,
             landmark=html.escape(shop.get('shop_landmark') or t(lang, 'not_specified')),
             landmark_map=landmark_map, dist=dist_line,
             wh=html.escape(shop.get('working_hours') or t(lang, 'not_specified')), open=open_line,
             wd=html.escape(shop.get('working_days') or t(lang, 'not_specified')),
             rating=f"{rating:.1f}", pcount=product_count, delivered=delivered)
    if verified_badge:
        text += t(lang, 'verified_seller_note')

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_view_products_n', n=product_count), callback_data=f"shop_products_{seller_id}_0")],
    ]
    # Savatda shu do'kon mahsulotlari bo'lsa — savatga tezkor kirish
    cart = _cart(context)
    if cart and cart.get('seller_id') == seller_id and cart.get('items'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_my_cart_summary', n=_cart_count(context), total=fmt_price(_cart_total(context))),
            callback_data="cart_view"
        )])
    if shop.get('telegram_username'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_tg_at', u=shop['telegram_username']),
            url=f"https://t.me/{shop['telegram_username']}"
        )])
    if shop.get('phone_number'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_phone_plain', p=shop['phone_number']), callback_data=f"noop"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def buyer_shop_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Do'konning barcha mahsulotlari (paginatsiya bilan)."""
    query = update.callback_query
    await query.answer()

    # callback: shop_products_{seller_id}_{page}
    parts = query.data.split("_")
    seller_id = int(parts[2])
    page = int(parts[3])

    lang = get_lang(update, context)
    products = db.get_shop_products(seller_id)
    shop = db.get_seller_public_info(seller_id)
    shop_name = shop.get('shop_name') if (shop and shop.get('shop_name')) else t(lang, 'shop_word')

    # Do'kon konteksti — savat shu do'kon uchun
    context.user_data['shop_ctx'] = seller_id

    if not products:
        await query.edit_message_text(
            t(lang, 'shop_no_products', shop=html.escape(shop_name)),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data=f"shop_{seller_id}")]])
        )
        return

    cart = _cart(context)
    cart_items = cart.get('items', {}) if (cart and cart.get('seller_id') == seller_id) else {}

    total = len(products)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    keyboard = []
    for product in products[start:end]:
        rating = product.get('prod_avg_rating') or product.get('avg_rating') or 0
        emoji = product.get('category_emoji') or '📦'
        in_cart = cart_items.get(str(product['id']))
        # 1-qator: mahsulot (batafsil sahifa)
        keyboard.append([InlineKeyboardButton(
            f"{emoji} ⭐{rating:.1f} | {product['name']} — {fmt_price(product['price'])}",
            callback_data=f"prod_{product['id']}"
        )])
        # 2-qator: tezkor "savatga qo'shish" (yoki savatdagi soni)
        if in_cart:
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_in_cart_manage', n=in_cart['qty']),
                callback_data="cart_view"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_add_to_cart'), callback_data=f"cart_add_{product['id']}"
            )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"shop_products_{seller_id}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"shop_products_{seller_id}_{page+1}"))
    if nav:
        keyboard.append(nav)
    # Savat footer
    if cart_items:
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_checkout_cart', n=_cart_count(context), total=fmt_price(_cart_total(context))),
            callback_data="cart_view"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_back_to_shop'), callback_data=f"shop_{seller_id}")])

    await query.edit_message_text(
        t(lang, 'shop_products_header', shop=html.escape(shop_name),
          total=total, page=page+1, pages=total_pages),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def buyer_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1-bosqich: hudud tanlash yoki o'tkazib yuborish
    context.user_data.pop('shop_ctx', None)  # do'kon konteksti tugadi
    context.user_data['search_state'] = 'awaiting_query'
    context.user_data.pop('search_query', None)
    context.user_data.pop('search_lat', None)
    context.user_data.pop('search_lon', None)
    context.user_data.pop('search_region_id', None)

    lang = get_lang(update, context)
    regions = db.get_regions(parent_id=None)
    kb_rows = []
    for r in regions:
        kb_rows.append([InlineKeyboardButton(region_name(r['name'], lang), callback_data=f"sreg_{r['id']}")])
    kb_rows.append([InlineKeyboardButton(t(lang, 'btn_all_regions'), callback_data="sreg_0")])
    kb_rows.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    text = t(lang, 'search_region_ask')

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))


async def search_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi viloyat tanladi — tuman ko'rsatamiz yoki to'g'ridan-to'g'ri qidiruv."""
    query = update.callback_query
    await query.answer()

    region_id = int(query.data.replace("sreg_", ""))
    lang = get_lang(update, context)

    if region_id == 0:
        # Barcha hududlar — hududsiz qidiruv
        context.user_data.pop('search_region_id', None)
        await query.edit_message_text(t(lang, 'search_prompt'))
        return

    # Tumanlar bormi?
    districts = db.get_regions(parent_id=region_id)
    if districts:
        context.user_data['search_region_id'] = region_id
        kb_rows = []
        for d in districts:
            kb_rows.append([InlineKeyboardButton(region_name(d['name'], lang), callback_data=f"sdist_{d['id']}")])
        region = db.get_region_by_id(region_id)
        kb_rows.append([InlineKeyboardButton(
            t(lang, 'btn_whole_region', name=region_name(region['name'], lang)), callback_data=f"sdist_0_{region_id}"
        )])
        kb_rows.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_search")])
        await query.edit_message_text(
            t(lang, 'region_pick_district', name=region_name(region['name'], lang)),
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
    else:
        # Tumansiz viloyat — to'g'ridan-to'g'ri qidiruv
        context.user_data['search_region_id'] = region_id
        region = db.get_region_by_id(region_id)
        await query.edit_message_text(
            t(lang, 'region_then_search', name=region_name(region['name'], lang))
        )


async def search_district_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi tuman tanladi."""
    query = update.callback_query
    await query.answer()

    data = query.data.replace("sdist_", "")
    lang = get_lang(update, context)

    if "_" in data:
        # "0_region_id" — butun viloyat
        region_id = int(data.split("_")[1])
        context.user_data['search_region_id'] = region_id
        region = db.get_region_by_id(region_id)
        name = region_name(region['name'], lang) if region else t(lang, 'selected_region')
    else:
        district_id = int(data)
        context.user_data['search_region_id'] = district_id
        district = db.get_region_by_id(district_id)
        name = region_name(district['name'], lang) if district else t(lang, 'selected_district')

    await query.edit_message_text(t(lang, 'region_then_search', name=name))


async def buyer_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_buyer(user['id'])

    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])

    if not orders:
        text = t(lang, 'orders_empty')
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}

    # Savat buyurtmalarini guruhlash: bir order_group_id bitta qator bo'lib ko'rinadi
    group_agg = {}
    for o in orders:
        gid = o.get('order_group_id')
        if gid:
            g = group_agg.setdefault(gid, {'count': 0, 'sum': 0.0, 'status': o['status']})
            g['count'] += 1
            g['sum'] += float(o['total_price'] or 0)

    keyboard = []
    seen_groups = set()
    shown = 0
    for order in orders:
        if shown >= 15:
            break
        gid = order.get('order_group_id')
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
            g = group_agg[gid]
            emoji = status_emoji.get(g['status'], '❓')
            keyboard.append([InlineKeyboardButton(
                t(lang, 'order_group_row', emoji=emoji, oid=fmt_order_id(int(gid)),
                  count=g['count'], sum=fmt_price(g['sum'])),
                callback_data=f"gorder_detail_{gid}"
            )])
        else:
            emoji = status_emoji.get(order['status'], '❓')
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {fmt_order_id(order['id'])} — {order['product_name'][:25]}",
                callback_data=f"order_detail_{order['id']}"
            )])
        shown += 1
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    total_display = len(seen_groups) + sum(1 for o in orders if not o.get('order_group_id'))
    text = t(lang, 'my_orders_count', n=total_display)
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor xabarli buyurtmalarini ko'radi."""
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT o.id, p.name as product_name, u.shop_name,
               MAX(m.created_at) as last_msg,
               COUNT(CASE WHEN m.receiver_id=? AND m.is_read=0 THEN 1 END) as unread
        FROM messages m
        JOIN orders o ON m.order_id=o.id
        JOIN products p ON o.product_id=p.id
        JOIN users u ON o.seller_id=u.id
        WHERE o.buyer_id=?
        GROUP BY o.id
        ORDER BY last_msg DESC
        LIMIT 20
    """, (user['id'], user['id']))
    rows = [dict(r) for r in cursor.fetchall()]
    lang = get_lang(update, context)

    kb_back = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])

    if not rows:
        text = t(lang, 'messages_empty')
        if query:
            await query.edit_message_text(text, reply_markup=kb_back)
        else:
            await update.message.reply_text(text, reply_markup=kb_back)
        return

    keyboard = []
    for r in rows:
        unread_mark = f" 🔴{r['unread']}" if r['unread'] else ""
        label = f"💬 {fmt_order_id(r['id'])} — {r['product_name'][:20]}{unread_mark}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"msgs_{r['id']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")])

    text = t(lang, 'messages_title')
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    lang = get_lang(update, context)

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_edit_name'), callback_data="edit_buyer_name")],
        [InlineKeyboardButton(t(lang, 'btn_edit_phone'), callback_data="edit_buyer_phone")],
        [InlineKeyboardButton(t(lang, 'btn_my_referral'), callback_data="my_referral")],
        [InlineKeyboardButton(t(lang, 'btn_change_language'), callback_data="change_lang")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")],
    ]
    text = t(lang, 'buyer_profile_body',
             name=user['name'], phone=user['phone_number'],
             refs=user.get('referral_count') or 0,
             date=fmt_datetime(user['created_at']))

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def change_language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Til tanlash menyusi (profil orqali)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    active = get_active_mode(user, context)
    if active == 'admin':
        back_cb = "admin_settings"
    elif active == 'seller':
        back_cb = "seller_profile"
    else:
        back_cb = "buyer_profile"
    kb = [
        [InlineKeyboardButton(LANGS['uz'], callback_data="setlang_uz")],
        [InlineKeyboardButton(LANGS['ru'], callback_data="setlang_ru")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data=back_cb)],
    ]
    await query.edit_message_text(
        t(lang, 'choose_language'),
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tilni tanlaydi va tegishli panelni yangi tilda ko'rsatadi."""
    query = update.callback_query
    new_lang = query.data.split("_")[1]  # "setlang_uz" -> "uz"
    new_lang = set_user_lang(update, context, new_lang)
    try:
        await query.answer(t(new_lang, 'language_changed'))
    except Exception:
        pass
    # Pastki Reply klaviaturani ham yangi tilga moslaymiz
    user = db.get_user_by_telegram_id(update.effective_user.id)
    active = get_active_mode(user, context)
    if active == 'seller':
        await seller_panel(update, context)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(new_lang, 'bottom_hint'),
            reply_markup=seller_bottom_kb(new_lang)
        )
    elif user and user.get('role') == 'admin':
        await admin_panel(update, context)
    else:
        await buyer_panel(update, context)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(new_lang, 'bottom_hint'),
            reply_markup=buyer_bottom_kb(new_lang)
        )


async def my_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi o'z taklif havolasini ko'radi va ulashishi mumkin."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text(t(lang, 'user_not_found_start'))
        return

    # Agar referral_code yo'q bo'lsa — hozir yaratib saqlaymiz
    if not user.get('referral_code'):
        import random, string
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        db.update_user(user['id'], referral_code=code)
        user = db.get_user_by_telegram_id(update.effective_user.id)

    from urllib.parse import quote
    bot_me = await context.bot.get_me()
    bot_username = bot_me.username
    ref_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    # t.me/share/url — faqat ref_link ni encode qilamiz, matn sodda bo'lsin
    share_url = f"https://t.me/share/url?url={quote(ref_link, safe='')}&text={quote(t(lang, 'referral_share_text'), safe='')}"

    text = t(lang, 'referral_link_title',
             link=ref_link, code=user['referral_code'],
             count=user.get('referral_count') or 0)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_share_friends'), url=share_url)],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_profile")],
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')


async def buyer_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)

    lang = get_lang(update, context)
    if not order:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    dlv = order.get('delivery_type', 'delivery')
    pay = order.get('payment_method', 'cash')
    status = order['status']

    # Status tavsifi — xaridorga tushunarli
    # Pending bo'lsa qolgan vaqtni hisoblaymiz
    pending_note = ""
    if status == 'pending' and order.get('created_at'):
        from datetime import datetime, timezone
        try:
            created = datetime.strptime(str(order['created_at'])[:19], "%Y-%m-%d %H:%M:%S")
            created = created.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            elapsed = (now - created).total_seconds()
            remaining = max(0, 600 - elapsed)  # 10 daqiqa = 600 sekund
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                pending_note = t(lang, 'pending_autocancel_left', m=mins, s=f"{secs:02d}")
            else:
                pending_note = t(lang, 'pending_autocancel_soon')
        except Exception:
            pass

    status_guide = {
        'pending':   t(lang, 'status_guide_pending', note=pending_note),
        'confirmed': (t(lang, 'status_guide_confirmed_delivery') if dlv == 'delivery'
                      else t(lang, 'status_guide_confirmed_pickup')),
        'delivered': t(lang, 'status_guide_delivered'),
        'cancelled': t(lang, 'status_guide_cancelled'),
    }

    # Holat ketma-ketligi vizual
    steps = [t(lang, 'step_new'), t(lang, 'step_confirmed'),
             t(lang, 'step_delivered') if dlv == 'delivery' else t(lang, 'step_picked'),
             t(lang, 'step_rated')]
    step_idx = {'pending': 0, 'confirmed': 1, 'delivered': 2, 'cancelled': 0}.get(status, 0)
    timeline = ""
    for i, step in enumerate(steps):
        if i < step_idx:
            timeline += f"✅ {step}\n"
        elif i == step_idx and status != 'cancelled':
            timeline += f"▶️ {step}{t(lang, 'timeline_now')}\n"
        else:
            timeline += f"⬜ {step}\n"

    keyboard = []

    if status == 'pending':
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_cancel_order'), callback_data=f"buyer_cancel_{order_id}"
        )])

    # Pickup: xaridor o'zi "Oldim" tugmasini bosadi → 'delivered' ga o'tadi
    if status == 'confirmed' and dlv == 'pickup':
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_got_item'), callback_data=f"buyer_confirm_pickup_{order_id}"
        )])

    if status in ('delivered', 'cancelled'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_reorder'), callback_data=f"order_{order['product_id']}"
        )])

    keyboard.append([InlineKeyboardButton(
        t(lang, 'btn_send_message'), callback_data=f"order_msg_{order_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        t(lang, 'btn_correspondence'), callback_data=f"msgs_{order_id}"
    )])

    # Reyting: delivery — faqat 'delivered' da; pickup — 'confirmed' da ham mumkin
    can_rate = (status == 'delivered') or (status == 'confirmed' and dlv == 'pickup')
    if can_rate:
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_leave_rating'), callback_data=f"order_rate_{order_id}"
        )])

    dlv_lbl = dlv_label(dlv, lang)
    pay_lbl = pay_label(pay, lang)

    # Sotuvchi lokatsiyasi va masofa
    location_line = ""
    map_button = None
    if order.get('shop_lat') and order.get('shop_lon'):
        slat, slon = order['shop_lat'], order['shop_lon']
        location_line = t(lang, 'frag_order_address',
                          addr=html.escape(order.get('shop_address') or t(lang, 'address_word')))
        if order.get('shop_landmark'):
            location_line += t(lang, 'frag_order_landmark', lm=html.escape(order['shop_landmark']))

        # Masofa — agar xaridorning lokatsiyasi bo'lsa
        if order.get('buyer_lat') and order.get('buyer_lon'):
            dist = haversine_km(order['buyer_lat'], order['buyer_lon'], slat, slon)
            if dist is not None:
                location_line += t(lang, 'frag_order_distance', km=dist)
            # Yo'l xaritasi — Google Maps directions
            map_button = InlineKeyboardButton(
                t(lang, 'btn_show_route'),
                url=f"https://www.google.com/maps/dir/{order['buyer_lat']},{order['buyer_lon']}/{slat},{slon}"
            )
        else:
            # Faqat sotuvchi lokatsiyasi
            map_button = InlineKeyboardButton(
                t(lang, 'btn_shop_location'),
                url=f"https://www.google.com/maps/search/?api=1&query={slat},{slon}"
            )

    # Xarita tugmasini klaviaturaga qo'shish
    if map_button:
        keyboard.append([map_button])

    # Sotuvchi Telegram
    if order.get('seller_username'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_tg_at', u=order['seller_username']),
            url=f"https://t.me/{order['seller_username']}"
        )])

    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_orders")])

    text = t(lang, 'order_detail_body',
             oid=fmt_order_id(order['id']),
             pname=html.escape(order.get('product_name') or ''),
             qty=order['quantity'], total=fmt_price(order['total_price']),
             dlv=dlv_lbl, pay=pay_lbl,
             shop=html.escape(order.get('shop_name') or ''),
             location=location_line, phone=order.get('seller_phone') or '—',
             date=fmt_datetime(order.get('created_at')),
             timeline=timeline, guide=status_guide.get(status, ''))

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )


async def buyer_confirm_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor pickup buyurtmasini o'zi olganligi haqida tasdiqlaydi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[3])
    order = db.get_order_by_id(order_id)
    buyer = db.get_user_by_telegram_id(update.effective_user.id)

    lang = get_lang(update, context)
    if not order or not buyer or order['buyer_id'] != buyer['id']:
        await query.edit_message_text(t(lang, 'order_not_yours'))
        return

    if order['status'] != 'confirmed':
        await query.edit_message_text(
            t(lang, 'cant_confirm_status', status=fmt_status(order['status']))
        )
        return

    db.update_order_status(order_id, 'delivered')

    # Sotuvchiga xabar (sotuvchi tilida)
    try:
        if order.get('seller_tg'):
            seller = db.get_user_by_id(order['seller_id'])
            await context.bot.send_message(
                chat_id=order['seller_tg'],
                text=t(seller or 'uz', 'pickup_seller_notify',
                       oid=fmt_order_id(order_id),
                       pname=html.escape(order.get('product_name') or ''),
                       buyer=html.escape(order.get('buyer_name') or '')),
                parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"Pickup tasdiqlash bildirishnomasi ketmadi: {e}")

    await query.edit_message_text(
        t(lang, 'pickup_done', oid=fmt_order_id(order_id)),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_leave_rating'), callback_data=f"order_rate_{order_id}")],
            [InlineKeyboardButton(t(lang, 'btn_orders_back'), callback_data="buyer_orders")],
        ])
    )


async def buyer_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor 'pending' buyurtmasini bekor qilishi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)
    buyer = db.get_user_by_telegram_id(update.effective_user.id)

    lang = get_lang(update, context)
    if not order or not buyer or order['buyer_id'] != buyer['id']:
        await query.edit_message_text(t(lang, 'order_not_yours'))
        return

    if order['status'] != 'pending':
        await query.edit_message_text(
            t(lang, 'cant_cancel_status', status=fmt_status(order['status']))
        )
        return

    db.update_order_status(order_id, 'cancelled')

    # Avtomatik bekor qilish taymerini o'chiramiz
    if context.application.job_queue:
        jobs = context.application.job_queue.get_jobs_by_name(f"auto_cancel_{order_id}")
        for job in jobs:
            job.schedule_removal()

    await query.edit_message_text(
        t(lang, 'order_cancelled_done', oid=fmt_order_id(order_id)),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, 'btn_orders_back'), callback_data="buyer_orders")
        ]])
    )

    # Sotuvchiga bildirishnoma (sotuvchi tilida)
    try:
        if order.get('seller_tg'):
            seller = db.get_user_by_id(order['seller_id'])
            await context.bot.send_message(
                chat_id=order['seller_tg'],
                text=t(seller or 'uz', 'seller_notify_cancelled',
                       oid=fmt_order_id(order_id),
                       pname=html.escape(order.get('product_name') or ''))
            )
    except Exception as e:
        logging.error(f"Sotuvchiga 'bekor qilindi' bildirishnomasi ketmadi: {e}")


# ============================================================
# BUYURTMA BERISH (Order Flow)
# Bosqichlar: miqdor → yetkazish turi → (manzil) → to'lov → tasdiq → DB+bildirishnoma
# ============================================================

PAYMENT_LABELS = {
    'cash':     '💵 Naqd pul',
    'terminal': '💳 Terminal (plastik karta)',
    'p2p':      '📲 Karta raqamiga o\'tkazish (P2P)',
}

CARD_TYPE_LABELS = {
    'uzcard':     '🟦 Uzcard',
    'humo':       '🟩 Humo',
    'visa':       '🔵 Visa',
    'mastercard': '🔴 Mastercard',
}
DELIVERY_LABELS = {'delivery': '🚚 Yetkazib berish', 'pickup': '🚶 Olib ketaman'}


# Til-aware yorliqlar (yuqoridagi dict'lar eski moslik uchun qoladi)
def dlv_label(dlv, lang=DEFAULT_LANG):
    return {'delivery': t(lang, 'order_delivery'),
            'pickup': t(lang, 'order_pickup')}.get(dlv, dlv)


def pay_label(pay, lang=DEFAULT_LANG):
    return {'cash': t(lang, 'payment_cash'),
            'terminal': t(lang, 'payment_terminal'),
            'p2p': t(lang, 'payment_p2p')}.get(pay, pay)


def region_label_l(region_id, lang=DEFAULT_LANG):
    """db.get_region_label natijasini ('Viloyat → Tuman') til bo'yicha qaytaradi."""
    lbl = db.get_region_label(region_id)
    if not lbl or lang != 'ru':
        return lbl
    return ' → '.join(region_name(p, lang) for p in lbl.split(' → '))


def status_label(status, lang=DEFAULT_LANG):
    """Buyurtma/so'rov holatining til-aware yorlig'i."""
    return {
        'pending': t(lang, 'st_pending'),
        'confirmed': t(lang, 'st_confirmed'),
        'delivered': t(lang, 'st_delivered'),
        'cancelled': t(lang, 'st_cancelled'),
        'approved': t(lang, 'st_approved'),
        'rejected': t(lang, 'st_rejected'),
    }.get(status, fmt_status(status))


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot kartasidagi '🛒 Buyurtma berish' tugmasi."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)

    if not product:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'product_not_found')
        )
        return ConversationHandler.END

    if not product.get('in_stock'):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'product_out_of_stock')
        )
        return ConversationHandler.END

    # O'z mahsulotini buyurtma qilish — oldini olamiz
    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if buyer and buyer['id'] == product['seller_id']:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'product_own')
        )
        return ConversationHandler.END

    # Buyurtma spam tekshiruvi
    if buyer and check_order_spam(context, buyer['id'], product_id):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'order_spam')
        )
        return ConversationHandler.END

    # Ish vaqti tashqarisidami?
    closed_note = ""
    if is_shop_open_now(product.get('working_hours')) is False:
        closed_note = t(lang, 'frag_shop_closed_note',
                        wh=html.escape(product.get('working_hours') or ''))

    # Jarayon ma'lumotlarini saqlab qo'yamiz
    context.user_data['order_product'] = product
    context.user_data.pop('order_qty', None)
    context.user_data.pop('order_delivery_type', None)
    context.user_data.pop('order_address', None)
    context.user_data.pop('order_lat', None)
    context.user_data.pop('order_lon', None)
    context.user_data.pop('order_payment', None)

    # edit_message_text foto xabarida ishlamaydi — send_message ishlatamiz
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t(lang, 'order_qty_prompt',
               name=html.escape(product['name'] or ''),
               price=fmt_price(product['price']), closed=closed_note),
        parse_mode='HTML'
    )
    return ORDER_QUANTITY


async def order_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    try:
        qty = int(update.message.text.strip())
        if qty < 1 or qty > 999:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(lang, 'order_quantity_invalid'))
        return ORDER_QUANTITY

    product = context.user_data['order_product']

    # Stock_count tekshiruvi — agar zahira chegarasi qo'yilgan bo'lsa
    stock = product.get('stock_count')
    if stock is not None and qty > stock:
        await update.message.reply_text(
            t(lang, 'qty_only_n_available', stock=stock)
        )
        return ORDER_QUANTITY

    context.user_data['order_qty'] = qty
    total = qty * float(product['price'])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(dlv_label('delivery', lang), callback_data="ord_dlv_delivery")],
        [InlineKeyboardButton(dlv_label('pickup', lang), callback_data="ord_dlv_pickup")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="ord_cancel")],
    ])
    await update.message.reply_text(
        t(lang, 'order_total_delivery_q', total=fmt_price(total)),
        reply_markup=kb,
        parse_mode='HTML'
    )
    return ORDER_DELIVERY_TYPE


async def order_delivery_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "ord_cancel":
        await query.edit_message_text(t(lang, 'order_cancel'))
        context.user_data.pop('order_product', None)
        return ConversationHandler.END

    choice = query.data.replace("ord_dlv_", "")  # 'delivery' yoki 'pickup'
    context.user_data['order_delivery_type'] = choice

    # Sotuvchi karta ma'lumotini oldindan olamiz (P2P uchun ko'rsatish uchun)
    product = context.user_data.get('order_product', {})
    seller = db.get_user_by_id(product.get('seller_id')) if product.get('seller_id') else None
    seller_card = None
    if seller and seller.get('card_number'):
        seller_card = {
            'card_number': seller['card_number'],
            'card_owner': seller.get('card_owner'),
            'card_type': seller.get('card_type'),
        }

    if choice == 'pickup':
        await _ask_payment(query, seller_card_info=seller_card, lang=lang)
        return ORDER_PAYMENT

    # Yetkazib berish — manzil so'raymiz
    await query.edit_message_text(t(lang, 'delivery_address_ask'))
    await query.message.reply_text(
        t(lang, 'delivery_address_hint'),
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(t(lang, 'btn_send_location'), request_location=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
    )
    return ORDER_ADDRESS


async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        loc = update.message.location
        context.user_data['order_lat'] = loc.latitude
        context.user_data['order_lon'] = loc.longitude
        context.user_data['order_address'] = f"{loc.latitude:.5f}, {loc.longitude:.5f}"
        remember_buyer_geo(context, loc.latitude, loc.longitude)
    else:
        text = update.message.text.strip()
        if len(text) < 5:
            await update.message.reply_text(T(update, context, 'address_too_short'))
            return ORDER_ADDRESS
        context.user_data['order_address'] = text

    lang = get_lang(update, context)
    await update.message.reply_text(
        t(lang, 'address_accepted'),
        reply_markup=ReplyKeyboardRemove()
    )
    product = context.user_data.get('order_product', {})
    seller = db.get_user_by_id(product.get('seller_id')) if product.get('seller_id') else None
    seller_card = None
    if seller and seller.get('card_number'):
        seller_card = {
            'card_number': seller['card_number'],
            'card_owner': seller.get('card_owner'),
            'card_type': seller.get('card_type'),
        }
    await _ask_payment(update.message, seller_card_info=seller_card, lang=lang)
    return ORDER_PAYMENT


async def _ask_payment(target, seller_card_info=None, cb_prefix="ord_pay_", cancel_cb="ord_cancel",
                       lang=DEFAULT_LANG):
    """To'lov usulini tanlash. seller_card_info — sotuvchining karta ma'lumoti.
    cb_prefix/cancel_cb — yakka buyurtma uchun 'ord_pay_'/'ord_cancel', savat uchun 'cart_pay_'/'cart_cancel'."""

    p2p_note = ""
    if seller_card_info:
        cnum = seller_card_info.get('card_number') or ''
        # Karta raqamini formatlash: 8600 **** **** 1234
        if len(cnum) >= 4:
            masked = f"{cnum[:4]} {'**** ' * ((len(cnum)-8)//4)}{cnum[-4:]}".strip()
        else:
            masked = cnum
        owner = seller_card_info.get('card_owner') or ''
        ctype = CARD_TYPE_LABELS.get(seller_card_info.get('card_type', ''), '')
        p2p_note = t(lang, 'frag_p2p_card_note', ctype=ctype, masked=masked, owner=owner)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(pay_label('cash', lang),     callback_data=f"{cb_prefix}cash")],
        [InlineKeyboardButton(pay_label('terminal', lang), callback_data=f"{cb_prefix}terminal")],
        [InlineKeyboardButton(pay_label('p2p', lang),      callback_data=f"{cb_prefix}p2p")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'),       callback_data=cancel_cb)],
    ])
    text = t(lang, 'payment_method_choose', p2p_note=p2p_note)

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
    else:
        await target.reply_text(text, reply_markup=kb, parse_mode='HTML')


async def order_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "ord_cancel":
        await query.edit_message_text(t(lang, 'order_cancel'))
        return ConversationHandler.END

    method = query.data.replace("ord_pay_", "")  # 'cash' | 'card' | 'click'
    context.user_data['order_payment'] = method

    # Tasdiq ekrani
    product = context.user_data['order_product']
    qty = context.user_data['order_qty']
    total = qty * float(product['price'])
    dlv = context.user_data['order_delivery_type']

    address_frag = ""
    if dlv == 'delivery':
        address_frag = t(lang, 'frag_summary_address',
                         addr=html.escape(context.user_data.get('order_address') or ''))
    summary = t(lang, 'order_confirm_summary',
                pname=html.escape(product['name'] or ''),
                shop=html.escape(product.get('shop_name') or ''),
                qty=qty, total=fmt_price(total),
                dlv=dlv_label(dlv, lang), address=address_frag,
                pay=pay_label(method, lang))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data="ord_confirm_yes")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="ord_cancel")],
    ])
    await query.edit_message_text(summary, reply_markup=kb, parse_mode='HTML')
    return ORDER_CONFIRM


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "ord_cancel":
        await query.edit_message_text(t(lang, 'order_cancel'))
        return ConversationHandler.END

    # DB ga yozish
    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    product = context.user_data['order_product']
    qty = context.user_data['order_qty']
    total = qty * float(product['price'])
    dlv = context.user_data['order_delivery_type']

    order_id = db.create_order(
        buyer_id=buyer['id'],
        seller_id=product['seller_id'],
        product_id=product['id'],
        quantity=qty,
        total_price=total,
        delivery_address=context.user_data.get('order_address'),
        buyer_lat=context.user_data.get('order_lat'),
        buyer_lon=context.user_data.get('order_lon'),
        payment_method=context.user_data.get('order_payment'),
        delivery_type=dlv,
    )

    # Buyurtma spam cooldown belgilash
    mark_order_placed(context, buyer['id'], product['id'])

    await query.edit_message_text(
        t(lang, 'order_placed', oid=fmt_order_id(order_id)),
        parse_mode='HTML'
    )

    # 10 daqiqadan keyin avtomatik bekor qilish
    if context.application.job_queue:
        context.application.job_queue.run_once(
            auto_cancel_order_job,
            when=600,  # 10 daqiqa = 600 sekund
            data={
                'order_id': order_id,
                'buyer_tg': update.effective_user.id,
                'seller_tg': product.get('seller_tg'),
            },
            name=f"auto_cancel_{order_id}"
        )

        # 5 daqiqadan keyin sotuvchiga eslatma
        context.application.job_queue.run_once(
            reminder_order_job,
            when=300,  # 5 daqiqa = 300 sekund
            data={
                'order_id': order_id,
                'seller_tg': product.get('seller_tg'),
                'product_name': product.get('name', ''),
                'buyer_name': buyer.get('name', ''),
                'total_price': total,
            },
            name=f"reminder_{order_id}"
        )

    # Sotuvchiga bildirishnoma (sotuvchi tilida)
    try:
        seller_tg = product.get('seller_tg')
        if seller_tg:
            seller = db.get_user_by_id(product['seller_id'])
            slang = get_user_lang(seller) if seller else DEFAULT_LANG
            buyer_lat = context.user_data.get('order_lat')
            buyer_lon = context.user_data.get('order_lon')
            buyer_address = context.user_data.get('order_address') or ''

            text = t(slang, 'seller_new_order_notify',
                     oid=fmt_order_id(order_id),
                     pname=html.escape(product['name'] or ''),
                     qty=qty, total=fmt_price(total),
                     buyer=html.escape(buyer['name'] or ''),
                     phone=buyer.get('phone_number') or '—',
                     dlv=dlv_label(dlv, slang))

            # Masofa hisoblash (sotuvchi do'koni → xaridor)
            if dlv == 'delivery' and buyer_lat and buyer_lon:
                shop_lat = product.get('shop_lat')
                shop_lon = product.get('shop_lon')
                if shop_lat and shop_lon:
                    dist = haversine_km(shop_lat, shop_lon, buyer_lat, buyer_lon)
                    if dist is not None:
                        text += t(slang, 'frag_dist_from_shop', km=f"{dist:.1f}")
                _ba = human_address(buyer_address)
                if _ba:
                    text += t(slang, 'frag_seller_address', addr=html.escape(_ba))
                text += t(slang, 'seller_client_location_below')
            elif dlv == 'delivery':
                _ba = human_address(buyer_address)
                if _ba:
                    text += t(slang, 'frag_seller_address', addr=html.escape(_ba))

            text += "💳 " + pay_label(context.user_data.get('order_payment'), slang)

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(slang, 'btn_confirm'), callback_data=f"confirm_order_{order_id}")],
                [InlineKeyboardButton(t(slang, 'btn_reject'), callback_data=f"cancel_order_{order_id}")],
            ])
            await context.bot.send_message(
                chat_id=seller_tg, text=text, reply_markup=kb,
                parse_mode='HTML', disable_notification=False
            )

            # Agar xaridor lokatsiya yuborgan bo'lsa — alohida Telegram location xabari
            # Sotuvchi bosadi → Telegram xaritasi ochiladi va yo'l ko'rsatadi
            if dlv == 'delivery' and buyer_lat and buyer_lon:
                await context.bot.send_location(
                    chat_id=seller_tg,
                    latitude=buyer_lat,
                    longitude=buyer_lon
                )

    except Exception as e:
        logging.error(f"Sotuvchiga bildirishnoma ketmadi: {e}")

    # User_data'ni tozalaymiz
    for k in ('order_product', 'order_qty', 'order_delivery_type', 'order_address',
             'order_lat', 'order_lon', 'order_payment'):
        context.user_data.pop(k, None)

    return ConversationHandler.END


# ============================================================
# SAVAT (CART) — bir do'kondan bir nechta mahsulotni bitta buyurtmaga
# ============================================================
# Tamoyil: savat faqat BITTA do'kon uchun. Boshqa do'kondan qo'shilsa —
# yangi savat ochiladi (tasdiq bilan). Rasmiylashtirilganda har bir mahsulot
# alohida 'orders' qatori bo'lib yoziladi, lekin barchasi bitta order_group_id
# bilan bog'lanadi — shu sababli mavjud yakka-buyurtma kodi buzilmaydi, ammo
# xaridor ham, sotuvchi ham buni BITTA buyurtma (bitta raqam) sifatida ko'radi.

def _cart(context):
    """Joriy savat (dict) yoki None."""
    return context.user_data.get('cart')


def _cart_count(context):
    """Savatdagi jami dona soni."""
    cart = _cart(context)
    if not cart:
        return 0
    return sum(int(i.get('qty', 0)) for i in cart.get('items', {}).values())


def _cart_total(context):
    """Savatdagi jami summa."""
    cart = _cart(context)
    if not cart:
        return 0
    return sum(float(i.get('price', 0)) * int(i.get('qty', 0))
               for i in cart.get('items', {}).values())


def _cart_clear(context):
    context.user_data.pop('cart', None)
    for k in ('cart_dlv', 'cart_address', 'cart_lat', 'cart_lon', 'cart_payment'):
        context.user_data.pop(k, None)


async def cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulotni savatga qo'shadi (yoki +1). Boshqa do'kon bo'lsa — tasdiq so'raydi."""
    query = update.callback_query
    product_id = int(query.data.split("_")[2])
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)

    if not product or not product.get('in_stock') or product.get('status') == 'deleted':
        await query.answer(t(lang, 'product_out_of_stock'), show_alert=True)
        return

    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if buyer and buyer['id'] == product['seller_id']:
        await query.answer(t(lang, 'cart_cant_add_own'), show_alert=True)
        return

    cart = _cart(context)
    # Boshqa do'kon mahsuloti — yangi savat kerak
    if cart and cart.get('items') and cart.get('seller_id') != product['seller_id']:
        await query.answer()
        old_shop = cart.get('shop_name') or t(lang, 'other_shop_word')
        new_shop = product.get('shop_name') or t(lang, 'new_shop_word')
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(lang, 'cart_other_shop_q',
                   old=html.escape(old_shop), new=html.escape(new_shop)),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_new_cart_for', shop=new_shop[:20]),
                                      callback_data=f"cart_reset_add_{product_id}")],
                [InlineKeyboardButton(t(lang, 'btn_view_current_cart'), callback_data="cart_view")],
            ]),
            parse_mode='HTML'
        )
        return

    _cart_put(context, product, delta=1)
    cart = _cart(context)
    item = cart['items'].get(str(product_id)) if cart else None
    if not item:
        # Zahira 0 bo'lib qolgan bo'lsa qo'shilmaydi
        await query.answer(t(lang, 'cart_stock_empty'), show_alert=True)
        return
    await query.answer(t(lang, 'cart_added_toast', name=product['name'][:30], qty=item['qty']), show_alert=False)


async def cart_reset_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Joriy savatni tozalab, yangi do'kon mahsulotini qo'shadi."""
    query = update.callback_query
    product_id = int(query.data.split("_")[3])
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)
    if not product or not product.get('in_stock'):
        await query.answer(t(lang, 'product_unavailable_toast'), show_alert=True)
        return
    _cart_clear(context)
    _cart_put(context, product, delta=1)
    await query.answer(t(lang, 'new_cart_toast', name=product['name'][:30]), show_alert=False)
    # Do'kon mahsulotlariga qaytaramiz
    try:
        await query.edit_message_text(
            t(lang, 'new_cart_opened',
              shop=html.escape(product.get('shop_name') or ''),
              name=html.escape(product['name'])),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_view_cart'), callback_data="cart_view")],
                [InlineKeyboardButton(t(lang, 'btn_shop_products_menu'),
                                      callback_data=f"shop_products_{product['seller_id']}_0")],
            ]),
            parse_mode='HTML'
        )
    except Exception:
        pass


def _cart_put(context, product, delta=1):
    """Savatga mahsulot qo'shadi / sonini o'zgartiradi (zahira chegarasini hisobga olib)."""
    cart = _cart(context)
    if not cart or cart.get('seller_id') != product['seller_id']:
        cart = {
            'seller_id': product['seller_id'],
            'shop_name': product.get('shop_name') or '',
            'items': {},
        }
    pid = str(product['id'])
    item = cart['items'].get(pid, {'name': product['name'], 'price': float(product['price']), 'qty': 0})
    new_qty = item['qty'] + delta
    # Zahira chegarasi
    stock = product.get('stock_count')
    if stock is not None:
        new_qty = min(new_qty, int(stock))
    if new_qty <= 0:
        cart['items'].pop(pid, None)
    else:
        item['qty'] = new_qty
        item['price'] = float(product['price'])  # narx o'zgargan bo'lsa yangilaymiz
        item['name'] = product['name']
        cart['items'][pid] = item
    if cart['items']:
        context.user_data['cart'] = cart
    else:
        _cart_clear(context)


async def cart_inc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot sahifasidagi ➕ (toast bilan)."""
    query = update.callback_query
    product_id = int(query.data.split("_")[2])
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)
    if not product:
        await query.answer(t(lang, 'product_not_found_toast'), show_alert=True)
        return
    cart = _cart(context)
    cur = cart['items'].get(str(product_id), {}).get('qty', 0) if cart else 0
    stock = product.get('stock_count')
    if stock is not None and cur >= int(stock):
        await query.answer(t(lang, 'only_n_available_toast', stock=stock), show_alert=True)
        return
    _cart_put(context, product, delta=1)
    qty = _cart(context)['items'].get(str(product_id), {}).get('qty', 0) if _cart(context) else 0
    await query.answer(t(lang, 'cart_qty_toast', name=product['name'][:30], qty=qty), show_alert=False)


async def cart_dec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot sahifasidagi ➖ (toast bilan)."""
    query = update.callback_query
    product_id = int(query.data.split("_")[2])
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)
    if not product:
        await query.answer(t(lang, 'product_not_found_toast'), show_alert=True)
        return
    _cart_put(context, product, delta=-1)
    cart = _cart(context)
    qty = cart['items'].get(str(product_id), {}).get('qty', 0) if cart else 0
    if qty <= 0:
        await query.answer(t(lang, 'removed_from_cart_toast'), show_alert=False)
    else:
        await query.answer(t(lang, 'cart_qty_toast', name=product['name'][:30], qty=qty), show_alert=False)


async def cart_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savat tarkibini ko'rsatadi (miqdorni boshqarish + rasmiylashtirish)."""
    query = update.callback_query
    if query:
        await query.answer()

    lang = get_lang(update, context)
    cart = _cart(context)
    if not cart or not cart.get('items'):
        text = t(lang, 'cart_empty')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")]])
        if query:
            try:
                await query.edit_message_text(text, reply_markup=kb)
            except Exception:
                await context.bot.send_message(update.effective_chat.id, text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    seller_id = cart['seller_id']
    lines = [t(lang, 'cart_view_header', shop=html.escape(cart.get('shop_name') or ''))]
    keyboard = []
    for pid, item in cart['items'].items():
        subtotal = float(item['price']) * int(item['qty'])
        lines.append(t(lang, 'cart_view_item',
                       name=html.escape(item['name']), qty=item['qty'],
                       price=fmt_price(item['price']), subtotal=fmt_price(subtotal)))
        # Miqdor boshqaruvi
        keyboard.append([
            InlineKeyboardButton("➖", callback_data=f"cvdec_{pid}"),
            InlineKeyboardButton(f"{item['name'][:18]}: {item['qty']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cvinc_{pid}"),
            InlineKeyboardButton("🗑", callback_data=f"cvrm_{pid}"),
        ])

    lines.append(t(lang, 'cart_view_total', total=fmt_price(_cart_total(context)), count=_cart_count(context)))

    keyboard.append([InlineKeyboardButton(t(lang, 'btn_checkout'), callback_data="cart_checkout")])
    keyboard.append([
        InlineKeyboardButton(t(lang, 'btn_add_more'), callback_data=f"shop_products_{seller_id}_0"),
        InlineKeyboardButton(t(lang, 'btn_clear'), callback_data="cart_clear"),
    ])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_back_to_shop'), callback_data=f"shop_{seller_id}")])

    text = "\n".join(lines)
    if query:
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except Exception:
            await context.bot.send_message(update.effective_chat.id, text,
                                           reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def cart_view_inc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savat ekranidagi ➕ — qayta render qiladi."""
    query = update.callback_query
    product_id = int(query.data.split("_")[1])
    product = db.get_product_by_id(product_id)
    if product:
        cart = _cart(context)
        cur = cart['items'].get(str(product_id), {}).get('qty', 0) if cart else 0
        stock = product.get('stock_count')
        if stock is not None and cur >= int(stock):
            await query.answer(t(get_lang(update, context), 'only_n_available_toast', stock=stock), show_alert=True)
            return
        _cart_put(context, product, delta=1)
    await cart_view(update, context)


async def cart_view_dec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savat ekranidagi ➖ — qayta render qiladi."""
    query = update.callback_query
    product_id = int(query.data.split("_")[1])
    product = db.get_product_by_id(product_id)
    if product:
        _cart_put(context, product, delta=-1)
    await cart_view(update, context)


async def cart_view_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savat ekranidagi 🗑 — mahsulotni butunlay olib tashlaydi."""
    query = update.callback_query
    product_id = int(query.data.split("_")[1])
    cart = _cart(context)
    if cart:
        cart.get('items', {}).pop(str(product_id), None)
        if not cart.get('items'):
            _cart_clear(context)
        else:
            context.user_data['cart'] = cart
    await cart_view(update, context)


async def cart_clear_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savatni tozalashdan oldin tasdiq."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)
    await query.edit_message_text(
        t(lang, 'cart_clear_confirm'),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_yes_clear'), callback_data="cart_clear_yes")],
            [InlineKeyboardButton(t(lang, 'btn_no_back'), callback_data="cart_view")],
        ])
    )


async def cart_clear_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_lang(update, context)
    await query.answer(t(lang, 'cart_cleared_toast'))
    _cart_clear(context)
    await query.edit_message_text(
        t(lang, 'cart_cleared'),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")]])
    )


# --- Savatni rasmiylashtirish (alohida conversation) ---

async def cart_checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rasmiylashtirish: yetkazish turini so'raydi."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    cart = _cart(context)
    if not cart or not cart.get('items'):
        await query.edit_message_text(
            t(lang, 'cart_empty'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")]])
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(dlv_label('delivery', lang), callback_data="cart_dlv_delivery")],
        [InlineKeyboardButton(dlv_label('pickup', lang), callback_data="cart_dlv_pickup")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="cart_cancel")],
    ])
    await query.edit_message_text(
        t(lang, 'cart_checkout_header',
          count=_cart_count(context), total=fmt_price(_cart_total(context))),
        reply_markup=kb, parse_mode='HTML'
    )
    return CART_DELIVERY_TYPE


async def cart_delivery_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "cart_cancel":
        await query.edit_message_text(
            t(lang, 'checkout_cancelled'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_back_to_cart'), callback_data="cart_view")]])
        )
        return ConversationHandler.END

    choice = query.data.replace("cart_dlv_", "")
    context.user_data['cart_dlv'] = choice

    cart = _cart(context)
    seller = db.get_user_by_id(cart['seller_id']) if cart else None
    seller_card = None
    if seller and seller.get('card_number'):
        seller_card = {
            'card_number': seller['card_number'],
            'card_owner': seller.get('card_owner'),
            'card_type': seller.get('card_type'),
        }

    if choice == 'pickup':
        await _ask_payment(query, seller_card_info=seller_card,
                           cb_prefix="cart_pay_", cancel_cb="cart_cancel", lang=lang)
        return CART_PAYMENT

    await query.edit_message_text(t(lang, 'delivery_address_ask'))
    await query.message.reply_text(
        t(lang, 'delivery_address_hint'),
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(t(lang, 'btn_send_location'), request_location=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
    )
    return CART_ADDRESS


async def cart_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        loc = update.message.location
        context.user_data['cart_lat'] = loc.latitude
        context.user_data['cart_lon'] = loc.longitude
        context.user_data['cart_address'] = f"{loc.latitude:.5f}, {loc.longitude:.5f}"
        remember_buyer_geo(context, loc.latitude, loc.longitude)
    else:
        text = update.message.text.strip()
        if len(text) < 5:
            await update.message.reply_text(T(update, context, 'address_too_short'))
            return CART_ADDRESS
        context.user_data['cart_address'] = text

    lang = get_lang(update, context)
    await update.message.reply_text(t(lang, 'address_accepted'), reply_markup=ReplyKeyboardRemove())

    cart = _cart(context)
    seller = db.get_user_by_id(cart['seller_id']) if cart else None
    seller_card = None
    if seller and seller.get('card_number'):
        seller_card = {
            'card_number': seller['card_number'],
            'card_owner': seller.get('card_owner'),
            'card_type': seller.get('card_type'),
        }
    await _ask_payment(update.message, seller_card_info=seller_card,
                       cb_prefix="cart_pay_", cancel_cb="cart_cancel", lang=lang)
    return CART_PAYMENT


async def cart_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "cart_cancel":
        await query.edit_message_text(
            t(lang, 'checkout_cancelled'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_back_to_cart'), callback_data="cart_view")]])
        )
        return ConversationHandler.END

    method = query.data.replace("cart_pay_", "")
    context.user_data['cart_payment'] = method

    cart = _cart(context)
    dlv = context.user_data.get('cart_dlv', 'delivery')

    lines = [t(lang, 'cart_confirm_header'),
             t(lang, 'cart_confirm_shop', shop=html.escape(cart.get('shop_name') or ''))]
    for item in cart['items'].values():
        subtotal = float(item['price']) * int(item['qty'])
        lines.append(t(lang, 'cart_confirm_item', name=html.escape(item['name']),
                       qty=item['qty'], price=fmt_price(item['price']), subtotal=fmt_price(subtotal)))
    lines.append(t(lang, 'cart_confirm_total', total=fmt_price(_cart_total(context))))
    lines.append(t(lang, 'cart_confirm_delivery', dlv=dlv_label(dlv, lang)))
    if dlv == 'delivery':
        lines.append(t(lang, 'cart_confirm_address', addr=html.escape(context.user_data.get('cart_address') or '')))
    lines.append(t(lang, 'cart_confirm_payment', pay=pay_label(method, lang)))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data="cart_confirm_yes")],
        [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="cart_cancel")],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode='HTML')
    return CART_CONFIRM


async def cart_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "cart_cancel":
        await query.edit_message_text(
            t(lang, 'checkout_cancelled'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_back_to_cart'), callback_data="cart_view")]])
        )
        return ConversationHandler.END

    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    cart = _cart(context)
    if not buyer or not cart or not cart.get('items'):
        await query.edit_message_text(t(lang, 'cart_empty_expired'))
        _cart_clear(context)
        return ConversationHandler.END

    dlv = context.user_data.get('cart_dlv', 'delivery')
    payment = context.user_data.get('cart_payment')
    addr = context.user_data.get('cart_address')
    b_lat = context.user_data.get('cart_lat')
    b_lon = context.user_data.get('cart_lon')

    # Har bir mahsulotni qayta tekshiramiz va buyurtma qatori yaratamiz
    created_ids = []
    skipped = []
    grand_total = 0.0
    for pid, item in list(cart['items'].items()):
        product = db.get_product_by_id(int(pid))
        if not product or not product.get('in_stock') or product.get('status') == 'deleted':
            skipped.append(item['name'])
            continue
        qty = int(item['qty'])
        stock = product.get('stock_count')
        if stock is not None:
            qty = min(qty, int(stock))
        if qty <= 0:
            skipped.append(item['name'])
            continue
        price = float(product['price'])
        line_total = qty * price
        grand_total += line_total
        oid = db.create_order(
            buyer_id=buyer['id'],
            seller_id=cart['seller_id'],
            product_id=int(pid),
            quantity=qty,
            total_price=line_total,
            delivery_address=addr,
            buyer_lat=b_lat,
            buyer_lon=b_lon,
            payment_method=payment,
            delivery_type=dlv,
        )
        created_ids.append(oid)
        mark_order_placed(context, buyer['id'], int(pid))

    if not created_ids:
        await query.edit_message_text(
            t(lang, 'cart_nothing_available'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")]])
        )
        _cart_clear(context)
        return ConversationHandler.END

    # Guruh kodi = birinchi buyurtma id (do'kon ichida noyob)
    group_id = str(created_ids[0])
    db.set_orders_group(created_ids, group_id)

    seller = db.get_user_by_id(cart['seller_id'])
    seller_tg = seller.get('telegram_id') if seller else None

    skip_note = ""
    if skipped:
        skip_note = t(lang, 'cart_skip_note',
                      names=', '.join(html.escape(s) for s in skipped[:5]))

    await query.edit_message_text(
        t(lang, 'cart_order_placed',
          oid=fmt_order_id(int(group_id)), count=len(created_ids),
          total=fmt_price(grand_total), skip=skip_note),
        parse_mode='HTML'
    )

    # Guruh uchun avtomatik bekor + eslatma
    if context.application.job_queue:
        context.application.job_queue.run_once(
            auto_cancel_group_job, when=600,
            data={'group_id': group_id, 'buyer_tg': update.effective_user.id, 'seller_tg': seller_tg},
            name=f"auto_cancel_group_{group_id}"
        )
        context.application.job_queue.run_once(
            reminder_group_job, when=300,
            data={'group_id': group_id, 'seller_tg': seller_tg},
            name=f"reminder_group_{group_id}"
        )

    # Sotuvchiga BITTA bildirishnoma (barcha mahsulotlar bilan)
    try:
        if seller_tg:
            await _notify_seller_group(context, group_id, seller_tg, dlv, payment, b_lat, b_lon, addr)
    except Exception as e:
        logging.error(f"Sotuvchiga savat bildirishnomasi ketmadi: {e}")

    _cart_clear(context)
    return ConversationHandler.END


async def _notify_seller_group(context, group_id, seller_tg, dlv, payment, b_lat, b_lon, addr):
    """Sotuvchiga savat buyurtmasi bo'yicha bitta bildirishnoma (mahsulotlar ro'yxati bilan)."""
    orders = db.get_orders_in_group(group_id)
    if not orders:
        return
    first = orders[0]
    grand = sum(float(o['total_price']) for o in orders)

    # Sotuvchi tili
    seller = db.get_user_by_id(first.get('seller_id')) if first.get('seller_id') else None
    slang = get_user_lang(seller) if seller else DEFAULT_LANG

    lines = [
        t(slang, 'seller_group_header', oid=fmt_order_id(int(group_id)), count=len(orders)),
    ]
    for o in orders:
        lines.append(t(slang, 'seller_group_item', name=html.escape(o['product_name'] or ''),
                       qty=o['quantity'], price=fmt_price(o['product_price']), total=fmt_price(o['total_price'])))
    lines.append("")
    lines.append(t(slang, 'seller_group_total', total=fmt_price(grand)))
    lines.append(t(slang, 'seller_group_buyer', buyer=html.escape(first.get('buyer_name') or '')))
    lines.append(f"📞 {first.get('buyer_phone') or '—'}")
    lines.append(f"🚚 {dlv_label(dlv, slang)}")

    if dlv == 'delivery' and b_lat and b_lon:
        s_lat, s_lon = first.get('shop_lat'), first.get('shop_lon')
        if s_lat and s_lon:
            d = haversine_km(s_lat, s_lon, b_lat, b_lon)
            if d is not None:
                lines.append(t(slang, 'grp_dist_from_shop', km=f"{d:.1f}"))
        _ba = human_address(addr)
        if _ba:
            lines.append(t(slang, 'grp_address', addr=html.escape(_ba)))
        lines.append(t(slang, 'grp_client_location'))
    elif dlv == 'delivery':
        _ba = human_address(addr)
        if _ba:
            lines.append(t(slang, 'grp_address', addr=html.escape(_ba)))

    lines.append("💳 " + pay_label(payment, slang))
    lines.append(t(slang, 'seller_group_confirm_prompt'))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(slang, 'btn_confirm'), callback_data=f"gconfirm_{group_id}")],
        [InlineKeyboardButton(t(slang, 'btn_reject'), callback_data=f"gcancel_{group_id}")],
    ])
    await context.bot.send_message(chat_id=seller_tg, text="\n".join(lines),
                                   reply_markup=kb, parse_mode='HTML')
    if dlv == 'delivery' and b_lat and b_lon:
        try:
            await context.bot.send_location(chat_id=seller_tg, latitude=b_lat, longitude=b_lon)
        except Exception:
            pass


# --- Guruh (savat) buyurtma — SOTUVCHI tomoni ---

async def group_status_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """gconfirm_/gcancel_/gdeliver_ — butun guruh holatini o'zgartiradi."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 1)
    action = parts[0]  # gconfirm / gcancel / gdeliver
    group_id = parts[1]

    orders = db.get_orders_in_group(group_id)
    if not orders:
        await query.edit_message_text(T(update, context, 'order_not_found'))
        return

    # Egalik tekshiruvi
    seller_user = db.get_user_by_telegram_id(update.effective_user.id)
    is_owner = bool(seller_user and seller_user.get('id') == orders[0].get('seller_id'))
    is_admin = (update.effective_user.id == ADMIN_ID) or (seller_user and seller_user.get('role') == 'admin')
    if not (is_owner or is_admin):
        await query.answer(t(get_lang(update, context), 'not_your_order_toast'), show_alert=True)
        return

    status_map = {'gconfirm': 'confirmed', 'gcancel': 'cancelled', 'gdeliver': 'delivered'}
    new_status = status_map.get(action)
    if not new_status:
        return

    # Guruh taymerlarini o'chiramiz
    if new_status in ('confirmed', 'cancelled') and context.application.job_queue:
        for nm in (f"auto_cancel_group_{group_id}", f"reminder_group_{group_id}"):
            for job in context.application.job_queue.get_jobs_by_name(nm):
                job.schedule_removal()

    # Tasdiqlashda har bir mahsulot zahirasini kamaytiramiz
    if new_status == 'confirmed':
        for o in orders:
            try:
                db.decrement_stock_on_confirm(o['product_id'], o['quantity'])
            except Exception as e:
                logging.error(f"Guruh stock kamaytirish xatosi: {e}")

    for o in orders:
        db.update_order_status(o['id'], new_status)

    # Xaridorga BITTA bildirishnoma (xaridor tilida)
    try:
        buyer_tg = orders[0].get('buyer_tg')
        if buyer_tg:
            buyer = db.get_user_by_id(orders[0]['buyer_id'])
            blang = get_user_lang(buyer) if buyer else DEFAULT_LANG
            is_pickup = orders[0].get('delivery_type') == 'pickup'
            n = len(orders)
            oid = fmt_order_id(int(group_id))
            if new_status == 'confirmed':
                txt = t(blang, 'grp_confirmed_pickup' if is_pickup else 'grp_confirmed_delivery',
                        oid=oid, n=n)
                kb = None
            elif new_status == 'cancelled':
                txt = t(blang, 'grp_cancelled_notify', oid=oid, n=n)
                kb = None
            else:  # delivered
                txt = t(blang, 'grp_delivered_pickup' if is_pickup else 'grp_delivered_delivery',
                        oid=oid, n=n)
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                    t(blang, 'btn_leave_rating'), callback_data=f"order_rate_{orders[0]['id']}")]])
            await context.bot.send_message(chat_id=buyer_tg, text=txt, reply_markup=kb, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Xaridorga guruh bildirishnomasi ketmadi: {e}")

    await seller_group_order_detail(update, context, group_id=group_id)


async def seller_group_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str = None):
    """Sotuvchi uchun savat buyurtmasi sahifasi."""
    query = update.callback_query
    if group_id is None:
        group_id = query.data.split("_", 2)[2]  # seller_gorder_<gid>

    orders = db.get_orders_in_group(group_id)
    lang = get_lang(update, context)
    if not orders:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    first = orders[0]
    status = first['status']
    dlv = first.get('delivery_type', 'delivery')
    pay = first.get('payment_method') or 'cash'
    grand = sum(float(o['total_price']) for o in orders)

    lines = [t(lang, 'grp_seller_header', oid=fmt_order_id(int(group_id)), n=len(orders))]
    for o in orders:
        lines.append(t(lang, 'seller_group_item', name=html.escape(o['product_name'] or ''),
                       qty=o['quantity'], price=fmt_price(o['product_price']), total=fmt_price(o['total_price'])))
    lines.append(t(lang, 'grp_total_plain', total=fmt_price(grand)))
    lines.append(t(lang, 'grp_status_line', status=status_label(status, lang)))
    lines.append(f"🚚 {dlv_label(dlv, lang)}")

    pay_note = ""
    if pay == 'p2p':
        seller_user = db.get_user_by_telegram_id(update.effective_user.id)
        if seller_user and seller_user.get('card_number'):
            cnum = seller_user['card_number']
            masked = f"{cnum[:4]} **** **** {cnum[-4:]}"
            ctype = CARD_TYPE_LABELS.get(seller_user.get('card_type', ''), '💳')
            pay_note = t(lang, 'p2p_your_card', ctype=ctype, masked=masked)
    lines.append(t(lang, 'grp_pay_line', pay=pay_label(pay, lang), paynote=pay_note))
    lines.append("\n" + t(lang, 'seller_group_buyer', buyer=html.escape(first.get('buyer_name') or '')))
    lines.append(t(lang, 'grp_phone_line', phone=fmt_phone(first.get('buyer_phone'))))

    if dlv == 'delivery':
        b_lat, b_lon = first.get('buyer_lat'), first.get('buyer_lon')
        addr_txt = human_address(first.get('delivery_address'))
        if addr_txt:
            lines.append(t(lang, 'courier_addr', addr=html.escape(addr_txt)))
        if b_lat is not None and b_lon is not None:
            lines.append(t(lang, 'grp_map_line', url=f"https://www.google.com/maps/search/?api=1&query={b_lat},{b_lon}"))
            s_lat, s_lon = first.get('shop_lat'), first.get('shop_lon')
            if s_lat is not None and s_lon is not None:
                d = haversine_km(s_lat, s_lon, b_lat, b_lon)
                if d is not None:
                    lines.append(t(lang, 'courier_dist', km=f"{d:.1f}"))
    lines.append(t(lang, 'grp_date_plain', date=fmt_datetime(first.get('created_at'))))

    keyboard = []
    if status == 'pending':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data=f"gconfirm_{group_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_reject'), callback_data=f"gcancel_{group_id}")])
    elif status == 'confirmed':
        if dlv == 'delivery':
            keyboard.append([InlineKeyboardButton(t(lang, 'btn_delivered'), callback_data=f"gdeliver_{group_id}")])
        else:
            keyboard.append([InlineKeyboardButton(t(lang, 'btn_buyer_received'), callback_data=f"gdeliver_{group_id}")])
    if dlv == 'delivery' and status in ('pending', 'confirmed'):
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_forward_courier'), callback_data=f"gcrfwd_{group_id}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_correspondence'), callback_data=f"msgs_{first['id']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_orders")])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode='HTML', disable_web_page_preview=True)


async def seller_forward_courier_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Savat buyurtmasini kuryerga uzatish (lokatsiya + barcha mahsulotlar)."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    group_id = query.data.split("_", 1)[1]  # gcrfwd_<gid>

    orders = db.get_orders_in_group(group_id)
    lang = get_lang(update, context)
    if not orders:
        await context.bot.send_message(chat_id, t(lang, 'order_not_found'))
        return

    first = orders[0]
    seller_user = db.get_user_by_telegram_id(update.effective_user.id)
    is_owner = bool(seller_user and seller_user.get('id') == first.get('seller_id'))
    is_admin = (update.effective_user.id == ADMIN_ID) or (seller_user and seller_user.get('role') == 'admin')
    if not (is_owner or is_admin):
        await context.bot.send_message(chat_id, t(lang, 'not_your_order_plain'))
        return

    b_lat, b_lon = first.get('buyer_lat'), first.get('buyer_lon')
    s_lat, s_lon = first.get('shop_lat'), first.get('shop_lon')
    pay = first.get('payment_method') or 'cash'
    addr_txt = human_address(first.get('delivery_address'))
    grand = sum(float(o['total_price']) for o in orders)

    if b_lat is not None and b_lon is not None:
        try:
            await context.bot.send_location(chat_id=chat_id, latitude=b_lat, longitude=b_lon)
        except Exception as e:
            logging.warning(f"group courier send_location xatosi: {e}")

    lines = [t(lang, 'courier_group_header', oid=fmt_order_id(int(group_id)), n=len(orders)), ""]
    for o in orders:
        lines.append(t(lang, 'courier_group_item', name=html.escape(o['product_name'] or ''), qty=o['quantity']))
    lines += [
        "",
        t(lang, 'courier_sum', total=fmt_price(grand)),
        t(lang, 'courier_pay', pay=pay_label(pay, lang)),
        "",
        t(lang, 'courier_client', buyer=html.escape(first.get('buyer_name') or '')),
        t(lang, 'courier_phone', phone=fmt_phone(first.get('buyer_phone'))),
    ]
    if addr_txt:
        lines.append(t(lang, 'courier_addr', addr=html.escape(addr_txt)))
    if b_lat is not None and b_lon is not None:
        lines.append(t(lang, 'courier_map', url=f"https://www.google.com/maps/search/?api=1&query={b_lat},{b_lon}"))
        if s_lat is not None and s_lon is not None:
            d = haversine_km(s_lat, s_lon, b_lat, b_lon)
            if d is not None:
                lines.append(t(lang, 'courier_dist', km=f"{d:.1f}"))
            lines.append(t(lang, 'courier_route', url=f"https://www.google.com/maps/dir/?api=1&origin={s_lat},{s_lon}&destination={b_lat},{b_lon}"))
    if not addr_txt and (b_lat is None or b_lon is None):
        lines.append(t(lang, 'courier_no_addr'))

    await context.bot.send_message(chat_id, "\n".join(lines), parse_mode='HTML', disable_web_page_preview=True)
    await context.bot.send_message(
        chat_id,
        t(lang, 'courier_instructions_short'),
        parse_mode='HTML'
    )


# --- Guruh (savat) buyurtma — XARIDOR tomoni ---

async def buyer_group_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str = None):
    """Xaridor uchun savat buyurtmasi sahifasi."""
    query = update.callback_query
    if group_id is None:
        group_id = query.data.split("_", 2)[2]  # gorder_detail_<gid>

    orders = db.get_orders_in_group(group_id)
    lang = get_lang(update, context)
    if not orders:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    first = orders[0]
    status = first['status']
    dlv = first.get('delivery_type', 'delivery')
    pay = first.get('payment_method', 'cash')
    grand = sum(float(o['total_price']) for o in orders)

    steps = [t(lang, 'step_new'), t(lang, 'step_confirmed'),
             t(lang, 'step_delivered') if dlv == 'delivery' else t(lang, 'step_picked'),
             t(lang, 'step_rated')]
    step_idx = {'pending': 0, 'confirmed': 1, 'delivered': 2, 'cancelled': 0}.get(status, 0)
    timeline = ""
    for i, step in enumerate(steps):
        if i < step_idx:
            timeline += f"✅ {step}\n"
        elif i == step_idx and status != 'cancelled':
            timeline += f"▶️ {step}{t(lang, 'timeline_now')}\n"
        else:
            timeline += f"⬜ {step}\n"

    status_guide = {
        'pending': t(lang, 'status_guide_pending_group'),
        'confirmed': (t(lang, 'status_guide_confirmed_delivery') if dlv == 'delivery'
                      else t(lang, 'status_guide_confirmed_pickup')),
        'delivered': t(lang, 'status_guide_delivered'),
        'cancelled': t(lang, 'status_guide_cancelled'),
    }

    lines = [t(lang, 'group_order_header', oid=fmt_order_id(int(group_id)), count=len(orders))]
    for o in orders:
        lines.append(t(lang, 'seller_group_item', name=html.escape(o['product_name'] or ''),
                       qty=o['quantity'], price=fmt_price(o['product_price']), total=fmt_price(o['total_price'])))
    lines.append(t(lang, 'cart_confirm_total', total=fmt_price(grand)))
    lines.append(f"🚚 {dlv_label(dlv, lang)}")
    lines.append(f"💳 {pay_label(pay, lang)}")
    lines.append(f"🏪 {html.escape(first.get('shop_name') or '')}")

    keyboard = []
    map_button = None
    if first.get('shop_lat') and first.get('shop_lon'):
        slat, slon = first['shop_lat'], first['shop_lon']
        loc_line = t(lang, 'frag_order_address',
                     addr=html.escape(first.get('shop_address') or t(lang, 'address_word')))
        if first.get('shop_landmark'):
            loc_line += t(lang, 'frag_order_landmark', lm=html.escape(first['shop_landmark']))
        lines.append(loc_line)
        if first.get('buyer_lat') and first.get('buyer_lon'):
            d = haversine_km(first['buyer_lat'], first['buyer_lon'], slat, slon)
            if d is not None:
                lines.append(t(lang, 'dist_line_plain', km=d))
            map_button = InlineKeyboardButton(t(lang, 'btn_show_route'),
                url=f"https://www.google.com/maps/dir/{first['buyer_lat']},{first['buyer_lon']}/{slat},{slon}")
        else:
            map_button = InlineKeyboardButton(t(lang, 'btn_shop_location'),
                url=f"https://www.google.com/maps/search/?api=1&query={slat},{slon}")

    lines.append(t(lang, 'group_date_line', date=fmt_datetime(first.get('created_at'))))
    lines.append(f"<b>{t(lang, 'label_status')}:</b>\n{timeline}")
    lines.append(f"<i>{status_guide.get(status, '')}</i>")

    if status == 'pending':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_cancel_order'), callback_data=f"gbuyer_cancel_{group_id}")])
    if status == 'confirmed' and dlv == 'pickup':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_got_item'), callback_data=f"gbuyer_pickup_{group_id}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_send_message'), callback_data=f"order_msg_{first['id']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_correspondence'), callback_data=f"msgs_{first['id']}")])
    can_rate = (status == 'delivered') or (status == 'confirmed' and dlv == 'pickup')
    if can_rate:
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_leave_rating'), callback_data=f"order_rate_{first['id']}")])
    if map_button:
        keyboard.append([map_button])
    if first.get('seller_username'):
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_tg_at', u=first['seller_username']),
                                              url=f"https://t.me/{first['seller_username']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_orders")])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode='HTML', disable_web_page_preview=True)


async def buyer_cancel_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor savat buyurtmasini bekor qiladi (faqat pending bo'lsa)."""
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_", 2)[2]  # gbuyer_cancel_<gid>

    lang = get_lang(update, context)
    orders = db.get_orders_in_group(group_id)
    if not orders:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if not buyer or buyer['id'] != orders[0].get('buyer_id'):
        await query.answer(t(lang, 'not_your_order_toast'), show_alert=True)
        return
    if orders[0]['status'] != 'pending':
        await query.answer(t(lang, 'cant_cancel_now_toast'), show_alert=True)
        await buyer_group_order_detail(update, context, group_id=group_id)
        return

    # Taymerlarni o'chiramiz va guruhni bekor qilamiz
    if context.application.job_queue:
        for nm in (f"auto_cancel_group_{group_id}", f"reminder_group_{group_id}"):
            for job in context.application.job_queue.get_jobs_by_name(nm):
                job.schedule_removal()
    for o in orders:
        db.update_order_status(o['id'], 'cancelled')

    # Sotuvchiga xabar (sotuvchi tilida)
    try:
        seller_tg = orders[0].get('seller_tg')
        if seller_tg:
            seller = db.get_user_by_id(orders[0]['seller_id'])
            await context.bot.send_message(
                chat_id=seller_tg,
                text=t(seller or 'uz', 'seller_notify_group_cancelled',
                       oid=fmt_order_id(int(group_id)), count=len(orders))
            )
    except Exception:
        pass

    await buyer_group_order_detail(update, context, group_id=group_id)


async def buyer_pickup_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor 'oldim' — savat buyurtmasini yetkazilgan deb belgilaydi (pickup)."""
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_", 2)[2]  # gbuyer_pickup_<gid>

    lang = get_lang(update, context)
    orders = db.get_orders_in_group(group_id)
    if not orders:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return
    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if not buyer or buyer['id'] != orders[0].get('buyer_id'):
        await query.answer(t(lang, 'not_your_order_toast'), show_alert=True)
        return
    if orders[0]['status'] != 'confirmed':
        await buyer_group_order_detail(update, context, group_id=group_id)
        return
    for o in orders:
        db.update_order_status(o['id'], 'delivered')
    await buyer_group_order_detail(update, context, group_id=group_id)


async def auto_cancel_group_job(context: ContextTypes.DEFAULT_TYPE):
    """10 daqiqada tasdiqlanmagan savat buyurtmasini avtomatik bekor qiladi."""
    data = context.job.data
    group_id = data.get('group_id')
    orders = db.get_orders_in_group(group_id)
    if not orders:
        return
    pending = [o for o in orders if o['status'] == 'pending']
    if not pending:
        return
    for o in pending:
        db.update_order_status(o['id'], 'cancelled')
    try:
        first = orders[0]
        buyer = db.get_user_by_id(first['buyer_id'])
        seller = db.get_user_by_id(first['seller_id'])
        oid = fmt_order_id(int(group_id))
        if data.get('buyer_tg'):
            await context.bot.send_message(
                chat_id=data['buyer_tg'],
                text=t(buyer or 'uz', 'job_group_autocancel_buyer', oid=oid)
            )
        if data.get('seller_tg'):
            await context.bot.send_message(
                chat_id=data['seller_tg'],
                text=t(seller or 'uz', 'job_group_autocancel_seller', oid=oid)
            )
    except Exception as e:
        logging.error(f"auto_cancel_group_job xabar xatosi: {e}")


async def reminder_group_job(context: ContextTypes.DEFAULT_TYPE):
    """5 daqiqadan keyin sotuvchiga eslatma (savat buyurtmasi hali pending bo'lsa)."""
    data = context.job.data
    group_id = data.get('group_id')
    orders = db.get_orders_in_group(group_id)
    if not orders or orders[0]['status'] != 'pending':
        return
    try:
        if data.get('seller_tg'):
            seller = db.get_user_by_id(orders[0]['seller_id'])
            slang = get_user_lang(seller) if seller else DEFAULT_LANG
            grand = sum(float(o['total_price']) for o in orders)
            await context.bot.send_message(
                chat_id=data['seller_tg'],
                text=t(slang, 'job_group_reminder_seller',
                       oid=fmt_order_id(int(group_id)), n=len(orders), total=fmt_price(grand)),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    t(slang, 'btn_open_order'), callback_data=f"seller_gorder_{group_id}")]])
            )
    except Exception as e:
        logging.error(f"reminder_group_job xatosi: {e}")


# ============================================================
# SELLER PANEL
# ============================================================

async def seller_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchining ulangan kanallari ro'yxati + qo'shish/o'chirish."""
    query = update.callback_query
    if query:
        await query.answer()
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    channels = db.get_seller_channels(user['id']) if user else []

    keyboard = []
    if channels:
        text = t(lang, 'channels_menu_connected') + "\n"
        has_inactive = False
        for ch in channels:
            title = ch.get('channel_title')
            if not title:
                # Sarlavha saqlanmagan bo'lsa — eng yaxshi imkon bilan aniqlaymiz
                try:
                    chat = await context.bot.get_chat(ch['channel_id'])
                    title = chat.title
                    if title:
                        db.update_seller_channel_title(user['id'], ch['channel_id'], title)
                except Exception:
                    title = ch['channel_id']
            is_active = ch.get('is_active', 1)
            mark = "✅" if is_active else "⚠️"
            if not is_active:
                has_inactive = True
            text += f"\n{mark} {html.escape(str(title))}"
            label = f"🗑 {title}"
            if len(label) > 32:
                label = label[:31] + "…"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"chremove_{ch['channel_id']}")])
        if has_inactive:
            text += "\n\n" + t(lang, 'channels_menu_inactive_hint')
    else:
        text = t(lang, 'channels_menu_empty')

    keyboard.append([InlineKeyboardButton(t(lang, 'btn_add_channel'), callback_data="seller_link_channel")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")])
    markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')


async def seller_channel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni o'chirib, menyuni qayta ko'rsatadi."""
    query = update.callback_query
    user = db.get_user_by_telegram_id(update.effective_user.id)
    channel_id = query.data.replace("chremove_", "", 1)
    if user:
        db.remove_seller_channel(user['id'], channel_id)
    await seller_channels_menu(update, context)


async def seller_link_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni ulash: yo'riqnoma ko'rsatadi va kanal postini (forward) kutadi."""
    query = update.callback_query
    if query:
        await query.answer()
    lang = get_lang(update, context)
    bot_me = await context.bot.get_me()
    text = t(lang, 'link_channel_prompt', bot=bot_me.username)
    if query:
        await query.edit_message_text(text, parse_mode='HTML', disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode='HTML', disable_web_page_preview=True)
    return LINK_CHANNEL_WAIT


async def link_channel_wait_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward o'rniga oddiy matn kelsa — qayta eslatma."""
    lang = get_lang(update, context)
    await update.message.reply_text(t(lang, 'link_channel_not_channel'), parse_mode='HTML')
    return LINK_CHANNEL_WAIT


async def link_channel_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward qilingan kanal postidan kanalni aniqlaydi, botning adminligini
    tekshiradi va sotuvchi <-> kanal bog'lanishini saqlaydi."""
    msg = update.message
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Kanalni aniqlash (PTB versiyasiga bardoshli: forward_origin yoki forward_from_chat)
    channel_chat = None
    origin = getattr(msg, 'forward_origin', None)
    if origin is not None and getattr(origin, 'type', None) == 'channel':
        channel_chat = getattr(origin, 'chat', None)
    if channel_chat is None:
        fwd = getattr(msg, 'forward_from_chat', None)
        if fwd is not None and getattr(fwd, 'type', None) == 'channel':
            channel_chat = fwd
    if channel_chat is None:
        await msg.reply_text(t(lang, 'link_channel_not_channel'), parse_mode='HTML')
        return LINK_CHANNEL_WAIT

    bot_me = await context.bot.get_me()

    # Bot o'sha kanalda admin va post yubora oladimi?
    try:
        member = await context.bot.get_chat_member(channel_chat.id, bot_me.id)
    except Exception:
        member = None
    if member is None or member.status not in ('administrator', 'creator'):
        await msg.reply_text(t(lang, 'link_channel_not_admin', bot=bot_me.username), parse_mode='HTML')
        return LINK_CHANNEL_WAIT
    if member.status == 'administrator' and not getattr(member, 'can_post_messages', False):
        await msg.reply_text(t(lang, 'link_channel_no_post_perm'), parse_mode='HTML')
        return LINK_CHANNEL_WAIT

    # Boshqa sotuvchi shu kanalni ulaganmi? (#5 — yumshoq ogohlantirish, bloklamaymiz)
    other_owners = db.find_channel_owners(channel_chat.id, exclude_seller_id=user['id']) if user else []

    # Saqlaymiz (ko'p kanal — seller_channels jadvali)
    title = channel_chat.title or str(channel_chat.id)
    is_new = db.add_seller_channel(user['id'], channel_chat.id, title) if user else False
    if is_new:
        await msg.reply_text(
            t(lang, 'link_channel_success', title=html.escape(title)),
            parse_mode='HTML'
        )
    else:
        await msg.reply_text(t(lang, 'link_channel_already'), parse_mode='HTML')
    if other_owners:
        await msg.reply_text(t(lang, 'link_channel_shared_warn'), parse_mode='HTML')
    await seller_channels_menu(update, context)
    return ConversationHandler.END


async def seller_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    context.user_data['active_mode'] = 'seller'
    lang = get_lang(update, context)

    # Tasdiqlanmagan sotuvchi — maxsus panel ko'rsatamiz
    if user and not user.get('is_approved') and user.get('role') != 'admin':
        req = db.get_seller_request_by_user(user['id'])
        req_status = req['status'] if req else None

        if req_status == 'rejected':
            # Rad etilgan — qayta so'rov yuborish imkoniyati
            text = t(lang, 'seller_rejected_panel')
            keyboard = [
                [InlineKeyboardButton(t(lang, 'btn_reapply'), callback_data="reapply_seller")],
                [InlineKeyboardButton(t(lang, 'btn_contact_admin'), callback_data="contact_admin")],
                [InlineKeyboardButton(t(lang, 'btn_buyer_mode'), callback_data="switch_to_buyer_confirm")],
            ]
        else:
            # Kutilmoqda (pending) yoki boshqa holat
            text = t(lang, 'seller_not_approved')
            keyboard = [
                [InlineKeyboardButton(t(lang, 'btn_contact_admin'), callback_data="contact_admin")],
                [InlineKeyboardButton(t(lang, 'btn_buyer_mode'), callback_data="switch_to_buyer_confirm")],
            ]

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
            )
        return

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_add_product'), callback_data="seller_add_product")],
        [InlineKeyboardButton(t(lang, 'btn_my_products'), callback_data="seller_products")],
        [InlineKeyboardButton(t(lang, 'btn_my_channels'), callback_data="seller_channels_menu")],
        [InlineKeyboardButton(t(lang, 'btn_orders'), callback_data="seller_orders")],
        [InlineKeyboardButton(t(lang, 'btn_stats'), callback_data="seller_stats")],
        [InlineKeyboardButton(t(lang, 'btn_messages'), callback_data="seller_messages")],
        [InlineKeyboardButton(t(lang, 'btn_seller_reviews'), callback_data="seller_reviews")],
        [InlineKeyboardButton(t(lang, 'btn_profile'), callback_data="seller_profile")],
        [InlineKeyboardButton(t(lang, 'btn_buyer_mode'), callback_data="switch_to_buyer_confirm")],
        [InlineKeyboardButton(t(lang, 'btn_ai_assistant'), callback_data="ai_assistant")],
        [InlineKeyboardButton(t(lang, 'btn_contact_admin'), callback_data="contact_admin")],
    ]
    if CHANNEL_URL:
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_official_channel'), url=CHANNEL_URL)])

    text = t(lang, 'seller_panel_full',
             shop=user.get('shop_name') or t(lang, 'not_specified'),
             address=user.get('shop_address') or t(lang, 'not_specified'))

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text(
            t(lang, 'bottom_hint'),
            reply_markup=seller_bottom_kb(lang)
        )


async def seller_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi o'z reytinglarini ko'radi."""
    query = update.callback_query
    if query:
        await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    reviews = db.get_seller_reviews(user['id'])
    avg = db.get_seller_avg_rating(user['id'])

    if not reviews:
        text = t(lang, 'reviews_none')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    lines = [t(lang, 'seller_avg_header', avg=f"{avg:.1f}", count=len(reviews))]

    for r in reviews[:20]:  # so'nggi 20 ta
        sr = r['rating'] or 0
        s_stars = "⭐" * sr + "☆" * (5 - sr)
        buyer = html.escape(r.get('buyer_name') or t(lang, 'anonymous'))
        comment = html.escape(r.get('comment') or '')
        date = fmt_datetime(r.get('created_at'))
        line = t(lang, 'review_shop_to') + s_stars
        pr = r.get('product_rating')
        if pr:
            line += t(lang, 'review_product_to') + f"{'⭐' * pr}{'☆' * (5 - pr)}"
        line += f"\n👤 {buyer} · {date}"
        if comment:
            line += f"\n💬 {comment}"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + t(lang, 'reviews_old_cut_seller')

    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")]])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')


async def buyer_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor o'zi qoldirgan reytinglarni ko'radi."""
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, u.shop_name, u.name as seller_name, p.name as product_name
        FROM reviews r
        JOIN users u ON r.seller_id=u.id
        LEFT JOIN orders o ON r.order_id=o.id
        LEFT JOIN products p ON o.product_id=p.id
        WHERE r.buyer_id=?
        ORDER BY r.created_at DESC
        LIMIT 20
    """, (user['id'],))
    reviews = [dict(r) for r in cursor.fetchall()]

    lang = get_lang(update, context)
    if not reviews:
        text = t(lang, 'my_reviews_empty')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    lines = [t(lang, 'my_reviews_header', n=len(reviews))]
    for r in reviews:
        sr = r['rating'] or 0
        s_stars = "⭐" * sr + "☆" * (5 - sr)
        shop = html.escape(r.get('shop_name') or r.get('seller_name') or '—')
        product = html.escape(r.get('product_name') or '—')
        comment = html.escape(r.get('comment') or '')
        date = fmt_datetime(r.get('created_at'))
        line = f"\n📦 {product} · {date}"
        pr = r.get('product_rating')
        if pr:
            line += f"\n{t(lang, 'review_to_product')}{'⭐' * pr}{'☆' * (5 - pr)}"
        line += f"\n🏪 {shop} — {s_stars}"
        if comment:
            line += f"\n💬 {comment}"
        lines.append(line)

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="buyer_panel")]])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')


async def seller_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi statistikasi: buyurtmalar, daromad, mahsulotlar — hafta/oy/jami."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    stats = db.get_seller_stats(user['id'])
    avg_rating = db.get_seller_avg_rating(user['id'])

    text = t(lang, 'seller_stats_body',
             shop=html.escape(user.get('shop_name') or ''),
             products=stats['products_count'], rating=f"{avg_rating:.1f}",
             week_orders=stats['week_orders'], week_revenue=fmt_price(stats['week_revenue']),
             month_orders=stats['month_orders'], month_revenue=fmt_price(stats['month_revenue']),
             total_orders=stats['total_orders'], pending=stats['pending'],
             confirmed=stats['confirmed'], delivered=stats['delivered'],
             cancelled=stats['cancelled'], total_revenue=fmt_price(stats['total_revenue']))

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_detailed_excel'), callback_data="seller_export_excel")],
            [InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")],
        ]),
        parse_mode='HTML'
    )


async def seller_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchining barcha ma'lumotlarini kengaytirilgan Excel fayl sifatida yuboradi:
    buyurtmalar (kim, qachon, nima olgani), mahsulotlar, reytinglar va umumiy hisobot."""
    query = update.callback_query
    lang = get_lang(update, context)
    ru = (lang == 'ru')
    await query.answer(t(lang, 'excel_preparing'))

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.message.reply_text(t(lang, 'user_not_found'))
        return

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        import datetime as dt
        import os

        seller_id = user['id']
        orders = db.get_seller_orders_list(seller_id)
        products = db.get_products_by_seller(seller_id)
        reviews = db.get_seller_reviews(seller_id)
        stats = db.get_seller_stats(seller_id)
        avg_rating = db.get_seller_avg_rating(seller_id)

        status_label = {
            'pending': 'Новый' if ru else 'Yangi',
            'confirmed': 'Подтверждён' if ru else 'Tasdiqlangan',
            'delivered': 'Доставлен' if ru else 'Yetkazilgan',
            'cancelled': 'Отменён' if ru else 'Bekor qilingan',
        }
        delivery_label = {
            'delivery': 'Доставка' if ru else 'Yetkazib berish',
            'pickup': 'Самовывоз' if ru else 'Olib ketish',
        }
        payment_label = {
            'cash': 'Наличные' if ru else 'Naqd pul',
            'card': 'Терминал' if ru else 'Terminal',
            'terminal': 'Терминал' if ru else 'Terminal',
            'p2p': 'Карта (P2P)' if ru else 'Karta (P2P)',
            'click': 'Click',
        }
        product_status_label = {
            'active': 'В продаже' if ru else 'Sotuvda',
            'reserve': 'В резерве' if ru else 'Zahirada',
            'deleted': 'Удалён' if ru else "O'chirilgan",
        }

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="1a8a2e")
        header_align = Alignment(horizontal="center", vertical="center")

        def style_header(ws_):
            for cell in ws_[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

        def auto_width(ws_):
            for col in ws_.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=0)
                ws_.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 45)

        wb = openpyxl.Workbook()

        # ---- 1) Buyurtmalar ----
        ws = wb.active
        ws.title = "Заказы" if ru else "Buyurtmalar"
        ws.append(
            ["ID заказа", "Дата", "Покупатель", "Телефон покупателя",
             "Товар", "Цена за шт", "Кол-во", "Сумма",
             "Статус", "Тип доставки", "Способ оплаты", "Адрес"]
            if ru else
            ["Buyurtma ID", "Sana", "Xaridor", "Xaridor telefoni",
             "Mahsulot", "Dona narxi", "Miqdor", "Jami summa",
             "Holat", "Yetkazish turi", "To'lov usuli", "Manzil"]
        )
        style_header(ws)
        for o in orders:
            ws.append([
                o.get('id'),
                fmt_datetime(o.get('created_at')),
                o.get('buyer_name') or '',
                o.get('buyer_phone') or '',
                o.get('product_name') or '',
                o.get('product_price') or 0,
                o.get('quantity') or 0,
                o.get('total_price') or 0,
                status_label.get(o.get('status') or '', o.get('status') or ''),
                delivery_label.get(o.get('delivery_type') or '', o.get('delivery_type') or ''),
                payment_label.get(o.get('payment_method') or '', o.get('payment_method') or ''),
                o.get('delivery_address') or '',
            ])
        auto_width(ws)

        # ---- 2) Mahsulotlar (sotilgan soni va daromad bilan) ----
        # Yetkazilgan buyurtmalardan har bir mahsulot bo'yicha jami hisoblaymiz
        sold_count = {}
        sold_revenue = {}
        for o in orders:
            if (o.get('status') or '') == 'delivered':
                pid = o.get('product_id')
                sold_count[pid] = sold_count.get(pid, 0) + (o.get('quantity') or 0)
                sold_revenue[pid] = sold_revenue.get(pid, 0) + (o.get('total_price') or 0)

        ws2 = wb.create_sheet("Товары" if ru else "Mahsulotlar")
        ws2.append(
            ["ID", "Название", "Категория", "Цена", "Статус", "Остаток",
             "Продано (шт)", "Доход (сум)", "Дата добавления"]
            if ru else
            ["ID", "Nom", "Kategoriya", "Narx", "Holat", "Zahira",
             "Sotilgan (dona)", "Daromad (so'm)", "Qo'shilgan sana"]
        )
        style_header(ws2)
        for p in products:
            st = p.get('status') or ('active' if p.get('in_stock') else 'reserve')
            ws2.append([
                p.get('id'),
                p.get('name') or '',
                p.get('category_name') or '',
                p.get('price') or 0,
                product_status_label.get(st, st),
                p.get('stock_count') if p.get('stock_count') is not None else ('Без лимита' if ru else 'Cheksiz'),
                sold_count.get(p.get('id'), 0),
                sold_revenue.get(p.get('id'), 0),
                fmt_datetime(p.get('created_at')),
            ])
        auto_width(ws2)

        # ---- 3) Reytinglar ----
        ws3 = wb.create_sheet("Отзывы" if ru else "Reytinglar")
        ws3.append(["Дата", "Покупатель", "Оценка", "Комментарий"] if ru
                   else ["Sana", "Xaridor", "Baho", "Izoh"])
        style_header(ws3)
        for r in reviews:
            ws3.append([
                fmt_datetime(r.get('created_at')),
                r.get('buyer_name') or ('Аноним' if ru else 'Anonim'),
                r.get('rating') or 0,
                r.get('comment') or '',
            ])
        auto_width(ws3)

        # ---- 4) Umumiy hisobot ----
        ws4 = wb.create_sheet("Сводка" if ru else "Umumiy")
        ws4.append(["Показатель", "Значение"] if ru else ["Ko'rsatkich", "Qiymat"])
        style_header(ws4)
        if ru:
            summary = [
                ("Название магазина", user.get('shop_name') or '—'),
                ("Кол-во товаров", stats.get('products_count', 0)),
                ("Средний рейтинг", round(avg_rating, 2)),
                ("Кол-во отзывов", len(reviews)),
                ("Всего заказов", stats.get('total_orders', 0)),
                ("Новые (в ожидании)", stats.get('pending', 0)),
                ("Подтверждённые", stats.get('confirmed', 0)),
                ("Доставленные", stats.get('delivered', 0)),
                ("Отменённые", stats.get('cancelled', 0)),
                ("Последние 7 дней — заказы", stats.get('week_orders', 0)),
                ("Последние 7 дней — доход", stats.get('week_revenue', 0)),
                ("Последние 30 дней — заказы", stats.get('month_orders', 0)),
                ("Последние 30 дней — доход", stats.get('month_revenue', 0)),
                ("Общий доход (доставленные)", stats.get('total_revenue', 0)),
            ]
        else:
            summary = [
                ("Do'kon nomi", user.get('shop_name') or '—'),
                ("Mahsulotlar soni", stats.get('products_count', 0)),
                ("O'rtacha reyting", round(avg_rating, 2)),
                ("Reytinglar soni", len(reviews)),
                ("Jami buyurtmalar", stats.get('total_orders', 0)),
                ("Yangi (kutilmoqda)", stats.get('pending', 0)),
                ("Tasdiqlangan", stats.get('confirmed', 0)),
                ("Yetkazilgan", stats.get('delivered', 0)),
                ("Bekor qilingan", stats.get('cancelled', 0)),
                ("So'nggi 7 kun — buyurtma", stats.get('week_orders', 0)),
                ("So'nggi 7 kun — daromad", stats.get('week_revenue', 0)),
                ("So'nggi 30 kun — buyurtma", stats.get('month_orders', 0)),
                ("So'nggi 30 kun — daromad", stats.get('month_revenue', 0)),
                ("Jami daromad (yetkazilgan)", stats.get('total_revenue', 0)),
            ]
        for k, v in summary:
            ws4.append([k, v])
        auto_width(ws4)

        ts = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
        filename = f"tezbozor_hisobot_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        wb.save(filename)

        shop_caption = user.get('shop_name') or t(lang, 'excel_shop_default')
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(filename, 'rb'),
            filename=filename,
            caption=t(lang, 'excel_caption', shop=shop_caption,
                      orders=len(orders), products=len(products),
                      reviews=len(reviews), ts=ts)
        )
        try:
            os.remove(filename)
        except Exception:
            pass

    except ImportError:
        await query.message.reply_text(
            t(lang, 'excel_not_installed'),
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Sotuvchi Excel eksport xatosi: {e}")
        await query.message.reply_text(t(lang, 'error_generic', e=e))


async def seller_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    # Callback (inline) yoki Reply tugma (matn) — ikkalasida ham ishlasin
    async def _show(text, **kw):
        if query:
            await query.edit_message_text(text, **kw)
        else:
            await update.message.reply_text(text, **kw)

    # Tasdiqlanmagan sotuvchi mahsulot qo'sha olmaydi
    user = db.get_user_by_telegram_id(update.effective_user.id)
    lang = get_lang(update, context)
    if user and not user.get('is_approved') and user.get('role') != 'admin':
        await _show(
            t(lang, 'seller_not_approved'),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_contact_admin'), callback_data="contact_admin")],
                [InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")],
            ])
        )
        return ConversationHandler.END

    context.user_data['adding_product'] = True
    # Eski qiymatlarni tozalaymiz (oldingi yarim qolgan jarayonni)
    for k in ('product_name', 'product_price', 'product_category', 'product_desc',
              'product_photo', 'product_photos'):
        context.user_data.pop(k, None)
    context.user_data['product_photos'] = []   # 4 tagacha rasm shu yerda yig'iladi
    await _show(t(lang, 'add_product_name_ask'))
    return PRODUCT_NAME


async def seller_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    lang = get_lang(update, context)
    # Validatsiya: uzunlik
    if len(name) < 3:
        await update.message.reply_text(t(lang, 'name_too_short'))
        return PRODUCT_NAME
    if len(name) > 100:
        await update.message.reply_text(t(lang, 'name_too_long'))
        return PRODUCT_NAME

    context.user_data['product_name'] = name
    await update.message.reply_text(t(lang, 'add_product_price_ask'))
    return PRODUCT_PRICE


async def seller_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.replace(" ", "").replace(",", "").replace("\u00A0", "")
    lang = get_lang(update, context)
    try:
        price = float(raw)
    except ValueError:
        await update.message.reply_text(t(lang, 'price_invalid'))
        return PRODUCT_PRICE

    # Validatsiya: musbat va mantiqiy chegara
    if price <= 0:
        await update.message.reply_text(t(lang, 'price_positive'))
        return PRODUCT_PRICE
    if price > 1_000_000_000:
        await update.message.reply_text(t(lang, 'price_too_big'))
        return PRODUCT_PRICE

    context.user_data['product_price'] = price

    categories = db.get_all_categories()
    keyboard = [[InlineKeyboardButton(f"{cat[2]} {category_name(cat[1], lang)}", callback_data=f"prodcat_{cat[0]}")] for cat in categories]
    await update.message.reply_text(t(lang, 'choose_category'), reply_markup=InlineKeyboardMarkup(keyboard))
    return PRODUCT_CATEGORY


async def seller_add_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    context.user_data['product_category'] = category_id

    await query.edit_message_text(T(update, context, 'add_product_desc_ask'))
    return PRODUCT_DESC


async def seller_add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    elif len(desc) > 500:
        await update.message.reply_text(t(lang, 'desc_too_long'))
        return PRODUCT_DESC

    context.user_data['product_desc'] = desc

    context.user_data.setdefault('product_photos', [])
    await update.message.reply_text(t(lang, 'add_photo_ask'))
    return PRODUCT_PHOTO


async def seller_add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = None
    lang = get_lang(update, context)

    if update.message.photo:
        # Eng katta o'lchamdagi rasmni olamiz
        photo = update.message.photo[-1]

        # Hajm tekshiruvi: 5 MB dan katta bo'lmasin
        if photo.file_size and photo.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'photo_too_big'))
            return PRODUCT_PHOTO

        # O'lcham tekshiruvi: kamida 200x200 piksel
        if photo.width and photo.height:
            if photo.width < 200 or photo.height < 200:
                await update.message.reply_text(t(lang, 'photo_too_small'))
                return PRODUCT_PHOTO

        photo_file_id = photo.file_id

    elif update.message.document:
        # Document sifatida yuborilgan rasmni tekshiramiz
        doc = update.message.document
        mime = doc.mime_type or ''

        if not mime.startswith('image/'):
            await update.message.reply_text(t(lang, 'only_images'))
            return PRODUCT_PHOTO

        # Hajm tekshiruvi
        if doc.file_size and doc.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'photo_too_big_doc'))
            return PRODUCT_PHOTO

        photo_file_id = doc.file_id

    elif update.message.sticker:
        await update.message.reply_text(t(lang, 'no_sticker'))
        return PRODUCT_PHOTO

    elif update.message.text and update.message.text.strip() == "-":
        # '-' = tugatish: yangi rasm qo'shmaymiz (rasmsiz yoki yetarli) — keyingi bosqich
        return await _proceed_after_photos(update, context)
    else:
        await update.message.reply_text(t(lang, 'send_photo_or_skip'))
        return PRODUCT_PHOTO

    # Bu yergacha yetib keldik — demak yangi rasm bor
    photos = context.user_data.setdefault('product_photos', [])
    photos.append(photo_file_id)
    n = len(photos)

    if n >= db.MAX_PRODUCT_IMAGES:
        await update.message.reply_text(t(lang, 'photos_max_added', n=n))
        return await _proceed_after_photos(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_add_more_photo'), callback_data="addphoto_more")],
        [InlineKeyboardButton(t(lang, 'btn_continue'), callback_data="addphoto_done")],
    ])
    await update.message.reply_text(
        t(lang, 'photos_added_n', n=n, max=db.MAX_PRODUCT_IMAGES),
        reply_markup=kb
    )
    return PRODUCT_PHOTO


async def _proceed_after_photos(update, context):
    """Rasm bosqichidan keyin: atributlar bo'lsa so'raydi, bo'lmasa mahsulotni saqlaydi."""
    category_id = context.user_data.get('product_category')
    templates = db.get_category_templates(category_id) if category_id else []
    if templates:
        context.user_data['attr_templates'] = templates
        context.user_data['attr_index'] = 0
        context.user_data['product_attrs'] = {}
        return await _ask_next_attr(update, context)
    return await _save_product(update, context)


async def add_photo_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Yana rasm qo'shish' tugmasi — keyingi rasmni so'raydi."""
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('product_photos', []))
    await query.edit_message_text(T(update, context, 'next_photo_ask', n=n, max=db.MAX_PRODUCT_IMAGES))
    return PRODUCT_PHOTO


async def add_photo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Davom etish' tugmasi — keyingi bosqichga o'tadi."""
    query = update.callback_query
    await query.answer()
    return await _proceed_after_photos(update, context)


async def _ask_next_attr(update, context):
    """Navbatdagi atributni so'raydi."""
    templates = context.user_data.get('attr_templates', [])
    idx = context.user_data.get('attr_index', 0)

    if idx >= len(templates):
        return await _save_product(update, context)

    lang = get_lang(update, context)
    tmpl = templates[idx]
    required_mark = " *" if tmpl['is_required'] else t(lang, 'attr_optional_mark')
    hint = t(lang, 'attr_eg', hint=tmpl['hint']) if tmpl.get('hint') else ""
    skip_note = "" if tmpl['is_required'] else t(lang, 'attr_skip_note')

    if tmpl['attr_type'] == 'select' and tmpl.get('hint'):
        # Tanlov variantlarini tugma sifatida ko'rsatamiz
        options = [o.strip() for o in tmpl['hint'].split('/')]
        kb = [[InlineKeyboardButton(opt, callback_data=f"attr_{opt}")] for opt in options]
        if not tmpl['is_required']:
            kb.append([InlineKeyboardButton(t(lang, 'btn_attr_skip'), callback_data="attr_-")])
        msg = f"📝 {tmpl['attr_label']}{required_mark}{hint}"
        if update.message:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        msg = f"📝 {tmpl['attr_label']}{required_mark}{hint}{skip_note}"
        if update.message:
            await update.message.reply_text(msg)
        else:
            await update.callback_query.message.reply_text(msg)

    return PRODUCT_ATTRS


async def seller_add_product_attr_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn atribut qabul qilish."""
    templates = context.user_data.get('attr_templates', [])
    idx = context.user_data.get('attr_index', 0)
    tmpl = templates[idx]

    value = update.message.text.strip()
    if value == '-':
        if tmpl['is_required']:
            await update.message.reply_text(T(update, context, 'attr_required_field'))
            return PRODUCT_ATTRS
        value = None

    if value:
        context.user_data['product_attrs'][tmpl['attr_key']] = value

    context.user_data['attr_index'] = idx + 1
    return await _ask_next_attr(update, context)


async def seller_add_product_attr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma orqali atribut tanlash."""
    query = update.callback_query
    await query.answer()

    templates = context.user_data.get('attr_templates', [])
    idx = context.user_data.get('attr_index', 0)
    tmpl = templates[idx]

    value = query.data.replace("attr_", "")
    if value != '-':
        context.user_data['product_attrs'][tmpl['attr_key']] = value

    context.user_data['attr_index'] = idx + 1
    return await _ask_next_attr(update, context)


async def _build_ad_caption(product):
    """Mahsulot uchun reklama matnini (caption) qaytaradi: (matn, parse_mode).
    Avval AI takrorlanmas reklama yozishga urinadi; bo'lmasa — tuzilgan HTML matn."""
    cat = product.get('category_name') or product.get('category')
    cat_emoji = product.get('category_emoji') or '📂'
    cat_line = f"\n{cat_emoji} {html.escape(str(cat))}" if cat else ""
    shop_name = product.get('shop_name')
    shop_line = f"\n🏪 {html.escape(str(shop_name))}" if shop_name else ""
    region_lbl = region_label_l(product.get('seller_region_id'), DEFAULT_LANG)
    region_line = f"\n🌍 {html.escape(region_lbl)}" if region_lbl else ""
    loc = best_location_text(product.get('shop_address'), product.get('shop_landmark'))
    loc_line = f"\n📍 {html.escape(loc)}" if loc else ""
    prod_rating = product.get('prod_avg_rating') or 0
    prod_cnt = product.get('prod_review_count') or 0
    rating_line = f"\n⭐ {prod_rating:.1f} ({prod_cnt})" if prod_cnt else ""
    desc = (product.get('description') or "").strip()
    if len(desc) > 300:
        desc = desc[:300].rstrip() + "…"
    desc_line = f"\n\n📝 {html.escape(desc)}" if desc else ""

    caption = (
        f"🆕 <b>{html.escape(product.get('name') or '')}</b>"
        f"\n💵 {fmt_price(product.get('price'))}"
        f"{cat_line}{shop_line}{region_line}{loc_line}{rating_line}{desc_line}"
    )
    parse_mode = 'HTML'

    # AI takrorlanmas reklama matni (faktlardan kelib chiqib)
    try:
        ad_text = await ai_assistant.generate_ad_caption(
            name=product.get('name') or '',
            price_text=fmt_price(product.get('price')),
            category=str(cat) if cat else '',
            description=(product.get('description') or ''),
            shop=str(shop_name) if shop_name else '',
            location=(loc or region_lbl or ''),
            lang=DEFAULT_LANG,
        )
    except Exception as e:
        logging.warning(f"Reklama matni olinmadi: {e}")
        ad_text = None
    if ad_text:
        # AI matni — oddiy matn (emoji + bezak). HTML parse qilinmaydi (xavfsiz).
        caption = ad_text
        parse_mode = None
    return caption, parse_mode


async def _build_ad_design_bytes(context, product):
    """Mahsulot rasmiga reklama dizayni qo'yib JPEG bytes qaytaradi (yoki None)."""
    photo = product.get('image_url')
    if not (photo and ad_design.is_enabled()):
        return None
    try:
        tg_file = await context.bot.get_file(photo)
        raw = bytes(await tg_file.download_as_bytearray())
        badges = ["YANGI", "ORIGINAL", "SIFATLI", "TOP TANLOV", "OMMABOP"]
        badge = badges[(product.get('id') or 0) % len(badges)]
        shop_name = product.get('shop_name')
        region_lbl = region_label_l(product.get('seller_region_id'), DEFAULT_LANG)
        return await asyncio.to_thread(
            ad_design.build_ad_image, raw,
            price_text=fmt_price(product.get('price')),
            badge_text=badge,
            shop_text=(str(shop_name) if shop_name else (region_lbl or '')),
        )
    except Exception as e:
        logging.warning(f"Reklama dizayni yasalmadi: {e}")
        return None


async def post_product_to_channel(context, product_id, *,
                                  caption_override=None, parse_mode_override=None,
                                  image_override=None):
    """Mahsulotni markaziy kanalga VA sotuvchining shaxsiy kanaliga post qiladi.

    caption_override / parse_mode_override — sotuvchi ko'rib tasdiqlagan AYNAN o'sha
    matnni joylash uchun (preview bilan 100% mos bo'lsin).
    image_override — allaqachon yuklangan (dizayn) rasm file_id si; berilsa qayta
    dizayn qilinmaydi va qayta yuklanmaydi.
    Xato yuz bersa ham asosiy oqimga (saqlash/status) ta'sir qilmaydi."""
    try:
        product = db.get_product_by_id(product_id)
        if not product:
            return

        bot_me = await context.bot.get_me()
        deep_link = f"https://t.me/{bot_me.username}?start=product_{product_id}"

        # === REKLAMA MATNI (A) ===
        if caption_override is not None:
            caption, caption_parse_mode = caption_override, parse_mode_override
        else:
            caption, caption_parse_mode = await _build_ad_caption(product)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Sotib olish", url=deep_link)
        ]])

        # Maqsad kanallar: (chat_id, owner_seller_id). Markaziy kanal — owner None.
        # Faqat FAOL sotuvchi kanallariga yuboramiz (yetimlari tashlab ketiladi).
        targets = []
        seen = set()
        if CHANNEL_ID:
            targets.append((CHANNEL_ID, None))
            seen.add(str(CHANNEL_ID))
        seller_id = product.get('seller_id')
        if seller_id:
            for ch in db.get_active_seller_channels(seller_id):
                cid = ch.get('channel_id')
                if cid and str(cid) not in seen:
                    targets.append((cid, seller_id))
                    seen.add(str(cid))

        photo = product.get('image_url')

        # === REKLAMA DIZAYNI (B) ===
        # image_override berilsa — tayyor file_id ni hamma kanalga qayta ishlatamiz.
        # Aks holda dizaynni yasab, birinchi yuborishdan keyin file_id ni eslab qolamiz.
        reusable_id = image_override
        designed_bytes = None
        if reusable_id is None:
            designed_bytes = await _build_ad_design_bytes(context, product)

        for chat_id, owner_id in targets:
            try:
                if reusable_id or designed_bytes or photo:
                    if reusable_id:
                        send_photo_arg = reusable_id
                    elif designed_bytes is not None:
                        send_photo_arg = io.BytesIO(designed_bytes)
                    else:
                        send_photo_arg = photo
                    sent = await context.bot.send_photo(
                        chat_id=chat_id, photo=send_photo_arg,
                        caption=caption, parse_mode=caption_parse_mode, reply_markup=keyboard,
                    )
                    # Birinchi yuborilgan rasmni keyingi kanallar uchun eslab qolamiz
                    if reusable_id is None:
                        try:
                            reusable_id = sent.photo[-1].file_id
                        except Exception:
                            reusable_id = None
                else:
                    await context.bot.send_message(
                        chat_id=chat_id, text=caption,
                        parse_mode=caption_parse_mode, reply_markup=keyboard,
                    )
            except (Forbidden, BadRequest) as e:
                # Doimiy xato: bot kanaldan chiqarilgan / huquqi yo'q / kanal o'chgan.
                # Sotuvchi kanali bo'lsa — yetim deb belgilaymiz va sotuvchini ogohlantiramiz.
                logging.warning(f"Channel post permanent error (product {product_id}, chat {chat_id}): {e}")
                if owner_id is not None and db.deactivate_seller_channel(owner_id, chat_id, str(e)):
                    try:
                        seller = db.get_user_by_id(owner_id)
                        seller_tg = seller.get('telegram_id') if seller else None
                        if seller_tg:
                            slang = get_user_lang(seller)
                            await context.bot.send_message(
                                chat_id=seller_tg,
                                text=t(slang, 'channel_deactivated_notify'),
                                parse_mode='HTML',
                            )
                    except Exception as notify_err:
                        logging.warning(f"Channel deactivation notify failed (seller {owner_id}): {notify_err}")
            except Exception as e:
                # Vaqtinchalik xato (tarmoq/limit) — kanalni o'chirmaymiz, faqat loglaymiz.
                logging.error(f"Channel post failed (product {product_id}, chat {chat_id}): {e}")
    except Exception as e:
        logging.error(f"post_product_to_channel failed (product {product_id}): {e}")


# ============================================================
# REKLAMA KO'RINISHI (preview) — kanalga joylashdan oldin tasdiqlash
# ============================================================
def _ad_preview_control_kb(lang):
    """Preview ostidagi boshqaruv tugmalari."""
    rows = [[InlineKeyboardButton(t(lang, 'ad_confirm_publish'), callback_data="adprev_publish")]]
    if ai_assistant.is_enabled():
        rows.append([InlineKeyboardButton(t(lang, 'ad_regen'), callback_data="adprev_regen")])
    rows.append([InlineKeyboardButton(t(lang, 'ad_edit_text'), callback_data="adprev_edit")])
    rows.append([InlineKeyboardButton(t(lang, 'ad_skip'), callback_data="adprev_skip")])
    return InlineKeyboardMarkup(rows)


async def _render_ad_preview(context, chat_id, lang, prev):
    """Saqlangan preview holatidan AYNAN kanaldagidek ko'rinishni yuboradi.
    prev['image_id'] mavjud bo'lsa — qayta yuklamasdan ishlatadi."""
    caption = prev['caption']
    pm = prev.get('parse_mode')
    buy_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Sotib olish", url=prev['deep_link'])]])
    # 1) Aynan reklama ko'rinishi
    try:
        if prev.get('image_id'):
            await context.bot.send_photo(chat_id=chat_id, photo=prev['image_id'],
                                         caption=caption, parse_mode=pm, reply_markup=buy_kb)
        elif prev.get('image_bytes'):
            await context.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(prev['image_bytes']),
                                         caption=caption, parse_mode=pm, reply_markup=buy_kb)
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption,
                                           parse_mode=pm, reply_markup=buy_kb)
    except Exception as e:
        logging.warning(f"Preview render xatosi: {e}")
        await context.bot.send_message(chat_id=chat_id, text=caption)
    # 2) Boshqaruv paneli
    await context.bot.send_message(chat_id=chat_id, text=t(lang, 'ad_preview_question'),
                                   reply_markup=_ad_preview_control_kb(lang))


async def show_ad_preview(update, context, product_id):
    """Mahsulot saqlangandan keyin — kanalga joylashdan OLDIN reklama ko'rinishini
    sotuvchiga ko'rsatadi (dizayn rasm + reklama matni)."""
    lang = get_lang(update, context)
    chat_id = update.effective_chat.id
    product = db.get_product_by_id(product_id)
    if not product:
        return
    await context.bot.send_message(chat_id=chat_id, text=t(lang, 'ad_preview_preparing'))

    caption, pm = await _build_ad_caption(product)
    designed = await _build_ad_design_bytes(context, product)
    photo = product.get('image_url')
    bot_me = await context.bot.get_me()
    deep_link = f"https://t.me/{bot_me.username}?start=product_{product_id}"
    buy_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Sotib olish", url=deep_link)]])

    # 1) Aynan reklama ko'rinishini yuboramiz va (rasmli bo'lsa) file_id ni eslab qolamiz
    image_id = None
    try:
        if designed is not None:
            sent = await context.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(designed),
                                                caption=caption, parse_mode=pm, reply_markup=buy_kb)
            try:
                image_id = sent.photo[-1].file_id
            except Exception:
                image_id = None
        elif photo:
            sent = await context.bot.send_photo(chat_id=chat_id, photo=photo,
                                                caption=caption, parse_mode=pm, reply_markup=buy_kb)
            try:
                image_id = sent.photo[-1].file_id
            except Exception:
                image_id = None
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption,
                                           parse_mode=pm, reply_markup=buy_kb)
    except Exception as e:
        logging.warning(f"Preview yuborish xatosi: {e}")
        await context.bot.send_message(chat_id=chat_id, text=caption)

    context.user_data['ad_preview'] = {
        'product_id': product_id, 'caption': caption, 'parse_mode': pm,
        'image_id': image_id, 'deep_link': deep_link,
    }
    context.user_data.pop('ad_editing_caption', None)

    # 2) Boshqaruv paneli
    await context.bot.send_message(chat_id=chat_id, text=t(lang, 'ad_preview_question'),
                                   reply_markup=_ad_preview_control_kb(lang))


async def ad_preview_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«✅ Kanalga joylash» — preview da ko'rsatilgan AYNAN reklamani joylaydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    prev = context.user_data.get('ad_preview')
    if not prev:
        await query.answer(t(lang, 'ad_preview_expired'), show_alert=True)
        return
    await query.answer()
    try:
        await query.edit_message_text(t(lang, 'ad_publishing'))
    except Exception:
        pass
    await post_product_to_channel(
        context, prev['product_id'],
        caption_override=prev['caption'], parse_mode_override=prev.get('parse_mode'),
        image_override=prev.get('image_id'),
    )
    context.user_data.pop('ad_preview', None)
    context.user_data.pop('ad_editing_caption', None)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="seller_panel")]])
    try:
        await query.edit_message_text(t(lang, 'ad_published'), reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=t(lang, 'ad_published'), reply_markup=kb)


async def ad_preview_regen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«🔄 Boshqa variant» — AI yangi reklama matni yozadi, dizayn rasm o'zgarmaydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    prev = context.user_data.get('ad_preview')
    if not prev:
        await query.answer(t(lang, 'ad_preview_expired'), show_alert=True)
        return
    await query.answer()
    try:
        await query.edit_message_text(t(lang, 'ad_preview_preparing'))
    except Exception:
        pass
    product = db.get_product_by_id(prev['product_id'])
    if product:
        caption, pm = await _build_ad_caption(product)
        prev['caption'], prev['parse_mode'] = caption, pm
        context.user_data['ad_preview'] = prev
    await _render_ad_preview(context, update.effective_chat.id, lang, prev)


async def ad_preview_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«✏️ Matnni tahrirlash» — sotuvchidan o'z reklama matnini so'raydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    prev = context.user_data.get('ad_preview')
    if not prev:
        await query.answer(t(lang, 'ad_preview_expired'), show_alert=True)
        return
    await query.answer()
    context.user_data['ad_editing_caption'] = True
    try:
        await query.edit_message_text(t(lang, 'ad_edit_prompt'))
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t(lang, 'ad_edit_prompt'))


async def ad_preview_caption_input(update, context):
    """Sotuvchi tahrirlangan reklama matnini yubordi — preview ni yangilaymiz."""
    lang = get_lang(update, context)
    prev = context.user_data.get('ad_preview')
    context.user_data.pop('ad_editing_caption', None)
    if not prev:
        await update.message.reply_text(t(lang, 'ad_preview_expired'))
        return
    new_text = (update.message.text or '').strip()
    if new_text:
        prev['caption'] = new_text
        prev['parse_mode'] = None   # sotuvchi matni — oddiy matn
        context.user_data['ad_preview'] = prev
    await _render_ad_preview(context, update.effective_chat.id, lang, prev)


async def ad_preview_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«⏭ Hozircha joylamayman» — mahsulot saqlangan, kanalga chiqarilmaydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    context.user_data.pop('ad_preview', None)
    context.user_data.pop('ad_editing_caption', None)
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_home'), callback_data="seller_panel")]])
    try:
        await query.edit_message_text(t(lang, 'ad_skipped'), reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=t(lang, 'ad_skipped'), reply_markup=kb)


async def _maybe_preview_on_reactivation(update, context, product_id, was_active):
    """Mahsulot zahiradan (reserve) sotuvga (active) qaytgan bo'lsa — reklama
    ko'rinishini ko'rsatadi. True qaytaradi (preview ko'rsatildi)."""
    if was_active:
        return False   # avval ham sotuvda edi — qayta reklama shart emas
    prod = db.get_product_by_id(product_id)
    if prod and (prod.get('status') == 'active'):
        await show_ad_preview(update, context, product_id)
        return True
    return False


async def _save_product(update, context):
    """Mahsulotni DB ga saqlaydi."""
    user = db.get_user_by_telegram_id(update.effective_user.id)
    photos = [p for p in context.user_data.get('product_photos', []) if p][:db.MAX_PRODUCT_IMAGES]
    product_id = db.create_product(
        seller_id=user['id'],
        name=context.user_data['product_name'],
        price=context.user_data['product_price'],
        category_id=context.user_data.get('product_category'),
        description=context.user_data.get('product_desc'),
        image_url=(photos[0] if photos else None),
    )

    # Barcha rasmlarni saqlaymiz (image_url ham birinchi rasmga sinxronlanadi)
    if photos and product_id:
        db.set_product_images(product_id, photos)

    # Atributlarni saqlash
    attrs = context.user_data.pop('product_attrs', {})
    if attrs and product_id:
        db.save_product_attributes(product_id, attrs)

    # State tozalash
    for k in ('product_name', 'product_price', 'product_category',
              'product_desc', 'product_photo', 'product_photos', 'attr_templates',
              'attr_index', 'adding_product'):
        context.user_data.pop(k, None)

    lang = get_lang(update, context)
    msg = t(lang, 'product_saved')
    if photos:
        msg += t(lang, 'frag_photos_saved', n=len(photos))
    if attrs:
        msg += t(lang, 'frag_attrs_saved', n=len(attrs))

    if update.message:
        await update.message.reply_text(msg)
    else:
        await update.callback_query.message.reply_text(msg)

    # Kanalga joylashdan OLDIN — reklama ko'rinishini ko'rsatamiz (tasdiq/tahrir)
    if product_id:
        await show_ad_preview(update, context, product_id)

    return ConversationHandler.END


async def seller_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulotlarim — 3 bo'lim: sotuvda / zahirada / o'chirilgan + qidiruv."""
    query = update.callback_query
    if query:
        await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    counts = db.count_seller_products_by_status(user['id'])

    text = t(lang, 'my_products_overview',
             active=counts['active'], reserve=counts['reserve'], deleted=counts['deleted'])

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_on_sale_n', n=counts['active']), callback_data="sp_list_active_0")],
        [InlineKeyboardButton(t(lang, 'btn_reserve_n', n=counts['reserve']), callback_data="sp_list_reserve_0")],
        [InlineKeyboardButton(t(lang, 'btn_deleted_n', n=counts['deleted']), callback_data="sp_list_deleted_0")],
        [InlineKeyboardButton(t(lang, 'btn_search_product'), callback_data="sp_search")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")],
    ]

    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


SP_PAGE = 8  # sahifadagi mahsulotlar soni

async def seller_products_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status bo'yicha mahsulotlar ro'yxati (paginatsiya bilan)."""
    query = update.callback_query
    await query.answer()

    # callback: sp_list_{status}_{page}
    parts = query.data.split("_")
    status = parts[2]
    page = int(parts[3])

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    products = db.get_seller_products_by_status(user['id'], status=status)

    status_labels = {'active': t(lang, 'status_on_sale'), 'reserve': t(lang, 'status_reserve_short'),
                     'deleted': t(lang, 'status_deleted_short')}

    if not products:
        await query.edit_message_text(
            t(lang, 'section_empty', status=status_labels.get(status)),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="seller_products")]])
        )
        return

    total = len(products)
    total_pages = max(1, (total + SP_PAGE - 1) // SP_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SP_PAGE
    end = min(start + SP_PAGE, total)

    keyboard = []
    for p in products[start:end]:
        stock_info = ""
        if p.get('stock_count') is not None:
            stock_info = t(lang, 'frag_stock_pieces', n=p['stock_count'])
        keyboard.append([InlineKeyboardButton(
            f"{p['name']} — {fmt_price(p['price'])}{stock_info}",
            callback_data=f"prod_menu_{p['id']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"sp_list_{status}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"sp_list_{status}_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_products")])

    await query.edit_message_text(
        t(lang, 'section_page', status=status_labels.get(status), total=total, page=page+1, pages=total_pages),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def seller_product_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot qidirish — so'rov so'raydi."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        T(update, context, 'seller_search_prompt'),
        parse_mode='HTML'
    )
    return SELLER_PRODUCT_SEARCH


async def seller_product_search_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qidiruv natijasini ko'rsatadi."""
    lang = get_lang(update, context)
    search_text = update.message.text.strip()
    user = db.get_user_by_telegram_id(update.effective_user.id)
    products = db.search_seller_products(user['id'], search_text)

    if not products:
        await update.message.reply_text(
            t(lang, 'seller_search_none', q=search_text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_my_products_back'), callback_data="seller_products")]])
        )
        return ConversationHandler.END

    status_emoji = {'active': '✅', 'reserve': '📥', 'deleted': '🗑'}
    keyboard = []
    for p in products[:20]:
        st = p.get('status') or 'active'
        emoji = status_emoji.get(st, '')
        stock_info = t(lang, 'frag_stock_pieces', n=p['stock_count']) if p.get('stock_count') is not None else ""
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {p['name']} — {fmt_price(p['price'])}{stock_info}",
            callback_data=f"prod_menu_{p['id']}"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_my_products_back'), callback_data="seller_products")])

    await update.message.reply_text(
        t(lang, 'seller_search_found', q=search_text, n=len(products)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def seller_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int = None):
    query = update.callback_query
    # Agar to'g'ridan-to'g'ri callback dan kelsa — javob beramiz; ichki chaqiriqda esa o'tkazib yuboramiz
    if product_id is None:
        await query.answer()
        product_id = int(query.data.split("_")[2])
    context.user_data['editing_product_id'] = product_id
    lang = get_lang(update, context)

    product = db.get_product_basic(product_id)

    if not product:
        await query.edit_message_text(t(lang, 'product_not_found'))
        return

    status = product.get('status') or 'active'
    status_labels = {
        'active':  t(lang, 'pm_status_active'),
        'reserve': t(lang, 'pm_status_reserve'),
        'deleted': t(lang, 'pm_status_deleted'),
    }
    status_text = status_labels.get(status, status)

    # Statusga qarab tugmalar
    keyboard = [[InlineKeyboardButton(t(lang, 'btn_edit'), callback_data=f"edit_start_{product_id}")]]
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_share_link'), callback_data=f"share_link_{product_id}")])

    if status == 'active':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_to_reserve'), callback_data=f"pstatus_reserve_{product_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_set_stock'), callback_data=f"set_stock_{product_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_remove_from_sale'), callback_data=f"pstatus_deleted_{product_id}")])
    elif status == 'reserve':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_return_to_sale'), callback_data=f"pstatus_active_{product_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_set_stock'), callback_data=f"set_stock_{product_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_remove_from_sale'), callback_data=f"pstatus_deleted_{product_id}")])
    else:  # deleted
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_repost_sale'), callback_data=f"pstatus_active_{product_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_delete_forever'), callback_data=f"delete_prod_{product_id}")])

    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_products")])

    # HTML rejimi + foydalanuvchi matnini escape
    name = html.escape(product['name'] or '')
    desc = html.escape(product.get('description') or t(lang, 'none_word'))
    if product.get('stock_count') is not None:
        stock_line = t(lang, 'pm_stock_line', n=product['stock_count'])
    else:
        stock_line = t(lang, 'pm_stock_unlimited')

    # Atributlar
    attrs = db.get_product_attributes(product_id)
    attrs_text = ""
    if attrs:
        lines = [f"• {a.get('attr_label') or a['attr_key']}: {a['attr_value']}" for a in attrs]
        attrs_text = t(lang, 'pm_attrs_title') + "\n".join(lines)

    body = t(lang, 'product_menu_body',
             name=name, price=fmt_price(product['price']),
             status=status_text, stock=stock_line, desc=desc, attrs=attrs_text)

    # Sotuvchi mahsulotining rasm(lar)ini ham ko'rsatamiz — shunda rasm
    # saqlangani-saqlanmaganini o'z ko'zi bilan tekshira oladi.
    images = db.get_product_images(product_id)
    if images:
        try:
            await query.message.delete()
        except Exception:
            pass
        await _send_product_card(context, update.effective_chat.id, images, body,
                                 keyboard)
    else:
        await query.edit_message_text(
            body, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )


async def change_product_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot statusini o'zgartiradi: active/reserve/deleted."""
    query = update.callback_query
    await query.answer()

    # callback: pstatus_{status}_{product_id}
    parts = query.data.split("_")
    new_status = parts[1]
    product_id = int(parts[2])

    db.set_product_status(product_id, new_status)

    lang = get_lang(update, context)

    # Qayta sotuvga qo'yilganda — kanalga to'g'ridan chiqarmaymiz, avval reklama
    # ko'rinishini ko'rsatamiz (sotuvchi tasdiqlasa/tahrirlasa, keyin joylanadi).
    if new_status == 'active':
        await query.answer(t(lang, 'pstatus_active_toast'), show_alert=True)
        await seller_product_menu(update, context, product_id=product_id)
        await show_ad_preview(update, context, product_id)
        return

    labels = {
        'reserve': t(lang, 'pstatus_reserve_toast'),
        'deleted': t(lang, 'pstatus_deleted_toast'),
    }
    await query.answer(labels.get(new_status, t(lang, 'status_changed_toast')), show_alert=True)

    # Menyuni yangilaymiz
    await seller_product_menu(update, context, product_id=product_id)


async def toggle_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])

    db.toggle_product_in_stock(product_id)

    # query.data ni o'zgartirmaymiz (PTB v22'da CallbackQuery muzlatilgan).
    # Buning o'rniga product_id'ni to'g'ridan-to'g'ri uzatamiz.
    await seller_product_menu(update, context, product_id=product_id)


async def set_stock_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi zahira sonini belgilamoqchi."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])
    context.user_data['setting_stock_for'] = product_id

    await query.edit_message_text(T(update, context, 'set_stock_ask'))


async def set_stock_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """text_handler tomonidan chaqiriladi — setting_stock_for bo'lsa."""
    product_id = context.user_data.pop('setting_stock_for', None)
    if not product_id:
        return False  # bizning rejimimiz emas

    lang = get_lang(update, context)
    text = update.message.text.strip()
    if text == '-':
        new_stock = None
    else:
        try:
            new_stock = int(text)
            if new_stock < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(t(lang, 'stock_invalid'))
            return True

    # Zahira to'ldirishdan oldingi holatni eslab qolamiz (reserve→active aniqlash uchun)
    before = db.get_product_by_id(product_id)
    was_active = bool(before and before.get('status') == 'active')

    db.set_product_stock_count(product_id, new_stock)

    if new_stock is None:
        await update.message.reply_text(t(lang, 'stock_set_unlimited'))
    else:
        await update.message.reply_text(t(lang, 'stock_set_n', n=new_stock))

    # Zahiradan sotuvga qaytgan bo'lsa — reklama ko'rinishini ko'rsatamiz,
    # aks holda oddiy holatda sotuvchi paneliga qaytamiz.
    if not await _maybe_preview_on_reactivation(update, context, product_id, was_active):
        await seller_panel(update, context)
    return True


async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    lang = get_lang(update, context)
    if data.startswith("delete_prod_") and not data.startswith("delete_confirm_"):
        product_id = int(data.split("_")[2])
        keyboard = [
            [InlineKeyboardButton(t(lang, 'btn_yes_delete'), callback_data=f"delete_confirm_{product_id}")],
            [InlineKeyboardButton(t(lang, 'btn_no_cancel'), callback_data=f"prod_menu_{product_id}")],
        ]
        await query.edit_message_text(
            t(lang, 'delete_confirm_ask'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    product_id = int(data.split("_")[2])
    hard_deleted = db.delete_product(product_id)

    msg = t(lang, 'product_deleted') if hard_deleted else t(lang, 'product_deleted_kept_history')
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_my_products_back'), callback_data="seller_products")]])
    )


# ============================================================
# MAHSULOTNI TAHRIRLASH — "bir oyna + qaysi qismni tanlash"
# Sotuvchi ma'lumotlarning hammasini bir oynada ko'radi va
# faqat o'zgartirmoqchi bo'lgan qismini tanlab tahrirlaydi.
# ============================================================

def _edit_field_kb(product_id, attrs, lang=DEFAULT_LANG):
    """Tahrir oynasidagi tugmalar — har bir maydon va xususiyat uchun alohida."""
    rows = [
        [InlineKeyboardButton(t(lang, 'ef_btn_name'), callback_data=f"ef_name_{product_id}")],
        [InlineKeyboardButton(t(lang, 'ef_btn_price'), callback_data=f"ef_price_{product_id}")],
        [InlineKeyboardButton(t(lang, 'ef_btn_cat'), callback_data=f"ef_cat_{product_id}")],
        [InlineKeyboardButton(t(lang, 'ef_btn_desc'), callback_data=f"ef_desc_{product_id}")],
        [InlineKeyboardButton(t(lang, 'ef_btn_photos'), callback_data=f"ef_photos_{product_id}")],
    ]
    for a in attrs:
        label = a.get('attr_label') or a['attr_key']
        rows.append([InlineKeyboardButton(
            f"🏷 {label}", callback_data=f"ea_{product_id}_{a['attr_key']}"
        )])
    rows.append([InlineKeyboardButton(t(lang, 'back'), callback_data=f"prod_menu_{product_id}")])
    return InlineKeyboardMarkup(rows)


def _edit_overview_text(product, attrs, img_count, lang=DEFAULT_LANG):
    """Mahsulotning barcha ma'lumotini bitta oynada ko'rsatuvchi matn."""
    name = html.escape(product.get('name') or '—')
    desc = html.escape(product.get('description') or t(lang, 'none_word'))
    cat = html.escape(category_name(product.get('category_name'), lang) or t(lang, 'category_not_selected'))
    lines = [
        t(lang, 'edit_title'),
        "",
        t(lang, 'edit_lbl_name', v=name),
        t(lang, 'edit_lbl_price', v=fmt_price(product.get('price') or 0)),
        t(lang, 'edit_lbl_cat', v=cat),
        t(lang, 'edit_lbl_photos', n=img_count),
        t(lang, 'edit_lbl_desc', v=desc),
    ]
    if attrs:
        lines.append("")
        lines.append(t(lang, 'edit_attrs_title'))
        for a in attrs:
            label = html.escape(a.get('attr_label') or a['attr_key'])
            val = html.escape(a.get('attr_value') or '—')
            lines.append(f"• {label}: {val}")
    lines.append("")
    lines.append(t(lang, 'edit_which_part'))
    return "\n".join(lines)


async def edit_product_hub(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int = None):
    """Tahrir oynasi — hamma ma'lumot bir joyda, har biriga alohida tugma."""
    query = update.callback_query
    if product_id is None:
        if query and query.data and query.data.startswith("edit_start_"):
            product_id = int(query.data.split("_")[2])
        else:
            product_id = context.user_data.get('editing_product_id')
    lang = get_lang(update, context)
    if not product_id:
        if query:
            await query.answer(t(lang, 'product_not_found'), show_alert=True)
        return
    context.user_data['editing_product_id'] = product_id

    product = db.get_product_by_id(product_id)
    if not product:
        if query:
            await query.edit_message_text(t(lang, 'product_not_found'))
        else:
            await update.message.reply_text(t(lang, 'product_not_found'))
        return

    attrs = db.get_product_attributes(product_id)
    img_count = db.count_product_images(product_id)
    text = _edit_overview_text(product, attrs, img_count, lang)
    kb = _edit_field_kb(product_id, attrs, lang)

    if query:
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
        except Exception:
            # Oldingi xabar rasm bo'lsa edit ishlamaydi — yangi xabar yuboramiz
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text,
                reply_markup=kb, parse_mode='HTML'
            )
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')


def _pid_from_cb(query):
    """ef_name_5 / ef_price_5 / ef_cat_5 / ef_desc_5 / ef_photos_5 → 5"""
    return int(query.data.split("_")[2])


# ---------- NOM ----------
async def edit_field_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing_product_id'] = _pid_from_cb(query)
    await query.edit_message_text(T(update, context, 'edit_name_ask'))
    return EDIT_FIELD_NAME


async def edit_field_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    pid = context.user_data.get('editing_product_id')
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text(t(lang, 'edit_name_short'))
        return EDIT_FIELD_NAME
    if len(name) > 100:
        await update.message.reply_text(t(lang, 'edit_name_long'))
        return EDIT_FIELD_NAME
    db.update_product_fields(pid, name=name)
    await update.message.reply_text(t(lang, 'name_updated'))
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


# ---------- NARX ----------
async def edit_field_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing_product_id'] = _pid_from_cb(query)
    await query.edit_message_text(T(update, context, 'edit_price_ask'))
    return EDIT_FIELD_PRICE


async def edit_field_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get('editing_product_id')
    raw = update.message.text.replace(" ", "").replace(",", "").replace("\u00A0", "")
    lang = get_lang(update, context)
    try:
        price = float(raw)
    except ValueError:
        await update.message.reply_text(t(lang, 'edit_price_invalid'))
        return EDIT_FIELD_PRICE
    if price <= 0 or price > 1_000_000_000:
        await update.message.reply_text(t(lang, 'edit_price_range'))
        return EDIT_FIELD_PRICE
    db.update_product_fields(pid, price=price)
    await update.message.reply_text(t(lang, 'price_updated'))
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


# ---------- KATEGORIYA ----------
async def edit_field_cat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = _pid_from_cb(query)
    context.user_data['editing_product_id'] = pid
    categories = db.get_all_categories()
    lang = get_lang(update, context)
    kb = [[InlineKeyboardButton(f"{cat[2]} {category_name(cat[1], lang)}", callback_data=f"ecat_{cat[0]}")] for cat in categories]
    kb.append([InlineKeyboardButton(t(lang, 'btn_cancel_edit'), callback_data="ecat_cancel")])
    await query.edit_message_text(t(lang, 'edit_cat_ask'), reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_FIELD_CATEGORY


async def edit_field_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = context.user_data.get('editing_product_id')
    if query.data != "ecat_cancel":
        cat_id = int(query.data.split("_")[1])
        db.update_product_fields(pid, category_id=cat_id)
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


# ---------- TAVSIF ----------
async def edit_field_desc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['editing_product_id'] = _pid_from_cb(query)
    await query.edit_message_text(T(update, context, 'edit_desc_ask'))
    return EDIT_FIELD_DESC


async def edit_field_desc_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    pid = context.user_data.get('editing_product_id')
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    elif len(desc) > 500:
        await update.message.reply_text(t(lang, 'edit_desc_long'))
        return EDIT_FIELD_DESC
    db.update_product_fields(pid, description=desc)
    await update.message.reply_text(t(lang, 'desc_updated'))
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


# ---------- RASMLAR (barchasini almashtirish, 4 tagacha) ----------
async def edit_field_photos_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = _pid_from_cb(query)
    context.user_data['editing_product_id'] = pid
    context.user_data['edit_photos'] = []
    await query.edit_message_text(T(update, context, 'edit_photos_ask'))
    return EDIT_FIELD_PHOTOS


async def edit_field_photos_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    pid = context.user_data.get('editing_product_id')
    file_id = None
    if update.message.photo:
        photo = update.message.photo[-1]
        if photo.file_size and photo.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'edit_photo_too_big'))
            return EDIT_FIELD_PHOTOS
        if photo.width and photo.height and (photo.width < 200 or photo.height < 200):
            await update.message.reply_text(t(lang, 'edit_photo_too_small'))
            return EDIT_FIELD_PHOTOS
        file_id = photo.file_id
    elif update.message.document and (update.message.document.mime_type or '').startswith('image/'):
        doc = update.message.document
        if doc.file_size and doc.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'edit_photo_too_big'))
            return EDIT_FIELD_PHOTOS
        file_id = doc.file_id
    elif update.message.text and update.message.text.strip() == "-":
        db.set_product_images(pid, [])
        context.user_data.pop('edit_photos', None)
        await update.message.reply_text(t(lang, 'all_photos_deleted'))
        await edit_product_hub(update, context, product_id=pid)
        return ConversationHandler.END
    else:
        await update.message.reply_text(t(lang, 'edit_photo_send_or_dash'))
        return EDIT_FIELD_PHOTOS

    photos = context.user_data.setdefault('edit_photos', [])
    photos.append(file_id)
    n = len(photos)
    if n >= db.MAX_PRODUCT_IMAGES:
        db.set_product_images(pid, photos)
        context.user_data.pop('edit_photos', None)
        await update.message.reply_text(t(lang, 'photos_saved_max', n=n))
        await edit_product_hub(update, context, product_id=pid)
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_add_more_photo'), callback_data="eph_more")],
        [InlineKeyboardButton(t(lang, 'btn_save'), callback_data="eph_done")],
    ])
    await update.message.reply_text(
        t(lang, 'photos_selected_n', n=n, max=db.MAX_PRODUCT_IMAGES),
        reply_markup=kb
    )
    return EDIT_FIELD_PHOTOS


async def edit_photos_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('edit_photos', []))
    await query.edit_message_text(T(update, context, 'next_photo_edit', n=n, max=db.MAX_PRODUCT_IMAGES))
    return EDIT_FIELD_PHOTOS


async def edit_photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = context.user_data.get('editing_product_id')
    photos = context.user_data.pop('edit_photos', [])
    if photos:
        db.set_product_images(pid, photos)
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


# ---------- XUSUSIYAT (atribut) ----------
async def edit_attr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # ea_{pid}_{attr_key}  (attr_key ichida '_' bo'lishi mumkin)
    parts = query.data.split("_", 2)
    pid = int(parts[1])
    attr_key = parts[2]
    context.user_data['editing_product_id'] = pid
    context.user_data['editing_attr_key'] = attr_key
    label = attr_key
    for a in db.get_product_attributes(pid):
        if a['attr_key'] == attr_key:
            label = a.get('attr_label') or attr_key
            break
    await query.edit_message_text(
        T(update, context, 'edit_attr_ask', label=html.escape(label)),
        parse_mode='HTML'
    )
    return EDIT_FIELD_ATTR


async def edit_attr_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    pid = context.user_data.get('editing_product_id')
    attr_key = context.user_data.get('editing_attr_key')
    if not pid or not attr_key:
        await update.message.reply_text(t(lang, 'edit_proc_error'))
        return ConversationHandler.END
    value = update.message.text.strip()
    if value != "-" and len(value) > 100:
        await update.message.reply_text(t(lang, 'attr_too_long'))
        return EDIT_FIELD_ATTR
    context.user_data.pop('editing_attr_key', None)
    if value == "-":
        db.delete_product_attribute(pid, attr_key)
        await update.message.reply_text(t(lang, 'attr_deleted'))
    else:
        db.save_product_attributes(pid, {attr_key: value})
        await update.message.reply_text(t(lang, 'attr_updated'))
    await edit_product_hub(update, context, product_id=pid)
    return ConversationHandler.END


async def seller_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    # Callback (inline) yoki Reply tugma (matn) — ikkalasida ham ishlasin
    async def _show(text, **kw):
        if query:
            await query.edit_message_text(text, **kw)
        else:
            await update.message.reply_text(text, **kw)

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_seller(user['id'])

    if not orders:
        await _show(
            t(lang, 'orders_empty'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}

    # Savat buyurtmalarini guruhlash
    group_agg = {}
    for o in orders:
        gid = o.get('order_group_id')
        if gid:
            g = group_agg.setdefault(gid, {'count': 0, 'sum': 0.0, 'status': o['status'],
                                           'buyer': o.get('buyer_name') or ''})
            g['count'] += 1
            g['sum'] += float(o['total_price'] or 0)

    keyboard = []
    seen_groups = set()
    shown = 0
    for order in orders:
        if shown >= 10:
            break
        gid = order.get('order_group_id')
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
            g = group_agg[gid]
            keyboard.append([InlineKeyboardButton(
                t(lang, 'seller_order_group_row', emoji=status_emoji.get(g['status'], '❓'),
                  buyer=g['buyer'], count=g['count'], sum=fmt_price(g['sum'])),
                callback_data=f"seller_gorder_{gid}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                t(lang, 'seller_order_row', emoji=status_emoji.get(order['status'], '❓'),
                  buyer=order['buyer_name'], total=fmt_price(order['total_price'])),
                callback_data=f"seller_order_{order['id']}"
            )])
        shown += 1
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")])

    await _show(t(lang, 'orders_title'), reply_markup=InlineKeyboardMarkup(keyboard))


async def seller_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    avg_rating = db.get_seller_avg_rating(user['id'])
    lang = get_lang(update, context)

    # Karta holati
    card_info = ""
    if user.get('card_number'):
        cnum = user['card_number']
        masked = f"{cnum[:4]} **** **** {cnum[-4:]}" if len(cnum) >= 8 else cnum
        ctype = CARD_TYPE_LABELS.get(user.get('card_type', ''), '💳')
        card_info = f"\n{ctype} {masked} ({user.get('card_owner', '')})"
    else:
        card_info = t(lang, 'card_not_added')

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_edit_shop_name'),    callback_data="edit_shop_name")],
        [InlineKeyboardButton(t(lang, 'btn_edit_address'),       callback_data="edit_shop_address")],
        [InlineKeyboardButton(t(lang, 'btn_edit_landmark'),      callback_data="edit_shop_landmark")],
        [InlineKeyboardButton(t(lang, 'btn_select_region'),      callback_data="edit_seller_region")],
        [InlineKeyboardButton(t(lang, 'btn_edit_working_days'),  callback_data="edit_working_days")],
        [InlineKeyboardButton(t(lang, 'btn_edit_working_hours'), callback_data="edit_working_hours")],
        [InlineKeyboardButton(t(lang, 'btn_edit_telegram'),      callback_data="edit_telegram")],
        [InlineKeyboardButton(t(lang, 'btn_card_info'),          callback_data="edit_card_info")],
        [InlineKeyboardButton(t(lang, 'btn_change_language'),    callback_data="change_lang")],
        [InlineKeyboardButton(t(lang, 'back'),                   callback_data="seller_panel")],
    ]

    # Hudud
    region_info = ""
    if user.get('region_id'):
        r = db.get_region_by_id(user['region_id'])
        if r:
            if r.get('parent_id'):
                parent = db.get_region_by_id(r['parent_id'])
                region_info = (f"{region_name(parent['name'], lang)} → {region_name(r['name'], lang)}"
                               if parent else region_name(r['name'], lang))
            else:
                region_info = region_name(r['name'], lang)
        else:
            region_info = t(lang, 'unknown_word')
    else:
        region_info = t(lang, 'region_not_set')

    YOQ = t(lang, 'not_specified')
    text = t(lang, 'seller_profile_body',
             shop=user.get('shop_name') or YOQ,
             address=user.get('shop_address') or YOQ,
             landmark=user.get('shop_landmark') or YOQ,
             region=region_info,
             wd=user.get('working_days') or YOQ,
             wh=user.get('working_hours') or YOQ,
             tg=user.get('telegram_username') or YOQ,
             phone=user.get('phone_number') or YOQ,
             card=card_info, rating=f"{avg_rating:.1f}",
             date=fmt_datetime(user['created_at']))

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def product_ask_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor sotuvchiga buyurtmasiz savol yubora oladi."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])
    lang = get_lang(update, context)
    product = db.get_product_basic(product_id)

    if not product:
        await query.answer(t(lang, 'product_not_found'), show_alert=True)
        return

    seller = db.get_user_by_id(product['seller_id'])
    if not seller or not seller.get('telegram_id'):
        await query.answer(t(lang, 'contact_seller_unavailable'), show_alert=True)
        return

    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if buyer and buyer['id'] == product['seller_id']:
        await query.answer(t(lang, 'this_is_your_product'), show_alert=True)
        return

    # Xaridorga sotuvchi ma'lumotlarini ko'rsatamiz
    seller_phone = seller.get('phone_number') or '—'
    seller_tg = seller.get('telegram_username')
    seller_tg_text = f"@{seller_tg}" if seller_tg else t(lang, 'tg_not_shown')
    shop_name = html.escape(seller.get('shop_name') or seller.get('name') or t(lang, 'seller_word'))

    contact_text = t(lang, 'contact_seller_text',
                     shop=shop_name, phone=seller_phone, tg=seller_tg_text,
                     pname=html.escape(product.get('name') or ''))

    kb = []
    if seller_tg:
        kb.append([InlineKeyboardButton(
            t(lang, 'btn_write_telegram'),
            url=f"https://t.me/{seller_tg.replace('@', '')}"
        )])
    kb.append([InlineKeyboardButton(
        t(lang, 'btn_order'),
        callback_data=f"order_{product_id}"
    )])
    kb.append([InlineKeyboardButton(t(lang, 'back'), callback_data=f"prod_{product_id}")])

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=contact_text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='HTML'
    )

    # Sotuvchiga ham xabar — kim qiziqdi (sotuvchi tilida)
    try:
        slang = get_user_lang(seller)
        buyer_tg = f"@{buyer['telegram_username']}" if buyer and buyer.get('telegram_username') and buyer.get('telegram_username', '').startswith(('@', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', 'A')) else "—"
        buyer_phone = buyer.get('phone_number') or '—' if buyer else '—'
        buyer_name = html.escape(buyer.get('name') or t(slang, 'anonymous')) if buyer else t(slang, 'anonymous')
        await context.bot.send_message(
            chat_id=seller['telegram_id'],
            text=t(slang, 'seller_interest_notify',
                   pname=html.escape(product.get('name') or ''),
                   buyer=buyer_name, phone=buyer_phone, tg=buyer_tg),
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"product_ask_seller sotuvchi xabari: {e}")


async def contact_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi admin bilan bog'lanmoqchi."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        T(update, context, 'contact_admin_prompt'),
        parse_mode='HTML'
    )
    return CONTACT_ADMIN_MSG


async def contact_admin_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi xabarini adminga yuboradi."""
    user = db.get_user_by_telegram_id(update.effective_user.id)
    text = update.message.text.strip()

    role = user.get('role', 'buyer') if user else 'buyer'
    role_label = {'buyer': '🛒 Xaridor', 'seller': '🏪 Sotuvchi', 'admin': '🔧 Admin'}.get(role, role)
    name = html.escape(user.get('name') or 'Anonim') if user else 'Anonim'
    phone = user.get('phone_number') or '—' if user else '—'
    tg_id = update.effective_user.id

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📨 <b>Foydalanuvchidan xabar</b>\n\n"
                f"{role_label}: {name}\n"
                f"📞 {phone}\n"
                f"🆔 Telegram ID: <code>{tg_id}</code>\n\n"
                f"💬 Xabar:\n{html.escape(text)}\n\n"
                f"<i>Javob berish uchun: /reply {tg_id} [matn]</i>"
            ),
            parse_mode='HTML'
        )
        await update.message.reply_text(T(update, context, 'contact_admin_sent'))
    except Exception as e:
        logging.error(f"contact_admin_send xatosi: {e}")
        await update.message.reply_text(T(update, context, 'admin_msg_failed'))

    # Panelga qaytamiz
    if update.effective_user:
        u = db.get_user_by_telegram_id(update.effective_user.id)
        if u:
            if get_active_mode(u, context) == 'seller':
                await seller_panel(update, context)
            else:
                await buyer_panel(update, context)
    return ConversationHandler.END


async def admin_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reply {user_id} {matn} — admin foydalanuvchiga javob beradi."""
    if update.effective_user.id != ADMIN_ID:
        return

    lang = get_lang(update, context)
    args = context.args  # [user_id, ...matn...]
    if not args or len(args) < 2:
        await update.message.reply_text(t(lang, 'admin_reply_usage'))
        return

    try:
        user_id = int(args[0])
        reply_text = ' '.join(args[1:])
        target = db.get_user_by_id(user_id)  # ehtimol topilmaydi (telegram_id bo'lishi mumkin)
        tlang = get_user_lang(target) if target else DEFAULT_LANG
        await context.bot.send_message(
            chat_id=user_id,
            text=t(tlang, 'admin_reply_prefix', text=html.escape(reply_text)),
            parse_mode='HTML'
        )
        await update.message.reply_text(t(lang, 'admin_reply_sent', uid=user_id))
    except ValueError:
        await update.message.reply_text(t(lang, 'admin_reply_format'))
    except Exception as e:
        await update.message.reply_text(t(lang, 'error_generic', e=e))


async def edit_seller_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi o'z hududini tanlaydi."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    regions = db.get_regions(parent_id=None)
    kb = []
    for r in regions:
        kb.append([InlineKeyboardButton(region_name(r['name'], lang), callback_data=f"sregset_{r['id']}")])
    kb.append([InlineKeyboardButton(t(lang, 'btn_cancel_edit'), callback_data="seller_profile")])

    await query.edit_message_text(
        t(lang, 'seller_region_ask'),
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def seller_region_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Viloyat tanlandi — tuman bor bo'lsa ko'rsatamiz, yo'q bo'lsa saqlaymiz."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    region_id = int(query.data.split("_")[1])
    districts = db.get_regions(parent_id=region_id)

    if districts:
        # Tuman tanlash
        kb = []
        for d in districts:
            kb.append([InlineKeyboardButton(region_name(d['name'], lang), callback_data=f"sregdist_{d['id']}")])
        region = db.get_region_by_id(region_id)
        kb.append([InlineKeyboardButton(
            t(lang, 'btn_whole_region', name=region_name(region['name'], lang)), callback_data=f"sregdist_0_{region_id}"
        )])
        kb.append([InlineKeyboardButton(t(lang, 'back'), callback_data="edit_seller_region")])
        await query.edit_message_text(
            t(lang, 'region_pick_district', name=region_name(region['name'], lang)),
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        # Tumansiz — to'g'ridan-to'g'ri saqlaymiz
        user = db.get_user_by_telegram_id(update.effective_user.id)
        db.update_user(user['id'], region_id=region_id)
        r = db.get_region_by_id(region_id)
        await query.answer(t(lang, 'region_saved_toast', name=region_name(r['name'], lang)), show_alert=True)
        await seller_profile(update, context)


async def seller_district_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tuman tanlandi — saqlaydi."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    data = query.data.replace("sregdist_", "")

    if "_" in data:
        # "0_{region_id}" — butun viloyat
        region_id = int(data.split("_")[1])
    else:
        region_id = int(data)

    db.update_user(user['id'], region_id=region_id)
    r = db.get_region_by_id(region_id)
    await query.answer(t(lang, 'region_saved_toast', name=region_name(r['name'], lang)), show_alert=True)
    await seller_profile(update, context)


async def edit_buyer_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(T(update, context, 'ask_new_name'))
    return EDIT_PROFILE_NAME


async def edit_buyer_name_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    name = validate_fullname(update.message.text, max_len=60)
    if not name:
        await update.message.reply_text(t(lang, 'name_invalid'))
        return EDIT_PROFILE_NAME

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], name=name)
    await update.message.reply_text(t(lang, 'name_updated_excl'))
    await buyer_panel(update, context)
    return ConversationHandler.END


async def edit_buyer_phone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)

    await query.edit_message_text(t(lang, 'ask_new_phone'))
    # edit_message_text reply_markup qabul qilmaydi ReplyKeyboard uchun,
    # shuning uchun alohida xabar yuboramiz
    await query.message.reply_text(
        t(lang, 'press_phone_btn'),
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(t(lang, 'phone_button'), request_contact=True)]],
                                         resize_keyboard=True, one_time_keyboard=True)
    )
    return EDIT_PROFILE_PHONE


async def edit_buyer_phone_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text

    normalized = normalize_phone(phone)
    if not normalized:
        await update.message.reply_text(t(lang, 'phone_invalid_2'))
        return EDIT_PROFILE_PHONE

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], phone_number=normalized)
    await update.message.reply_text(t(lang, 'phone_updated'), reply_markup=ReplyKeyboardRemove())
    await buyer_panel(update, context)
    return ConversationHandler.END


async def edit_seller_field_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # masalan: "edit_shop_name", "edit_working_days", "edit_telegram"

    # BUG FIX #4: field nomini to'g'ri ajratish
    if data == "edit_telegram":
        field = "telegram"
    elif data.startswith("edit_shop_"):
        field = data[len("edit_"):]   # "shop_name", "shop_address", "shop_landmark"
    elif data.startswith("edit_working_"):
        field = data[len("edit_"):]   # "working_days", "working_hours"
    else:
        field = data[len("edit_"):]

    context.user_data['editing_field'] = field
    lang = get_lang(update, context)

    field_labels = {
        'shop_name': t(lang, 'efl_shop_name'),
        'shop_address': t(lang, 'efl_shop_address'),
        'shop_landmark': t(lang, 'efl_shop_landmark'),
        'working_days': t(lang, 'efl_working_days'),
        'working_hours': t(lang, 'efl_working_hours'),
        'telegram': t(lang, 'efl_telegram'),
    }

    label = field_labels.get(field, field)

    if field == 'shop_address':
        await query.edit_message_text(t(lang, 'edit_field_ask_addr', label=label))
        await query.message.reply_text(
            t(lang, 'send_location_or_text'),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(t(lang, 'send_location_button'), request_location=True)]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return EDIT_SHOP_ADDRESS
    else:
        await query.edit_message_text(t(lang, 'edit_field_ask', label=label))

    state_map = {
        'shop_name': EDIT_SHOP_NAME,
        'shop_landmark': EDIT_SHOP_LANDMARK,
        'working_days': EDIT_WORKING_DAYS,
        'working_hours': EDIT_WORKING_HOURS,
        'telegram': EDIT_TELEGRAM_USERNAME,
    }
    return state_map.get(field, ConversationHandler.END)


async def edit_seller_field_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get('editing_field')
    user = db.get_user_by_telegram_id(update.effective_user.id)

    if field == 'shop_address' and update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        addr_text = await resolve_shop_address(lat, lon)
        db.update_user(user['id'], shop_address=addr_text, shop_lat=lat, shop_lon=lon)
        if addr_text:
            await update.message.reply_text(T(update, context, 'address_detected', address=addr_text))
    else:
        value = update.message.text.strip()
        field_map = {
            'shop_name': 'shop_name',
            'shop_address': 'shop_address',
            'shop_landmark': 'shop_landmark',
            'working_days': 'working_days',
            'working_hours': 'working_hours',
            'telegram': 'telegram_username',
        }
        if field in field_map:
            db.update_user(user['id'], **{field_map[field]: value})

    await update.message.reply_text(T(update, context, 'info_updated'), reply_markup=ReplyKeyboardRemove())
    await seller_panel(update, context)
    return ConversationHandler.END


async def edit_card_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi karta ma'lumotini qo'shish/tahrirlash."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟦 Uzcard",     callback_data="card_type_uzcard")],
        [InlineKeyboardButton("🟩 Humo",       callback_data="card_type_humo")],
        [InlineKeyboardButton("🔵 Visa",       callback_data="card_type_visa")],
        [InlineKeyboardButton("🔴 Mastercard", callback_data="card_type_mastercard")],
        [InlineKeyboardButton(t(lang, 'btn_card_remove'), callback_data="card_type_remove")],
        [InlineKeyboardButton(t(lang, 'btn_cancel_edit'), callback_data="seller_profile")],
    ])
    await query.edit_message_text(
        t(lang, 'card_menu'),
        reply_markup=kb,
        parse_mode='HTML'
    )
    return EDIT_CARD_TYPE


async def edit_card_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    if query.data == "card_type_remove":
        user = db.get_user_by_telegram_id(update.effective_user.id)
        db.update_user(user['id'], card_number=None, card_owner=None, card_type=None)
        await query.edit_message_text(t(lang, 'card_removed'))
        await seller_profile(update, context)
        return ConversationHandler.END

    card_type = query.data.replace("card_type_", "")
    context.user_data['new_card_type'] = card_type
    await query.edit_message_text(
        t(lang, 'card_number_ask'),
        parse_mode='HTML'
    )
    return EDIT_CARD_NUMBER


async def edit_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    raw = update.message.text.replace(" ", "").replace("-", "")

    if not raw.isdigit() or len(raw) not in (16, 18, 20):
        await update.message.reply_text(
            t(lang, 'card_number_invalid'),
            parse_mode='HTML'
        )
        return EDIT_CARD_NUMBER

    context.user_data['new_card_number'] = raw
    await update.message.reply_text(
        t(lang, 'card_owner_ask'),
        parse_mode='HTML'
    )
    return EDIT_CARD_OWNER


async def edit_card_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    owner = update.message.text.strip().upper()

    if len(owner) < 3 or len(owner) > 50:
        await update.message.reply_text(t(lang, 'card_owner_invalid'))
        return EDIT_CARD_OWNER

    user = db.get_user_by_telegram_id(update.effective_user.id)
    card_type = context.user_data.pop('new_card_type', '')
    card_number = context.user_data.pop('new_card_number', '')

    db.update_user(
        user['id'],
        card_type=card_type,
        card_number=card_number,
        card_owner=owner
    )

    # Tasdiqlash
    cnum = card_number
    masked = f"{cnum[:4]} **** **** {cnum[-4:]}"
    ctype_label = CARD_TYPE_LABELS.get(card_type, card_type)

    await update.message.reply_text(
        t(lang, 'card_saved', ctype=ctype_label, masked=masked, owner=owner),
        parse_mode='HTML'
    )
    await seller_profile(update, context)
    return ConversationHandler.END


async def seller_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])

    order = db.get_order_by_id(order_id)
    lang = get_lang(update, context)

    if not order:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    dlv = order.get('delivery_type', 'delivery')
    keyboard = []
    if order['status'] == 'pending':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data=f"confirm_order_{order_id}")])
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_reject'), callback_data=f"cancel_order_{order_id}")])
    elif order['status'] == 'confirmed':
        if dlv == 'delivery':
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_delivered'), callback_data=f"deliver_order_{order_id}"
            )])
        else:
            # Pickup: xaridor o'zi "Oldim" bosadi, lekin sotuvchi ham tasdiqlashi mumkin
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_buyer_received'), callback_data=f"deliver_order_{order_id}"
            )])
    # Kuryerga uzatish — yetkazib berish buyurtmasi hali yopilmagan bo'lsa
    if dlv == 'delivery' and order['status'] in ('pending', 'confirmed'):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_forward_courier'), callback_data=f"crfwd_{order_id}"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_correspondence'), callback_data=f"msgs_{order_id}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_orders")])

    pay_method = order.get('payment_method') or 'cash'
    pay_lbl = pay_label(pay_method, lang)

    # P2P bo'lsa — sotuvchiga karta raqamini eslatamiz
    pay_note = ""
    if pay_method == 'p2p':
        seller_user = db.get_user_by_telegram_id(update.effective_user.id)
        if seller_user and seller_user.get('card_number'):
            cnum = seller_user['card_number']
            masked = f"{cnum[:4]} **** **** {cnum[-4:]}"
            ctype = CARD_TYPE_LABELS.get(seller_user.get('card_type', ''), '💳')
            pay_note = t(lang, 'p2p_your_card', ctype=ctype, masked=masked)
        else:
            pay_note = t(lang, 'p2p_no_card')

    dlv_type = dlv_label(dlv, lang)

    # Yetkazib berish manzili — kuryer uchun (faqat delivery buyurtmalarda)
    delivery_block = ""
    if dlv == 'delivery':
        b_lat = order.get('buyer_lat')
        b_lon = order.get('buyer_lon')
        addr_txt = human_address(order.get('delivery_address'))
        parts = []
        if addr_txt:
            parts.append(t(lang, 'seller_order_addr', addr=html.escape(addr_txt)))
        if b_lat is not None and b_lon is not None:
            parts.append(t(lang, 'seller_order_map',
                           url=f"https://www.google.com/maps/search/?api=1&query={b_lat},{b_lon}"))
            s_lat = order.get('shop_lat')
            s_lon = order.get('shop_lon')
            if s_lat is not None and s_lon is not None:
                d = haversine_km(s_lat, s_lon, b_lat, b_lon)
                if d is not None:
                    parts.append(t(lang, 'seller_dist_from_shop', km=f"{d:.1f}"))
        if not parts:
            parts.append(t(lang, 'addr_not_shown'))
        delivery_block = "".join(parts)

    await query.edit_message_text(
        t(lang, 'seller_order_body',
          oid=fmt_order_id(order['id']), pname=html.escape(order.get('product_name') or ''),
          qty=order['quantity'], total=fmt_price(order['total_price']),
          status=status_label(order['status'], lang), dlv=dlv_type,
          pay=pay_lbl, paynote=pay_note,
          buyer=html.escape(order.get('buyer_name') or ''),
          phone=fmt_phone(order.get('buyer_phone')),
          delivery=delivery_block, date=fmt_datetime(order.get('created_at'))),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def seller_forward_courier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi buyurtma manzilini kuryerga uzatadi.
    Bot sotuvchiga forward qilinadigan paket yuboradi:
    1) mijoz lokatsiyasi (pin),  2) buyurtma + manzil matni,  3) yo'riqnoma."""
    query = update.callback_query
    # Eslatma: button_handler bu callback uchun allaqachon query.answer() chaqirgan.
    chat_id = update.effective_chat.id
    lang = get_lang(update, context)

    try:
        order_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):
        await context.bot.send_message(chat_id, t(lang, 'order_num_invalid'))
        return

    order = db.get_order_by_id(order_id)
    if not order:
        await context.bot.send_message(chat_id, t(lang, 'order_not_found'))
        return

    # Egalik tekshiruvi — faqat shu buyurtma sotuvchisi yoki admin
    seller_user = db.get_user_by_telegram_id(update.effective_user.id)
    is_owner = bool(seller_user and seller_user.get('id') == order.get('seller_id'))
    is_admin = (update.effective_user.id == ADMIN_ID) or (
        seller_user and seller_user.get('role') == 'admin'
    )
    if not (is_owner or is_admin):
        await context.bot.send_message(chat_id, t(lang, 'not_your_order_plain'))
        return

    b_lat = order.get('buyer_lat')
    b_lon = order.get('buyer_lon')
    s_lat = order.get('shop_lat')
    s_lon = order.get('shop_lon')

    pay_method = order.get('payment_method') or 'cash'
    pay_lbl = pay_label(pay_method, lang)
    addr_txt = human_address(order.get('delivery_address'))

    # 1) Mijoz lokatsiyasi (pin) — forward qilish uchun alohida xabar
    if b_lat is not None and b_lon is not None:
        try:
            await context.bot.send_location(chat_id=chat_id, latitude=b_lat, longitude=b_lon)
        except Exception as e:
            logging.warning(f"courier send_location xatosi: {e}")

    # 2) Buyurtma + manzil matni
    lines = [t(lang, 'courier_body',
               oid=fmt_order_id(order['id']),
               pname=html.escape(order.get('product_name') or ''),
               qty=order.get('quantity'), total=fmt_price(order.get('total_price')),
               pay=pay_lbl, buyer=html.escape(order.get('buyer_name') or ''),
               phone=fmt_phone(order.get('buyer_phone')))]
    if addr_txt:
        lines.append(t(lang, 'courier_addr', addr=html.escape(addr_txt)))
    if b_lat is not None and b_lon is not None:
        lines.append(t(lang, 'courier_map',
                       url=f"https://www.google.com/maps/search/?api=1&query={b_lat},{b_lon}"))
        if s_lat is not None and s_lon is not None:
            d = haversine_km(s_lat, s_lon, b_lat, b_lon)
            if d is not None:
                lines.append(t(lang, 'courier_dist', km=f"{d:.1f}"))
            lines.append(t(lang, 'courier_route',
                           url=f"https://www.google.com/maps/dir/?api=1&origin={s_lat},{s_lon}&destination={b_lat},{b_lon}"))
    if not addr_txt and (b_lat is None or b_lon is None):
        lines.append(t(lang, 'courier_no_addr'))

    await context.bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode='HTML',
        disable_web_page_preview=True,
    )

    # 3) Yo'riqnoma
    await context.bot.send_message(
        chat_id,
        t(lang, 'courier_instructions'),
        parse_mode='HTML',
    )


async def update_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    # confirm_order_ID, cancel_order_ID, deliver_order_ID
    parts = data.split("_")
    order_id = int(parts[2])
    action = parts[0]  # confirm / cancel / deliver

    status_map = {'confirm': 'confirmed', 'cancel': 'cancelled', 'deliver': 'delivered'}
    new_status = status_map.get(action)
    if new_status:
        # Avtomatik bekor qilish taymerini va eslatmani o'chiramiz
        if new_status in ('confirmed', 'cancelled') and context.application.job_queue:
            jobs = context.application.job_queue.get_jobs_by_name(f"auto_cancel_{order_id}")
            for job in jobs:
                job.schedule_removal()
            jobs = context.application.job_queue.get_jobs_by_name(f"reminder_{order_id}")
            for job in jobs:
                job.schedule_removal()

        # Stock kamaytirish — faqat tasdiqlanganda
        if new_status == 'confirmed':
            try:
                order_for_stock = db.get_order_by_id(order_id)
                if order_for_stock:
                    db.decrement_stock_on_confirm(
                        order_for_stock['product_id'],
                        order_for_stock['quantity']
                    )
            except Exception as e:
                logging.error(f"Stock kamaytirish xatosi: {e}")

        db.update_order_status(order_id, new_status)

        # Xaridorga bildirishnoma yuboramiz (xaridor tilida)
        try:
            order = db.get_order_by_id(order_id)
            if order and order.get('buyer_tg'):
                buyer = db.get_user_by_id(order['buyer_id'])
                blang = get_user_lang(buyer) if buyer else DEFAULT_LANG
                dlv = order.get('delivery_type', 'delivery')
                is_pickup = dlv == 'pickup'
                oid = fmt_order_id(order_id)
                pname = html.escape(order.get('product_name') or '')

                msg_map = {
                    'confirmed': t(blang, 'order_confirmed_pickup' if is_pickup else 'order_confirmed_delivery',
                                   oid=oid, pname=pname),
                    'cancelled': t(blang, 'order_cancelled_notify', oid=oid, pname=pname),
                    'delivered': t(blang, 'order_delivered_pickup' if is_pickup else 'order_delivered_delivery',
                                   oid=oid, pname=pname),
                }

                txt = msg_map.get(new_status)
                if txt:
                    kb = None
                    if new_status == 'delivered':
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                t(blang, 'btn_leave_rating'), callback_data=f"order_rate_{order_id}"
                            )
                        ]])
                    await context.bot.send_message(
                        chat_id=order['buyer_tg'], text=txt,
                        reply_markup=kb, parse_mode='HTML'
                    )
        except Exception as e:
            logging.error(f"Xaridorga bildirishnoma ketmadi: {e}")

    await seller_order_detail(update, context)


# ============================================================
# MESSAGING
# ============================================================

async def message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    context.user_data['current_order_id'] = order_id

    await query.edit_message_text(T(update, context, 'message_ask'))
    return MESSAGE_TEXT


async def message_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    order_id = context.user_data.get('current_order_id')

    user = db.get_user_by_telegram_id(update.effective_user.id)
    lang = get_lang(update, context)

    # Buyurtma bo'yicha xaridor va sotuvchini olamiz (telegram_id bilan)
    order = db.get_order_by_id(order_id)
    if not order:
        await update.message.reply_text(t(lang, 'order_not_found_x'))
        return ConversationHandler.END

    # Qabul qiluvchi tilini aniqlash uchun
    receiver = db.get_user_by_id(order['seller_id'] if user['id'] == order['buyer_id'] else order['buyer_id'])
    rlang = get_user_lang(receiver) if receiver else DEFAULT_LANG

    # Foydalanuvchi shu buyurtmaning xaridorimi yoki sotuvchisimi — shunga qarab xabar yuboriladi.
    # role'ga tayanish noto'g'ri, chunki bitta foydalanuvchi ham xaridor ham sotuvchi bo'lishi mumkin.
    if user['id'] == order['buyer_id']:
        receiver_id = order['seller_id']
        receiver_tg = order.get('seller_tg')
        sender_label = t(rlang, 'sender_label_buyer', name=html.escape(user.get('name') or ''))
    else:
        receiver_id = order['buyer_id']
        receiver_tg = order.get('buyer_tg')
        sender_label = t(rlang, 'sender_label_seller', name=html.escape(user.get('shop_name') or user.get('name') or ''))

    db.create_message(order_id, user['id'], receiver_id, message_text)
    await update.message.reply_text(t(lang, 'message_sent'))

    # Qabul qiluvchiga real yetkazish — Telegram orqali (qabul qiluvchi tilida)
    if receiver_tg:
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(rlang, 'btn_reply'), callback_data=f"order_msg_{order_id}")],
                [InlineKeyboardButton(t(rlang, 'btn_correspondence'), callback_data=f"msgs_{order_id}")],
            ])
            await context.bot.send_message(
                chat_id=receiver_tg,
                text=t(rlang, 'new_message_notify', oid=fmt_order_id(order_id),
                       sender=sender_label, msg=html.escape(message_text)),
                reply_markup=kb,
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"Xabar qabul qiluvchiga yetkazilmadi: {e}")

    # Qaysi panelga qaytishni active_mode aniqlaydi
    if get_active_mode(user, context) == 'seller':
        await seller_panel(update, context)
    else:
        await buyer_panel(update, context)

    return ConversationHandler.END


async def view_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyurtma bo'yicha xabar tarixini ko'rsatadi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    order = db.get_order_by_id(order_id)

    if not order or not user or user['id'] not in (order['buyer_id'], order['seller_id']):
        await query.edit_message_text(t(lang, 'order_not_yours_full'))
        return

    messages = db.get_messages_by_order(order_id)
    if not messages:
        text = t(lang, 'no_messages_yet')
    else:
        lines = [t(lang, 'messages_history_header', oid=fmt_order_id(order_id))]
        for m in messages[-30:]:  # so'nggi 30 ta xabar
            who = "👤" if m['sender_id'] == order['buyer_id'] else "🏪"
            name = html.escape(m.get('sender_name') or '')
            msg = html.escape(m.get('message') or '')
            ts = fmt_datetime(m.get('created_at'))
            lines.append(f"{who} <b>{name}</b> · {ts}\n{msg}\n")
        text = "\n".join(lines)
        # Telegram xabari 4096 belgidan uzun bo'la olmaydi — kesamiz
        if len(text) > 3800:
            text = text[:3800] + t(lang, 'old_messages_cut')

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_new_message'), callback_data=f"order_msg_{order_id}")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data=f"order_detail_{order_id}"
                              if user['id'] == order['buyer_id'] else f"seller_order_{order_id}")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')


async def seller_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchining barcha xabarli buyurtmalari ro'yxati."""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    rows = db.get_seller_messages_summary(user['id'])

    lang = get_lang(update, context)
    if not rows:
        await query.edit_message_text(
            t(lang, 'messages_empty'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")]])
        )
        return

    keyboard = []
    for rec in rows:
        label = f"📜 {fmt_order_id(rec['id'])} — {rec.get('product_name', '')[:25]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"msgs_{rec['id']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="seller_panel")])

    await query.edit_message_text(
        t(lang, 'recent_correspondence'),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# RATING
# ============================================================

async def rating_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    context.user_data['current_order_id'] = order_id
    context.user_data.pop('product_rating', None)
    context.user_data.pop('product_comment', None)
    context.user_data.pop('seller_rating', None)

    # 1-qadam: mahsulotni baholash
    keyboard = [[InlineKeyboardButton("⭐" * i, callback_data=f"prate_{i}")] for i in range(1, 6)]
    await query.edit_message_text(
        T(update, context, 'rate_product_ask'),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return PRODUCT_RATING


async def rating_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """1-qadam tugadi: mahsulot reytingi tanlandi -> izoh so'raymiz."""
    query = update.callback_query
    await query.answer()

    context.user_data['product_rating'] = int(query.data.split("_")[1])
    await query.edit_message_text(
        T(update, context, 'rate_product_comment_ask'),
        parse_mode='HTML'
    )
    return PRODUCT_COMMENT


async def rating_product_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """2-qadam tugadi: mahsulot izohi olindi -> sotuvchini baholashga o'tamiz."""
    comment = (update.message.text or "").strip()
    if comment == "-":
        comment = None
    context.user_data['product_comment'] = comment

    # 3-qadam: sotuvchini (do'konni) baholash
    keyboard = [[InlineKeyboardButton("⭐" * i, callback_data=f"srate_{i}")] for i in range(1, 6)]
    await update.message.reply_text(
        T(update, context, 'rate_seller_ask'),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return SELLER_RATING


async def rating_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """3-qadam tugadi: sotuvchi reytingi tanlandi -> bazaga yozamiz."""
    query = update.callback_query
    await query.answer()

    seller_rating = int(query.data.split("_")[1])
    product_rating = context.user_data.get('product_rating')
    comment = context.user_data.get('product_comment')
    order_id = context.user_data.get('current_order_id')
    user = db.get_user_by_telegram_id(update.effective_user.id)
    lang = get_lang(update, context)

    if not product_rating or not seller_rating or not order_id:
        await query.edit_message_text(t(lang, 'rate_not_found'))
        await buyer_panel(update, context)
        return ConversationHandler.END

    order = db.get_order_by_id_for_rating(order_id)
    if not order:
        await query.edit_message_text(t(lang, 'order_not_found_x'))
        await buyer_panel(update, context)
        return ConversationHandler.END

    # Bir buyurtmaga bir martadan ko'p baho qoldirishni oldini olamiz
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM reviews WHERE order_id=? AND buyer_id=?",
        (order_id, user['id'])
    )
    if cursor.fetchone():
        await query.edit_message_text(t(lang, 'rate_already'))
        await buyer_panel(update, context)
        return ConversationHandler.END

    db.create_review(
        order_id=order_id,
        seller_id=order['seller_id'],
        buyer_id=user['id'],
        rating=seller_rating,                 # do'kon (sotuvchi) reytingi
        comment=comment,                      # mahsulot haqida izoh
        product_id=order.get('product_id'),   # baho qaysi mahsulotga
        product_rating=product_rating         # mahsulot reytingi
    )

    # Sotuvchiga baho haqida xabar (sotuvchi tilida)
    try:
        full_order = db.get_order_by_id(order_id)
        if full_order and full_order.get('seller_tg'):
            seller = db.get_user_by_id(order['seller_id'])
            slang = get_user_lang(seller) if seller else DEFAULT_LANG
            p_stars = "⭐" * product_rating
            s_stars = "⭐" * seller_rating
            msg = t(slang, 'rate_seller_notify',
                    pname=html.escape(full_order.get('product_name') or ''),
                    pstars=p_stars, prate=product_rating,
                    sstars=s_stars, srate=seller_rating,
                    buyer=html.escape(user.get('name') or ''))
            if comment:
                msg += t(slang, 'rate_comment_line', comment=html.escape(comment))
            await context.bot.send_message(
                chat_id=full_order['seller_tg'], text=msg, parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"Baho bildirishnomasi ketmadi: {e}")

    await query.edit_message_text(
        t(lang, 'rate_thanks', pstars='⭐' * product_rating, sstars='⭐' * seller_rating)
    )
    await buyer_panel(update, context)
    return ConversationHandler.END


# ============================================================
# ADMIN PANEL
# ============================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin tekshiruvi
    _uid = update.effective_user.id if update.effective_user else None
    _user = db.get_user_by_telegram_id(_uid) if _uid else None
    lang = get_lang(update, context)
    if not _user or (_user['role'] != 'admin' and _uid != ADMIN_ID):
        if update.callback_query:
            await update.callback_query.answer(t(lang, 'no_access_alert'), show_alert=True)
        else:
            await update.message.reply_text(t(lang, 'not_admin'))
        return

    total_users = len(db.get_all_users())
    total_products = len(db.get_all_products())
    total_orders = len(db.get_all_orders())
    pending_requests = len(db.get_pending_seller_requests())

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_seller_requests_n', n=pending_requests), callback_data="admin_seller_requests")],
        [InlineKeyboardButton(t(lang, 'btn_admin_users'), callback_data="admin_users")],
        [InlineKeyboardButton(t(lang, 'btn_admin_products'), callback_data="admin_products")],
        [InlineKeyboardButton(t(lang, 'btn_admin_orders'), callback_data="admin_orders")],
        [InlineKeyboardButton(t(lang, 'btn_admin_channels'), callback_data="admin_channels")],
        [InlineKeyboardButton(t(lang, 'btn_admin_stats'), callback_data="admin_stats")],
        [InlineKeyboardButton(t(lang, 'btn_admin_broadcast'), callback_data="admin_broadcast")],
        [InlineKeyboardButton(t(lang, 'btn_admin_settings'), callback_data="admin_settings")],
        [InlineKeyboardButton(t(lang, 'btn_ai_assistant'), callback_data="ai_assistant")],
    ]

    text = t(lang, 'admin_panel_body', users=total_users, products=total_products, orders=total_orders)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        # Admin faqat inline panel bilan ishlaydi. Boshqa rejimlardan (mas. sotuvchi
        # profilini tahrirlash yoki xaridor qidiruvi) qolib ketgan pastki Reply
        # klaviaturani — jumladan "📍 Lokatsiya yuborish" tugmasini — tozalaymiz.
        try:
            await update.message.reply_text(t(lang, 'admin_kb_cleared'), reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def admin_seller_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin — kutilayotgan sotuvchi so'rovlari ro'yxati."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    requests = db.get_pending_seller_requests()

    if not requests:
        await query.edit_message_text(
            t(lang, 'no_pending_requests'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")]])
        )
        return

    keyboard = []
    for req in requests[:20]:
        name = req.get('name') or t(lang, 'anonymous')
        shop = req.get('shop_name') or ''
        label = f"🏪 {name} — {shop}"[:45]
        keyboard.append([InlineKeyboardButton(label, callback_data=f"seller_req_{req['id']}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")])

    await query.edit_message_text(
        t(lang, 'pending_requests_title', n=len(requests)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_seller_request_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bitta sotuvchi so'rovining batafsil ma'lumotlari."""
    query = update.callback_query
    await query.answer()

    request_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sr.*, u.name, u.phone_number, u.shop_name, u.shop_address,
               u.shop_landmark, u.working_days, u.working_hours,
               u.telegram_username, u.telegram_id, u.id as uid
        FROM seller_requests sr
        JOIN users u ON sr.user_id = u.id
        WHERE sr.id=?
    """, (request_id,))
    row = cursor.fetchone()

    lang = get_lang(update, context)
    if not row:
        await query.edit_message_text(
            t(lang, 'request_not_found'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_seller_requests")]])
        )
        return

    req = dict(row)
    user_id = req['uid']

    text = t(lang, 'seller_request_detail',
             name=html.escape(req.get('name') or ''),
             phone=req.get('phone_number') or '—',
             shop=html.escape(req.get('shop_name') or '—'),
             address=html.escape(req.get('shop_address') or '—'),
             landmark=html.escape(req.get('shop_landmark') or '—'),
             wd=html.escape(req.get('working_days') or '—'),
             wh=html.escape(req.get('working_hours') or '—'),
             tg=req.get('telegram_username') or '—',
             date=fmt_datetime(req.get('created_at')))

    keyboard = [
        [InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data=f"approve_seller_{user_id}")],
        [InlineKeyboardButton(t(lang, 'btn_reject'), callback_data=f"reject_seller_{user_id}")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_seller_requests")],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def approve_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sotuvchini tasdiqlaydi."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])
    user = db.get_user_by_id(user_id)
    lang = get_lang(update, context)

    if not user:
        await query.edit_message_text(t(lang, 'user_not_found'))
        return

    # Foydalanuvchini tasdiqlash
    db.update_user(user_id, is_approved=1, role='seller')

    # seller_requests jadvalini yangilash
    req = db.get_seller_request_by_user(user_id)
    if req:
        db.update_seller_request(req['id'], 'approved')

    # Sotuvchiga xabar (sotuvchi tilida)
    try:
        await context.bot.send_message(
            chat_id=user['telegram_id'],
            text=t(user, 'approve_seller_notify'),
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Sotuvchiga tasdiqlash xabari ketmadi: {e}")

    await query.edit_message_text(
        t(lang, 'seller_approved_admin', name=html.escape(user.get('name') or '')),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_requests_back'), callback_data="admin_seller_requests")]])
    )


async def reject_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sotuvchini rad etadi."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])
    user = db.get_user_by_id(user_id)
    lang = get_lang(update, context)

    if not user:
        await query.edit_message_text(t(lang, 'user_not_found'))
        return

    # So'rovni rad etish
    db.update_user(user_id, is_approved=0, role='buyer')

    req = db.get_seller_request_by_user(user_id)
    if req:
        db.update_seller_request(req['id'], 'rejected')

    # Foydalanuvchiga xabar (uning tilida)
    try:
        await context.bot.send_message(
            chat_id=user['telegram_id'],
            text=t(user, 'reject_seller_notify'),
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Sotuvchiga rad xabari ketmadi: {e}")

    await query.edit_message_text(
        t(lang, 'seller_rejected_admin', name=html.escape(user.get('name') or '')),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_requests_back'), callback_data="admin_seller_requests")]])
    )


ADMIN_USERS_PAGE_SIZE = 10


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Qidirish holatini tozalash
    context.user_data.pop('admin_searching_user', None)

    # Sahifa raqami callback_data dan kelishi mumkin: 'admin_users' yoki 'admin_users_pg_N'
    page = 0
    if query.data.startswith("admin_users_pg_"):
        try:
            page = int(query.data.replace("admin_users_pg_", ""))
        except ValueError:
            page = 0

    total, rows_raw = db.get_users_paginated(limit=ADMIN_USERS_PAGE_SIZE, offset=0)
    total_pages = max(1, (total + ADMIN_USERS_PAGE_SIZE - 1) // ADMIN_USERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    offset = page * ADMIN_USERS_PAGE_SIZE
    total, rows_raw = db.get_users_paginated(limit=ADMIN_USERS_PAGE_SIZE, offset=offset)
    rows = rows_raw
    columns = list(rows[0].keys()) if rows else []

    lang = get_lang(update, context)
    if not rows:
        await query.edit_message_text(
            t(lang, 'admin_no_users'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")]])
        )
        return

    keyboard = []
    # Qidirish tugmasi
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_search_user'), callback_data="admin_user_search")])
    for user in rows:
        status = "🟢" if not user.get('is_blocked') else "🔴"
        role_emoji = {"buyer": "🛒", "seller": "🏪", "admin": "🔧"}
        keyboard.append([InlineKeyboardButton(
            f"{status} {role_emoji.get(user.get('role'), '❓')} {user.get('name') or t(lang, 'anonymous')}",
            callback_data=f"admin_user_{user['id']}"
        )])

    # Pagination tugmalari
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_users_pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_users_pg_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")])

    await query.edit_message_text(
        t(lang, 'admin_users_title', total=total, page=page+1, pages=total_pages),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin — foydalanuvchi qidirish boshlash."""
    query = update.callback_query
    await query.answer()
    context.user_data['admin_searching_user'] = True
    lang = get_lang(update, context)
    await query.edit_message_text(
        t(lang, 'admin_user_search_ask'),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="admin_users")]
        ])
    )


async def admin_user_search_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin — foydalanuvchi qidirish natijalari."""
    search_text = update.message.text.strip()
    context.user_data.pop('admin_searching_user', None)
    lang = get_lang(update, context)

    if len(search_text) < 2:
        await update.message.reply_text(
            t(lang, 'admin_search_min2'),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_retry_search_user'), callback_data="admin_user_search")],
                [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_users")],
            ])
        )
        return

    results = db.search_users(search_text)

    if not results:
        await update.message.reply_text(
            t(lang, 'admin_search_none', q=search_text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_retry_search_user'), callback_data="admin_user_search")],
                [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_users")],
            ])
        )
        return

    keyboard = []
    for user in results[:20]:
        status = "🟢" if not user.get('is_blocked') else "🔴"
        role_emoji = {"buyer": "🛒", "seller": "🏪", "admin": "🔧"}
        name = user.get('name') or t(lang, 'anonymous')
        shop = f" · {user['shop_name']}" if user.get('shop_name') else ""
        keyboard.append([InlineKeyboardButton(
            f"{status} {role_emoji.get(user.get('role'), '❓')} {name}{shop}",
            callback_data=f"admin_user_{user['id']}"
        )])

    keyboard.append([InlineKeyboardButton(t(lang, 'btn_retry_search_user'), callback_data="admin_user_search")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_users")])

    await update.message.reply_text(
        t(lang, 'admin_search_results', q=search_text, n=len(results)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    query = update.callback_query
    if user_id is None:
        await query.answer()
        user_id = int(query.data.split("_")[2])

    user = db.get_user_by_id(user_id)
    lang = get_lang(update, context)

    if not user:
        await query.edit_message_text(t(lang, 'user_not_found'))
        return
    status = t(lang, 'adu_status_active') if not user['is_blocked'] else t(lang, 'adu_status_blocked')

    # Sotuvchi uchun is_approved ni ko'rsatamiz
    is_seller = bool(user.get('shop_name'))
    if is_seller:
        approved_text = t(lang, 'adu_seller_approved') if user.get('is_approved') else t(lang, 'adu_seller_not_approved')
    else:
        approved_text = t(lang, 'adu_buyer_dash')

    keyboard = [
        [InlineKeyboardButton(
            t(lang, 'btn_unblock') if user['is_blocked'] else t(lang, 'btn_block'),
            callback_data=f"admin_block_{user_id}"
        )],
    ]

    # Sotuvchi tasdiqlash/bekor qilish — faqat do'koni bor foydalanuvchilar uchun
    if is_seller:
        if user.get('is_approved'):
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_unverify_seller'),
                callback_data=f"admin_verify_{user_id}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                t(lang, 'btn_verify_seller'),
                callback_data=f"admin_verify_{user_id}"
            )])

    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_users")])

    seller_flag = is_seller or user.get('role') == 'seller'

    # ===== Asosiy ma'lumotlar =====
    uname = user.get('telegram_username')
    uname_txt = f"@{html.escape(uname)}" if uname else "—"
    verified_txt = t(lang, 'adu_yes') if user.get('is_verified') else t(lang, 'adu_no')
    _none = t(lang, 'word_none_yes')

    text = t(lang, 'adu_main_block',
             id=user['id'], name=html.escape(user.get('name') or t(lang, 'anonymous')),
             tgid=user.get('telegram_id'), username=uname_txt,
             phone=fmt_phone(user.get('phone_number')), role=user.get('role') or '—',
             lang=user.get('language') or '—',
             region=user.get('region_id') if user.get('region_id') is not None else '—',
             status=status, approved=approved_text, verified=verified_txt,
             created=fmt_datetime(user.get('created_at')), updated=fmt_datetime(user.get('updated_at')))

    # ===== Do'kon ma'lumotlari =====
    if seller_flag:
        shop_addr = human_address(user.get('shop_address'))
        addr_line = (html.escape(shop_addr) if shop_addr else _none) + maps_link(user.get('shop_lat'), user.get('shop_lon'))
        text += t(lang, 'adu_shop_block',
                  name=html.escape(user.get('shop_name') or _none), addr=addr_line,
                  lm=html.escape(user.get('shop_landmark') or _none),
                  wh=html.escape(user.get('working_hours') or _none),
                  wd=html.escape(user.get('working_days') or _none))

    # ===== Ulangan kanallar (sotuvchi) =====
    if seller_flag:
        _chans = db.get_seller_channels(user_id)
        if _chans:
            _lines = [t(lang, 'adu_channels_header')]
            for _ch in _chans:
                _ttl = _ch.get('channel_title') or _ch.get('channel_id')
                _lines.append(f"• {html.escape(str(_ttl))}")
            text += "\n\n" + "\n".join(_lines)
        else:
            text += "\n\n" + t(lang, 'adu_channels_none')

    # ===== To'lov kartasi =====
    cnum = user.get('card_number')
    if cnum:
        cnum_str = str(cnum)
        grouped = " ".join(cnum_str[i:i + 4] for i in range(0, len(cnum_str), 4))
        ctype = CARD_TYPE_LABELS.get(user.get('card_type', ''), '💳')
        text += t(lang, 'adu_card_block', ctype=ctype, num=grouped,
                  owner=html.escape(user.get('card_owner') or _none))

    # ===== Referal =====
    text += t(lang, 'adu_referral_block',
              code=user.get('referral_code') or '—', by=user.get('referred_by') or '—',
              count=user.get('referral_count') or 0)

    # ===== Faollik statistikasi =====
    try:
        buyer_orders = db.get_orders_by_buyer(user_id) or []
    except Exception:
        buyer_orders = []
    text += t(lang, 'adu_activity_block', n=len(buyer_orders))
    if seller_flag:
        try:
            st = db.get_seller_stats(user_id) or {}
        except Exception:
            st = {}
        try:
            avg = db.get_seller_avg_rating(user_id) or 0.0
        except Exception:
            avg = 0.0
        text += t(lang, 'adu_seller_activity',
                  total=st.get('total_orders', 0), delivered=st.get('delivered', 0),
                  pending=st.get('pending', 0), cancelled=st.get('cancelled', 0),
                  products=st.get('products_count', 0),
                  revenue=fmt_price(st.get('total_revenue', 0)), rating=f"{avg:.1f}")

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
        disable_web_page_preview=True,
    )


async def admin_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])

    is_blocked = db.get_user_is_blocked(user_id)
    if is_blocked is not None:
        if is_blocked:
            db.unblock_user(user_id)
        else:
            db.block_user(user_id)

    # query.data ni mutatsiya qilmaymiz — user_id ni to'g'ridan-to'g'ri uzatamiz
    await admin_user_details(update, context, user_id=user_id)


async def admin_verify_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi uchun is_approved toggle — do'konni muzlatish/qayta tasdiqlash."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])
    user = db.get_user_by_id(user_id)
    lang = get_lang(update, context)

    if not user:
        await query.edit_message_text(t(lang, 'user_not_found'))
        return

    is_seller = bool(user.get('shop_name'))

    if is_seller:
        if user.get('is_approved'):
            # Tasdiqlashni bekor qilish — do'konni muzlatish
            db.update_user(user_id, is_approved=0)
            # Sotuvchiga xabar (sotuvchi tilida)
            try:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=t(user, 'seller_frozen_notify'),
                    parse_mode='HTML'
                )
            except Exception as e:
                logging.error(f"Sotuvchiga tasdiqlash bekor xabari ketmadi: {e}")
        else:
            # Qayta tasdiqlash — do'konni ochish
            db.update_user(user_id, is_approved=1, role='seller')
            # seller_requests jadvalini yangilash
            req = db.get_seller_request_by_user(user_id)
            if req:
                db.update_seller_request(req['id'], 'approved')
            # Sotuvchiga xabar (sotuvchi tilida)
            try:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=t(user, 'seller_reactivated_notify'),
                    parse_mode='HTML'
                )
            except Exception as e:
                logging.error(f"Sotuvchiga qayta tasdiqlash xabari ketmadi: {e}")
    else:
        # Oddiy foydalanuvchi uchun is_verified toggle (eski xatti-harakat)
        is_verified = db.get_user_is_verified(user_id)
        if is_verified is not None:
            db.update_user(user_id, is_verified=0 if is_verified else 1)

    await admin_user_details(update, context, user_id=user_id)


ADMIN_PRODUCTS_PAGE_SIZE = 10
_PROD_STATUS_EMOJI = {'active': '✅', 'reserve': '📦', 'deleted': '🗑'}


def _admin_product_rows(products):
    rows = []
    for p in products:
        st = _PROD_STATUS_EMOJI.get(p.get('status') or 'active', '✅')
        rows.append([InlineKeyboardButton(
            f"{st} {p['name']} — {fmt_price(p['price'])}",
            callback_data=f"admin_prod_{p['id']}"
        )])
    return rows


async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)
    context.user_data.pop('admin_searching_product', None)

    page = 0
    if query.data.startswith("admin_products_pg_"):
        try:
            page = int(query.data.replace("admin_products_pg_", ""))
        except ValueError:
            page = 0

    products = db.get_all_products()
    total = len(products)
    if not products:
        await query.edit_message_text(
            t(lang, 'admin_no_products'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")]])
        )
        return

    total_pages = (total + ADMIN_PRODUCTS_PAGE_SIZE - 1) // ADMIN_PRODUCTS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_PRODUCTS_PAGE_SIZE
    chunk = products[start:start + ADMIN_PRODUCTS_PAGE_SIZE]

    keyboard = _admin_product_rows(chunk)
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_search_product'), callback_data="admin_product_search")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_products_pg_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_products_pg_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")])

    await query.edit_message_text(
        t(lang, 'admin_products_title', n=total),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_product_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)
    context.user_data['admin_searching_product'] = True
    await query.edit_message_text(
        t(lang, 'admin_product_search_ask'),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data="admin_products")]])
    )


async def admin_product_search_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('admin_searching_product', None)
    lang = get_lang(update, context)
    search_text = (update.message.text or "").strip()
    if len(search_text) < 2:
        await update.message.reply_text(
            t(lang, 'admin_search_min2'),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_retry_search_product'), callback_data="admin_product_search")],
                [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_products")],
            ])
        )
        return
    results = db.admin_search_products(search_text)
    if not results:
        await update.message.reply_text(
            t(lang, 'admin_product_search_none', q=html.escape(search_text)),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, 'btn_retry_search_product'), callback_data="admin_product_search")],
                [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_products")],
            ])
        )
        return
    keyboard = _admin_product_rows(results[:20])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_retry_search_product'), callback_data="admin_product_search")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_products")])
    await update.message.reply_text(
        t(lang, 'admin_product_search_results', q=html.escape(search_text), n=len(results)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _admin_render_product(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    """Mahsulot detalini (matn) ko'rsatadi + admin amallari (olib tashlash/qaytarish/rasm)."""
    query = update.callback_query
    lang = get_lang(update, context)
    product = db.get_product_by_id(product_id)
    if not product:
        await query.edit_message_text(
            t(lang, 'product_not_found'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_products")]])
        )
        return

    status = product.get('status') or 'active'
    status_lbls = {'active': 'status_on_sale', 'reserve': 'status_reserve_short', 'deleted': 'status_removed'}
    status_lbl = t(lang, status_lbls.get(status, 'status_on_sale'))

    region_lbl = region_label_l(product.get('seller_region_id'), lang) or '—'
    prod_cnt = product.get('prod_review_count') or 0
    prod_rating = product.get('prod_avg_rating') or 0
    rating_txt = f"{prod_rating:.1f} ({prod_cnt})" if prod_cnt else '—'
    desc = (product.get('description') or '').strip() or '—'
    _uname = product.get('telegram_username')
    seller_disp = f"@{html.escape(str(_uname))}" if _uname else '—'

    text = t(lang, 'admin_product_body',
             name=html.escape(product.get('name') or '—'),
             price=fmt_price(product.get('price')),
             cat=html.escape(str(product.get('category_name') or '—')),
             status=status_lbl,
             shop=html.escape(str(product.get('shop_name') or '—')),
             seller=seller_disp,
             region=html.escape(str(region_lbl)),
             rating=rating_txt,
             created=fmt_datetime(product.get('created_at')),
             pid=product_id,
             desc=html.escape(desc))

    buttons = []
    if status == 'active':
        buttons.append([InlineKeyboardButton(t(lang, 'btn_remove_from_sale'), callback_data=f"admin_prodrm_{product_id}")])
    else:
        buttons.append([InlineKeyboardButton(t(lang, 'btn_return_to_sale'), callback_data=f"admin_prodrs_{product_id}")])
    if product.get('image_url'):
        buttons.append([InlineKeyboardButton(t(lang, 'btn_view_image'), callback_data=f"admin_prodimg_{product_id}")])
    buttons.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_products")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')


async def admin_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.rsplit("_", 1)[1])
    await _admin_render_product(update, context, product_id)


async def admin_product_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = int(query.data.rsplit("_", 1)[1])
    db.set_product_status(product_id, 'deleted')
    await query.answer(t(get_lang(update, context), 'admin_product_removed'), show_alert=False)
    await _admin_render_product(update, context, product_id)


async def admin_product_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = int(query.data.rsplit("_", 1)[1])
    db.set_product_status(product_id, 'active')
    await query.answer(t(get_lang(update, context), 'admin_product_restored'), show_alert=False)
    await _admin_render_product(update, context, product_id)


async def admin_product_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = int(query.data.rsplit("_", 1)[1])
    product = db.get_product_by_id(product_id)
    lang = get_lang(update, context)
    photo = product.get('image_url') if product else None
    if not photo:
        await query.answer(t(lang, 'no_image'), show_alert=True)
        return
    await query.answer()
    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id, photo=photo,
            caption=f"🖼 {html.escape(product.get('name') or '')}"
        )
    except Exception as e:
        logging.error(f"admin_product_image failed: {e}")


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    orders = db.get_all_orders()

    if not orders:
        await query.edit_message_text(
            t(lang, 'admin_no_orders'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = [[InlineKeyboardButton(
        f"{status_emoji.get(o['status'], '❓')} #{o['id']} — {fmt_price(o['total_price'])}",
        callback_data=f"admin_order_{o['id']}"
    )] for o in orders[:20]]
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")])

    await query.edit_message_text(
        t(lang, 'admin_orders_title', n=len(orders)),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)
    lang = get_lang(update, context)

    if not order:
        await query.edit_message_text(t(lang, 'order_not_found'))
        return

    dlv = order.get('delivery_type') or 'delivery'
    pay = order.get('payment_method') or '—'

    text = t(lang, 'admin_order_body',
             oid=fmt_order_id(order_id), pname=html.escape(order.get('product_name') or ''),
             qty=order.get('quantity'), total=fmt_price(order.get('total_price')),
             status=status_label(order.get('status'), lang),
             buyer=html.escape(order.get('buyer_name') or ''), buyer_phone=order.get('buyer_phone') or '—',
             seller=html.escape(order.get('seller_name') or ''), seller_phone=order.get('seller_phone') or '—',
             dlv=dlv_label(dlv, lang), pay=pay_label(pay, lang),
             date=fmt_datetime(order.get('created_at')))
    if order.get('delivery_address'):
        text += t(lang, 'admin_order_addr', addr=html.escape(order.get('delivery_address') or ''))

    keyboard = []
    if order.get('status') == 'pending':
        keyboard.append([
            InlineKeyboardButton(t(lang, 'btn_confirm'), callback_data=f"confirm_order_{order_id}"),
            InlineKeyboardButton(t(lang, 'btn_cancel'), callback_data=f"cancel_order_{order_id}"),
        ])
    elif order.get('status') == 'confirmed':
        keyboard.append([InlineKeyboardButton(t(lang, 'btn_delivered'), callback_data=f"deliver_order_{order_id}")])

    if order.get('status') not in ('cancelled',):
        keyboard.append([InlineKeyboardButton(
            t(lang, 'btn_force_cancel'), callback_data=f"admin_force_cancel_{order_id}"
        )])

    keyboard.append([InlineKeyboardButton(t(lang, 'btn_send_message'), callback_data=f"order_msg_{order_id}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'btn_correspondence'), callback_data=f"msgs_{order_id}")])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_orders")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def admin_force_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin istalgan buyurtmani majburan bekor qiladi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[3])
    order = db.get_order_by_id(order_id)

    if order:
        db.update_order_status(order_id, 'cancelled')
        # Ikki tomonga xabar (har biri o'z tilida)
        oid = fmt_order_id(order_id)
        buyer = db.get_user_by_id(order['buyer_id']) if order.get('buyer_id') else None
        seller = db.get_user_by_id(order['seller_id']) if order.get('seller_id') else None
        for tg_id, u in [(order.get('buyer_tg'), buyer), (order.get('seller_tg'), seller)]:
            if tg_id:
                try:
                    await context.bot.send_message(
                        chat_id=tg_id,
                        text=t(u or 'uz', 'admin_cancel_notify', oid=oid)
                    )
                except Exception:
                    pass

    await admin_orders(update, context)


ADMIN_CHANNELS_PAGE_SIZE = 8  # sahifada nechta SOTUVCHI ko'rsatiladi


async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin — qaysi sotuvchi qaysi kanal(lar)ni ulagani. Sotuvchi bo'yicha guruhlangan, sahifalangan."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)

    # Sahifa raqami: 'admin_channels' yoki 'admin_channels_pg_N'
    page = 0
    if query.data.startswith("admin_channels_pg_"):
        try:
            page = int(query.data.replace("admin_channels_pg_", ""))
        except ValueError:
            page = 0

    rows = db.get_all_seller_channels()

    if not rows:
        await query.edit_message_text(
            t(lang, 'admin_channels_none'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")]]),
            parse_mode='HTML',
        )
        return

    # Sotuvchi bo'yicha guruhlaymiz (rows allaqachon shop_name -> created_at bo'yicha tartiblangan)
    grouped = {}
    order = []
    for r in rows:
        sid = r['seller_id']
        if sid not in grouped:
            grouped[sid] = []
            order.append(sid)
        grouped[sid].append(r)

    # Sotuvchilar bo'yicha sahifalash
    total_sellers = len(order)
    total_pages = max(1, (total_sellers + ADMIN_CHANNELS_PAGE_SIZE - 1) // ADMIN_CHANNELS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_CHANNELS_PAGE_SIZE
    page_sellers = order[start:start + ADMIN_CHANNELS_PAGE_SIZE]

    lines = [t(lang, 'admin_channels_title', sellers=total_sellers, channels=len(rows)),
             t(lang, 'admin_channels_page', page=page + 1, pages=total_pages)]
    for sid in page_sellers:
        chans = grouped[sid]
        head = chans[0]
        shop = head.get('shop_name') or head.get('seller_name') or t(lang, 'anonymous')
        uname = head.get('telegram_username')
        uname_txt = f" (@{html.escape(uname)})" if uname else ""
        approved = "✅" if head.get('is_approved') else "⏳"
        lines.append(f"\n{approved} <b>{html.escape(str(shop))}</b>{uname_txt} — ID {sid}")
        for c in chans:
            ttl = c.get('channel_title') or c.get('channel_id')
            cmark = "📢" if c.get('is_active', 1) else "⚠️"
            lines.append(f"   {cmark} {html.escape(str(ttl))}  <code>{html.escape(str(c.get('channel_id')))}</code>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n…"

    # Navigatsiya tugmalari
    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_channels_pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_channels_pg_{page+1}"))
    if len(nav) > 1:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
        disable_web_page_preview=True,
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    s = db.get_admin_stats_summary()
    top = t(lang, 'top_seller_fmt', name=s['top_seller'], n=s['top_seller_count']) if s['top_seller'] else "—"

    await query.edit_message_text(
        t(lang, 'admin_stats_body',
          total_users=s['total_users'], buyers=s['buyers'], sellers=s['sellers'],
          products=s['products'], total_orders=s['total_orders'],
          pending=s['pending'], confirmed=s['confirmed'], delivered=s['delivered'], cancelled=s['cancelled'],
          today_rev=fmt_price(s['today_revenue']), today_cnt=s['today_count'],
          week_rev=fmt_price(s['week_revenue']), week_cnt=s['week_count'],
          month_rev=fmt_price(s['month_revenue']), month_cnt=s['month_count'],
          total_rev=fmt_price(s['total_revenue']), top=top),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_conversion_funnel'), callback_data="admin_analytics")],
            [InlineKeyboardButton(t(lang, 'btn_financial_report'), callback_data="admin_revenue")],
            [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")],
        ]),
        parse_mode='HTML'
    )


async def admin_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Conversion funnel va batafsil analytics."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    a = db.get_analytics_funnel()

    # Funnel vizualizatsiya
    funnel_bar = t(lang, 'analytics_funnel_bar',
                   b1='█' * 20,
                   b2='█' * max(1, int(20 * a['confirm_rate'] / 100)),
                   b3='█' * max(1, int(20 * a['deliver_rate'] / 100)),
                   b4='░' * max(1, int(20 * a['cancel_rate'] / 100)),
                   total=a['total_orders'], confirmed=a['confirmed_total'], confirm_rate=a['confirm_rate'],
                   delivered=a['delivered_total'], deliver_rate=a['deliver_rate'],
                   cancelled=a['cancelled_total'], cancel_rate=a['cancel_rate'])

    # Peak soatlar
    peak_hours_text = ""
    if a['peak_hours']:
        hours = [t(lang, 'analytics_peak_hour', h=h, cnt=cnt) for h, cnt in a['peak_hours'][:3]]
        peak_hours_text = ", ".join(hours)

    # Peak kunlar
    peak_days_text = ""
    if a['peak_days']:
        days = [t(lang, 'analytics_peak_day', d=d, cnt=cnt) for d, cnt in a['peak_days'][:3]]
        peak_days_text = ", ".join(days)

    # Top kategoriyalar
    top_cats_text = ""
    if a['top_categories']:
        for emoji, name, cnt in a['top_categories']:
            top_cats_text += t(lang, 'analytics_top_cat', emoji=emoji, name=name, cnt=cnt)

    # Top mahsulotlar
    top_prods_text = ""
    if a['top_products']:
        for i, (name, cnt, rev) in enumerate(a['top_products'], 1):
            top_prods_text += t(lang, 'analytics_top_prod', i=i, name=name, cnt=cnt, rev=fmt_price(rev))

    text = t(lang, 'analytics_body',
             funnel=funnel_bar,
             week_orders=a['week_orders'], week_confirmed=a['week_confirmed'], week_confirm_rate=a['week_confirm_rate'],
             week_delivered=a['week_delivered'], week_deliver_rate=a['week_deliver_rate'], week_cancelled=a['week_cancelled'],
             month_orders=a['month_orders'], month_confirmed=a['month_confirmed'], month_confirm_rate=a['month_confirm_rate'],
             month_delivered=a['month_delivered'], month_deliver_rate=a['month_deliver_rate'], month_cancelled=a['month_cancelled'],
             avg_order=fmt_price(a['avg_order_value']),
             new_week=a['new_users_week'], new_month=a['new_users_month'],
             peak_hours=peak_hours_text, peak_days=peak_days_text,
             top_cats=top_cats_text, top_prods=top_prods_text)

    if len(text) > 4000:
        text = text[:3900] + "\n\n…"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_general_stats'), callback_data="admin_stats")],
            [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")],
        ]),
        parse_mode='HTML'
    )


async def admin_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Batafsil moliyaviy hisobot — sotuvchi bo'yicha."""
    query = update.callback_query
    await query.answer()

    lang = get_lang(update, context)
    orders = db.get_all_orders()
    delivered = [o for o in orders if o['status'] == 'delivered']

    if not delivered:
        await query.edit_message_text(
            t(lang, 'revenue_no_delivered'),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(t(lang, 'back'), callback_data="admin_stats")
            ]])
        )
        return

    from collections import defaultdict
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')

    # Sotuvchi bo'yicha hisobot
    seller_stats = defaultdict(lambda: {'count': 0, 'revenue': 0, 'month_count': 0, 'month_revenue': 0})
    for o in delivered:
        sname = o.get('seller_name') or t(lang, 'unknown_seller')
        price = float(o.get('total_price') or 0)
        seller_stats[sname]['count'] += 1
        seller_stats[sname]['revenue'] += price
        if str(o.get('created_at') or '')[:10] >= month_ago:
            seller_stats[sname]['month_count'] += 1
            seller_stats[sname]['month_revenue'] += price

    # To'lov usuli bo'yicha
    pay_stats = defaultdict(int)
    for o in delivered:
        pay = o.get('payment_method') or 'cash'
        pay_stats[pay_label(pay, lang)] += 1

    # Yetkazish turi bo'yicha
    dlv_stats = defaultdict(int)
    for o in delivered:
        dlv = o.get('delivery_type') or 'delivery'
        dlv_stats[dlv_label(dlv, lang)] += 1

    total = sum(s['revenue'] for s in seller_stats.values())
    month_total = sum(s['month_revenue'] for s in seller_stats.values())

    # Top 5 sotuvchi
    top5 = sorted(seller_stats.items(), key=lambda x: x[1]['revenue'], reverse=True)[:5]
    sellers_text = ""
    for i, (name, s) in enumerate(top5, 1):
        sellers_text += t(lang, 'revenue_seller_line', i=i, name=name,
                          revenue=fmt_price(s['revenue']), count=s['count'])

    pay_text = "\n".join(t(lang, 'revenue_pay_line', label=k, n=v) for k, v in pay_stats.items())
    dlv_text = "\n".join(t(lang, 'revenue_pay_line', label=k, n=v) for k, v in dlv_stats.items())

    text = t(lang, 'revenue_body',
             month_total=fmt_price(month_total),
             month_count=sum(s['month_count'] for s in seller_stats.values()),
             total=fmt_price(total), delivered_count=len(delivered),
             sellers=sellers_text, pay=pay_text, dlv=dlv_text)

    if len(text) > 4000:
        text = text[:3900] + "\n\n…"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, 'btn_excel_report'), callback_data="excel_orders")],
            [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_stats")],
        ]),
        parse_mode='HTML'
    )


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['broadcasting'] = True
    await query.edit_message_text(T(update, context, 'broadcast_ask'))


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    users = db.get_all_users()
    products = db.get_all_products()
    orders = db.get_all_orders()

    lang = get_lang(update, context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_db_backup'), callback_data="admin_backup")],
        [InlineKeyboardButton(t(lang, 'btn_excel_users'), callback_data="excel_users")],
        [InlineKeyboardButton(t(lang, 'btn_excel_products'), callback_data="excel_products")],
        [InlineKeyboardButton(t(lang, 'btn_excel_orders'), callback_data="excel_orders")],
        [InlineKeyboardButton(t(lang, 'btn_clean_cancelled'), callback_data="admin_clean_cancelled")],
        [InlineKeyboardButton(t(lang, 'btn_change_language'), callback_data="change_lang")],
        [InlineKeyboardButton(t(lang, 'back'), callback_data="admin_panel")],
    ])

    await query.edit_message_text(
        t(lang, 'admin_settings_body', admin_id=ADMIN_ID,
          users=len(users), products=len(products), orders=len(orders)),
        reply_markup=kb,
        parse_mode='HTML'
    )


async def admin_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Excel eksport — foydalanuvchilar, mahsulotlar yoki buyurtmalar."""
    query = update.callback_query
    lang = get_lang(update, context)
    ru = (lang == 'ru')
    await query.answer(t(lang, 'excel_preparing'))

    export_type = query.data.replace("excel_", "")

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        import datetime as dt
        import os

        wb = openpyxl.Workbook()
        ws = wb.active

        # Header style
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="1a8a2e")
        header_align = Alignment(horizontal="center", vertical="center")

        def style_header(row):
            for cell in row:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

        def auto_width(ws):
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=0)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 40)

        ts = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

        if export_type == "users":
            ws.title = "Пользователи" if ru else "Foydalanuvchilar"
            headers = (["ID", "Telegram ID", "Имя", "Телефон", "Роль",
                        "Магазин", "ID региона", "Рейтинг", "Заказы", "Дата регистрации"]
                       if ru else
                       ["ID", "Telegram ID", "Ism", "Telefon", "Rol",
                        "Do'kon", "Hudud ID", "Reyting", "Buyurtmalar", "Ro'yxat sanasi"])
            ws.append(headers)
            style_header(ws[1])

            users = db.get_all_users()
            for u in users:
                avg = db.get_seller_avg_rating(u['id'])
                conn = db.get_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM orders WHERE buyer_id=?", (u['id'],))
                order_count = cur.fetchone()[0]
                region = db.get_region_by_id(u['region_id']) if u.get('region_id') else None
                if region:
                    if region.get('parent_id'):
                        parent = db.get_region_by_id(region['parent_id'])
                        region_name = f"{parent['name']} → {region['name']}" if parent else region['name']
                    else:
                        region_name = region['name']
                else:
                    region_name = ''
                ws.append([
                    u['id'], u['telegram_id'], u.get('name') or '',
                    u.get('phone_number') or '', u.get('role') or '',
                    u.get('shop_name') or '', region_name,
                    round(avg, 1), order_count,
                    str(u.get('created_at') or '')[:10]
                ])
            filename = f"tezbozor_users_{dt.datetime.now().strftime('%Y%m%d')}.xlsx"
            caption = (f"👥 Список пользователей\n{len(users)} · {ts}" if ru
                       else f"👥 Foydalanuvchilar ro'yxati\n{len(users)} ta · {ts}")

        elif export_type == "products":
            ws.title = "Товары" if ru else "Mahsulotlar"
            headers = (["ID", "Продавец", "Категория", "Название", "Цена",
                        "Статус", "Остаток", "Рейтинг", "Дата добавления"]
                       if ru else
                       ["ID", "Sotuvchi", "Kategoriya", "Nom", "Narx",
                        "Holat", "Zahira", "Reyting", "Qo'shilgan sana"])
            ws.append(headers)
            style_header(ws[1])

            products = db.get_all_products()
            for p in products:
                status = p.get('status') or ('active' if p.get('in_stock') else 'reserve')
                if ru:
                    status_lbl = {'active': 'В продаже', 'reserve': 'В резерве', 'deleted': 'Удалён'}.get(status, status)
                else:
                    status_lbl = {'active': 'Sotuvda', 'reserve': 'Zahirada', 'deleted': "O'chirilgan"}.get(status, status)
                ws.append([
                    p['id'], p.get('seller_name') or p.get('seller_id') or '',
                    p.get('category_name') or '',
                    p.get('name') or '', p.get('price') or 0,
                    status_lbl,
                    p.get('stock_count') if p.get('stock_count') is not None else ('Без лимита' if ru else 'Cheksiz'),
                    round(p.get('avg_rating') or 0, 1),
                    str(p.get('created_at') or '')[:10]
                ])
            filename = f"tezbozor_products_{dt.datetime.now().strftime('%Y%m%d')}.xlsx"
            caption = (f"📦 Список товаров\n{len(products)} · {ts}" if ru
                       else f"📦 Mahsulotlar ro'yxati\n{len(products)} ta · {ts}")

        elif export_type == "orders":
            ws.title = "Заказы" if ru else "Buyurtmalar"
            headers = (["ID", "Покупатель", "Продавец", "Товар", "Цена",
                        "Кол-во", "Итого", "Статус", "Оплата", "Доставка", "Дата"]
                       if ru else
                       ["ID", "Xaridor", "Sotuvchi", "Mahsulot", "Narx",
                        "Miqdor", "Jami", "Holat", "To'lov", "Yetkazish", "Sana"])
            ws.append(headers)
            style_header(ws[1])

            orders = db.get_all_orders()
            for o in orders:
                if ru:
                    status_lbl = {'pending': 'В ожидании', 'confirmed': 'Подтверждён',
                                  'delivered': 'Доставлен', 'cancelled': 'Отменён'}.get(o.get('status') or '', o.get('status') or '')
                else:
                    status_lbl = {'pending': 'Kutilmoqda', 'confirmed': 'Tasdiqlangan',
                                  'delivered': 'Yetkazildi', 'cancelled': 'Bekor'}.get(o.get('status') or '', o.get('status') or '')
                ws.append([
                    o['id'],
                    o.get('buyer_name') or '', o.get('seller_name') or '',
                    o.get('product_name') or '', o.get('product_price') or 0,
                    o.get('quantity') or 0, o.get('total_price') or 0,
                    status_lbl,
                    o.get('payment_method') or '', o.get('delivery_type') or '',
                    str(o.get('created_at') or '')[:10]
                ])
            filename = f"tezbozor_orders_{dt.datetime.now().strftime('%Y%m%d')}.xlsx"
            caption = (f"🛒 Список заказов\n{len(orders)} · {ts}" if ru
                       else f"🛒 Buyurtmalar ro'yxati\n{len(orders)} ta · {ts}")
        else:
            await query.message.reply_text(t(lang, 'unknown_export'))
            return

        auto_width(ws)
        wb.save(filename)

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(filename, 'rb'),
            filename=filename,
            caption=caption
        )
        os.remove(filename)

    except ImportError:
        await query.message.reply_text(
            t(lang, 'excel_not_installed'),
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Excel eksport xatosi: {e}")
        await query.message.reply_text(t(lang, 'error_generic', e=e))


async def admin_clean_cancelled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilingan eski (30 kundan oshgan) buyurtmalarni DB dan tozalaydi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update, context)

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM orders
        WHERE status='cancelled'
        AND created_at < datetime('now', '-30 days')
    """)
    deleted = cursor.rowcount
    conn.commit()

    # Natijani alohida ekranda ko'rsatamiz (bitta javob — ikki marta answer qilmaymiz)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, 'back'), callback_data="admin_settings")]])
    await query.edit_message_text(t(lang, 'clean_done', n=deleted), reply_markup=kb)


async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DB'ni admin'ga yuboradi — `.db` fayl sifatida."""
    query = update.callback_query
    lang = get_lang(update, context)
    await query.answer(t(lang, 'backup_preparing'))

    import datetime as dt
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"marketplace_backup_{ts}.db"

    ok = db.backup(backup_path)
    if not ok:
        await query.message.reply_text(t(lang, 'backup_failed'))
        return

    try:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(backup_path, 'rb'),
            filename=backup_path,
            caption=t(lang, 'backup_caption', ts=ts)
        )
    except Exception as e:
        await query.message.reply_text(t(lang, 'backup_send_failed', e=e))
    finally:
        try:
            import os
            os.remove(backup_path)
        except Exception:
            pass


# ============================================================
# AI RECOMMENDATIONS
# ============================================================

async def share_product_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi mahsulot havolasini oladi — xaridorlarga ulashish uchun."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])
    lang = get_lang(update, context)
    product = db.get_product_basic(product_id)

    if not product:
        await query.answer(t(lang, 'product_not_found'), show_alert=True)
        return

    bot_me = await context.bot.get_me()
    bot_username = bot_me.username
    deep_link = f"https://t.me/{bot_username}?start=product_{product_id}"

    from urllib.parse import quote
    share_text = f"{product.get('name', '')} — {fmt_price(product.get('price', 0))}"
    share_url = f"https://t.me/share/url?url={quote(deep_link, safe='')}&text={quote(share_text, safe='')}"

    text = t(lang, 'share_link_body', name=html.escape(product.get('name') or ''), link=deep_link)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'btn_share'), url=share_url)],
        [InlineKeyboardButton(t(lang, 'back'), callback_data=f"prod_menu_{product_id}")],
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')


async def show_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ko'rish tarixiga qarab tavsiya qilinadigan mahsulotlarni ko'rsatadi."""
    query = update.callback_query
    await query.answer()

    current_pid = int(query.data.split("_")[1])
    lang = get_lang(update, context)
    recs = _get_recommendations(context, db, current_pid, limit=10)

    if not recs:
        await query.answer(t(lang, 'recs_not_enough'), show_alert=True)
        return

    keyboard = []
    for p in recs:
        rating = p.get('prod_avg_rating') or p.get('avg_rating') or 0
        emoji = p.get('category_emoji') or '📦'
        keyboard.append([InlineKeyboardButton(
            f"{emoji} ⭐{rating:.1f} | {p['name']} — {fmt_price(p['price'])}",
            callback_data=f"prod_{p['id']}"
        )])
    keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data=f"prod_{current_pid}")])

    await query.edit_message_text(
        t(lang, 'recs_title'),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def ai_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    products = db.get_admin_products_summary(limit=10)

    if not products:
        await update.message.reply_text(t(lang, 'ai_no_products'))
        return

    keyboard = [[InlineKeyboardButton(
        f"🤖 {p['name']} — {fmt_price(p['price'])}",
        callback_data=f"prod_{p['id']}"
    )] for p in products]

    await update.message.reply_text(
        t(lang, 'ai_recs_title'),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ai_recommendations(update, context)


# ============================================================
# AI YORDAMCHI (DeepSeek)
# ============================================================

def _ai_exit_kb(lang):
    """AI rejimidan chiqish tugmasi."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t(lang, 'ai_exit'), callback_data="ai_exit")
    ]])


async def ai_assistant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI suhbat rejimini boshlaydi (tugma yoki /ai orqali)."""
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        msg = T(update, context, 'not_registered_short')
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    if not ai_assistant.is_enabled():
        if update.callback_query:
            await update.callback_query.answer(t(lang, 'ai_disabled_alert'), show_alert=True)
        else:
            await update.message.reply_text(t(lang, 'ai_disabled_alert'))
        return

    context.user_data['ai_chat'] = True
    context.user_data.pop('ai_draft', None)
    ai_assistant.reset_history(context.user_data)

    # Rolga moslangan xush kelibsiz matni (yangi imkoniyatlarni ko'rsatadi)
    role = user.get('role', 'buyer')
    if role != 'admin':
        role = get_active_mode(user, context)
    text = t(lang, f'ai_welcome_{role}') if role in ('seller', 'buyer', 'admin') else t(lang, 'ai_welcome')
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode='HTML', reply_markup=_ai_exit_kb(lang)
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, parse_mode='HTML', reply_markup=_ai_exit_kb(lang)
            )
    else:
        await update.message.reply_text(
            text, parse_mode='HTML', reply_markup=_ai_exit_kb(lang)
        )


async def ai_assistant_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI suhbat rejimidan chiqadi va tegishli panelga qaytaradi."""
    lang = get_lang(update, context)
    context.user_data.pop('ai_chat', None)
    context.user_data.pop('ai_draft', None)
    context.user_data.pop('ai_awaiting_photos', None)
    context.user_data.pop('ai_product_photos', None)
    ai_assistant.reset_history(context.user_data)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(t(lang, 'ai_exited'))
        except Exception:
            pass

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if user:
        if user['role'] == 'admin':
            await admin_panel(update, context)
        elif get_active_mode(user, context) == 'seller':
            await seller_panel(update, context)
        else:
            await buyer_panel(update, context)


async def ai_handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI agent rejimi — matnni bazaga ulangan agentga uzatadi va strukturalangan
    javobni (matn + mahsulot kartalari + e'lon qoralamasi) render qiladi."""
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    role = user.get('role', 'buyer') if user else 'buyer'
    if role != 'admin':
        role = get_active_mode(user, context) if user else 'buyer'
    user_name = (user.get('name') if user else '') or ''
    seller_id = user['id'] if user else None

    # "Yozyapti..." indikatori
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except Exception:
        pass

    result = await ai_assistant.ask(
        db, lang=lang, role=role, user_text=update.message.text,
        user_data=context.user_data, seller_id=seller_id, user_name=user_name,
    )

    text = (result.get('text') or '').strip() if isinstance(result, dict) else str(result)
    products = result.get('products') if isinstance(result, dict) else None
    draft = result.get('draft') if isinstance(result, dict) else None
    reactivated_id = result.get('reactivated_id') if isinstance(result, dict) else None

    # 1) Asosiy javob matni
    if text:
        await update.message.reply_text(text, reply_markup=_ai_exit_kb(lang))

    # 2) Topilgan real mahsulotlar — kartalar/tugmalar bilan
    if products:
        await _ai_send_products(update, context, lang, products)

    # 3) Sotuvchi uchun tayyor e'lon qoralamasi — joylash tugmasi bilan
    if draft:
        await _ai_send_draft(update, context, lang, draft)

    # 4) AI mahsulotni zahiradan sotuvga qaytardi — reklama ko'rinishini ko'rsatamiz
    if reactivated_id:
        await show_ad_preview(update, context, reactivated_id)


async def _ai_send_products(update, context, lang, products):
    """AI topgan real mahsulotlarni bosiladigan tugmalar sifatida yuboradi.
    Har bir tugma mavjud `prod_{id}` oqimini ochadi (ko'rish + buyurtma)."""
    rows = []
    for p in products:
        if not p.get('id'):
            continue
        label = p.get('name') or '—'
        if p.get('price'):
            label = f"{label} — {fmt_price(p['price'])}"
        if len(label) > 60:
            label = label[:57] + '…'
        rows.append([InlineKeyboardButton(label, callback_data=f"prod_{p['id']}")])
    if not rows:
        return
    rows.append([InlineKeyboardButton(t(lang, 'ai_exit'), callback_data="ai_exit")])
    await update.message.reply_text(
        t(lang, 'ai_found_products'),
        reply_markup=InlineKeyboardMarkup(rows)
    )


async def _ai_send_draft(update, context, lang, draft):
    """AI tuzgan e'lon qoralamasini ko'rsatadi va joylash tugmasini beradi."""
    context.user_data['ai_draft'] = draft
    name = draft.get('name') or '—'
    desc = draft.get('description') or ''
    cat = draft.get('category_name') or '—'
    price = draft.get('price')
    price_s = (fmt_price(price) if price else t(lang, 'ai_price_missing'))

    text = t(lang, 'ai_draft_card', name=name, price=price_s, category=cat, desc=desc)

    if price:
        kb = [
            [InlineKeyboardButton(t(lang, 'ai_add_photo_publish'), callback_data="ai_addphoto")],
            [InlineKeyboardButton(t(lang, 'ai_publish_nophoto'), callback_data="ai_publish")],
            [InlineKeyboardButton(t(lang, 'ai_discard'), callback_data="ai_exit")],
        ]
    else:
        # Narx yo'q — joylab bo'lmaydi; foydalanuvchi narx yozsin
        kb = [[InlineKeyboardButton(t(lang, 'ai_discard'), callback_data="ai_exit")]]

    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
    )


def _ai_photos_kb(lang):
    """AI rasm yig'ish bosqichidagi inline tugmalar."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, 'ai_photo_done_btn'), callback_data="ai_photos_done")],
        [InlineKeyboardButton(t(lang, 'ai_discard'), callback_data="ai_exit")],
    ])


async def _ai_publish_from_draft(update, context, draft, user, photos=None):
    """AI qoralamasini bazaga yozadi va rasmlarni saqlaydi (kanalga JOYLAMAYDI —
    bu reklama preview tasdiqidan keyin bo'ladi). Yaratilgan product_id ni qaytaradi."""
    photos = [p for p in (photos or []) if p][:db.MAX_PRODUCT_IMAGES]
    product_id = db.create_product(
        seller_id=user['id'],
        name=draft['name'],
        price=draft['price'],
        category_id=draft.get('category_id'),
        description=draft.get('description'),
        image_url=(photos[0] if photos else None),
    )
    if product_id and photos:
        db.set_product_images(product_id, photos)
    # AI rasm/qoralama holatlarini tozalaymiz
    for k in ('ai_draft', 'ai_awaiting_photos', 'ai_product_photos'):
        context.user_data.pop(k, None)
    return product_id


async def ai_publish_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI tuzgan e'lonni RASMSIZ bazaga saqlaydi va reklama ko'rinishini ko'rsatadi."""
    query = update.callback_query
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    draft = context.user_data.get('ai_draft')

    if not user or not draft or not draft.get('price') or not draft.get('name'):
        await query.answer(t(lang, 'ai_draft_expired'), show_alert=True)
        return
    await query.answer()

    product_id = await _ai_publish_from_draft(update, context, draft, user, photos=None)
    try:
        await query.edit_message_text(t(lang, 'ai_saved_preview', id=product_id))
    except Exception:
        pass
    if product_id:
        await show_ad_preview(update, context, product_id)


async def ai_addphoto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📷 Rasm qo'shib joylash» — rasm yig'ish bosqichini boshlaydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    draft = context.user_data.get('ai_draft')

    if not draft or not draft.get('price') or not draft.get('name'):
        await query.answer(t(lang, 'ai_draft_expired'), show_alert=True)
        return
    await query.answer()

    context.user_data['ai_awaiting_photos'] = True
    context.user_data['ai_product_photos'] = []
    try:
        await query.edit_message_text(t(lang, 'ai_send_photos'), reply_markup=_ai_photos_kb(lang))
    except Exception:
        await query.message.reply_text(t(lang, 'ai_send_photos'), reply_markup=_ai_photos_kb(lang))


async def ai_photo_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI rejimida mahsulot rasmlarini yig'adi (global PHOTO/Document handler).
    Faqat 'ai_awaiting_photos' yoqilgan bo'lsa ishlaydi; aks holda e'tiborsiz."""
    if not context.user_data.get('ai_awaiting_photos'):
        return  # AI rasm bosqichida emasmiz — boshqa rasmlarga tegmaymiz

    lang = get_lang(update, context)
    file_id = None
    if update.message.photo:
        photo = update.message.photo[-1]
        if photo.file_size and photo.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'photo_too_big'))
            return
        file_id = photo.file_id
    elif update.message.document:
        doc = update.message.document
        if not (doc.mime_type or '').startswith('image/'):
            await update.message.reply_text(t(lang, 'only_images'))
            return
        if doc.file_size and doc.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(t(lang, 'photo_too_big_doc'))
            return
        file_id = doc.file_id
    else:
        return

    photos = context.user_data.setdefault('ai_product_photos', [])
    photos.append(file_id)
    n = len(photos)
    if n >= db.MAX_PRODUCT_IMAGES:
        await update.message.reply_text(
            t(lang, 'ai_photos_max_reached', max=db.MAX_PRODUCT_IMAGES),
            reply_markup=_ai_photos_kb(lang)
        )
    else:
        await update.message.reply_text(
            t(lang, 'ai_photos_added', n=n, max=db.MAX_PRODUCT_IMAGES),
            reply_markup=_ai_photos_kb(lang)
        )


async def ai_photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«✅ Joylash» — yig'ilgan rasmlar bilan AI e'lonini joylaydi."""
    query = update.callback_query
    lang = get_lang(update, context)
    user = db.get_user_by_telegram_id(update.effective_user.id)
    draft = context.user_data.get('ai_draft')

    if not user or not draft or not draft.get('price') or not draft.get('name'):
        await query.answer(t(lang, 'ai_draft_expired'), show_alert=True)
        return

    photos = [p for p in context.user_data.get('ai_product_photos', []) if p]
    if not photos:
        # Hali rasm yo'q — yuborishni so'raymiz
        await query.answer(t(lang, 'ai_send_photo_hint'), show_alert=True)
        return
    await query.answer()

    product_id = await _ai_publish_from_draft(update, context, draft, user, photos=photos)

    msg = t(lang, 'ai_saved_preview', id=product_id)
    if photos:
        msg += t(lang, 'frag_photos_saved', n=len(photos))
    try:
        await query.edit_message_text(msg)
    except Exception:
        pass
    if product_id:
        await show_ad_preview(update, context, product_id)


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ai_assistant_start(update, context)


# ============================================================
# GENERIC BUTTON HANDLER
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Rate limiting: bir foydalanuvchi 0.5s dan tez callback yuborsa — e'tiborsiz
    uid = update.effective_user.id if update.effective_user else None
    if uid:
        now = _time.monotonic()
        last = context.user_data.get('_rl_btn', 0)
        if now - last < 0.5:
            try:
                await query.answer("⏳")
            except Exception:
                pass
            return
        context.user_data['_rl_btn'] = now

    data = query.data

    # === XAVFSIZLIK: admin amallari faqat admin uchun ===
    # button_handler barcha callback'larni yo'naltirgani uchun, admin amallarini
    # SHU YERDA tekshiramiz. Bu qo'shimcha himoya — oddiy foydalanuvchilar uchun
    # hech narsani o'zgartirmaydi, faqat admin bo'lmaganlarni to'xtatadi.
    ADMIN_CB_PREFIXES = (
        "admin_", "approve_seller_", "reject_seller_", "seller_req_", "excel_",
    )
    if data and data.startswith(ADMIN_CB_PREFIXES):
        _admin_user = db.get_user_by_telegram_id(uid) if uid else None
        _is_admin = bool(_admin_user) and (
            _admin_user.get("role") == "admin" or uid == ADMIN_ID
        )
        if not _is_admin:
            try:
                await query.answer(T(update, context, 'admin_only_action'), show_alert=True)
            except Exception:
                pass
            return

    await query.answer()

    handlers = {
        "buyer_panel": buyer_panel,
        "buyer_search_menu": buyer_search_menu,
        "buyer_categories": buyer_categories,
        "buyer_search": buyer_search,
        "buyer_shop_search": buyer_shop_search,
        "buyer_orders": buyer_orders,
        "buyer_profile": buyer_profile,
        "seller_panel": seller_panel,
        "seller_products": seller_products,
        "seller_orders": seller_orders,
        "seller_profile": seller_profile,
        "admin_panel": admin_panel,
        "admin_users": admin_users,
        "admin_products": admin_products,
        "admin_orders": admin_orders,
        "admin_stats": admin_stats,
        "admin_channels": admin_channels,
        "admin_revenue": admin_revenue,
        "admin_broadcast": admin_broadcast_start,
        "admin_seller_requests": admin_seller_requests,
        "admin_analytics": admin_analytics,
        "edit_seller_region": edit_seller_region,
        "contact_admin": contact_admin_start,
        "admin_backup": admin_backup,
        "admin_settings": admin_settings,
        "admin_clean_cancelled": admin_clean_cancelled,
        "skip_search_location": skip_search_location,
        "switch_to_buyer": switch_to_buyer,
        "switch_to_seller": switch_to_seller,
        "switch_to_buyer_confirm": switch_to_buyer_confirm,
        "switch_to_seller_confirm": switch_to_seller_confirm,
        "do_switch_buyer": switch_to_buyer,
        "do_switch_seller": switch_to_seller,
        "my_referral": my_referral,
        "seller_stats": seller_stats,
        "seller_export_excel": seller_export_excel,
        "seller_messages": seller_messages,
        "seller_reviews": seller_reviews,
        "buyer_reviews": buyer_reviews,
        "buyer_messages": buyer_messages,
        "reapply_seller": reapply_seller,
        "admin_user_search": admin_user_search_start,
        "cart_view": cart_view,
        "cart_clear": cart_clear_ask,
        "cart_clear_yes": cart_clear_yes,
        "change_lang": change_language_menu,
        "ai_assistant": ai_assistant_start,
        "ai_exit": ai_assistant_exit,
        "ai_publish": ai_publish_draft,
        "ai_addphoto": ai_addphoto_start,
        "ai_photos_done": ai_photos_done,
        "adprev_publish": ad_preview_publish,
        "adprev_regen": ad_preview_regen,
        "adprev_edit": ad_preview_edit,
        "adprev_skip": ad_preview_skip,
    }

    if data in handlers:
        await handlers[data](update, context)
    elif data.startswith("setlang_"):
        await set_language(update, context)
    # === SAVAT (cart) va GURUH (savat buyurtmasi) callback'lari ===
    elif data.startswith("cart_reset_add_"):
        await cart_reset_add(update, context)
    elif data.startswith("cart_add_"):
        await cart_add(update, context)
    elif data.startswith("cart_inc_"):
        await cart_inc(update, context)
    elif data.startswith("cart_dec_"):
        await cart_dec(update, context)
    elif data.startswith("cvinc_"):
        await cart_view_inc(update, context)
    elif data.startswith("cvdec_"):
        await cart_view_dec(update, context)
    elif data.startswith("cvrm_"):
        await cart_view_remove(update, context)
    elif data.startswith(("gconfirm_", "gcancel_", "gdeliver_")):
        await group_status_action(update, context)
    elif data.startswith("gcrfwd_"):
        await seller_forward_courier_group(update, context)
    elif data.startswith("seller_gorder_"):
        await seller_group_order_detail(update, context)
    elif data.startswith("gorder_detail_"):
        await buyer_group_order_detail(update, context)
    elif data.startswith("gbuyer_cancel_"):
        await buyer_cancel_group(update, context)
    elif data.startswith("gbuyer_pickup_"):
        await buyer_pickup_group(update, context)
    elif data.startswith("shop_products_"):
        await buyer_shop_products(update, context)
    elif data.startswith("shop_list_"):
        await buyer_shop_list(update, context)
    elif data.startswith("shop_") and not data.startswith("shop_products_") and not data.startswith("shop_list_"):
        await buyer_shop_detail(update, context)
    elif data.startswith("cat_"):
        # cat_ID yoki cat_ID_pg_N
        await buyer_category_products(update, context)
    elif data.startswith("edit_start_"):
        await edit_product_hub(update, context)
    elif data.startswith("prod_menu_"):
        await seller_product_menu(update, context)
    elif data.startswith("sp_list_"):
        await seller_products_list(update, context)
    elif data.startswith("pstatus_"):
        await change_product_status(update, context)
    elif data == "sp_search":
        await seller_product_search_start(update, context)
    elif data == "noop":
        pass
    elif data.startswith("prod_"):
        await buyer_product_details(update, context)
    elif data.startswith("pcomm_"):
        await product_reviews_view(update, context)
    elif data.startswith("toggle_stock_"):
        await toggle_product_stock(update, context)
    elif data.startswith("set_stock_"):
        await set_stock_prompt(update, context)
    elif data.startswith("msgs_"):
        await view_messages(update, context)
    elif data.startswith("call_"):
        # tel: URL Telegram'da ishlamaydi — raqamni matn sifatida ko'rsatamiz
        product_id = int(data.split("_")[1])
        product = db.get_product_basic(product_id)
        if product:
            phone = product.get('phone_number') or '—'
            await update.callback_query.answer(f"📞 {phone}", show_alert=True)
    elif data.startswith("delete_prod_") or data.startswith("delete_confirm_"):
        await delete_product(update, context)
    elif data.startswith("order_detail_"):
        await buyer_order_detail(update, context)
    elif data.startswith("buyer_cancel_"):
        await buyer_cancel_order(update, context)
    elif data.startswith("buyer_confirm_pickup_"):
        await buyer_confirm_pickup(update, context)
    elif data.startswith("seller_order_"):
        await seller_order_detail(update, context)
    elif data.startswith(("confirm_order_", "cancel_order_", "deliver_order_")):
        await update_order_status(update, context)
    elif data.startswith("crfwd_"):
        await seller_forward_courier(update, context)
    elif data.startswith("admin_user_"):
        await admin_user_details(update, context)
    elif data.startswith("admin_block_"):
        await admin_block_user(update, context)
    elif data.startswith("admin_verify_"):
        await admin_verify_user(update, context)
    elif data.startswith("excel_"):
        await admin_export_excel(update, context)
    elif data == "admin_clean_cancelled":
        await admin_clean_cancelled(update, context)
    elif data.startswith("recommend_"):
        await show_recommendations(update, context)
    elif data.startswith("share_link_"):
        await share_product_link(update, context)
    elif data.startswith("sregset_"):
        await seller_region_set(update, context)
    elif data.startswith("msg_"):
        # Buyurtmasiz sotuvchiga savol — mahsulot ID bo'yicha
        await product_ask_seller(update, context)
    elif data.startswith("sregdist_"):
        await seller_district_set(update, context)
    elif data.startswith("sreg_"):
        await search_region_select(update, context)
    elif data.startswith("sdist_"):
        await search_district_select(update, context)
    elif data.startswith("srt_"):
        await search_sort_change(update, context)
    elif data.startswith("pg_"):
        await search_page_change(update, context)
    elif data.startswith("admin_users_pg_"):
        await admin_users(update, context)
    elif data.startswith("admin_channels_pg_"):
        await admin_channels(update, context)
    elif data.startswith("admin_order_"):
        await admin_order_detail(update, context)
    elif data.startswith("admin_force_cancel_"):
        await admin_force_cancel_order(update, context)
    elif data.startswith("approve_seller_"):
        await approve_seller(update, context)
    elif data.startswith("reject_seller_"):
        await reject_seller(update, context)
    elif data.startswith("seller_req_"):
        await admin_seller_request_detail(update, context)
    elif data == "noop":
        # Sahifa indikatori tugmasi — hech narsa qilmaymiz, faqat answer()
        await update.callback_query.answer()


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Zahira sonini belgilash rejimida bo'lsa — uni avval ishlov beramiz
    if context.user_data.get('setting_stock_for'):
        handled = await set_stock_submit(update, context)
        if handled:
            return

    # Pastki panel tugmalari (uz/ru) — kanonik kalitga aylantiramiz
    action = bottom_action(text)

    if action:
        if not user:
            await update.message.reply_text(T(update, context, 'not_registered_short'))
            return

        # Pastki menyu bosilganda — eski search/broadcast/AI holatlarini tozalaymiz
        context.user_data.pop('search_state', None)
        context.user_data.pop('search_query', None)
        context.user_data.pop('broadcasting', None)
        context.user_data.pop('ai_chat', None)
        context.user_data.pop('ai_draft', None)
        context.user_data.pop('ai_awaiting_photos', None)
        context.user_data.pop('ai_product_photos', None)
        context.user_data.pop('ad_preview', None)
        context.user_data.pop('ad_editing_caption', None)
        ai_assistant.reset_history(context.user_data)

        # role o'rniga active_mode — bitta foydalanuvchi ikkala rejimda ishlashi mumkin
        active_mode = get_active_mode(user, context)

        # Rol talab qiladigan harakatlar
        role_actions = {
            'btn_search_menu': (buyer_search_menu, 'buyer'),
            'btn_search':      (buyer_search, 'buyer'),
            'btn_categories':  (buyer_categories, 'buyer'),
            'btn_my_orders':   (buyer_orders, 'buyer'),
            'btn_add_product': (seller_add_product_start, 'seller'),
            'btn_my_products': (seller_products, 'seller'),
            'btn_orders':      (seller_orders, 'seller'),
        }

        if action == 'btn_profile':
            if active_mode == 'buyer':
                await buyer_profile(update, context)
            elif active_mode == 'seller':
                await seller_profile(update, context)
        elif action == 'btn_home':
            if user['role'] == 'admin':
                await admin_panel(update, context)
            elif active_mode == 'seller':
                await seller_panel(update, context)
            else:
                await buyer_panel(update, context)
        elif action == 'btn_contact_admin':
            await update.message.reply_text(
                T(update, context, 'contact_admin_prompt'),
                parse_mode='HTML'
            )
            context.user_data['contacting_admin'] = True
        else:
            fn, required_role = role_actions[action]
            if active_mode == required_role:
                await fn(update, context)
        return

    # Reklama matnini sotuvchi tahrirlamoqda — kiritilgan matnni qabul qilamiz
    if context.user_data.get('ad_editing_caption'):
        await ad_preview_caption_input(update, context)
        return

    # AI yordamchi rejimi — erkin matn DeepSeek'ga uzatiladi
    if context.user_data.get('ai_chat'):
        if not user:
            context.user_data.pop('ai_chat', None)
            await update.message.reply_text(T(update, context, 'not_registered_short'))
            return
        # AI e'loni uchun rasm kutyapmiz — matn emas, rasm kerak
        if context.user_data.get('ai_awaiting_photos'):
            await update.message.reply_text(
                T(update, context, 'ai_send_photo_hint'),
                reply_markup=_ai_photos_kb(get_lang(update, context))
            )
            return
        await ai_handle_message(update, context)
        return

    # Admin bilan bog'lanish (pastki menyu orqali)
    if context.user_data.get('admin_searching_user'):
        if user and (user['role'] == 'admin' or update.effective_user.id == ADMIN_ID):
            await admin_user_search_result(update, context)
            return
        else:
            context.user_data.pop('admin_searching_user', None)

    if context.user_data.get('admin_searching_product'):
        if user and (user['role'] == 'admin' or update.effective_user.id == ADMIN_ID):
            await admin_product_search_result(update, context)
            return
        else:
            context.user_data.pop('admin_searching_product', None)

    if context.user_data.get('contacting_admin'):
        context.user_data.pop('contacting_admin', None)
        try:
            buyer_tg = f"@{user['telegram_username']}" if user and user.get('telegram_username') else "—"
            buyer_phone = user.get('phone_number') or '—' if user else '—'
            buyer_name = html.escape(user.get('name') or 'Anonim') if user else 'Anonim'
            role = user.get('role', 'buyer') if user else 'buyer'
            role_label = {'buyer': '🛒 Xaridor', 'seller': '🏪 Sotuvchi'}.get(role, role)
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📨 <b>Foydalanuvchidan xabar</b>\n\n"
                    f"{role_label}: {buyer_name}\n"
                    f"📞 {buyer_phone}\n"
                    f"📱 {buyer_tg}\n"
                    f"🆔 <code>{update.effective_user.id}</code>\n\n"
                    f"💬 {html.escape(text)}\n\n"
                    f"<i>Javob: /reply {update.effective_user.id} [matn]</i>"
                ),
                parse_mode='HTML'
            )
            await update.message.reply_text(T(update, context, 'contact_admin_sent'))
        except Exception as e:
            logging.error(f"Admin contact error: {e}")
            await update.message.reply_text(T(update, context, 'contact_admin_failed'))
        return

    # Admin broadcast
    if context.user_data.get('broadcasting'):
        context.user_data['broadcasting'] = False
        alang = get_lang(update, context)
        users = db.get_all_users()
        sent, failed = 0, 0
        sample_error = None
        failed_users = []   # kim olmaganini ko'rsatish uchun

        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u['telegram_id'],
                    text=t(u, 'admin_msg_prefix', text=text)
                )
                sent += 1
            except Exception as e:
                failed += 1
                failed_users.append(u)
                if sample_error is None:
                    sample_error = str(e)
                logging.error(f"Broadcast failed for {u['telegram_id']}: {e}")

        response = t(alang, 'broadcast_sent', n=sent)
        if failed:
            response += t(alang, 'broadcast_failed_n', n=failed)
            # Aniq kimlar olmagani — ism, username, ID
            response += t(alang, 'broadcast_failed_list_title')
            for u in failed_users[:30]:
                uname = u.get('telegram_username')
                tg = f"@{uname}" if uname else "—"
                response += t(alang, 'broadcast_failed_item',
                              name=html.escape(u.get('name') or t(alang, 'anonymous')),
                              tg=tg, id=u.get('telegram_id'))
            if sample_error:
                response += t(alang, 'broadcast_reason', err=sample_error[:200])
            response += t(alang, 'broadcast_reasons_common')
        await update.message.reply_text(response, parse_mode='HTML')
        return

    # Do'kon qidirish — foydalanuvchi do'kon nomini kiritdi
    if context.user_data.get('shop_search_state') == 'awaiting_query':
        context.user_data.pop('shop_search_state', None)
        query_text = text.strip()

        lang = get_lang(update, context)
        shops = db.search_shops(query=query_text)

        if not shops:
            await update.message.reply_text(
                t(lang, 'shop_not_found_q', q=query_text),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(lang, 'btn_retry_search'), callback_data="buyer_shop_search")],
                    [InlineKeyboardButton(t(lang, 'btn_home'), callback_data="buyer_panel")],
                ])
            )
            return

        context.user_data['_shop_results'] = shops
        await _render_shop_list(update.message, context, shops, page=0)
        return

    # Qidiruv — 1-bosqich: mahsulot nomi kiritildi, lokatsiyani so'raymiz
    if context.user_data.get('search_state') == 'awaiting_query':
        context.user_data['search_query'] = text.strip()
        context.user_data['search_state'] = 'awaiting_location'

        lang = get_lang(update, context)
        location_kb = ReplyKeyboardMarkup(
            [[KeyboardButton(t(lang, 'btn_send_location'), request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        skip_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, 'search_skip_location'), callback_data="skip_search_location")
        ]])
        await update.message.reply_text(
            t(lang, 'search_location_full'),
            reply_markup=location_kb,
        )
        await update.message.reply_text(
            t(lang, 'or_below'),
            reply_markup=skip_kb,
        )
        return

    # Qidiruv — 2-bosqich: foydalanuvchi lokatsiya o'rniga matn yubordi (manzil yozdi)
    # Bunga ham tayyor bo'lamiz — matnni e'tiborsiz qoldirib, faqat saqlangan so'rov bo'yicha qidiramiz
    if context.user_data.get('search_state') == 'awaiting_location':
        q_text = context.user_data.pop('search_query', None)
        context.user_data.pop('search_state', None)
        if q_text:
            await update.message.reply_text(
                T(update, context, 'text_instead_of_location'),
                reply_markup=ReplyKeyboardRemove(),
            )
            await _show_search_results(update, context, q_text)
        return

    # Noma'lum xabar
    await update.message.reply_text(T(update, context, 'unknown_command'))


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lokatsiya xabari uchun — qidiruv 2-bosqichi va deeplink masofa so'rovi."""
    loc = update.message.location

    # Deeplink (kanal orqali ochilgan) mahsulot uchun masofa so'ralgan bo'lsa
    pending_pid = context.user_data.get('_dist_pending_product')
    if pending_pid and context.user_data.get('search_state') != 'awaiting_location':
        context.user_data.pop('_dist_pending_product', None)
        lang = get_lang(update, context)
        if loc:
            remember_buyer_geo(context, loc.latitude, loc.longitude)
            product = db.get_product_by_id(pending_pid)
            if product and product.get('shop_lat') and product.get('shop_lon'):
                km = haversine_km(loc.latitude, loc.longitude,
                                  product['shop_lat'], product['shop_lon'])
                if km is not None:
                    await update.message.reply_text(
                        t(lang, 'deeplink_distance_result', km=f"{km:.1f}"),
                        reply_markup=ReplyKeyboardRemove(),
                    )
                    return
        await update.message.reply_text(
            t(lang, 'location_saved_ok'), reply_markup=ReplyKeyboardRemove()
        )
        return

    if context.user_data.get('search_state') == 'awaiting_location':
        loc = update.message.location
        q_text = context.user_data.pop('search_query', None)
        context.user_data.pop('search_state', None)
        remember_buyer_geo(context, loc.latitude, loc.longitude)

        if not q_text:
            await update.message.reply_text(T(update, context, 'search_cancelled'), reply_markup=ReplyKeyboardRemove())
            return

        await update.message.reply_text(
            T(update, context, 'location_received_searching', q=q_text),
            reply_markup=ReplyKeyboardRemove()
        )
        await _show_search_results(update, context, q_text,
                                   buyer_lat=loc.latitude, buyer_lon=loc.longitude)
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Kutilmagan istisno bo'lsa — log'ga yozadi va foydalanuvchini xabardor qiladi."""
    logging.error("Exception while handling update:", exc_info=context.error)

    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                T(update, context, 'error_unexpected')
            )
    except Exception:
        pass


async def reminder_order_job(context: ContextTypes.DEFAULT_TYPE):
    """5 daqiqadan keyin sotuvchiga eslatma yuboradi — buyurtma hali tasdiqlanmagan bo'lsa."""
    try:
        data = context.job.data
        order_id = data['order_id']
        seller_tg = data.get('seller_tg')

        if not seller_tg:
            return

        order = db.get_order_by_id(order_id)
        if not order or order['status'] != 'pending':
            return  # Allaqachon tasdiqlangan yoki bekor qilingan

        product_name = html.escape(data.get('product_name') or '')
        buyer_name = html.escape(data.get('buyer_name') or '')
        total = data.get('total_price', 0)
        seller = db.get_user_by_id(order['seller_id'])
        slang = get_user_lang(seller) if seller else DEFAULT_LANG

        await context.bot.send_message(
            chat_id=seller_tg,
            text=t(slang, 'job_reminder_seller',
                   pname=product_name, buyer=buyer_name, total=fmt_price(total)),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(slang, 'btn_confirm'), callback_data=f"confirm_order_{order_id}")],
                [InlineKeyboardButton(t(slang, 'btn_reject'), callback_data=f"cancel_order_{order_id}")],
            ])
        )
        logging.info(f"Reminder: buyurtma {order_id} uchun sotuvchiga eslatma yuborildi.")
    except Exception as e:
        logging.error(f"reminder_order_job xatosi: {e}")


async def auto_cancel_order_job(context: ContextTypes.DEFAULT_TYPE):
    """10 daqiqadan keyin pending buyurtmani avtomatik bekor qiladi."""
    try:
        data = context.job.data
        order_id = data['order_id']
        buyer_tg = data['buyer_tg']
        seller_tg = data.get('seller_tg')

        order = db.get_order_by_id(order_id)
        if not order or order['status'] != 'pending':
            return  # Allaqachon tasdiqlangan yoki bekor qilingan

        # Buyurtmani bekor qilamiz
        db.update_order_status(order_id, 'cancelled')
        oid = fmt_order_id(order_id)

        # Xaridorga xabar (xaridor tilida)
        try:
            buyer = db.get_user_by_id(order['buyer_id'])
            await context.bot.send_message(
                chat_id=buyer_tg,
                text=t(buyer or 'uz', 'job_autocancel_buyer', oid=oid),
                parse_mode='HTML'
            )
        except Exception:
            pass

        # Sotuvchiga xabar (sotuvchi tilida)
        if seller_tg:
            try:
                seller = db.get_user_by_id(order['seller_id'])
                await context.bot.send_message(
                    chat_id=seller_tg,
                    text=t(seller or 'uz', 'job_autocancel_seller', oid=oid),
                    parse_mode='HTML'
                )
            except Exception:
                pass

        logging.info(f"Auto-cancel: buyurtma {order_id} 10 daqiqadan keyin bekor qilindi.")
    except Exception as e:
        logging.error(f"auto_cancel_order_job xatosi: {e}")


async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni avtomatik DB backup — adminga fayl sifatida yuboradi."""
    try:
        import datetime as dt

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"marketplace_backup_{ts}.db"

        ok = db.backup(backup_path)
        if not ok:
            logging.error("Avtomatik backup muvaffaqiyatsiz.")
            return

        # Fayl hajmini tekshiramiz
        file_size = os.path.getsize(backup_path)
        size_mb = file_size / (1024 * 1024)

        try:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=open(backup_path, 'rb'),
                filename=backup_path,
                caption=(
                    f"💾 <b>Avtomatik kunlik backup</b>\n\n"
                    f"📅 Sana: {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"📦 Hajmi: {size_mb:.2f} MB"
                ),
                parse_mode='HTML'
            )
            logging.info(f"Avtomatik backup muvaffaqiyatli yuborildi: {backup_path} ({size_mb:.2f} MB)")
        except Exception as e:
            logging.error(f"Backup faylini adminga yuborib bo'lmadi: {e}")
        finally:
            try:
                os.remove(backup_path)
            except Exception:
                pass

    except Exception as e:
        logging.error(f"auto_backup_job xatosi: {e}")


async def cleanup_stale_orders_job(context: ContextTypes.DEFAULT_TYPE):
    """Kuniga bir marta — 3 kun ichida tasdiqlanmagan buyurtmalarni bekor qiladi
    va ikkala tomonga xabar yuboradi."""
    try:
        stale = db.auto_cancel_stale_orders(days=3)
        logging.info(f"Auto-cancel: {len(stale)} ta eski pending buyurtma bekor qilindi.")

        for s in stale:
            try:
                order = db.get_order_by_id(s['id'])
                if not order:
                    continue
                oid = fmt_order_id(s['id'])
                if order.get('buyer_tg'):
                    try:
                        buyer = db.get_user_by_id(order['buyer_id'])
                        await context.bot.send_message(
                            chat_id=order['buyer_tg'],
                            text=t(buyer or 'uz', 'stale_cancel_notify', oid=oid))
                    except Exception:
                        pass
                if order.get('seller_tg'):
                    try:
                        seller = db.get_user_by_id(order['seller_id'])
                        await context.bot.send_message(
                            chat_id=order['seller_tg'],
                            text=t(seller or 'uz', 'stale_cancel_notify', oid=oid))
                    except Exception:
                        pass
            except Exception as e:
                logging.error(f"Stale order notify failed: {e}")
    except Exception as e:
        logging.error(f"cleanup_stale_orders_job failed: {e}")


async def testpost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal ulanishini tekshirish (faqat admin).  /testpost"""
    if update.effective_user.id != ADMIN_ID:
        return
    if not CHANNEL_ID:
        await update.message.reply_text(
            "❌ CHANNEL_ID belgilanmagan.\n.env fayliga qo'shing:  CHANNEL_ID=@TezBozorUz24"
        )
        return
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="✅ TezBozor kanal ulanishi ishlayapti!"
        )
        await update.message.reply_text(f"✅ Yuborildi → {CHANNEL_ID}")
    except Exception as e:
        logging.error(f"testpost failed: {e}")
        await update.message.reply_text(
            f"❌ Xato: {e}\n\n"
            "Tekshiring: bot kanalda admin va 'Post Messages' ruxsati yoqilganmi?"
        )


# ============================================================
# MAIN — HANDLER REGISTRATION (BUG FIX ASOSIY QISMI)
# ============================================================

def main():
    # Persistence — bot qayta ishga tushganda foydalanuvchi sessiyalari saqlanadi
    # (yarim qolgan ro'yxatdan o'tish, qidiruv state, va h.k.)
    persistence = PicklePersistence(filepath="tezbozor_state.pickle")
    app = Application.builder().token(TOKEN).persistence(persistence).build()

    # BUG FIX #5: global_fallbacks — jarayon ichida /start, /cancel yoki pastki menyu bosilsa to'xtatadi
    async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Har qanday conversation'ni to'xtatib, foydalanuvchini bosh sahifaga qaytaradi."""
        # Conversation state'larini tozalaymiz
        for key in ['adding_product', 'searching', 'search_state', 'search_query',
                    'broadcasting', 'setting_stock_for', 'attr_templates', 'attr_index',
                    'product_attrs', 'order_product', 'order_qty', 'shop_search_state',
                    '_shop_results']:
            context.user_data.pop(key, None)

        user = db.get_user_by_telegram_id(update.effective_user.id)
        if update.message:
            await update.message.reply_text(T(update, context, 'cancelled'))
        if user:
            if user['role'] == 'admin':
                await admin_panel(update, context)
            elif get_active_mode(user, context) == 'seller':
                await seller_panel(update, context)
            else:
                await buyer_panel(update, context)
        return ConversationHandler.END

    # Pastki menyu tugmalari (uz+ru) — conversation ichida bosilsa bekor qiladi
    BOTTOM_MENU_TEXTS = all_bottom_menu_texts()

    cancel_filter = filters.Regex(
        "^(" + "|".join(_re.escape(_btn) for _btn in BOTTOM_MENU_TEXTS) + ")$"
    )

    global_fallbacks = [
        CommandHandler("start", start),
        CommandHandler("cancel", cancel_conversation),
        CommandHandler("admin", admin_command),
        MessageHandler(cancel_filter, cancel_conversation),
        CallbackQueryHandler(button_handler),
    ]

    # --- Registration ConversationHandler ---
    registration_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_LANG:       [CallbackQueryHandler(registration_language, pattern="^reglang_")],
            PHONE:             [MessageHandler(filters.CONTACT | filters.TEXT & ~filters.COMMAND, registration_phone)],
            NAME:              [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_name)],
            ROLE:              [CallbackQueryHandler(registration_role, pattern="^reg_")],
            SELLER_CATEGORY:   [CallbackQueryHandler(registration_seller_category, pattern="^regcat_")],
            SHOP_NAME:         [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_shop_name)],
            SHOP_LANDMARK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_shop_landmark)],
            SHOP_ADDRESS:      [MessageHandler(filters.LOCATION | filters.TEXT & ~filters.COMMAND, registration_shop_address)],
            WORKING_DAYS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_working_days)],
            WORKING_HOURS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_working_hours)],
            TELEGRAM_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_telegram_username)],
        },
        fallbacks=global_fallbacks,
        allow_reentry=True,
        conversation_timeout=300,  # 5 daqiqadan keyin conversation avtomatik tugaydi
    )

    # --- Product add ConversationHandler ---
    _add_product_btn_re = "^(" + "|".join(_re.escape(s) for s in _lang_labels('btn_add_product')) + ")$"
    product_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(seller_add_product_start, pattern="^seller_add_product$"),
            MessageHandler(filters.Regex(_add_product_btn_re), seller_add_product_start),
        ],
        states={
            PRODUCT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, seller_add_product_name)],
            PRODUCT_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, seller_add_product_price)],
            PRODUCT_CATEGORY: [CallbackQueryHandler(seller_add_product_category, pattern="^prodcat_")],
            PRODUCT_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, seller_add_product_desc)],
            PRODUCT_PHOTO:    [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.Sticker.ALL | (filters.TEXT & ~filters.COMMAND), seller_add_product_photo),
                CallbackQueryHandler(add_photo_more, pattern="^addphoto_more$"),
                CallbackQueryHandler(add_photo_done, pattern="^addphoto_done$"),
            ],
            PRODUCT_ATTRS:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, seller_add_product_attr_text),
                CallbackQueryHandler(seller_add_product_attr_callback, pattern="^attr_"),
            ],
        },
        fallbacks=global_fallbacks,
    )

    # --- Product edit ConversationHandler (yangi: maydon tanlash usuli) ---
    # 'edit_start_' (tahrir oynasini ochish) button_handler orqali ishlaydi.
    # Bu conversation faqat aniq bir maydon tanlangach boshlanadi.
    edit_product_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_field_name_start,   pattern=r"^ef_name_\d+$"),
            CallbackQueryHandler(edit_field_price_start,  pattern=r"^ef_price_\d+$"),
            CallbackQueryHandler(edit_field_cat_start,    pattern=r"^ef_cat_\d+$"),
            CallbackQueryHandler(edit_field_desc_start,   pattern=r"^ef_desc_\d+$"),
            CallbackQueryHandler(edit_field_photos_start, pattern=r"^ef_photos_\d+$"),
            CallbackQueryHandler(edit_attr_start,         pattern=r"^ea_\d+_"),
        ],
        states={
            EDIT_FIELD_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_name_save)],
            EDIT_FIELD_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_price_save)],
            EDIT_FIELD_CATEGORY: [CallbackQueryHandler(edit_field_cat_save, pattern=r"^ecat_")],
            EDIT_FIELD_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_desc_save)],
            EDIT_FIELD_PHOTOS:   [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.Sticker.ALL | (filters.TEXT & ~filters.COMMAND), edit_field_photos_collect),
                CallbackQueryHandler(edit_photos_more, pattern="^eph_more$"),
                CallbackQueryHandler(edit_photos_done, pattern="^eph_done$"),
            ],
            EDIT_FIELD_ATTR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_attr_save)],
        },
        fallbacks=global_fallbacks,
    )

    # --- Buyer profile edit ---
    buyer_profile_edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_buyer_name_start, pattern="^edit_buyer_name$"),
            CallbackQueryHandler(edit_buyer_phone_start, pattern="^edit_buyer_phone$"),
        ],
        states={
            EDIT_PROFILE_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_buyer_name_submit)],
            EDIT_PROFILE_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT & ~filters.COMMAND, edit_buyer_phone_submit)],
        },
        fallbacks=global_fallbacks,
    )

    # --- Seller profile edit ---
    # BUG FIX #6: pattern regex to'g'irlandi — "edit_telegram" ham ushlanadi
    seller_profile_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            edit_seller_field_start,
            pattern="^(edit_shop_name|edit_shop_address|edit_shop_landmark|edit_working_days|edit_working_hours|edit_telegram)$"
        )],
        states={
            EDIT_SHOP_NAME:         [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
            EDIT_SHOP_ADDRESS:      [MessageHandler(filters.LOCATION | filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
            EDIT_SHOP_LANDMARK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
            EDIT_WORKING_DAYS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
            EDIT_WORKING_HOURS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
            EDIT_TELEGRAM_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_seller_field_submit)],
        },
        fallbacks=global_fallbacks,
    )

    # --- Messaging ---
    message_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(message_start, pattern="^order_msg_")],
        states={
            MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_send)],
        },
        fallbacks=global_fallbacks,
    )

    # --- Rating (3 qadam: mahsulot reytingi -> mahsulot izohi -> do'kon reytingi) ---
    rating_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rating_start, pattern="^order_rate_")],
        states={
            PRODUCT_RATING:  [CallbackQueryHandler(rating_product_select, pattern="^prate_")],
            PRODUCT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_product_comment)],
            SELLER_RATING:   [CallbackQueryHandler(rating_submit, pattern="^srate_")],
        },
        fallbacks=global_fallbacks,
    )

    # /admin va /recommend — conversation boshlamaydigan alohida buyruqlar
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("recommend", recommend_command))
    app.add_handler(CommandHandler("ai", ai_command))

    # --- Become seller (mavjud xaridorni sotuvchi qilish) ---
    # Ro'yxatdan o'tish handlerlarini qayta ishlatamiz — ular faqat context.user_data ga yozadi,
    # DB ga yozuv esa oxirgi qadamda (become_seller_finish) bo'ladi.
    become_seller_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(become_seller_start, pattern="^become_seller$")],
        states={
            SHOP_NAME:         [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_shop_name)],
            SHOP_LANDMARK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_shop_landmark)],
            SHOP_ADDRESS:      [MessageHandler(filters.LOCATION | filters.TEXT & ~filters.COMMAND, registration_shop_address)],
            WORKING_DAYS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_working_days)],
            WORKING_HOURS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_working_hours)],
            TELEGRAM_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, become_seller_finish)],
        },
        fallbacks=global_fallbacks,
    )

    # --- Buyurtma berish (Order Flow) ---
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(order_start, pattern=r"^order_\d+$")],
        states={
            ORDER_QUANTITY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, order_quantity)],
            ORDER_DELIVERY_TYPE: [CallbackQueryHandler(order_delivery_type, pattern=r"^ord_dlv_|^ord_cancel$")],
            ORDER_ADDRESS:       [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), order_address)],
            ORDER_PAYMENT:       [CallbackQueryHandler(order_payment, pattern=r"^ord_pay_|^ord_cancel$")],
            ORDER_CONFIRM:       [CallbackQueryHandler(order_confirm, pattern=r"^ord_confirm_yes$|^ord_cancel$")],
        },
        fallbacks=global_fallbacks,
    )

    # ConversationHandler'lar — /start ichida boshlanadi
    app.add_handler(registration_conv)
    app.add_handler(become_seller_conv)
    app.add_handler(order_conv)
    app.add_handler(product_conv)
    app.add_handler(edit_product_conv)
    app.add_handler(buyer_profile_edit_conv)
    app.add_handler(seller_profile_edit_conv)
    app.add_handler(message_conv)
    app.add_handler(rating_conv)

    # --- Karta ma'lumotlari tahrirlash ---
    card_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_card_start, pattern="^edit_card_info$")],
        states={
            EDIT_CARD_TYPE:   [CallbackQueryHandler(edit_card_type,   pattern="^card_type_")],
            EDIT_CARD_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_card_number)],
            EDIT_CARD_OWNER:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_card_owner)],
        },
        fallbacks=global_fallbacks,
    )
    app.add_handler(card_conv)

    # --- Admin bilan bog'lanish ---
    contact_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(contact_admin_start, pattern="^contact_admin$")],
        states={
            CONTACT_ADMIN_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_admin_send)],
        },
        fallbacks=global_fallbacks,
    )
    app.add_handler(contact_admin_conv)

    # --- Sotuvchi kanalini ulash (forward orqali) ---
    link_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(seller_link_channel_start, pattern="^seller_link_channel$")],
        states={
            LINK_CHANNEL_WAIT: [
                MessageHandler(filters.FORWARDED, link_channel_receive),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, link_channel_wait_hint),
            ],
        },
        fallbacks=global_fallbacks,
    )
    app.add_handler(link_channel_conv)

    # Sotuvchi kanallari menyusi + kanalni o'chirish
    app.add_handler(CallbackQueryHandler(seller_channels_menu, pattern="^seller_channels_menu$"))
    app.add_handler(CallbackQueryHandler(seller_channel_remove, pattern="^chremove_"))

    # Admin mahsulot moderatsiyasi (detal, qidiruv, sotuvdan olib tashlash, rasm)
    app.add_handler(CallbackQueryHandler(admin_products, pattern=r"^admin_products(_pg_\d+)?$"))
    app.add_handler(CallbackQueryHandler(admin_product_search, pattern=r"^admin_product_search$"))
    app.add_handler(CallbackQueryHandler(admin_product_detail, pattern=r"^admin_prod_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_product_remove, pattern=r"^admin_prodrm_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_product_restore, pattern=r"^admin_prodrs_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_product_image, pattern=r"^admin_prodimg_\d+$"))

    # Admin javob komandasi: /reply 123456789 matn
    app.add_handler(CommandHandler("reply", admin_reply_command))

    # Kanal ulanishini tekshirish (faqat admin): /testpost
    app.add_handler(CommandHandler("testpost", testpost))

    # --- Sotuvchi mahsulot qidirish ---
    sp_search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(seller_product_search_start, pattern="^sp_search$")],
        states={
            SELLER_PRODUCT_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_product_search_result)],
        },
        fallbacks=global_fallbacks,
    )
    app.add_handler(sp_search_conv)

    # --- Savatni rasmiylashtirish (savat buyurtmasi) ---
    cart_checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cart_checkout_start, pattern="^cart_checkout$")],
        states={
            CART_DELIVERY_TYPE: [CallbackQueryHandler(cart_delivery_type, pattern=r"^cart_dlv_|^cart_cancel$")],
            CART_ADDRESS:       [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), cart_address)],
            CART_PAYMENT:       [CallbackQueryHandler(cart_payment, pattern=r"^cart_pay_|^cart_cancel$")],
            CART_CONFIRM:       [CallbackQueryHandler(cart_confirm, pattern=r"^cart_confirm_yes$|^cart_cancel$")],
        },
        fallbacks=global_fallbacks,
    )
    app.add_handler(cart_checkout_conv)

    # Umumiy handler'lar ENG OXIRIDA
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    # AI rejimida mahsulot rasmlarini yig'ish (faqat 'ai_awaiting_photos' yoqilganda ishlaydi)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, ai_photo_collect))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Global xato ushlovchi — kutilmagan exception bo'lsa, foydalanuvchini xabardor qiladi
    app.add_error_handler(error_handler)

    # Kunlik ishlaydigan job — eski 'pending' buyurtmalarni avtomatik bekor qilish.
    # Bot ishga tushgandan 60 soniyadan keyin birinchi marta, keyin har 24 soatda.
    if app.job_queue:
        app.job_queue.run_repeating(cleanup_stale_orders_job, interval=86400, first=60)
        logging.info("Stale orders cleanup job rejalashtirildi (har 24 soatda)")

        # Avtomatik backup — har kuni ertalab 06:00 (UTC) = 11:00 Toshkent
        from datetime import time as dt_time
        app.job_queue.run_daily(
            auto_backup_job,
            time=dt_time(hour=6, minute=0),
            name="daily_backup"
        )
        logging.info("Avtomatik backup job rejalashtirildi (har kuni 11:00 Toshkent)")

    print("🚀 TezBozor Bot ishlamoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()