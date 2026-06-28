"""TezBozor — AI agent (tool-calling, bazaga ulangan).

Eski versiya shunchaki suhbatlashuvchi chatbot edi: ma'lumotlar bazasini ko'rmas,
hech qanday amal bajara olmas, faqat "bot haqida" gapirardi. Yangi versiya — bu
DeepSeek (OpenAI-mos function calling) ustiga qurilgan AGENT bo'lib, marketplace
bazasiga real ulangan va rolga qarab ish bajaradi:

  • XARIDOR  — tabiiy tilda yozadi ("200 mingdan arzon qishki kurtka"), agent
              `search_products` tool'i orqali REAL mahsulotlarni bazadan topadi.
  • SOTUVCHI — bir-ikki so'z aytadi, agent chiroyli sarlavha + tavsif yozadi
              (`compose_listing`), o'xshash mahsulotlardan narx maslahati beradi
              (`price_advice`), va savdosini tahlil qiladi (`sales_report`).
  • ADMIN    — `platform_overview` orqali tizim holatini o'qiydi.

`ask()` endi STRUKTURALANGAN natija qaytaradi:
    {"text": str, "products": [...], "draft": {...}|None}
main.py shu natijani Telegram'da kartalar/tugmalar bilan ko'rsatadi.

.env:
    DEEPSEEK_API_KEY=sk-...        (majburiy)
    DEEPSEEK_MODEL=deepseek-chat    (ixtiyoriy)
    DEEPSEEK_BASE_URL=https://api.deepseek.com  (ixtiyoriy)
"""

import os
import re
import json
import logging

import httpx

try:
    from languages import category_name as _category_name
except Exception:  # languages import bo'lmasa — xom nomni qaytaramiz
    def _category_name(name, lang='uz'):
        return name or ''

log = logging.getLogger(__name__)

# ============================================================
# SOZLAMALAR
# ============================================================
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")

MAX_HISTORY = 10        # saqlanadigan oxirgi user/assistant xabarlar soni
MAX_TOKENS = 900
TIMEOUT = 60.0
MAX_TOOL_STEPS = 5      # bitta savol uchun tool-call sikllari soni
MAX_PRODUCTS = 8        # bitta qidiruvda ko'rsatiladigan mahsulot soni


def is_enabled() -> bool:
    return bool(API_KEY)


# ============================================================
# SYSTEM PROMPT (rol + til)
# ============================================================
def build_system_prompt(lang: str, role: str, user_name: str = "") -> str:
    lang = lang if lang in ('uz', 'ru') else 'uz'
    role = role if role in ('admin', 'seller', 'buyer') else 'buyer'

    if lang == 'ru':
        base = (
            "Ты — встроенный ИИ-агент маркетплейса «TezBozor» (Узбекистан). "
            "Ты не просто болтаешь — ты ВЫПОЛНЯЕШЬ работу через инструменты (функции), "
            "которые подключены к реальной базе данных бота.\n"
            "Главные правила:\n"
            "• Никогда не выдумывай товары, цены, остатки или статистику. "
            "Всё, что касается реальных данных — бери ТОЛЬКО через инструменты.\n"
            "• Отвечай коротко, по-человечески, дружелюбно. Простой текст для Telegram, "
            "без HTML и сложного markdown, можно эмодзи и списки с •.\n"
            "• ВСЕГДА обращайся к пользователю уважительно, на формальное «вы» (НИКОГДА на «ты»). "
            "Не используй фамильярные обращения («братан», «дружище» и т.п.).\n"
            "• Отвечай на русском языке."
        )
        roles = {
            'buyer': (
                "С тобой ПОКУПАТЕЛЬ. Твоя задача — помочь найти и купить товар.\n"
                "• На ЛЮБОЙ запрос о товаре ('ищу...', 'есть ли...', 'покажи...', цена/бюджет) — "
                "ОБЯЗАТЕЛЬНО вызови search_products с фильтрами (цена, категория). Не отвечай по памяти.\n"
                "• После поиска НЕ перечисляй товары списком в тексте — система сама покажет карточки с кнопками. "
                "Напиши 1-2 короткие фразы: что нашёл и совет (например 'нажмите на товар, чтобы заказать').\n"
                "• Если ничего не найдено — честно скажи и предложи изменить запрос или категорию."
            ),
            'seller': (
                "С тобой ПРОДАВЕЦ. Ты — его рабочий ассистент: не только советуешь, но и "
                "ВЫПОЛНЯЕШЬ действия с его магазином через инструменты.\n"
                "• Новый товар: когда продавец описывает товар (даже в 2-3 словах) — сам составь "
                "продающий ЗАГОЛОВОК и ОПИСАНИЕ, при необходимости вызови price_advice, и вызови "
                "compose_listing (name, price, category, description). Система покажет кнопку «опубликовать».\n"
                "• Управление каталогом: list_my_products — посмотреть товары и их id; update_product — "
                "изменить цену/название/описание; set_stock — задать остаток (0 = убрать из продажи, "
                "unlimited — снова в продажу); delete_product — удалить (только по явной просьбе, переспроси).\n"
                "• Заказы: list_orders — показать заказы, особенно ожидающие подтверждения (pending). "
                "manage_order — подтвердить заказ (confirm), отметить доставленным (deliver) или отклонить "
                "ожидающий заказ (cancel); система покажет кнопку подтверждения, действие НЕ выполняется сразу. "
                "Сначала найди правильный order_id через list_orders.\n"
                "• Отзывы: list_reviews — рейтинг магазина и товаров, комментарии покупателей (с id и признаком, "
                "отвечено ли). Выдели низкие оценки. reply_to_review — составь вежливый публичный ответ от имени "
                "магазина (review_id и reply); система покажет кнопку подтверждения, ответ НЕ публикуется сразу. "
                "Сначала найди review_id через list_reviews.\n"
                "• Аналитика: sales_report — статистика и конкретные советы (что улучшить, какой товар не продаётся).\n"
                "ВАЖНО: перед update_product/set_stock/delete_product/manage_order сначала найди правильный id "
                "через list_my_products или list_orders. Перед удалением — переспроси. После действия кратко подтверди результат."
            ),
            'admin': (
                "С тобой АДМИНИСТРАТОР. Для статистики и состояния платформы вызывай "
                "platform_overview и кратко интерпретируй цифры, давай рекомендации."
            ),
        }
        prompt = base + "\n\n" + roles[role]
        if user_name:
            prompt += f"\n\nИмя пользователя: {user_name}."
        return prompt

    # --- UZ ---
    base = (
        "Sen — \"TezBozor\" marketplace (O'zbekiston) ichidagi AI agentsan. "
        "Sen shunchaki suhbatlashmaysan — sen ish BAJARASAN: senga botning haqiqiy "
        "ma'lumotlar bazasiga ulangan tool'lar (funksiyalar) berilgan.\n"
        "Asosiy qoidalar:\n"
        "• Mahsulot, narx, qoldiq yoki statistikani HECH QACHON o'ylab topma. "
        "Real ma'lumotni FAQAT tool'lar orqali ol.\n"
        "• Qisqa, samimiy va insondek javob ber. Telegram uchun oddiy matn, "
        "HTML yoki murakkab markdown ishlatma, emoji va • ro'yxat mumkin.\n"
        "• Foydalanuvchiga DOIM hurmat bilan, formal «siz» da murojaat qil (HECH QACHON «sen» emas). "
        "«aka», «uka», «birodar» kabi samimiy-ko'cha murojaatlarini ishlatma.\n"
        "• Javoblaring o'zbek tilida bo'lsin."
    )
    roles = {
        'buyer': (
            "Sen bilan XARIDOR. Vazifang — mahsulot topish va sotib olishga yordam berish.\n"
            "• Mahsulot haqidagi HAR QANDAY so'rovda ('... kerak', '... bormi', 'ko'rsat', narx/byudjet) — "
            "ALBATTA search_products tool'ini chaqir (narx, kategoriya filtrlari bilan). Xotiradan javob berma.\n"
            "• Qidiruvdan keyin mahsulotlarni matnda ro'yxat qilib sanab o'tirma — tizim o'zi kartalar va "
            "tugmalar bilan ko'rsatadi. Sen 1-2 qisqa jumla yoz: nima topdim va maslahat "
            "(masalan 'buyurtma berish uchun mahsulotni bosing').\n"
            "• Hech narsa topilmasa — rostini ayt va so'rovni yoki kategoriyani o'zgartirishni taklif qil."
        ),
        'seller': (
            "Sen bilan SOTUVCHI. Sen — uning ishchi yordamchisisan: nafaqat maslahat berasan, balki "
            "uning do'koni bilan tool'lar orqali AMALLARNI BAJARASAN.\n"
            "• Yangi mahsulot: sotuvchi mahsulotni tasvirlasa (hatto 2-3 so'z bo'lsa ham) — o'zing sotuvchan "
            "SARLAVHA va TAVSIF tuz, kerak bo'lsa price_advice ni chaqir, so'ng compose_listing ni chaqir "
            "(name, price, category, description). Tizim «e'lon qilish» tugmasini ko'rsatadi.\n"
            "• Katalogni boshqarish: list_my_products — mahsulotlar va ularning id sini ko'rish; update_product — "
            "narx/nom/tavsifni o'zgartirish; set_stock — zahirani belgilash (0 = sotuvdan olib qo'yish, "
            "unlimited — qayta sotuvga); delete_product — o'chirish (faqat aniq so'ralsa, qayta so'ra).\n"
            "• Buyurtmalar: list_orders — buyurtmalarni, ayniqsa tasdiq kutayotganlarini (pending) ko'rsat. "
            "manage_order — buyurtmani tasdiqlash (confirm), 'yetkazilgan' deb belgilash (deliver) yoki tasdiq "
            "kutayotgan buyurtmani rad etish (cancel); tizim tasdiq tugmasini ko'rsatadi, amal DARROV bajarilmaydi. "
            "Avval list_orders orqali to'g'ri order_id ni top.\n"
            "• Sharhlar: list_reviews — do'kon va mahsulot reytingi, mijoz izohlari (har birida id va javob "
            "berilgan-berilmagani). Past baholarni ajratib ko'rsat. reply_to_review — izohga sotuvchi nomidan "
            "ochiq, xushmuomala javob tuz (review_id va reply bilan); tizim tasdiq tugmasini ko'rsatadi, javob "
            "darrov e'lon qilinmaydi. Avval list_reviews orqali review_id ni top.\n"
            "• Tahlil: sales_report — statistika va aniq maslahat (nimani yaxshilash, qaysi mahsulot sotilmayapti).\n"
            "MUHIM: update_product/set_stock/delete_product/manage_order dan OLDIN avval list_my_products yoki "
            "list_orders orqali to'g'ri id ni top. O'chirishdan oldin qayta so'ra. Amaldan keyin natijani qisqa tasdiqla."
        ),
        'admin': (
            "Sen bilan ADMIN. Statistika va tizim holati uchun platform_overview ni chaqir, "
            "raqamlarni qisqa izohlab, tavsiyalar ber."
        ),
    }
    prompt = base + "\n\n" + roles[role]
    if user_name:
        prompt += f"\n\nFoydalanuvchi ismi: {user_name}."
    return prompt


