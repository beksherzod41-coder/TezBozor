import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from database import Database

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "722266370"))

logging.basicConfig(level=logging.INFO)

db = Database()

# ============================================================
# CONVERSATION STATES
# Har bir ConversationHandler o'z alohida state raqamlarini ishlatishi kerak
# Aks holda state'lar bir-birini ustidan yozib ketadi (BUG FIX #1)
# ============================================================
(PHONE, NAME, ROLE, SELLER_CATEGORY, SHOP_NAME, SHOP_LANDMARK,
 SHOP_ADDRESS, WORKING_DAYS, WORKING_HOURS, TELEGRAM_USERNAME) = range(10)

(PRODUCT_NAME, PRODUCT_PRICE, PRODUCT_CATEGORY, PRODUCT_DESC) = range(10, 14)

(EDIT_PRODUCT_NAME, EDIT_PRODUCT_PRICE, EDIT_PRODUCT_CATEGORY, EDIT_PRODUCT_DESC) = range(20, 24)

(ORDER_QUANTITY, ORDER_ADDRESS) = range(30, 32)

MESSAGE_TEXT = 40

(RATING, REVIEW_COMMENT) = range(50, 52)

(EDIT_PROFILE_NAME, EDIT_PROFILE_PHONE,
 EDIT_SHOP_NAME, EDIT_SHOP_LANDMARK, EDIT_SHOP_ADDRESS,
 EDIT_WORKING_DAYS, EDIT_WORKING_HOURS, EDIT_TELEGRAM_USERNAME) = range(60, 68)


# ============================================================
# START & REGISTRATION
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

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
        "👋 TezBozor'ga xush kelibsiz!\n\n"
        "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring:",
        reply_markup=reply_markup
    )
    return PHONE


