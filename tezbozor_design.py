"""TezBozor — dizayn yordamchilari (matn formatlash, status emojilari)"""
import re
import json
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


def wholesale_tiers(product):
    """Mahsulotning optom (ulgurji) narx ZINALARINI qaytaradi: (listed, [{'min','price'}, ...]).
    Zinalar min bo'yicha o'sib tartiblangan. Manba: `wholesale_tiers` (JSON ro'yxat) yoki
    eski yagona `wholesale_price`/`wholesale_min_qty` (moslik). Faqat to'g'ri zinalar:
    price>0, min>=2, price<listed; takror min olib tashlanadi."""
    try:
        p = dict(product)
    except Exception:
        p = product or {}
    try:
        listed = float(p.get("price") or 0)
    except (ValueError, TypeError):
        listed = 0.0
    raw = p.get("wholesale_tiers")
    items = []
    if raw:
        try:
            data = raw if isinstance(raw, list) else json.loads(raw)
            for t in data:
                items.append((int(t.get("min")), float(t.get("price"))))
        except Exception:
            items = []
    if not items:   # eski yagona zina (moslik)
        try:
            wp = float(p.get("wholesale_price") or 0)
            wq = int(p.get("wholesale_min_qty") or 0)
            if wp > 0 and wq >= 2:
                items = [(wq, wp)]
        except (ValueError, TypeError):
            items = []
    clean, seen = [], set()
    for m, pr in sorted(items, key=lambda x: x[0]):
        if m < 2 or pr <= 0 or (listed > 0 and pr >= listed) or m in seen:
            continue
        seen.add(m)
        clean.append({"min": m, "price": pr})
    return listed, clean


def wholesale_info(product):
    """Optom holati: {enabled, listed, tiers:[...], entry (eng past min), best (eng past narx)}."""
    listed, tiers = wholesale_tiers(product)
    return {"enabled": bool(tiers), "listed": listed, "tiers": tiers,
            "entry": (tiers[0] if tiers else None),
            "best": (tiers[-1] if tiers else None)}


def effective_unit_price(product, qty):
    """Berilgan son uchun amaldagi DONA narxi: qty yetadigan zinalardan ENG ARZONI;
    hech bir zinaga yetmasa oddiy (listed) narx. Barcha o'lchov birliklari uchun."""
    listed, tiers = wholesale_tiers(product)
    try:
        q = int(qty)
    except (ValueError, TypeError):
        q = 0
    applicable = [t["price"] for t in tiers if q >= t["min"]]
    return min(applicable) if applicable else listed


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


# Kun uchun maxsus qiymatlar (resolve_schedule natijasida):
#   (start_min, end_min) — o'sha kun aniq soatlarda ochiq
#   CLOSED               — o'sha kun BUTUNLAY yopiq (dam olish yoki qisqa jadval bo'yicha)
#   None                 — soat noma'lum (24 soat / parse yo'q) → "ochiq" deb qaraladi, muzlatilmaydi
CLOSED = "closed"