# ============================================================
# TOOL SXEMALARI (OpenAI/DeepSeek function-calling format)
# ============================================================
def _tools_for(role: str) -> list:
    if role == 'buyer':
        return [{
            "type": "function",
            "function": {
                "name": "search_products",
                "description": "Marketplace bazasidan real mahsulotlarni qidiradi. "
                               "Xaridor mahsulot so'raganda doim shu chaqiriladi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Qidiruv so'zi (mahsulot nomi/kalit so'z). Bo'sh bo'lishi mumkin."},
                        "min_price": {"type": "number", "description": "Minimal narx (so'm)."},
                        "max_price": {"type": "number", "description": "Maksimal narx (so'm) / byudjet."},
                        "category": {"type": "string", "description": "Kategoriya nomi (masalan 'Kiyim', 'Elektronika'). Ixtiyoriy."},
                        "sort": {"type": "string", "enum": ["rating", "price_asc", "price_desc", "newest"],
                                  "description": "Saralash: reyting / arzondan / qimmatdan / yangi."},
                    },
                    "required": ["query"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "list_categories",
                "description": "Mavjud mahsulot kategoriyalari ro'yxatini qaytaradi.",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    if role == 'seller':
        return [{
            "type": "function",
            "function": {
                "name": "compose_listing",
                "description": "Sotuvchi uchun TAYYOR mahsulot e'lonini ro'yxatga qo'yadi. "
                               "name va description'ni SEN sotuvchan qilib yozasan. "
                               "Foydalanuvchiga e'lonni tasdiqlash/joylash tugmasi ko'rsatiladi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Sotuvchan, aniq sarlavha."},
                        "price": {"type": "number", "description": "Narx (so'm)."},
                        "category": {"type": "string", "description": "Mos kategoriya nomi."},
                        "description": {"type": "string", "description": "Batafsil, sotuvchan tavsif."},
                    },
                    "required": ["name", "description"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "price_advice",
                "description": "Bazadagi o'xshash mahsulotlar narxini tahlil qiladi (min/o'rtacha/max) — "
                               "raqobatbardosh narx belgilash uchun.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string", "description": "Mahsulot nomi/turi."},
                        "category": {"type": "string", "description": "Kategoriya (ixtiyoriy)."},
                    },
                    "required": ["product_name"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "sales_report",
                "description": "Shu sotuvchining savdo statistikasini va mahsulotlari samaradorligini qaytaradi "
                               "(buyurtmalar, daromad, sotilmayotgan mahsulotlar).",
                "parameters": {"type": "object", "properties": {}},
            },
        }, {
            "type": "function",
            "function": {
                "name": "list_my_products",
                "description": "Shu sotuvchining BARCHA mahsulotlarini qaytaradi: id, nom, narx, "
                               "holat (sotuvda/zahirada/o'chirilgan) va zahira soni. "
                               "Mahsulotni tahrirlash, narxini o'zgartirish yoki o'chirishdan OLDIN "
                               "kerakli mahsulot id sini bilish uchun shu chaqiriladi.",
                "parameters": {"type": "object", "properties": {}},
            },
        }, {
            "type": "function",
            "function": {
                "name": "update_product",
                "description": "Shu sotuvchining mavjud mahsulotini tahrirlaydi: narx, nom yoki tavsifni "
                               "o'zgartiradi. Avval list_my_products bilan to'g'ri product_id ni aniqla. "
                               "Faqat o'zgartiriladigan maydon(lar)ni yubor.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer", "description": "Tahrirlanadigan mahsulot id si."},
                        "name": {"type": "string", "description": "Yangi nom (ixtiyoriy)."},
                        "price": {"type": "number", "description": "Yangi narx, so'm (ixtiyoriy)."},
                        "description": {"type": "string", "description": "Yangi tavsif (ixtiyoriy)."},
                    },
                    "required": ["product_id"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "set_stock",
                "description": "Mahsulot zahirasini boshqaradi. stock_count — qancha dona qolgani "
                               "(0 = zahiraga o'tadi, sotuvdan yashiriladi). unlimited=true bo'lsa cheksiz zahira "
                               "va mahsulot sotuvga qaytadi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer", "description": "Mahsulot id si."},
                        "stock_count": {"type": "integer", "description": "Zahiradagi dona soni (0 = tugadi)."},
                        "unlimited": {"type": "boolean", "description": "true bo'lsa cheksiz zahira."},
                    },
                    "required": ["product_id"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "delete_product",
                "description": "Shu sotuvchining mahsulotini sotuvdan butunlay o'chiradi. "
                               "Qaytarib bo'lmaydi — faqat foydalanuvchi aniq so'raganda chaqir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer", "description": "O'chiriladigan mahsulot id si."},
                    },
                    "required": ["product_id"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "list_orders",
                "description": "Shu sotuvchiga tushgan buyurtmalarni qaytaradi (yangi → eski). "
                               "Ayniqsa 'pending' (tasdiq kutayotgan) buyurtmalarni ko'rsatadi. "
                               "Buyurtmalarni tasdiqlash/bekor qilish tugmalari «Buyurtmalar» bo'limida bo'ladi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["pending", "confirmed", "delivered", "cancelled", "all"],
                                     "description": "Filtr (ixtiyoriy, default 'all')."},
                    },
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "manage_order",
                "description": "Sotuvchining buyurtmasi ustida amal uchun TASDIQ TUGMASINI ko'rsatadi "
                               "(amal darrov bajarilmaydi): 'confirm' — tasdiq kutayotgan buyurtmani tasdiqlash, "
                               "'deliver' — tasdiqlangan buyurtmani 'yetkazilgan' deb belgilash, "
                               "'cancel' — tasdiq kutayotgan buyurtmani rad etish. "
                               "Avval list_orders bilan to'g'ri order_id ni aniqla. "
                               "Buyurtma holatiga mos kelmasa tool xato qaytaradi — buni foydalanuvchiga tushuntir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "integer", "description": "Buyurtma id si (list_orders dan)."},
                        "action": {"type": "string", "enum": ["confirm", "deliver", "cancel"],
                                    "description": "Bajariladigan amal."},
                    },
                    "required": ["order_id", "action"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "list_reviews",
                "description": "Shu sotuvchining mijoz baholari va sharhlarini qaytaradi (yangi → eski): "
                               "id, do'kon reytingi, mahsulot reytingi, izoh matni, xaridor ismi, o'rtacha reyting "
                               "va javob berilgan-berilmagani (replied). "
                               "Sotuvchi sharhlar, reyting yoki mijoz fikrlari haqida so'raganda chaqir. "
                               "Past baholarni alohida ajratib ko'rsat va xaridorga professional, xushmuomala "
                               "javob matnini taklif qil.",
                "parameters": {"type": "object", "properties": {}},
            },
        }, {
            "type": "function",
            "function": {
                "name": "reply_to_review",
                "description": "Mijoz sharhiga sotuvchi nomidan OCHIQ javob tayyorlaydi (izoh ostida hammaga "
                               "ko'rinadi). reply matnini SEN xushmuomala, professional va qisqa yoz: mijozga "
                               "rahmat, kamchilik aytilgan bo'lsa uzr va yechim. Avval list_reviews bilan to'g'ri "
                               "review_id ni aniqla. Javob DARROV e'lon qilinmaydi — foydalanuvchiga tasdiq "
                               "tugmasi ko'rsatiladi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "review_id": {"type": "integer", "description": "Sharh id si (list_reviews dan)."},
                        "reply": {"type": "string", "description": "Sotuvchi nomidan xushmuomala javob matni."},
                    },
                    "required": ["review_id", "reply"],
                },
            },
        }]

    if role == 'admin':
        return [{
            "type": "function",
            "function": {
                "name": "platform_overview",
                "description": "Butun platforma statistikasi: foydalanuvchilar, mahsulotlar, "
                               "buyurtmalar, aylanma (bugun/hafta/oy), top sotuvchi.",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    return []


# ============================================================
# TOOL BAJARUVCHILAR (bazaga real murojaat)
# ============================================================
def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(n) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(n)


def _resolve_category(db, name):
    """Kategoriya nomini (uz yoki ru) id ga aylantiradi. Topilmasa (None, None)."""
    if not name:
        return None, None
    try:
        cats = db.get_categories()
    except Exception:
        return None, None
    nl = str(name).strip().lower()
    for c in cats:
        cn = (c.get('name') or '').lower()
        ru = (_category_name(c.get('name'), 'ru') or '').lower()
        if not cn:
            continue
        if nl == cn or nl == ru or nl in cn or cn in nl or (ru and (nl in ru or ru in nl)):
            return c.get('id'), c.get('name')
    return None, None


def _exec_tool(db, actor, name, args):
    """Tool'ni bajaradi. Qaytaradi: (model_uchun_natija: dict, ui_payload: dict|None).

    ui_payload — Telegram'da render qilinadigan qism:
        {"type": "products", "items": [...]}  yoki
        {"type": "draft", "draft": {...}}
    """
    lang = actor.get('lang', 'uz')
    role = actor.get('role', 'buyer')

    try:
        # ---------- XARIDOR ----------
        if name == "search_products":
            cat_id, _ = _resolve_category(db, args.get("category"))
            sort = args.get("sort") or "rating"
            if sort not in ("rating", "price_asc", "price_desc", "newest"):
                sort = "rating"
            rows = db.search_products(
                query=(args.get("query") or "").strip() or None,
                category_id=cat_id,
                min_price=_num(args.get("min_price")),
                max_price=_num(args.get("max_price")),
                sort_by=sort,
                seller_id=actor.get('shop_filter'),  # do'kon ichida qidiruv bo'lsa — shu do'kon bilan cheklash
            )
            items = []
            for p in rows[:MAX_PRODUCTS]:
                rating = p.get('prod_avg_rating') or p.get('avg_rating')
                items.append({
                    "id": p.get('id'),
                    "name": p.get('name'),
                    "price": p.get('price'),
                    "shop": p.get('shop_name') or '',
                    "category": _category_name(p.get('category_name'), lang) if p.get('category_name') else '',
                    "rating": round(rating, 1) if rating else None,
                })
            model_view = {
                "found": len(rows),
                "showing": len(items),
                "products": [
                    {"name": i["name"], "price_som": _fmt(i["price"]),
                     "shop": i["shop"], "rating": i["rating"]}
                    for i in items
                ],
            }
            ui = {"type": "products", "items": items} if items else None
            return model_view, ui

        if name == "list_categories":
            cats = db.get_categories()
            names = [_category_name(c.get('name'), lang) for c in cats if c.get('name')]
            return {"categories": names}, None

        # ---------- SOTUVCHI ----------
        if name == "compose_listing":
            cat_id, cat_name = _resolve_category(db, args.get("category"))
            price = _num(args.get("price"))
            draft = {
                "name": (args.get("name") or "").strip(),
                "price": price,
                "category_id": cat_id,
                "category_name": cat_name,
                "description": (args.get("description") or "").strip(),
            }
            if not draft["name"] or not draft["description"]:
                return {"status": "error", "reason": "name va description majburiy"}, None
            ui = {"type": "draft", "draft": draft}
            return {"status": "draft_ready",
                    "note": "E'lon foydalanuvchiga ko'rsatildi. Endi qisqa izoh yozing va "
                            "narx kiritilmagan bo'lsa so'rang.",
                    "price_set": price is not None}, ui

        if name == "price_advice":
            cat_id, _ = _resolve_category(db, args.get("category"))
            rows = db.search_products(
                query=(args.get("product_name") or "").strip() or None,
                category_id=cat_id, sort_by="price_asc",
            )
            prices = [p.get('price') for p in rows if p.get('price')]
            if not prices:
                return {"matches": 0,
                        "note": "Bazada o'xshash mahsulot topilmadi — narxni bozorga qarab belgilang."}, None
            avg = sum(prices) / len(prices)
            return {
                "matches": len(prices),
                "min_price_som": _fmt(min(prices)),
                "avg_price_som": _fmt(avg),
                "max_price_som": _fmt(max(prices)),
            }, None

        if name == "list_my_products":
            seller_id = actor.get('seller_id')
            if not seller_id:
                return {"status": "error", "reason": "seller_id yo'q"}, None
            rows = db.get_products_by_seller(seller_id)
            status_uz = {'active': 'sotuvda', 'reserve': 'zahirada',
                         'deleted': "o'chirilgan", 'purged': "o'chirilgan"}
            items = []
            for p in rows:
                st = (p.get('status') or 'active')
                if st in ('deleted', 'purged'):
                    continue  # o'chirilganlarni ko'rsatmaymiz
                sc = p.get('stock_count')
                items.append({
                    "id": p.get('id'),
                    "name": p.get('name'),
                    "price_som": _fmt(p.get('price')),
                    "status": status_uz.get(st, st),
                    "stock": ("cheksiz" if sc is None else sc),
                })
            return {"count": len(items), "products": items}, None

        if name == "update_product":
            seller_id = actor.get('seller_id')
            pid = args.get("product_id")
            prod = db.get_product_by_id(pid) if pid else None
            if not prod or prod.get('seller_id') != seller_id:
                return {"status": "error", "reason": "Mahsulot topilmadi yoki sizga tegishli emas"}, None
            fields = {}
            if args.get("name"):
                fields["name"] = str(args["name"]).strip()
            if args.get("description") is not None and str(args.get("description")).strip():
                fields["description"] = str(args["description"]).strip()
            price = _num(args.get("price"))
            if price is not None:
                if price <= 0:
                    return {"status": "error", "reason": "Narx 0 dan katta bo'lishi kerak"}, None
                fields["price"] = price
            if not fields:
                return {"status": "error", "reason": "O'zgartirish uchun maydon berilmagan"}, None
            db.update_product_fields(pid, **fields)
            return {"status": "updated", "product_id": pid,
                    "changed": list(fields.keys()),
                    "name": fields.get("name", prod.get("name")),
                    "price_som": _fmt(fields.get("price", prod.get("price")))}, None

        if name == "set_stock":
            seller_id = actor.get('seller_id')
            pid = args.get("product_id")
            prod = db.get_product_by_id(pid) if pid else None
            if not prod or prod.get('seller_id') != seller_id:
                return {"status": "error", "reason": "Mahsulot topilmadi yoki sizga tegishli emas"}, None
            was_active = (prod.get('status') == 'active')

            def _reactivation_ui():
                """Zahiradan sotuvga qaytgan bo'lsa — main.py reklama preview ko'rsatadi."""
                fresh = db.get_product_by_id(pid)
                if (not was_active) and fresh and fresh.get('status') == 'active':
                    return {"type": "reactivated", "product_id": pid}
                return None

            if args.get("unlimited"):
                db.set_product_stock_count(pid, None)
                return {"status": "stock_set", "product_id": pid, "stock": "cheksiz"}, _reactivation_ui()
            sc = args.get("stock_count")
            if sc is None:
                return {"status": "error", "reason": "stock_count yoki unlimited berilishi kerak"}, None
            try:
                sc = int(sc)
            except (TypeError, ValueError):
                return {"status": "error", "reason": "stock_count butun son bo'lishi kerak"}, None
            db.set_product_stock_count(pid, max(0, sc))
            return {"status": "stock_set", "product_id": pid,
                    "stock": max(0, sc),
                    "note": ("Zahira 0 — mahsulot sotuvdan vaqtincha yashirildi" if sc <= 0 else "Sotuvda")}, _reactivation_ui()

        if name == "delete_product":
            seller_id = actor.get('seller_id')
            pid = args.get("product_id")
            prod = db.get_product_by_id(pid) if pid else None
            if not prod or prod.get('seller_id') != seller_id:
                return {"status": "error", "reason": "Mahsulot topilmadi yoki sizga tegishli emas"}, None
            db.delete_product(pid)
            return {"status": "deleted", "product_id": pid, "name": prod.get("name")}, None

        if name == "list_orders":
            seller_id = actor.get('seller_id')
            if not seller_id:
                return {"status": "error", "reason": "seller_id yo'q"}, None
            flt = (args.get("status") or "all").lower()
            rows = db.get_orders_by_seller(seller_id)
            if flt in ("pending", "confirmed", "delivered", "cancelled"):
                rows = [o for o in rows if (o.get('status') or '') == flt]
            status_uz = {'pending': 'tasdiq kutilmoqda', 'confirmed': 'tasdiqlangan',
                         'delivered': 'yetkazilgan', 'cancelled': 'bekor qilingan'}
            orders = []
            for o in rows[:15]:
                orders.append({
                    "id": o.get('id'),
                    "product": o.get('product_name'),
                    "qty": o.get('quantity') or 1,
                    "buyer": o.get('buyer_name') or '',
                    "status": status_uz.get(o.get('status'), o.get('status')),
                    "price_som": _fmt(o.get('product_price')),
                })
            pending_n = sum(1 for o in rows if (o.get('status') or '') == 'pending')
            return {"count": len(rows), "showing": len(orders),
                    "pending_count": pending_n, "orders": orders}, None

        if name == "manage_order":
            seller_id = actor.get('seller_id')
            oid = args.get("order_id")
            action = (args.get("action") or "").strip().lower()
            if action not in ("confirm", "deliver", "cancel"):
                return {"status": "error", "reason": "action 'confirm', 'deliver' yoki 'cancel' bo'lishi kerak"}, None
            order = db.get_order_by_id(oid) if oid else None
            if not order or order.get('seller_id') != seller_id:
                return {"status": "error", "reason": "Buyurtma topilmadi yoki sizga tegishli emas"}, None
            st = order.get('status') or ''
            allowed = {"confirm": st == 'pending',
                       "deliver": st == 'confirmed',
                       "cancel": st == 'pending'}
            status_uz = {'pending': 'tasdiq kutilmoqda', 'confirmed': 'tasdiqlangan',
                         'delivered': 'yetkazilgan', 'cancelled': 'bekor qilingan'}
            if not allowed[action]:
                hint = {
                    "confirm": "faqat 'tasdiq kutilmoqda' holatidagi buyurtmani tasdiqlash mumkin",
                    "deliver": "faqat 'tasdiqlangan' buyurtmani 'yetkazilgan' deb belgilash mumkin",
                    "cancel": "bu yerdan faqat 'tasdiq kutilmoqda' buyurtmani rad etish mumkin; "
                              "tasdiqlangan buyurtmani bekor qilish «Buyurtmalar» bo'limidagi kelishuv orqali bo'ladi",
                }[action]
                return {"status": "error", "current_status": status_uz.get(st, st), "reason": hint}, None
            ui = {"type": "order_action", "order_id": oid, "action": action,
                  "product": order.get('product_name') or '',
                  "qty": order.get('quantity') or 1,
                  "buyer": order.get('buyer_name') or '',
                  "price_som": _fmt(order.get('product_price') or order.get('total_price'))}
            return {"status": "confirm_shown", "order_id": oid, "action": action,
                    "note": "Foydalanuvchiga tasdiq tugmasi ko'rsatildi. Bir qisqa jumla bilan "
                            "tugmani bosib tasdiqlashini so'ra."}, ui

        if name == "list_reviews":
            seller_id = actor.get('seller_id')
            if not seller_id:
                return {"status": "error", "reason": "seller_id yo'q"}, None
            rows = db.get_seller_reviews(seller_id)
            avg = db.get_seller_avg_rating(seller_id)
            reviews = []
            for r in rows[:15]:
                reviews.append({
                    "id": r.get('id'),
                    "shop_rating": r.get('rating'),
                    "product_rating": r.get('product_rating'),
                    "product": r.get('product_name') or '',
                    "comment": (r.get('comment') or '').strip(),
                    "buyer": r.get('buyer_name') or '',
                    "replied": bool((r.get('seller_reply') or '').strip()),
                })
            low = [rv for rv in reviews if (rv.get('shop_rating') or 5) <= 3]
            return {
                "count": len(rows),
                "avg_shop_rating": round(avg, 2) if avg else None,
                "low_rating_count": len(low),
                "reviews": reviews,
            }, None

        if name == "reply_to_review":
            seller_id = actor.get('seller_id')
            rid = args.get("review_id")
            reply = (args.get("reply") or "").strip()
            if not rid or len(reply) < 2:
                return {"status": "error", "reason": "review_id va reply (javob matni) majburiy"}, None
            review = db.get_review_by_id(rid)
            if not review or review.get('seller_id') != seller_id:
                return {"status": "error",
                        "reason": "Sharh topilmadi yoki sizning do'koningizga tegishli emas"}, None
            if len(reply) > 500:
                reply = reply[:500].rstrip()
            ui = {"type": "review_reply", "review_id": rid, "reply": reply,
                  "product": review.get('product_name') or '',
                  "comment": (review.get('comment') or '').strip()}
            return {"status": "reply_drafted", "review_id": rid,
                    "note": "Javob foydalanuvchiga tasdiq tugmasi bilan ko'rsatildi. "
                            "Bir qisqa jumla bilan tugmani bosib e'lon qilishini so'ra."}, ui

        if name == "sales_report":
            seller_id = actor.get('seller_id')
            if not seller_id:
                return {"status": "error", "reason": "seller_id yo'q"}, None
            stats = db.get_seller_stats(seller_id)
            perf = []
            try:
                perf = db.get_seller_product_performance(seller_id)
            except Exception:
                perf = []
            no_sales = [p['name'] for p in perf if not p.get('sold')][:8]
            best = [f"{p['name']} ({p.get('sold', 0)} dona)"
                    for p in sorted(perf, key=lambda x: x.get('sold', 0), reverse=True)
                    if p.get('sold')][:3]
            return {
                "total_orders": stats.get('total_orders', 0),
                "delivered": stats.get('delivered', 0),
                "pending": stats.get('pending', 0),
                "cancelled": stats.get('cancelled', 0),
                "total_revenue_som": _fmt(stats.get('total_revenue', 0)),
                "week_orders": stats.get('week_orders', 0),
                "month_orders": stats.get('month_orders', 0),
                "products_count": stats.get('products_count', 0),
                "best_sellers": best,
                "products_with_no_sales": no_sales,
            }, None

        # ---------- ADMIN ----------
        if name == "platform_overview":
            s = db.get_admin_stats_summary()
            return {
                "users": s.get('total_users', 0),
                "buyers": s.get('buyers', 0),
                "sellers": s.get('sellers', 0),
                "products": s.get('products', 0),
                "orders_total": s.get('total_orders', 0),
                "orders_pending": s.get('pending', 0),
                "orders_delivered": s.get('delivered', 0),
                "revenue_today_som": _fmt(s.get('today_revenue', 0)),
                "revenue_week_som": _fmt(s.get('week_revenue', 0)),
                "revenue_month_som": _fmt(s.get('month_revenue', 0)),
                "revenue_total_som": _fmt(s.get('total_revenue', 0)),
                "top_seller": s.get('top_seller'),
                "top_seller_orders": s.get('top_seller_count', 0),
            }, None

    except Exception as e:
        log.error(f"Tool '{name}' bajarishda xato: {e}")
        return {"status": "error", "reason": str(e)[:200]}, None

    return {"status": "error", "reason": f"noma'lum tool: {name}"}, None


# ============================================================
# REKLAMA MATNI (caption) GENERATSIYASI
# ============================================================
AD_TIMEOUT = 25.0   # reklama matni uchun qisqaroq timeout (joylashni ushlab qolmasin)

_AD_SYSTEM = {
    'uz': (
        "Sen — TezBozor marketplace uchun tajribali REKLAMA kopiraytersan. "
        "Berilgan mahsulot ma'lumotidan kelib chiqib BITTA jozibali, takrorlanmas reklama matni yoz "
        "(Telegram posti uchun). Qoidalar:\n"
        "• Faqat berilgan faktlardan foydalan — narx, nom, xususiyatlarni O'YLAB TOPMA.\n"
        "• Jonli, e'tibor tortadigan uslub. Emoji va bezak chiziqlaridan (━ ✦ 🔥 ⭐ 👇) foydalan.\n"
        "• Tuzilma: diqqat tortuvchi sarlavha → 2-4 ta afzallik (emoji bilan) → narx → "
        "hudud (berilgan bo'lsa, '🌍 Hudud: <viloyat → tuman>' ko'rinishida DOIM ko'rsat) → "
        "joylashuv (bo'lsa) → kuchli harakatga chorlash (CTA).\n"
        "• Xaridorga murojaat va harakatga chorlash (CTA) DOIM hurmatli, formal «siz» da bo'lsin "
        "(masalan «Hoziroq buyurtma bering») — «sen» yoki «aka/uka» ISHLATMA.\n"
        "• HASHTAG (#) ISHLATMA — hech qanday # bilan yorliq qo'shma.\n"
        "• HTML yoki markdown (** , __) ISHLATMA — faqat oddiy matn va emoji.\n"
        "• Faqat reklama matnini qaytar, izohsiz."
    ),
    'ru': (
        "Ты — опытный РЕКЛАМНЫЙ копирайтер маркетплейса TezBozor. "
        "По данным о товаре напиши ОДИН цепляющий, уникальный рекламный текст (для поста в Telegram). Правила:\n"
        "• Используй только данные факты — не выдумывай цену, название, характеристики.\n"
        "• Живой, привлекающий стиль. Используй эмодзи и разделители (━ ✦ 🔥 ⭐ 👇).\n"
        "• Структура: цепляющий заголовок → 2-4 преимущества (с эмодзи) → цена → "
        "регион (если задан, ВСЕГДА показывай в виде '🌍 Регион: <область → район>') → "
        "локация (если есть) → сильный призыв к действию.\n"
        "• Обращение к покупателю и призыв к действию (CTA) ВСЕГДА на уважительном, формальном «вы» "
        "(например «Закажите прямо сейчас») — не используй «ты» или фамильярные обращения.\n"
        "• НЕ используй ХЕШТЕГИ (#) — не добавляй никаких меток с #.\n"
        "• НЕ используй HTML или markdown (**, __) — только обычный текст и эмодзи.\n"
        "• Верни только рекламный текст, без пояснений."
    ),
}

# Reklama uzunligi bo'yicha qo'shimcha ko'rsatma (sotuvchi tanlaydi: uzun yoki qisqa)
_AD_LENGTH = {
    'uz': {
        'long': ("• UZUN, batafsil variant yoz: jozibali sarlavha, 4-6 ta afzallik (emoji bilan), "
                 "boy va ishonarli tavsif. 900 belgigacha bo'lsin."),
        'short': ("• QISQA, lo'nda variant yoz: 1-2 ta eng kuchli afzallik, narx va qisqa CTA. "
                  "300 belgidan oshmasin."),
    },
    'ru': {
        'long': ("• Напиши ДЛИННЫЙ, подробный вариант: цепляющий заголовок, 4-6 преимуществ (с эмодзи), "
                 "насыщенное убедительное описание. До 900 символов."),
        'short': ("• Напиши КОРОТКИЙ, лаконичный вариант: 1-2 самых сильных преимущества, цена и краткий призыв. "
                  "Не более 300 символов."),
    },
}


def _strip_hashtags(text: str) -> str:
    """Reklama matnidan hashtag (#so'z) larni tozalaydi.

    AI prompt'da hashtag taqiqlangan bo'lsa-da, ba'zan baribir qo'shib yuboradi.
    Bu yerda #belgili so'zlarni va ulardan iborat bo'sh qatorlarni olib tashlaymiz.
    Mahsulot nomidagi '#' (masalan "iPhone 13 #128GB") tegmasligi uchun faqat
    bo'sh joy yoki qator boshidagi hashtag'lar o'chiriladi."""
    # Qator boshidagi yoki bo'sh joydan keyingi #so'z larni olib tashlaymiz
    text = re.sub(r"(?:(?<=\s)|^)#[^\s#]+", "", text)
    # Hashtaglar o'chgach qolgan ortiqcha bo'sh qatorlarni siqamiz
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln.strip() == "":
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


async def generate_ad_caption(*, name, price_text, category="", description="",
                              shop="", location="", region="", lang="uz", length="long") -> str:
    """Mahsulotdan kelib chiqib takrorlanmas reklama matni (caption) yaratadi.

    region — viloyat → tuman (masalan "Surxondaryo viloyati → Muzrabot"). Manzildan
    alohida beriladi va reklama matnida DOIM ko'rsatilishi kerak.
    length — 'long' (uzun, batafsil) yoki 'short' (qisqa, lo'nda). Sotuvchi tanlaydi.

    Xato yoki AI o'chiq bo'lsa — None qaytaradi (chaqiruvchi oddiy matnga qaytadi)."""
    if not is_enabled():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    length = length if length in ('long', 'short') else 'long'
    hudud_key = "hudud" if lang == 'uz' else "регион"
    facts = {
        "nom": name, "narx": price_text, "kategoriya": category,
        "tavsif": description, "do'kon": shop, hudud_key: region, "joylashuv": location,
    }
    facts = {k: v for k, v in facts.items() if v}
    user_msg = ("Mahsulot ma'lumotlari:\n" if lang == 'uz' else "Данные о товаре:\n") + \
               "\n".join(f"- {k}: {v}" for k, v in facts.items())

    system_content = _AD_SYSTEM[lang] + "\n" + _AD_LENGTH[lang][length]
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 600 if length == 'long' else 300,
        "temperature": 1.0,   # yuqori — har safar takrorlanmas variant
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Reklama matni API xatosi {resp.status_code}")
                return None
            data = resp.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                return None
            text = _strip_hashtags(text)
            if not text:
                return None
            cap = 1000 if length == 'long' else 400
            if len(text) > cap:
                text = text[:cap].rstrip()
            return text
    except Exception as e:
        log.warning(f"Reklama matni yaratishda xato: {e}")
        return None


# ============================================================
# MAHSULOTGA MOSLASHGAN SAVOLLAR (dinamik atributlar) GENERATSIYASI
# ============================================================
# Eski tizimda har bir KATEGORIYA uchun savollar qotib qolgan edi: "Ehtiyot
# Qismlar"da dvigatel ham, far ham, tormoz kolodka ham bir xil 5 savol olardi.
# Bu funksiya mahsulotning NOMI + KATEGORIYASI + TAVSIFidan kelib chiqib aynan
# shu mahsulotga mos 3-6 ta savolni generatsiya qiladi.
#   smart=False ("AI savollar")  — faqat savollar ro'yxati.
#   smart=True  ("AI aqlli")      — tavsifdan ajratilgan tayyor atributlar +
#                                    faqat YETISHMAYOTGAN savollar.
_PRODUCT_Q_SYSTEM = {
    'uz': (
        "Sen — TezBozor marketplace uchun mahsulot e'lonini to'ldirishga yordam beruvchi "
        "yordamchisiz. Senga mahsulot NOMI, KATEGORIYASI va (bo'lsa) TAVSIFI beriladi. "
        "Vazifang — AYNAN SHU mahsulotga mos, xaridor uchun muhim 3-6 ta savol tuzish "
        "(qidiruv va tanlash uchun foydali xususiyatlar). Qoidalar:\n"
        "• Savollar mahsulotga xos bo'lsin. Masalan tormoz kolodka uchun 'old/orqa', "
        "'qaysi avtomobil', 'brend'; futbolka uchun 'o'lcham', 'rang', 'mato'. "
        "Mahsulotga aloqasi yo'q savol BERMA.\n"
        "• Nomdan yoki tavsifdan allaqachon MA'LUM bo'lgan narsani qayta so'rama.\n"
        "• Eng muhim 1-2 savolni majburiy (required=true), qolganini ixtiyoriy qil.\n"
        "• Variantlari aniq cheklangan savol uchun type='select' va options ber "
        "(masalan ['Yangi','Ishlatilgan']). Aks holda type='text' yoki son uchun 'number'.\n"
        "• key — lotin harflarida, qisqa, snake_case (masalan 'car_model', 'size').\n"
        "• label va options — O'ZBEK tilida, qisqa.\n"
        "• Faqat quyidagi JSON ni qaytar, boshqa hech narsa yozma:\n"
        '{"known":[{"key":"...","label":"...","value":"..."}],'
        '"questions":[{"key":"...","label":"...","type":"text|number|select",'
        '"required":true,"options":["...","..."],"example":"..."}]}'
    ),
    'ru': (
        "Ты — помощник заполнения объявления на маркетплейсе TezBozor. Тебе дают "
        "НАЗВАНИЕ, КАТЕГОРИЮ и (если есть) ОПИСАНИЕ товара. Задача — составить 3-6 "
        "вопросов ИМЕННО для этого товара, важных для покупателя (полезные для поиска и "
        "выбора характеристики). Правила:\n"
        "• Вопросы должны подходить товару. Напр. для тормозных колодок 'перед/зад', "
        "'для какого авто', 'бренд'; для футболки 'размер', 'цвет', 'ткань'. "
        "НЕ задавай вопросы, не относящиеся к товару.\n"
        "• Не спрашивай то, что уже ясно из названия или описания.\n"
        "• 1-2 самых важных вопроса сделай обязательными (required=true), остальные — нет.\n"
        "• Для вопроса с фиксированными вариантами используй type='select' и options "
        "(напр. ['Новый','Б/у']). Иначе type='text' или 'number' для чисел.\n"
        "• key — латиницей, коротко, snake_case (напр. 'car_model', 'size').\n"
        "• label и options — на РУССКОМ, коротко.\n"
        "• Верни только следующий JSON, ничего больше:\n"
        '{"known":[{"key":"...","label":"...","value":"..."}],'
        '"questions":[{"key":"...","label":"...","type":"text|number|select",'
        '"required":true,"options":["...","..."],"example":"..."}]}'
    ),
}


def _coerce_questions(data: dict, smart: bool) -> dict:
    """AI JSON ni ichki shablon shakliga keltiradi.

    Qaytaradi: {"known": {attr_key: {"label","value"}}, "questions": [
        {"attr_key","attr_label","attr_type","is_required","hint"}]}.
    Ichki shakl _ask_next_attr kutgan DB shablonlari bilan bir xil — shu sabab
    AI savollari hech qanday qo'shimcha kodsiz mavjud atribut mashinasiga tushadi."""
    known = {}
    if smart:
        for k in (data.get("known") or []):
            if not isinstance(k, dict):
                continue
            key = str(k.get("key") or "").strip().lower()
            val = str(k.get("value") or "").strip()
            if key and val:
                known[key] = {"label": str(k.get("label") or key).strip(), "value": val}

    questions = []
    seen = set(known.keys())
    for q in (data.get("questions") or []):
        if not isinstance(q, dict):
            continue
        key = str(q.get("key") or "").strip().lower()
        label = str(q.get("label") or "").strip()
        if not key or not label or key in seen:
            continue
        seen.add(key)
        qtype = str(q.get("type") or "text").strip().lower()
        options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        if qtype == "select" and len(options) >= 2:
            attr_type, hint = "select", "/".join(options)
        elif qtype == "number":
            attr_type, hint = "number", str(q.get("example") or "").strip()
        else:
            attr_type, hint = "text", str(q.get("example") or "").strip()
        questions.append({
            "attr_key": key,
            "attr_label": label,
            "attr_type": attr_type,
            "is_required": 1 if q.get("required") else 0,
            "hint": hint,
        })
        if len(questions) >= 6:
            break
    return {"known": known, "questions": questions}


async def generate_product_questions(*, name, category="", description="",
                                     lang="uz", smart=False) -> dict:
    """Mahsulotga moslashtirilgan atribut savollarini generatsiya qiladi.

    Qaytaradi {"known": {...}, "questions": [...]} yoki xato/AI o'chiq bo'lsa None
    (chaqiruvchi klassik shablonlarga qaytadi)."""
    if not is_enabled() or not (name or "").strip():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    facts = {
        ("nom" if lang == 'uz' else "название"): name,
        ("kategoriya" if lang == 'uz' else "категория"): category,
        ("tavsif" if lang == 'uz' else "описание"): description,
    }
    facts = {k: v for k, v in facts.items() if v}
    user_msg = ("Mahsulot:\n" if lang == 'uz' else "Товар:\n") + \
               "\n".join(f"- {k}: {v}" for k, v in facts.items())
    if smart:
        user_msg += ("\n\nTavsifdan aniq bo'lganlarni 'known' ga, qolgan muhim "
                     "savollarni 'questions' ga yoz." if lang == 'uz' else
                     "\n\nЯсное из описания — в 'known', остальные важные вопросы — в 'questions'.")
    else:
        user_msg += ("\n\n'known' ni bo'sh qoldir, faqat 'questions' ni to'ldir." if lang == 'uz'
                     else "\n\nОставь 'known' пустым, заполни только 'questions'.")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _PRODUCT_Q_SYSTEM[lang]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 700,
        "temperature": 0.3,   # past — barqaror, mantiqiy savollar
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Mahsulot savollari API xatosi {resp.status_code}")
                return None
            data = resp.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()
            if not content:
                return None
            # JSON ni ajratamiz (ba'zan ```json ... ``` bilan o'raladi)
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)
            result = _coerce_questions(parsed, smart)
            if not result["questions"] and not result["known"]:
                return None
            return result
    except Exception as e:
        log.warning(f"Mahsulot savollari yaratishda xato: {e}")
        return None


# ============================================================
# AVTO-MODERATSIYA (#5) — mahsulot matnini xavfsizlik bo'yicha tekshiradi
# ============================================================
_MODERATION_SYSTEM = (
    "You are a strict but fair content-safety moderator for an Uzbekistan marketplace. "
    "Decide if a product listing (name + description) violates marketplace policy.\n"
    "PROHIBITED: firearms, ammunition, explosives, weapons designed to kill; "
    "narcotics/drugs and drug paraphernalia; prescription-only medicines; poisons; "
    "sexual/adult/pornographic content and services; human/organ/people trade; "
    "counterfeit money, fraud, stolen goods, hacking/carding services; "
    "endangered animals/parts; extremist, hateful or terrorist content; alcohol/tobacco to minors.\n"
    "ALLOWED (do NOT flag): ordinary clothes, electronics, food, cosmetics, household goods, "
    "kitchen knives, tools, toys (incl. toy guns), legal supplements/vitamins, books, furniture, etc.\n"
    "Be conservative: when in doubt, DO NOT flag (avoid false positives). "
    "Respond ONLY with compact JSON: "
    '{"flagged": true|false, "category": "<short category or empty>", '
    '"reason": "<one short sentence in {LANG}, why flagged>"}'
)


async def moderate_product(*, name, description="", lang="uz") -> dict:
    """Mahsulot matnini taqiqlangan tovar/kontent uchun tekshiradi.

    Qaytaradi {"flagged": bool, "category": str, "reason": str} yoki None
    (AI o'chiq / xato — chaqiruvchi bunda mahsulotni bloklamaydi, oddiy o'tkazadi)."""
    if not is_enabled() or not (name or "").strip():
        return None
    lng = "uzbek" if lang == "uz" else ("russian" if lang == "ru" else "uzbek")
    system = _MODERATION_SYSTEM.replace("{LANG}", lng)
    user_msg = f"name: {name}\ndescription: {description or ''}"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 200,
        "temperature": 0.0,   # qat'iy/barqaror qaror
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Moderatsiya API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            if not content:
                return None
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)
            return {
                "flagged": bool(parsed.get("flagged")),
                "category": str(parsed.get("category") or "")[:60],
                "reason": str(parsed.get("reason") or "")[:300],
            }
    except Exception as e:
        log.warning(f"Moderatsiya xato: {e}")
        return None


# ============================================================
# AI-MENEJER / RAG (#3) — mijoz savoliga do'kon profilidan grounded javob
# ============================================================
_SHOP_QA_SYSTEM = {
    'uz': ("Siz do'konning xushmuomala AI-yordamchisisiz. Mijoz savoliga FAQAT quyida "
           "berilgan do'kon va mahsulot ma'lumotlari asosida javob bering. Ma'lumotlarda "
           "javob bo'lmasa, muloyimlik bilan «Bu haqda sotuvchining o'zidan so'rang» deng. "
           "Narx, muddat yoki shartni O'ZINGIZDAN o'ylab TOPMANG. Qisqa (1-3 jumla), "
           "do'stona, o'zbek tilida javob bering."),
    'ru': ("Вы вежливый AI-помощник магазина. Отвечайте на вопрос клиента ТОЛЬКО на основе "
           "приведённых данных о магазине и товаре. Если ответа в данных нет, вежливо "
           "скажите «Уточните это у самого продавца». НЕ ВЫДУМЫВАЙТЕ цены, сроки или условия. "
           "Отвечайте кратко (1-3 предложения), дружелюбно, на русском языке."),
}


async def answer_shop_question(*, question, facts, lang="uz") -> str:
    """Mijoz savoliga do'kon/mahsulot faktlari asosida javob beradi (RAG).
    Qaytaradi javob matni yoki None (AI o'chiq/xato)."""
    if not is_enabled() or not (question or "").strip():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    label = "Do'kon va mahsulot ma'lumotlari" if lng == 'uz' else "Данные магазина и товара"
    qlabel = "Mijoz savoli" if lng == 'uz' else "Вопрос клиента"
    user_msg = f"{label}:\n{facts}\n\n{qlabel}: {question}"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SHOP_QA_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 300,
        "temperature": 0.2,   # past — faktlardan chetga chiqmasin
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Shop QA API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            return content or None
    except Exception as e:
        log.warning(f"Shop QA xato: {e}")
        return None


# ============================================================
# AI SAVDOLASHISH (#8) — sotuvchi nomidan, maxfiy "oxirgi narx" floor'i bilan
# ============================================================
_HAGGLE_SYSTEM = (
    "You are a warm, polite, professional sales assistant haggling on the seller's behalf. "
    "ALWAYS address the buyer with utmost respect using the FORMAL second person — Uzbek 'siz' "
    "(NEVER 'sen'), Russian formal 'вы' (NEVER 'ты'). NEVER use familiar/colloquial terms of "
    "address like 'aka', 'uka', 'birodar', 'opa', 'singlim'. You may warmly address the buyer as "
    "'Hurmatli xaridor' (Uzbek) / 'Уважаемый покупатель' (Russian). Keep a friendly, courteous "
    "tone with light, tasteful warmth and praise the product.\n"
    "The product's LISTED price is {LISTED}. Your SECRET minimum acceptable price is {FLOOR}. "
    "RULES YOU MUST NEVER BREAK:\n"
    "1) NEVER reveal, hint at, or mention that you have a minimum/secret price or what it is.\n"
    "2) NEVER agree to any price BELOW {FLOOR}. If the buyer offers below {FLOOR}, politely refuse "
    "and counter with a price between their offer and the listed price (but >= {FLOOR}).\n"
    "3) CONCEDE GRADUALLY — this is the most important rule. Start AT the listed price. "
    "Each time the buyer pushes, lower your offer by only a SMALL step (about 5-15% of the gap "
    "between listed and your minimum). NEVER drop straight to your minimum, and NEVER make a big "
    "sudden jump — sellers hate that. It must take several rounds of pushing to approach {FLOOR}.\n"
    "4) Only accept once the buyer meets your current (slowly lowered) asking price and it is "
    ">= {FLOOR}. Do not give your best price on the first or second message.\n"
    "Reply in {LANG}, 1-2 short sentences, friendly.\n"
    'Respond ONLY with JSON: {"reply": "<message>", "offer_price": <integer current or agreed price>, '
    '"accepted": true|false}. accepted=true ONLY for a final deal at offer_price (>= your minimum).'
)


async def haggle(*, listed_price, floor_price, history, buyer_message, lang="uz") -> dict:
    """Xaridor bilan sotuvchi nomidan savdolashadi. floor_price — MAXFIY (hech qachon
    ochilmaydi/buzilmaydi). Qaytaradi {"reply", "offer_price", "accepted"} yoki None."""
    if not is_enabled() or not (buyer_message or "").strip():
        return None
    lng = "uzbek" if lang == "uz" else ("russian" if lang == "ru" else "uzbek")
    system = (_HAGGLE_SYSTEM.replace("{LISTED}", str(int(listed_price)))
              .replace("{FLOOR}", str(int(floor_price))).replace("{LANG}", lng))
    msgs = [{"role": "system", "content": system}]
    for h in (history or [])[-6:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        msgs.append({"role": role, "content": str(h.get("content") or "")[:500]})
    msgs.append({"role": "user", "content": str(buyer_message)[:500]})
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    # max_tokens 400 — 250'da DeepSeek ba'zan javobni kesib BO'SH content qaytarardi
    # ("Expecting value: line 1 column 1") va savdolashish 502 bilan o'lardi.
    payload = {"model": MODEL, "messages": msgs, "max_tokens": 400,
               "temperature": 0.6, "response_format": {"type": "json_object"}, "stream": False}
    # Bo'sh/buzuq javob — vaqtinchalik DeepSeek nuqsoni; bir marta qayta uriniladi.
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
                resp = await client.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers)
                if resp.status_code >= 400:
                    log.warning(f"Haggle API xatosi {resp.status_code}: {resp.text[:300]}")
                    return None
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("message", {}).get("content") or "").strip()
                if not content:
                    log.warning(f"Haggle bo'sh content (urinish {attempt + 1}), "
                                f"finish_reason={choice.get('finish_reason')}")
                    continue  # qayta urinib ko'ramiz
                m = re.search(r"\{.*\}", content, re.DOTALL)
                parsed = json.loads(m.group(0) if m else content)
                try:
                    offer = int(float(parsed.get("offer_price") or listed_price))
                except (TypeError, ValueError):
                    offer = int(listed_price)
                reply = str(parsed.get("reply") or "").strip()[:500]
                if not reply:
                    log.warning(f"Haggle reply bo'sh (urinish {attempt + 1})")
                    continue
                return {
                    "reply": reply,
                    "offer_price": offer,
                    "accepted": bool(parsed.get("accepted")),
                }
        except Exception as e:
            log.warning(f"Haggle xato (urinish {attempt + 1}): {e}")
    return None


