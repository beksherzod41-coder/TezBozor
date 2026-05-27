import logging
import math
import html
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler, PicklePersistence
from database import Database
from tezbozor_design import (fmt_price, fmt_phone, fmt_order_id, fmt_status, fmt_rating,
                             fmt_datetime, is_shop_open_now, M)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "722266370"))

logging.basicConfig(level=logging.INFO)

db = Database()


def haversine_km(lat1, lon1, lat2, lon2):
    """Ikki nuqta orasidagi masofa (km)"""
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


import time as _time

def rate_limit(min_interval: float = 1.0):
    """Decorator: foydalanuvchi min_interval soniyadan tez-tez so'rov yuborsa, bloklanadi.
    Faqat CallbackQuery va Message handler'larda ishlaydi."""
    def decorator(func):
        import functools
        @functools.wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                key = f'_rl_{func.__name__}'
                last = context.user_data.get(key, 0)
                now = _time.monotonic()
                if now - last < min_interval:
                    # Telegram'ga "loading" ko'rinmasligi uchun callback_query'ga javob beramiz
                    if update.callback_query:
                        try:
                            await update.callback_query.answer("⏳ Biroz kuting...")
                        except Exception:
                            pass
                    return
                context.user_data[key] = now
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


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

# ============================================================
# CONVERSATION STATES
# Har bir ConversationHandler o'z alohida state raqamlarini ishlatishi kerak
# Aks holda state'lar bir-birini ustidan yozib ketadi (BUG FIX #1)
# ============================================================
(PHONE, NAME, ROLE, SELLER_CATEGORY, SHOP_NAME, SHOP_LANDMARK,
 SHOP_ADDRESS, WORKING_DAYS, WORKING_HOURS, TELEGRAM_USERNAME) = range(10)

(PRODUCT_NAME, PRODUCT_PRICE, PRODUCT_CATEGORY, PRODUCT_DESC, PRODUCT_PHOTO, PRODUCT_ATTRS) = range(10, 16)

(EDIT_PRODUCT_NAME, EDIT_PRODUCT_PRICE, EDIT_PRODUCT_CATEGORY, EDIT_PRODUCT_DESC, EDIT_PRODUCT_PHOTO) = range(20, 25)

(ORDER_QUANTITY, ORDER_DELIVERY_TYPE, ORDER_ADDRESS, ORDER_PAYMENT, ORDER_CONFIRM) = range(30, 35)

MESSAGE_TEXT = 40

(RATING, REVIEW_COMMENT) = range(50, 52)

(EDIT_PROFILE_NAME, EDIT_PROFILE_PHONE,
 EDIT_SHOP_NAME, EDIT_SHOP_LANDMARK, EDIT_SHOP_ADDRESS,
 EDIT_WORKING_DAYS, EDIT_WORKING_HOURS, EDIT_TELEGRAM_USERNAME) = range(60, 68)

(EDIT_CARD_TYPE, EDIT_CARD_NUMBER, EDIT_CARD_OWNER) = range(70, 73)


# ============================================================
# START & REGISTRATION
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Referral kod tekshiruvi — faqat yangi foydalanuvchi uchun
    # /start REF12345 ko'rinishida kelishi mumkin (context.args ichida)
    if not user and context.args:
        ref_code = context.args[0].strip()
        referrer = db.get_user_by_referral_code(ref_code)
        if referrer:
            context.user_data['referred_by'] = referrer['id']
            logging.info(f"New user referred by {referrer['name']} (code={ref_code})")

    if user and user['role'] != 'admin' and update.effective_user.id == ADMIN_ID:
        db.update_user(user['id'], role='admin')
        user['role'] = 'admin'
        await update.message.reply_text("✅ Siz admin bo'ldingiz!")

    if user:
        if user['is_blocked']:
            await update.message.reply_text("⛔ Siz bloklangansiz. Admin bilan bog'laning.")
            return ConversationHandler.END

        # Avvalgi conversation state'ni tozalaymiz
        context.user_data.clear()

        if user['role'] == 'admin':
            await admin_panel(update, context)
        elif user['role'] == 'seller':
            await seller_panel(update, context)
        else:
            await buyer_panel(update, context)
        return ConversationHandler.END
    else:
        return await registration_start(update, context)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    if not user:
        await update.message.reply_text("Iltimos, avval ro'yxatdan o'ting: /start")
        return ConversationHandler.END

    if user['role'] != 'admin' and update.effective_user.id == ADMIN_ID:
        db.update_user(user['id'], role='admin')
        user['role'] = 'admin'

    if user['role'] != 'admin':
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return ConversationHandler.END

    # Conversation state'ni tozalaymiz — /admin dan keyin bot ro'yxat jarayonida qolmasin
    context.user_data.clear()

    await admin_panel(update, context)
    return ConversationHandler.END


async def registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "👋 TezBozorga xush kelibsiz!\n\n"
        "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring:",
        reply_markup=reply_markup
    )
    return PHONE


