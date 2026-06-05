
"""TezBozor — ko'p tilli qo'llab-quvvatlash (i18n): O'zbek + Rus.

Foydalanish:
    from languages import t, LANGS, DEFAULT_LANG
    t('uz', 'welcome')        → lang string bilan
    t(user_dict, 'welcome')   → user qatori bilan (user['language'] o'qiladi)
    t(lang, 'greet', name=x)  → format parametrlari bilan
"""

LANGS = {
    'uz': "🇺🇿 O'zbek",
    'ru': "🇷🇺 Русский",
}

DEFAULT_LANG = 'uz'

# ============================================================
# TARJIMALAR  {kalit: {'uz': ..., 'ru': ...}}
# ============================================================

_TEXTS = {
    # --- UMUMIY ---
    'welcome': {
        'uz': "👋 TezBozorga xush kelibsiz!",
        'ru': "👋 Добро пожаловать в TezBozor!",
    },
    'registration_success': {
        'uz': "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nTezBozorga xush kelibsiz!",
        'ru': "✅ Регистрация прошла успешно!\n\nДобро пожаловать в TezBozor!",
    },
    'blocked': {
        'uz': "⛔ Siz bloklangansiz. Admin bilan bog'laning.",
        'ru': "⛔ Вы заблокированы. Свяжитесь с администратором.",
    },
    'not_registered': {
        'uz': "Iltimos, avval ro'yxatdan o'ting: /start",
        'ru': "Пожалуйста, сначала зарегистрируйтесь: /start",
    },
    'not_registered_short': {
        'uz': "Iltimos, /start orqali ro'yxatdan o'ting.",
        'ru': "Пожалуйста, зарегистрируйтесь через /start.",
    },
    'cancelled': {
        'uz': "❌ Jarayon bekor qilindi.",
        'ru': "❌ Процесс отменён.",
    },
    'error_unexpected': {
        'uz': "⚠️ Kutilmagan xato yuz berdi. Iltimos, qaytadan urinib ko'ring yoki /start bosing.",
        'ru': "⚠️ Произошла непредвиденная ошибка. Попробуйте снова или нажмите /start.",
    },
    'back': {
        'uz': "⬅️ Orqaga",
        'ru': "⬅️ Назад",
    },
    'bottom_hint': {
        'uz': "Quyidagi tugmalardan ham foydalanishingiz mumkin:",
        'ru': "Вы также можете пользоваться кнопками ниже:",
    },
    'you_are_admin': {
        'uz': "✅ Siz admin bo'ldingiz!",
        'ru': "✅ Вы стали администратором!",
    },
    'not_admin': {
        'uz': "⛔ Siz admin emassiz!",
        'ru': "⛔ Вы не администратор!",
    },

    # --- TIL TANLASH ---
    'choose_language': {
        'uz': "🌐 Tilni tanlang:",
        'ru': "🌐 Выберите язык:",
    },
    'btn_change_language': {
        'uz': "🌐 Tilni o'zgartirish",
        'ru': "🌐 Сменить язык",
    },
    'language_changed': {
        'uz': "✅ Til o'zgartirildi: O'zbek",
        'ru': "✅ Язык изменён: Русский",
    },

    # --- RO'YXATDAN O'TISH ---
    'ask_phone': {
        'uz': "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring:",
        'ru': "Для регистрации отправьте ваш номер телефона:",
    },
    'welcome_ask_phone': {
        'uz': "👋 TezBozorga xush kelibsiz!\n\nRo'yxatdan o'tish uchun telefon raqamingizni yuboring:",
        'ru': "👋 Добро пожаловать в TezBozor!\n\nДля регистрации отправьте ваш номер телефона:",
    },
    'phone_button': {
        'uz': "📞 Telefon raqamni yuborish",
        'ru': "📞 Отправить номер телефона",
    },
    'phone_send_prompt': {
        'uz': "Iltimos, telefon raqamingizni yuboring:",
        'ru': "Пожалуйста, отправьте ваш номер телефона:",
    },
    'phone_invalid': {
        'uz': "❌ Telefon raqami noto'g'ri.\nMisol: +998901234567 yoki tugmadan foydalaning.",
        'ru': "❌ Неверный номер телефона.\nПример: +998901234567 или используйте кнопку.",
    },
    'ask_name': {
        'uz': "To'liq F.I.SH (Familiya, Ism, Sharifingiz) kiriting:",
        'ru': "Введите ваше полное ФИО (Фамилия, Имя, Отчество):",
    },
    'name_invalid': {
        'uz': ("❌ To'liq F.I.SH kiriting — kamida Familiya va Ism (faqat harflar).\n"
               "Masalan: Karimov Sherzod"),
        'ru': ("❌ Введите полное ФИО — минимум фамилия и имя (только буквы).\n"
               "Например: Каримов Шерзод"),
    },
    'name_thanks_role': {
        'uz': "Rahmat, {name}!\n\nO'zingizga rol tanlang:",
        'ru': "Спасибо, {name}!\n\nВыберите вашу роль:",
    },
    'ask_role': {
        'uz': "O'zingizga rol tanlang:",
        'ru': "Выберите вашу роль:",
    },
    'role_buyer': {
        'uz': "🛒 Xaridor",
        'ru': "🛒 Покупатель",
    },
    'role_seller': {
        'uz': "🏪 Sotuvchi",
        'ru': "🏪 Продавец",
    },
    'seller_category_ask': {
        'uz': "Qaysi bo'lim uchun sotuvchi bo'lmoqchisiz?",
        'ru': "В каком разделе вы хотите быть продавцом?",
    },
    'shop_name_ask': {
        'uz': "Do'kon nomingizni kiriting:",
        'ru': "Введите название вашего магазина:",
    },
    'shop_name_invalid': {
        'uz': "❌ Do'kon nomi 2-80 belgi bo'lishi kerak. Qaytadan kiriting:",
        'ru': "❌ Название магазина должно быть от 2 до 80 символов. Введите заново:",
    },
    'shop_landmark_ask': {
        'uz': "Mo'ljal (yaqin joy, orientir) kiriting:",
        'ru': "Введите ориентир (ближайшее заметное место):",
    },
    'shop_landmark_too_long': {
        'uz': "❌ Mo'ljal juda uzun (maks. 200 belgi):",
        'ru': "❌ Ориентир слишком длинный (макс. 200 символов):",
    },
    'shop_address_ask': {
        'uz': "Do'kon manzilingizni yuboring (lokatsiya yoki matn):",
        'ru': "Отправьте адрес магазина (геолокация или текст):",
    },
    'send_location_button': {
        'uz': "📍 Manzilni yuborish",
        'ru': "📍 Отправить геолокацию",
    },
    'address_detected': {
        'uz': "📍 Aniqlangan manzil: {address}",
        'ru': "📍 Определённый адрес: {address}",
    },
    'address_invalid': {
        'uz': "❌ Manzil 5-200 belgi bo'lishi kerak. Qaytadan:",
        'ru': "❌ Адрес должен быть от 5 до 200 символов. Введите заново:",
    },
    'working_days_ask': {
        'uz': "Ish kunlari kiriting (masalan: Dush-Shan, Chor-Juma):",
        'ru': "Введите рабочие дни (например: Пн-Сб):",
    },
    'working_days_too_long': {
        'uz': "❌ Juda uzun. Qisqaroq yozing (maks. 100 belgi):",
        'ru': "❌ Слишком длинно. Короче (макс. 100 символов):",
    },
    'working_hours_ask': {
        'uz': "Ish vaqti kiriting (masalan: 09:00-21:00):",
        'ru': "Введите рабочее время (например: 09:00-21:00):",
    },
    'working_hours_too_long': {
        'uz': "❌ Juda uzun. Qisqaroq yozing (maks. 50 belgi):",
        'ru': "❌ Слишком длинно. Короче (макс. 50 символов):",
    },
    'username_ask': {
        'uz': ("Telegram usernameingiz kiriting (@ bilan, masalan: @username):\n"
               "Agar yo'q bo'lsa — '-' yozing."),
        'ru': ("Введите ваш Telegram username (с @, например: @username):\n"
               "Если нет — напишите '-'."),
    },
    'username_invalid': {
        'uz': ("❌ Username noto'g'ri.\n"
               "Lotin harfi bilan boshlanishi va 5-32 belgi bo'lishi kerak (a-z, 0-9, _).\n"
               "Misol: @ali_2024\nYoki '-' yozing:"),
        'ru': ("❌ Неверный username.\n"
               "Должен начинаться с латинской буквы, 5-32 символа (a-z, 0-9, _).\n"
               "Пример: @ali_2024\nИли напишите '-':"),
    },
    'reg_success_seller': {
        'uz': ("✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
               "⏳ Sotuvchi sifatida ishlash uchun admin tasdiqlashi kerak.\n"
               "Tez orada javob beramiz. Shu vaqtda xaridor sifatida foydalanishingiz mumkin."),
        'ru': ("✅ Регистрация прошла успешно!\n\n"
               "⏳ Для работы продавцом требуется подтверждение администратора.\n"
               "Скоро ответим. Пока можете пользоваться как покупатель."),
    },
    'new_referral': {
        'uz': "🎉 Yangi taklif! <b>{name}</b> sizning havolangiz orqali ro'yxatdan o'tdi.",
        'ru': "🎉 Новый реферал! <b>{name}</b> зарегистрировался по вашей ссылке.",
    },

    # --- XARIDOR PANELI ---
    'buyer_panel_title': {
        'uz': "🛒 Xaridor paneli\n\nTanlang:",
        'ru': "🛒 Панель покупателя\n\nВыберите:",
    },
    'btn_search': {
        'uz': "🔍 Qidirish",
        'ru': "🔍 Поиск",
    },
    'btn_shop_search': {
        'uz': "🏪 Do'kon qidirish",
        'ru': "🏪 Поиск магазина",
    },
    'btn_categories': {
        'uz': "📦 Kategoriyalar",
        'ru': "📦 Категории",
    },
    'btn_search_menu': {
        'uz': "🔍 Qidiruv",
        'ru': "🔍 Поиск",
    },
    'search_menu_title': {
        'uz': "🔍 <b>Qidiruv</b>\n\nNima qidiramiz? Bo'limni tanlang:",
        'ru': "🔍 <b>Поиск</b>\n\nЧто ищем? Выберите раздел:",
    },
    'btn_my_orders': {
        'uz': "🛒 Buyurtmalarim",
        'ru': "🛒 Мои заказы",
    },
    'btn_messages': {
        'uz': "💬 Xabarlar",
        'ru': "💬 Сообщения",
    },
    'btn_reviews': {
        'uz': "⭐ Reytinglarim",
        'ru': "⭐ Мои отзывы",
    },
    'btn_profile': {
        'uz': "👤 Profil",
        'ru': "👤 Профиль",
    },
    'btn_seller_mode': {
        'uz': "🏪 Sotuvchi rejimi",
        'ru': "🏪 Режим продавца",
    },
    'btn_become_seller': {
        'uz': "🏪 Sotuvchi bo'lish",
        'ru': "🏪 Стать продавцом",
    },
    'btn_contact_admin': {
        'uz': "🆘 Admin bilan bog'lanish",
        'ru': "🆘 Связаться с админом",
    },
    'btn_home': {
        'uz': "🏠 Bosh sahifa",
        'ru': "🏠 Главная",
    },

    # --- KANALNI ULASH ---
    'btn_link_channel': {
        'uz': "📢 Kanalimni ulash",
        'ru': "📢 Подключить мой канал",
    },
    'link_channel_prompt': {
        'uz': ("📢 <b>Kanalingizni ulash</b>\n\n"
               "Mahsulotlaringiz avtomatik o'z kanalingizga ham chiqishi uchun:\n\n"
               "1️⃣ Botni (@{bot}) kanalingizga <b>admin</b> qilib qo'shing — "
               "\"Post Messages\" (xabar yuborish) ruxsati bilan.\n"
               "2️⃣ So'ng kanalingizdan <b>istalgan postni</b> shu yerga <b>forward</b> qiling.\n\n"
               "Men kanalni avtomatik aniqlab, ulab qo'yaman.\n\n"
               "❌ Bekor qilish: /cancel"),
        'ru': ("📢 <b>Подключение вашего канала</b>\n\n"
               "Чтобы ваши товары автоматически публиковались и в вашем канале:\n\n"
               "1️⃣ Добавьте бота (@{bot}) в свой канал как <b>администратора</b> — "
               "с правом «Post Messages» (отправка сообщений).\n"
               "2️⃣ Затем <b>перешлите</b> сюда <b>любой пост</b> из вашего канала.\n\n"
               "Я автоматически определю канал и подключу его.\n\n"
               "❌ Отмена: /cancel"),
    },
    'link_channel_success': {
        'uz': ("✅ Kanal ulandi: <b>{title}</b>\n\n"
               "Endi qo'shgan (yoki qayta sotuvga qo'ygan) mahsulotlaringiz "
               "avtomatik shu kanalga ham chiqadi."),
        'ru': ("✅ Канал подключён: <b>{title}</b>\n\n"
               "Теперь добавленные (или повторно выставленные) товары "
               "будут автоматически публиковаться и в этом канале."),
    },
    'link_channel_not_channel': {
        'uz': ("❌ Bu kanal posti emas.\n\n"
               "Iltimos, o'z <b>kanalingizdan</b> istalgan postni shu yerga forward qiling "
               "(guruh yoki shaxsiy xabar emas — aynan kanal posti)."),
        'ru': ("❌ Это не пост из канала.\n\n"
               "Пожалуйста, перешлите сюда любой пост именно из вашего <b>канала</b> "
               "(не из группы и не личное сообщение)."),
    },
    'link_channel_not_admin': {
        'uz': ("❌ Men bu kanalda admin emasman.\n\n"
               "Avval @{bot} ni kanalingizga <b>admin</b> qilib qo'shing "
               "(\"Post Messages\" ruxsati bilan), so'ng postni qayta forward qiling."),
        'ru': ("❌ Я не администратор этого канала.\n\n"
               "Сначала добавьте @{bot} в канал как <b>администратора</b> "
               "(с правом «Post Messages»), затем перешлите пост заново."),
    },
    'link_channel_no_post_perm': {
        'uz': ("❌ Men kanalda adminman, lekin <b>post yuborish</b> ruxsatim yo'q.\n\n"
               "Kanal sozlamalaridan menga \"Post Messages\" ruxsatini yoqing va qayta urinib ko'ring."),
        'ru': ("❌ Я администратор канала, но у меня нет права <b>публикации</b>.\n\n"
               "Включите для меня право «Post Messages» в настройках канала и попробуйте снова."),
    },
    'link_channel_already': {
        'uz': "ℹ️ Bu kanal allaqachon ulangan.",
        'ru': "ℹ️ Этот канал уже подключён.",
    },
    'link_channel_shared_warn': {
        'uz': ("⚠️ <b>Diqqat:</b> bu kanalni boshqa sotuvchi ham ulagan. "
               "Mahsulotlaringiz baribir bu kanalga chiqadi, lekin kanal sizniki ekanligiga ishonch hosil qiling."),
        'ru': ("⚠️ <b>Внимание:</b> этот канал подключил и другой продавец. "
               "Ваши товары всё равно будут публиковаться в нём, но убедитесь, что канал действительно ваш."),
    },
    'channel_deactivated_notify': {
        'uz': ("⚠️ <b>Kanal uzildi</b>\n\n"
               "Botingiz kanalingizdan chiqarilgan yoki post yuborish huquqi yo'q, shuning uchun "
               "mahsulotlaringiz u yerga chiqmayapti.\n\n"
               "Kanalni qayta ulash uchun botni kanalga admin qilib, kanaldan istalgan postni botga forward qiling."),
        'ru': ("⚠️ <b>Канал отключён</b>\n\n"
               "Бот удалён из вашего канала или у него нет прав на публикацию, поэтому "
               "товары туда не публикуются.\n\n"
               "Чтобы переподключить канал, сделайте бота администратором и перешлите ему любой пост из канала."),
    },
    'channels_menu_inactive_hint': {
        'uz': ("⚠️ — bot bu kanaldan chiqarilgan yoki post yuborolmayapti. "
               "Qayta ulash uchun botni admin qilib, kanaldan post forward qiling."),
        'ru': ("⚠️ — бот удалён из этого канала или не может публиковать. "
               "Для переподключения сделайте бота админом и перешлите пост из канала."),
    },
    'btn_my_channels': {
        'uz': "📢 Kanallarim",
        'ru': "📢 Мои каналы",
    },
    'btn_add_channel': {
        'uz': "➕ Kanal qo'shish",
        'ru': "➕ Добавить канал",
    },
    'btn_official_channel': {
        'uz': "🛍 Ko'proq mahsulot — kanalimiz",
        'ru': "🛍 Больше товаров — наш канал",
    },
    'channels_menu_connected': {
        'uz': ("📢 <b>Ulangan kanallaringiz</b>\n\n"
               "Yangi (va qayta sotuvga qo'yilgan) mahsulotlaringiz quyidagi kanallarga avtomatik chiqadi:"),
        'ru': ("📢 <b>Ваши подключённые каналы</b>\n\n"
               "Новые (и повторно выставленные) товары автоматически публикуются в этих каналах:"),
    },
    'channels_menu_empty': {
        'uz': ("📢 <b>Kanallarim</b>\n\n"
               "Hali birorta kanal ulanmagan.\n\n"
               "Mahsulotlaringiz o'z kanalingizga ham avtomatik chiqishi uchun kanal ulang."),
        'ru': ("📢 <b>Мои каналы</b>\n\n"
               "Пока не подключён ни один канал.\n\n"
               "Подключите канал, чтобы товары публиковались и в вашем канале."),
    },
    'adu_channels_header': {
        'uz': "📢 <b>Ulangan kanallar:</b>",
        'ru': "📢 <b>Подключённые каналы:</b>",
    },
    'adu_channels_none': {
        'uz': "📢 Ulangan kanal yo'q",
        'ru': "📢 Нет подключённых каналов",
    },
    'btn_view_image': {
        'uz': "🖼 Rasmni ko'rish",
        'ru': "🖼 Посмотреть фото",
    },
    'no_image': {
        'uz': "Rasm yo'q",
        'ru': "Нет фото",
    },
    'status_removed': {
        'uz': "🗑 Sotuvdan olingan",
        'ru': "🗑 Снят с продажи",
    },
    'btn_retry_search_product': {
        'uz': "🔍 Qayta qidirish",
        'ru': "🔍 Искать снова",
    },
    'admin_product_search_ask': {
        'uz': "🔍 Mahsulot nomini yozing:",
        'ru': "🔍 Введите название товара:",
    },
    'admin_product_search_none': {
        'uz': "❌ \"{q}\" bo'yicha mahsulot topilmadi.",
        'ru': "❌ По запросу \"{q}\" товары не найдены.",
    },
    'admin_product_search_results': {
        'uz': "🔍 \"{q}\" — {n} ta mahsulot topildi:",
        'ru': "🔍 \"{q}\" — найдено товаров: {n}",
    },
    'admin_product_removed': {
        'uz': "🚫 Sotuvdan olib tashlandi",
        'ru': "🚫 Снято с продажи",
    },
    'admin_product_restored': {
        'uz': "♻️ Sotuvga qaytarildi",
        'ru': "♻️ Возвращено в продажу",
    },
    'admin_product_body': {
        'uz': ("🛒 <b>{name}</b>\n\n"
               "💵 Narx: {price}\n"
               "📂 Kategoriya: {cat}\n"
               "📦 Holat: {status}\n"
               "🏪 Do'kon: {shop}\n"
               "👤 Sotuvchi: {seller}\n"
               "🌍 Hudud: {region}\n"
               "⭐ Reyting: {rating}\n"
               "📅 Qo'shilgan: {created}\n"
               "🆔 ID: {pid}\n\n"
               "📝 {desc}"),
        'ru': ("🛒 <b>{name}</b>\n\n"
               "💵 Цена: {price}\n"
               "📂 Категория: {cat}\n"
               "📦 Статус: {status}\n"
               "🏪 Магазин: {shop}\n"
               "👤 Продавец: {seller}\n"
               "🌍 Регион: {region}\n"
               "⭐ Рейтинг: {rating}\n"
               "📅 Добавлен: {created}\n"
               "🆔 ID: {pid}\n\n"
               "📝 {desc}"),
    },

    # --- SOTUVCHI PANELI ---
    'seller_panel_title': {
        'uz': "🏪 Sotuvchi paneli",
        'ru': "🏪 Панель продавца",
    },
    'btn_add_product': {
        'uz': "➕ Mahsulot qo'shish",
        'ru': "➕ Добавить товар",
    },
    'btn_my_products': {
        'uz': "📦 Mahsulotlarim",
        'ru': "📦 Мои товары",
    },
    'btn_orders': {
        'uz': "🛒 Buyurtmalar",
        'ru': "🛒 Заказы",
    },
    'btn_stats': {
        'uz': "📊 Statistika",
        'ru': "📊 Статистика",
    },
    'btn_buyer_mode': {
        'uz': "🛒 Xaridor rejimi",
        'ru': "🛒 Режим покупателя",
    },
    'seller_not_approved': {
        'uz': ("⏳ <b>Sizning sotuvchi akkauntingiz hali tasdiqlanmagan.</b>\n\n"
               "Admin tez orada so'rovingizni ko'rib chiqadi.\n"
               "Tasdiqlangandan keyin mahsulot qo'sha olasiz."),
        'ru': ("⏳ <b>Ваш аккаунт продавца ещё не подтверждён.</b>\n\n"
               "Администратор скоро рассмотрит вашу заявку.\n"
               "После подтверждения вы сможете добавлять товары."),
    },
    'seller_rejected_panel': {
        'uz': ("❌ <b>Sotuvchi so'rovingiz rad etildi.</b>\n\n"
               "Sabab: admin tomonidan tasdiqlanmadi.\n"
               "Agar savollaringiz bo'lsa — admin bilan bog'laning.\n\n"
               "Qayta so'rov yuborishingiz mumkin."),
        'ru': ("❌ <b>Ваша заявка продавца отклонена.</b>\n\n"
               "Причина: не одобрена администратором.\n"
               "Если есть вопросы — свяжитесь с администратором.\n\n"
               "Вы можете отправить заявку повторно."),
    },
    'btn_reapply': {
        'uz': "🔄 Qayta so'rov yuborish",
        'ru': "🔄 Отправить заявку повторно",
    },
    'btn_seller_reviews': {
        'uz': "⭐ Reytinglar",
        'ru': "⭐ Отзывы",
    },
    'not_specified': {
        'uz': "Ko'rsatilmagan",
        'ru': "Не указано",
    },
    'seller_panel_full': {
        'uz': "🏪 Sotuvchi paneli\n\nDo'kon: {shop}\nManzil: {address}\n\nTanlang:",
        'ru': "🏪 Панель продавца\n\nМагазин: {shop}\nАдрес: {address}\n\nВыберите:",
    },

    # --- ROL ALMASHTIRISH ---
    'switch_to_seller_confirm_text': {
        'uz': ("🔄 Rolni o'zgartirasizmi?\n\n"
               "🛒 Xaridor → 🏪 Sotuvchi\n\n"
               "Sotuvchi rejimida mahsulot qo'shib, buyurtmalarni boshqara olasiz."),
        'ru': ("🔄 Сменить роль?\n\n"
               "🛒 Покупатель → 🏪 Продавец\n\n"
               "В режиме продавца вы можете добавлять товары и управлять заказами."),
    },
    'switch_to_buyer_confirm_text': {
        'uz': ("🔄 Rolni o'zgartirasizmi?\n\n"
               "🏪 Sotuvchi → 🛒 Xaridor\n\n"
               "Xaridor rejimida mahsulot qidirib, buyurtma bera olasiz."),
        'ru': ("🔄 Сменить роль?\n\n"
               "🏪 Продавец → 🛒 Покупатель\n\n"
               "В режиме покупателя вы можете искать товары и оформлять заказы."),
    },
    'btn_yes_to_seller': {
        'uz': "✅ Ha, sotuvchiga o'tish",
        'ru': "✅ Да, перейти к продавцу",
    },
    'btn_yes_to_buyer': {
        'uz': "✅ Ha, xaridorga o'tish",
        'ru': "✅ Да, перейти к покупателю",
    },
    'btn_no_stay': {
        'uz': "❌ Yo'q, qolaman",
        'ru': "❌ Нет, остаюсь",
    },
    'in_buyer_mode': {
        'uz': "🛒 Xaridor rejimida.",
        'ru': "🛒 Режим покупателя.",
    },
    'in_seller_mode': {
        'uz': "🏪 Sotuvchi rejimida.",
        'ru': "🏪 Режим продавца.",
    },
    'become_seller_prompt': {
        'uz': ("🏪 Sotuvchi rejimiga o'tish uchun avval do'kon ma'lumotlarini kiritishingiz kerak "
               "(do'kon nomi, manzili, ish vaqti).\n\nBoshlaymizmi?"),
        'ru': ("🏪 Чтобы перейти в режим продавца, сначала нужно ввести данные магазина "
               "(название, адрес, рабочее время).\n\nНачнём?"),
    },
    'btn_yes_become_seller': {
        'uz': "✅ Ha, sotuvchi bo'laman",
        'ru': "✅ Да, стать продавцом",
    },
    'btn_cancel': {
        'uz': "❌ Bekor qilish",
        'ru': "❌ Отмена",
    },
    'become_seller_start_text': {
        'uz': "🏪 Sotuvchi bo'lish jarayoni boshlandi.\n\nDo'kon nomini kiriting:",
        'ru': "🏪 Процесс становления продавцом начат.\n\nВведите название магазина:",
    },
    'become_seller_saved': {
        'uz': ("✅ Do'kon ma'lumotlari saqlandi!\n\n"
               "⏳ Sotuvchi sifatida ishlash uchun admin tasdiqlashi kerak.\n"
               "Tez orada javob beramiz. Shu vaqtda xaridor sifatida foydalanishingiz mumkin."),
        'ru': ("✅ Данные магазина сохранены!\n\n"
               "⏳ Для работы продавцом требуется подтверждение администратора.\n"
               "Скоро ответим. Пока можете пользоваться как покупатель."),
    },
    'reapply_sent': {
        'uz': ("✅ <b>Qayta so'rov yuborildi!</b>\n\n"
               "⏳ Admin tez orada ko'rib chiqadi.\n"
               "Tasdiqlangandan keyin mahsulot qo'sha olasiz."),
        'ru': ("✅ <b>Повторная заявка отправлена!</b>\n\n"
               "⏳ Администратор скоро рассмотрит.\n"
               "После подтверждения вы сможете добавлять товары."),
    },
    'user_not_found': {
        'uz': "Foydalanuvchi topilmadi.",
        'ru': "Пользователь не найден.",
    },

    # --- ADMIN BILAN BOG'LANISH ---
    'contact_admin_prompt': {
        'uz': ("🆘 <b>Admin bilan bog'lanish</b>\n\n"
               "Muammo, taklif yoki savolingizni yozing.\n"
               "Admin tez orada javob beradi.\n\n"
               "<i>Bekor qilish uchun /cancel yozing.</i>"),
        'ru': ("🆘 <b>Связаться с админом</b>\n\n"
               "Напишите вашу проблему, предложение или вопрос.\n"
               "Администратор скоро ответит.\n\n"
               "<i>Для отмены напишите /cancel.</i>"),
    },
    'contact_admin_sent': {
        'uz': "✅ Xabaringiz adminga yuborildi!",
        'ru': "✅ Ваше сообщение отправлено администратору!",
    },
    'contact_admin_failed': {
        'uz': "❌ Xabar yuborib bo'lmadi.",
        'ru': "❌ Не удалось отправить сообщение.",
    },

    # --- BUYURTMA ---
    'order_quantity_ask': {
        'uz': "Nechta olmoqchisiz? (raqam kiriting):",
        'ru': "Сколько хотите купить? (введите число):",
    },
    'order_quantity_invalid': {
        'uz': "❌ 1 dan 999 gacha raqam kiriting:",
        'ru': "❌ Введите число от 1 до 999:",
    },
    'order_delivery_ask': {
        'uz': "Qanday qabul qilasiz?",
        'ru': "Как хотите получить?",
    },
    'order_delivery': {
        'uz': "🚚 Yetkazib berish",
        'ru': "🚚 Доставка",
    },
    'order_pickup': {
        'uz': "🚶 Olib ketaman",
        'ru': "🚶 Самовывоз",
    },
    'order_cancel': {
        'uz': "Buyurtma bekor qilindi.",
        'ru': "Заказ отменён.",
    },
    'order_success': {
        'uz': "✅ Buyurtmangiz qabul qilindi!",
        'ru': "✅ Ваш заказ принят!",
    },
    'order_auto_cancel': {
        'uz': "⏰ Buyurtma avtomatik bekor qilindi",
        'ru': "⏰ Заказ автоматически отменён",
    },
    'order_confirmed': {
        'uz': "✅ Buyurtmangiz tasdiqlandi!",
        'ru': "✅ Ваш заказ подтверждён!",
    },
    'order_delivered': {
        'uz': "🚚 Buyurtmangiz yetkazildi!",
        'ru': "🚚 Ваш заказ доставлен!",
    },
    'order_cancelled': {
        'uz': "❌ Buyurtmangiz bekor qilindi.",
        'ru': "❌ Ваш заказ отменён.",
    },
    'order_spam': {
        'uz': "⏳ Bu mahsulotga yaqinda buyurtma bergansiz.\n5 daqiqadan keyin qayta urinib ko'ring.",
        'ru': "⏳ Вы недавно заказывали этот товар.\nПопробуйте через 5 минут.",
    },

    # --- MAHSULOT ---
    'product_added': {
        'uz': "✅ Mahsulot muvaffaqiyatli qo'shildi!",
        'ru': "✅ Товар успешно добавлен!",
    },
    'product_updated': {
        'uz': "✅ Mahsulot yangilandi!",
        'ru': "✅ Товар обновлён!",
    },
    'product_not_found': {
        'uz': "Mahsulot topilmadi.",
        'ru': "Товар не найден.",
    },
    'product_out_of_stock': {
        'uz': "❌ Bu mahsulot hozir sotuvda yo'q.",
        'ru': "❌ Этот товар сейчас не в продаже.",
    },
    'product_own': {
        'uz': "❌ O'z mahsulotingizni buyurtma qila olmaysiz.",
        'ru': "❌ Вы не можете заказать свой товар.",
    },

    # --- QIDIRUV ---
    'search_prompt': {
        'uz': "🔍 Mahsulot nomini kiriting:",
        'ru': "🔍 Введите название товара:",
    },
    'search_no_results': {
        'uz': "❌ Hech narsa topilmadi.",
        'ru': "❌ Ничего не найдено.",
    },
    'search_location_ask': {
        'uz': "📍 Lokatsiyangizni yuboring — sizga eng yaqin do'konlar birinchi ko'rsatiladi.",
        'ru': "📍 Отправьте вашу геолокацию — ближайшие магазины будут показаны первыми.",
    },
    'search_skip_location': {
        'uz': "⏭ Lokatsiyasiz qidirish",
        'ru': "⏭ Искать без геолокации",
    },

    # --- PROFIL ---
    'profile_updated': {
        'uz': "✅ Profil yangilandi!",
        'ru': "✅ Профиль обновлён!",
    },

    # --- REYTING ---
    'rating_ask': {
        'uz': "⭐ Reytingni tanlang:",
        'ru': "⭐ Выберите рейтинг:",
    },
    'rating_comment_ask': {
        'uz': "📝 Izohingizni kiriting (ixtiyoriy, \"-\" yozsangiz o'tkazib yuboriladi):",
        'ru': "📝 Введите комментарий (необязательно, \"-\" чтобы пропустить):",
    },
    'rating_success': {
        'uz': "✅ Rahmat! Reyting qabul qilindi.",
        'ru': "✅ Спасибо! Отзыв принят.",
    },

    # --- XABAR ---
    'message_ask': {
        'uz': "💬 Xabaringizni kiriting:",
        'ru': "💬 Введите ваше сообщение:",
    },
    'message_sent': {
        'uz': "✅ Xabar yuborildi!",
        'ru': "✅ Сообщение отправлено!",
    },

    # --- TO'LOV ---
    'payment_cash': {
        'uz': "💵 Naqd pul",
        'ru': "💵 Наличные",
    },
    'payment_terminal': {
        'uz': "💳 Terminal (plastik karta)",
        'ru': "💳 Терминал (пластиковая карта)",
    },
    'payment_p2p': {
        'uz': "📲 Karta raqamiga o'tkazish (P2P)",
        'ru': "📲 Перевод на карту (P2P)",
    },

    # --- ADMIN ---
    'admin_panel_title': {
        'uz': "🔧 Admin paneli",
        'ru': "🔧 Панель администратора",
    },
    'new_seller_request': {
        'uz': "🆕 Yangi sotuvchi so'rovi!",
        'ru': "🆕 Новая заявка продавца!",
    },
    'seller_approved': {
        'uz': ("🎉 Tabriklaymiz!\n\n"
               "Sizning sotuvchi so'rovingiz tasdiqlandi!\n"
               "Endi mahsulot qo'shib, savdo qilishingiz mumkin."),
        'ru': ("🎉 Поздравляем!\n\n"
               "Ваша заявка продавца одобрена!\n"
               "Теперь вы можете добавлять товары и торговать."),
    },
    'seller_rejected': {
        'uz': ("❌ Sotuvchi so'rovingiz rad etildi.\n\n"
               "Sabab: admin tomonidan tasdiqlanmadi.\n"
               "Xaridor sifatida davom etishingiz mumkin."),
        'ru': ("❌ Ваша заявка продавца отклонена.\n\n"
               "Причина: не одобрена администратором.\n"
               "Вы можете продолжить как покупатель."),
    },

    # --- KATEGORIYALAR / MAHSULOT RO'YXATI ---
    'categories_title': {'uz': "📦 Kategoriyalar:", 'ru': "📦 Категории:"},
    'category_empty': {
        'uz': "Bu kategoriyada mahsulotlar yo'q.",
        'ru': "В этой категории нет товаров.",
    },
    'products_page': {
        'uz': "📦 Mahsulotlar — jami {total} ta. Sahifa {page}/{pages}:",
        'ru': "📦 Товары — всего {total}. Страница {page}/{pages}:",
    },
    'none_word': {'uz': "Yo'q", 'ru': "Нет"},
    'unknown_word': {'uz': "Noma'lum", 'ru': "Неизвестно"},
    'map_view': {'uz': "Xaritada ko'rish", 'ru': "Посмотреть на карте"},

    # --- MAHSULOT KARTOCHKASI ---
    'btn_order': {'uz': "🛒 Buyurtma berish", 'ru': "🛒 Оформить заказ"},
    'btn_send_message': {'uz': "💬 Xabar yuborish", 'ru': "💬 Отправить сообщение"},
    'btn_product_reviews': {'uz': "💬 Mahsulot izohlari ({n})", 'ru': "💬 Отзывы о товаре ({n})"},
    'btn_recommend': {'uz': "✨ Sizga mos boshqa tovarlar", 'ru': "✨ Другие товары для вас"},
    'btn_back_to_shop': {'uz': "⬅️ Do'konga qaytish", 'ru': "⬅️ Вернуться в магазин"},
    'btn_add_to_cart': {'uz': "➕ Savatga qo'shish", 'ru': "➕ В корзину"},
    'btn_in_cart_qty': {'uz': "🛒 Savatda: {n} ta", 'ru': "🛒 В корзине: {n}"},
    'btn_view_cart_n': {'uz': "🛒 Savatni ko'rish ({n} ta)", 'ru': "🛒 Корзина ({n})"},
    'btn_tg_label': {'uz': "📱 Telegram: {u}", 'ru': "📱 Telegram: {u}"},
    'btn_phone_label': {'uz': "📞 Telefon: {p}", 'ru': "📞 Телефон: {p}"},
    'open_now': {'uz': "🟢 Hozir ochiq", 'ru': "🟢 Сейчас открыто"},
    'closed_now': {'uz': "🔴 Hozir yopiq", 'ru': "🔴 Сейчас закрыто"},
    'frag_stock': {'uz': "\n📦 Zahirada: {n} dona", 'ru': "\n📦 В наличии: {n} шт"},
    'frag_region': {'uz': "🌍 Hudud: {label}\n", 'ru': "🌍 Регион: {label}\n"},
    'frag_address': {'uz': "📍 Manzil: {addr}\n", 'ru': "📍 Адрес: {addr}\n"},
    'frag_map': {
        'uz': "\n🗺️ <a href=\"{url}\">Xaritada ko'rish</a>",
        'ru': "\n🗺️ <a href=\"{url}\">Посмотреть на карте</a>",
    },
    'frag_rating_count': {'uz': " ({n} ta baho)\n", 'ru': " ({n} оценок)\n"},
    'frag_no_rating': {'uz': " (baho yo'q)\n", 'ru': " (нет оценок)\n"},
    'frag_attrs_title': {'uz': "\n\n🏷 <b>Xususiyatlar:</b>\n", 'ru': "\n\n🏷 <b>Характеристики:</b>\n"},
    'dist_from_you': {'uz': "📏 Sizdan masofa: ~", 'ru': "📏 Расстояние от вас: ~"},
    'product_card': {
        'uz': ("📦 <b>{name}</b>\n\n"
               "💰 Narxi: <b>{price}</b>{stock}\n"
               "🏪 Do'kon: {shop}{verified}\n"
               "{region}{address}"
               "🎯 Mo'ljal: {landmark}{map}\n"
               "{dist}"
               "⭐ Mahsulot: {prod_rating}/5.0{rating_cnt}"
               "🏪 Do'kon reytingi: {shop_rating}/5.0\n"
               "🕐 Ish vaqti: {wh}{open}\n"
               "📅 Ish kunlari: {wd}\n"
               "📝 Tavsif: {desc}{attrs}"),
        'ru': ("📦 <b>{name}</b>\n\n"
               "💰 Цена: <b>{price}</b>{stock}\n"
               "🏪 Магазин: {shop}{verified}\n"
               "{region}{address}"
               "🎯 Ориентир: {landmark}{map}\n"
               "{dist}"
               "⭐ Товар: {prod_rating}/5.0{rating_cnt}"
               "🏪 Рейтинг магазина: {shop_rating}/5.0\n"
               "🕐 Рабочее время: {wh}{open}\n"
               "📅 Рабочие дни: {wd}\n"
               "📝 Описание: {desc}{attrs}"),
    },

    # --- MAHSULOT IZOHLARI ---
    'btn_back_to_product': {'uz': "⬅️ Mahsulotga qaytish", 'ru': "⬅️ Вернуться к товару"},
    'reviews_none_for_product': {
        'uz': "💬 <b>{name}</b>\n\nHozircha izohlar yo'q.",
        'ru': "💬 <b>{name}</b>\n\nПока нет отзывов.",
    },
    'reviews_header': {
        'uz': "💬 <b>{name}</b> — izohlar",
        'ru': "💬 <b>{name}</b> — отзывы",
    },
    'reviews_product_rating': {
        'uz': "⭐ Mahsulot reytingi: <b>{avg}/5.0</b> ({count} ta baho)\n",
        'ru': "⭐ Рейтинг товара: <b>{avg}/5.0</b> ({count} оценок)\n",
    },
    'reviews_old_cut': {'uz': "\n\n…(eski izohlar kesildi)", 'ru': "\n\n…(старые отзывы обрезаны)"},
    'anonymous': {'uz': "Anonim", 'ru': "Аноним"},

    # --- QIDIRUV (davomi) ---
    'search_cancelled': {'uz': "Qidiruv bekor qilindi.", 'ru': "Поиск отменён."},
    'searching_for': {'uz': "🔍 '{q}' bo'yicha qidirilmoqda...", 'ru': "🔍 Идёт поиск по '{q}'..."},
    'product_word': {'uz': "Mahsulot", 'ru': "Товар"},

    # --- DEEPLINK KARTOCHKA ---
    'map_see_inline': {'uz': "xaritadan ko'ring", 'ru': "смотрите на карте"},
    'frag_address_map': {
        'uz': "📍 Manzil: xaritadan ko'ring{map}\n",
        'ru': "📍 Адрес: смотрите на карте{map}\n",
    },
    'product_card_deeplink': {
        'uz': ("📦 <b>{name}</b>\n\n"
               "💰 Narxi: <b>{price}</b>\n"
               "🏪 Do'kon: {shop}\n"
               "{region}{address}{dist}"
               "⭐ Mahsulot: {prod_rating}/5.0{rating_cnt}"
               "🏪 Do'kon reytingi: {shop_rating}/5.0\n"
               "🕐 Ish vaqti: {wh}\n"
               "📝 Tavsif: {desc}"),
        'ru': ("📦 <b>{name}</b>\n\n"
               "💰 Цена: <b>{price}</b>\n"
               "🏪 Магазин: {shop}\n"
               "{region}{address}{dist}"
               "⭐ Товар: {prod_rating}/5.0{rating_cnt}"
               "🏪 Рейтинг магазина: {shop_rating}/5.0\n"
               "🕐 Рабочее время: {wh}\n"
               "📝 Описание: {desc}"),
    },

    'deeplink_ask_location': {
        'uz': "📍 Sotuvchigacha bo'lgan masofani ko'rish uchun pastdagi tugma orqali joylashuvingizni yuboring:",
        'ru': "📍 Чтобы увидеть расстояние до продавца, отправьте свою геолокацию кнопкой ниже:",
    },
    'deeplink_distance_result': {
        'uz': "📏 Sotuvchigacha masofa: ~{km} km",
        'ru': "📏 Расстояние до продавца: ~{km} км",
    },
    'location_saved_ok': {
        'uz': "✅ Joylashuvingiz qabul qilindi.",
        'ru': "✅ Ваша геолокация принята.",
    },

    # --- QIDIRUV NATIJALARI RO'YXATI ---
    'search_no_results_q': {
        'uz': "❌ '{q}' bo'yicha hech narsa topilmadi.",
        'ru': "❌ По запросу '{q}' ничего не найдено.",
    },
    'frag_distance': {'uz': "\n📏 Masofa: ~{km} km", 'ru': "\n📏 Расстояние: ~{km} км"},
    'btn_telegram': {'uz': "📱 Telegram", 'ru': "📱 Telegram"},
    'btn_phone': {'uz': "📞 Telefon", 'ru': "📞 Телефон"},
    'btn_details': {'uz': "📦 Batafsil", 'ru': "📦 Подробнее"},
    'btn_reviews_n': {'uz': "💬 Izohlar ({n})", 'ru': "💬 Отзывы ({n})"},
    'map_see_line': {'uz': "📍 Xaritadan ko'ring", 'ru': "📍 Смотрите на карте"},
    'srch_rating_cnt': {'uz': " ({n} ta)", 'ru': " ({n})"},
    'srch_no_rating': {'uz': " (baho yo'q)", 'ru': " (нет оценок)"},
    'search_item_card': {
        'uz': ("{emoji} <b>{name}</b>\n\n"
               "💰 <b>{price}</b>\n"
               "🏪 {shop}\n"
               "{region}{address}"
               "⭐ Mahsulot: {prod_rating}/5.0{rating_cnt}"
               "\n🏪 Do'kon: {shop_rating}/5.0"),
        'ru': ("{emoji} <b>{name}</b>\n\n"
               "💰 <b>{price}</b>\n"
               "🏪 {shop}\n"
               "{region}{address}"
               "⭐ Товар: {prod_rating}/5.0{rating_cnt}"
               "\n🏪 Магазин: {shop_rating}/5.0"),
    },
    'sort_rating': {'uz': "⭐ Reyting", 'ru': "⭐ Рейтинг"},
    'sort_price_asc': {'uz': "💰 Arzondan", 'ru': "💰 Сначала дешёвые"},
    'sort_price_desc': {'uz': "💰 Qimmatdan", 'ru': "💰 Сначала дорогие"},
    'sort_newest': {'uz': "🆕 Yangi", 'ru': "🆕 Новые"},
    'btn_prev': {'uz': "⬅️ Oldingi", 'ru': "⬅️ Предыдущая"},
    'btn_next': {'uz': "Keyingi ➡️", 'ru': "Следующая ➡️"},
    'btn_main_menu': {'uz': "⬅️ Bosh menyu", 'ru': "⬅️ Главное меню"},
    'search_results_count': {
        'uz': "🔍 '{q}' bo'yicha jami {total} ta natija. Sahifa {page}/{pages}.",
        'ru': "🔍 По '{q}' всего {total} результатов. Страница {page}/{pages}.",
    },
    'search_results_gone': {
        'uz': "Qidiruv natijalari yo'q. Qaytadan qidiring.",
        'ru': "Результатов поиска нет. Попробуйте снова.",
    },

    # --- DO'KON QIDIRISH ---
    'shop_search_prompt': {'uz': "🏪 Do'kon nomini kiriting:", 'ru': "🏪 Введите название магазина:"},
    'shops_not_found': {'uz': "Do'konlar topilmadi.", 'ru': "Магазины не найдены."},
    'shops_page': {
        'uz': "🏪 Do'konlar — jami {total} ta. Sahifa {page}/{pages}:",
        'ru': "🏪 Магазины — всего {total}. Страница {page}/{pages}:",
    },
    'shop_count_label': {'uz': "{n} ta", 'ru': "{n}"},
    'shop_not_found': {'uz': "Do'kon topilmadi.", 'ru': "Магазин не найден."},
    'shop_word': {'uz': "Do'kon", 'ru': "Магазин"},
    'shop_detail_card': {
        'uz': ("🏪 <b>{shop}{verified}</b>\n\n"
               "👤 Sotuvchi: {seller}\n"
               "{region}{address}"
               "🎯 Mo'ljal: {landmark}{landmark_map}\n"
               "{dist}"
               "🕐 Ish vaqti: {wh}{open}\n"
               "📅 Ish kunlari: {wd}\n"
               "⭐ Reyting: {rating}/5.0\n"
               "📦 Mahsulotlar: {pcount} ta\n"
               "🚚 Yetkazilgan: {delivered} ta buyurtma\n"),
        'ru': ("🏪 <b>{shop}{verified}</b>\n\n"
               "👤 Продавец: {seller}\n"
               "{region}{address}"
               "🎯 Ориентир: {landmark}{landmark_map}\n"
               "{dist}"
               "🕐 Рабочее время: {wh}{open}\n"
               "📅 Рабочие дни: {wd}\n"
               "⭐ Рейтинг: {rating}/5.0\n"
               "📦 Товаров: {pcount}\n"
               "🚚 Доставлено: {delivered} заказов\n"),
    },
    'verified_seller_note': {
        'uz': "\n<i>✅ Tasdiqlangan ishonchli sotuvchi</i>\n",
        'ru': "\n<i>✅ Проверенный надёжный продавец</i>\n",
    },
    'btn_view_products_n': {
        'uz': "📦 Mahsulotlarni ko'rish ({n})",
        'ru': "📦 Посмотреть товары ({n})",
    },
    'btn_my_cart_summary': {
        'uz': "🛒 Savatim ({n} ta • {total})",
        'ru': "🛒 Моя корзина ({n} • {total})",
    },
    'btn_tg_at': {'uz': "📱 Telegram: @{u}", 'ru': "📱 Telegram: @{u}"},
    'btn_phone_plain': {'uz': "📞 {p}", 'ru': "📞 {p}"},
    'shop_no_products': {
        'uz': "🏪 {shop} — hozircha mahsulotlar yo'q.",
        'ru': "🏪 {shop} — пока нет товаров.",
    },
    'btn_in_cart_manage': {
        'uz': "🛒 Savatda: {n} ta — boshqarish",
        'ru': "🛒 В корзине: {n} — управление",
    },
    'btn_checkout_cart': {
        'uz': "🛒 Savatni rasmiylashtirish ({n} ta • {total})",
        'ru': "🛒 Оформить корзину ({n} • {total})",
    },
    'shop_products_header': {
        'uz': ("🏪 <b>{shop}</b> — {total} ta mahsulot. Sahifa {page}/{pages}:\n"
               "<i>Bir nechta mahsulotni savatga qo'shib, bitta buyurtma qilishingiz mumkin.</i>"),
        'ru': ("🏪 <b>{shop}</b> — {total} товаров. Страница {page}/{pages}:\n"
               "<i>Можно добавить несколько товаров в корзину и оформить один заказ.</i>"),
    },

    # --- QIDIRUVDA HUDUD ---
    'search_region_ask': {'uz': "📍 Qaysi hudud bo'yicha qidirasiz?", 'ru': "📍 По какому региону ищем?"},
    'btn_all_regions': {'uz': "🌐 Barcha hududlar", 'ru': "🌐 Все регионы"},
    'btn_whole_region': {'uz': "📍 Butun {name}", 'ru': "📍 Весь {name}"},
    'region_pick_district': {'uz': "📍 {name} — tuman tanlang:", 'ru': "📍 {name} — выберите район:"},
    'region_then_search': {
        'uz': "📍 Hudud: {name}\n\n🔍 Mahsulot nomini kiriting:",
        'ru': "📍 Регион: {name}\n\n🔍 Введите название товара:",
    },
    'selected_region': {'uz': "tanlangan hudud", 'ru': "выбранный регион"},
    'selected_district': {'uz': "tanlangan tuman", 'ru': "выбранный район"},

    # --- BUYURTMALARIM ---
    'orders_empty': {'uz': "Hozircha buyurtmalar yo'q.", 'ru': "Пока нет заказов."},
    'order_group_row': {
        'uz': "{emoji} 🛒 {oid} — {count} ta tovar • {sum}",
        'ru': "{emoji} 🛒 {oid} — {count} товаров • {sum}",
    },
    'my_orders_count': {'uz': "🛒 Buyurtmalarim ({n} ta):", 'ru': "🛒 Мои заказы ({n}):"},

    # --- XABARLAR ---
    'messages_empty': {'uz': "💬 Hali xabarli buyurtmalar yo'q.", 'ru': "💬 Пока нет заказов с сообщениями."},
    'messages_title': {'uz': "💬 Xabarlar:", 'ru': "💬 Сообщения:"},

    # --- XARIDOR PROFILI ---
    'btn_edit_name': {'uz': "✏️ Ismni tahrirlash", 'ru': "✏️ Изменить имя"},
    'btn_edit_phone': {'uz': "✏️ Telefonni tahrirlash", 'ru': "✏️ Изменить телефон"},
    'btn_my_referral': {'uz': "🔗 Mening havolam", 'ru': "🔗 Моя ссылка"},
    'buyer_profile_body': {
        'uz': ("👤 Xaridor profili\n\n"
               "Ism: {name}\n"
               "Telefon: {phone}\n"
               "Takliflar: {refs} ta\n"
               "Ro'yxatdan o'tgan: {date}"),
        'ru': ("👤 Профиль покупателя\n\n"
               "Имя: {name}\n"
               "Телефон: {phone}\n"
               "Рефералы: {refs}\n"
               "Дата регистрации: {date}"),
    },
    'referral_link_title': {
        'uz': ("🔗 <b>Mening taklif havolam</b>\n\n"
               "Havola (bosing va nusxalang):\n"
               "<code>{link}</code>\n\n"
               "Kod: <code>{code}</code>\n"
               "👥 Taklif qilganlar: <b>{count} ta</b>\n\n"
               "Havolani do'stlaringizga yuboring — ular ro'yxatdan o'tganda hisobingizga qo'shiladi."),
        'ru': ("🔗 <b>Моя реферальная ссылка</b>\n\n"
               "Ссылка (нажмите и скопируйте):\n"
               "<code>{link}</code>\n\n"
               "Код: <code>{code}</code>\n"
               "👥 Приглашено: <b>{count}</b>\n\n"
               "Отправьте ссылку друзьям — когда они зарегистрируются, они добавятся к вашему счёту."),
    },
    'referral_share_text': {
        'uz': "TezBozor marketplace botiga qo`shiling!",
        'ru': "Присоединяйтесь к маркетплейс-боту TezBozor!",
    },
    'btn_share_friends': {'uz': "📤 Do'stlarga ulashish", 'ru': "📤 Поделиться с друзьями"},
    'user_not_found_start': {
        'uz': "Foydalanuvchi topilmadi. /start bilan boshlang.",
        'ru': "Пользователь не найден. Начните с /start.",
    },

    # --- BUYURTMA TAFSILOTI ---
    'order_not_found': {'uz': "Buyurtma topilmadi.", 'ru': "Заказ не найден."},
    'pending_autocancel_left': {
        'uz': "\n⏰ Avtomatik bekor: {m}:{s} qoldi",
        'ru': "\n⏰ Автоотмена через: {m}:{s}",
    },
    'pending_autocancel_soon': {
        'uz': "\n⏰ Tez orada avtomatik bekor bo'ladi",
        'ru': "\n⏰ Скоро будет автоматически отменён",
    },
    'status_guide_pending': {
        'uz': "⏳ Sotuvchi hali tasdiqlamadi.{note}\nKuting yoki bekor qiling.",
        'ru': "⏳ Продавец ещё не подтвердил.{note}\nПодождите или отмените.",
    },
    'status_guide_confirmed_delivery': {
        'uz': "✅ Sotuvchi tasdiqladi!\n📍 Yetkazib berish kutilmoqda.",
        'ru': "✅ Продавец подтвердил!\n📍 Ожидается доставка.",
    },
    'status_guide_confirmed_pickup': {
        'uz': "✅ Sotuvchi tasdiqladi!\n🚶 Do'konga borib olishingiz mumkin.",
        'ru': "✅ Продавец подтвердил!\n🚶 Можете забрать в магазине.",
    },
    'status_guide_delivered': {
        'uz': "🚚 Buyurtma yakunlandi. Reyting qoldiring!",
        'ru': "🚚 Заказ завершён. Оставьте отзыв!",
    },
    'status_guide_cancelled': {'uz': "❌ Buyurtma bekor qilindi.", 'ru': "❌ Заказ отменён."},
    'step_new': {'uz': "⏳ Yangi", 'ru': "⏳ Новый"},
    'step_confirmed': {'uz': "✅ Tasdiqlangan", 'ru': "✅ Подтверждён"},
    'step_delivered': {'uz': "🚚 Yetkazildi", 'ru': "🚚 Доставлен"},
    'step_picked': {'uz': "✅ Olindi", 'ru': "✅ Получен"},
    'step_rated': {'uz': "⭐ Baholandi", 'ru': "⭐ Оценён"},
    'timeline_now': {'uz': "  ← hozir", 'ru': "  ← сейчас"},
    'btn_cancel_order': {'uz': "❌ Bekor qilish", 'ru': "❌ Отменить"},
    'btn_got_item': {'uz': "✅ Tovarni oldim", 'ru': "✅ Я получил товар"},
    'btn_reorder': {'uz': "🔁 Qaytadan buyurtma", 'ru': "🔁 Повторить заказ"},
    'btn_correspondence': {'uz': "📜 Yozishmalar", 'ru': "📜 Переписка"},
    'btn_leave_rating': {'uz': "⭐ Reyting qoldirish", 'ru': "⭐ Оставить отзыв"},
    'btn_show_route': {'uz': "🗺️ Yo'lni ko'rsatish", 'ru': "🗺️ Показать маршрут"},
    'btn_shop_location': {'uz': "🗺️ Do'kon joylashuvi", 'ru': "🗺️ Расположение магазина"},
    'frag_order_address': {'uz': "\n📍 {addr}", 'ru': "\n📍 {addr}"},
    'frag_order_landmark': {'uz': "\n🏷 Mo'ljal: {lm}", 'ru': "\n🏷 Ориентир: {lm}"},
    'frag_order_distance': {'uz': "\n📏 Masofa: ~{km} km", 'ru': "\n📏 Расстояние: ~{km} км"},
    'address_word': {'uz': "Manzil", 'ru': "Адрес"},
    'order_not_yours': {
        'uz': "❌ Buyurtma topilmadi yoki sizniki emas.",
        'ru': "❌ Заказ не найден или не ваш.",
    },
    'cant_confirm_status': {
        'uz': "❌ Bu buyurtma holati: {status}. Tasdiqlab bo'lmaydi.",
        'ru': "❌ Статус заказа: {status}. Подтвердить нельзя.",
    },
    'pickup_seller_notify': {
        'uz': "✅ Xaridor tovarni oldi!\n\nBuyurtma {oid} — {pname}\n👤 {buyer}",
        'ru': "✅ Покупатель забрал товар!\n\nЗаказ {oid} — {pname}\n👤 {buyer}",
    },
    'pickup_done': {
        'uz': ("✅ Ajoyib! Buyurtma {oid} yakunlandi.\n\n"
               "Xaridingiz qulay bo'lsin! ⭐ Reyting qoldirishni unutmang."),
        'ru': ("✅ Отлично! Заказ {oid} завершён.\n\n"
               "Приятных покупок! ⭐ Не забудьте оставить отзыв."),
    },
    'btn_orders_back': {'uz': "⬅️ Buyurtmalar", 'ru': "⬅️ Заказы"},
    'cant_cancel_status': {
        'uz': ("❌ Bu buyurtmani bekor qila olmaysiz (holat: {status}).\n"
               "Sotuvchi bilan bog'laning."),
        'ru': ("❌ Этот заказ нельзя отменить (статус: {status}).\n"
               "Свяжитесь с продавцом."),
    },
    'order_cancelled_done': {
        'uz': "✅ Buyurtma {oid} bekor qilindi.",
        'ru': "✅ Заказ {oid} отменён.",
    },
    'seller_notify_cancelled': {
        'uz': "ℹ️ Xaridor buyurtmani bekor qildi: {oid} — {pname}",
        'ru': "ℹ️ Покупатель отменил заказ: {oid} — {pname}",
    },
    'order_detail_body': {
        'uz': ("🛒 <b>Buyurtma {oid}</b>\n\n"
               "📦 {pname}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Jami: <b>{total}</b>\n"
               "🚚 {dlv}\n"
               "💳 {pay}\n"
               "🏪 {shop}{location}\n"
               "📞 {phone}\n"
               "📅 {date}\n\n"
               "<b>Holat:</b>\n{timeline}\n"
               "<i>{guide}</i>"),
        'ru': ("🛒 <b>Заказ {oid}</b>\n\n"
               "📦 {pname}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Итого: <b>{total}</b>\n"
               "🚚 {dlv}\n"
               "💳 {pay}\n"
               "🏪 {shop}{location}\n"
               "📞 {phone}\n"
               "📅 {date}\n\n"
               "<b>Статус:</b>\n{timeline}\n"
               "<i>{guide}</i>"),
    },

    # --- BUYURTMA OQIMI ---
    'frag_shop_closed_note': {
        'uz': "\n⚠️ Eslatma: do'kon hozir yopiq ({wh}). Sotuvchi xabarni keyinroq ko'rishi mumkin.",
        'ru': "\n⚠️ Внимание: магазин сейчас закрыт ({wh}). Продавец может увидеть сообщение позже.",
    },
    'order_qty_prompt': {
        'uz': "🛒 <b>{name}</b>\nNarxi: {price} / dona{closed}\n\nNechta olmoqchisiz? (raqam kiriting):",
        'ru': "🛒 <b>{name}</b>\nЦена: {price} / шт{closed}\n\nСколько хотите? (введите число):",
    },
    'qty_only_n_available': {
        'uz': "❌ Bu mahsulotdan faqat {stock} dona mavjud. Kichikroq miqdor kiriting (1–{stock}):",
        'ru': "❌ Этого товара только {stock} шт. Введите меньшее количество (1–{stock}):",
    },
    'order_total_delivery_q': {
        'uz': "Jami: <b>{total}</b>\n\nQanday qabul qilasiz?",
        'ru': "Итого: <b>{total}</b>\n\nКак хотите получить?",
    },
    'delivery_address_ask': {
        'uz': "📍 Yetkazib berish manzilini yuboring (lokatsiya yoki matn):",
        'ru': "📍 Отправьте адрес доставки (геолокация или текст):",
    },
    'delivery_address_hint': {
        'uz': "Lokatsiyani yuborish uchun pastdagi tugmani bosing yoki manzilni matn ko'rinishida yozing:",
        'ru': "Нажмите кнопку ниже, чтобы отправить геолокацию, или напишите адрес текстом:",
    },
    'btn_send_location': {'uz': "📍 Lokatsiyani yuborish", 'ru': "📍 Отправить геолокацию"},
    'address_too_short': {'uz': "❌ Manzil juda qisqa. Aniqroq yozing:", 'ru': "❌ Адрес слишком короткий. Уточните:"},
    'address_accepted': {'uz': "✅ Manzil qabul qilindi.", 'ru': "✅ Адрес принят."},
    'frag_p2p_card_note': {
        'uz': "\n\n📲 P2P uchun sotuvchi kartasi:\n{ctype} {masked}\n👤 {owner}",
        'ru': "\n\n📲 Карта продавца для P2P:\n{ctype} {masked}\n👤 {owner}",
    },
    'payment_method_choose': {
        'uz': ("💰 To'lov usulini tanlang:\n\n"
               "💵 <b>Naqd</b> — yetkazib berganda naqd to'laysiz\n"
               "💳 <b>Terminal</b> — sotuvchidagi POS terminalni ishlatib to'laysiz\n"
               "📲 <b>P2P</b> — karta raqamiga o'tkazasiz"
               "{p2p_note}\n\n"
               "<i>⚠️ Bot hech qanday karta ma'lumotini so'ramaydi va to'lovni o'zi amalga oshirmaydi.</i>"),
        'ru': ("💰 Выберите способ оплаты:\n\n"
               "💵 <b>Наличные</b> — оплачиваете наличными при получении\n"
               "💳 <b>Терминал</b> — оплата через POS-терминал продавца\n"
               "📲 <b>P2P</b> — перевод на номер карты"
               "{p2p_note}\n\n"
               "<i>⚠️ Бот не запрашивает данные карты и не проводит оплату сам.</i>"),
    },
    'btn_confirm': {'uz': "✅ Tasdiqlash", 'ru': "✅ Подтвердить"},
    'btn_reject': {'uz': "❌ Rad etish", 'ru': "❌ Отклонить"},
    'order_confirm_summary': {
        'uz': ("🛒 <b>Buyurtmani tasdiqlang:</b>\n\n"
               "📦 Mahsulot: {pname}\n"
               "🏪 Do'kon: {shop}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Jami: <b>{total}</b>\n"
               "🚚 Yetkazish: {dlv}\n"
               "{address}"
               "💳 To'lov: {pay}\n"),
        'ru': ("🛒 <b>Подтвердите заказ:</b>\n\n"
               "📦 Товар: {pname}\n"
               "🏪 Магазин: {shop}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Итого: <b>{total}</b>\n"
               "🚚 Доставка: {dlv}\n"
               "{address}"
               "💳 Оплата: {pay}\n"),
    },
    'frag_summary_address': {'uz': "📍 Manzil: {addr}\n", 'ru': "📍 Адрес: {addr}\n"},
    'order_placed': {
        'uz': ("✅ Buyurtmangiz qabul qilindi!\n\n"
               "Buyurtma raqami: <b>{oid}</b>\n"
               "⏳ Sotuvchi <b>10 daqiqa</b> ichida tasdiqlashi kerak.\n"
               "Aks holda buyurtma avtomatik bekor bo'ladi."),
        'ru': ("✅ Ваш заказ принят!\n\n"
               "Номер заказа: <b>{oid}</b>\n"
               "⏳ Продавец должен подтвердить в течение <b>10 минут</b>.\n"
               "Иначе заказ будет автоматически отменён."),
    },
    'seller_new_order_notify': {
        'uz': ("🔔 <b>Yangi buyurtma!</b> {oid}\n\n"
               "📦 {pname}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Jami: <b>{total}</b>\n"
               "👤 Xaridor: {buyer}\n"
               "📞 {phone}\n"
               "🚚 {dlv}\n"
               "\n⏳ <b>10 daqiqa ichida tasdiqlang!</b>\n"
               "<i>Aks holda buyurtma avtomatik bekor bo'ladi.</i>\n"),
        'ru': ("🔔 <b>Новый заказ!</b> {oid}\n\n"
               "📦 {pname}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Итого: <b>{total}</b>\n"
               "👤 Покупатель: {buyer}\n"
               "📞 {phone}\n"
               "🚚 {dlv}\n"
               "\n⏳ <b>Подтвердите в течение 10 минут!</b>\n"
               "<i>Иначе заказ будет автоматически отменён.</i>\n"),
    },
    'frag_dist_from_shop': {
        'uz': "📏 Do'kondan masofa: ~{km} km\n",
        'ru': "📏 Расстояние от магазина: ~{km} км\n",
    },
    'frag_seller_address': {'uz': "📍 Manzil: {addr}\n", 'ru': "📍 Адрес: {addr}\n"},
    'seller_client_location_below': {
        'uz': "📍 Mijoz lokatsiyasi quyida yuboriladi 👇\n",
        'ru': "📍 Геолокация клиента отправлена ниже 👇\n",
    },

    # --- SAVAT (CART) ---
    'cart_cant_add_own': {'uz': "❌ O'z mahsulotingizni qo'sha olmaysiz.", 'ru': "❌ Нельзя добавить свой товар."},
    'other_shop_word': {'uz': "boshqa do'kon", 'ru': "другой магазин"},
    'new_shop_word': {'uz': "yangi do'kon", 'ru': "новый магазин"},
    'cart_other_shop_q': {
        'uz': ("🛒 Savatingizda «{old}» mahsulotlari bor.\n\n"
               "Bitta buyurtmada faqat bitta do'kon bo'ladi. «{new}» uchun yangi savat ochilsinmi? (joriy savat o'chadi)"),
        'ru': ("🛒 В вашей корзине товары из «{old}».\n\n"
               "В одном заказе только один магазин. Открыть новую корзину для «{new}»? (текущая корзина очистится)"),
    },
    'btn_new_cart_for': {'uz': "🆕 Ha, «{shop}» uchun yangi savat", 'ru': "🆕 Да, новая корзина для «{shop}»"},
    'btn_view_current_cart': {'uz': "🛒 Joriy savatni ko'rish", 'ru': "🛒 Посмотреть текущую корзину"},
    'cart_stock_empty': {'uz': "❌ Bu mahsulot zahirada tugagan.", 'ru': "❌ Этот товар закончился."},
    'cart_added_toast': {'uz': "🛒 {name}: {qty} ta savatda", 'ru': "🛒 {name}: {qty} в корзине"},
    'product_unavailable_toast': {'uz': "❌ Mahsulot mavjud emas.", 'ru': "❌ Товар недоступен."},
    'new_cart_toast': {'uz': "🆕 Yangi savat: {name}", 'ru': "🆕 Новая корзина: {name}"},
    'new_cart_opened': {
        'uz': "🆕 Yangi savat ochildi: «{shop}».\n🛒 {name} — 1 ta qo'shildi.",
        'ru': "🆕 Открыта новая корзина: «{shop}».\n🛒 {name} — добавлено 1 шт.",
    },
    'btn_view_cart': {'uz': "🛒 Savatni ko'rish", 'ru': "🛒 Посмотреть корзину"},
    'btn_shop_products_menu': {'uz': "📦 Do'kon mahsulotlari", 'ru': "📦 Товары магазина"},
    'product_not_found_toast': {'uz': "❌ Mahsulot topilmadi.", 'ru': "❌ Товар не найден."},
    'only_n_available_toast': {'uz': "❌ Faqat {stock} dona mavjud.", 'ru': "❌ Доступно только {stock} шт."},
    'cart_qty_toast': {'uz': "🛒 {name}: {qty} ta", 'ru': "🛒 {name}: {qty}"},
    'removed_from_cart_toast': {'uz': "🗑 Savatdan olib tashlandi", 'ru': "🗑 Удалено из корзины"},
    'cart_empty': {'uz': "🛒 Savatingiz bo'sh.", 'ru': "🛒 Ваша корзина пуста."},
    'cart_view_header': {'uz': "🛒 <b>Savat — {shop}</b>\n", 'ru': "🛒 <b>Корзина — {shop}</b>\n"},
    'cart_view_item': {
        'uz': "• {name}\n   {qty} × {price} = <b>{subtotal}</b>",
        'ru': "• {name}\n   {qty} × {price} = <b>{subtotal}</b>",
    },
    'cart_view_total': {
        'uz': "\n💰 <b>Jami: {total}</b> ({count} dona)",
        'ru': "\n💰 <b>Итого: {total}</b> ({count} шт)",
    },
    'btn_checkout': {'uz': "✅ Rasmiylashtirish", 'ru': "✅ Оформить"},
    'btn_add_more': {'uz': "➕ Yana qo'shish", 'ru': "➕ Добавить ещё"},
    'btn_clear': {'uz': "🗑 Tozalash", 'ru': "🗑 Очистить"},
    'cart_clear_confirm': {'uz': "🗑 Savatni butunlay tozalaymizmi?", 'ru': "🗑 Очистить корзину полностью?"},
    'btn_yes_clear': {'uz': "✅ Ha, tozalash", 'ru': "✅ Да, очистить"},
    'btn_no_back': {'uz': "⬅️ Yo'q, qaytish", 'ru': "⬅️ Нет, назад"},
    'cart_cleared_toast': {'uz': "🗑 Savat tozalandi", 'ru': "🗑 Корзина очищена"},
    'cart_cleared': {'uz': "🛒 Savat tozalandi.", 'ru': "🛒 Корзина очищена."},
    'cart_checkout_header': {
        'uz': "🛒 <b>Savat:</b> {count} ta mahsulot, jami <b>{total}</b>\n\nQanday qabul qilasiz?",
        'ru': "🛒 <b>Корзина:</b> {count} товаров, итого <b>{total}</b>\n\nКак хотите получить?",
    },
    'checkout_cancelled': {
        'uz': "Rasmiylashtirish bekor qilindi. Savat saqlanib qoldi.",
        'ru': "Оформление отменено. Корзина сохранена.",
    },
    'btn_back_to_cart': {'uz': "🛒 Savatga qaytish", 'ru': "🛒 Вернуться в корзину"},
    'cart_confirm_header': {'uz': "🛒 <b>Buyurtmani tasdiqlang:</b>\n", 'ru': "🛒 <b>Подтвердите заказ:</b>\n"},
    'cart_confirm_shop': {'uz': "🏪 Do'kon: {shop}\n", 'ru': "🏪 Магазин: {shop}\n"},
    'cart_confirm_item': {
        'uz': "• {name} — {qty} × {price} = {subtotal}",
        'ru': "• {name} — {qty} × {price} = {subtotal}",
    },
    'cart_confirm_total': {'uz': "\n💰 Jami: <b>{total}</b>", 'ru': "\n💰 Итого: <b>{total}</b>"},
    'cart_confirm_delivery': {'uz': "🚚 Yetkazish: {dlv}", 'ru': "🚚 Доставка: {dlv}"},
    'cart_confirm_address': {'uz': "📍 Manzil: {addr}", 'ru': "📍 Адрес: {addr}"},
    'cart_confirm_payment': {'uz': "💳 To'lov: {pay}", 'ru': "💳 Оплата: {pay}"},
    'cart_empty_expired': {'uz': "🛒 Savat bo'sh yoki muddati o'tgan.", 'ru': "🛒 Корзина пуста или устарела."},
    'cart_skip_note': {
        'uz': "\n⚠️ Sotuvda bo'lmagani uchun qo'shilmadi: {names}",
        'ru': "\n⚠️ Не добавлено (нет в продаже): {names}",
    },
    'cart_order_placed': {
        'uz': ("✅ Buyurtmangiz qabul qilindi!\n\n"
               "Buyurtma raqami: <b>{oid}</b>\n"
               "📦 {count} ta mahsulot · 💰 Jami: <b>{total}</b>\n"
               "⏳ Sotuvchi <b>10 daqiqa</b> ichida tasdiqlashi kerak.\n"
               "Aks holda buyurtma avtomatik bekor bo'ladi.{skip}"),
        'ru': ("✅ Ваш заказ принят!\n\n"
               "Номер заказа: <b>{oid}</b>\n"
               "📦 {count} товаров · 💰 Итого: <b>{total}</b>\n"
               "⏳ Продавец должен подтвердить в течение <b>10 минут</b>.\n"
               "Иначе заказ будет автоматически отменён.{skip}"),
    },
    'cart_nothing_available': {
        'uz': "❌ Savatdagi mahsulotlar hozir sotuvda yo'q. Buyurtma yaratilmadi.",
        'ru': "❌ Товаров в корзине нет в продаже. Заказ не создан.",
    },

    # --- SOTUVCHIGA GURUH BILDIRISHNOMASI ---
    'seller_group_header': {
        'uz': "🔔 <b>Yangi buyurtma!</b> {oid}\n🛒 {count} ta mahsulot:\n",
        'ru': "🔔 <b>Новый заказ!</b> {oid}\n🛒 {count} товаров:\n",
    },
    'seller_group_item': {
        'uz': "• {name} — {qty} × {price} = {total}",
        'ru': "• {name} — {qty} × {price} = {total}",
    },
    'seller_group_total': {'uz': "💰 Jami: <b>{total}</b>", 'ru': "💰 Итого: <b>{total}</b>"},
    'seller_group_buyer': {'uz': "👤 Xaridor: {buyer}", 'ru': "👤 Покупатель: {buyer}"},
    'grp_dist_from_shop': {'uz': "📏 Do'kondan masofa: ~{km} km", 'ru': "📏 Расстояние от магазина: ~{km} км"},
    'grp_address': {'uz': "📍 Manzil: {addr}", 'ru': "📍 Адрес: {addr}"},
    'grp_client_location': {'uz': "📍 Mijoz lokatsiyasi quyida 👇", 'ru': "📍 Геолокация клиента ниже 👇"},
    'seller_group_confirm_prompt': {
        'uz': "\n⏳ <b>10 daqiqa ichida tasdiqlang!</b>",
        'ru': "\n⏳ <b>Подтвердите в течение 10 минут!</b>",
    },

    # --- XARIDOR GURUH BUYURTMA TAFSILOTI ---
    'group_order_header': {
        'uz': "🛒 <b>Buyurtma {oid}</b> — {count} ta mahsulot\n",
        'ru': "🛒 <b>Заказ {oid}</b> — {count} товаров\n",
    },
    'status_guide_pending_group': {
        'uz': "⏳ Sotuvchi hali tasdiqlamadi. Kuting yoki bekor qiling.",
        'ru': "⏳ Продавец ещё не подтвердил. Подождите или отмените.",
    },
    'label_status': {'uz': "Holat", 'ru': "Статус"},
    'dist_line_plain': {'uz': "📏 Masofa: ~{km} km", 'ru': "📏 Расстояние: ~{km} км"},
    'group_date_line': {'uz': "📅 {date}\n", 'ru': "📅 {date}\n"},
    'seller_notify_group_cancelled': {
        'uz': "❌ Xaridor {oid} buyurtmani bekor qildi ({count} ta mahsulot).",
        'ru': "❌ Покупатель отменил заказ {oid} ({count} товаров).",
    },
    'cant_cancel_now_toast': {
        'uz': "❌ Buyurtmani endi bekor qilib bo'lmaydi.",
        'ru': "❌ Заказ уже нельзя отменить.",
    },
    'not_your_order_toast': {'uz': "⛔ Bu buyurtma sizniki emas.", 'ru': "⛔ Это не ваш заказ."},

    # --- XARIDOR REYTINGLARI ---
    'my_reviews_empty': {
        'uz': "⭐ Siz hali hech qanday reyting qoldirmagan ekansiz.",
        'ru': "⭐ Вы ещё не оставляли отзывов.",
    },
    'my_reviews_header': {'uz': "⭐ <b>Mening baholarim</b> ({n} ta)\n", 'ru': "⭐ <b>Мои оценки</b> ({n})\n"},
    'review_to_product': {'uz': "Mahsulotga: ", 'ru': "Товару: "},

    # --- XABAR ALMASHISH ---
    'order_not_found_x': {'uz': "❌ Buyurtma topilmadi.", 'ru': "❌ Заказ не найден."},
    'sender_label_buyer': {'uz': "👤 {name} (xaridor)", 'ru': "👤 {name} (покупатель)"},
    'sender_label_seller': {'uz': "🏪 {name} (sotuvchi)", 'ru': "🏪 {name} (продавец)"},
    'btn_reply': {'uz': "💬 Javob berish", 'ru': "💬 Ответить"},
    'new_message_notify': {
        'uz': "💬 Yangi xabar — {oid}\n\n{sender}:\n{msg}",
        'ru': "💬 Новое сообщение — {oid}\n\n{sender}:\n{msg}",
    },
    'order_not_yours_full': {
        'uz': "❌ Buyurtma topilmadi yoki sizning buyurtmangiz emas.",
        'ru': "❌ Заказ не найден или не ваш.",
    },
    'no_messages_yet': {
        'uz': "📜 Bu buyurtma bo'yicha hali xabarlar yo'q.",
        'ru': "📜 По этому заказу пока нет сообщений.",
    },
    'messages_history_header': {
        'uz': "📜 <b>Yozishmalar — {oid}</b>\n",
        'ru': "📜 <b>Переписка — {oid}</b>\n",
    },
    'old_messages_cut': {'uz': "\n\n…(eski xabarlar kesildi)", 'ru': "\n\n…(старые сообщения обрезаны)"},
    'btn_new_message': {'uz': "💬 Yangi xabar", 'ru': "💬 Новое сообщение"},
    'recent_correspondence': {'uz': "💬 So'nggi yozishmalar:", 'ru': "💬 Последние переписки:"},

    # --- REYTING OQIMI ---
    'rate_product_ask': {
        'uz': "📦 <b>Mahsulotni baholang:</b>\nMahsulot sifatiga nechta yulduz berasiz?",
        'ru': "📦 <b>Оцените товар:</b>\nСколько звёзд за качество товара?",
    },
    'rate_product_comment_ask': {
        'uz': ("📝 <b>Mahsulot haqida izoh</b> (ixtiyoriy).\n"
               "Fikringizni yozing yoki o'tkazib yuborish uchun \"-\" yuboring:"),
        'ru': ("📝 <b>Комментарий о товаре</b> (необязательно).\n"
               "Напишите мнение или отправьте \"-\", чтобы пропустить:"),
    },
    'rate_seller_ask': {
        'uz': ("🏪 <b>Sotuvchini (do'konni) baholang:</b>\n"
               "Xizmat va muomalaga nechta yulduz berasiz?"),
        'ru': ("🏪 <b>Оцените продавца (магазин):</b>\n"
               "Сколько звёзд за сервис и отношение?"),
    },
    'rate_not_found': {
        'uz': "❌ Baho topilmadi. Qaytadan urinib ko'ring.",
        'ru': "❌ Оценка не найдена. Попробуйте снова.",
    },
    'rate_already': {
        'uz': "❌ Bu buyurtma uchun allaqachon baho qoldirgan ekansiz.",
        'ru': "❌ Вы уже оставили отзыв по этому заказу.",
    },
    'rate_seller_notify': {
        'uz': ("⭐ <b>Yangi baho!</b>\n\n"
               "📦 {pname}\n"
               "Mahsulotga: {pstars} {prate}/5\n"
               "Do'konga: {sstars} {srate}/5\n"
               "👤 Xaridor: {buyer}"),
        'ru': ("⭐ <b>Новый отзыв!</b>\n\n"
               "📦 {pname}\n"
               "Товару: {pstars} {prate}/5\n"
               "Магазину: {sstars} {srate}/5\n"
               "👤 Покупатель: {buyer}"),
    },
    'rate_comment_line': {'uz': "\n💬 Izoh: {comment}", 'ru': "\n💬 Комментарий: {comment}"},
    'rate_thanks': {
        'uz': "✅ Rahmat! Bahoyingiz qabul qilindi.\n📦 Mahsulot: {pstars}\n🏪 Do'kon: {sstars}",
        'ru': "✅ Спасибо! Ваша оценка принята.\n📦 Товар: {pstars}\n🏪 Магазин: {sstars}",
    },

    # --- QIDIRUV MATN/LOKATSIYA ISHLOVI ---
    'shop_not_found_q': {
        'uz': "❌ '{q}' bo'yicha do'kon topilmadi.",
        'ru': "❌ По запросу '{q}' магазин не найден.",
    },
    'btn_retry_search': {'uz': "🔍 Qayta qidirish", 'ru': "🔍 Искать снова"},
    'search_location_full': {
        'uz': ("📍 Lokatsiyangizni yuboring — sizga eng yaqin do'konlar birinchi ko'rsatiladi.\n"
               "Yoki lokatsiyasiz davom etish uchun pastdagi tugmani bosing."),
        'ru': ("📍 Отправьте геолокацию — ближайшие магазины будут показаны первыми.\n"
               "Или нажмите кнопку ниже, чтобы продолжить без геолокации."),
    },
    'or_below': {'uz': "👇 yoki:", 'ru': "👇 или:"},
    'text_instead_of_location': {
        'uz': "Lokatsiya o'rniga matn yubordingiz — lokatsiyasiz qidiramiz.",
        'ru': "Вы отправили текст вместо геолокации — ищем без неё.",
    },
    'location_received_searching': {
        'uz': "📍 Lokatsiya qabul qilindi. '{q}' bo'yicha qidirilmoqda...",
        'ru': "📍 Геолокация принята. Идёт поиск по '{q}'...",
    },
    'unknown_command': {
        'uz': ("Buyruqni tanlang:\n"
               "/start — Boshlash\n"
               "/admin — Admin panel\n"
               "/recommend — AI tavsiyalari"),
        'ru': ("Выберите команду:\n"
               "/start — Начать\n"
               "/admin — Панель администратора\n"
               "/recommend — AI рекомендации"),
    },

    # --- SOTUVCHI BILAN BOG'LANISH ---
    'contact_seller_unavailable': {'uz': "Sotuvchi bilan bog'lanib bo'lmadi.", 'ru': "Не удалось связаться с продавцом."},
    'this_is_your_product': {'uz': "Bu sizning mahsulotingiz.", 'ru': "Это ваш товар."},
    'tg_not_shown': {'uz': "ko'rsatilmagan", 'ru': "не указан"},
    'seller_word': {'uz': "Sotuvchi", 'ru': "Продавец"},
    'contact_seller_text': {
        'uz': ("📞 <b>{shop}</b> bilan bog'lanish:\n\n"
               "☎️ Telefon: <code>{phone}</code>\n"
               "📱 Telegram: {tg}\n\n"
               "📦 Mahsulot: {pname}"),
        'ru': ("📞 Связаться с <b>{shop}</b>:\n\n"
               "☎️ Телефон: <code>{phone}</code>\n"
               "📱 Telegram: {tg}\n\n"
               "📦 Товар: {pname}"),
    },
    'btn_write_telegram': {'uz': "📱 Telegramda yozish", 'ru': "📱 Написать в Telegram"},
    'deeplink_product_unavailable': {
        'uz': "❌ Bu mahsulot topilmadi yoki sotuvda yo'q.",
        'ru': "❌ Этот товар не найден или не в продаже.",
    },
    'seller_interest_notify': {
        'uz': ("❓ <b>Mahsulotingizga qiziqish bor!</b>\n\n"
               "📦 {pname}\n\n"
               "👤 Xaridor: {buyer}\n"
               "📞 Telefon: <code>{phone}</code>\n"
               "📱 Telegram: {tg}\n\n"
               "<i>Xaridor siz bilan bog'lanmoqchi.\nTelefon orqali murojaat qiling.</i>"),
        'ru': ("❓ <b>Есть интерес к вашему товару!</b>\n\n"
               "📦 {pname}\n\n"
               "👤 Покупатель: {buyer}\n"
               "📞 Телефон: <code>{phone}</code>\n"
               "📱 Telegram: {tg}\n\n"
               "<i>Покупатель хочет связаться с вами.\nСвяжитесь по телефону.</i>"),
    },

    # --- SOTUVCHI REYTINGLARI ---
    'reviews_none': {'uz': "⭐ Hozircha reytinglar yo'q.", 'ru': "⭐ Пока нет отзывов."},
    'seller_avg_header': {
        'uz': "⭐ O'rtacha reyting: <b>{avg}/5.0</b> ({count} ta baho)\n",
        'ru': "⭐ Средний рейтинг: <b>{avg}/5.0</b> ({count} оценок)\n",
    },
    'review_shop_to': {'uz': "\n🏪 Do'konga: ", 'ru': "\n🏪 Магазину: "},
    'review_product_to': {'uz': "\n📦 Mahsulotga: ", 'ru': "\n📦 Товару: "},
    'reviews_old_cut_seller': {
        'uz': "\n\n…(eski reytinglar kesildi)",
        'ru': "\n\n…(старые отзывы обрезаны)",
    },

    # --- SOTUVCHI STATISTIKA ---
    'seller_stats_body': {
        'uz': ("📊 <b>{shop} statistikasi</b>\n\n"
               "📦 Mahsulotlar soni: <b>{products}</b>\n"
               "⭐ O'rtacha reyting: <b>{rating}/5.0</b>\n\n"
               "<b>So'nggi 7 kun</b>\n"
               "🛒 Buyurtmalar: {week_orders}\n"
               "💰 Daromad (yetkazilgan): {week_revenue}\n\n"
               "<b>So'nggi 30 kun</b>\n"
               "🛒 Buyurtmalar: {month_orders}\n"
               "💰 Daromad: {month_revenue}\n\n"
               "<b>Jami</b>\n"
               "🛒 Buyurtmalar: {total_orders}\n"
               "⏳ Yangi: {pending}\n"
               "✅ Tasdiqlangan: {confirmed}\n"
               "🚚 Yetkazilgan: {delivered}\n"
               "❌ Bekor qilingan: {cancelled}\n"
               "💰 Jami daromad: <b>{total_revenue}</b>"),
        'ru': ("📊 <b>Статистика {shop}</b>\n\n"
               "📦 Кол-во товаров: <b>{products}</b>\n"
               "⭐ Средний рейтинг: <b>{rating}/5.0</b>\n\n"
               "<b>Последние 7 дней</b>\n"
               "🛒 Заказы: {week_orders}\n"
               "💰 Доход (доставленные): {week_revenue}\n\n"
               "<b>Последние 30 дней</b>\n"
               "🛒 Заказы: {month_orders}\n"
               "💰 Доход: {month_revenue}\n\n"
               "<b>Всего</b>\n"
               "🛒 Заказы: {total_orders}\n"
               "⏳ Новые: {pending}\n"
               "✅ Подтверждённые: {confirmed}\n"
               "🚚 Доставленные: {delivered}\n"
               "❌ Отменённые: {cancelled}\n"
               "💰 Общий доход: <b>{total_revenue}</b>"),
    },
    'btn_detailed_excel': {'uz': "📥 Batafsil hisobot (Excel)", 'ru': "📥 Подробный отчёт (Excel)"},

    # --- EXCEL EKSPORT (chat xabarlari) ---
    'excel_preparing': {'uz': "⏳ Excel tayyorlanmoqda...", 'ru': "⏳ Готовится Excel..."},
    'excel_caption': {
        'uz': "📊 {shop} — to'liq hisobot\n🛒 {orders} ta buyurtma · 📦 {products} ta mahsulot · ⭐ {reviews} ta baho\n{ts}",
        'ru': "📊 {shop} — полный отчёт\n🛒 {orders} заказов · 📦 {products} товаров · ⭐ {reviews} оценок\n{ts}",
    },
    'excel_shop_default': {'uz': "Do'koningiz", 'ru': "Ваш магазин"},
    'excel_not_installed': {
        'uz': "❌ openpyxl o'rnatilmagan.\n\nTerminalda: <code>pip install openpyxl</code>",
        'ru': "❌ openpyxl не установлен.\n\nВ терминале: <code>pip install openpyxl</code>",
    },
    'excel_failed': {'uz': "❌ Hisobot yaratishda xato.", 'ru': "❌ Ошибка при создании отчёта."},
    'error_generic': {'uz': "❌ Xato: {e}", 'ru': "❌ Ошибка: {e}"},
    'stale_cancel_notify': {
        'uz': "⏳ Buyurtma {oid} avtomatik bekor qilindi (3 kun ichida tasdiqlanmadi).",
        'ru': "⏳ Заказ {oid} автоматически отменён (не подтверждён за 3 дня).",
    },

    # --- MAHSULOT QO'SHISH ---
    'add_product_name_ask': {'uz': "Mahsulot nomini kiriting (3–100 belgi):", 'ru': "Введите название товара (3–100 символов):"},
    'name_too_short': {'uz': "❌ Nom juda qisqa. Kamida 3 belgi kiriting:", 'ru': "❌ Название слишком короткое. Минимум 3 символа:"},
    'name_too_long': {'uz': "❌ Nom juda uzun (maksimal 100 belgi). Qisqartiring:", 'ru': "❌ Название слишком длинное (макс. 100 символов). Сократите:"},
    'add_product_price_ask': {
        'uz': "Mahsulot narxini kiriting (so'mda, faqat raqam — masalan: 50000):",
        'ru': "Введите цену товара (в сумах, только число — например: 50000):",
    },
    'price_invalid': {'uz': "❌ Iltimos, to'g'ri raqam kiriting (masalan: 50000):", 'ru': "❌ Введите корректное число (например: 50000):"},
    'price_positive': {'uz': "❌ Narx 0 dan katta bo'lishi kerak:", 'ru': "❌ Цена должна быть больше 0:"},
    'price_too_big': {'uz': "❌ Narx juda katta. Qaytadan kiriting:", 'ru': "❌ Цена слишком большая. Введите заново:"},
    'choose_category': {'uz': "Kategoriyani tanlang:", 'ru': "Выберите категорию:"},
    'add_product_desc_ask': {
        'uz': "Mahsulot tavsifini kiriting (maksimal 500 belgi).\nO'tkazib yuborish uchun '-' yozing:",
        'ru': "Введите описание товара (макс. 500 символов).\nЧтобы пропустить, напишите '-':",
    },
    'desc_too_long': {'uz': "❌ Tavsif juda uzun (maksimal 500 belgi). Qisqartiring:", 'ru': "❌ Описание слишком длинное (макс. 500 символов). Сократите:"},
    'add_photo_ask': {
        'uz': ("📷 Mahsulot rasm(lar)ini yuboring — 4 tagacha qo'shsangiz bo'ladi.\n"
               "Birinchi rasmni yuboring, yoki rasmsiz saqlash uchun '-' yozing."),
        'ru': ("📷 Отправьте фото товара — можно до 4 штук.\n"
               "Отправьте первое фото или напишите '-', чтобы сохранить без фото."),
    },
    'photo_too_big': {
        'uz': "❌ Rasm juda katta (maksimal 5 MB).\nKichikroq rasm yuboring yoki '-' yozing (rasmsiz saqlash):",
        'ru': "❌ Фото слишком большое (макс. 5 МБ).\nОтправьте меньше или напишите '-' (без фото):",
    },
    'photo_too_small': {
        'uz': "❌ Rasm juda kichik (kamida 200x200 piksel).\nSifatliroq rasm yuboring yoki '-' yozing:",
        'ru': "❌ Фото слишком маленькое (мин. 200x200 пикс).\nОтправьте качественнее или '-':",
    },
    'only_images': {
        'uz': "❌ Faqat rasm fayllar qabul qilinadi (JPG, PNG, WEBP).\nRasmni rasm sifatida yuboring yoki '-' yozing:",
        'ru': "❌ Принимаются только изображения (JPG, PNG, WEBP).\nОтправьте как фото или '-':",
    },
    'photo_too_big_doc': {
        'uz': "❌ Rasm juda katta (maksimal 5 MB).\nKichikroq rasm yuboring yoki '-' yozing:",
        'ru': "❌ Фото слишком большое (макс. 5 МБ).\nОтправьте меньше или '-':",
    },
    'no_sticker': {'uz': "❌ Sticker qabul qilinmaydi. Oddiy rasm yuboring yoki '-' yozing:", 'ru': "❌ Стикеры не принимаются. Отправьте обычное фото или '-':"},
    'send_photo_or_skip': {'uz': "❌ Iltimos, rasm yuboring yoki '-' yozing (rasmsiz/tugatish uchun):", 'ru': "❌ Отправьте фото или '-' (без фото/завершить):"},
    'photos_max_added': {'uz': "✅ {n} ta rasm qo'shildi — bu maksimal. Keyingi bosqichga o'tamiz.", 'ru': "✅ Добавлено {n} фото — это максимум. Переходим дальше."},
    'btn_add_more_photo': {'uz': "➕ Yana rasm qo'shish", 'ru': "➕ Добавить ещё фото"},
    'btn_continue': {'uz': "➡️ Davom etish", 'ru': "➡️ Продолжить"},
    'photos_added_n': {
        'uz': "✅ {n}/{max} ta rasm qo'shildi.\nYana rasm qo'shasizmi yoki keyingi bosqichga o'tasizmi?",
        'ru': "✅ Добавлено {n}/{max} фото.\nДобавить ещё или перейти дальше?",
    },
    'next_photo_ask': {'uz': "📷 Keyingi rasmni yuboring ({n}/{max}):", 'ru': "📷 Отправьте следующее фото ({n}/{max}):"},
    'attr_optional_mark': {'uz': " (ixtiyoriy)", 'ru': " (необязательно)"},
    'attr_eg': {'uz': "\nMasalan: {hint}", 'ru': "\nНапример: {hint}"},
    'attr_skip_note': {'uz': "\nO'tkazib yuborish uchun '-' yozing.", 'ru': "\nЧтобы пропустить, напишите '-'."},
    'btn_attr_skip': {'uz': "⏭ O'tkazib yuborish", 'ru': "⏭ Пропустить"},
    'attr_required_field': {'uz': "❌ Bu maydon majburiy. Qaytadan kiriting:", 'ru': "❌ Это обязательное поле. Введите заново:"},
    'product_saved': {'uz': "✅ Mahsulot muvaffaqiyatli qo'shildi!", 'ru': "✅ Товар успешно добавлен!"},
    'frag_photos_saved': {'uz': "\n🖼 {n} ta rasm saqlandi.", 'ru': "\n🖼 Сохранено {n} фото."},
    'frag_attrs_saved': {'uz': "\n📋 {n} ta xususiyat saqlandi.", 'ru': "\n📋 Сохранено {n} характеристик."},

    # --- MAHSULOTLARIM RO'YXATI ---
    'my_products_overview': {
        'uz': ("📦 <b>Mahsulotlarim</b>\n\n"
               "✅ Sotuvda: {active} ta\n"
               "📥 Zahirada: {reserve} ta\n"
               "🗑 O'chirilgan: {deleted} ta\n\n"
               "Bo'limni tanlang:"),
        'ru': ("📦 <b>Мои товары</b>\n\n"
               "✅ В продаже: {active}\n"
               "📥 В резерве: {reserve}\n"
               "🗑 Удалённые: {deleted}\n\n"
               "Выберите раздел:"),
    },
    'btn_on_sale_n': {'uz': "✅ Sotuvda ({n})", 'ru': "✅ В продаже ({n})"},
    'btn_reserve_n': {'uz': "📥 Zahirada ({n})", 'ru': "📥 В резерве ({n})"},
    'btn_deleted_n': {'uz': "🗑 O'chirilgan ({n})", 'ru': "🗑 Удалённые ({n})"},
    'btn_search_product': {'uz': "🔍 Mahsulot qidirish", 'ru': "🔍 Поиск товара"},
    'status_on_sale': {'uz': "✅ Sotuvda", 'ru': "✅ В продаже"},
    'status_reserve_short': {'uz': "📥 Zahirada", 'ru': "📥 В резерве"},
    'status_deleted_short': {'uz': "🗑 O'chirilgan", 'ru': "🗑 Удалённые"},
    'section_empty': {'uz': "{status} — bo'sh.", 'ru': "{status} — пусто."},
    'frag_stock_pieces': {'uz': " ({n} dona)", 'ru': " ({n} шт)"},
    'section_page': {'uz': "{status} — jami {total} ta. Sahifa {page}/{pages}:", 'ru': "{status} — всего {total}. Страница {page}/{pages}:"},

    # --- MAHSULOT QIDIRISH (sotuvchi) ---
    'seller_search_prompt': {
        'uz': "🔍 Qidirayotgan mahsulot nomini yozing:\n\n<i>Masalan: Coca yoki non</i>",
        'ru': "🔍 Введите название искомого товара:\n\n<i>Например: Coca или хлеб</i>",
    },
    'seller_search_none': {'uz': "🔍 '{q}' bo'yicha hech narsa topilmadi.", 'ru': "🔍 По '{q}' ничего не найдено."},
    'btn_my_products_back': {'uz': "⬅️ Mahsulotlarim", 'ru': "⬅️ Мои товары"},
    'seller_search_found': {'uz': "🔍 '{q}' — {n} ta topildi:", 'ru': "🔍 '{q}' — найдено {n}:"},

    # --- MAHSULOT MENYUSI (sotuvchi) ---
    'pm_status_active': {'uz': "✅ Sotuvda mavjud", 'ru': "✅ В продаже"},
    'pm_status_reserve': {'uz': "📥 Zahirada", 'ru': "📥 В резерве"},
    'pm_status_deleted': {'uz': "🗑 O'chirilgan", 'ru': "🗑 Удалён"},
    'btn_edit': {'uz': "✏️ Tahrirlash", 'ru': "✏️ Редактировать"},
    'btn_share_link': {'uz': "🔗 Havola ulashish", 'ru': "🔗 Поделиться ссылкой"},
    'btn_to_reserve': {'uz': "📥 Zahiraga olish", 'ru': "📥 В резерв"},
    'btn_set_stock': {'uz': "📦 Zahira sonini belgilash", 'ru': "📦 Указать остаток"},
    'btn_remove_from_sale': {'uz': "🗑 Sotuvdan o'chirish", 'ru': "🗑 Снять с продажи"},
    'btn_return_to_sale': {'uz': "✅ Sotuvga qaytarish", 'ru': "✅ Вернуть в продажу"},
    'btn_repost_sale': {'uz': "✅ Qayta sotuvga qo'yish", 'ru': "✅ Снова выставить"},
    'btn_delete_forever': {'uz': "❌ Butunlay o'chirish", 'ru': "❌ Удалить навсегда"},
    'pm_stock_line': {'uz': "\nZahira soni: {n} dona", 'ru': "\nОстаток: {n} шт"},
    'pm_stock_unlimited': {'uz': "\nZahira: cheklanmagan", 'ru': "\nОстаток: без лимита"},
    'pm_attrs_title': {'uz': "\n\n🏷 Xususiyatlar:\n", 'ru': "\n\n🏷 Характеристики:\n"},
    'product_menu_body': {
        'uz': ("📦 <b>{name}</b>\n\n"
               "Narxi: {price}\n"
               "Holat: {status}{stock}\n"
               "Tavsif: {desc}{attrs}"),
        'ru': ("📦 <b>{name}</b>\n\n"
               "Цена: {price}\n"
               "Статус: {status}{stock}\n"
               "Описание: {desc}{attrs}"),
    },

    # --- STATUS O'ZGARTIRISH ---
    'pstatus_active_toast': {'uz': "✅ Mahsulot sotuvga qaytarildi", 'ru': "✅ Товар возвращён в продажу"},
    'pstatus_reserve_toast': {'uz': "📥 Mahsulot zahiraga olindi", 'ru': "📥 Товар отправлен в резерв"},
    'pstatus_deleted_toast': {'uz': "🗑 Mahsulot sotuvdan o'chirildi", 'ru': "🗑 Товар снят с продажи"},
    'status_changed_toast': {'uz': "Holat o'zgardi", 'ru': "Статус изменён"},

    # --- ZAHIRA ---
    'set_stock_ask': {
        'uz': ("📦 Zahira sonini kiriting (faqat raqam).\n"
               "Cheksiz qilish uchun '-' yozing.\n"
               "Bekor qilish uchun /cancel yoki bosh sahifaga qayting."),
        'ru': ("📦 Введите количество остатка (только число).\n"
               "Для безлимита напишите '-'.\n"
               "Для отмены — /cancel или вернитесь на главную."),
    },
    'stock_invalid': {
        'uz': "❌ Manfiy bo'lmagan butun son yoki '-' yozing. Qaytadan urinish uchun mahsulot menyusiga qayting.",
        'ru': "❌ Введите неотрицательное целое число или '-'. Для повтора вернитесь в меню товара.",
    },
    'stock_set_unlimited': {'uz': "✅ Zahira: cheklanmagan qilib belgilandi.", 'ru': "✅ Остаток: установлен без лимита."},
    'stock_set_n': {'uz': "✅ Zahira: {n} dona qilib belgilandi.", 'ru': "✅ Остаток: установлено {n} шт."},

    # --- O'CHIRISH ---
    'delete_confirm_ask': {
        'uz': "⚠️ Haqiqatan ham bu mahsulotni o'chirmoqchimisiz?\nBu amalni qaytarib bo'lmaydi!",
        'ru': "⚠️ Вы действительно хотите удалить этот товар?\nЭто действие необратимо!",
    },
    'btn_yes_delete': {'uz': "✅ Ha, o'chirish", 'ru': "✅ Да, удалить"},
    'btn_no_cancel': {'uz': "❌ Yo'q, bekor", 'ru': "❌ Нет, отмена"},
    'product_deleted': {'uz': "✅ Mahsulot o'chirildi.", 'ru': "✅ Товар удалён."},
    'product_deleted_kept_history': {
        'uz': "✅ Mahsulot olib tashlandi.\n\nℹ️ Bu mahsulotda buyurtma tarixi bo'lgani uchun yozuv arxivlandi (endi hech qaysi ro'yxatda ko'rinmaydi), buyurtma tarixi esa saqlanib qoldi.",
        'ru': "✅ Товар удалён.\n\nℹ️ Так как по товару есть история заказов, запись архивирована (больше не отображается ни в одном списке), а история заказов сохранена.",
    },

    # --- MAHSULOTNI TAHRIRLASH (hub) ---
    'ef_btn_name': {'uz': "✏️ Nomi", 'ru': "✏️ Название"},
    'ef_btn_price': {'uz': "💰 Narxi", 'ru': "💰 Цена"},
    'ef_btn_cat': {'uz': "🗂 Kategoriya", 'ru': "🗂 Категория"},
    'ef_btn_desc': {'uz': "📝 Tavsif", 'ru': "📝 Описание"},
    'ef_btn_photos': {'uz': "🖼 Rasmlar", 'ru': "🖼 Фото"},
    'edit_title': {'uz': "✏️ <b>Mahsulotni tahrirlash</b>", 'ru': "✏️ <b>Редактирование товара</b>"},
    'edit_lbl_name': {'uz': "📦 <b>Nomi:</b> {v}", 'ru': "📦 <b>Название:</b> {v}"},
    'edit_lbl_price': {'uz': "💰 <b>Narxi:</b> {v}", 'ru': "💰 <b>Цена:</b> {v}"},
    'edit_lbl_cat': {'uz': "🗂 <b>Kategoriya:</b> {v}", 'ru': "🗂 <b>Категория:</b> {v}"},
    'edit_lbl_photos': {'uz': "🖼 <b>Rasmlar:</b> {n} ta", 'ru': "🖼 <b>Фото:</b> {n}"},
    'edit_lbl_desc': {'uz': "📝 <b>Tavsif:</b> {v}", 'ru': "📝 <b>Описание:</b> {v}"},
    'edit_attrs_title': {'uz': "🏷 <b>Xususiyatlar:</b>", 'ru': "🏷 <b>Характеристики:</b>"},
    'edit_which_part': {'uz': "Qaysi qismini tahrirlaysiz?", 'ru': "Какую часть редактируете?"},
    'category_not_selected': {'uz': "Tanlanmagan", 'ru': "Не выбрана"},

    # --- TAHRIR MAYDONLARI ---
    'edit_name_ask': {'uz': "✏️ Yangi nomni kiriting (3–100 belgi):", 'ru': "✏️ Введите новое название (3–100 символов):"},
    'edit_name_short': {'uz': "❌ Nom juda qisqa. Kamida 3 belgi:", 'ru': "❌ Название слишком короткое. Минимум 3 символа:"},
    'edit_name_long': {'uz': "❌ Nom juda uzun (maks. 100 belgi):", 'ru': "❌ Название слишком длинное (макс. 100 символов):"},
    'name_updated': {'uz': "✅ Nom yangilandi.", 'ru': "✅ Название обновлено."},
    'edit_price_ask': {'uz': "💰 Yangi narxni kiriting (so'mda, faqat raqam — masalan: 50000):", 'ru': "💰 Введите новую цену (в сумах, только число — например: 50000):"},
    'edit_price_invalid': {'uz': "❌ To'g'ri raqam kiriting:", 'ru': "❌ Введите корректное число:"},
    'edit_price_range': {'uz': "❌ Narx 0 dan katta va mantiqiy bo'lishi kerak:", 'ru': "❌ Цена должна быть больше 0 и разумной:"},
    'price_updated': {'uz': "✅ Narx yangilandi.", 'ru': "✅ Цена обновлена."},
    'edit_cat_ask': {'uz': "🗂 Yangi kategoriyani tanlang:", 'ru': "🗂 Выберите новую категорию:"},
    'btn_cancel_edit': {'uz': "⬅️ Bekor qilish", 'ru': "⬅️ Отмена"},
    'edit_desc_ask': {'uz': "📝 Yangi tavsifni kiriting (maks. 500 belgi).\nTavsifni o'chirish uchun '-' yozing:", 'ru': "📝 Введите новое описание (макс. 500 символов).\nЧтобы удалить описание, напишите '-':"},
    'edit_desc_long': {'uz': "❌ Tavsif juda uzun (maks. 500 belgi):", 'ru': "❌ Описание слишком длинное (макс. 500 символов):"},
    'desc_updated': {'uz': "✅ Tavsif yangilandi.", 'ru': "✅ Описание обновлено."},
    'edit_photos_ask': {
        'uz': ("🖼 Mahsulotning yangi rasm(lar)ini yuboring — 4 tagacha.\n"
               "Birinchi rasmni yuboring.\nBarcha rasmlarni o'chirish uchun '-' yozing."),
        'ru': ("🖼 Отправьте новые фото товара — до 4 штук.\n"
               "Отправьте первое фото.\nЧтобы удалить все фото, напишите '-'."),
    },
    'edit_photo_too_big': {'uz': "❌ Rasm juda katta (maks. 5 MB). Boshqa rasm yuboring:", 'ru': "❌ Фото слишком большое (макс. 5 МБ). Отправьте другое:"},
    'edit_photo_too_small': {'uz': "❌ Rasm juda kichik (kamida 200x200). Boshqa rasm yuboring:", 'ru': "❌ Фото слишком маленькое (мин. 200x200). Отправьте другое:"},
    'all_photos_deleted': {'uz': "✅ Barcha rasmlar o'chirildi.", 'ru': "✅ Все фото удалены."},
    'edit_photo_send_or_dash': {'uz': "❌ Rasm yuboring yoki '-' yozing (rasmlarni o'chirish uchun):", 'ru': "❌ Отправьте фото или '-' (чтобы удалить фото):"},
    'photos_saved_max': {'uz': "✅ {n} ta rasm saqlandi (maksimal).", 'ru': "✅ Сохранено {n} фото (максимум)."},
    'btn_save': {'uz': "✅ Saqlash", 'ru': "✅ Сохранить"},
    'photos_selected_n': {'uz': "✅ {n}/{max} ta rasm tanlandi.\nYana rasm qo'shasizmi yoki saqlaysizmi?", 'ru': "✅ Выбрано {n}/{max} фото.\nДобавить ещё или сохранить?"},
    'next_photo_edit': {'uz': "🖼 Keyingi rasmni yuboring ({n}/{max}):", 'ru': "🖼 Отправьте следующее фото ({n}/{max}):"},
    'edit_attr_ask': {'uz': "🏷 <b>{label}</b> uchun yangi qiymatni kiriting.\nO'chirish uchun '-' yozing:", 'ru': "🏷 Введите новое значение для <b>{label}</b>.\nЧтобы удалить, напишите '-':"},
    'edit_proc_error': {'uz': "Xato: tahrir jarayoni noto'g'ri boshlandi.", 'ru': "Ошибка: процесс редактирования начат неверно."},
    'attr_too_long': {'uz': "❌ Juda uzun (maks. 100 belgi). Qaytadan kiriting:", 'ru': "❌ Слишком длинно (макс. 100 символов). Введите заново:"},
    'attr_deleted': {'uz': "✅ Xususiyat o'chirildi.", 'ru': "✅ Характеристика удалена."},
    'attr_updated': {'uz': "✅ Xususiyat yangilandi.", 'ru': "✅ Характеристика обновлена."},

    # --- SOTUVCHI BUYURTMALARI RO'YXATI ---
    'seller_order_group_row': {'uz': "{emoji} 🛒 {buyer} — {count} ta • {sum}", 'ru': "{emoji} 🛒 {buyer} — {count} шт • {sum}"},
    'seller_order_row': {'uz': "{emoji} {buyer} — {total}", 'ru': "{emoji} {buyer} — {total}"},
    'orders_title': {'uz': "🛒 Buyurtmalar:", 'ru': "🛒 Заказы:"},

    # --- GURUH HOLATI O'ZGARISHI (xaridorga bildirishnoma) ---
    'grp_confirmed_pickup': {
        'uz': "✅ Buyurtmangiz <b>tasdiqlandi!</b>\n{oid} — {n} ta mahsulot\n🚶 Do'konga borib olishingiz mumkin.",
        'ru': "✅ Ваш заказ <b>подтверждён!</b>\n{oid} — {n} товаров\n🚶 Можете забрать в магазине.",
    },
    'grp_confirmed_delivery': {
        'uz': "✅ Buyurtmangiz <b>tasdiqlandi!</b>\n{oid} — {n} ta mahsulot\n📦 Yetkazib berish kutilmoqda. Sotuvchi siz bilan bog'lanadi.",
        'ru': "✅ Ваш заказ <b>подтверждён!</b>\n{oid} — {n} товаров\n📦 Ожидается доставка. Продавец свяжется с вами.",
    },
    'grp_cancelled_notify': {
        'uz': "❌ Buyurtmangiz <b>bekor qilindi.</b>\n{oid} — {n} ta mahsulot",
        'ru': "❌ Ваш заказ <b>отменён.</b>\n{oid} — {n} товаров",
    },
    'grp_delivered_pickup': {
        'uz': "✅ Tovar olindi!\n{oid} — {n} ta mahsulot\n⭐ Sotuvchiga reyting qoldiring!",
        'ru': "✅ Товар получен!\n{oid} — {n} товаров\n⭐ Оставьте отзыв продавцу!",
    },
    'grp_delivered_delivery': {
        'uz': "🚚 Buyurtmangiz yetkazildi!\n{oid} — {n} ta mahsulot\n⭐ Sotuvchiga reyting qoldiring!",
        'ru': "🚚 Ваш заказ доставлен!\n{oid} — {n} товаров\n⭐ Оставьте отзыв продавцу!",
    },

    # --- YAKKA BUYURTMA HOLATI (xaridorga) ---
    'order_confirmed_pickup': {
        'uz': "✅ Buyurtmangiz <b>tasdiqlandi!</b>\n{oid} — {pname}\n🚶 Do'konga borib olishingiz mumkin.",
        'ru': "✅ Ваш заказ <b>подтверждён!</b>\n{oid} — {pname}\n🚶 Можете забрать в магазине.",
    },
    'order_confirmed_delivery': {
        'uz': "✅ Buyurtmangiz <b>tasdiqlandi!</b>\n{oid} — {pname}\n📦 Yetkazib berish kutilmoqda. Sotuvchi siz bilan bog'lanadi.",
        'ru': "✅ Ваш заказ <b>подтверждён!</b>\n{oid} — {pname}\n📦 Ожидается доставка. Продавец свяжется с вами.",
    },
    'order_cancelled_notify': {
        'uz': "❌ Buyurtmangiz <b>bekor qilindi.</b>\n{oid} — {pname}\nBoshqa do'konlardan qidirib ko'ring.",
        'ru': "❌ Ваш заказ <b>отменён.</b>\n{oid} — {pname}\nПопробуйте поискать в других магазинах.",
    },
    'order_delivered_pickup': {
        'uz': "✅ Tovar olindi!\n{oid} — {pname}\n⭐ Sotuvchiga reyting qoldiring!",
        'ru': "✅ Товар получен!\n{oid} — {pname}\n⭐ Оставьте отзыв продавцу!",
    },
    'order_delivered_delivery': {
        'uz': "🚚 Buyurtmangiz yetkazildi!\n{oid} — {pname}\n⭐ Sotuvchiga reyting qoldiring!",
        'ru': "🚚 Ваш заказ доставлен!\n{oid} — {pname}\n⭐ Оставьте отзыв продавцу!",
    },

    # --- AVTOMATIK JOB BILDIRISHNOMALAR ---
    'job_group_autocancel_buyer': {
        'uz': "⏰ Buyurtma {oid} avtomatik bekor qilindi (sotuvchi 10 daqiqada tasdiqlamadi).",
        'ru': "⏰ Заказ {oid} автоматически отменён (продавец не подтвердил за 10 минут).",
    },
    'job_group_autocancel_seller': {
        'uz': "⏰ {oid} buyurtma tasdiqlanmagani uchun avtomatik bekor qilindi.",
        'ru': "⏰ Заказ {oid} автоматически отменён из-за отсутствия подтверждения.",
    },
    'job_group_reminder_seller': {
        'uz': "⏳ Eslatma: {oid} buyurtma ({n} ta mahsulot, {total}) hali tasdiqlanmagan. 5 daqiqa qoldi!",
        'ru': "⏳ Напоминание: заказ {oid} ({n} товаров, {total}) ещё не подтверждён. Осталось 5 минут!",
    },
    'btn_open_order': {'uz': "🛒 Buyurtmani ochish", 'ru': "🛒 Открыть заказ"},
    'job_reminder_seller': {
        'uz': ("⏰ <b>Eslatma!</b> Buyurtma hali tasdiqlanmagan.\n\n"
               "📦 {pname}\n"
               "👤 Xaridor: {buyer}\n"
               "💰 Jami: {total}\n\n"
               "⚠️ <b>5 daqiqa qoldi!</b> Aks holda buyurtma avtomatik bekor bo'ladi."),
        'ru': ("⏰ <b>Напоминание!</b> Заказ ещё не подтверждён.\n\n"
               "📦 {pname}\n"
               "👤 Покупатель: {buyer}\n"
               "💰 Итого: {total}\n\n"
               "⚠️ <b>Осталось 5 минут!</b> Иначе заказ будет автоматически отменён."),
    },
    'job_autocancel_buyer': {
        'uz': ("⏰ <b>Buyurtma avtomatik bekor qilindi</b>\n\n"
               "Buyurtma: {oid}\n"
               "Sabab: Sotuvchi 10 daqiqa ichida tasdiqlamadi.\n\n"
               "Boshqa sotuvchilardan xarid qilishingiz mumkin."),
        'ru': ("⏰ <b>Заказ автоматически отменён</b>\n\n"
               "Заказ: {oid}\n"
               "Причина: продавец не подтвердил за 10 минут.\n\n"
               "Вы можете купить у других продавцов."),
    },
    # --- SOTUVCHI TASDIQ/RAD (sotuvchiga) ---
    'approve_seller_notify': {
        'uz': ("🎉 <b>Tabriklaymiz!</b>\n\n"
               "Sizning sotuvchi so'rovingiz <b>tasdiqlandi!</b>\n"
               "Endi mahsulot qo'shib, savdo qilishingiz mumkin.\n\n"
               "Boshlash uchun /start bosing."),
        'ru': ("🎉 <b>Поздравляем!</b>\n\n"
               "Ваша заявка продавца <b>одобрена!</b>\n"
               "Теперь вы можете добавлять товары и торговать.\n\n"
               "Нажмите /start, чтобы начать."),
    },
    'reject_seller_notify': {
        'uz': ("❌ <b>Sotuvchi so'rovingiz rad etildi.</b>\n\n"
               "Sabab: admin tomonidan tasdiqlanmadi.\n"
               "Agar savollaringiz bo'lsa — admin bilan bog'laning.\n\n"
               "Xaridor sifatida davom etishingiz mumkin."),
        'ru': ("❌ <b>Ваша заявка продавца отклонена.</b>\n\n"
               "Причина: не одобрена администратором.\n"
               "Если есть вопросы — свяжитесь с администратором.\n\n"
               "Вы можете продолжить как покупатель."),
    },

    'job_autocancel_seller': {
        'uz': ("⏰ <b>Buyurtma avtomatik bekor qilindi</b>\n\n"
               "Buyurtma: {oid}\n"
               "Sabab: 10 daqiqa ichida tasdiqlanmadi.\n\n"
               "<i>Buyurtmalarni tezroq tasdiqlang — xaridorlar kutmaydi.</i>"),
        'ru': ("⏰ <b>Заказ автоматически отменён</b>\n\n"
               "Заказ: {oid}\n"
               "Причина: не подтверждён за 10 минут.\n\n"
               "<i>Подтверждайте заказы быстрее — покупатели не ждут.</i>"),
    },

    # ============================================================
    # ADMIN PANEL
    # ============================================================
    'seller_approved_admin': {'uz': "✅ {name} sotuvchi sifatida tasdiqlandi!", 'ru': "✅ {name} подтверждён как продавец!"},
    'seller_rejected_admin': {'uz': "❌ {name} sotuvchi so'rovi rad etildi.", 'ru': "❌ Заявка продавца {name} отклонена."},
    'btn_requests_back': {'uz': "⬅️ So'rovlar", 'ru': "⬅️ Заявки"},
    'no_pending_requests': {'uz': "✅ Hozircha kutilayotgan so'rovlar yo'q.", 'ru': "✅ Пока нет ожидающих заявок."},
    'pending_requests_title': {'uz': "🆕 Kutilayotgan sotuvchi so'rovlari ({n} ta):", 'ru': "🆕 Ожидающие заявки продавцов ({n}):"},
    'request_not_found': {'uz': "So'rov topilmadi.", 'ru': "Заявка не найдена."},
    'seller_request_detail': {
        'uz': ("🏪 <b>Sotuvchi so'rovi</b>\n\n"
               "👤 Ism: {name}\n"
               "📞 Telefon: {phone}\n"
               "🏪 Do'kon: {shop}\n"
               "📍 Manzil: {address}\n"
               "🎯 Mo'ljal: {landmark}\n"
               "📅 Ish kunlari: {wd}\n"
               "🕐 Ish vaqti: {wh}\n"
               "📱 Telegram: @{tg}\n"
               "📅 So'rov sanasi: {date}"),
        'ru': ("🏪 <b>Заявка продавца</b>\n\n"
               "👤 Имя: {name}\n"
               "📞 Телефон: {phone}\n"
               "🏪 Магазин: {shop}\n"
               "📍 Адрес: {address}\n"
               "🎯 Ориентир: {landmark}\n"
               "📅 Рабочие дни: {wd}\n"
               "🕐 Рабочее время: {wh}\n"
               "📱 Telegram: @{tg}\n"
               "📅 Дата заявки: {date}"),
    },

    # --- ADMIN: FOYDALANUVCHILAR ---
    'admin_no_users': {'uz': "Foydalanuvchilar yo'q.", 'ru': "Пользователей нет."},
    'btn_search_user': {'uz': "🔍 Foydalanuvchi qidirish", 'ru': "🔍 Поиск пользователя"},
    'admin_users_title': {'uz': "👥 Foydalanuvchilar — jami {total} ta. Sahifa {page}/{pages}.", 'ru': "👥 Пользователи — всего {total}. Страница {page}/{pages}."},
    'admin_user_search_ask': {'uz': "🔍 Foydalanuvchi ismini, telefon raqamini yoki do'kon nomini kiriting:", 'ru': "🔍 Введите имя, телефон или название магазина пользователя:"},
    'admin_search_min2': {'uz': "❌ Kamida 2 belgi kiriting.", 'ru': "❌ Введите минимум 2 символа."},
    'admin_search_none': {'uz': "❌ '{q}' bo'yicha hech kim topilmadi.", 'ru': "❌ По '{q}' никто не найден."},
    'admin_search_results': {'uz': "🔍 '{q}' bo'yicha {n} ta natija:", 'ru': "🔍 По '{q}' найдено {n}:"},
    'btn_retry_search_user': {'uz': "🔍 Qayta qidirish", 'ru': "🔍 Искать снова"},

    # --- ADMIN PANEL ASOSIY ---
    'no_access_alert': {'uz': "⛔ Ruxsat yo'q!", 'ru': "⛔ Нет доступа!"},
    'admin_only_action': {'uz': "⛔ Bu amal faqat admin uchun.", 'ru': "⛔ Это действие только для администратора."},
    'admin_panel_body': {
        'uz': ("🔧 <b>Admin paneli</b>\n\n"
               "📊 <b>Statistika:</b>\n"
               "👥 Foydalanuvchilar: {users}\n"
               "📦 Mahsulotlar: {products}\n"
               "🛒 Buyurtmalar: {orders}\n\n"
               "Boshqaruv funksiyalari:"),
        'ru': ("🔧 <b>Панель администратора</b>\n\n"
               "📊 <b>Статистика:</b>\n"
               "👥 Пользователи: {users}\n"
               "📦 Товары: {products}\n"
               "🛒 Заказы: {orders}\n\n"
               "Функции управления:"),
    },
    'btn_seller_requests_n': {'uz': "🆕 Sotuvchi so'rovlari ({n})", 'ru': "🆕 Заявки продавцов ({n})"},
    'btn_admin_users': {'uz': "👥 Foydalanuvchilar", 'ru': "👥 Пользователи"},
    'btn_admin_products': {'uz': "📦 Mahsulotlar", 'ru': "📦 Товары"},
    'btn_admin_orders': {'uz': "🛒 Buyurtmalar", 'ru': "🛒 Заказы"},
    'btn_admin_channels': {'uz': "📢 Kanallar", 'ru': "📢 Каналы"},
    'btn_admin_stats': {'uz': "📊 Statistika", 'ru': "📊 Статистика"},
    'admin_channels_title': {
        'uz': "📢 <b>Ulangan kanallar</b>\nSotuvchilar: {sellers} • Kanallar: {channels}\n",
        'ru': "📢 <b>Подключённые каналы</b>\nПродавцов: {sellers} • Каналов: {channels}\n",
    },
    'admin_channels_page': {
        'uz': "📄 Sahifa {page}/{pages}",
        'ru': "📄 Страница {page}/{pages}",
    },
    'admin_channels_none': {
        'uz': "📢 Hali hech bir sotuvchi kanal ulamagan.",
        'ru': "📢 Пока ни один продавец не подключил канал.",
    },
    'btn_admin_broadcast': {'uz': "📢 Xabar yuborish", 'ru': "📢 Рассылка"},
    'btn_admin_settings': {'uz': "⚙️ Sozlamalar", 'ru': "⚙️ Настройки"},

    # --- ADMIN: FOYDALANUVCHI TAFSILOTI ---
    'btn_unblock': {'uz': "🔓 Blokdan olish", 'ru': "🔓 Разблокировать"},
    'btn_block': {'uz': "🔒 Bloklash", 'ru': "🔒 Заблокировать"},
    'btn_unverify_seller': {'uz': "🔴 Sotuvchi tasdiqlashni bekor qilish", 'ru': "🔴 Отозвать подтверждение продавца"},
    'btn_verify_seller': {'uz': "✅ Sotuvchini tasdiqlash", 'ru': "✅ Подтвердить продавца"},
    'adu_yes': {'uz': "✅ Ha", 'ru': "✅ Да"},
    'adu_no': {'uz': "❌ Yo'q", 'ru': "❌ Нет"},
    'adu_status_active': {'uz': "🟢 Faol", 'ru': "🟢 Активен"},
    'adu_status_blocked': {'uz': "🔴 Bloklangan", 'ru': "🔴 Заблокирован"},
    'adu_seller_approved': {'uz': "✅ Sotuvchi tasdiqlangan", 'ru': "✅ Продавец подтверждён"},
    'adu_seller_not_approved': {'uz': "❌ Sotuvchi tasdiqlanmagan", 'ru': "❌ Продавец не подтверждён"},
    'adu_buyer_dash': {'uz': "— (xaridor)", 'ru': "— (покупатель)"},
    'word_none_yes': {'uz': "Yo'q", 'ru': "Нет"},
    'adu_main_block': {
        'uz': ("👤 <b>FOYDALANUVCHI — TO'LIQ MA'LUMOT</b>\n\n"
               "<b>— Asosiy —</b>\n"
               "🆔 ID: <code>{id}</code>\n"
               "👤 Ism: {name}\n"
               "📱 Telegram ID: <code>{tgid}</code>\n"
               "🔗 Username: {username}\n"
               "📞 Tel: {phone}\n"
               "🎭 Rol: {role}\n"
               "🌐 Til: {lang}\n"
               "📌 Hudud (region_id): {region}\n"
               "Holat: {status}\n"
               "Sotuvchi tasdiq: {approved}\n"
               "🔐 Tasdiqlangan (verified): {verified}\n"
               "📅 Ro'yxatdan: {created}\n"
               "🔄 Yangilangan: {updated}"),
        'ru': ("👤 <b>ПОЛЬЗОВАТЕЛЬ — ПОЛНЫЕ ДАННЫЕ</b>\n\n"
               "<b>— Основное —</b>\n"
               "🆔 ID: <code>{id}</code>\n"
               "👤 Имя: {name}\n"
               "📱 Telegram ID: <code>{tgid}</code>\n"
               "🔗 Username: {username}\n"
               "📞 Тел: {phone}\n"
               "🎭 Роль: {role}\n"
               "🌐 Язык: {lang}\n"
               "📌 Регион (region_id): {region}\n"
               "Статус: {status}\n"
               "Подтверждение продавца: {approved}\n"
               "🔐 Подтверждён (verified): {verified}\n"
               "📅 Регистрация: {created}\n"
               "🔄 Обновлён: {updated}"),
    },
    'adu_shop_block': {
        'uz': ("\n\n<b>— Do'kon —</b>\n"
               "🏪 Nomi: {name}\n"
               "📍 Manzil: {addr}\n"
               "🎯 Mo'ljal: {lm}\n"
               "🕐 Ish vaqti: {wh}\n"
               "📆 Ish kunlari: {wd}"),
        'ru': ("\n\n<b>— Магазин —</b>\n"
               "🏪 Название: {name}\n"
               "📍 Адрес: {addr}\n"
               "🎯 Ориентир: {lm}\n"
               "🕐 Рабочее время: {wh}\n"
               "📆 Рабочие дни: {wd}"),
    },
    'adu_card_block': {
        'uz': ("\n\n<b>— To'lov kartasi —</b>\n"
               "💳 Karta: {ctype} <code>{num}</code>\n"
               "👤 Egasi: {owner}"),
        'ru': ("\n\n<b>— Карта оплаты —</b>\n"
               "💳 Карта: {ctype} <code>{num}</code>\n"
               "👤 Владелец: {owner}"),
    },
    'adu_referral_block': {
        'uz': ("\n\n<b>— Referal —</b>\n"
               "🎟 Kod: <code>{code}</code>\n"
               "👥 Taklif qilgan (referred_by): {by}\n"
               "📊 Takliflar soni: {count}"),
        'ru': ("\n\n<b>— Реферал —</b>\n"
               "🎟 Код: <code>{code}</code>\n"
               "👥 Пригласил (referred_by): {by}\n"
               "📊 Кол-во приглашений: {count}"),
    },
    'adu_activity_block': {
        'uz': "\n\n<b>— Faollik —</b>\n🛒 Xaridor buyurtmalari: {n}",
        'ru': "\n\n<b>— Активность —</b>\n🛒 Заказы покупателя: {n}",
    },
    'adu_seller_activity': {
        'uz': ("\n🏪 Sotuvchi buyurtmalari: {total} (🚚 {delivered} · ⏳ {pending} · ❌ {cancelled})\n"
               "📦 Mahsulotlar: {products}\n"
               "💰 Tushum (yetkazilgan): {revenue}\n"
               "⭐ O'rtacha reyting: {rating}/5.0"),
        'ru': ("\n🏪 Заказы продавца: {total} (🚚 {delivered} · ⏳ {pending} · ❌ {cancelled})\n"
               "📦 Товары: {products}\n"
               "💰 Выручка (доставлено): {revenue}\n"
               "⭐ Средний рейтинг: {rating}/5.0"),
    },
    'seller_frozen_notify': {
        'uz': ("🔴 <b>Sizning sotuvchi akkauntingiz vaqtincha to'xtatildi.</b>\n\n"
               "Mahsulotlaringiz xaridorlarga ko'rinmaydi va yangi buyurtmalar qabul qilinmaydi.\n"
               "Sababini bilish uchun admin bilan bog'laning.\n\n"
               "Xaridor sifatida davom etishingiz mumkin."),
        'ru': ("🔴 <b>Ваш аккаунт продавца временно приостановлен.</b>\n\n"
               "Ваши товары не видны покупателям, новые заказы не принимаются.\n"
               "Свяжитесь с администратором, чтобы узнать причину.\n\n"
               "Вы можете продолжить как покупатель."),
    },
    'seller_reactivated_notify': {
        'uz': ("🟢 <b>Sizning sotuvchi akkauntingiz qayta tasdiqlandi!</b>\n\n"
               "Mahsulotlaringiz yana xaridorlarga ko'rinadi.\n"
               "Yangi mahsulot qo'shib, savdo qilishingiz mumkin.\n\n"
               "Boshlash uchun /start bosing."),
        'ru': ("🟢 <b>Ваш аккаунт продавца снова подтверждён!</b>\n\n"
               "Ваши товары снова видны покупателям.\n"
               "Можете добавлять товары и торговать.\n\n"
               "Нажмите /start, чтобы начать."),
    },

    # --- ADMIN: MAHSULOTLAR/BUYURTMALAR RO'YXATI ---
    'admin_no_products': {'uz': "Mahsulotlar yo'q.", 'ru': "Товаров нет."},
    'admin_products_title': {'uz': "📦 Mahsulotlar (Jami: {n}):", 'ru': "📦 Товары (всего: {n}):"},
    'admin_no_orders': {'uz': "Buyurtmalar yo'q.", 'ru': "Заказов нет."},
    'admin_orders_title': {'uz': "🛒 Buyurtmalar (Jami: {n}):", 'ru': "🛒 Заказы (всего: {n}):"},
    'admin_order_body': {
        'uz': ("🛒 <b>Buyurtma {oid}</b>\n\n"
               "📦 Mahsulot: {pname}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Jami: <b>{total}</b>\n"
               "Holat: {status}\n\n"
               "👤 Xaridor: {buyer}\n"
               "📞 {buyer_phone}\n\n"
               "🏪 Sotuvchi: {seller}\n"
               "📞 {seller_phone}\n\n"
               "🚚 {dlv}\n"
               "💳 {pay}\n"
               "📅 {date}"),
        'ru': ("🛒 <b>Заказ {oid}</b>\n\n"
               "📦 Товар: {pname}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Итого: <b>{total}</b>\n"
               "Статус: {status}\n\n"
               "👤 Покупатель: {buyer}\n"
               "📞 {buyer_phone}\n\n"
               "🏪 Продавец: {seller}\n"
               "📞 {seller_phone}\n\n"
               "🚚 {dlv}\n"
               "💳 {pay}\n"
               "📅 {date}"),
    },
    'admin_order_addr': {'uz': "\n📍 Manzil: {addr}", 'ru': "\n📍 Адрес: {addr}"},
    'btn_force_cancel': {'uz': "🗑 Majburiy bekor qilish", 'ru': "🗑 Принудительная отмена"},
    'admin_cancel_notify': {'uz': "⚠️ Admin tomonidan buyurtma bekor qilindi: {oid}", 'ru': "⚠️ Заказ отменён администратором: {oid}"},

    # --- ADMIN: STATISTIKA ---
    'admin_stats_body': {
        'uz': ("📊 <b>Umumiy statistika</b>\n\n"
               "👥 <b>Foydalanuvchilar:</b> {total_users} ta\n"
               "  🛒 Xaridorlar: {buyers}\n"
               "  🏪 Sotuvchilar: {sellers}\n\n"
               "📦 <b>Mahsulotlar:</b> {products} ta\n\n"
               "🛒 <b>Buyurtmalar:</b> {total_orders} ta\n"
               "  ⏳ Kutilmoqda: {pending}\n"
               "  ✅ Tasdiqlangan: {confirmed}\n"
               "  🚚 Yetkazilgan: {delivered}\n"
               "  ❌ Bekor: {cancelled}\n\n"
               "💰 <b>Aylanma (yetkazilgan):</b>\n"
               "  📅 Bugun: {today_rev} ({today_cnt} ta)\n"
               "  📅 7 kun: {week_rev} ({week_cnt} ta)\n"
               "  📅 30 kun: {month_rev} ({month_cnt} ta)\n"
               "  📅 Jami: {total_rev}\n\n"
               "🏆 Top sotuvchi: {top}"),
        'ru': ("📊 <b>Общая статистика</b>\n\n"
               "👥 <b>Пользователи:</b> {total_users}\n"
               "  🛒 Покупатели: {buyers}\n"
               "  🏪 Продавцы: {sellers}\n\n"
               "📦 <b>Товары:</b> {products}\n\n"
               "🛒 <b>Заказы:</b> {total_orders}\n"
               "  ⏳ В ожидании: {pending}\n"
               "  ✅ Подтверждённые: {confirmed}\n"
               "  🚚 Доставленные: {delivered}\n"
               "  ❌ Отменённые: {cancelled}\n\n"
               "💰 <b>Оборот (доставлено):</b>\n"
               "  📅 Сегодня: {today_rev} ({today_cnt})\n"
               "  📅 7 дней: {week_rev} ({week_cnt})\n"
               "  📅 30 дней: {month_rev} ({month_cnt})\n"
               "  📅 Всего: {total_rev}\n\n"
               "🏆 Топ продавец: {top}"),
    },
    'top_seller_fmt': {'uz': "{name} ({n} ta)", 'ru': "{name} ({n})"},
    'btn_conversion_funnel': {'uz': "📈 Conversion funnel", 'ru': "📈 Воронка конверсии"},
    'btn_financial_report': {'uz': "💰 Batafsil moliyaviy hisobot", 'ru': "💰 Подробный фин. отчёт"},
    'btn_general_stats': {'uz': "📊 Umumiy statistika", 'ru': "📊 Общая статистика"},

    # --- ADMIN: ANALYTICS ---
    'analytics_funnel_bar': {
        'uz': ("📊 Buyurtma → Tasdiqlash → Yetkazish\n"
               "{b1} {total} ta (100%)\n"
               "{b2} {confirmed} ta ({confirm_rate}%)\n"
               "{b3} {delivered} ta ({deliver_rate}%)\n"
               "{b4} ❌ {cancelled} ta ({cancel_rate}%)"),
        'ru': ("📊 Заказ → Подтверждение → Доставка\n"
               "{b1} {total} (100%)\n"
               "{b2} {confirmed} ({confirm_rate}%)\n"
               "{b3} {delivered} ({deliver_rate}%)\n"
               "{b4} ❌ {cancelled} ({cancel_rate}%)"),
    },
    'analytics_body': {
        'uz': ("📈 <b>Analytics — Conversion Funnel</b>\n\n"
               "<pre>{funnel}</pre>\n\n"
               "<b>Haftalik (7 kun):</b>\n"
               "  Buyurtmalar: {week_orders}\n"
               "  Tasdiqlangan: {week_confirmed} ({week_confirm_rate}%)\n"
               "  Yetkazilgan: {week_delivered} ({week_deliver_rate}%)\n"
               "  Bekor: {week_cancelled}\n\n"
               "<b>Oylik (30 kun):</b>\n"
               "  Buyurtmalar: {month_orders}\n"
               "  Tasdiqlangan: {month_confirmed} ({month_confirm_rate}%)\n"
               "  Yetkazilgan: {month_delivered} ({month_deliver_rate}%)\n"
               "  Bekor: {month_cancelled}\n\n"
               "💰 <b>O'rtacha buyurtma:</b> {avg_order}\n\n"
               "👥 <b>Yangi foydalanuvchilar:</b>\n"
               "  Hafta: +{new_week} ta\n"
               "  Oy: +{new_month} ta\n\n"
               "⏰ <b>Eng faol soatlar:</b> {peak_hours}\n"
               "📅 <b>Eng faol kunlar:</b> {peak_days}\n\n"
               "🏷 <b>Top kategoriyalar:</b>{top_cats}\n\n"
               "📦 <b>Top mahsulotlar:</b>{top_prods}"),
        'ru': ("📈 <b>Аналитика — Воронка конверсии</b>\n\n"
               "<pre>{funnel}</pre>\n\n"
               "<b>За неделю (7 дней):</b>\n"
               "  Заказы: {week_orders}\n"
               "  Подтверждённые: {week_confirmed} ({week_confirm_rate}%)\n"
               "  Доставленные: {week_delivered} ({week_deliver_rate}%)\n"
               "  Отменённые: {week_cancelled}\n\n"
               "<b>За месяц (30 дней):</b>\n"
               "  Заказы: {month_orders}\n"
               "  Подтверждённые: {month_confirmed} ({month_confirm_rate}%)\n"
               "  Доставленные: {month_delivered} ({month_deliver_rate}%)\n"
               "  Отменённые: {month_cancelled}\n\n"
               "💰 <b>Средний заказ:</b> {avg_order}\n\n"
               "👥 <b>Новые пользователи:</b>\n"
               "  Неделя: +{new_week}\n"
               "  Месяц: +{new_month}\n\n"
               "⏰ <b>Самые активные часы:</b> {peak_hours}\n"
               "📅 <b>Самые активные дни:</b> {peak_days}\n\n"
               "🏷 <b>Топ категории:</b>{top_cats}\n\n"
               "📦 <b>Топ товары:</b>{top_prods}"),
    },
    'analytics_peak_hour': {'uz': "{h}:00 ({cnt} ta)", 'ru': "{h}:00 ({cnt})"},
    'analytics_peak_day': {'uz': "{d} ({cnt})", 'ru': "{d} ({cnt})"},
    'analytics_top_cat': {'uz': "\n  {emoji} {name}: {cnt} ta", 'ru': "\n  {emoji} {name}: {cnt}"},
    'analytics_top_prod': {'uz': "\n  {i}. {name}: {cnt} ta ({rev})", 'ru': "\n  {i}. {name}: {cnt} ({rev})"},

    # --- ADMIN: MOLIYAVIY HISOBOT ---
    'revenue_no_delivered': {'uz': "💰 Hali yetkazilgan buyurtmalar yo'q.", 'ru': "💰 Пока нет доставленных заказов."},
    'revenue_body': {
        'uz': ("💰 <b>Moliyaviy hisobot</b>\n\n"
               "📅 Oxirgi 30 kun: <b>{month_total}</b> ({month_count} ta)\n"
               "📅 Jami: <b>{total}</b> ({delivered_count} ta)\n\n"
               "🏆 <b>Top sotuvchilar (jami aylanma):</b>{sellers}\n\n"
               "💳 <b>To'lov usullari:</b>\n{pay}\n\n"
               "🚚 <b>Yetkazish:</b>\n{dlv}"),
        'ru': ("💰 <b>Финансовый отчёт</b>\n\n"
               "📅 Последние 30 дней: <b>{month_total}</b> ({month_count})\n"
               "📅 Всего: <b>{total}</b> ({delivered_count})\n\n"
               "🏆 <b>Топ продавцы (общий оборот):</b>{sellers}\n\n"
               "💳 <b>Способы оплаты:</b>\n{pay}\n\n"
               "🚚 <b>Доставка:</b>\n{dlv}"),
    },
    'revenue_seller_line': {'uz': "\n{i}. {name}: {revenue} ({count} ta)", 'ru': "\n{i}. {name}: {revenue} ({count})"},
    'revenue_pay_line': {'uz': "  {label}: {n} ta", 'ru': "  {label}: {n}"},
    'btn_excel_report': {'uz': "📊 Excel hisobot", 'ru': "📊 Excel отчёт"},
    'unknown_seller': {'uz': "Noma'lum", 'ru': "Неизвестно"},

    # --- ADMIN: BROADCAST / SOZLAMALAR ---
    'broadcast_ask': {'uz': "📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni kiriting:", 'ru': "📢 Введите сообщение для рассылки всем пользователям:"},
    'admin_settings_body': {
        'uz': ("⚙️ <b>Admin Sozlamalar</b>\n\n"
               "Bot versiyasi: 2.0.0\n"
               "Admin ID: <code>{admin_id}</code>\n\n"
               "📊 Statistika:\n"
               "👥 Foydalanuvchilar: {users}\n"
               "📦 Mahsulotlar: {products}\n"
               "🛒 Buyurtmalar: {orders}"),
        'ru': ("⚙️ <b>Настройки администратора</b>\n\n"
               "Версия бота: 2.0.0\n"
               "Admin ID: <code>{admin_id}</code>\n\n"
               "📊 Статистика:\n"
               "👥 Пользователи: {users}\n"
               "📦 Товары: {products}\n"
               "🛒 Заказы: {orders}"),
    },
    'btn_db_backup': {'uz': "💾 DB Backup", 'ru': "💾 Бэкап БД"},
    'btn_excel_users': {'uz': "📊 Excel — Foydalanuvchilar", 'ru': "📊 Excel — Пользователи"},
    'btn_excel_products': {'uz': "📊 Excel — Mahsulotlar", 'ru': "📊 Excel — Товары"},
    'btn_excel_orders': {'uz': "📊 Excel — Buyurtmalar", 'ru': "📊 Excel — Заказы"},
    'btn_clean_cancelled': {'uz': "🗑 Bekor qilingan buyurtmalar tozalash", 'ru': "🗑 Очистить отменённые заказы"},
    'clean_done': {'uz': "✅ {n} ta eski bekor buyurtma o'chirildi.", 'ru': "✅ Удалено {n} старых отменённых заказов."},
    'backup_preparing': {'uz': "⏳ Backup tayyorlanmoqda...", 'ru': "⏳ Готовится бэкап..."},
    'backup_failed': {'uz': "❌ Backup xatosi. Log'ni tekshiring.", 'ru': "❌ Ошибка бэкапа. Проверьте лог."},
    'backup_caption': {'uz': "💾 TezBozor DB Backup\n{ts}", 'ru': "💾 Бэкап БД TezBozor\n{ts}"},
    'backup_send_failed': {'uz': "❌ Fayl yuborilmadi: {e}", 'ru': "❌ Файл не отправлен: {e}"},
    'unknown_export': {'uz': "❌ Noma'lum eksport turi.", 'ru': "❌ Неизвестный тип экспорта."},

    # --- AI TAVSIYA / HAVOLA ---
    'share_link_body': {
        'uz': ("🔗 <b>Mahsulot havolasi</b>\n\n"
               "📦 {name}\n\n"
               "Havola (bosing va nusxalang):\n"
               "<code>{link}</code>\n\n"
               "Bu havolani xaridorlarga yuboring — ular to'g'ridan-to'g'ri mahsulot sahifasiga tushadi."),
        'ru': ("🔗 <b>Ссылка на товар</b>\n\n"
               "📦 {name}\n\n"
               "Ссылка (нажмите и скопируйте):\n"
               "<code>{link}</code>\n\n"
               "Отправьте эту ссылку покупателям — они попадут прямо на страницу товара."),
    },
    'btn_share': {'uz': "📤 Ulashish", 'ru': "📤 Поделиться"},
    'recs_not_enough': {'uz': "Hali yetarli ma'lumot yo'q. Ko'proq mahsulot ko'ring!", 'ru': "Пока недостаточно данных. Посмотрите больше товаров!"},
    'recs_title': {
        'uz': "✨ <b>Sizga mos bo'lishi mumkin:</b>\n\nKo'rgan mahsulotlaringizga asoslanib tanlandi:",
        'ru': "✨ <b>Возможно, вам подойдёт:</b>\n\nПодобрано на основе просмотренных товаров:",
    },
    'ai_no_products': {'uz': "Hali mahsulotlar yo'q.", 'ru': "Пока нет товаров."},
    'ai_recs_title': {'uz': "🤖 AI tavsiyalari (Ommabop mahsulotlar):", 'ru': "🤖 AI рекомендации (Популярные товары):"},

    # --- FLOOD / RATE LIMIT ---
    'flood_ban': {'uz': "⛔ Juda ko'p so'rov. 1 daqiqa kuting.", 'ru': "⛔ Слишком много запросов. Подождите 1 минуту."},
    'flood_detected': {'uz': "⛔ Flood aniqlandi! 1 daqiqa kuting.", 'ru': "⛔ Обнаружен флуд! Подождите 1 минуту."},
    'flood_too_many': {'uz': "⛔ Juda ko'p so'rov yubordingiz. 1 daqiqa kuting.", 'ru': "⛔ Вы отправили слишком много запросов. Подождите 1 минуту."},
    'please_wait': {'uz': "⏳ Biroz kuting...", 'ru': "⏳ Немного подождите..."},

    # --- ADMIN REPLY / BROADCAST ---
    'admin_reply_sent': {'uz': "✅ Javob {uid} ga yuborildi.", 'ru': "✅ Ответ отправлен {uid}."},
    'admin_reply_usage': {
        'uz': "Format: /reply 123456789 Javob matni\n\nMisol: /reply 722266370 Muammoingiz hal qilindi!",
        'ru': "Формат: /reply 123456789 Текст ответа\n\nПример: /reply 722266370 Ваша проблема решена!",
    },
    'admin_reply_format': {'uz': "❌ Noto'g'ri format. User ID raqam bo'lishi kerak.", 'ru': "❌ Неверный формат. User ID должен быть числом."},
    'admin_msg_failed': {'uz': "❌ Xabar yuborib bo'lmadi. Keyinroq urinib ko'ring.", 'ru': "❌ Не удалось отправить сообщение. Попробуйте позже."},
    'admin_msg_prefix': {'uz': "📢 Admin xabari\n\n{text}", 'ru': "📢 Сообщение от администратора\n\n{text}"},
    'admin_reply_prefix': {'uz': "💬 <b>Admin javobi:</b>\n\n{text}", 'ru': "💬 <b>Ответ администратора:</b>\n\n{text}"},
    'broadcast_sent': {'uz': "✅ {n} ta foydalanuvchiga yuborildi.", 'ru': "✅ Отправлено {n} пользователям."},
    'broadcast_failed_n': {'uz': "\n❌ {n} ta foydalanuvchiga yuborilmadi.", 'ru': "\n❌ Не отправлено {n} пользователям."},
    'broadcast_reason': {'uz': "\n\nSabab (birinchi xato): {err}", 'ru': "\n\nПричина (первая ошибка): {err}"},
    'broadcast_failed_list_title': {
        'uz': "\n\n📋 <b>Yuborilmaganlar:</b>",
        'ru': "\n\n📋 <b>Не доставлено:</b>",
    },
    'broadcast_failed_item': {
        'uz': "\n• {name} {tg} — <code>{id}</code>",
        'ru': "\n• {name} {tg} — <code>{id}</code>",
    },
    'broadcast_reasons_common': {
        'uz': ("\n\nKo'p uchraydigan sabablar:\n"
               "• Foydalanuvchi botni bloklagan\n"
               "• Foydalanuvchi botga hali /start bermagan\n"
               "• Telegram chat topilmadi"),
        'ru': ("\n\nЧастые причины:\n"
               "• Пользователь заблокировал бота\n"
               "• Пользователь ещё не нажал /start\n"
               "• Чат Telegram не найден"),
    },
    'contact_admin_from_user': {
        'uz': ("📨 <b>Foydalanuvchidan xabar</b>\n\n"
               "{role}: {name}\n"
               "📞 {phone}\n"
               "📱 {tg}\n"
               "🆔 <code>{uid}</code>\n\n"
               "💬 {text}\n\n"
               "<i>Javob: /reply {uid} [matn]</i>"),
        'ru': ("📨 <b>Сообщение от пользователя</b>\n\n"
               "{role}: {name}\n"
               "📞 {phone}\n"
               "📱 {tg}\n"
               "🆔 <code>{uid}</code>\n\n"
               "💬 {text}\n\n"
               "<i>Ответ: /reply {uid} [текст]</i>"),
    },

    # --- GURUH BUYURTMA — SOTUVCHI TAFSILOTI ---
    'grp_seller_header': {'uz': "🛒 Buyurtma {oid} — {n} ta mahsulot\n", 'ru': "🛒 Заказ {oid} — {n} товаров\n"},
    'grp_total_plain': {'uz': "\n💰 Jami: {total}", 'ru': "\n💰 Итого: {total}"},
    'grp_status_line': {'uz': "Holat: {status}", 'ru': "Статус: {status}"},
    'grp_pay_line': {'uz': "💳 To'lov: {pay}{paynote}", 'ru': "💳 Оплата: {pay}{paynote}"},
    'grp_phone_line': {'uz': "📞 {phone}", 'ru': "📞 {phone}"},
    'grp_map_line': {'uz': "🗺️ <a href=\"{url}\">Mijoz joylashuvi</a>", 'ru': "🗺️ <a href=\"{url}\">Геолокация клиента</a>"},
    'grp_date_plain': {'uz': "📅 {date}", 'ru': "📅 {date}"},

    # --- GURUH KURYERGA UZATISH ---
    'courier_group_header': {
        'uz': "📦 <b>Yetkazib berish</b> — {oid} ({n} ta mahsulot)",
        'ru': "📦 <b>Доставка</b> — {oid} ({n} товаров)",
    },
    'courier_group_item': {'uz': "• {name} × {qty}", 'ru': "• {name} × {qty}"},
    'courier_sum': {'uz': "💰 Summa: {total}", 'ru': "💰 Сумма: {total}"},
    'courier_pay': {'uz': "💳 To'lov: {pay}", 'ru': "💳 Оплата: {pay}"},
    'courier_client': {'uz': "👤 Mijoz: {buyer}", 'ru': "👤 Клиент: {buyer}"},
    'courier_phone': {'uz': "📞 Tel: {phone}", 'ru': "📞 Тел: {phone}"},
    'courier_instructions_short': {
        'uz': "👆 Yuqoridagi lokatsiya va ma'lumotni kuryeringizga <b>forward</b> qiling.",
        'ru': "👆 Перешлите (<b>forward</b>) геолокацию и данные выше вашему курьеру.",
    },

    # --- HOLAT YORLIQLARI (status) ---
    'st_pending': {'uz': "⏳ Yangi", 'ru': "⏳ Новый"},
    'st_confirmed': {'uz': "✅ Tasdiqlangan", 'ru': "✅ Подтверждён"},
    'st_delivered': {'uz': "🚚 Yetkazildi", 'ru': "🚚 Доставлен"},
    'st_cancelled': {'uz': "❌ Bekor qilindi", 'ru': "❌ Отменён"},
    'st_approved': {'uz': "✅ Tasdiqlangan", 'ru': "✅ Подтверждён"},
    'st_rejected': {'uz': "❌ Rad etildi", 'ru': "❌ Отклонён"},

    # --- SOTUVCHI BUYURTMA TAFSILOTI ---
    'btn_delivered': {'uz': "🚚 Yetkazib berildi", 'ru': "🚚 Доставлено"},
    'btn_buyer_received': {'uz': "✅ Xaridor oldi (tasdiqlash)", 'ru': "✅ Покупатель получил (подтвердить)"},
    'btn_forward_courier': {'uz': "📨 Kuryerga uzatish", 'ru': "📨 Передать курьеру"},
    'p2p_your_card': {'uz': "\n📲 P2P kartangiz: {ctype} {masked}", 'ru': "\n📲 Ваша P2P-карта: {ctype} {masked}"},
    'p2p_no_card': {
        'uz': "\n⚠️ P2P karta ma'lumoti yo'q. Profilga kiring va karta qo'shing.",
        'ru': "\n⚠️ Нет данных P2P-карты. Зайдите в профиль и добавьте карту.",
    },
    'seller_order_addr': {'uz': "\n📍 Manzil: {addr}", 'ru': "\n📍 Адрес: {addr}"},
    'seller_order_map': {
        'uz': "\n🗺️ <a href=\"{url}\">Mijoz joylashuvi</a>",
        'ru': "\n🗺️ <a href=\"{url}\">Геолокация клиента</a>",
    },
    'seller_dist_from_shop': {'uz': "\n📏 Do'kondan masofa: ~{km} km", 'ru': "\n📏 Расстояние от магазина: ~{km} км"},
    'addr_not_shown': {'uz': "\n📍 Manzil ko'rsatilmagan", 'ru': "\n📍 Адрес не указан"},
    'seller_order_body': {
        'uz': ("🛒 Buyurtma {oid}\n\n"
               "📦 {pname}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Jami: {total}\n"
               "Holat: {status}\n"
               "🚚 {dlv}\n"
               "💳 To'lov: {pay}{paynote}\n\n"
               "👤 Xaridor: {buyer}\n"
               "📞 {phone}{delivery}\n"
               "📅 {date}"),
        'ru': ("🛒 Заказ {oid}\n\n"
               "📦 {pname}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Итого: {total}\n"
               "Статус: {status}\n"
               "🚚 {dlv}\n"
               "💳 Оплата: {pay}{paynote}\n\n"
               "👤 Покупатель: {buyer}\n"
               "📞 {phone}{delivery}\n"
               "📅 {date}"),
    },

    # --- KURYERGA UZATISH ---
    'order_num_invalid': {'uz': "⚠️ Buyurtma raqami noto'g'ri.", 'ru': "⚠️ Неверный номер заказа."},
    'not_your_order_plain': {'uz': "⛔ Bu buyurtma sizniki emas.", 'ru': "⛔ Это не ваш заказ."},
    'courier_body': {
        'uz': ("📦 <b>Yetkazib berish</b> — {oid}\n\n"
               "🛍 {pname}\n"
               "🔢 Miqdor: {qty}\n"
               "💰 Summa: {total}\n"
               "💳 To'lov: {pay}\n\n"
               "👤 Mijoz: {buyer}\n"
               "📞 Tel: {phone}"),
        'ru': ("📦 <b>Доставка</b> — {oid}\n\n"
               "🛍 {pname}\n"
               "🔢 Кол-во: {qty}\n"
               "💰 Сумма: {total}\n"
               "💳 Оплата: {pay}\n\n"
               "👤 Клиент: {buyer}\n"
               "📞 Тел: {phone}"),
    },
    'courier_addr': {'uz': "📍 Manzil: {addr}", 'ru': "📍 Адрес: {addr}"},
    'courier_map': {
        'uz': "🗺️ <a href=\"{url}\">Mijoz joylashuvi (xarita)</a>",
        'ru': "🗺️ <a href=\"{url}\">Геолокация клиента (карта)</a>",
    },
    'courier_dist': {'uz': "📏 Do'kondan masofa: ~{km} km", 'ru': "📏 Расстояние от магазина: ~{km} км"},
    'courier_route': {
        'uz': "🧭 <a href=\"{url}\">Do'kondan yo'l ko'rsatish</a>",
        'ru': "🧭 <a href=\"{url}\">Маршрут от магазина</a>",
    },
    'courier_no_addr': {
        'uz': "⚠️ Manzil ko'rsatilmagan — mijoz bilan bog'laning.",
        'ru': "⚠️ Адрес не указан — свяжитесь с клиентом.",
    },
    'courier_instructions': {
        'uz': ("👆 Yuqoridagi lokatsiya va ma'lumotni kuryeringizga <b>forward</b> qiling "
               "(xabarni bosib turib «Forward / Yuborish» tugmasini tanlang).\n\n"
               "Kuryer manzilni xaritada ochib, mijozga yetkazib beradi."),
        'ru': ("👆 Перешлите (<b>forward</b>) геолокацию и данные выше вашему курьеру "
               "(зажмите сообщение и выберите «Переслать»).\n\n"
               "Курьер откроет адрес на карте и доставит клиенту."),
    },

    # --- SOTUVCHI PROFILI ---
    'card_not_added': {
        'uz': "\n❌ Karta qo'shilmagan (P2P to'lov qabul qilish uchun kerak)",
        'ru': "\n❌ Карта не добавлена (нужна для приёма P2P-оплаты)",
    },
    'region_not_set': {
        'uz': "❌ Belgilanmagan (xaridorlar topa olmaydi!)",
        'ru': "❌ Не указан (покупатели не смогут найти!)",
    },
    'btn_edit_shop_name': {'uz': "✏️ Do'kon nomi", 'ru': "✏️ Название магазина"},
    'btn_edit_address': {'uz': "✏️ Manzil", 'ru': "✏️ Адрес"},
    'btn_edit_landmark': {'uz': "✏️ Mo'ljal", 'ru': "✏️ Ориентир"},
    'btn_select_region': {'uz': "📍 Hudud tanlash", 'ru': "📍 Выбрать регион"},
    'btn_edit_working_days': {'uz': "✏️ Ish kunlari", 'ru': "✏️ Рабочие дни"},
    'btn_edit_working_hours': {'uz': "✏️ Ish vaqti", 'ru': "✏️ Рабочее время"},
    'btn_edit_telegram': {'uz': "✏️ Telegram", 'ru': "✏️ Telegram"},
    'btn_card_info': {'uz': "💳 Karta ma'lumoti", 'ru': "💳 Данные карты"},
    # --- HUDUD TANLASH (sotuvchi) ---
    'seller_region_ask': {
        'uz': "📍 Do'koningiz joylashgan viloyatni tanlang:\n\nBu xaridorlar sizni hudud bo'yicha topishi uchun kerak.",
        'ru': "📍 Выберите регион вашего магазина:\n\nЭто нужно, чтобы покупатели находили вас по региону.",
    },
    'region_saved_toast': {'uz': "✅ Hudud saqlandi: {name}", 'ru': "✅ Регион сохранён: {name}"},

    # --- XARIDOR PROFIL TAHRIR ---
    'ask_new_name': {'uz': "Yangi ismingizni kiriting:", 'ru': "Введите ваше новое имя:"},
    'name_invalid_2_50': {'uz': "❌ Ism 2-50 belgi bo'lishi kerak. Qaytadan kiriting:", 'ru': "❌ Имя должно быть от 2 до 50 символов. Введите заново:"},
    'name_updated_excl': {'uz': "✅ Ism yangilandi!", 'ru': "✅ Имя обновлено!"},
    'ask_new_phone': {'uz': "Yangi telefon raqamingizni yuboring:", 'ru': "Отправьте ваш новый номер телефона:"},
    'press_phone_btn': {'uz': "Telefon tugmasini bosing:", 'ru': "Нажмите кнопку телефона:"},
    'phone_invalid_2': {'uz': "❌ Telefon raqami noto'g'ri. Misol: +998901234567\nQaytadan yuboring:", 'ru': "❌ Неверный номер. Пример: +998901234567\nОтправьте заново:"},
    'phone_updated': {'uz': "✅ Telefon yangilandi!", 'ru': "✅ Телефон обновлён!"},

    # --- SOTUVCHI MAYDON TAHRIR ---
    'efl_shop_name': {'uz': "Do'kon nomi", 'ru': "Название магазина"},
    'efl_shop_address': {'uz': "Manzil", 'ru': "Адрес"},
    'efl_shop_landmark': {'uz': "Mo'ljal", 'ru': "Ориентир"},
    'efl_working_days': {'uz': "Ish kunlari", 'ru': "Рабочие дни"},
    'efl_working_hours': {'uz': "Ish vaqti", 'ru': "Рабочее время"},
    'efl_telegram': {'uz': "Telegram username", 'ru': "Telegram username"},
    'edit_field_ask': {'uz': "✏️ {label}ni kiriting:", 'ru': "✏️ Введите: {label}"},
    'edit_field_ask_addr': {'uz': "✏️ {label}ni kiriting (lokatsiya yoki matn):", 'ru': "✏️ Введите {label} (геолокация или текст):"},
    'send_location_or_text': {'uz': "Lokatsiya yuboring yoki matn kiriting:", 'ru': "Отправьте геолокацию или введите текст:"},
    'info_updated': {'uz': "✅ Ma'lumotlar yangilandi!", 'ru': "✅ Данные обновлены!"},

    # --- KARTA ---
    'card_menu': {
        'uz': ("💳 <b>Karta ma'lumotlari</b>\n\n"
               "Bu ma'lumotlar faqat xaridorga to'lov uchun ko'rsatiladi.\n"
               "<i>⚠️ Bot karta ma'lumotlarini hech qachon so'ramaydi — siz o'zingiz qo'shasiz.</i>\n\n"
               "Karta turini tanlang:"),
        'ru': ("💳 <b>Данные карты</b>\n\n"
               "Эти данные показываются только покупателю для оплаты.\n"
               "<i>⚠️ Бот никогда не запрашивает данные карты — вы добавляете их сами.</i>\n\n"
               "Выберите тип карты:"),
    },
    'btn_card_remove': {'uz': "❌ Kartani o'chirish", 'ru': "❌ Удалить карту"},
    'card_removed': {'uz': "✅ Karta ma'lumotlari o'chirildi.", 'ru': "✅ Данные карты удалены."},
    'card_number_ask': {
        'uz': "💳 Karta raqamini kiriting (16 ta raqam, bo'shliqlarsiz):\n\nMisol: <code>8600123456781234</code>",
        'ru': "💳 Введите номер карты (16 цифр, без пробелов):\n\nПример: <code>8600123456781234</code>",
    },
    'card_number_invalid': {
        'uz': "❌ Karta raqami noto'g'ri. 16 ta raqam kiriting:\nMisol: <code>8600123456781234</code>",
        'ru': "❌ Неверный номер карты. Введите 16 цифр:\nПример: <code>8600123456781234</code>",
    },
    'card_owner_ask': {
        'uz': "👤 Karta egasining to'liq ismini kiriting:\nMisol: <code>SHERZOD KARIMOV</code>",
        'ru': "👤 Введите полное имя владельца карты:\nПример: <code>SHERZOD KARIMOV</code>",
    },
    'card_owner_invalid': {'uz': "❌ Ism noto'g'ri. Qaytadan kiriting:", 'ru': "❌ Имя неверно. Введите заново:"},
    'card_saved': {
        'uz': ("✅ Karta saqlandi:\n\n"
               "{ctype} {masked}\n"
               "👤 {owner}\n\n"
               "<i>Endi xaridorlar P2P to'lov tanlasa, karta raqamingiz ko'rsatiladi.</i>"),
        'ru': ("✅ Карта сохранена:\n\n"
               "{ctype} {masked}\n"
               "👤 {owner}\n\n"
               "<i>Теперь при выборе P2P-оплаты покупателям будет показан номер вашей карты.</i>"),
    },

    'seller_profile_body': {
        'uz': ("🏪 Sotuvchi profili\n\n"
               "Do'kon: {shop}\n"
               "Manzil: {address}\n"
               "Mo'ljal: {landmark}\n"
               "📍 Hudud: {region}\n"
               "Ish kunlari: {wd}\n"
               "Ish vaqti: {wh}\n"
               "Telegram: {tg}\n"
               "Telefon: {phone}\n"
               "💳 To'lov kartasi:{card}\n"
               "⭐ Reyting: {rating}/5.0\n"
               "Ro'yxatdan o'tgan: {date}"),
        'ru': ("🏪 Профиль продавца\n\n"
               "Магазин: {shop}\n"
               "Адрес: {address}\n"
               "Ориентир: {landmark}\n"
               "📍 Регион: {region}\n"
               "Рабочие дни: {wd}\n"
               "Рабочее время: {wh}\n"
               "Telegram: {tg}\n"
               "Телефон: {phone}\n"
               "💳 Карта оплаты:{card}\n"
               "⭐ Рейтинг: {rating}/5.0\n"
               "Дата регистрации: {date}"),
    },

    # --- AI YORDAMCHI (DeepSeek) ---
    'btn_ai_assistant': {
        'uz': "🤖 AI yordamchi",
        'ru': "🤖 ИИ-помощник",
    },
    'ai_welcome': {
        'uz': ("🤖 <b>AI yordamchi</b>\n\n"
               "Salom! Men TezBozor sun'iy intellekt yordamchisiman. "
               "Menga istalgan savolingizni yozing — mahsulot topish, buyurtma berish, "
               "do'kon ochish, tavsif yozish yoki narx bo'yicha maslahat beraman.\n\n"
               "💬 Savolingizni yozing yoki ⬅️ Chiqish tugmasini bosing."),
        'ru': ("🤖 <b>ИИ-помощник</b>\n\n"
               "Здравствуйте! Я ИИ-помощник TezBozor. "
               "Задайте мне любой вопрос — помогу найти товар, оформить заказ, "
               "открыть магазин, написать описание или дать совет по цене.\n\n"
               "💬 Напишите вопрос или нажмите ⬅️ Выход."),
    },
    'ai_welcome_buyer': {
        'uz': ("🤖 <b>AI yordamchi</b>\n\n"
               "Salom! Men sizga kerakli mahsulotni topib beraman. "
               "Oddiy gap bilan yozing — masalan:\n"
               "• «200 mingdan arzon qishki kurtka»\n"
               "• «sumka, qora rangli»\n"
               "• «eng arzon telefonlar»\n\n"
               "Men bazadan real mahsulotlarni topib, narxi bilan ko'rsataman. 👇"),
        'ru': ("🤖 <b>ИИ-помощник</b>\n\n"
               "Здравствуйте! Я помогу найти нужный товар. "
               "Напишите простыми словами — например:\n"
               "• «зимняя куртка дешевле 200 тысяч»\n"
               "• «сумка чёрного цвета»\n"
               "• «самые дешёвые телефоны»\n\n"
               "Я найду реальные товары из базы и покажу с ценой. 👇"),
    },
    'ai_welcome_seller': {
        'uz': ("🤖 <b>AI sotuvchi yordamchisi</b>\n\n"
               "Men shunchaki maslahatchi emasman — do'koningiz bilan ish bajaraman:\n"
               "• «qizil Nike krossovka 250 ming» — sotuvchan e'lon tayyorlab beraman.\n"
               "• «mahsulotlarimni ko'rsat» — barcha tovarlaringizni ro'yxat qilaman.\n"
               "• «krossovka narxini 300 mingga o'zgartir» — narx/nom/tavsifni tahrirlayman.\n"
               "• «bu mahsulot tugadi» / «zahirasi 5 ta» — zahirani boshqaraman.\n"
               "• «buyurtmalarim qani?» — yangi buyurtmalarni ko'rsataman.\n"
               "• «savdolarim qanday?» — statistikani tahlil qilib maslahat beraman.\n\n"
               "Yozing, boshladik! ✍️"),
        'ru': ("🤖 <b>ИИ-помощник продавца</b>\n\n"
               "Я не просто советчик — я выполняю работу с вашим магазином:\n"
               "• «красные Nike кроссовки 250 тысяч» — подготовлю продающее объявление.\n"
               "• «покажи мои товары» — выведу весь ваш каталог.\n"
               "• «измени цену кроссовок на 300 тысяч» — отредактирую цену/название/описание.\n"
               "• «этот товар закончился» / «остаток 5 шт» — управлю остатками.\n"
               "• «где мои заказы?» — покажу новые заказы.\n"
               "• «как мои продажи?» — проанализирую статистику и дам советы.\n\n"
               "Пишите, начнём! ✍️"),
    },
    'ai_welcome_admin': {
        'uz': ("🤖 <b>AI admin yordamchisi</b>\n\n"
               "Tizim holati, statistika va aylanma bo'yicha savol bering — "
               "real raqamlarni tahlil qilib beraman."),
        'ru': ("🤖 <b>ИИ-помощник админа</b>\n\n"
               "Спросите о состоянии системы, статистике и обороте — "
               "проанализирую реальные цифры."),
    },
    'ai_thinking': {
        'uz': "🤖 O'ylayapman...",
        'ru': "🤖 Думаю...",
    },
    'ai_exit': {
        'uz': "⬅️ Chiqish",
        'ru': "⬅️ Выход",
    },
    'ai_exited': {
        'uz': "✅ AI yordamchidan chiqdingiz.",
        'ru': "✅ Вы вышли из ИИ-помощника.",
    },
    'ai_disabled_alert': {
        'uz': "🤖 AI yordamchi hozircha sozlanmagan.",
        'ru': "🤖 ИИ-помощник пока не настроен.",
    },
    'ai_found_products': {
        'uz': "🔎 Mana topilgan mahsulotlar — ko'rish va buyurtma berish uchun bosing:",
        'ru': "🔎 Вот найденные товары — нажмите, чтобы посмотреть и заказать:",
    },
    'ai_draft_card': {
        'uz': ("📝 <b>Tayyor e'lon</b>\n\n"
               "🏷 <b>{name}</b>\n"
               "💰 {price}\n"
               "📂 {category}\n\n"
               "{desc}\n\n"
               "Quyidagi tugma orqali e'lonni joylang yoki bekor qiling."),
        'ru': ("📝 <b>Готовое объявление</b>\n\n"
               "🏷 <b>{name}</b>\n"
               "💰 {price}\n"
               "📂 {category}\n\n"
               "{desc}\n\n"
               "Опубликуйте объявление кнопкой ниже или отмените."),
    },
    'ai_price_missing': {
        'uz': "Narx ko'rsatilmagan — narxni yozing",
        'ru': "Цена не указана — напишите цену",
    },
    'ai_publish': {
        'uz': "✅ E'lonni joylash",
        'ru': "✅ Опубликовать",
    },
    'ai_add_photo_publish': {
        'uz': "📷 Rasm qo'shib joylash",
        'ru': "📷 Добавить фото и опубликовать",
    },
    'ai_publish_nophoto': {
        'uz': "🚀 Rasmsiz joylash",
        'ru': "🚀 Опубликовать без фото",
    },
    'ai_send_photos': {
        'uz': ("📷 Mahsulot rasm(lar)ini yuboring (4 tagacha).\n"
               "Har bir rasmni alohida yuboring. Tugatgach «✅ Joylash» tugmasini bosing."),
        'ru': ("📷 Отправьте фото товара (до 4 шт).\n"
               "Каждое фото отдельным сообщением. По готовности нажмите «✅ Опубликовать»."),
    },
    'ai_photos_added': {
        'uz': "📷 {n}/{max} rasm qo'shildi. Yana yuboring yoki «✅ Joylash» tugmasini bosing.",
        'ru': "📷 Добавлено {n}/{max} фото. Отправьте ещё или нажмите «✅ Опубликовать».",
    },
    'ai_photos_max_reached': {
        'uz': "📷 Maksimal {max} ta rasm qo'shildi. «✅ Joylash» tugmasini bosing.",
        'ru': "📷 Достигнут максимум {max} фото. Нажмите «✅ Опубликовать».",
    },
    'ai_photo_done_btn': {
        'uz': "✅ Joylash",
        'ru': "✅ Опубликовать",
    },
    'ai_send_photo_hint': {
        'uz': "📷 Iltimos, mahsulot rasmini yuboring yoki pastdagi tugmani bosing.",
        'ru': "📷 Пожалуйста, отправьте фото товара или нажмите кнопку ниже.",
    },
    'ai_discard': {
        'uz': "❌ Bekor qilish",
        'ru': "❌ Отменить",
    },
    'ai_draft_expired': {
        'uz': "⚠️ E'lon qoralamasi topilmadi yoki narx yo'q. Qaytadan urinib ko'ring.",
        'ru': "⚠️ Черновик не найден или нет цены. Попробуйте снова.",
    },
    'ai_published': {
        'uz': "🎉 E'lon joylandi! Mahsulot #{id} sotuvga qo'shildi va kanalga e'lon qilindi.",
        'ru': "🎉 Объявление опубликовано! Товар #{id} добавлен в продажу и размещён в канале.",
    },
    'admin_kb_cleared': {
        'uz': "🛠 Admin rejimi",
        'ru': "🛠 Режим админа",
    },
    # === REKLAMA KO'RINISHI (preview) ===
    'ad_preview_preparing': {
        'uz': "⏳ Reklama ko'rinishi tayyorlanmoqda...",
        'ru': "⏳ Готовим предпросмотр рекламы...",
    },
    'ad_preview_question': {
        'uz': ("👆 Reklama kanalda AYNAN shunday ko'rinadi.\n\n"
               "Ma'qul bo'lsa — joylang. Yoki matnni o'zgartiring."),
        'ru': ("👆 Так реклама будет выглядеть в канале.\n\n"
               "Если всё ок — опубликуйте. Или измените текст."),
    },
    'ad_confirm_publish': {
        'uz': "✅ Ha, kanalga joylash",
        'ru': "✅ Да, опубликовать в канал",
    },
    'ad_regen': {
        'uz': "🔄 Boshqa variant yozish",
        'ru': "🔄 Другой вариант текста",
    },
    'ad_edit_text': {
        'uz': "✏️ Matnni o'zim tahrirlayman",
        'ru': "✏️ Изменю текст сам",
    },
    'ad_skip': {
        'uz': "⏭ Hozircha joylamayman",
        'ru': "⏭ Пока не публиковать",
    },
    'ad_edit_prompt': {
        'uz': "✏️ Yangi reklama matnini yuboring (emoji ishlatishingiz mumkin):",
        'ru': "✏️ Отправьте новый рекламный текст (можно с эмодзи):",
    },
    'ad_publishing': {
        'uz': "⏳ Kanal(lar)ga joylanmoqda...",
        'ru': "⏳ Публикуем в канал(ы)...",
    },
    'ad_published': {
        'uz': "🎉 Reklama kanal(lar)ga joylandi!",
        'ru': "🎉 Реклама опубликована в канал(ах)!",
    },
    'ad_skipped': {
        'uz': ("✅ Mahsulot saqlandi. Kanalga joylanmadi —\n"
               "keyin «Mahsulotlarim»dan istalgan vaqtda joylashingiz mumkin."),
        'ru': ("✅ Товар сохранён. В канал не опубликован —\n"
               "вы можете опубликовать позже из «Мои товары»."),
    },
    'ad_preview_expired': {
        'uz': "⚠️ Reklama ko'rinishi topilmadi. Qaytadan urinib ko'ring.",
        'ru': "⚠️ Предпросмотр не найден. Попробуйте снова.",
    },
    'ai_saved_preview': {
        'uz': "✅ Mahsulot #{id} saqlandi. Endi reklama ko'rinishini tekshiring 👇",
        'ru': "✅ Товар #{id} сохранён. Теперь проверьте предпросмотр рекламы 👇",
    },
}