async def registration_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # BUG FIX #2: CONTACT kelsa contact.phone_number olindi,
    # matn kelsa matn olindi. Lekin filters.TEXT ham CONTACT'ni tutib olmasligini
    # ta'minlash uchun alohida tekshiruv qo'shildi.
    if update.message.contact:
        phone = update.message.contact.phone_number
        if not phone.startswith("+"):
            phone = "+" + phone
        logging.info(f"Contact received: {phone}")
    elif update.message.text:
        phone = update.message.text
        logging.info(f"Text phone received: {phone}")
    else:
        await update.message.reply_text("Iltimos, telefon raqamingizni yuboring:")
        return PHONE

    context.user_data['phone'] = phone

    # Klaviaturani yashiramiz
    await update.message.reply_text(
        "To'liq F.I.SH (Familiya, Ism, Sharifingiz) kiriting:",
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME


async def registration_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Iltimos, ismingizni kiriting:")
        return NAME

    context.user_data['name'] = name

    keyboard = [
        [InlineKeyboardButton("🛒 XARIDOR", callback_data="reg_buyer")],
        [InlineKeyboardButton("🏪 SOTUVCHI", callback_data="reg_seller")],
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
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories")
        categories = cursor.fetchall()
        conn.close()

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
            "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nTezBozor'ga xush kelibsiz!"
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
    context.user_data['shop_name'] = update.message.text.strip()
    await update.message.reply_text("Mo'ljal (yaqin joy, orientir) kiriting:")
    return SHOP_LANDMARK


async def registration_shop_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop_landmark'] = update.message.text.strip()

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
        address = update.message.text
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
    context.user_data['working_days'] = update.message.text.strip()
    await update.message.reply_text("Ish vaqti kiriting (masalan: 09:00 - 21:00):")
    return WORKING_HOURS


async def registration_working_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['working_hours'] = update.message.text.strip()
    await update.message.reply_text(
        "Telegram usernameingiz kiriting (@ bilan, masalan: @username):\n"
        "Agar yo'q bo'lsa — yo'q deb yozing."
    )
    return TELEGRAM_USERNAME


async def registration_telegram_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['telegram_username'] = update.message.text.strip()
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
        "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nTezBozor'ga xush kelibsiz!"
    )

    if role == 'seller':
        await seller_panel(update, context)
    elif role == 'admin':
        await admin_panel(update, context)
    else:
        await buyer_panel(update, context)

    return ConversationHandler.END


# ============================================================
# BUYER PANEL
# ============================================================

async def buyer_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Qidirish", callback_data="buyer_search")],
        [InlineKeyboardButton("📦 Kategoriyalar", callback_data="buyer_categories")],
        [InlineKeyboardButton("🛒 Buyurtmalarim", callback_data="buyer_orders")],
        [InlineKeyboardButton("⭐ Reytinglarim", callback_data="buyer_reviews")],
        [InlineKeyboardButton("👤 Profil", callback_data="buyer_profile")],
    ]

    text = "🛒 XARIDOR PANELI\n\nTanlang:"

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
    await query.answer()

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    conn.close()

    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"cat_{cat[0]}")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")])

    await query.edit_message_text("📦 Kategoriyalar:", reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_category_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    products = db.search_products(category_id=category_id)

    if not products:
        await query.edit_message_text(
            "Bu kategoriyada mahsulotlar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")]])
        )
        return

    keyboard = []
    for product in products[:10]:
        rating = product.get('avg_rating') or 0
        keyboard.append([
            InlineKeyboardButton(
                f"⭐{rating:.1f} | {product['name']} — {product['price']:,.0f} so'm",
                callback_data=f"prod_{product['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")])

    await query.edit_message_text("📦 Mahsulotlar:", reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, c.name as category_name, u.shop_name, u.shop_address, u.shop_landmark,
               u.shop_lat, u.shop_lon, u.working_days, u.working_hours,
               u.telegram_username, u.phone_number,
               (SELECT AVG(rating) FROM reviews WHERE seller_id = p.seller_id) as avg_rating
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN users u ON p.seller_id = u.id
        WHERE p.id = ?
    """, (product_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("Mahsulot topilmadi.")
        return

    columns = [desc[0] for desc in cursor.description]
    product = dict(zip(columns, row))
    rating = product['avg_rating'] or 0

    map_link = ""
    if product.get('shop_lat') and product.get('shop_lon'):
        map_link = f"\n🗺️ [Xaritada ko'rish](https://www.google.com/maps/search/?api=1&query={product['shop_lat']},{product['shop_lon']})"

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
            url=f"tel:{product['phone_number']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_categories")])

    await query.edit_message_text(
        f"📦 *{product['name']}*\n\n"
        f"💰 Narxi: *{product['price']:,.0f} so'm*\n"
        f"🏪 Do'kon: {product.get('shop_name', 'Nomaʼlum')}\n"
        f"📍 Manzil: {product.get('shop_address', 'Koʼrsatilmagan')}\n"
        f"🎯 Moʼljal: {product.get('shop_landmark', 'Koʼrsatilmagan')}{map_link}\n"
        f"⭐ Reyting: {rating:.1f}/5.0\n"
        f"🕐 Ish vaqti: {product.get('working_hours', 'Koʼrsatilmagan')}\n"
        f"📅 Ish kunlari: {product.get('working_days', 'Koʼrsatilmagan')}\n"
        f"📝 Tavsif: {product.get('description') or 'Yoʼq'}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def buyer_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # BUG FIX #3: buyer_search ni callback ham, message handler ham chaqirishi mumkin.
    # context.user_data['searching'] = True qo'yib, text_handler'ga ishlov beramiz.
    context.user_data['searching'] = True

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🔍 Qidirish uchun mahsulot nomini kiriting:")
    else:
        await update.message.reply_text("🔍 Qidirish uchun mahsulot nomini kiriting:")


async def buyer_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_buyer(user['id'])

    if not orders:
        await query.edit_message_text(
            "Sizda hali buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = []
    for order in orders[:10]:
        keyboard.append([InlineKeyboardButton(
            f"{status_emoji.get(order['status'], '❓')} {order['product_name']} — {order['total_price']:,.0f} so'm",
            callback_data=f"order_detail_{order['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")])

    await query.edit_message_text("🛒 Buyurtmalarim:", reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    keyboard = [
        [InlineKeyboardButton("✏️ Ismni tahrirlash", callback_data="edit_buyer_name")],
        [InlineKeyboardButton("✏️ Telefonni tahrirlash", callback_data="edit_buyer_phone")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")],
    ]
    text = (
        f"👤 XARIDOR PROFILI\n\n"
        f"Ism: {user['name']}\n"
        f"Telefon: {user['phone_number']}\n"
        f"Ro'yxatdan o'tgan: {user['created_at']}"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buyer_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, p.name as product_name, p.price as product_price,
               u.shop_name, u.phone_number as seller_phone
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.seller_id = u.id
        WHERE o.id = ?
    """, (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("Buyurtma topilmadi.")
        return

    columns = [desc[0] for desc in cursor.description]
    order = dict(zip(columns, row))
    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}

    keyboard = [
        [InlineKeyboardButton("💬 Xabar yuborish", callback_data=f"order_msg_{order_id}")],
        [InlineKeyboardButton("⭐ Reyting qoldirish", callback_data=f"order_rate_{order_id}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_orders")],
    ]

    await query.edit_message_text(
        f"🛒 Buyurtma #{order['id']}\n\n"
        f"Mahsulot: {order['product_name']}\n"
        f"Narxi: {order['product_price']:,.0f} so'm\n"
        f"Soni: {order['quantity']}\n"
        f"Jami: {order['total_price']:,.0f} so'm\n"
        f"Holat: {status_emoji.get(order['status'], '❓')} {order['status']}\n"
        f"Do'kon: {order['shop_name']}\n"
        f"Telefon: {order['seller_phone']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# SELLER PANEL
# ============================================================

async def seller_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)

    keyboard = [
        [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="seller_add_product")],
        [InlineKeyboardButton("📦 Mahsulotlarim", callback_data="seller_products")],
        [InlineKeyboardButton("🛒 Buyurtmalar", callback_data="seller_orders")],
        [InlineKeyboardButton("💬 Xabarlar", callback_data="seller_messages")],
        [InlineKeyboardButton("⭐ Reytinglar", callback_data="seller_reviews")],
        [InlineKeyboardButton("👤 Profil", callback_data="seller_profile")],
    ]

    text = (
        f"🏪 SOTUVCHI PANELI\n\n"
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


async def seller_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['adding_product'] = True
    await query.edit_message_text("Mahsulot nomini kiriting:")
    return PRODUCT_NAME


async def seller_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['product_name'] = update.message.text.strip()
    await update.message.reply_text("Mahsulot narxini kiriting (so'm):")
    return PRODUCT_PRICE


async def seller_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.replace(" ", "").replace(",", ""))
        context.user_data['product_price'] = price
    except ValueError:
        await update.message.reply_text("❌ Iltimos, to'g'ri raqam kiriting (masalan: 50000):")
        return PRODUCT_PRICE

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    conn.close()

    keyboard = [[InlineKeyboardButton(f"{cat[2]} {cat[1]}", callback_data=f"prodcat_{cat[0]}")] for cat in categories]
    await update.message.reply_text("Kategoriyani tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return PRODUCT_CATEGORY


async def seller_add_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    context.user_data['product_category'] = category_id

    await query.edit_message_text("Mahsulot tavsifini kiriting (ixtiyoriy, o'tkazib yuborish uchun \"-\" yozing):")
    return PRODUCT_DESC


async def seller_add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    context.user_data['adding_product'] = False

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.create_product(
        seller_id=user['id'],
        name=context.user_data['product_name'],
        price=context.user_data['product_price'],
        category_id=context.user_data['product_category'],
        description=desc
    )

    await update.message.reply_text("✅ Mahsulot muvaffaqiyatli qo'shildi!")
    await seller_panel(update, context)
    return ConversationHandler.END


async def seller_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    products = db.get_products_by_seller(user['id'])

    if not products:
        await query.edit_message_text(
            "Sizda hali mahsulotlar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        )
        return

    keyboard = []
    for product in products:
        icon = "✅" if product["in_stock"] else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {product['name']} — {product['price']:,.0f} so'm",
            callback_data=f"prod_menu_{product['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")])

    await query.edit_message_text("📦 Mahsulotlarim:", reply_markup=InlineKeyboardMarkup(keyboard))