async def registration_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        raw = update.message.contact.phone_number
    elif update.message.text:
        raw = update.message.text
    else:
        await update.message.reply_text("Iltimos, telefon raqamingizni yuboring:")
        return PHONE

    phone = normalize_phone(raw)
    if not phone:
        await update.message.reply_text(
            "❌ Telefon raqami noto'g'ri.\nMisol: +998901234567 yoki tugmadan foydalaning."
        )
        return PHONE

    context.user_data['phone'] = phone
    logging.info(f"Phone normalized: {phone}")

    await update.message.reply_text(
        "To'liq F.I.SH (Familiya, Ism, Sharifingiz) kiriting:",
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME


async def registration_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = normalize_name(update.message.text, min_len=2, max_len=60)
    if not name:
        await update.message.reply_text("❌ Ism 2-60 belgi bo'lishi kerak. Qaytadan kiriting:")
        return NAME

    context.user_data['name'] = name

    keyboard = [
        [InlineKeyboardButton("🛒 Xaridor", callback_data="reg_buyer")],
        [InlineKeyboardButton("🏪 Sotuvchi", callback_data="reg_seller")],
    ]
    await update.message.reply_text(
        f"Rahmat, {name}!\n\nO'zingizga rol tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ROLE


async def registration_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    role = query.data.split("_")[1]  # "reg_buyer" -> "buyer"
    context.user_data['role'] = role

    if role == 'seller':
        categories = db.get_all_categories()
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"regcat_{cat[0]}")])

        await query.edit_message_text(
            "Qaysi bo'lim uchun sotuvchi bo'lmoqchisiz?",
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
        await query.edit_message_text(
            "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nTezBozorga xush kelibsiz!"
        )
        await buyer_panel(update, context)
        return ConversationHandler.END


async def registration_seller_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    context.user_data['seller_category'] = category_id

    await query.edit_message_text("Do'kon nomingizni kiriting:")
    return SHOP_NAME


async def registration_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 80:
        await update.message.reply_text("❌ Do'kon nomi 2-80 belgi bo'lishi kerak. Qaytadan kiriting:")
        return SHOP_NAME
    context.user_data['shop_name'] = name
    await update.message.reply_text("Mo'ljal (yaqin joy, orientir) kiriting:")
    return SHOP_LANDMARK


async def registration_shop_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    landmark = update.message.text.strip()
    if len(landmark) > 200:
        await update.message.reply_text("❌ Mo'ljal juda uzun (maks. 200 belgi):")
        return SHOP_LANDMARK
    context.user_data['shop_landmark'] = landmark

    keyboard = [[KeyboardButton("📍 Manzilni yuborish", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Do'kon manzilingizni yuboring (lokatsiya yoki matn):",
        reply_markup=reply_markup
    )
    return SHOP_ADDRESS


async def registration_shop_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        address = f"{lat}, {lon}"
    else:
        address = update.message.text.strip()
        if len(address) < 5 or len(address) > 200:
            await update.message.reply_text("❌ Manzil 5-200 belgi bo'lishi kerak. Qaytadan:")
            return SHOP_ADDRESS
        lat, lon = None, None

    context.user_data['shop_address'] = address
    context.user_data['shop_lat'] = lat
    context.user_data['shop_lon'] = lon

    await update.message.reply_text(
        "Ish kunlari kiriting (masalan: Dush-Shan, Chor-Juma):",
        reply_markup=ReplyKeyboardRemove()
    )
    return WORKING_DAYS


async def registration_working_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = update.message.text.strip()
    if len(days) > 100:
        await update.message.reply_text("❌ Juda uzun. Qisqaroq yozing (maks. 100 belgi):")
        return WORKING_DAYS
    context.user_data['working_days'] = days
    await update.message.reply_text("Ish vaqti kiriting (masalan: 09:00-21:00):")
    return WORKING_HOURS


async def registration_working_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hours = update.message.text.strip()
    # Vaqtni qattiq validatsiya qilmaymiz (turli formatlar bo'lishi mumkin: "09-21", "9:00 dan 21:00 gacha")
    # Lekin parse qilib ko'ramiz, agar formatga to'g'ri kelsa — keyinchalik ish vaqti tekshiruvi uchun ishlatamiz.
    if len(hours) > 50:
        await update.message.reply_text("❌ Juda uzun. Qisqaroq yozing (maks. 50 belgi):")
        return WORKING_HOURS
    context.user_data['working_hours'] = hours
    await update.message.reply_text(
        "Telegram usernameingiz kiriting (@ bilan, masalan: @username):\n"
        "Agar yo'q bo'lsa — '-' yozing."
    )
    return TELEGRAM_USERNAME


async def registration_telegram_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    if raw == '-' or raw.lower() in ('yoq', "yo'q", "yoʼq", 'no', 'none'):
        context.user_data['telegram_username'] = None
    else:
        u = normalize_telegram_username(raw)
        if not u:
            await update.message.reply_text(
                "❌ Username noto'g'ri.\n"
                "Lotin harfi bilan boshlanishi va 5-32 belgi bo'lishi kerak (a-z, 0-9, _).\n"
                "Misol: @ali_2024\nYoki '-' yozing:"
            )
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

    # Referral — agar /start REF... orqali kelgan bo'lsa
    referred_by = context.user_data.get('referred_by')
    if referred_by:
        try:
            db.update_user(user_id, referred_by=referred_by)
            db.increment_referral_count(referred_by)
            # Taklif qiluvchiga bildirishnoma
            referrer = db.get_user_by_id(referred_by)
            if referrer and referrer.get('telegram_id'):
                try:
                    await context.bot.send_message(
                        chat_id=referrer['telegram_id'],
                        text=f"🎉 Yangi taklif! <b>{html.escape(context.user_data['name'])}</b> "
                             f"sizning havolangiz orqali ro'yxatdan o'tdi.",
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

    await update.message.reply_text(
        "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nTezBozorga xush kelibsiz!"
    )

    if role == 'seller':
        await seller_panel(update, context)
    elif role == 'admin':
        await admin_panel(update, context)
    else:
        await buyer_panel(update, context)

    return ConversationHandler.END


# ============================================================
# ROL ALMASHTIRISH (Xaridor ↔ Sotuvchi)
# Bitta akkaunt — ikkala rejim. role ustuni asosiy rolni saqlaydi,
# active_mode esa hozir qaysi panel ko'rsatilayotganini belgilaydi.
# ============================================================

async def switch_to_buyer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['active_mode'] = 'buyer'
    await buyer_panel(update, context)
    # Pastki menyuni ham xaridor variantiga o'tkazamiz
    bottom_keyboard = [
        [KeyboardButton("🔍 Qidirish"), KeyboardButton("📦 Kategoriyalar")],
        [KeyboardButton("🛒 Buyurtmalarim"), KeyboardButton("👤 Profil")],
        [KeyboardButton("🏠 Bosh sahifa")],
    ]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🛒 Xaridor rejimida.",
        reply_markup=ReplyKeyboardMarkup(bottom_keyboard, resize_keyboard=True)
    )


async def switch_to_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_by_telegram_id(update.effective_user.id)

    if is_seller_capable(user):
        # Do'kon ma'lumotlari bor — to'g'ridan-to'g'ri sotuvchi paneliga
        context.user_data['active_mode'] = 'seller'
        await seller_panel(update, context)
        bottom_keyboard = [
            [KeyboardButton("➕ Mahsulot qo'shish"), KeyboardButton("📦 Mahsulotlarim")],
            [KeyboardButton("🛒 Buyurtmalar"), KeyboardButton("👤 Profil")],
            [KeyboardButton("🏠 Bosh sahifa")],
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🏪 Sotuvchi rejimida.",
            reply_markup=ReplyKeyboardMarkup(bottom_keyboard, resize_keyboard=True)
        )
        return

    # Do'kon yo'q — sotuvchi bo'lishni taklif qilamiz
    kb = [
        [InlineKeyboardButton("✅ Ha, sotuvchi bo'laman", callback_data="become_seller")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="buyer_panel")],
    ]
    await query.edit_message_text(
        "🏪 Sotuvchi rejimiga o'tish uchun avval do'kon ma'lumotlarini kiritishingiz kerak "
        "(do'kon nomi, manzili, ish vaqti).\n\nBoshlaymizmi?",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def become_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Sotuvchi bo'lish' jarayonini boshlaydi — mavjud akkauntga do'kon ma'lumotlari qo'shamiz."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏪 Sotuvchi bo'lish jarayoni boshlandi.\n\nDo'kon nomini kiriting:"
    )
    return SHOP_NAME


async def become_seller_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jarayonning so'nggi qadami — telegram username va DB ga yozish."""
    context.user_data['telegram_username'] = update.message.text.strip()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(
        user['id'],
        role='seller',  # asosiy rol endi sotuvchi (xaridor rejimi har doim ochiq)
        shop_name=context.user_data.get('shop_name'),
        shop_address=context.user_data.get('shop_address'),
        shop_landmark=context.user_data.get('shop_landmark'),
        shop_lat=context.user_data.get('shop_lat'),
        shop_lon=context.user_data.get('shop_lon'),
        working_days=context.user_data.get('working_days'),
        working_hours=context.user_data.get('working_hours'),
        telegram_username=context.user_data.get('telegram_username'),
        is_verified=1,
    )

    await update.message.reply_text(
        "✅ Tabriklaymiz! Endi siz sotuvchi sifatida ham ishlay olasiz.\n"
        "Xaridor rejimiga istalgan vaqtda qaytib o'ta olasiz."
    )
    context.user_data['active_mode'] = 'seller'
    await seller_panel(update, context)
    return ConversationHandler.END


# ============================================================
# BUYER PANEL
# ============================================================

async def buyer_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    context.user_data['active_mode'] = 'buyer'

    # Sotuvchi rejimi tugmasi: agar do'koni bo'lsa — to'g'ri rejimga o'tadi;
    # bo'lmasa — "sotuvchi bo'lish" jarayonini boshlaydi
    seller_btn_label = "🏪 Sotuvchi rejimi" if is_seller_capable(user) else "🏪 Sotuvchi bo'lish"

    keyboard = [
        [InlineKeyboardButton("🔍 Qidirish", callback_data="buyer_search")],
        [InlineKeyboardButton("📦 Kategoriyalar", callback_data="buyer_categories")],
        [InlineKeyboardButton("🛒 Buyurtmalarim", callback_data="buyer_orders")],
        [InlineKeyboardButton("💬 Xabarlar", callback_data="buyer_messages")],
        [InlineKeyboardButton("⭐ Reytinglarim", callback_data="buyer_reviews")],
        [InlineKeyboardButton("👤 Profil", callback_data="buyer_profile")],
        [InlineKeyboardButton(seller_btn_label, callback_data="switch_to_seller")],
    ]

    text = "🛒 Xaridor paneli\n\nTanlang:"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        bottom_keyboard = [
            [KeyboardButton("🔍 Qidirish"), KeyboardButton("📦 Kategoriyalar")],
            [KeyboardButton("🛒 Buyurtmalarim"), KeyboardButton("👤 Profil")],
            [KeyboardButton("🏠 Bosh sahifa")],
        ]
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await update.message.reply_text(
            "Quyidagi tugmalardan ham foydalanishingiz mumkin:",
            reply_markup=ReplyKeyboardMarkup(bottom_keyboard, resize_keyboard=True)
        )


async def buyer_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    categories = db.get_all_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"cat_{cat[0]}")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")])

    if query:
        await query.answer()
        await query.edit_message_text("📦 Kategoriyalar:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("📦 Kategoriyalar:", reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_category_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # callback_data: 'cat_ID' yoki 'cat_ID_pg_N'
    parts = query.data.split("_")
    category_id = int(parts[1])
    page = int(parts[3]) if len(parts) >= 4 and parts[2] == 'pg' else 0

    products = db.search_products(category_id=category_id)

    if not products:
        await query.edit_message_text(
            "Bu kategoriyada mahsulotlar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")]])
        )
        return

    total = len(products)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    keyboard = []
    for product in products[start:end]:
        rating = product.get('avg_rating') or 0
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
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")])

    await query.edit_message_text(
        f"📦 Mahsulotlar — jami {total} ta. Sahifa {page+1}/{total_pages}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buyer_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])

    product = db.get_product_by_id(product_id)

    if not product:
        await query.edit_message_text("Mahsulot topilmadi.")
        return

    # Ko'rish tarixini yangilaymiz
    _track_viewed(context, product_id, product.get('category_id'))

    rating = product['avg_rating'] or 0

    map_link = ""
    if product.get('shop_lat') and product.get('shop_lon'):
        map_link = f"\n🗺️ <a href=\"https://www.google.com/maps/search/?api=1&query={product['shop_lat']},{product['shop_lon']}\">Xaritada ko'rish</a>"

    keyboard = [
        [InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order_{product_id}")],
        [InlineKeyboardButton("💬 Xabar yuborish", callback_data=f"msg_{product_id}")],
    ]
    if product.get('telegram_username'):
        keyboard.append([InlineKeyboardButton(
            f"📱 Telegram: {product['telegram_username']}",
            url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
        )])
    if product.get('phone_number'):
        keyboard.append([InlineKeyboardButton(
            f"📞 Telefon: {product['phone_number']}",
            callback_data=f"call_{product['id']}"
        )])

    # Recommendation tugmasi — agar tarix bo'lsa
    history = context.user_data.get('_view_history', [])
    if len(history) >= 2:  # kamida 2 ta ko'rilgan bo'lsa
        keyboard.append([InlineKeyboardButton(
            "✨ Sizga mos boshqa tovarlar",
            callback_data=f"recommend_{product_id}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")])

    # HTML rejimi — foydalanuvchi matnida `*`, `_`, `[` bo'lsa ham crash bo'lmaydi
    name = html.escape(product['name'] or '')
    shop_name = html.escape(product.get('shop_name') or 'Nomaʼlum')
    shop_address = html.escape(product.get('shop_address') or "Koʼrsatilmagan")
    shop_landmark = html.escape(product.get('shop_landmark') or "Koʼrsatilmagan")
    working_hours = html.escape(product.get('working_hours') or "Koʼrsatilmagan")
    working_days = html.escape(product.get('working_days') or "Koʼrsatilmagan")
    desc = html.escape(product.get('description') or "Yo'q")

    # Hozir ochiq/yopiqmi (faqat working_hours parse qilinsa)
    open_status = is_shop_open_now(product.get('working_hours'))
    if open_status is True:
        open_line = "🟢 Hozir ochiq"
    elif open_status is False:
        open_line = "🔴 Hozir yopiq"
    else:
        open_line = ""

    stock_line = ""
    if product.get('stock_count') is not None:
        stock_line = f"\n📦 Zahirada: {product['stock_count']} dona"

    # Dinamik atributlar
    attrs = db.get_product_attributes(product['id'])
    attrs_text = ""
    if attrs:
        lines = []
        for a in attrs:
            label = a.get('attr_label') or a['attr_key']
            lines.append(f"• {label}: {a['attr_value']}")
        attrs_text = "\n\n🏷 <b>Xususiyatlar:</b>\n" + "\n".join(lines)

    text = (
        f"📦 <b>{name}</b>\n\n"
        f"💰 Narxi: <b>{fmt_price(product['price'])}</b>{stock_line}\n"
        f"🏪 Do'kon: {shop_name}\n"
        f"📍 Manzil: {shop_address}\n"
        f"🎯 Moʼljal: {shop_landmark}{map_link}\n"
        f"⭐ Reyting: {rating:.1f}/5.0\n"
        f"🕐 Ish vaqti: {working_hours}"
    )
    if open_line:
        text += f"  {open_line}"
    text += (
        f"\n📅 Ish kunlari: {working_days}\n"
        f"📝 Tavsif: {desc}"
        f"{attrs_text}"
    )

    # Agar rasm bo'lsa — alohida xabar bilan yuboramiz, keyin batafsil ma'lumotni
    # (edit_message_text rasm bilan ishlamaydi, shuning uchun eski xabarni o'chiramiz va yangisini yuboramiz)
    if product.get('image_url'):
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=product['image_url'],
            caption=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )


async def skip_search_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Lokatsiyasiz qidirish' tugmasi — lokatsiyasiz natijalarni ko'rsatadi (pagination bilan)."""
    query = update.callback_query
    await query.answer()

    q_text = context.user_data.pop('search_query', None)
    context.user_data.pop('search_state', None)

    if not q_text:
        await query.edit_message_text("Qidiruv bekor qilindi.")
        return

    await query.edit_message_text(f"🔍 '{q_text}' bo'yicha qidirilmoqda...")
    region_id = context.user_data.get('search_region_id')
    products = db.search_products(query=q_text, region_id=region_id)
    await _render_search_page(update.effective_chat.id, context, products,
                              page=0, sort_by='rating', query_text=q_text,
                              buyer_lat=None)


PAGE_SIZE = 10  # sahifadagi mahsulotlar soni
HISTORY_LIMIT = 20  # ko'rilgan mahsulotlar tarixi


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
    total = len(products)
    if total == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ '{query_text}' bo'yicha hech narsa topilmadi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])
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
        rating = product.get('avg_rating') or 0
        map_link = ""
        if product.get('shop_lat') and product.get('shop_lon'):
            map_link = (f"\n🗺️ <a href=\"https://www.google.com/maps/search/?api=1&"
                        f"query={product['shop_lat']},{product['shop_lon']}\">Xaritada ko'rish</a>")

        distance_line = ""
        if product.get('_distance_km') is not None:
            distance_line = f"\n📏 Masofa: ~{product['_distance_km']:.1f} km"

        contact_keyboard = []
        if product.get('telegram_username'):
            contact_keyboard.append([InlineKeyboardButton(
                "📱 Telegram",
                url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
            )])
        if product.get('phone_number'):
            contact_keyboard.append([InlineKeyboardButton(
                "📞 Telefon", callback_data=f"call_{product['id']}"
            )])
        contact_keyboard.append([InlineKeyboardButton("📦 Batafsil", callback_data=f"prod_{product['id']}")])

        emoji = product.get('category_emoji') or '📦'
        name = html.escape(product['name'] or '')
        shop_name = html.escape(product.get('shop_name') or 'Nomaʼlum')
        shop_address = html.escape(product.get('shop_address') or 'Nomaʼlum')
        caption = (
            f"{emoji} <b>{name}</b>\n\n"
            f"💰 <b>{fmt_price(product['price'])}</b>\n"
            f"🏪 {shop_name}\n"
            f"📍 {shop_address}{map_link}{distance_line}\n"
            f"⭐ Reyting: {rating:.1f}/5.0"
        )

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
        'rating': '⭐ Reyting',
        'price_asc': '💰 Arzondan',
        'price_desc': '💰 Qimmatdan',
        'newest': '🆕 Yangi',
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
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"pg_{page+1}"))

    footer_kb = sort_kb + ([nav] if nav else []) + [
        [InlineKeyboardButton("⬅️ Bosh menyu", callback_data="buyer_panel")]
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 '{html.escape(query_text)}' bo'yicha jami {total} ta natija. "
             f"Sahifa {page+1}/{total_pages}.",
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
        await query.edit_message_text("Qidiruv natijalari yo'q. Qaytadan qidiring.")
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


async def buyer_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1-bosqich: hudud tanlash yoki o'tkazib yuborish
    context.user_data['search_state'] = 'awaiting_query'
    context.user_data.pop('search_query', None)
    context.user_data.pop('search_lat', None)
    context.user_data.pop('search_lon', None)
    context.user_data.pop('search_region_id', None)

    regions = db.get_regions(parent_id=None)
    kb_rows = []
    for r in regions:
        kb_rows.append([InlineKeyboardButton(r['name'], callback_data=f"sreg_{r['id']}")])
    kb_rows.append([InlineKeyboardButton("🌐 Barcha hududlar", callback_data="sreg_0")])

    text = "📍 Qaysi hudud bo'yicha qidirasiz?"

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

    if region_id == 0:
        # Barcha hududlar — hududsiz qidiruv
        context.user_data.pop('search_region_id', None)
        await query.edit_message_text("🔍 Mahsulot nomini kiriting:")
        return

    # Tumanlar bormi?
    districts = db.get_regions(parent_id=region_id)
    if districts:
        context.user_data['search_region_id'] = region_id
        kb_rows = []
        for d in districts:
            kb_rows.append([InlineKeyboardButton(d['name'], callback_data=f"sdist_{d['id']}")])
        region = db.get_region_by_id(region_id)
        kb_rows.append([InlineKeyboardButton(
            f"📍 Butun {region['name']}", callback_data=f"sdist_0_{region_id}"
        )])
        kb_rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_search")])
        await query.edit_message_text(
            f"📍 {region['name']} — tuman tanlang:",
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
    else:
        # Tumansiz viloyat — to'g'ridan-to'g'ri qidiruv
        context.user_data['search_region_id'] = region_id
        region = db.get_region_by_id(region_id)
        await query.edit_message_text(
            f"📍 Hudud: {region['name']}\n\n🔍 Mahsulot nomini kiriting:"
        )


async def search_district_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi tuman tanladi."""
    query = update.callback_query
    await query.answer()

    data = query.data.replace("sdist_", "")

    if "_" in data:
        # "0_region_id" — butun viloyat
        region_id = int(data.split("_")[1])
        context.user_data['search_region_id'] = region_id
        region = db.get_region_by_id(region_id)
        name = region['name'] if region else "tanlangan hudud"
    else:
        district_id = int(data)
        context.user_data['search_region_id'] = district_id
        district = db.get_region_by_id(district_id)
        name = district['name'] if district else "tanlangan tuman"

    await query.edit_message_text(f"📍 Hudud: {name}\n\n🔍 Mahsulot nomini kiriting:")


async def buyer_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_buyer(user['id'])

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])

    if not orders:
        text = "Hozircha buyurtmalar yo'q."
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = []
    for order in orders[:15]:
        emoji = status_emoji.get(order['status'], '❓')
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {fmt_order_id(order['id'])} — {order['product_name'][:25]}",
            callback_data=f"order_detail_{order['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")])

    text = f"🛒 Buyurtmalarim ({len(orders)} ta):"
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

    kb_back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])

    if not rows:
        text = "💬 Hali xabarli buyurtmalar yo'q."
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
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")])

    text = "💬 Xabarlar:"
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    keyboard = [
        [InlineKeyboardButton("✏️ Ismni tahrirlash", callback_data="edit_buyer_name")],
        [InlineKeyboardButton("✏️ Telefonni tahrirlash", callback_data="edit_buyer_phone")],
        [InlineKeyboardButton("🔗 Mening havolam", callback_data="my_referral")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")],
    ]
    text = (
        f"👤 Xaridor profili\n\n"
        f"Ism: {user['name']}\n"
        f"Telefon: {user['phone_number']}\n"
        f"Takliflar: {user.get('referral_count') or 0} ta\n"
        f"Ro'yxatdan o'tgan: {fmt_datetime(user['created_at'])}"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def my_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi o'z taklif havolasini ko'radi va ulashishi mumkin."""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("Foydalanuvchi topilmadi. /start bilan boshlang.")
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
    share_url = f"https://t.me/share/url?url={quote(ref_link, safe='')}&text={quote('TezBozor marketplace botiga qo`shiling!', safe='')}"

    text = (
        f"🔗 <b>Mening taklif havolam</b>\n\n"
        f"Havola (bosing va nusxalang):\n"
        f"<code>{ref_link}</code>\n\n"
        f"Kod: <code>{user['referral_code']}</code>\n"
        f"👥 Taklif qilganlar: <b>{user.get('referral_count') or 0} ta</b>\n\n"
        f"Havolani do'stlaringizga yuboring — ular ro'yxatdan o'tganda hisobingizga qo'shiladi."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Do'stlarga ulashish", url=share_url)],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_profile")],
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')


async def buyer_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)

    if not order:
        await query.edit_message_text("Buyurtma topilmadi.")
        return

    dlv = order.get('delivery_type', 'delivery')
    pay = order.get('payment_method', 'cash')
    status = order['status']

    # Status tavsifi — xaridorga tushunarli
    status_guide = {
        'pending':   "⏳ Sotuvchi hali tasdiqlamadi. Kuting yoki bekor qiling.",
        'confirmed': (
            "✅ Sotuvchi tasdiqladi!\n"
            + ("📍 Yetkazib berish kutilmoqda." if dlv == 'delivery'
               else "🚶 Do'konga borib olishingiz mumkin.")
        ),
        'delivered': "🚚 Buyurtma yakunlandi. Reyting qoldiring!",
        'cancelled': "❌ Buyurtma bekor qilindi.",
    }

    # Holat ketma-ketligi vizual
    steps = ['⏳ Yangi', '✅ Tasdiqlangan',
             '🚚 Yetkazildi' if dlv == 'delivery' else '✅ Olindi',
             '⭐ Baholandi']
    step_idx = {'pending': 0, 'confirmed': 1, 'delivered': 2, 'cancelled': 0}.get(status, 0)
    timeline = ""
    for i, step in enumerate(steps):
        if i < step_idx:
            timeline += f"✅ {step}\n"
        elif i == step_idx and status != 'cancelled':
            timeline += f"▶️ {step}  ← hozir\n"
        else:
            timeline += f"⬜ {step}\n"

    keyboard = []

    if status == 'pending':
        keyboard.append([InlineKeyboardButton(
            "❌ Bekor qilish", callback_data=f"buyer_cancel_{order_id}"
        )])

    # Pickup: xaridor o'zi "Oldim" tugmasini bosadi → 'delivered' ga o'tadi
    if status == 'confirmed' and dlv == 'pickup':
        keyboard.append([InlineKeyboardButton(
            "✅ Tovarni oldim", callback_data=f"buyer_confirm_pickup_{order_id}"
        )])

    if status in ('delivered', 'cancelled'):
        keyboard.append([InlineKeyboardButton(
            "🔁 Qaytadan buyurtma", callback_data=f"order_{order['product_id']}"
        )])

    keyboard.append([InlineKeyboardButton(
        "💬 Xabar yuborish", callback_data=f"order_msg_{order_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        "📜 Yozishmalar", callback_data=f"msgs_{order_id}"
    )])

    # Reyting: delivery — faqat 'delivered' da; pickup — 'confirmed' da ham mumkin
    can_rate = (status == 'delivered') or (status == 'confirmed' and dlv == 'pickup')
    if can_rate:
        keyboard.append([InlineKeyboardButton(
            "⭐ Reyting qoldirish", callback_data=f"order_rate_{order_id}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_orders")])

    dlv_label = DELIVERY_LABELS.get(dlv, dlv)
    pay_label = PAYMENT_LABELS.get(pay, pay)

    text = (
        f"🛒 <b>Buyurtma {fmt_order_id(order['id'])}</b>\n\n"
        f"📦 {html.escape(order.get('product_name') or '')}\n"
        f"🔢 Miqdor: {order['quantity']}\n"
        f"💰 Jami: <b>{fmt_price(order['total_price'])}</b>\n"
        f"🚚 {dlv_label}\n"
        f"💳 {pay_label}\n"
        f"🏪 {html.escape(order.get('shop_name') or '')}\n"
        f"📞 {order.get('seller_phone') or '—'}\n"
        f"📅 {fmt_datetime(order.get('created_at'))}\n\n"
        f"<b>Holat:</b>\n{timeline}\n"
        f"<i>{status_guide.get(status, '')}</i>"
    )

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

    if not order or not buyer or order['buyer_id'] != buyer['id']:
        await query.edit_message_text("❌ Buyurtma topilmadi yoki sizniki emas.")
        return

    if order['status'] != 'confirmed':
        await query.edit_message_text(
            f"❌ Bu buyurtma holati: {fmt_status(order['status'])}. Tasdiqlab bo'lmaydi."
        )
        return

    db.update_order_status(order_id, 'delivered')

    # Sotuvchiga xabar
    try:
        if order.get('seller_tg'):
            await context.bot.send_message(
                chat_id=order['seller_tg'],
                text=(
                    f"✅ Xaridor tovarni oldi!\n\n"
                    f"Buyurtma {fmt_order_id(order_id)} — "
                    f"{html.escape(order.get('product_name') or '')}\n"
                    f"👤 {html.escape(order.get('buyer_name') or '')}"
                ),
                parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"Pickup tasdiqlash bildirishnomasi ketmadi: {e}")

    await query.edit_message_text(
        f"✅ Ajoyib! Buyurtma {fmt_order_id(order_id)} yakunlandi.\n\n"
        f"Xaridingiz qulay bo'lsin! ⭐ Reyting qoldirishni unutmang.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Reyting qoldirish", callback_data=f"order_rate_{order_id}")],
            [InlineKeyboardButton("⬅️ Buyurtmalar", callback_data="buyer_orders")],
        ])
    )


async def buyer_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xaridor 'pending' buyurtmasini bekor qilishi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)
    buyer = db.get_user_by_telegram_id(update.effective_user.id)

    if not order or not buyer or order['buyer_id'] != buyer['id']:
        await query.edit_message_text("❌ Buyurtma topilmadi yoki sizniki emas.")
        return

    if order['status'] != 'pending':
        await query.edit_message_text(
            f"❌ Bu buyurtmani bekor qila olmaysiz (holat: {fmt_status(order['status'])}).\n"
            f"Sotuvchi bilan bog'laning."
        )
        return

    db.update_order_status(order_id, 'cancelled')
    await query.edit_message_text(
        f"✅ Buyurtma {fmt_order_id(order_id)} bekor qilindi.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Buyurtmalar", callback_data="buyer_orders")
        ]])
    )

    # Sotuvchiga bildirishnoma
    try:
        if order.get('seller_tg'):
            await context.bot.send_message(
                chat_id=order['seller_tg'],
                text=f"ℹ️ Xaridor buyurtmani bekor qildi: {fmt_order_id(order_id)} — {html.escape(order.get('product_name') or '')}"
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


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahsulot kartasidagi '🛒 Buyurtma berish' tugmasi."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])
    product = db.get_product_by_id(product_id)

    if not product:
        await query.edit_message_text("Mahsulot topilmadi.")
        return ConversationHandler.END

    if not product.get('in_stock'):
        await query.edit_message_text("❌ Bu mahsulot hozir sotuvda yo'q.")
        return ConversationHandler.END

    # O'z mahsulotini buyurtma qilish — oldini olamiz
    buyer = db.get_user_by_telegram_id(update.effective_user.id)
    if buyer and buyer['id'] == product['seller_id']:
        await query.edit_message_text("❌ O'z mahsulotingizni buyurtma qila olmaysiz.")
        return ConversationHandler.END

    # Ish vaqti tashqarisidami? Ogohlantiramiz, lekin to'xtatmaymiz
    closed_note = ""
    if is_shop_open_now(product.get('working_hours')) is False:
        closed_note = (
            f"\n⚠️ Eslatma: do'kon hozir yopiq ({html.escape(product.get('working_hours') or '')}). "
            f"Sotuvchi xabarni keyinroq ko'rishi mumkin."
        )

    # Jarayon ma'lumotlarini saqlab qo'yamiz
    context.user_data['order_product'] = product
    context.user_data.pop('order_qty', None)
    context.user_data.pop('order_delivery_type', None)
    context.user_data.pop('order_address', None)
    context.user_data.pop('order_lat', None)
    context.user_data.pop('order_lon', None)
    context.user_data.pop('order_payment', None)

    await query.edit_message_text(
        f"🛒 <b>{html.escape(product['name'] or '')}</b>\n"
        f"Narxi: {fmt_price(product['price'])} / dona{closed_note}\n\n"
        f"Nechta olmoqchisiz? (raqam kiriting):",
        parse_mode='HTML'
    )
    return ORDER_QUANTITY


async def order_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1 or qty > 999:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ 1 dan 999 gacha raqam kiriting:")
        return ORDER_QUANTITY

    product = context.user_data['order_product']

    # Stock_count tekshiruvi — agar zahira chegarasi qo'yilgan bo'lsa
    stock = product.get('stock_count')
    if stock is not None and qty > stock:
        await update.message.reply_text(
            f"❌ Bu mahsulotdan faqat {stock} dona mavjud. "
            f"Kichikroq miqdor kiriting (1–{stock}):"
        )
        return ORDER_QUANTITY

    context.user_data['order_qty'] = qty
    total = qty * float(product['price'])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(DELIVERY_LABELS['delivery'], callback_data="ord_dlv_delivery")],
        [InlineKeyboardButton(DELIVERY_LABELS['pickup'], callback_data="ord_dlv_pickup")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="ord_cancel")],
    ])
    await update.message.reply_text(
        f"Jami: <b>{fmt_price(total)}</b>\n\nQanday qabul qilasiz?",
        reply_markup=kb,
        parse_mode='HTML'
    )
    return ORDER_DELIVERY_TYPE


async def order_delivery_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ord_cancel":
        await query.edit_message_text("Buyurtma bekor qilindi.")
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
        await _ask_payment(query, seller_card_info=seller_card)
        return ORDER_PAYMENT

    # Yetkazib berish — manzil so'raymiz
    await query.edit_message_text(
        "📍 Yetkazib berish manzilini yuboring (lokatsiya yoki matn):"
    )
    await query.message.reply_text(
        "Lokatsiyani yuborish uchun pastdagi tugmani bosing yoki manzilni matn ko'rinishida yozing:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Lokatsiyani yuborish", request_location=True)]],
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
    else:
        text = update.message.text.strip()
        if len(text) < 5:
            await update.message.reply_text("❌ Manzil juda qisqa. Aniqroq yozing:")
            return ORDER_ADDRESS
        context.user_data['order_address'] = text

    await update.message.reply_text(
        "✅ Manzil qabul qilindi.",
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
    await _ask_payment(update.message, seller_card_info=seller_card)
    return ORDER_PAYMENT


async def _ask_payment(target, seller_card_info=None):
    """To'lov usulini tanlash. seller_card_info — sotuvchining karta ma'lumoti."""

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
        p2p_note = f"\n\n📲 P2P uchun sotuvchi kartasi:\n{ctype} {masked}\n👤 {owner}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(PAYMENT_LABELS['cash'],     callback_data="ord_pay_cash")],
        [InlineKeyboardButton(PAYMENT_LABELS['terminal'], callback_data="ord_pay_terminal")],
        [InlineKeyboardButton(PAYMENT_LABELS['p2p'],      callback_data="ord_pay_p2p")],
        [InlineKeyboardButton("❌ Bekor qilish",           callback_data="ord_cancel")],
    ])
    text = (
        "💰 To'lov usulini tanlang:\n\n"
        "💵 <b>Naqd</b> — yetkazib berganda naqd to'laysiz\n"
        "💳 <b>Terminal</b> — sotuvchidagi POS terminalni ishlatib to'laysiz\n"
        "📲 <b>P2P</b> — karta raqamiga o'tkazasiz"
        f"{p2p_note}\n\n"
        "<i>⚠️ Bot hech qanday karta ma'lumotini so'ramaydi va to'lovni o'zi amalga oshirmaydi.</i>"
    )

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
    else:
        await target.reply_text(text, reply_markup=kb, parse_mode='HTML')


async def order_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ord_cancel":
        await query.edit_message_text("Buyurtma bekor qilindi.")
        return ConversationHandler.END

    method = query.data.replace("ord_pay_", "")  # 'cash' | 'card' | 'click'
    context.user_data['order_payment'] = method

    # Tasdiq ekrani
    product = context.user_data['order_product']
    qty = context.user_data['order_qty']
    total = qty * float(product['price'])
    dlv = context.user_data['order_delivery_type']

    summary = (
        "🛒 <b>Buyurtmani tasdiqlang:</b>\n\n"
        f"📦 Mahsulot: {html.escape(product['name'] or '')}\n"
        f"🏪 Do'kon: {html.escape(product.get('shop_name') or '')}\n"
        f"🔢 Miqdor: {qty}\n"
        f"💰 Jami: <b>{fmt_price(total)}</b>\n"
        f"🚚 Yetkazish: {DELIVERY_LABELS.get(dlv, dlv)}\n"
    )
    if dlv == 'delivery':
        summary += f"📍 Manzil: {html.escape(context.user_data.get('order_address') or '')}\n"
    summary += f"💳 To'lov: {PAYMENT_LABELS.get(method, method)}\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data="ord_confirm_yes")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="ord_cancel")],
    ])
    await query.edit_message_text(summary, reply_markup=kb, parse_mode='HTML')
    return ORDER_CONFIRM


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ord_cancel":
        await query.edit_message_text("Buyurtma bekor qilindi.")
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

    await query.edit_message_text(
        f"✅ Buyurtmangiz qabul qilindi!\n\n"
        f"Buyurtma raqami: <b>{fmt_order_id(order_id)}</b>\n"
        f"Sotuvchi tez orada tasdiqlaydi va siz bilan bog'lanadi.",
        parse_mode='HTML'
    )

    # Sotuvchiga bildirishnoma
    try:
        seller_tg = product.get('seller_tg')
        if seller_tg:
            buyer_lat = context.user_data.get('order_lat')
            buyer_lon = context.user_data.get('order_lon')
            buyer_address = context.user_data.get('order_address') or ''

            text = (
                f"🔔 <b>Yangi buyurtma!</b> {fmt_order_id(order_id)}\n\n"
                f"📦 {html.escape(product['name'] or '')}\n"
                f"🔢 Miqdor: {qty}\n"
                f"💰 Jami: <b>{fmt_price(total)}</b>\n"
                f"👤 Xaridor: {html.escape(buyer['name'] or '')}\n"
                f"📞 {buyer.get('phone_number') or '—'}\n"
                f"🚚 {DELIVERY_LABELS.get(dlv, dlv)}\n"
            )

            # Masofa hisoblash (sotuvchi do'koni → xaridor)
            if dlv == 'delivery' and buyer_lat and buyer_lon:
                shop_lat = product.get('shop_lat')
                shop_lon = product.get('shop_lon')
                if shop_lat and shop_lon:
                    dist = haversine_km(shop_lat, shop_lon, buyer_lat, buyer_lon)
                    if dist is not None:
                        text += f"📏 Do'kondan masofa: ~{dist:.1f} km\n"
                elif buyer_address:
                    text += f"📍 Manzil: {html.escape(buyer_address)}\n"
            elif dlv == 'delivery' and buyer_address:
                text += f"📍 Manzil: {html.escape(buyer_address)}\n"

            text += f"💳 {PAYMENT_LABELS.get(context.user_data.get('order_payment'), '')}"

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}")],
                [InlineKeyboardButton("❌ Rad etish", callback_data=f"cancel_order_{order_id}")],
            ])
            await context.bot.send_message(
                chat_id=seller_tg, text=text, reply_markup=kb, parse_mode='HTML'
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
# SELLER PANEL
# ============================================================

async def seller_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    context.user_data['active_mode'] = 'seller'

    keyboard = [
        [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="seller_add_product")],
        [InlineKeyboardButton("📦 Mahsulotlarim", callback_data="seller_products")],
        [InlineKeyboardButton("🛒 Buyurtmalar", callback_data="seller_orders")],
        [InlineKeyboardButton("📊 Statistika", callback_data="seller_stats")],
        [InlineKeyboardButton("💬 Xabarlar", callback_data="seller_messages")],
        [InlineKeyboardButton("⭐ Reytinglar", callback_data="seller_reviews")],
        [InlineKeyboardButton("👤 Profil", callback_data="seller_profile")],
        [InlineKeyboardButton("🛒 Xaridor rejimi", callback_data="switch_to_buyer")],
    ]

    text = (
        f"🏪 Sotuvchi paneli\n\n"
        f"Do'kon: {user.get('shop_name', 'Koʼrsatilmagan')}\n"
        f"Manzil: {user.get('shop_address', 'Koʼrsatilmagan')}\n\n"
        f"Tanlang:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        bottom_keyboard = [
            [KeyboardButton("➕ Mahsulot qo'shish"), KeyboardButton("📦 Mahsulotlarim")],
            [KeyboardButton("🛒 Buyurtmalar"), KeyboardButton("👤 Profil")],
            [KeyboardButton("🏠 Bosh sahifa")],
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text(
            "Quyidagi tugmalardan ham foydalanishingiz mumkin:",
            reply_markup=ReplyKeyboardMarkup(bottom_keyboard, resize_keyboard=True)
        )


async def seller_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi o'z reytinglarini ko'radi."""
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    reviews = db.get_seller_reviews(user['id'])
    avg = db.get_seller_avg_rating(user['id'])

    if not reviews:
        text = "⭐ Hozircha reytinglar yo'q."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    lines = [f"⭐ O'rtacha reyting: <b>{avg:.1f}/5.0</b> ({len(reviews)} ta baho)\n"]

    for r in reviews[:20]:  # so'nggi 20 ta
        stars = "⭐" * r['rating'] + "☆" * (5 - r['rating'])
        buyer = html.escape(r.get('buyer_name') or 'Anonim')
        comment = html.escape(r.get('comment') or '')
        date = fmt_datetime(r.get('created_at'))
        line = f"\n{stars}\n👤 {buyer} · {date}"
        if comment:
            line += f"\n💬 {comment}"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n…(eski reytinglar kesildi)"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])

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

    if not reviews:
        text = "⭐ Siz hali hech qanday reyting qoldirmagan ekansiz."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    lines = [f"⭐ <b>Mening baholarim</b> ({len(reviews)} ta)\n"]
    for r in reviews:
        stars = "⭐" * r['rating'] + "☆" * (5 - r['rating'])
        shop = html.escape(r.get('shop_name') or r.get('seller_name') or '—')
        product = html.escape(r.get('product_name') or '—')
        comment = html.escape(r.get('comment') or '')
        date = fmt_datetime(r.get('created_at'))
        line = f"\n{stars} · {shop}\n📦 {product} · {date}"
        if comment:
            line += f"\n💬 {comment}"
        lines.append(line)

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')


async def seller_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi statistikasi: buyurtmalar, daromad, mahsulotlar — hafta/oy/jami."""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    stats = db.get_seller_stats(user['id'])
    avg_rating = db.get_seller_avg_rating(user['id'])

    text = (
        f"📊 <b>{html.escape(user.get('shop_name') or '')} statistikasi</b>\n\n"
        f"📦 Mahsulotlar soni: <b>{stats['products_count']}</b>\n"
        f"⭐ O'rtacha reyting: <b>{avg_rating:.1f}/5.0</b>\n\n"
        f"<b>So'nggi 7 kun</b>\n"
        f"🛒 Buyurtmalar: {stats['week_orders']}\n"
        f"💰 Daromad (yetkazilgan): {fmt_price(stats['week_revenue'])}\n\n"
        f"<b>So'nggi 30 kun</b>\n"
        f"🛒 Buyurtmalar: {stats['month_orders']}\n"
        f"💰 Daromad: {fmt_price(stats['month_revenue'])}\n\n"
        f"<b>Jami</b>\n"
        f"🛒 Buyurtmalar: {stats['total_orders']}\n"
        f"⏳ Yangi: {stats['pending']}\n"
        f"✅ Tasdiqlangan: {stats['confirmed']}\n"
        f"🚚 Yetkazilgan: {stats['delivered']}\n"
        f"❌ Bekor qilingan: {stats['cancelled']}\n"
        f"💰 Jami daromad: <b>{fmt_price(stats['total_revenue'])}</b>"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]]),
        parse_mode='HTML'
    )

async def seller_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    context.user_data['adding_product'] = True
    # Eski qiymatlarni tozalaymiz (oldingi yarim qolgan jarayonni)
    for k in ('product_name', 'product_price', 'product_category', 'product_desc', 'product_photo'):
        context.user_data.pop(k, None)
    await query.edit_message_text("Mahsulot nomini kiriting (3–100 belgi):")
    return PRODUCT_NAME


async def seller_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    # Validatsiya: uzunlik
    if len(name) < 3:
        await update.message.reply_text("❌ Nom juda qisqa. Kamida 3 belgi kiriting:")
        return PRODUCT_NAME
    if len(name) > 100:
        await update.message.reply_text("❌ Nom juda uzun (maksimal 100 belgi). Qisqartiring:")
        return PRODUCT_NAME

    context.user_data['product_name'] = name
    await update.message.reply_text("Mahsulot narxini kiriting (so'mda, faqat raqam — masalan: 50000):")
    return PRODUCT_PRICE


async def seller_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.replace(" ", "").replace(",", "").replace("\u00A0", "")
    try:
        price = float(raw)
    except ValueError:
        await update.message.reply_text("❌ Iltimos, to'g'ri raqam kiriting (masalan: 50000):")
        return PRODUCT_PRICE

    # Validatsiya: musbat va mantiqiy chegara
    if price <= 0:
        await update.message.reply_text("❌ Narx 0 dan katta bo'lishi kerak:")
        return PRODUCT_PRICE
    if price > 1_000_000_000:
        await update.message.reply_text("❌ Narx juda katta. Qaytadan kiriting:")
        return PRODUCT_PRICE

    context.user_data['product_price'] = price

    categories = db.get_all_categories()
    keyboard = [[InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"prodcat_{cat[0]}")] for cat in categories]
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return PRODUCT_CATEGORY


async def seller_add_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    context.user_data['product_category'] = category_id

    await query.edit_message_text(
        "Mahsulot tavsifini kiriting (maksimal 500 belgi).\n"
        "O'tkazib yuborish uchun '-' yozing:"
    )
    return PRODUCT_DESC


async def seller_add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    elif len(desc) > 500:
        await update.message.reply_text("❌ Tavsif juda uzun (maksimal 500 belgi). Qisqartiring:")
        return PRODUCT_DESC

    context.user_data['product_desc'] = desc

    await update.message.reply_text(
        "📷 Mahsulot rasmini yuboring.\n"
        "Rasmsiz saqlash uchun '-' yozing."
    )
    return PRODUCT_PHOTO


async def seller_add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = None

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.strip() == "-":
        photo_file_id = None
    else:
        await update.message.reply_text(
            "❌ Iltimos, rasm yuboring yoki '-' yozing (rasmsiz saqlash uchun):"
        )
        return PRODUCT_PHOTO

    context.user_data['product_photo'] = photo_file_id

    # Kategoriya uchun atribut shablonlari bormi?
    category_id = context.user_data.get('product_category')
    templates = db.get_category_templates(category_id) if category_id else []

    if templates:
        # Atributlarni yig'ish uchun navbatni tuzamiz
        context.user_data['attr_templates'] = templates
        context.user_data['attr_index'] = 0
        context.user_data['product_attrs'] = {}
        return await _ask_next_attr(update, context)
    else:
        return await _save_product(update, context)


async def _ask_next_attr(update, context):
    """Navbatdagi atributni so'raydi."""
    templates = context.user_data.get('attr_templates', [])
    idx = context.user_data.get('attr_index', 0)

    if idx >= len(templates):
        return await _save_product(update, context)

    tmpl = templates[idx]
    required_mark = " *" if tmpl['is_required'] else " (ixtiyoriy)"
    hint = f"\nMasalan: {tmpl['hint']}" if tmpl.get('hint') else ""
    skip_note = "" if tmpl['is_required'] else "\nO'tkazib yuborish uchun '-' yozing."

    if tmpl['attr_type'] == 'select' and tmpl.get('hint'):
        # Tanlov variantlarini tugma sifatida ko'rsatamiz
        options = [o.strip() for o in tmpl['hint'].split('/')]
        kb = [[InlineKeyboardButton(opt, callback_data=f"attr_{opt}")] for opt in options]
        if not tmpl['is_required']:
            kb.append([InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="attr_-")])
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
            await update.message.reply_text(f"❌ Bu maydon majburiy. Qaytadan kiriting:")
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


async def _save_product(update, context):
    """Mahsulotni DB ga saqlaydi."""
    user = db.get_user_by_telegram_id(update.effective_user.id)
    product_id = db.create_product(
        seller_id=user['id'],
        name=context.user_data['product_name'],
        price=context.user_data['product_price'],
        category_id=context.user_data.get('product_category'),
        description=context.user_data.get('product_desc'),
        image_url=context.user_data.get('product_photo'),
    )

    # Atributlarni saqlash
    attrs = context.user_data.pop('product_attrs', {})
    if attrs and product_id:
        db.save_product_attributes(product_id, attrs)

    # State tozalash
    for k in ('product_name', 'product_price', 'product_category',
              'product_desc', 'product_photo', 'attr_templates',
              'attr_index', 'adding_product'):
        context.user_data.pop(k, None)

    msg = f"✅ Mahsulot muvaffaqiyatli qo'shildi!"
    if attrs:
        msg += f"\n📋 {len(attrs)} ta xususiyat saqlandi."

    if update.message:
        await update.message.reply_text(msg)
        await seller_panel(update, context)
    else:
        await update.callback_query.message.reply_text(msg)
        await seller_panel(update, context)

    return ConversationHandler.END


async def seller_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    products = db.get_products_by_seller(user['id'])

    if not products:
        await query.edit_message_text(
            "Hozircha mahsulotlar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        )
        return

    keyboard = []
    for product in products:
        icon = "✅" if product["in_stock"] else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {product['name']} — {fmt_price(product['price'])}",
            callback_data=f"prod_menu_{product['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")])

    await query.edit_message_text("📦 Mahsulotlarim:", reply_markup=InlineKeyboardMarkup(keyboard))