# ============================================================
# SHARHGA JAVOB GENERATSIYASI (bir martalik, agent siklisiz)
# ============================================================
_REVIEW_REPLY_SYSTEM = {
    'uz': (
        "Sen — TezBozor marketplace sotuvchisining mijozlarga g'amxo'r yordamchisisan. "
        "Mijozning sharhiga sotuvchi nomidan QISQA, samimiy va professional OCHIQ javob yoz "
        "(boshqa xaridorlar ham o'qiydi). Qoidalar:\n"
        "• Mijozga DOIM formal «siz» da (hech qachon «sen» emas), ism bilan (bo'lsa) hurmat bilan "
        "murojaat qil; ijobiy fikr uchun rahmat ayt.\n"
        "• Past baho yoki shikoyat bo'lsa — bahslashmasdan uzr so'ra va yechim/yaxshilanish va'da qil.\n"
        "• 1-3 jumla, samimiy. 1-2 emoji mumkin. HTML/markdown va hashtag ISHLATMA.\n"
        "• Faqat javob matnini qaytar, izohsiz. 400 belgidan oshmasin."
    ),
    'ru': (
        "Ты — заботливый помощник продавца маркетплейса TezBozor. "
        "Напиши от имени магазина КОРОТКИЙ, искренний и профессиональный ПУБЛИЧНЫЙ ответ на отзыв "
        "(его читают и другие покупатели). Правила:\n"
        "• Обращайся к клиенту ВСЕГДА на формальное «вы» (никогда на «ты»), по имени (если есть), "
        "уважительно; поблагодари за положительный отзыв.\n"
        "• Если оценка низкая или жалоба — без спора извинись и пообещай решение/улучшение.\n"
        "• 1-3 предложения, искренне. Можно 1-2 эмодзи. БЕЗ HTML/markdown и хештегов.\n"
        "• Верни только текст ответа, без пояснений. Не более 400 символов."
    ),
}


