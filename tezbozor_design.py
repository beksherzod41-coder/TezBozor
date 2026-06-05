"""TezBozor — dizayn yordamchilari (matn formatlash, status emojilari)"""
import re
from datetime import datetime, timezone, timedelta


# Toshkent vaqt zonasi: UTC+5
TZ_TASHKENT = timezone(timedelta(hours=5))


def fmt_datetime(dt_value):
    """SQLite UTC timestampini Toshkent vaqtiga aylantiradi.
    Misol: '2026-05-25 06:44:32' (UTC) → '25.05.2026 11:44'"""
    if not dt_value:
        return "—"
    try:
        if isinstance(dt_value, str):
            # SQLite default formati: 'YYYY-MM-DD HH:MM:SS'
            # Ba'zan mikrosekundlar bilan keladi
            try:
                dt = datetime.strptime(dt_value[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return str(dt_value)
        elif isinstance(dt_value, datetime):
            dt = dt_value
        else:
            return str(dt_value)
        # SQLite CURRENT_TIMESTAMP UTC qaytaradi
        dt_utc = dt.replace(tzinfo=timezone.utc)
        dt_tashkent = dt_utc.astimezone(TZ_TASHKENT)
        return dt_tashkent.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(dt_value)


def fmt_price(uzs):
    """45000 → '45 000 so'm' (bo'sh joy ajratuvchi)"""
    try:
        n = int(round(float(uzs)))
        return f"{n:,}".replace(",", "\u00A0") + " so'm"
    except (ValueError, TypeError):
        return f"{uzs} so'm"


def fmt_phone(num):
    """998901234567 → '+998 90 123 45 67'"""
    if not num:
        return "Kiritilmagan"
    digits = re.sub(r"\D", "", str(num))
    if digits.startswith("998") and len(digits) == 12:
        return f"+{digits[:3]} {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:]}"
    if len(digits) == 9:
        return f"+998 {digits[:2]} {digits[2:5]} {digits[5:7]} {digits[7:]}"
    return str(num)


def fmt_order_id(n):
    """48201 → '#TB-48201'"""
    try:
        return f"#TB-{int(n):06d}"
    except (ValueError, TypeError):
        return f"#TB-{n}"


def fmt_status(status):
    """'delivered' → '🚚 Yetkazildi'"""
    mapping = {
        'pending': '⏳ Yangi',
        'confirmed': '✅ Tasdiqlangan',
        'delivered': '🚚 Yetkazildi',
        'cancelled': '❌ Bekor qilindi',
        'approved': '✅ Tasdiqlangan',
        'rejected': '❌ Rad etildi',
    }
    return mapping.get(status, status or '?')


def fmt_rating(rating, count=None):
    """4.7 → '⭐ 4.7' yoki '⭐ 4.7 (12 baho)'"""
    try:
        r = float(rating)
        if count is not None:
            return f"⭐ {r:.1f} ({count} baho)"
        return f"⭐ {r:.1f}"
    except (ValueError, TypeError):
        return "⭐ Reyting yo'q"


def safe(val, default="Kiritilmagan"):
    if val is None or str(val).strip() == "":
        return default
    return str(val)


# ============================================================
# MANZIL (ADDRESS) YORDAMCHILARI
# ============================================================
# Muammo: lokatsiya yuborilganda manzil "41.31, 69.24" ko'rinishida saqlanardi.
# Hech kim bu raqamlardan joyni tushunmaydi. Quyidagi yordamchilar shunday
# "xom koordinata" matnini aniqlaydi va uni foydalanuvchiga ko'rsatmaydi —
# o'rniga mo'ljal (orientir) yoki xaritadan ko'rish havolasi ishlatiladi.

# "41.311081, 69.240562"  yoki  "41.31,69.24"  ko'rinishini tutadi
_COORD_RE = re.compile(r'^\s*[-+]?\d{1,3}(?:\.\d+)?\s*,\s*[-+]?\d{1,3}(?:\.\d+)?\s*$')


def looks_like_coords(value) -> bool:
    """Matn faqat 'lat, lon' xom koordinatasimi?"""
    return bool(_COORD_RE.match(str(value or "")))


def human_address(shop_address):
    """O'qiladigan manzil matnini qaytaradi.
    Agar qiymat bo'sh bo'lsa yoki faqat xom koordinata bo'lsa — None."""
    s = str(shop_address or "").strip()
    if not s or looks_like_coords(s):
        return None
    return s


def best_location_text(shop_address, shop_landmark=None):
    """Eng yaxshi o'qiladigan joy matni: haqiqiy manzil > mo'ljal > None.
    Hech qachon xom koordinatani qaytarmaydi."""
    addr = human_address(shop_address)
    if addr:
        return addr
    lm = str(shop_landmark or "").strip()
    return lm or None


def maps_link(lat, lon, label="Xaritada ko'rish"):
    """Google Maps qidiruv havolasi (HTML <a>). Koordinata bo'lmasa — bo'sh."""
    if lat is None or lon is None:
        return ""
    return (f"\n🗺️ <a href=\"https://www.google.com/maps/search/?api=1&"
            f"query={lat},{lon}\">{label}</a>")


def parse_working_hours(text):
    """'09:00-21:00' yoki '9-21' ko'rinishidagi vaqt oralig'ini (start_min, end_min) tupliga aylantiradi.
    Yaroqsiz bo'lsa None qaytaradi."""
    if not text:
        return None
    s = str(text).strip().lower()
    # 'dan'/'gacha'/'to'/'from' so'zlarini bo'sh joy bilan birga olib tashlash
    s = re.sub(r'\s*(dan|gacha|to|from|—|–)\s*', '-', s, flags=re.IGNORECASE)
    s = s.replace(' ', '').replace('—', '-').replace('–', '-')
    # Bir nechta '-' bo'lib qolsa, eng cheti bilan qisqartirish
    s = re.sub(r'-+', '-', s).strip('-')
    m = re.match(r'^(\d{1,2})(?::(\d{1,2}))?-(\d{1,2})(?::(\d{1,2}))?$', s)
    if not m:
        return None
    try:
        h1 = int(m.group(1)); m1 = int(m.group(2) or 0)
        h2 = int(m.group(3)); m2 = int(m.group(4) or 0)
        if not (0 <= h1 <= 24 and 0 <= h2 <= 24 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
            return None
        return (h1 * 60 + m1, h2 * 60 + m2)
    except ValueError:
        return None


def is_shop_open_now(working_hours_text):
    """Hozirgi Toshkent vaqtida do'kon ochiqmi? None — aniqlay olmadik, True/False — aniq."""
    parsed = parse_working_hours(working_hours_text)
    if not parsed:
        return None
    now = datetime.now(TZ_TASHKENT)
    current = now.hour * 60 + now.minute
    start, end = parsed
    if start == end:
        return None
    if start < end:
        return start <= current < end
    # Tunda yopiladigan do'kon (masalan, 22:00-04:00)
    return current >= start or current < end


class M:
    """Bot xabarlari — barchasi sentence case, qisqa"""
    WELCOME = "👋 TezBozorga xush kelibsiz!"
    REGISTRATION_PHONE = "Telefon raqamingizni yuboring:"
    REGISTRATION_NAME = "Ismingizni kiriting:"
    
    BUYER_PANEL = "Xaridor paneli\n\nNima qilmoqchisiz?"
    SELLER_PANEL = "Sotuvchi paneli"
    ADMIN_PANEL = "Admin paneli"
    
    EMPTY_PRODUCTS = "Hozircha mahsulotlar yo'q."
    EMPTY_ORDERS = "Hozircha buyurtmalar yo'q."
    EMPTY_USERS = "Hozircha foydalanuvchilar yo'q."
    
    SEARCH_PROMPT = "🔍 Qidirish uchun mahsulot nomini yozing:"
    LOCATION_PROMPT = "📍 Joylashuvingizni yuboring:"
    
    PRODUCT_ADDED = "✅ Mahsulot qo'shildi!"
    PRODUCT_UPDATED = "✅ Mahsulot yangilandi!"
    PRODUCT_DELETED = "✅ Mahsulot o'chirildi."
    
    ORDER_CREATED = "✅ Buyurtma qabul qilindi!"
    MESSAGE_SENT = "✅ Xabar yuborildi!"
    PROFILE_UPDATED = "✅ Profil yangilandi!"
    
    ERROR_NOT_FOUND = "Topilmadi."
    ERROR_BLOCKED = "⛔ Siz bloklangansiz. Admin bilan bog'laning."
    ERROR_INVALID_INPUT = "Iltimos, to'g'ri ma'lumot kiriting."


BRAND = {
    "name": "TezBozor",
    "description": "TezBozor — o'z mahsulotlaringizni sotish va kerakli tovarlarni qulay xarid qilish uchun marketplace bot. Tez. Oson. Ishonchli.",
    "short_description": "Marketplace bot · Tashkent",
    "commands": [
        ("start", "Botni boshlash"),
        ("help", "Yordam"),
        ("orders", "Buyurtmalarim"),
        ("cancel", "Bekor qilish"),
        ("admin", "Admin paneli"),
    ],
}