async def seller_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int = None):
    query = update.callback_query
    # Agar to'g'ridan-to'g'ri callback dan kelsa — javob beramiz; ichki chaqiriqda esa o'tkazib yuboramiz
    if product_id is None:
        await query.answer()
        product_id = int(query.data.split("_")[2])
    context.user_data['editing_product_id'] = product_id

    product = db.get_product_basic(product_id)

    if not product:
        await query.edit_message_text("Mahsulot topilmadi.")
        return

    status_text = "✅ Sotuvda" if product['in_stock'] else "❌ Sotuvda yo'q"
    toggle_btn = "❌ Sotuvdan olish" if product['in_stock'] else "✅ Sotuvga qo'yish"

    keyboard = [
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_start_{product_id}")],
        [InlineKeyboardButton(toggle_btn, callback_data=f"toggle_stock_{product_id}")],
        [InlineKeyboardButton("📦 Zahirani belgilash", callback_data=f"set_stock_{product_id}")],
        [InlineKeyboardButton("🗑️ O'chirish", callback_data=f"delete_prod_{product_id}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_products")],
    ]

    # HTML rejimi + foydalanuvchi matnini escape — '*', '_' kabi belgilarda crash bo'lmaydi
    name = html.escape(product['name'] or '')
    desc = html.escape(product.get('description') or "Yo'q")
    stock_line = ""
    if product.get('stock_count') is not None:
        stock_line = f"\nZahira: {product['stock_count']} dona"
    else:
        stock_line = "\nZahira: cheklanmagan"

    # Atributlar
    attrs = db.get_product_attributes(product_id)
    attrs_text = ""
    if attrs:
        lines = [f"• {a.get('attr_label') or a['attr_key']}: {a['attr_value']}" for a in attrs]
        attrs_text = "\n\n🏷 Xususiyatlar:\n" + "\n".join(lines)

    await query.edit_message_text(
        f"📦 <b>{name}</b>\n\n"
        f"Narxi: {fmt_price(product['price'])}\n"
        f"Holat: {status_text}{stock_line}\n"
        f"Tavsif: {desc}"
        f"{attrs_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


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

    await query.edit_message_text(
        "📦 Zahira sonini kiriting (faqat raqam).\n"
        "Cheksiz qilish uchun '-' yozing.\n"
        "Bekor qilish uchun /cancel yoki bosh sahifaga qayting."
    )


async def set_stock_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """text_handler tomonidan chaqiriladi — setting_stock_for bo'lsa."""
    product_id = context.user_data.pop('setting_stock_for', None)
    if not product_id:
        return False  # bizning rejimimiz emas

    text = update.message.text.strip()
    if text == '-':
        new_stock = None
    else:
        try:
            new_stock = int(text)
            if new_stock < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Manfiy bo'lmagan butun son yoki '-' yozing. Qaytadan urinish uchun mahsulot menyusiga qayting."
            )
            return True

    db.set_product_stock_count(product_id, new_stock)

    if new_stock is None:
        await update.message.reply_text("✅ Zahira: cheklanmagan qilib belgilandi.")
    else:
        await update.message.reply_text(f"✅ Zahira: {new_stock} dona qilib belgilandi.")

    # Sotuvchi paneliga qaytamiz
    await seller_panel(update, context)
    return True