async def generate_review_reply(*, product, comment, shop_rating=None,
                                product_rating=None, buyer="", lang="uz") -> str:
    """Mijoz sharhiga sotuvchi nomidan javob matnini tuzadi (bir martalik chaqiruv).
    Xato yoki AI o'chiq bo'lsa — None qaytaradi."""
    if not is_enabled():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    facts = {
        ("mahsulot" if lang == 'uz' else "товар"): product,
        ("xaridor" if lang == 'uz' else "покупатель"): buyer,
        ("do'kon bahosi" if lang == 'uz' else "оценка магазина"):
            (f"{shop_rating}/5" if shop_rating else None),
        ("mahsulot bahosi" if lang == 'uz' else "оценка товара"):
            (f"{product_rating}/5" if product_rating else None),
        ("izoh" if lang == 'uz' else "отзыв"): comment,
    }
    facts = {k: v for k, v in facts.items() if v}
    user_msg = ("Sharh ma'lumotlari:\n" if lang == 'uz' else "Данные отзыва:\n") + \
               "\n".join(f"- {k}: {v}" for k, v in facts.items())

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _REVIEW_REPLY_SYSTEM[lang]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 300,
        "temperature": 0.9,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Sharh javobi API xatosi {resp.status_code}")
                return None
            data = resp.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                return None
            text = _strip_hashtags(text)
            if len(text) > 500:
                text = text[:500].rstrip()
            return text or None
    except Exception as e:
        log.warning(f"Sharh javobi yaratishda xato: {e}")
        return None