def t(user_or_lang, key: str, **kwargs) -> str:
    """Tarjima olish.
    user_or_lang: dict (user qatori) yoki str ('uz'/'ru').
    kwargs: format uchun o'zgaruvchilar."""
    if isinstance(user_or_lang, dict):
        lang = user_or_lang.get('language') or DEFAULT_LANG
    elif isinstance(user_or_lang, str):
        lang = user_or_lang
    else:
        lang = DEFAULT_LANG

    if lang not in LANGS:
        lang = DEFAULT_LANG

    entry = _TEXTS.get(key)
    if not entry:
        return key  # Tarjima topilmasa — kalitni qaytaramiz

    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return text


def get_user_lang(user) -> str:
    """Foydalanuvchi tilini oladi."""
    if user and isinstance(user, dict):
        lang = user.get('language') or DEFAULT_LANG
        return lang if lang in LANGS else DEFAULT_LANG
    return DEFAULT_LANG


# ============================================================
# HUDUD NOMLARI — lotin → kirill transliteratsiya (RU ko'rinishi uchun)
# Viloyat/tuman nomlari bazada o'zbekcha (lotin) saqlanadi. RU tilida
# ularni kirillga o'giramiz (bosh harflar saqlanadi).
# ============================================================
_R_LAT2CYR = {
    "o'": 'ў', "g'": 'ғ', 'yo': 'ё', 'yu': 'ю', 'ya': 'я',
    'ch': 'ч', 'sh': 'ш', 'ts': 'ц',
    'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д', 'e': 'е', 'j': 'ж',
    'z': 'з', 'i': 'и', 'y': 'й', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
    'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'f': 'ф',
    'x': 'х', 'q': 'қ', 'h': 'ҳ', "'": 'ъ', 'c': 'к', 'w': 'в',
}