async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("delete_prod_") and not data.startswith("delete_confirm_"):
        product_id = int(data.split("_")[2])
        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"delete_confirm_{product_id}")],
            [InlineKeyboardButton("❌ Yo'q, bekor", callback_data=f"prod_menu_{product_id}")],
        ]
        await query.edit_message_text(
            "⚠️ Haqiqatan ham bu mahsulotni o'chirmoqchimisiz?\nBu amalni qaytarib bo'lmaydi!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    product_id = int(data.split("_")[2])
    db.delete_product(product_id)

    await query.edit_message_text(
        "✅ Mahsulot o'chirildi.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Mahsulotlarim", callback_data="seller_products")]])
    )


async def edit_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Mahsulot nomini kiriting (o'zgartirmaslik uchun /skip yozing):")
    return EDIT_PRODUCT_NAME


async def edit_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        name = update.message.text.strip()
        if len(name) < 3:
            await update.message.reply_text("❌ Nom juda qisqa. Kamida 3 belgi yoki /skip:")
            return EDIT_PRODUCT_NAME
        if len(name) > 100:
            await update.message.reply_text("❌ Nom juda uzun (maks. 100 belgi):")
            return EDIT_PRODUCT_NAME
        context.user_data['edit_product_name'] = name
    await update.message.reply_text("Mahsulot narxini kiriting (so'm) yoki /skip:")
    return EDIT_PRODUCT_PRICE


async def edit_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        raw = update.message.text.replace(" ", "").replace(",", "").replace("\u00A0", "")
        try:
            price = float(raw)
        except ValueError:
            await update.message.reply_text("❌ To'g'ri raqam kiriting yoki /skip:")
            return EDIT_PRODUCT_PRICE
        if price <= 0 or price > 1_000_000_000:
            await update.message.reply_text("❌ Narx 0 dan katta va mantiqiy bo'lishi kerak. Qaytadan yoki /skip:")
            return EDIT_PRODUCT_PRICE
        context.user_data['edit_product_price'] = price

    categories = db.get_all_categories()
    keyboard = [[InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"editcat_{cat[0]}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("⏭️ O'zgarishsiz qoldirish", callback_data="editcat_skip")])

    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_PRODUCT_CATEGORY


async def edit_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data != "editcat_skip":
        context.user_data['edit_product_category'] = int(query.data.split("_")[1])

    await query.edit_message_text("Mahsulot tavsifini kiriting yoki /skip:")
    return EDIT_PRODUCT_DESC


async def edit_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        desc = update.message.text.strip()
        if len(desc) > 500:
            await update.message.reply_text("❌ Tavsif juda uzun (maks. 500 belgi):")
            return EDIT_PRODUCT_DESC
        context.user_data['edit_product_desc'] = desc

    await update.message.reply_text(
        "📷 Yangi rasm yuboring, o'zgarishsiz qoldirish uchun /skip, "
        "rasmni o'chirish uchun '-' yozing:"
    )
    return EDIT_PRODUCT_PHOTO


async def edit_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Foydalanuvchi rasm yuborgan / "/skip" / "-" yozgan bo'lishi mumkin
    if update.message.photo:
        context.user_data['edit_product_image_url'] = update.message.photo[-1].file_id
    elif update.message.text:
        text = update.message.text.strip()
        if text == "/skip":
            pass  # o'zgartirmaymiz
        elif text == "-":
            context.user_data['edit_product_image_url'] = None  # rasmni o'chiramiz
        else:
            await update.message.reply_text("❌ Rasm yuboring, /skip yoki '-' yozing:")
            return EDIT_PRODUCT_PHOTO
    else:
        await update.message.reply_text("❌ Rasm yuboring, /skip yoki '-' yozing:")
        return EDIT_PRODUCT_PHOTO

    product_id = context.user_data.get('editing_product_id')
    if not product_id:
        await update.message.reply_text("Xato: tahrirlash jarayoni noto'g'ri boshlandi.")
        return ConversationHandler.END

    update_data = {}
    if 'edit_product_name' in context.user_data:
        update_data['name'] = context.user_data.pop('edit_product_name')
    if 'edit_product_price' in context.user_data:
        update_data['price'] = context.user_data.pop('edit_product_price')
    if 'edit_product_category' in context.user_data:
        update_data['category_id'] = context.user_data.pop('edit_product_category')
    if 'edit_product_desc' in context.user_data:
        update_data['description'] = context.user_data.pop('edit_product_desc')
    if 'edit_product_image_url' in context.user_data:
        update_data['image_url'] = context.user_data.pop('edit_product_image_url')

    if update_data:
        db.update_product_fields(product_id, **update_data)

    await update.message.reply_text("✅ Mahsulot yangilandi!")
    await seller_panel(update, context)
    return ConversationHandler.END


async def seller_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_seller(user['id'])

    if not orders:
        await query.edit_message_text(
            "Hozircha buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = []
    for order in orders[:10]:
        keyboard.append([InlineKeyboardButton(
            f"{status_emoji.get(order['status'], '❓')} {order['buyer_name']} — {fmt_price(order['total_price'])}",
            callback_data=f"seller_order_{order['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")])

    await query.edit_message_text("🛒 Buyurtmalar:", reply_markup=InlineKeyboardMarkup(keyboard))


async def seller_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    avg_rating = db.get_seller_avg_rating(user['id'])

    # Karta holati
    card_info = ""
    if user.get('card_number'):
        cnum = user['card_number']
        masked = f"{cnum[:4]} **** **** {cnum[-4:]}" if len(cnum) >= 8 else cnum
        ctype = CARD_TYPE_LABELS.get(user.get('card_type', ''), '💳')
        card_info = f"\n{ctype} {masked} ({user.get('card_owner', '')})"
    else:
        card_info = "\n❌ Karta qo'shilmagan (P2P to'lov qabul qilish uchun kerak)"

    keyboard = [
        [InlineKeyboardButton("✏️ Do'kon nomi",  callback_data="edit_shop_name")],
        [InlineKeyboardButton("✏️ Manzil",        callback_data="edit_shop_address")],
        [InlineKeyboardButton("✏️ Mo'ljal",       callback_data="edit_shop_landmark")],
        [InlineKeyboardButton("✏️ Ish kunlari",   callback_data="edit_working_days")],
        [InlineKeyboardButton("✏️ Ish vaqti",     callback_data="edit_working_hours")],
        [InlineKeyboardButton("✏️ Telegram",      callback_data="edit_telegram")],
        [InlineKeyboardButton("💳 Karta ma'lumoti", callback_data="edit_card_info")],
        [InlineKeyboardButton("⬅️ Orqaga",        callback_data="seller_panel")],
    ]

    YOQ = "Ko'rsatilmagan"
    text = (
        f"🏪 Sotuvchi profili\n\n"
        f"Do'kon: {user.get('shop_name') or YOQ}\n"
        f"Manzil: {user.get('shop_address') or YOQ}\n"
        f"Mo'ljal: {user.get('shop_landmark') or YOQ}\n"
        f"Ish kunlari: {user.get('working_days') or YOQ}\n"
        f"Ish vaqti: {user.get('working_hours') or YOQ}\n"
        f"Telegram: {user.get('telegram_username') or YOQ}\n"
        f"Telefon: {user.get('phone_number') or YOQ}\n"
        f"💳 To'lov kartasi:{card_info}\n"
        f"⭐ Reyting: {avg_rating:.1f}/5.0\n"
        f"Ro'yxatdan o'tgan: {fmt_datetime(user['created_at'])}"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def edit_buyer_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Yangi ismingizni kiriting:")
    return EDIT_PROFILE_NAME


async def edit_buyer_name_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = normalize_name(update.message.text)
    if not name:
        await update.message.reply_text("❌ Ism 2-50 belgi bo'lishi kerak. Qaytadan kiriting:")
        return EDIT_PROFILE_NAME

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], name=name)
    await update.message.reply_text("✅ Ism yangilandi!")
    await buyer_panel(update, context)
    return ConversationHandler.END


async def edit_buyer_phone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]]
    await query.edit_message_text("Yangi telefon raqamingizni yuboring:")
    # edit_message_text reply_markup qabul qilmaydi ReplyKeyboard uchun,
    # shuning uchun alohida xabar yuboramiz
    await query.message.reply_text(
        "Telefon tugmasini bosing:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]],
                                         resize_keyboard=True, one_time_keyboard=True)
    )
    return EDIT_PROFILE_PHONE