# ============================================================
# MUROJAATGA ADMIN JAVOBI (support) — AI suhbatni O'QIB javob tuzadi
# ============================================================
_SUPPORT_REPLY_SYSTEM = {
    'uz': (
        "Sen — TezBozor marketplace qo'llab-quvvatlash (support) xizmatining admin yordamchisisan. "
        "Quyidagi suhbatni DIQQAT bilan o'qib, foydalanuvchining ANIQ savoli/muammosiga to'g'ridan-to'g'ri, "
        "foydali va aniq javob yoz. Qoidalar:\n"
        "• Shablon javob YOZMA — aynan shu savolga, suhbat mazmuniga qarab javob ber.\n"
        "• Muammoni hal qilishga qaratilgan amaliy qadamlar yoki aniq tushuntirish ber.\n"
        "• Ma'lumot yetishmasa — foydalanuvchidan kerakli aniqlik (masalan buyurtma raqami)ni xushmuomalalik bilan so'ra.\n"
        "• Iliq, hurmatli, qisqa ohang. Foydalanuvchiga DOIM formal «siz» da murojaat qil "
        "(hech qachon «sen» emas). 1 emoji mumkin. HTML/markdown/hashtag ISHLATMA.\n"
        "• Faqat javob matnini qaytar, izohsiz. 600 belgidan oshmasin."
    ),
    'ru': (
        "Ты — помощник администратора службы поддержки маркетплейса TezBozor. "
        "Внимательно прочитай переписку и напиши прямой, полезный и конкретный ответ на КОНКРЕТНЫЙ "
        "вопрос/проблему пользователя. Правила:\n"
        "• НЕ пиши шаблонный ответ — отвечай именно на этот вопрос, по сути переписки.\n"
        "• Дай практические шаги решения или чёткое объяснение.\n"
        "• Если данных не хватает — вежливо уточни нужное (например номер заказа).\n"
        "• Тёплый, уважительный, краткий тон. ВСЕГДА обращайся к пользователю на формальное «вы» "
        "(никогда на «ты»). Можно 1 эмодзи. БЕЗ HTML/markdown/хештегов.\n"
        "• Верни только текст ответа, без пояснений. Не более 600 символов."
    ),
}