async def seller_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])
    context.user_data['editing_product_id'] = product_id

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("Mahsulot topilmadi.")
        return

    columns = [desc[0] for desc in cursor.description]
    product = dict(zip(columns, row))

    status_text = "✅ Sotuvda" if product['in_stock'] else "❌ Sotuvda yo'q"
    toggle_btn = "❌ Sotuvdan olish" if product['in_stock'] else "✅ Sotuvga qo'yish"

    keyboard = [
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_start_{product_id}")],
        [InlineKeyboardButton(toggle_btn, callback_data=f"toggle_stock_{product_id}")],
        [InlineKeyboardButton("🗑️ O'chirish", callback_data=f"delete_prod_{product_id}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_products")],
    ]

    await query.edit_message_text(
        f"📦 *{product['name']}*\n\n"
        f"Narxi: {product['price']:,.0f} so'm\n"
        f"Holat: {status_text}\n"
        f"Tavsif: {product.get('description') or 'Yoʼq'}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def toggle_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT in_stock FROM products WHERE id = ?", (product_id,))
    result = cursor.fetchone()

    if result:
        new_status = 0 if result[0] else 1
        cursor.execute("UPDATE products SET in_stock = ? WHERE id = ?", (new_status, product_id))
        conn.commit()
    conn.close()

    # Menyu qaytadan ko'rsatiladi
    context.user_data['editing_product_id'] = product_id
    # prod_menu_ pattern bilan seller_product_menu'ni chaqiramiz
    class FakeQuery:
        data = f"prod_menu_{product_id}"
    query.data = f"prod_menu_{product_id}"
    await seller_product_menu(update, context)


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
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

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
        context.user_data['edit_product_name'] = update.message.text.strip()
    await update.message.reply_text("Mahsulot narxini kiriting (so'm) yoki /skip:")
    return EDIT_PRODUCT_PRICE