async def edit_buyer_phone_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text

    normalized = normalize_phone(phone)
    if not normalized:
        await update.message.reply_text(
            "❌ Telefon raqami noto'g'ri. Misol: +998901234567\nQaytadan yuboring:"
        )
        return EDIT_PROFILE_PHONE

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], phone_number=normalized)
    await update.message.reply_text("✅ Telefon yangilandi!", reply_markup=ReplyKeyboardRemove())
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

    field_labels = {
        'shop_name': "Do'kon nomi",
        'shop_address': "Manzil",
        'shop_landmark': "Mo'ljal",
        'working_days': "Ish kunlari",
        'working_hours': "Ish vaqti",
        'telegram': "Telegram username"
    }

    label = field_labels.get(field, field)

    if field == 'shop_address':
        await query.edit_message_text(f"✏️ {label}ni kiriting (lokatsiya yoki matn):")
        await query.message.reply_text(
            "Lokatsiya yuboring yoki matn kiriting:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Manzilni yuborish", request_location=True)]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return EDIT_SHOP_ADDRESS
    else:
        await query.edit_message_text(f"✏️ {label}ni kiriting:")

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
        db.update_user(user['id'], shop_address=f"{lat}, {lon}", shop_lat=lat, shop_lon=lon)
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

    await update.message.reply_text("✅ Ma'lumotlar yangilandi!", reply_markup=ReplyKeyboardRemove())
    await seller_panel(update, context)
    return ConversationHandler.END