def _translit_word(w: str) -> str:
    wl = w.lower()
    res = []
    i = 0
    while i < len(wl):
        if i + 1 < len(wl) and wl[i:i+2] in _R_LAT2CYR:
            res.append(_R_LAT2CYR[wl[i:i+2]])
            i += 2
            continue
        res.append(_R_LAT2CYR.get(wl[i], wl[i]))
        i += 1
    s = ''.join(res)
    return (s[:1].upper() + s[1:]) if s else s


# Hududlarning rasmiy ruscha nomlari (bazadagi o'zbekcha nom -> ruscha).
# Bu yerda bo'lmagan nom transliteratsiya bilan ko'rsatiladi (zaxira).
_REGION_RU = {
    # --- Viloyatlar / shaharlar ---
    "Toshkent shahri": "Ташкент (город)",
    "Toshkent viloyati": "Ташкентская область",
    "Samarqand viloyati": "Самаркандская область",
    "Farg'ona viloyati": "Ферганская область",
    "Andijon viloyati": "Андижанская область",
    "Namangan viloyati": "Наманганская область",
    "Buxoro viloyati": "Бухарская область",
    "Qashqadaryo viloyati": "Кашкадарьинская область",
    "Surxondaryo viloyati": "Сурхандарьинская область",
    "Sirdaryo viloyati": "Сырдарьинская область",
    "Jizzax viloyati": "Джизакская область",
    "Navoiy viloyati": "Навоийская область",
    "Xorazm viloyati": "Хорезмская область",
    "Qoraqalpog'iston": "Каракалпакстан",
    # --- Toshkent shahri tumanlari ---
    "Bektemir": "Бектемир", "Chilonzor": "Чиланзар", "Hamza": "Хамза",
    "Mirobod": "Мирабад", "Mirzo Ulug'bek": "Мирзо-Улугбек", "Olmazor": "Алмазар",
    "Sergeli": "Сергели", "Shayxontohur": "Шайхантахур", "Uchtepa": "Учтепа",
    "Yakkasaroy": "Яккасарай", "Yunusobod": "Юнусабад",
    # --- Toshkent viloyati ---
    "Angren": "Ангрен", "Bekobod": "Бекабад", "Bo'stonliq": "Бостанлык", "Bo'ka": "Бука",
    "Chirchiq": "Чирчик", "Ohangaron": "Ахангаран", "Oqqo'rg'on": "Аккурган",
    "Parkent": "Паркент", "Piskent": "Пскент", "Qibray": "Кибрай", "Toshloq": "Ташлак",
    "Urtachi": "Уртачирчик", "Yangiyo'l": "Янгиюль", "Yuqorichirchiq": "Юкоричирчик",
    "Zangiota": "Зангиата",
    # --- Samarqand viloyati ---
    "Samarqand shahri": "Самарканд (город)", "Bulung'ur": "Булунгур", "Ishtixon": "Иштыхан",
    "Jomboy": "Джамбай", "Kattaqo'rg'on": "Каттакурган", "Narpay": "Нарпай",
    "Nurobod": "Нурабад", "Oqdaryo": "Акдарья", "Pastdarg'om": "Пастдаргом",
    "Paxtachi": "Пахтачи", "Payariq": "Пайарык", "Qo'shrabot": "Кушрабат",
    "Tayloq": "Тайлак", "Urgut": "Ургут",
    # --- Farg'ona viloyati ---
    "Farg'ona shahri": "Фергана (город)", "Beshariq": "Бешарык", "Bog'dod": "Багдад",
    "Buvayda": "Бувайда", "Dang'ara": "Дангара", "Furqat": "Фуркат", "Marg'ilon": "Маргилан",
    "Oltiariq": "Алтыарык", "Quva": "Кува", "Qo'qon": "Коканд", "Rishton": "Риштан",
    "So'x": "Сох", "Uchko'prik": "Учкуприк", "Uzbekiston": "Узбекистан", "Yozyovon": "Язъяван",
    # --- Andijon viloyati ---
    "Andijon shahri": "Андижан (город)", "Asaka": "Асака", "Baliqchi": "Балыкчи",
    "Bo'z": "Буз", "Buloqboshi": "Булакбаши", "Jalaquduq": "Джалакудук", "Izboskan": "Избаскан",
    "Xo'jaobod": "Ходжаабад", "Marhamat": "Мархамат", "Oltinko'l": "Алтынкуль",
    "Paxtaobod": "Пахтаабад", "Qo'rg'ontepa": "Кургантепа", "Shahrixon": "Шахрихан",
    "Ulug'nor": "Улугнор",
    # --- Namangan viloyati ---
    "Namangan shahri": "Наманган (город)", "Chortoq": "Чартак", "Chust": "Чуст",
    "Kosonsoy": "Касансай", "Mingbuloq": "Мингбулак", "Norin": "Нарын", "Pop": "Пап",
    "To'raqo'rg'on": "Туракурган", "Tuproqqo'rg'on": "Тупраккурган", "Uychi": "Уйчи",
    "Yangiqo'rg'on": "Янгикурган",
    # --- Buxoro viloyati ---
    "Buxoro shahri": "Бухара (город)", "Alat": "Алат", "Buxoro tumani": "Бухарский район",
    "G'ijduvon": "Гиждуван", "Jondor": "Джандар", "Kogon": "Каган",
    "Qorovulbozor": "Каравулбазар", "Romitan": "Ромитан", "Shofirkon": "Шафиркан",
    "Vobkent": "Вабкент",
    # --- Qashqadaryo viloyati ---
    "Qarshi shahri": "Карши (город)", "Chiroqchi": "Чиракчи", "Dehqonobod": "Дехканабад",
    "G'uzor": "Гузар", "Kamashi": "Камаши", "Kasbi": "Касби", "Kitob": "Китаб",
    "Koson": "Касан", "Mirishkor": "Миришкор", "Muborak": "Мубарек", "Nishon": "Нишан",
    "Shahrisabz": "Шахрисабз", "Yakkabog'": "Яккабаг",
    # --- Surxondaryo viloyati ---
    "Termiz shahri": "Термез (город)", "Angor": "Ангор", "Bandixon": "Бандихан",
    "Boysun": "Байсун", "Denov": "Денау", "Jarqo'rg'on": "Джаркурган", "Muzrabot": "Музрабат",
    "Oltinsoy": "Алтынсай", "Qiziriq": "Кизирик", "Qumqo'rg'on": "Кумкурган",
    "Sariosiyo": "Сариасия", "Sherobod": "Шерабад", "Sho'rchi": "Шурчи", "Uzun": "Узун",
    # --- Sirdaryo viloyati ---
    "Guliston shahri": "Гулистан (город)", "Boyovut": "Баяут", "Guliston tumani": "Гулистанский район",
    "Mirzaobod": "Мирзаабад", "Oqoltin": "Акалтын", "Sardoba": "Сардоба",
    "Sayxunobod": "Сайхунабад", "Shirin": "Ширин", "Xovos": "Хавас",
    # --- Jizzax viloyati ---
    "Jizzax shahri": "Джизак (город)", "Arnasoy": "Арнасай", "Baxmal": "Бахмаль",
    "Do'stlik": "Дустлик", "Forish": "Фориш", "G'allaorol": "Галляарал", "Mirzacho'l": "Мирзачуль",
    "Paxtakor": "Пахтакор", "Yangiobod": "Янгиабад", "Zarbdor": "Зарбдар",
    "Zafarobod": "Зафарабад", "Zomin": "Заамин",
    # --- Navoiy viloyati ---
    "Navoiy shahri": "Навои (город)", "Karmana": "Кармана", "Konimex": "Канимех",
    "Navbahor": "Навбахор", "Nurota": "Нурата", "Qiziltepa": "Кызылтепа", "Tomdi": "Тамды",
    "Uchquduq": "Учкудук", "Xatirchi": "Хатырчи", "Zarafshon": "Зарафшан",
    # --- Xorazm viloyati ---
    "Urganch shahri": "Ургенч (город)", "Bog'ot": "Багат", "Gurlan": "Гурлен",
    "Xazorasp": "Хазарасп", "Xiva": "Хива", "Qo'shko'pir": "Кошкупыр", "Shovot": "Шават",
    "Tuproqqal'a": "Тупраккала", "Yangiariq": "Янгиарык", "Yangibozor": "Янгибазар",
    # --- Qoraqalpog'iston ---
    "Nukus shahri": "Нукус (город)", "Amudaryo": "Амударья", "Beruniy": "Беруни",
    "Chimboy": "Чимбай", "Ellikkala": "Элликкала", "Kegeyli": "Кегейли", "Mo'ynoq": "Муйнак",
    "Nukus tumani": "Нукусский район", "Qanliko'l": "Канлыкуль", "Qo'ng'irot": "Кунград",
    "Shumanay": "Шуманай", "Taxtako'pir": "Тахтакупыр", "To'rtko'l": "Турткуль",
    "Xo'jayli": "Ходжейли",
}