async def generate_support_reply(*, reason_label="", messages=None, lang="uz") -> str:
    """Murojaat suhbatini (foydalanuvchi↔admin) O'QIB, foydalanuvchining oxirgi savoliga
    mos admin javobini tuzadi. Shablon emas — kontekstga qarab. Xato/o'chiq bo'lsa None."""
    if not is_enabled():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    messages = messages or []
    # Suhbat transkripti — kim yozgani aniq ko'rsatiladi
    you = "Foydalanuvchi" if lang == 'uz' else "Пользователь"
    adm = "Admin" if lang == 'uz' else "Админ"
    lines = []
    for m in messages[-12:]:
        who = adm if (m.get("sender_role") == "admin") else you
        txt = (m.get("text") or "").strip()
        if txt:
            lines.append(f"{who}: {txt}")
    if not lines:
        return None
    hdr = (f"Murojaat sababi: {reason_label}\n" if reason_label else "")
    convo = ("Suhbat:\n" if lang == 'uz' else "Переписка:\n") + "\n".join(lines)
    user_msg = hdr + convo

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SUPPORT_REPLY_SYSTEM[lang]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 400,
        "temperature": 0.7,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Support javobi API xatosi {resp.status_code}")
                return None
            data = resp.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                return None
            text = _strip_hashtags(text)
            if len(text) > 600:
                text = text[:600].rstrip()
            return text or None
    except Exception as e:
        log.warning(f"Support javobi yaratishda xato: {e}")
        return None


# ============================================================
# PROFILNI TO'LDIRISHGA ILTIMOS (admin → foydalanuvchi)
# ============================================================
_PROFILE_FILL_SYSTEM = {
    'uz': (
        "Sen — TezBozor marketplace ma'muriyatining xushmuomala yordamchisisan. "
        "Foydalanuvchiga uning profilida TO'LDIRILMAGAN ma'lumotlarni to'ldirishni iltimos qilib "
        "QISQA, samimiy va hurmatli xabar yoz. Qoidalar:\n"
        "• Ism bilan (bo'lsa) iliq murojaat qil va salomlash.\n"
        "• Qaysi ma'lumotlar yetishmayotganini aniq, ro'yxat ko'rinishida ko'rsat.\n"
        "• Nega kerakligini bitta jumlada tushuntir (ishonch ortadi, buyurtmalar oson bo'ladi).\n"
        "• Profilni «Profil» bo'limidan to'ldirish mumkinligini ayt.\n"
        "• Iliq, hurmatli ohang. 1-2 emoji mumkin. HTML/markdown va hashtag ISHLATMA.\n"
        "• Faqat xabar matnini qaytar, izohsiz. 700 belgidan oshmasin."
    ),
    'ru': (
        "Ты — вежливый помощник администрации маркетплейса TezBozor. "
        "Напиши пользователю КОРОТКОЕ, искреннее и уважительное сообщение с просьбой "
        "заполнить НЕДОСТАЮЩИЕ данные в его профиле. Правила:\n"
        "• Обратись по имени (если есть), тепло поздоровайся.\n"
        "• Чётко, списком укажи, каких данных не хватает.\n"
        "• Одним предложением объясни, зачем это нужно (доверие, удобство заказов).\n"
        "• Скажи, что профиль можно заполнить в разделе «Профиль».\n"
        "• Тёплый, уважительный тон. Можно 1-2 эмодзи. БЕЗ HTML/markdown и хештегов.\n"
        "• Верни только текст сообщения, без пояснений. Не более 700 символов."
    ),
}


async def generate_profile_completion_message(*, name="", missing_fields=None,
                                               is_seller=False, lang="uz") -> str:
    """Profilda yetishmayotgan maydonlar asosida foydalanuvchiga yuboriladigan
    iltimos xabarini tuzadi. Har chaqiruvda yangi variant (temperature yuqori).
    Xato yoki AI o'chiq bo'lsa — None qaytaradi."""
    if not is_enabled():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    missing_fields = missing_fields or []
    fields_str = "\n".join(f"- {m}" for m in missing_fields) or ("- (—)")
    if lang == 'uz':
        who = "Sotuvchi" if is_seller else "Xaridor"
        user_msg = (f"Foydalanuvchi ismi: {name or '—'}\n"
                    f"Roli: {who}\n"
                    f"Profildagi to'ldirilmagan maydonlar:\n{fields_str}")
    else:
        who = "Продавец" if is_seller else "Покупатель"
        user_msg = (f"Имя пользователя: {name or '—'}\n"
                    f"Роль: {who}\n"
                    f"Незаполненные поля профиля:\n{fields_str}")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _PROFILE_FILL_SYSTEM[lang]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 500,
        "temperature": 1.0,   # har safar takrorlanmas variant (admin "qayta yaratish"i uchun)
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Profil to'ldirish xabari API xatosi {resp.status_code}")
                return None
            data = resp.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                return None
            text = _strip_hashtags(text)
            if len(text) > 900:
                text = text[:900].rstrip()
            return text or None
    except Exception as e:
        log.warning(f"Profil to'ldirish xabari yaratishda xato: {e}")
        return None


# ============================================================
# #9 — SHEVA / SLANG QIDIRUV (natija topilmasa AI tushunadi)
# ============================================================
# Xaridor "chotki oyoq kiyim", "duxi", "kasitka" kabi shevada yozsa, oddiy LIKE
# qidiruv hech narsa topmaydi. Bu yordamchi so'rovni RASMIY/standart qidiruv
# so'zlariga aylantiradi (sinonim + transliteratsiya emas, MA'NO darajasida).
_SLANG_SYSTEM = {
    'uz': (
        "Sen O'zbekiston onlayn bozori uchun qidiruv tarjimonisan. Xaridor mahsulotni "
        "SHEVA, jargon yoki so'zlashuv tilida yozadi (masalan 'chotki krasovka', 'duxi', "
        "'kasitka', 'adidaslar'). Sening vazifang — buni do'kondagi mahsulot nomi/tavsifida "
        "uchraydigan 2-5 ta STANDART, rasmiy kalit so'zga aylantirish.\n"
        "Faqat JSON qaytar: {\"keywords\": [\"...\", \"...\"], \"category\": \"<eng mos kategoriya nomi yoki bo'sh>\"}.\n"
        "keywords — qisqa, umumiy nomlar (sifat/brendni ham qo'shsang bo'ladi). Hech narsa "
        "tushunmasang, bo'sh ro'yxat qaytar. Izoh yozma."
    ),
    'ru': (
        "Ты — поисковый переводчик для узбекского онлайн-рынка. Покупатель пишет товар на "
        "СЛЕНГЕ или разговорно (например 'кроссы', 'духи', 'кофта'). Твоя задача — превратить "
        "это в 2-5 СТАНДАРТНЫХ ключевых слов, которые встречаются в названии/описании товара.\n"
        "Верни только JSON: {\"keywords\": [\"...\", \"...\"], \"category\": \"<подходящая категория или пусто>\"}.\n"
        "keywords — короткие общие названия. Если ничего не понятно — пустой список. Без пояснений."
    ),
}


async def interpret_search_query(query, categories=None, lang="uz") -> dict:
    """Sheva/jargon so'rovni standart kalit so'zlarga aylantiradi (#9).
    Qaytaradi {"keywords": [str, ...], "category": str} yoki None (AI o'chiq/xato)."""
    if not is_enabled() or not (query or "").strip():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    user_msg = (query or "").strip()[:200]
    if categories:
        cat_label = "Mavjud kategoriyalar" if lng == 'uz' else "Доступные категории"
        names = ", ".join(str(c)[:40] for c in categories if c)[:600]
        user_msg += f"\n\n{cat_label}: {names}"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SLANG_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 150,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Slang qidiruv API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)
            kws = parsed.get("keywords") or []
            if isinstance(kws, str):
                kws = [kws]
            keywords = [str(k).strip()[:50] for k in kws if str(k).strip()][:5]
            return {
                "keywords": keywords,
                "category": str(parsed.get("category") or "").strip()[:60],
            }
    except Exception as e:
        log.warning(f"Slang qidiruv xato: {e}")
        return None