async def edit_card_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchi karta ma'lumotini qo'shish/tahrirlash."""
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟦 Uzcard",     callback_data="card_type_uzcard")],
        [InlineKeyboardButton("🟩 Humo",       callback_data="card_type_humo")],
        [InlineKeyboardButton("🔵 Visa",       callback_data="card_type_visa")],
        [InlineKeyboardButton("🔴 Mastercard", callback_data="card_type_mastercard")],
        [InlineKeyboardButton("❌ Kartani o'chirish", callback_data="card_type_remove")],
        [InlineKeyboardButton("⬅️ Bekor qilish", callback_data="seller_profile")],
    ])
    await query.edit_message_text(
        "💳 <b>Karta ma'lumotlari</b>\n\n"
        "Bu ma'lumotlar faqat xaridorga to'lov uchun ko'rsatiladi.\n"
        "<i>⚠️ Bot karta ma'lumotlarini hech qachon so'ramaydi — siz o'zingiz qo'shasiz.</i>\n\n"
        "Karta turini tanlang:",
        reply_markup=kb,
        parse_mode='HTML'
    )
    return EDIT_CARD_TYPE


async def edit_card_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "card_type_remove":
        user = db.get_user_by_telegram_id(update.effective_user.id)
        db.update_user(user['id'], card_number=None, card_owner=None, card_type=None)
        await query.edit_message_text("✅ Karta ma'lumotlari o'chirildi.")
        await seller_profile(update, context)
        return ConversationHandler.END

    card_type = query.data.replace("card_type_", "")
    context.user_data['new_card_type'] = card_type
    await query.edit_message_text(
        "💳 Karta raqamini kiriting (16 ta raqam, bo'shliqlarsiz):\n\n"
        "Misol: <code>8600123456781234</code>",
        parse_mode='HTML'
    )
    return EDIT_CARD_NUMBER


async def edit_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.replace(" ", "").replace("-", "")

    if not raw.isdigit() or len(raw) not in (16, 18, 20):
        await update.message.reply_text(
            "❌ Karta raqami noto'g'ri. 16 ta raqam kiriting:\n"
            "Misol: <code>8600123456781234</code>",
            parse_mode='HTML'
        )
        return EDIT_CARD_NUMBER

    context.user_data['new_card_number'] = raw
    await update.message.reply_text(
        "👤 Karta egasining to'liq ismini kiriting:\n"
        "Misol: <code>SHERZOD KARIMOV</code>",
        parse_mode='HTML'
    )
    return EDIT_CARD_OWNER


async def edit_card_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner = update.message.text.strip().upper()

    if len(owner) < 3 or len(owner) > 50:
        await update.message.reply_text("❌ Ism noto'g'ri. Qaytadan kiriting:")
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
        f"✅ Karta saqlandi:\n\n"
        f"{ctype_label} {masked}\n"
        f"👤 {owner}\n\n"
        f"<i>Endi xaridorlar P2P to'lov tanlasa, karta raqamingiz ko'rsatiladi.</i>",
        parse_mode='HTML'
    )
    await seller_profile(update, context)
    return ConversationHandler.END


async def seller_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])

    order = db.get_order_by_id(order_id)

    if not order:
        await query.edit_message_text("Buyurtma topilmadi.")
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}

    keyboard = []
    if order['status'] == 'pending':
        keyboard.append([InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}")])
        keyboard.append([InlineKeyboardButton("❌ Rad etish", callback_data=f"cancel_order_{order_id}")])
    elif order['status'] == 'confirmed':
        dlv = order.get('delivery_type', 'delivery')
        if dlv == 'delivery':
            keyboard.append([InlineKeyboardButton(
                "🚚 Yetkazib berildi", callback_data=f"deliver_order_{order_id}"
            )])
        else:
            # Pickup: xaridor o'zi "Oldim" bosadi, lekin sotuvchi ham tasdiqlashi mumkin
            keyboard.append([InlineKeyboardButton(
                "✅ Xaridor oldi (tasdiqlash)", callback_data=f"deliver_order_{order_id}"
            )])
    keyboard.append([InlineKeyboardButton("📜 Yozishmalar", callback_data=f"msgs_{order_id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_orders")])

    pay_method = order.get('payment_method') or 'cash'
    pay_label = PAYMENT_LABELS.get(pay_method, pay_method)

    # P2P bo'lsa — sotuvchiga karta raqamini eslatamiz
    pay_note = ""
    if pay_method == 'p2p':
        seller_user = db.get_user_by_telegram_id(update.effective_user.id)
        if seller_user and seller_user.get('card_number'):
            cnum = seller_user['card_number']
            masked = f"{cnum[:4]} **** **** {cnum[-4:]}"
            ctype = CARD_TYPE_LABELS.get(seller_user.get('card_type', ''), '💳')
            pay_note = f"\n📲 P2P kartangiz: {ctype} {masked}"
        else:
            pay_note = "\n⚠️ P2P karta ma'lumoti yo'q. Profilga kiring va karta qo'shing."

    dlv_type = DELIVERY_LABELS.get(order.get('delivery_type', 'delivery'), '')

    await query.edit_message_text(
        f"🛒 Buyurtma {fmt_order_id(order['id'])}\n\n"
        f"📦 {html.escape(order.get('product_name') or '')}\n"
        f"🔢 Miqdor: {order['quantity']}\n"
        f"💰 Jami: {fmt_price(order['total_price'])}\n"
        f"Holat: {fmt_status(order['status'])}\n"
        f"🚚 {dlv_type}\n"
        f"💳 To'lov: {pay_label}{pay_note}\n\n"
        f"👤 Xaridor: {html.escape(order.get('buyer_name') or '')}\n"
        f"📞 {order.get('buyer_phone') or '—'}\n"
        f"📅 {fmt_datetime(order.get('created_at'))}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
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

        # Xaridorga bildirishnoma yuboramiz
        try:
            order = db.get_order_by_id(order_id)
            if order and order.get('buyer_tg'):
                dlv = order.get('delivery_type', 'delivery')
                is_pickup = dlv == 'pickup'

                confirmed_msg = (
                    f"✅ Buyurtmangiz <b>tasdiqlandi!</b>\n"
                    f"{fmt_order_id(order_id)} — {html.escape(order.get('product_name') or '')}\n"
                    + ("🚶 Do'konga borib olishingiz mumkin." if is_pickup
                       else "📦 Yetkazib berish kutilmoqda. Sotuvchi siz bilan bog'lanadi.")
                )
                delivered_msg = (
                    f"{'✅ Tovar olindi!' if is_pickup else '🚚 Buyurtmangiz yetkazildi!'}\n"
                    f"{fmt_order_id(order_id)} — {html.escape(order.get('product_name') or '')}\n"
                    f"⭐ Sotuvchiga reyting qoldiring!"
                )

                msg_map = {
                    'confirmed': confirmed_msg,
                    'cancelled': (
                        f"❌ Buyurtmangiz <b>bekor qilindi.</b>\n"
                        f"{fmt_order_id(order_id)} — {html.escape(order.get('product_name') or '')}\n"
                        f"Boshqa do'konlardan qidirib ko'ring."
                    ),
                    'delivered': delivered_msg,
                }

                txt = msg_map.get(new_status)
                if txt:
                    kb = None
                    if new_status == 'delivered':
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                "⭐ Reyting qoldirish", callback_data=f"order_rate_{order_id}"
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

    await query.edit_message_text("💬 Xabaringizni kiriting:")
    return MESSAGE_TEXT


async def message_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    order_id = context.user_data.get('current_order_id')

    user = db.get_user_by_telegram_id(update.effective_user.id)

    # Buyurtma bo'yicha xaridor va sotuvchini olamiz (telegram_id bilan)
    order = db.get_order_by_id(order_id)
    if not order:
        await update.message.reply_text("❌ Buyurtma topilmadi.")
        return ConversationHandler.END

    # Foydalanuvchi shu buyurtmaning xaridorimi yoki sotuvchisimi — shunga qarab xabar yuboriladi.
    # role'ga tayanish noto'g'ri, chunki bitta foydalanuvchi ham xaridor ham sotuvchi bo'lishi mumkin.
    if user['id'] == order['buyer_id']:
        receiver_id = order['seller_id']
        receiver_tg = order.get('seller_tg')
        sender_label = f"👤 {html.escape(user.get('name') or '')} (xaridor)"
    else:
        receiver_id = order['buyer_id']
        receiver_tg = order.get('buyer_tg')
        sender_label = f"🏪 {html.escape(user.get('shop_name') or user.get('name') or '')} (sotuvchi)"

    db.create_message(order_id, user['id'], receiver_id, message_text)
    await update.message.reply_text("✅ Xabar yuborildi!")

    # Qabul qiluvchiga real yetkazish — Telegram orqali
    if receiver_tg:
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Javob berish", callback_data=f"order_msg_{order_id}")],
                [InlineKeyboardButton("📜 Yozishmalar", callback_data=f"msgs_{order_id}")],
            ])
            await context.bot.send_message(
                chat_id=receiver_tg,
                text=f"💬 Yangi xabar — {fmt_order_id(order_id)}\n\n"
                     f"{sender_label}:\n{html.escape(message_text)}",
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
    user = db.get_user_by_telegram_id(update.effective_user.id)
    order = db.get_order_by_id(order_id)

    if not order or not user or user['id'] not in (order['buyer_id'], order['seller_id']):
        await query.edit_message_text("❌ Buyurtma topilmadi yoki sizning buyurtmangiz emas.")
        return

    messages = db.get_messages_by_order(order_id)
    if not messages:
        text = "📜 Bu buyurtma bo'yicha hali xabarlar yo'q."
    else:
        lines = [f"📜 <b>Yozishmalar — {fmt_order_id(order_id)}</b>\n"]
        for m in messages[-30:]:  # so'nggi 30 ta xabar
            who = "👤" if m['sender_id'] == order['buyer_id'] else "🏪"
            name = html.escape(m.get('sender_name') or '')
            msg = html.escape(m.get('message') or '')
            ts = fmt_datetime(m.get('created_at'))
            lines.append(f"{who} <b>{name}</b> · {ts}\n{msg}\n")
        text = "\n".join(lines)
        # Telegram xabari 4096 belgidan uzun bo'la olmaydi — kesamiz
        if len(text) > 3800:
            text = text[:3800] + "\n\n…(eski xabarlar kesildi)"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Yangi xabar", callback_data=f"order_msg_{order_id}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"order_detail_{order_id}"
                              if user['id'] == order['buyer_id'] else f"seller_order_{order_id}")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')


async def seller_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sotuvchining barcha xabarli buyurtmalari ro'yxati."""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    rows = db.get_seller_messages_summary(user['id'])

    if not rows:
        await query.edit_message_text(
            "💬 Hali xabarli buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        )
        return

    keyboard = []
    for row in rows:
        rec = dict(zip(columns, row))
        label = f"📜 {fmt_order_id(rec['id'])} — {rec.get('product_name', '')[:25]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"msgs_{rec['id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")])

    await query.edit_message_text(
        "💬 So'nggi yozishmalar:",
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

    keyboard = [[InlineKeyboardButton("⭐" * i, callback_data=f"rate_{i}")] for i in range(1, 6)]
    await query.edit_message_text("⭐ Reytingni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return RATING


async def rating_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['rating'] = int(query.data.split("_")[1])
    await query.edit_message_text("📝 Izohingizni kiriting (ixtiyoriy, \"-\" yozsangiz o'tkazib yuboriladi):")
    return REVIEW_COMMENT


async def rating_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if comment == "-":
        comment = None

    rating = context.user_data.get('rating')
    order_id = context.user_data.get('current_order_id')
    user = db.get_user_by_telegram_id(update.effective_user.id)

    if not rating or not order_id:
        await update.message.reply_text("❌ Reyting topilmadi. Qaytadan urinib ko'ring.")
        await buyer_panel(update, context)
        return ConversationHandler.END

    order = db.get_order_by_id_for_rating(order_id)

    if not order:
        await update.message.reply_text("❌ Buyurtma topilmadi.")
        await buyer_panel(update, context)
        return ConversationHandler.END

    # Bir buyurtmaga bir martadan ko'p reyting qoldirishni oldini olamiz
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM reviews WHERE order_id=? AND buyer_id=?",
        (order_id, user['id'])
    )
    existing = cursor.fetchone()

    if existing:
        await update.message.reply_text("❌ Bu buyurtma uchun allaqachon reyting qoldirgan ekansiz.")
        await buyer_panel(update, context)
        return ConversationHandler.END

    # order endi dict — seller_id va buyer_id kalitlari bilan
    db.create_review(
        order_id=order_id,
        seller_id=order['seller_id'],
        buyer_id=user['id'],
        rating=rating,
        comment=comment
    )

    # Sotuvchiga reyting haqida xabar
    try:
        full_order = db.get_order_by_id(order_id)
        if full_order and full_order.get('seller_tg'):
            stars = "⭐" * rating
            await context.bot.send_message(
                chat_id=full_order['seller_tg'],
                text=f"⭐ Yangi reyting!\n\n"
                     f"{stars} {rating}/5\n"
                     f"Xaridor: {html.escape(user.get('name') or '')}\n"
                     + (f"Izoh: {html.escape(comment)}" if comment else "")
            )
    except Exception as e:
        logging.error(f"Reyting bildirishnomasi ketmadi: {e}")

    await update.message.reply_text(f"✅ Rahmat! {'⭐' * rating} reyting qabul qilindi.")
    await buyer_panel(update, context)
    return ConversationHandler.END


# ============================================================
# ADMIN PANEL
# ============================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(db.get_all_users())
    total_products = len(db.get_all_products())
    total_orders = len(db.get_all_orders())

    keyboard = [
        [InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton("📦 Mahsulotlar", callback_data="admin_products")],
        [InlineKeyboardButton("🛒 Buyurtmalar", callback_data="admin_orders")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Xabar yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="admin_settings")],
    ]

    text = (
        f"🔧 *Admin paneli*\n\n"
        f"📊 *Statistika:*\n"
        f"👥 Foydalanuvchilar: {total_users}\n"
        f"📦 Mahsulotlar: {total_products}\n"
        f"🛒 Buyurtmalar: {total_orders}\n\n"
        f"Boshqaruv funksiyalari:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


ADMIN_USERS_PAGE_SIZE = 15


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

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

    if not rows:
        await query.edit_message_text(
            "Foydalanuvchilar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")]])
        )
        return

    keyboard = []
    for user in rows:
        status = "🟢" if not user.get('is_blocked') else "🔴"
        role_emoji = {"buyer": "🛒", "seller": "🏪", "admin": "🔧"}
        keyboard.append([InlineKeyboardButton(
            f"{status} {role_emoji.get(user.get('role'), '❓')} {user.get('name') or 'Anonim'}",
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
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"👥 Foydalanuvchilar — jami {total} ta. Sahifa {page+1}/{total_pages}.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    query = update.callback_query
    if user_id is None:
        await query.answer()
        user_id = int(query.data.split("_")[2])

    user = db.get_user_by_id(user_id)

    if not user:
        await query.edit_message_text("Foydalanuvchi topilmadi.")
        return
    status = "🟢 Faol" if not user['is_blocked'] else "🔴 Bloklangan"
    verified = "✅ Tasdiqlangan" if user['is_verified'] else "❌ Tasdiqlanmagan"

    keyboard = [
        [InlineKeyboardButton(
            "🔓 Blokdan olish" if user['is_blocked'] else "🔒 Bloklash",
            callback_data=f"admin_block_{user_id}"
        )],
        [InlineKeyboardButton(
            "❌ Tasdiqlashni bekor qilish" if user['is_verified'] else "✅ Tasdiqlash",
            callback_data=f"admin_verify_{user_id}"
        )],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_users")],
    ]

    await query.edit_message_text(
        f"👤 Foydalanuvchi ma'lumotlari:\n\n"
        f"Ism: {user['name'] or 'Anonim'}\n"
        f"Telefon: {user.get('phone_number', 'Yoʼq')}\n"
        f"Rol: {user['role']}\n"
        f"Do'kon: {user.get('shop_name', 'Yoʼq')}\n"
        f"Holat: {status}\n"
        f"Tasdiqlash: {verified}\n"
        f"Ro'yxatdan o'tgan: {fmt_datetime(user['created_at'])}",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])

    is_verified = db.get_user_is_verified(user_id)
    if is_verified is not None:
        db.update_user(user_id, is_verified=0 if is_verified else 1)

    await admin_user_details(update, context, user_id=user_id)


async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    products = db.get_all_products()

    if not products:
        await query.edit_message_text(
            "Mahsulotlar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")]])
        )
        return

    keyboard = [[InlineKeyboardButton(
        f"{p['name']} — {fmt_price(p['price'])}",
        callback_data=f"admin_prod_{p['id']}"
    )] for p in products[:20]]
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"📦 Mahsulotlar (Jami: {len(products)}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    orders = db.get_all_orders()

    if not orders:
        await query.edit_message_text(
            "Buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = [[InlineKeyboardButton(
        f"{status_emoji.get(o['status'], '❓')} #{o['id']} — {fmt_price(o['total_price'])}",
        callback_data=f"admin_order_{o['id']}"
    )] for o in orders[:20]]
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"🛒 Buyurtmalar (Jami: {len(orders)}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])
    order = db.get_order_by_id(order_id)

    if not order:
        await query.edit_message_text("Buyurtma topilmadi.")
        return

    dlv = order.get('delivery_type') or 'delivery'
    pay = order.get('payment_method') or '—'

    text = (
        f"🛒 <b>Buyurtma {fmt_order_id(order_id)}</b>\n\n"
        f"📦 Mahsulot: {html.escape(order.get('product_name') or '')}\n"
        f"🔢 Miqdor: {order.get('quantity')}\n"
        f"💰 Jami: <b>{fmt_price(order.get('total_price'))}</b>\n"
        f"Holat: {fmt_status(order.get('status'))}\n\n"
        f"👤 Xaridor: {html.escape(order.get('buyer_name') or '')}\n"
        f"📞 {order.get('buyer_phone') or '—'}\n\n"
        f"🏪 Sotuvchi: {html.escape(order.get('seller_name') or '')}\n"
        f"📞 {order.get('seller_phone') or '—'}\n\n"
        f"🚚 {DELIVERY_LABELS.get(dlv, dlv)}\n"
        f"💳 {PAYMENT_LABELS.get(pay, pay)}\n"
        f"📅 {fmt_datetime(order.get('created_at'))}"
    )
    if order.get('delivery_address'):
        text += f"\n📍 Manzil: {html.escape(order.get('delivery_address') or '')}"

    keyboard = []
    if order.get('status') == 'pending':
        keyboard.append([
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_order_{order_id}"),
        ])
    elif order.get('status') == 'confirmed':
        keyboard.append([InlineKeyboardButton("🚚 Yetkazildi", callback_data=f"deliver_order_{order_id}")])

    if order.get('status') not in ('cancelled',):
        keyboard.append([InlineKeyboardButton(
            "🗑 Majburiy bekor qilish", callback_data=f"admin_force_cancel_{order_id}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_orders")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def admin_force_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin istalgan buyurtmani majburan bekor qiladi."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[3])
    order = db.get_order_by_id(order_id)

    if order:
        db.update_order_status(order_id, 'cancelled')
        # Ikki tomonga xabar
        msg = f"⚠️ Admin tomonidan buyurtma bekor qilindi: {fmt_order_id(order_id)}"
        for tg_id in [order.get('buyer_tg'), order.get('seller_tg')]:
            if tg_id:
                try:
                    await context.bot.send_message(chat_id=tg_id, text=msg)
                except Exception:
                    pass

    await admin_orders(update, context)



    query = update.callback_query
    await query.answer()

    users = db.get_all_users()
    products = db.get_all_products()
    orders = db.get_all_orders()

    buyers = [u for u in users if u['role'] == 'buyer']
    sellers = [u for u in users if u['role'] == 'seller']

    await query.edit_message_text(
        f"📊 *Statistika*\n\n"
        f"👥 *Foydalanuvchilar:*\n"
        f"Jami: {len(users)}\nXaridorlar: {len(buyers)}\nSotuvchilar: {len(sellers)}\n\n"
        f"📦 *Mahsulotlar:* {len(products)}\n\n"
        f"🛒 *Buyurtmalar:* {len(orders)}\n"
        f"⏳ Kutilmoqda: {len([o for o in orders if o['status'] == 'pending'])}\n"
        f"✅ Tasdiqlangan: {len([o for o in orders if o['status'] == 'confirmed'])}\n"
        f"🚚 Yetkazilgan: {len([o for o in orders if o['status'] == 'delivered'])}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")]]),
        parse_mode='Markdown'
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    users = db.get_all_users()
    products = db.get_all_products()
    orders = db.get_all_orders()

    buyers  = [u for u in users if u['role'] == 'buyer']
    sellers = [u for u in users if u['role'] == 'seller']

    pending   = [o for o in orders if o['status'] == 'pending']
    confirmed = [o for o in orders if o['status'] == 'confirmed']
    delivered = [o for o in orders if o['status'] == 'delivered']
    cancelled = [o for o in orders if o['status'] == 'cancelled']

    total_revenue = sum(float(o.get('total_price') or 0) for o in delivered)

    await query.edit_message_text(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {len(users)} ta\n"
        f"  🛒 Xaridorlar: {len(buyers)}\n"
        f"  🏪 Sotuvchilar: {len(sellers)}\n\n"
        f"📦 <b>Mahsulotlar:</b> {len(products)} ta\n\n"
        f"🛒 <b>Buyurtmalar:</b> {len(orders)} ta\n"
        f"  ⏳ Kutilmoqda: {len(pending)}\n"
        f"  ✅ Tasdiqlangan: {len(confirmed)}\n"
        f"  🚚 Yetkazilgan: {len(delivered)}\n"
        f"  ❌ Bekor qilingan: {len(cancelled)}\n\n"
        f"💰 <b>Jami daromad:</b> {fmt_price(total_revenue)}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")
        ]]),
        parse_mode='HTML'
    )


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['broadcasting'] = True
    await query.edit_message_text("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni kiriting:")


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 DB Backup olish", callback_data="admin_backup")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")],
    ])
    await query.edit_message_text(
        f"⚙️ Sozlamalar\n\nBot versiyasi: 2.0.0\nAdmin ID: {ADMIN_ID}\n\nTezBozor Marketplace Bot",
        reply_markup=kb,
    )