async def edit_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        try:
            price = float(update.message.text.replace(" ", "").replace(",", ""))
            context.user_data['edit_product_price'] = price
        except ValueError:
            await update.message.reply_text("❌ To'g'ri raqam kiriting yoki /skip:")
            return EDIT_PRODUCT_PRICE

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    conn.close()

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
        context.user_data['edit_product_desc'] = update.message.text.strip()

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

    if update_data:
        conn = db.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k} = ?" for k in update_data.keys()])
        values = list(update_data.values()) + [product_id]
        cursor.execute(f"UPDATE products SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()

    await update.message.reply_text("✅ Mahsulot yangilandi!")
    await seller_panel(update, context)
    return ConversationHandler.END


async def seller_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    orders = db.get_orders_by_seller(user['id'])

    if not orders:
        await query.edit_message_text(
            "Sizda hali buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")]])
        )
        return

    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}
    keyboard = []
    for order in orders[:10]:
        keyboard.append([InlineKeyboardButton(
            f"{status_emoji.get(order['status'], '❓')} {order['buyer_name']} — {order['total_price']:,.0f} so'm",
            callback_data=f"seller_order_{order['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")])

    await query.edit_message_text("🛒 Buyurtmalar:", reply_markup=InlineKeyboardMarkup(keyboard))