# ============================================================
# #4 — REELS / TIKTOK SSENARIY (sotuvchiga qisqa video skript)
# ============================================================
_REELS_SYSTEM = {
    'uz': (
        "Sen — qisqa video (Reels/TikTok) bo'yicha tajribali ssenariy mualliflisan. "
        "Sotuvchiga uning mahsuloti uchun 15-30 soniyalik JOZIBALI video skript yoz.\n"
        "Tuzilma (shu sarlavhalar bilan):\n"
        "🎬 HOOK (0-3s) — e'tibor tortuvchi birinchi jumla/sahna.\n"
        "🎥 SAHNALAR — 3-5 ta qisqa kadr: har biri [vaqt] + nima ko'rsatiladi + ekrandagi yozuv.\n"
        "🗣 OVOZ MATNI — kadrlarga mos qisqa zakadr matni.\n"
        "🎵 MUSIQA — mos trend/uslub maslahati.\n"
        "📢 CTA — oxirgi chorlov.\n"
        "#️⃣ HASHTAGLAR — 5-8 ta mos hashtag.\n"
        "Faqat berilgan mahsulot faktlaridan foydalan, narx/xususiyatni o'ylab topma. "
        "Jonli, sodda o'zbek tilida. HTML/markdown ishlatma — oddiy matn va emoji."
    ),
    'ru': (
        "Ты — опытный сценарист коротких видео (Reels/TikTok). Напиши продавцу ЦЕПЛЯЮЩИЙ "
        "сценарий видео на 15-30 секунд для его товара.\n"
        "Структура (с этими заголовками):\n"
        "🎬 HOOK (0-3s) — цепляющая первая фраза/сцена.\n"
        "🎥 СЦЕНЫ — 3-5 коротких кадров: [время] + что показать + текст на экране.\n"
        "🗣 ОЗВУЧКА — короткий закадровый текст под кадры.\n"
        "🎵 МУЗЫКА — совет по тренду/стилю.\n"
        "📢 CTA — финальный призыв.\n"
        "#️⃣ ХЕШТЕГИ — 5-8 подходящих.\n"
        "Используй только данные факты, не выдумывай цену/характеристики. "
        "Живой, простой русский. Без HTML/markdown — обычный текст и эмодзи."
    ),
}


async def generate_video_script(*, name, price_text="", category="",
                                description="", lang="uz") -> str:
    """Mahsulot uchun Reels/TikTok ssenariysi yozadi (#4). Matn yoki None qaytaradi."""
    if not is_enabled() or not (name or "").strip():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    parts = [f"{'Mahsulot' if lng=='uz' else 'Товар'}: {name}"]
    if price_text:
        parts.append(f"{'Narx' if lng=='uz' else 'Цена'}: {price_text}")
    if category:
        parts.append(f"{'Kategoriya' if lng=='uz' else 'Категория'}: {category}")
    if description:
        parts.append(f"{'Tavsif' if lng=='uz' else 'Описание'}: {description}")
    user_msg = "\n".join(parts)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _REELS_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 800,
        "temperature": 0.85,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Reels ssenariy API xatosi {resp.status_code}")
                return None
            text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            if len(text) > 2000:
                text = text[:2000].rstrip()
            return text or None
    except Exception as e:
        log.warning(f"Reels ssenariy xato: {e}")
        return None


# ============================================================
# #6 — SENTIMENT TAHLIL (sharhlardan admin uchun "nimadan norozi")
# ============================================================
_SENTIMENT_SYSTEM = {
    'uz': (
        "Sen — marketplace uchun mijoz sharhlarini tahlil qiluvchi tahlilchisan. "
        "Senga bir nechta sharh (baho + izoh) beriladi. Ularni umumlashtirib, admin uchun "
        "qisqa hisobot tuz.\n"
        "Faqat JSON qaytar:\n"
        '{"summary": "<2-3 jumlalik umumiy xulosa>", '
        '"complaints": ["<asosiy shikoyat/norozilik mavzulari>"], '
        '"praises": ["<eng ko\'p maqtalgan jihatlar>"], '
        '"suggestions": ["<admin uchun 2-4 ta amaliy tavsiya>"]}.\n'
        "Har ro'yxat 3-5 banddan oshmasin, bandlar qisqa. Faqat berilgan sharhlarga tayan. "
        "O'zbek tilida yoz. Izohsiz."
    ),
    'ru': (
        "Ты — аналитик отзывов клиентов маркетплейса. Тебе дают несколько отзывов "
        "(оценка + комментарий). Обобщи их в краткий отчёт для админа.\n"
        "Верни только JSON:\n"
        '{"summary": "<вывод в 2-3 предложениях>", '
        '"complaints": ["<основные темы жалоб>"], '
        '"praises": ["<что чаще всего хвалят>"], '
        '"suggestions": ["<2-4 практических совета админу>"]}.\n'
        "В каждом списке не более 3-5 коротких пунктов. Опирайся только на данные отзывы. "
        "Пиши по-русски. Без пояснений."
    ),
}


async def analyze_sentiment(reviews, lang="uz") -> dict:
    """Sharhlar ro'yxatini tahlil qilib admin hisobotini qaytaradi (#6).
    reviews — [{rating, comment, product_name?, shop_name?}, ...].
    Qaytaradi {"summary","complaints","praises","suggestions"} yoki None."""
    if not is_enabled():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    lines = []
    for r in (reviews or [])[:120]:
        cm = str((r.get("comment") or "")).strip()
        if not cm:
            continue
        rt = r.get("rating") or r.get("product_rating") or "?"
        shop = str(r.get("shop_name") or "").strip()
        prefix = f"[{rt}★]" + (f"({shop})" if shop else "")
        lines.append(f"{prefix} {cm[:300]}")
    if not lines:
        return None
    user_msg = "\n".join(lines[:120])[:8000]
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SENTIMENT_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 700,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Sentiment API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)

            def _lst(key):
                v = parsed.get(key) or []
                if isinstance(v, str):
                    v = [v]
                return [str(x).strip()[:200] for x in v if str(x).strip()][:5]

            return {
                "summary": str(parsed.get("summary") or "").strip()[:600],
                "complaints": _lst("complaints"),
                "praises": _lst("praises"),
                "suggestions": _lst("suggestions"),
            }
    except Exception as e:
        log.warning(f"Sentiment tahlil xato: {e}")
        return None


# ============================================================
# #11 — DINAMIK NARX (talab/raqobat signallaridan narx tavsiyasi)
# ============================================================
# #2 (price-insight) faqat raqobat o'rtachasiga qaraydi. Dinamik narx esa mahsulotning
# REAL signallarini (sotuv tezligi, zahira, kunlar, sevimlilar, reyting) + raqobatni
# birga tahlil qilib "ko'tar / tushir / qoldir" tavsiyasini va aniq narxni beradi.
_DYNPRICE_SYSTEM = {
    'uz': (
        "Sen — marketplace uchun dinamik narx bo'yicha tahlilchisan. Senga mahsulotning "
        "joriy narxi, talab signallari (sotilgan dona, kutilayotgan buyurtma, sevimlilar, "
        "e'lon turgan kunlar, zahira, reyting) va raqobat narx statistikasi beriladi.\n"
        "Mantiq:\n"
        "• Talab YUQORI (tez sotilyapti, ko'p sevimli) + zahira kam → narxni biroz KO'TARISH mumkin.\n"
        "• Talab PAST (uzoq turibdi, sotilmayapti, ko'p zahira) → narxni TUSHIRISH (chegirma) tavsiya.\n"
        "• Narx raqobatdan ancha qimmat va sotuv past → tushir; ancha arzon va talab yuqori → ko'tar.\n"
        "• Ishonching kam bo'lsa yoki signal yetarli emas → 'keep'.\n"
        "Faqat JSON qaytar: {\"verdict\": \"raise|lower|keep\", \"suggested_price\": <butun son>, "
        "\"change_pct\": <foiz, manfiy=tushish>, \"reason\": \"<1-2 jumla, o'zbekcha>\", "
        "\"confidence\": \"low|medium|high\"}. suggested_price real va mantiqiy bo'lsin "
        "(odatda joriy narxdan ±25% ichida). Izohsiz."
    ),
    'ru': (
        "Ты — аналитик динамического ценообразования маркетплейса. Тебе дают текущую цену "
        "товара, сигналы спроса (продано шт, ожидающие заказы, в избранном, дней в продаже, "
        "остаток, рейтинг) и статистику цен конкурентов.\n"
        "Логика:\n"
        "• Высокий спрос (быстро продаётся, много в избранном) + мало остатка → можно слегка ПОВЫСИТЬ.\n"
        "• Низкий спрос (долго висит, не продаётся, много остатка) → ПОНИЗИТЬ (скидка).\n"
        "• Цена сильно выше конкурентов и слабые продажи → понизить; сильно ниже и высокий спрос → повысить.\n"
        "• Мало уверенности или недостаточно сигналов → 'keep'.\n"
        "Верни только JSON: {\"verdict\": \"raise|lower|keep\", \"suggested_price\": <целое>, "
        "\"change_pct\": <процент, минус=снижение>, \"reason\": \"<1-2 предложения, по-русски>\", "
        "\"confidence\": \"low|medium|high\"}. suggested_price реалистичный "
        "(обычно в пределах ±25% от текущей). Без пояснений."
    ),
}


async def dynamic_price_advice(*, name, price, signals, competitor=None,
                               category="", lang="uz") -> dict:
    """#11 — mahsulot uchun dinamik narx tavsiyasi. signals — get_product_demand_signals()
    natijasi; competitor — get_category_price_stats() natijasi (yoki None).
    Qaytaradi {"verdict","suggested_price","change_pct","reason","confidence"} yoki None."""
    if not is_enabled() or not (name or "").strip():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    s = signals or {}
    parts = [f"{'Mahsulot' if lng=='uz' else 'Товар'}: {name}"]
    if category:
        parts.append(f"{'Kategoriya' if lng=='uz' else 'Категория'}: {category}")
    parts.append(f"{'Joriy narx' if lng=='uz' else 'Текущая цена'}: {int(price or 0)}")
    stock = s.get("stock_count")
    stock_txt = ("∞" if stock is None else str(stock))
    if lng == 'uz':
        parts += [
            f"E'lon turgan kunlar: {s.get('days_listed', 0)}",
            f"Sotilgan (dona): {s.get('sold', 0)}",
            f"Jami buyurtma: {s.get('orders_total', 0)} (kutilayotgan: {s.get('pending_orders', 0)})",
            f"Sevimlilarga qo'shilgan: {s.get('favorites', 0)}",
            f"Zahira: {stock_txt}",
            f"Reyting: {s.get('prod_rating') or '—'} ({s.get('review_count', 0)} sharh)",
        ]
    else:
        parts += [
            f"Дней в продаже: {s.get('days_listed', 0)}",
            f"Продано (шт): {s.get('sold', 0)}",
            f"Всего заказов: {s.get('orders_total', 0)} (ожидают: {s.get('pending_orders', 0)})",
            f"В избранном: {s.get('favorites', 0)}",
            f"Остаток: {stock_txt}",
            f"Рейтинг: {s.get('prod_rating') or '—'} ({s.get('review_count', 0)} отзывов)",
        ]
    if competitor and competitor.get("count"):
        if lng == 'uz':
            parts.append(f"Raqobat ({competitor['count']} ta): o'rtacha {competitor.get('avg')}, "
                         f"eng arzon {competitor.get('min')}, eng qimmat {competitor.get('max')}")
        else:
            parts.append(f"Конкуренты ({competitor['count']}): средняя {competitor.get('avg')}, "
                         f"мин {competitor.get('min')}, макс {competitor.get('max')}")
    user_msg = "\n".join(parts)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _DYNPRICE_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 250,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Dinamik narx API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)
            verdict = str(parsed.get("verdict") or "keep").lower()
            if verdict not in ("raise", "lower", "keep"):
                verdict = "keep"
            try:
                sp = int(float(parsed.get("suggested_price") or price or 0))
            except (TypeError, ValueError):
                sp = int(price or 0)
            try:
                cp = int(float(parsed.get("change_pct") or 0))
            except (TypeError, ValueError):
                cp = 0
            conf = str(parsed.get("confidence") or "medium").lower()
            if conf not in ("low", "medium", "high"):
                conf = "medium"
            return {
                "verdict": verdict,
                "suggested_price": max(0, sp),
                "change_pct": cp,
                "reason": str(parsed.get("reason") or "")[:300],
                "confidence": conf,
            }
    except Exception as e:
        log.warning(f"Dinamik narx xato: {e}")
        return None