async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DB'ni admin'ga yuboradi — `.db` fayl sifatida."""
    query = update.callback_query
    await query.answer("⏳ Backup tayyorlanmoqda...")

    import datetime as dt
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"marketplace_backup_{ts}.db"

    ok = db.backup(backup_path)
    if not ok:
        await query.message.reply_text("❌ Backup xatosi. Log'ni tekshiring.")
        return

    try:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(backup_path, 'rb'),
            filename=backup_path,
            caption=f"💾 TezBozor DB Backup\n{ts}"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Fayl yuborilmadi: {e}")
    finally:
        try:
            import os
            os.remove(backup_path)
        except Exception:
            pass


# ============================================================
# AI RECOMMENDATIONS
# ============================================================

async def show_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ko'rish tarixiga qarab tavsiya qilinadigan mahsulotlarni ko'rsatadi."""
    query = update.callback_query
    await query.answer()

    current_pid = int(query.data.split("_")[1])
    recs = _get_recommendations(context, db, current_pid, limit=10)

    if not recs:
        await query.answer("Hali yetarli ma'lumot yo'q. Ko'proq mahsulot ko'ring!", show_alert=True)
        return

    keyboard = []
    for p in recs:
        rating = p.get('avg_rating') or 0
        emoji = p.get('category_emoji') or '📦'
        keyboard.append([InlineKeyboardButton(
            f"{emoji} ⭐{rating:.1f} | {p['name']} — {fmt_price(p['price'])}",
            callback_data=f"prod_{p['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"prod_{current_pid}")])

    await query.edit_message_text(
        "✨ <b>Sizga mos bo'lishi mumkin:</b>\n\n"
        "Ko'rgan mahsulotlaringizga asoslanib tanlandı:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def ai_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = db.get_admin_products_summary(limit=10)

    if not products:
        await update.message.reply_text("Hali mahsulotlar yo'q.")
        return

    keyboard = [[InlineKeyboardButton(
        f"🤖 {p['name']} — {fmt_price(p['price'])}",
        callback_data=f"prod_{p['id']}"
    )] for p in products]

    await update.message.reply_text(
        "🤖 AI tavsiyalari (Ommabop mahsulotlar):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ai_recommendations(update, context)


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

    await query.answer()
    data = query.data

    handlers = {
        "buyer_panel": buyer_panel,
        "buyer_categories": buyer_categories,
        "buyer_search": buyer_search,
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
        "admin_broadcast": admin_broadcast_start,
        "admin_settings": admin_settings,
        "admin_backup": admin_backup,
        "skip_search_location": skip_search_location,
        "switch_to_buyer": switch_to_buyer,
        "switch_to_seller": switch_to_seller,
        "my_referral": my_referral,
        "seller_stats": seller_stats,
        "seller_messages": seller_messages,
        "seller_reviews": seller_reviews,
        "buyer_reviews": buyer_reviews,
        "buyer_messages": buyer_messages,
    }

    if data in handlers:
        await handlers[data](update, context)
    elif data.startswith("cat_"):
        # cat_ID yoki cat_ID_pg_N
        await buyer_category_products(update, context)
    elif data.startswith("prod_menu_"):
        await seller_product_menu(update, context)
    elif data.startswith("prod_"):
        await buyer_product_details(update, context)
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
    elif data.startswith("admin_user_"):
        await admin_user_details(update, context)
    elif data.startswith("admin_block_"):
        await admin_block_user(update, context)
    elif data.startswith("admin_verify_"):
        await admin_verify_user(update, context)
    elif data.startswith("recommend_"):
        await show_recommendations(update, context)
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
    elif data.startswith("admin_order_"):
        await admin_order_detail(update, context)
    elif data.startswith("admin_force_cancel_"):
        await admin_force_cancel_order(update, context)
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

    # Pastki panel tugmalari
    bottom_btn_map = {
        "🔍 Qidirish": (buyer_search, 'buyer'),
        "📦 Kategoriyalar": (buyer_categories, 'buyer'),
        "🛒 Buyurtmalarim": (buyer_orders, 'buyer'),
        "👤 Profil": None,
        "➕ Mahsulot qo'shish": (seller_add_product_start, 'seller'),
        "📦 Mahsulotlarim": (seller_products, 'seller'),
        "🛒 Buyurtmalar": (seller_orders, 'seller'),
        "🏠 Bosh sahifa": None,
    }

    if text in bottom_btn_map:
        if not user:
            await update.message.reply_text("Iltimos, /start orqali ro'yxatdan o'ting.")
            return

        # Pastki menyu bosilganda — eski search/broadcast holatlarini tozalaymiz
        context.user_data.pop('search_state', None)
        context.user_data.pop('search_query', None)
        context.user_data.pop('broadcasting', None)

        # role o'rniga active_mode — bitta foydalanuvchi ikkala rejimda ishlashi mumkin
        active_mode = get_active_mode(user, context)

        if text == "👤 Profil":
            if active_mode == 'buyer':
                await buyer_profile(update, context)
            elif active_mode == 'seller':
                await seller_profile(update, context)
        elif text == "🏠 Bosh sahifa":
            if user['role'] == 'admin':
                await admin_panel(update, context)
            elif active_mode == 'seller':
                await seller_panel(update, context)
            else:
                await buyer_panel(update, context)
        else:
            fn, required_role = bottom_btn_map[text]
            if active_mode == required_role:
                await fn(update, context)
        return

    # Admin broadcast
    if context.user_data.get('broadcasting'):
        context.user_data['broadcasting'] = False
        users = db.get_all_users()
        sent, failed = 0, 0
        sample_error = None

        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u['telegram_id'],
                    text=f"📢 Admin xabari\n\n{text}"
                )
                sent += 1
            except Exception as e:
                failed += 1
                if sample_error is None:
                    sample_error = str(e)
                logging.error(f"Broadcast failed for {u['telegram_id']}: {e}")

        response = f"✅ {sent} ta foydalanuvchiga yuborildi."
        if failed:
            response += f"\n❌ {failed} ta foydalanuvchiga yuborilmadi."
            if sample_error:
                response += f"\n\nSabab (birinchi xato): {sample_error[:200]}"
            response += (
                "\n\nKo'p uchraydigan sabablar:\n"
                "• Foydalanuvchi botni bloklagan\n"
                "• Foydalanuvchi botga hali /start bermagan\n"
                "• Telegram chat topilmadi"
            )
        await update.message.reply_text(response)
        return

    # Qidiruv — 1-bosqich: mahsulot nomi kiritildi, lokatsiyani so'raymiz
    if context.user_data.get('search_state') == 'awaiting_query':
        context.user_data['search_query'] = text.strip()
        context.user_data['search_state'] = 'awaiting_location'

        location_kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Lokatsiyani yuborish", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        skip_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Lokatsiyasiz qidirish", callback_data="skip_search_location")
        ]])
        await update.message.reply_text(
            "📍 Lokatsiyangizni yuboring — sizga eng yaqin do'konlar birinchi ko'rsatiladi.\n"
            "Yoki lokatsiyasiz davom etish uchun pastdagi tugmani bosing.",
            reply_markup=location_kb,
        )
        await update.message.reply_text(
            "👇 yoki:",
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
                "Lokatsiya o'rniga matn yubordingiz — lokatsiyasiz qidiramiz.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await _show_search_results(update, context, q_text)
        return

    # Noma'lum xabar
    await update.message.reply_text(
        "Buyruqni tanlang:\n"
        "/start — Boshlash\n"
        "/admin — Admin panel\n"
        "/recommend — AI tavsiyalari"
    )


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lokatsiya xabari uchun — hozircha faqat qidiruvning 2-bosqichida ishlatiladi."""
    if context.user_data.get('search_state') == 'awaiting_location':
        loc = update.message.location
        q_text = context.user_data.pop('search_query', None)
        context.user_data.pop('search_state', None)

        if not q_text:
            await update.message.reply_text("Qidiruv bekor qilindi.", reply_markup=ReplyKeyboardRemove())
            return

        await update.message.reply_text(
            f"📍 Lokatsiya qabul qilindi. '{q_text}' bo'yicha qidirilmoqda...",
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
                "⚠️ Kutilmagan xato yuz berdi. Iltimos, qaytadan urinib ko'ring yoki /start bosing."
            )
    except Exception:
        pass


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
                text = (
                    f"⏳ Buyurtma {fmt_order_id(s['id'])} avtomatik bekor qilindi "
                    f"(3 kun ichida tasdiqlanmadi)."
                )
                if order.get('buyer_tg'):
                    try:
                        await context.bot.send_message(chat_id=order['buyer_tg'], text=text)
                    except Exception:
                        pass
                if order.get('seller_tg'):
                    try:
                        await context.bot.send_message(chat_id=order['seller_tg'], text=text)
                    except Exception:
                        pass
            except Exception as e:
                logging.error(f"Stale order notify failed: {e}")
    except Exception as e:
        logging.error(f"cleanup_stale_orders_job failed: {e}")


# ============================================================
# MAIN — HANDLER REGISTRATION (BUG FIX ASOSIY QISMI)
# ============================================================

def main():
    # Persistence — bot qayta ishga tushganda foydalanuvchi sessiyalari saqlanadi
    # (yarim qolgan ro'yxatdan o'tish, qidiruv state, va h.k.)
    persistence = PicklePersistence(filepath="tezbozor_state.pickle")
    app = Application.builder().token(TOKEN).persistence(persistence).build()

    # BUG FIX #5: global_fallbacks ichida faqat command va callback handler'lar
    global_fallbacks = [
        CommandHandler("start", start),
        CommandHandler("admin", admin_command),
        CallbackQueryHandler(button_handler),
    ]

    # --- Registration ConversationHandler ---
    registration_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
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
    product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(seller_add_product_start, pattern="^seller_add_product$")],
        states={
            PRODUCT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_add_product_name)],
            PRODUCT_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_add_product_price)],
            PRODUCT_CATEGORY: [CallbackQueryHandler(seller_add_product_category, pattern="^prodcat_")],
            PRODUCT_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_add_product_desc)],
            PRODUCT_PHOTO:    [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), seller_add_product_photo)],
            PRODUCT_ATTRS:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_add_product_attr_text),
                CallbackQueryHandler(seller_add_product_attr_callback, pattern="^attr_"),
            ],
        },
        fallbacks=global_fallbacks,
    )

    # --- Product edit ConversationHandler ---
    edit_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_product_start, pattern="^edit_start_")],
        states={
            EDIT_PRODUCT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_name),
                                    CommandHandler("skip", edit_product_name)],
            EDIT_PRODUCT_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_price),
                                    CommandHandler("skip", edit_product_price)],
            EDIT_PRODUCT_CATEGORY: [CallbackQueryHandler(edit_product_category, pattern="^editcat_")],
            EDIT_PRODUCT_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_desc),
                                    CommandHandler("skip", edit_product_desc)],
            EDIT_PRODUCT_PHOTO:    [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_product_photo),
                                    CommandHandler("skip", edit_product_photo)],
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

    # --- Rating ---
    rating_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rating_start, pattern="^order_rate_")],
        states={
            RATING:         [CallbackQueryHandler(rating_select, pattern="^rate_")],
            REVIEW_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_submit)],
        },
        fallbacks=global_fallbacks,
    )

    # /admin va /recommend — conversation boshlamaydigan alohida buyruqlar
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("recommend", recommend_command))

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

    # Umumiy handler'lar ENG OXIRIDA
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Global xato ushlovchi — kutilmagan exception bo'lsa, foydalanuvchini xabardor qiladi
    app.add_error_handler(error_handler)

    # Kunlik ishlaydigan job — eski 'pending' buyurtmalarni avtomatik bekor qilish.
    # Bot ishga tushgandan 60 soniyadan keyin birinchi marta, keyin har 24 soatda.
    if app.job_queue:
        app.job_queue.run_repeating(cleanup_stale_orders_job, interval=86400, first=60)
        logging.info("Stale orders cleanup job rejalashtirildi (har 24 soatda)")

    print("🚀 TezBozor Bot ishlamoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()