async def seller_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_telegram_id(update.effective_user.id)
    avg_rating = db.get_seller_avg_rating(user['id'])

    keyboard = [
        [InlineKeyboardButton("✏️ Do'kon nomi", callback_data="edit_shop_name")],
        [InlineKeyboardButton("✏️ Manzil", callback_data="edit_shop_address")],
        [InlineKeyboardButton("✏️ Mo'ljal", callback_data="edit_shop_landmark")],
        [InlineKeyboardButton("✏️ Ish kunlari", callback_data="edit_working_days")],
        [InlineKeyboardButton("✏️ Ish vaqti", callback_data="edit_working_hours")],
        [InlineKeyboardButton("✏️ Telegram", callback_data="edit_telegram")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_panel")],
    ]

    text = (
        f"🏪 SOTUVCHI PROFILI\n\n"
        f"Do'kon: {user.get('shop_name', 'Koʼrsatilmagan')}\n"
        f"Manzil: {user.get('shop_address', 'Koʼrsatilmagan')}\n"
        f"Moʼljal: {user.get('shop_landmark', 'Koʼrsatilmagan')}\n"
        f"Ish kunlari: {user.get('working_days', 'Koʼrsatilmagan')}\n"
        f"Ish vaqti: {user.get('working_hours', 'Koʼrsatilmagan')}\n"
        f"Telegram: {user.get('telegram_username', 'Koʼrsatilmagan')}\n"
        f"Telefon: {user.get('phone_number', 'Koʼrsatilmagan')}\n"
        f"⭐ Reyting: {avg_rating:.1f}/5.0\n"
        f"Ro'yxatdan o'tgan: {user['created_at']}"
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
    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], name=update.message.text.strip())
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
        if not phone.startswith("+"):
            phone = "+" + phone
    else:
        phone = update.message.text.strip()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    db.update_user(user['id'], phone_number=phone)
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