def resolve_schedule(work_schedule=None, working_hours=None, working_days=None):
    """Do'konning HAFTALIK jadvalini {0..6: (start_min,end_min)|CLOSED|None} ko'rinishida qaytaradi
    (0=Dushanba .. 6=Yakshanba). Ustuvorlik:
      1) work_schedule — har kun uchun alohida soat (JSON dict yoki tayyor dict). Bu bo'lsa
         working_hours/working_days E'TIBORGA OLINMAYDI (to'liq ustun).
      2) Aks holda — eski yagona working_hours + working_days'dan bir xil jadval quriladi
         (orqaga moslik: har ochiq kun bir xil soatda ishlaydi).

    work_schedule format: {"0":"09:00-21:00", ..., "6":"09:00-12:30" yoki "" / null=yopiq}.
    Bo'sh/yaroqsiz kun = CLOSED. Hech bir kunda soat bo'lmasa jadval yaroqsiz → fallback."""
    data = work_schedule
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    if isinstance(data, dict):
        # Kamida bitta kun uchun qiymat bo'lsa — bu haqiqiy per-kun jadval
        if any(data.get(str(w)) or data.get(w) for w in range(7)):
            out = {}
            for wd in range(7):
                v = data.get(str(wd))
                if v is None:
                    v = data.get(wd)
                if not v or not str(v).strip():
                    out[wd] = CLOSED          # bo'sh = o'sha kun yopiq
                else:
                    p = parse_working_hours(v)
                    if not p or p[0] == p[1]:
                        out[wd] = None        # 24 soat / noaniq → ochiq
                    else:
                        out[wd] = p
            return out
    # --- Fallback: eski yagona soat + ish kunlari ---
    parsed = parse_working_hours(working_hours)
    if parsed and parsed[0] == parsed[1]:
        parsed = None                         # 24 soat → noma'lum (ochiq)
    open_days = parse_working_days(working_days)
    out = {}
    for wd in range(7):
        if open_days is not None and wd not in open_days:
            out[wd] = CLOSED                  # dam olish kuni
        else:
            out[wd] = parsed if parsed else None
    return out


def normalize_schedule(raw):
    """Client (Mini App) yuborgan haftalik jadvalni tekshirib, KANONIK JSON matnga aylantiradi.
    Kirish: dict yoki JSON-matn {"0":"09:00-21:00", ..., "6":""}. Har kalit 0..6 (Du..Ya),
    qiymat soat oralig'i yoki bo'sh (=yopiq). Qaytadi: '{"0":"09:00-21:00",...}' JSON matni,
    yoki hech bir kunda soat bo'lmasa None (= jadval o'chirildi, eski yagona soatga qaytadi).

    Har bir kun soati kanonik "HH:MM-HH:MM" ko'rinishida saqlanadi; yopiq kunlar kalitga
    kiritilmaydi (yo'qligi = yopiq)."""
    data = raw
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    out = {}
    for wd in range(7):
        v = data.get(str(wd))
        if v is None:
            v = data.get(wd)
        if v is None or not str(v).strip():
            continue                     # yopiq kun — kalit qo'shilmaydi
        p = parse_working_hours(v)
        if not p or p[0] == p[1]:
            continue                     # yaroqsiz / 24 soat → o'sha kunni tashlab ketamiz
        s, e = p
        out[str(wd)] = f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}"
    if not out:
        return None
    return json.dumps(out, ensure_ascii=False)


def is_shop_open_now(working_hours_text=None, working_days=None, work_schedule=None):
    """Hozirgi Toshkent vaqtida do'kon ochiqmi? None — aniqlay olmadik, True/False — aniq.
    Endi haftalik jadvalni ham hisobga oladi (dam olish/qisqa kunlar)."""
    sched = resolve_schedule(work_schedule, working_hours_text, working_days)
    now = datetime.now(TZ_TASHKENT)
    entry = sched[now.weekday()]
    if entry is None:            # soat noma'lum
        return None
    if entry == CLOSED:          # bugun yopiq
        return False
    start, end = entry
    current = now.hour * 60 + now.minute
    if start < end:
        return start <= current < end
    # Tunda yopiladigan do'kon (masalan, 22:00-04:00)
    return current >= start or current < end


# Ish kunlari (weekday indekslari: 0=Dushanba ... 6=Yakshanba). Uzun nomlar avval —
# "shanba" boshqa kun nomlari ichida (seshanba, chorshanba...) borligi uchun tartib muhim.
_DAY_PATTERNS = [
    (r'yakshanba|yaksh|voskresen|воскрес|\bвс\b', 6),
    (r'dushanba|dush|ponedel|понедел|\bпн\b', 0),
    (r'seshanba|sesh|vtornik|вторник|\bвт\b', 1),
    (r'chorshanba|chor|sred|сред|\bср\b', 2),
    (r'payshanba|pays|chetverg|четверг|\bчт\b', 3),
    (r'juma|pyatnic|пятниц|\bпт\b', 4),
    (r'shanba|shan|subbot|суббот|\bсб\b', 5),
]