def region_name(name, lang: str = 'uz') -> str:
    """Hudud nomini til bo'yicha qaytaradi.
    RU da: avval rasmiy ruscha nom; topilmasa kirillga transliteratsiya (zaxira)."""
    if not name or lang != 'ru':
        return name or ''
    if name in _REGION_RU:
        return _REGION_RU[name]
    return ' '.join(_translit_word(w) for w in str(name).split())


# ============================================================
# KATEGORIYA NOMLARI — UZ -> RU (bazada o'zbekcha saqlanadi)
# ============================================================
_CATEGORY_RU = {
    # Mavjud
    "Ichimliklar": "Напитки",
    "Ehtiyot Qismlar": "Запчасти",
    "Xojalik Mollari": "Хозтовары",
    "Elektronika": "Электроника",
    "Kiyimlar": "Одежда",
    "Oziq-ovqat": "Продукты питания",
    "Taomlar": "Готовые блюда",
    # Yangi (zamonaviy sohalar)
    "Go'zallik va parfyumeriya": "Красота и парфюмерия",
    "Salomatlik va dorixona": "Здоровье и аптека",
    "Bolalar mahsulotlari": "Детские товары",
    "Sport va dam olish": "Спорт и отдых",
    "Uy va mebel": "Дом и мебель",
    "Kitob va kanstovarlar": "Книги и канцтовары",
    "Qurilish mollari": "Стройматериалы",
    "Hayvonlar uchun": "Зоотовары",
    "Gul va sovg'alar": "Цветы и подарки",
}


def category_name(name, lang: str = 'uz') -> str:
    """Kategoriya nomini til bo'yicha qaytaradi (RU bo'lmasa o'zbekcha)."""
    if not name or lang != 'ru':
        return name or ''
    return _CATEGORY_RU.get(name, name)


def all_labels(key: str):
    """Bitta kalitning barcha tillardagi matnlari ro'yxati.
    Pastki klaviatura tugmalarini ikkala tilda ham tanib olish uchun ishlatiladi."""
    entry = _TEXTS.get(key) or {}
    return [v for v in entry.values() if v]