async def seller_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, p.name as product_name, p.price as product_price,
               u.name as buyer_name, u.phone_number as buyer_phone
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.buyer_id = u.id
        WHERE o.id = ?
    """, (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("Buyurtma topilmadi.")
        return

    columns = [desc[0] for desc in cursor.description]
    order = dict(zip(columns, row))
    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'delivered': '🚚', 'cancelled': '❌'}

    keyboard = []
    if order['status'] == 'pending':
        keyboard.append([InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}")])
        keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_order_{order_id}")])
    elif order['status'] == 'confirmed':
        keyboard.append([InlineKeyboardButton("🚚 Yetkazib berildi", callback_data=f"deliver_order_{order_id}")])
    keyboard.append([InlineKeyboardButton("💬 Xabar yuborish", callback_data=f"order_msg_{order_id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="seller_orders")])

    await query.edit_message_text(
        f"🛒 Buyurtma #{order['id']}\n\n"
        f"Mahsulot: {order['product_name']}\n"
        f"Narxi: {order['product_price']:,.0f} so'm\n"
        f"Soni: {order['quantity']}\n"
        f"Jami: {order['total_price']:,.0f} so'm\n"
        f"Holat: {status_emoji.get(order['status'], '❓')} {order['status']}\n"
        f"Xaridor: {order['buyer_name']}\n"
        f"Telefon: {order['buyer_phone']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
        db.update_order_status(order_id, new_status)

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

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT buyer_id, seller_id FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    conn.close()

    if order:
        receiver_id = order[1] if user['role'] == 'buyer' else order[0]
        db.create_message(order_id, user['id'], receiver_id, message_text)
        await update.message.reply_text("✅ Xabar yuborildi!")

    if user['role'] == 'seller':
        await seller_panel(update, context)
    else:
        await buyer_panel(update, context)

    return ConversationHandler.END


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

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT seller_id FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    conn.close()

    if order:
        db.create_review(order_id, order[0], user['id'], rating, comment)
        await update.message.reply_text("✅ Rahmat! Reyting qabul qilindi.")

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
        f"🔧 *ADMIN PANELI*\n\n"
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


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 20")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if not rows:
        await query.edit_message_text("Foydalanuvchilar yo'q.")
        return

    keyboard = []
    for row in rows:
        user = dict(zip(columns, row))
        status = "🟢" if not user['is_blocked'] else "🔴"
        role_emoji = {"buyer": "🛒", "seller": "🏪", "admin": "🔧"}
        keyboard.append([InlineKeyboardButton(
            f"{status} {role_emoji.get(user['role'], '❓')} {user['name'] or 'Anonim'}",
            callback_data=f"admin_user_{user['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"👥 Foydalanuvchilar ({len(rows)} ta):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if not row:
        await query.edit_message_text("Foydalanuvchi topilmadi.")
        return

    user = dict(zip(columns, row))
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
        f"Ro'yxatdan o'tgan: {user['created_at']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        if result[0]:
            db.unblock_user(user_id)
        else:
            db.block_user(user_id)

    # admin_user_details ni chaqirish uchun query.data ni to'g'irlaymiz
    query.data = f"admin_user_{user_id}"
    await admin_user_details(update, context)


async def admin_verify_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("_")[2])

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_verified FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        db.update_user(user_id, is_verified=0 if result[0] else 1)

    query.data = f"admin_user_{user_id}"
    await admin_user_details(update, context)


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
        f"{p['name']} — {p['price']:,.0f} so'm",
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
        f"{status_emoji.get(o['status'], '❓')} #{o['id']} — {o['total_price']:,.0f} so'm",
        callback_data=f"admin_order_{o['id']}"
    )] for o in orders[:20]]
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"🛒 Buyurtmalar (Jami: {len(orders)}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    users = db.get_all_users()
    products = db.get_all_products()
    orders = db.get_all_orders()

    buyers = [u for u in users if u['role'] == 'buyer']
    sellers = [u for u in users if u['role'] == 'seller']

    await query.edit_message_text(
        f"📊 *STATISTIKA*\n\n"
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


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['broadcasting'] = True
    await query.edit_message_text("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni kiriting:")


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        f"⚙️ *SOZLAMALAR*\n\nBot versiyasi: 1.0.0\nAdmin ID: {ADMIN_ID}\n\nTezBozor Marketplace Bot",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_panel")]]),
        parse_mode='Markdown'
    )


# ============================================================
# AI RECOMMENDATIONS
# ============================================================

async def ai_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.name, p.price, COUNT(o.id) as order_count
        FROM products p
        LEFT JOIN orders o ON o.product_id = p.id
        WHERE p.in_stock = 1
        GROUP BY p.id
        ORDER BY order_count DESC, p.created_at DESC
        LIMIT 10
    """)
    products = cursor.fetchall()
    conn.close()

    if not products:
        await update.message.reply_text("Hali mahsulotlar yo'q.")
        return

    keyboard = [[InlineKeyboardButton(
        f"🤖 {p[1]} — {p[2]:,.0f} so'm",
        callback_data=f"prod_{p[0]}"
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
    }

    if data in handlers:
        await handlers[data](update, context)
    elif data.startswith("cat_"):
        await buyer_category_products(update, context)
    elif data.startswith("prod_menu_"):
        await seller_product_menu(update, context)
    elif data.startswith("prod_"):
        await buyer_product_details(update, context)
    elif data.startswith("toggle_stock_"):
        await toggle_product_stock(update, context)
    elif data.startswith("delete_prod_") or data.startswith("delete_confirm_"):
        await delete_product(update, context)
    elif data.startswith("order_detail_"):
        await buyer_order_detail(update, context)
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


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = db.get_user_by_telegram_id(update.effective_user.id)

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

        if text == "👤 Profil":
            if user['role'] == 'buyer':
                await buyer_profile(update, context)
            elif user['role'] == 'seller':
                await seller_profile(update, context)
        elif text == "🏠 Bosh sahifa":
            if user['role'] == 'buyer':
                await buyer_panel(update, context)
            elif user['role'] == 'seller':
                await seller_panel(update, context)
            elif user['role'] == 'admin':
                await admin_panel(update, context)
        else:
            fn, required_role = bottom_btn_map[text]
            if user['role'] == required_role:
                await fn(update, context)
        return

    # Admin broadcast
    if context.user_data.get('broadcasting'):
        context.user_data['broadcasting'] = False
        users = db.get_all_users()
        sent, failed = 0, 0

        for u in users:
            try:
                await update.message.bot.send_message(
                    chat_id=u['telegram_id'],
                    text=f"📢 *ADMIN XABARI*\n\n{text}",
                    parse_mode='Markdown'
                )
                sent += 1
            except Exception as e:
                failed += 1
                logging.error(f"Broadcast failed for {u['telegram_id']}: {e}")

        response = f"✅ {sent} ta foydalanuvchiga yuborildi."
        if failed:
            response += f"\n❌ {failed} ta foydalanuvchiga yuborilmadi."
        await update.message.reply_text(response)
        return

    # Qidiruv
    if context.user_data.get('searching'):
        context.user_data['searching'] = False
        products = db.search_products(query=text)

        if not products:
            await update.message.reply_text(
                "❌ Mahsulot topilmadi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])
            )
            return

        for product in products[:5]:
            rating = product.get('avg_rating') or 0
            map_link = ""
            if product.get('shop_lat') and product.get('shop_lon'):
                map_link = f"\n🗺️ [Xaritada ko'rish](https://www.google.com/maps/search/?api=1&query={product['shop_lat']},{product['shop_lon']})"

            contact_keyboard = []
            if product.get('telegram_username'):
                contact_keyboard.append([InlineKeyboardButton(
                    "📱 Telegram",
                    url=f"https://t.me/{product['telegram_username'].replace('@', '')}"
                )])
            if product.get('phone_number'):
                contact_keyboard.append([InlineKeyboardButton(
                    "📞 Telefon",
                    url=f"tel:{product['phone_number']}"
                )])
            contact_keyboard.append([InlineKeyboardButton("📦 Batafsil", callback_data=f"prod_{product['id']}")])

            await update.message.reply_text(
                f"{product.get('category_emoji', '📦')} *{product['name']}*\n\n"
                f"💰 *{product['price']:,.0f} so'm*\n"
                f"🏪 {product.get('shop_name', 'Nomaʼlum')}\n"
                f"📍 {product.get('shop_address', 'Nomaʼlum')}{map_link}\n"
                f"⭐ Reyting: {rating:.1f}/5.0",
                reply_markup=InlineKeyboardMarkup(contact_keyboard),
                parse_mode='Markdown'
            )

        await update.message.reply_text(
            f"🔍 '{text}' bo'yicha {min(len(products), 5)} ta natija topildi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="buyer_panel")]])
        )
        return

    # Noma'lum xabar
    await update.message.reply_text(
        "Buyruqni tanlang:\n"
        "/start — Boshlash\n"
        "/admin — Admin panel\n"
        "/recommend — AI tavsiyalari"
    )


# ============================================================
# MAIN — HANDLER REGISTRATION (BUG FIX ASOSIY QISMI)
# ============================================================

def main():
    app = Application.builder().token(TOKEN).build()

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
        },
        fallbacks=global_fallbacks,
    )

    # --- Product edit ConversationHandler ---
    edit_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_product_start, pattern="^edit_start_")],
        states={
            EDIT_PRODUCT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_name)],
            EDIT_PRODUCT_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_price)],
            EDIT_PRODUCT_CATEGORY: [CallbackQueryHandler(edit_product_category, pattern="^editcat_")],
            EDIT_PRODUCT_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_desc)],
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

    # ConversationHandler'lar — /start ichida boshlanadi
    app.add_handler(registration_conv)
    app.add_handler(product_conv)
    app.add_handler(edit_product_conv)
    app.add_handler(buyer_profile_edit_conv)
    app.add_handler(seller_profile_edit_conv)
    app.add_handler(message_conv)
    app.add_handler(rating_conv)

    # Umumiy handler'lar ENG OXIRIDA
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 TezBozor Bot ishlamoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()