def parse_working_days(text):
    """Do'kon OCHIQ bo'lgan hafta kunlari to'plamini (0=Dushanba..6=Yakshanba) qaytaradi.
    Aniqlab bo'lmasa None (= barcha kun ochiq deb qaraladi). Erkin matn: "Dushanba-Shanba",
    "Har kuni", "Ish kunlari", "Du-Ju, Ya" kabi ko'rinishlarni tushunadi."""
    if not text:
        return None
    s = str(text).strip().lower()
    if not s:
        return None
    # Har kuni / 7-24 / hafta davomida → hammasi ochiq (None ham shu ma'noda, lekin aniq)
    if re.search(r'har\s*kuni|hamma\s*kun|hafta\s*davomida|ежеднев|каждый\s*день|все\s*дни'
                 r'|every\s*day|daily|7/7|24/7|7\s*kun', s):
        return {0, 1, 2, 3, 4, 5, 6}
    if re.search(r'ish\s*kunlari|budni|рабочие', s):
        return {0, 1, 2, 3, 4}
    if re.search(r'dam\s*olish|выходны|weekend', s):
        return {5, 6}
    # Kun tokenlarini pozitsiyasi bilan topamiz; topilganini masklaymiz (ichma-ich mos kelmasin)
    masked = s
    found = []  # (pozitsiya, indeks)
    for pat, idx in _DAY_PATTERNS:
        for m in re.finditer(pat, masked):
            found.append((m.start(), idx))
        masked = re.sub(pat, lambda mm: ' ' * (mm.end() - mm.start()), masked)
    if not found:
        return None
    found.sort()
    idxs = [i for _, i in found]
    # "X-Y" oralig'i: aynan 2 ta kun va orasida chiziqcha bo'lsa — siklik oraliq
    if len(idxs) == 2 and '-' in s.replace('—', '-').replace('–', '-'):
        a, b = idxs[0], idxs[1]
        days = set()
        d = a
        while True:
            days.add(d)
            if d == b:
                break
            d = (d + 1) % 7
        return days or None
    return set(idxs) or None


def next_shop_open_datetime(working_hours=None, working_days=None, now=None, work_schedule=None):
    """Do'kon HOZIR yopiq bo'lsa — keyingi ochilish vaqtini (TZ_TASHKENT, tz-aware) qaytaradi.
    Hozir OCHIQ bo'lsa None. Ish soatini umuman aniqlab bo'lmasa (hamma kun noma'lum / 24 soat)
    ham None (= "ochiq" deb qaraladi, buyurtma darhol boshlanadi). Endi HAFTALIK jadvalni
    (har kun alohida soat, qisqa/dam olish kunlari) to'liq hisobga oladi — masalan
    "yakshanba faqat 12:30 gacha" holatida tushdan keyin kelgan buyurtma dushanbagacha muzlaydi."""
    sched = resolve_schedule(work_schedule, working_hours, working_days)
    # Hamma kun noma'lum bo'lsa — soat umuman belgilanmagan → doim ochiq deb qaraymiz
    if all(v is None for v in sched.values()):
        return None

    if now is None:
        now = datetime.now(TZ_TASHKENT)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=TZ_TASHKENT)
    else:
        now = now.astimezone(TZ_TASHKENT)

    def _is_open(dt):
        entry = sched[dt.weekday()]
        if entry is None:        # o'sha kun soati noma'lum → ochiq
            return True
        if entry == CLOSED:
            return False
        start, end = entry
        minute = dt.hour * 60 + dt.minute
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end   # tunda yopiladigan

    if _is_open(now):
        return None
    for off in range(0, 8):
        d = now + timedelta(days=off)
        entry = sched[d.weekday()]
        if entry == CLOSED:
            continue
        if entry is None:
            # O'sha kun soati noma'lum (24 soat) → kun boshidan ochiq deb qaraymiz
            open_dt = d.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start, _end = entry
            open_dt = d.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if open_dt > now:
            return open_dt
    return None


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
