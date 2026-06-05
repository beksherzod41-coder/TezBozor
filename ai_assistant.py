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
                "• Заказы: list_orders — показать заказы, особенно ожидающие подтверждения (pending).\n"
                "• Аналитика: sales_report — статистика и конкретные советы (что улучшить, какой товар не продаётся).\n"
                "ВАЖНО: перед update_product/set_stock/delete_product сначала найди правильный product_id "
                "через list_my_products. Перед удалением — переспроси. После действия кратко подтверди результат."
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
            "• Buyurtmalar: list_orders — buyurtmalarni, ayniqsa tasdiq kutayotganlarini (pending) ko'rsat.\n"
            "• Tahlil: sales_report — statistika va aniq maslahat (nimani yaxshilash, qaysi mahsulot sotilmayapti).\n"
            "MUHIM: update_product/set_stock/delete_product dan OLDIN avval list_my_products orqali to'g'ri "
            "product_id ni top. O'chirishdan oldin qayta so'ra. Amaldan keyin natijani qisqa tasdiqla."
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
        "• Tuzilma: diqqat tortuvchi sarlavha → 2-4 ta afzallik (emoji bilan) → narx → joylashuv (bo'lsa) "
        "→ kuchli harakatga chorlash (CTA) → 3-6 ta mos hashtag.\n"
        "• HTML yoki markdown (** , __) ISHLATMA — faqat oddiy matn va emoji.\n"
        "• Qisqa va lo'nda: 700 belgidan oshmasin. Faqat reklama matnini qaytar, izohsiz."
    ),
    'ru': (
        "Ты — опытный РЕКЛАМНЫЙ копирайтер маркетплейса TezBozor. "
        "По данным о товаре напиши ОДИН цепляющий, уникальный рекламный текст (для поста в Telegram). Правила:\n"
        "• Используй только данные факты — не выдумывай цену, название, характеристики.\n"
        "• Живой, привлекающий стиль. Используй эмодзи и разделители (━ ✦ 🔥 ⭐ 👇).\n"
        "• Структура: цепляющий заголовок → 2-4 преимущества (с эмодзи) → цена → локация (если есть) "
        "→ сильный призыв к действию → 3-6 подходящих хештегов.\n"
        "• НЕ используй HTML или markdown (**, __) — только обычный текст и эмодзи.\n"
        "• Коротко: не более 700 символов. Верни только рекламный текст, без пояснений."
    ),
}


async def generate_ad_caption(*, name, price_text, category="", description="",
                              shop="", location="", lang="uz") -> str:
    """Mahsulotdan kelib chiqib takrorlanmas reklama matni (caption) yaratadi.

    Xato yoki AI o'chiq bo'lsa — None qaytaradi (chaqiruvchi oddiy matnga qaytadi)."""
    if not is_enabled():
        return None
    lang = lang if lang in ('uz', 'ru') else 'uz'
    facts = {
        "nom": name, "narx": price_text, "kategoriya": category,
        "tavsif": description, "do'kon": shop, "joylashuv": location,
    }
    facts = {k: v for k, v in facts.items() if v}
    user_msg = ("Mahsulot ma'lumotlari:\n" if lang == 'uz' else "Данные о товаре:\n") + \
               "\n".join(f"- {k}: {v}" for k, v in facts.items())

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _AD_SYSTEM[lang]},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 500,
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
            if len(text) > 1000:
                text = text[:1000].rstrip()
            return text
    except Exception as e:
        log.warning(f"Reklama matni yaratishda xato: {e}")
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
              *, seller_id=None, user_name: str = "") -> dict:
    """Foydalanuvchi xabariga agent javobini qaytaradi.

    Natija: {"text": str, "products": [...]|None, "draft": {...}|None}
    Xato bo'lsa ham istisno tashlamaydi — text ichida tushunarli xabar bo'ladi.
    """
    if not is_enabled():
        return {"text": _msg_disabled(lang), "products": None, "draft": None}

    role = role if role in ('admin', 'seller', 'buyer') else 'buyer'
    actor = {'lang': lang, 'role': role, 'seller_id': seller_id}

    history = _get_history(user_data)

    # Ishchi xabarlar (system + tarix + joriy savol). Tool round-trip shu yerda kechadi,
    # lekin tarixga faqat toza user/assistant matn saqlanadi.
    messages = [{"role": "system", "content": build_system_prompt(lang, role, user_name)}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    tools = _tools_for(role)
    ui_products = None
    ui_draft = None
    ui_reactivated = None
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
                            "reactivated_id": ui_reactivated}

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
                            "reactivated_id": ui_reactivated}

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
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                # keyingi sikl — model natijani ko'rib javob yozadi

            # Sikllar tugadi, javob yo'q — bor natijani qaytaramiz
            fallback = _msg_steps(lang)
            return {"text": fallback, "products": ui_products, "draft": ui_draft,
                    "reactivated_id": ui_reactivated}

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