# ============================================================
# #17 — AQLLI SOVG'A YORDAMCHISI (kimga + sabab + budjet → g'oyalar)
# ============================================================
_GIFT_SYSTEM = {
    'uz': (
        "Sen — O'zbekiston marketplace'ining sovg'a tanlash bo'yicha aqlli yordamchisisan. "
        "Foydalanuvchi kimga (kishi, yosh/jins), qaysi sabab bilan va qancha budjetga sovg'a "
        "izlayotganini aytadi. Sen 3-5 ta aniq sovg'a G'OYASINI taklif qil.\n"
        "Faqat JSON qaytar:\n"
        '{"intro": "<1 jumlalik samimiy kirish>", "ideas": [{"title": "<sovg\'a nomi>", '
        '"reason": "<nega mos, 1 jumla>", "keywords": ["<do\'kondan qidirish uchun 1-3 standart so\'z>"]}]}\n'
        "keywords — do'kon katalogida mahsulot nomida uchraydigan umumiy so'zlar (brend emas). "
        "G'oyalar budjetga mos va xilma-xil bo'lsin. O'zbekcha. Izohsiz."
    ),
    'ru': (
        "Ты — умный помощник по выбору подарков узбекского маркетплейса. Пользователь говорит, "
        "кому (человек, возраст/пол), по какому поводу и на какой бюджет ищет подарок. "
        "Предложи 3-5 конкретных ИДЕЙ подарка.\n"
        "Верни только JSON:\n"
        '{"intro": "<тёплое вступление в 1 предложение>", "ideas": [{"title": "<название подарка>", '
        '"reason": "<почему подходит, 1 предложение>", "keywords": ["<1-3 стандартных слова для поиска>"]}]}\n'
        "keywords — общие слова, встречающиеся в названиях товаров каталога (не бренды). "
        "Идеи в рамках бюджета и разнообразные. По-русски. Без пояснений."
    ),
}


async def gift_advisor(*, recipient="", occasion="", budget=None, notes="",
                       categories=None, lang="uz") -> dict:
    """#17 — sovg'a g'oyalarini taklif qiladi. Qaytaradi {"intro", "ideas":[{title,reason,keywords}]}
    yoki None (AI o'chiq/xato)."""
    if not is_enabled():
        return None
    lng = lang if lang in ('uz', 'ru') else 'uz'
    parts = []
    if recipient:
        parts.append(f"{'Kimga' if lng=='uz' else 'Кому'}: {recipient}")
    if occasion:
        parts.append(f"{'Sabab' if lng=='uz' else 'Повод'}: {occasion}")
    if budget:
        parts.append(f"{'Budjet' if lng=='uz' else 'Бюджет'}: {budget}")
    if notes:
        parts.append(f"{'Qo`shimcha' if lng=='uz' else 'Дополнительно'}: {notes}")
    if not parts:
        return None
    if categories:
        cat_label = "Mavjud kategoriyalar" if lng == 'uz' else "Доступные категории"
        names = ", ".join(str(c)[:40] for c in categories if c)[:600]
        parts.append(f"{cat_label}: {names}")
    user_msg = "\n".join(parts)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _GIFT_SYSTEM[lng]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 600,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=AD_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/chat/completions",
                                     json=payload, headers=headers)
            if resp.status_code >= 400:
                log.warning(f"Sovg'a yordamchisi API xatosi {resp.status_code}")
                return None
            content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0) if m else content)
            ideas = []
            for it in (parsed.get("ideas") or [])[:5]:
                if not isinstance(it, dict):
                    continue
                kws = it.get("keywords") or []
                if isinstance(kws, str):
                    kws = [kws]
                keywords = [str(k).strip()[:50] for k in kws if str(k).strip()][:3]
                title = str(it.get("title") or "").strip()[:80]
                if not title:
                    continue
                ideas.append({
                    "title": title,
                    "reason": str(it.get("reason") or "").strip()[:200],
                    "keywords": keywords,
                })
            if not ideas:
                return None
            return {"intro": str(parsed.get("intro") or "").strip()[:300], "ideas": ideas}
    except Exception as e:
        log.warning(f"Sovg'a yordamchisi xato: {e}")
        return None


# ============================================================
# SUHBAT XOTIRASI
# ============================================================
def reset_history(user_data: dict) -> None:
    user_data.pop('ai_history', None)


def _get_history(user_data: dict) -> list:
    hist = user_data.get('ai_history')
    if not isinstance(hist, list):
        hist = []
        user_data['ai_history'] = hist
    return hist


# ============================================================
# ASOSIY: AGENT CHAQIRUVI (tool-call sikli)
# ============================================================
async def ask(db, lang: str, role: str, user_text: str, user_data: dict,
              *, seller_id=None, user_name: str = "", shop_filter=None, shop_name="") -> dict:
    """Foydalanuvchi xabariga agent javobini qaytaradi.

    shop_filter — do'kon (sotuvchi) id si: berilsa, xaridor qidiruvi FAQAT shu
    do'kon mahsulotlari bilan cheklanadi (do'kon ichida AI qidiruv).

    Natija: {"text": str, "products": [...]|None, "draft": {...}|None}
    Xato bo'lsa ham istisno tashlamaydi — text ichida tushunarli xabar bo'ladi.
    """
    if not is_enabled():
        return {"text": _msg_disabled(lang), "products": None, "draft": None}

    role = role if role in ('admin', 'seller', 'buyer') else 'buyer'
    actor = {'lang': lang, 'role': role, 'seller_id': seller_id, 'shop_filter': shop_filter}

    history = _get_history(user_data)

    # Ishchi xabarlar (system + tarix + joriy savol). Tool round-trip shu yerda kechadi,
    # lekin tarixga faqat toza user/assistant matn saqlanadi.
    system_content = build_system_prompt(lang, role, user_name)
    if shop_filter:
        if lang == 'ru':
            system_content += (f"\n\nВАЖНО: покупатель находится ВНУТРИ магазина "
                               f"«{shop_name or '—'}». search_products ищет ТОЛЬКО товары этого "
                               f"магазина. Если в этом магазине ничего не найдено — честно скажи, "
                               f"что в этом магазине такого нет.")
        else:
            system_content += (f"\n\nMUHIM: xaridor «{shop_name or '—'}» do'koni ICHIDA. "
                               f"search_products FAQAT shu do'kon mahsulotlarini qidiradi. "
                               f"Shu do'kondan topilmasa — rostini ayt, shu do'konda bunday "
                               f"mahsulot yo'qligini bildirib qo'y.")
    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    tools = _tools_for(role)
    ui_products = None
    ui_draft = None
    ui_reactivated = None
    ui_order_actions = []
    ui_review_replies = []
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for _ in range(MAX_TOOL_STEPS):
                payload = {
                    "model": MODEL,
                    "messages": messages,
                    "max_tokens": MAX_TOKENS,
                    "temperature": 0.6,
                    "stream": False,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                resp = await client.post(f"{BASE_URL}/chat/completions",
                                         json=payload, headers=headers)
                err = _http_error_text(resp, lang)
                if err is not None:
                    return {"text": err, "products": ui_products, "draft": ui_draft,
                            "reactivated_id": ui_reactivated, "order_actions": ui_order_actions,
                            "review_replies": ui_review_replies}

                data = resp.json()
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    answer = (msg.get("content") or "").strip()
                    if not answer:
                        answer = _msg_empty(lang)
                    # Tarixni yangilaymiz (faqat toza matn)
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": answer})
                    if len(history) > MAX_HISTORY:
                        del history[:len(history) - MAX_HISTORY]
                    return {"text": answer, "products": ui_products, "draft": ui_draft,
                            "reactivated_id": ui_reactivated, "order_actions": ui_order_actions,
                            "review_replies": ui_review_replies}

                # Tool'larni bajaramiz
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn = (tc.get("function") or {})
                    tname = fn.get("name") or ""
                    try:
                        targs = json.loads(fn.get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        targs = {}
                    result, ui = _exec_tool(db, actor, tname, targs)
                    if ui and ui.get("type") == "products":
                        ui_products = ui["items"]
                    elif ui and ui.get("type") == "draft":
                        ui_draft = ui["draft"]
                    elif ui and ui.get("type") == "reactivated":
                        ui_reactivated = ui["product_id"]
                    elif ui and ui.get("type") == "order_action":
                        ui_order_actions.append(ui)
                    elif ui and ui.get("type") == "review_reply":
                        ui_review_replies.append(ui)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                # keyingi sikl — model natijani ko'rib javob yozadi

            # Sikllar tugadi, javob yo'q — bor natijani qaytaramiz
            fallback = _msg_steps(lang)
            return {"text": fallback, "products": ui_products, "draft": ui_draft,
                    "reactivated_id": ui_reactivated, "order_actions": ui_order_actions,
                    "review_replies": ui_review_replies}

    except httpx.TimeoutException:
        log.warning("DeepSeek timeout")
        return {"text": _msg_timeout(lang), "products": None, "draft": None}
    except Exception as e:
        log.error(f"AI agent xatosi: {e}")
        return {"text": _msg_error(lang), "products": None, "draft": None}


def _http_error_text(resp, lang):
    """HTTP status >=400 bo'lsa tushunarli xabar matnini qaytaradi, aks holda None."""
    sc = resp.status_code
    if sc < 400:
        return None
    if sc == 401:
        log.error("DeepSeek 401 — noto'g'ri API kalit")
        return _msg_badkey(lang)
    if sc == 402:
        log.error("DeepSeek 402 — balans yetarli emas")
        return _msg_nobalance(lang)
    if sc == 429:
        log.warning("DeepSeek 429 — rate limit")
        return _msg_busy(lang)
    log.error(f"DeepSeek error {sc}: {resp.text[:300]}")
    return _msg_error(lang)


# ============================================================
# FOYDALANUVCHIGA XABARLAR (xato holatlari)
# ============================================================
def _pick(lang, uz, ru):
    return ru if lang == 'ru' else uz


def _msg_disabled(lang):
    return _pick(lang,
        "🤖 AI yordamchi hozircha sozlanmagan. Admin DEEPSEEK_API_KEY ni qo'shishi kerak.",
        "🤖 ИИ-помощник пока не настроен. Администратору нужно добавить DEEPSEEK_API_KEY.")

def _msg_timeout(lang):
    return _pick(lang,
        "⌛ Javob juda uzoq cho'zildi. Iltimos, qaytadan urinib ko'ring.",
        "⌛ Ответ занял слишком много времени. Попробуйте ещё раз.")

def _msg_error(lang):
    return _pick(lang,
        "⚠️ AI bilan bog'lanishda xato yuz berdi. Birozdan so'ng urinib ko'ring.",
        "⚠️ Ошибка при обращении к ИИ. Попробуйте чуть позже.")

def _msg_badkey(lang):
    return _pick(lang,
        "🔑 AI kaliti noto'g'ri. Admin DEEPSEEK_API_KEY ni tekshirishi kerak.",
        "🔑 Неверный ключ ИИ. Администратору нужно проверить DEEPSEEK_API_KEY.")

def _msg_nobalance(lang):
    return _pick(lang,
        "💳 AI hisobida mablag' tugagan. Admin DeepSeek balansini to'ldirishi kerak.",
        "💳 На счёте ИИ закончились средства. Администратору нужно пополнить баланс DeepSeek.")

def _msg_busy(lang):
    return _pick(lang,
        "🚦 So'rovlar juda ko'p. Iltimos, bir oz kutib qaytadan urinib ko'ring.",
        "🚦 Слишком много запросов. Подождите немного и попробуйте снова.")

def _msg_empty(lang):
    return _pick(lang,
        "🤔 Javob topilmadi. Savolni boshqacha yozib ko'ring.",
        "🤔 Не удалось получить ответ. Попробуйте переформулировать вопрос.")

def _msg_steps(lang):
    return _pick(lang,
        "🤔 Savol biroz murakkab bo'ldi. Iltimos, soddaroq qilib yozib ko'ring.",
        "🤔 Запрос оказался сложным. Попробуйте сформулировать проще.")
