"""`main.py` ning sof (mock'siz) funksiyalari uchun karakterizatsiya testlari.

15K qatorli `main.py` ilgari 0% test bilan qoplangan edi — bot biznes-mantig'idagi
har o'zgarish jimgina buzilishi mumkin edi. Bu fayl eng xavfli, mock talab
qilmaydigan sohalarni qotiradi: SAVAT pul matematikasi, TAYMER/muddat, INPUT
VALIDATSIYA (xavfsizlik), narx/masofa. Telegram handlerlari (update/context
oluvchi async funksiyalar) bu yerda emas — ular keyingi bosqich.
"""
import os
import types
from datetime import datetime, timedelta, timezone

# main.py tokensiz import bo'lishi uchun — DB default sqlite, import paytida
# Database() yaratiladi (idempotent init_db), bu testlarga zarar bermaydi.
os.environ.setdefault("BOT_TOKEN", "test:test")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DB_BACKEND", "sqlite")

import main  # noqa: E402


def _ctx():
    """Telegram context o'rniga: faqat user_data dict kerak (savat shu yerda)."""
    return types.SimpleNamespace(user_data={})


def _product(pid=1, seller_id=10, price=45000, stock=None, name="Telefon"):
    p = {"id": pid, "seller_id": seller_id, "name": name, "price": price,
         "shop_name": "Do'kon"}
    if stock is not None:
        p["stock_count"] = stock
    return p


# ===================== INPUT VALIDATSIYA (xavfsizlik) =====================
def test_normalize_phone_local_9_digits():
    assert main.normalize_phone("901234567") == "+998901234567"


def test_normalize_phone_with_spaces_and_plus():
    assert main.normalize_phone("+998 90 123 45 67") == "+998901234567"


def test_normalize_phone_too_short_is_none():
    assert main.normalize_phone("123") is None


def test_normalize_phone_too_long_is_none():
    assert main.normalize_phone("1" * 16) is None


def test_normalize_phone_empty_is_none():
    assert main.normalize_phone("") is None
    assert main.normalize_phone(None) is None


def test_normalize_username_strips_at():
    assert main.normalize_telegram_username("@durov") == "durov"
    assert main.normalize_telegram_username("durov") == "durov"


def test_normalize_username_must_start_with_letter():
    assert main.normalize_telegram_username("123ab") is None


def test_normalize_username_length_bounds():
    assert main.normalize_telegram_username("ab") is None       # juda qisqa
    assert main.normalize_telegram_username("a" * 33) is None   # juda uzun


def test_normalize_username_rejects_space():
    assert main.normalize_telegram_username("user name") is None


def test_normalize_name_collapses_whitespace():
    assert main.normalize_name("  Ali   Vali  ") == "Ali Vali"


def test_normalize_name_length_bounds():
    assert main.normalize_name("A") is None
    assert main.normalize_name("x" * 51) is None


def test_validate_fullname_ok():
    assert main.validate_fullname("Aliyev Vali") == "Aliyev Vali"


def test_validate_fullname_requires_two_words():
    assert main.validate_fullname("Aliyev") is None


def test_validate_fullname_rejects_digits():
    assert main.validate_fullname("Aliyev123 Vali") is None


def test_validate_fullname_length_bounds():
    assert main.validate_fullname("A B") is None          # <5 belgi
    assert main.validate_fullname("Aliyev " + "x" * 60) is None  # >60


def test_validate_fullname_allows_cyrillic_and_apostrophe():
    assert main.validate_fullname("G'ulomov Asad") == "G'ulomov Asad"


# ===================== SAVAT — pul matematikasi =====================
def test_empty_cart_counts_zero():
    ctx = _ctx()
    assert main._cart_count(ctx) == 0
    assert main._cart_total(ctx) == 0


def test_cart_put_adds_item():
    ctx = _ctx()
    main._cart_put(ctx, _product(price=45000))
    assert main._cart_count(ctx) == 1
    assert main._cart_total(ctx) == 45000


def test_cart_put_increments_quantity():
    ctx = _ctx()
    p = _product(price=1000)
    main._cart_put(ctx, p)
    main._cart_put(ctx, p)
    assert main._cart_count(ctx) == 2
    assert main._cart_total(ctx) == 2000


def test_cart_put_respects_stock_cap():
    ctx = _ctx()
    main._cart_put(ctx, _product(stock=2), delta=5)
    assert main._cart_count(ctx) == 2  # 5 emas — zahira chegarasi


def test_cart_put_negative_delta_removes_item():
    ctx = _ctx()
    p = _product()
    main._cart_put(ctx, p)
    main._cart_put(ctx, p, delta=-10)
    assert main._cart_count(ctx) == 0
    assert main._cart(ctx) is None  # bo'shasa savat tozalanadi


def test_cart_switching_seller_resets_cart():
    ctx = _ctx()
    main._cart_put(ctx, _product(pid=1, seller_id=10, price=1000))
    main._cart_put(ctx, _product(pid=2, seller_id=99, price=500))
    # Yangi do'kon — eski savat almashtiriladi
    cart = main._cart(ctx)
    assert cart["seller_id"] == 99
    assert main._cart_count(ctx) == 1
    assert main._cart_total(ctx) == 500


def test_cart_total_multiple_items():
    ctx = _ctx()
    main._cart_put(ctx, _product(pid=1, seller_id=10, price=1000), delta=2)
    main._cart_put(ctx, _product(pid=2, seller_id=10, price=500), delta=3)
    assert main._cart_count(ctx) == 5
    assert main._cart_total(ctx) == 1000 * 2 + 500 * 3


def test_cart_clear_removes_everything():
    ctx = _ctx()
    main._cart_put(ctx, _product())
    ctx.user_data["cart_address"] = "Toshkent"
    main._cart_clear(ctx)
    assert main._cart(ctx) is None
    assert "cart_address" not in ctx.user_data


# ===================== TAYMER / MUDDAT =====================
def test_parse_utc_valid():
    dt = main._parse_utc("2026-06-22 10:30:00")
    assert dt is not None
    assert dt.year == 2026 and dt.hour == 10 and dt.tzinfo == timezone.utc


def test_parse_utc_truncates_microseconds():
    assert main._parse_utc("2026-06-22 10:30:00.123456") is not None


def test_parse_utc_invalid_is_none():
    assert main._parse_utc("axlat") is None
    assert main._parse_utc(None) is None
    assert main._parse_utc("") is None


def test_order_deadline_prefers_auto_cancel_at():
    order = {"auto_cancel_at": "2026-06-22 12:00:00",
             "created_at": "2026-06-22 10:00:00"}
    dl = main._order_deadline(order)
    assert dl == datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_order_deadline_falls_back_to_created_plus_ttl():
    order = {"created_at": "2026-06-22 10:00:00"}
    dl = main._order_deadline(order)
    expected = (datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
                + timedelta(seconds=main.ORDER_TTL_SECONDS))
    assert dl == expected


def test_order_deadline_none_when_no_timestamps():
    assert main._order_deadline({}) is None


def test_countdown_line_empty_when_no_deadline():
    assert main._countdown_line("uz", None) == ""


def test_countdown_line_future_is_nonempty():
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    line = main._countdown_line("uz", future)
    assert isinstance(line, str) and line != ""


def test_countdown_line_expired_is_nonempty():
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    line = main._countdown_line("uz", past)
    assert isinstance(line, str) and line != ""


# ===================== NARX / MASOFA =====================
def test_price_with_unit_no_unit():
    from tezbozor_design import fmt_price
    p = {"price": 45000}
    assert main.price_with_unit(p) == fmt_price(45000)


def test_price_with_unit_with_unit():
    from tezbozor_design import fmt_price
    p = {"price": 5000, "unit": "kg"}
    assert main.price_with_unit(p) == f"{fmt_price(5000)} / kg"


def test_haversine_same_point_is_zero():
    assert main.haversine_km(41.31, 69.24, 41.31, 69.24) == 0.0


def test_haversine_one_degree_lat():
    # 1° kenglik ~111 km; yo'l koeffitsienti 1.35 → ~150 km
    d = main.haversine_km(41.0, 69.0, 42.0, 69.0)
    assert 145 <= d <= 155


def test_haversine_invalid_is_none():
    assert main.haversine_km(None, 1, 2, 3) is None
    assert main.haversine_km("x", 1, 2, 3) is None


# ===================== CALLBACK PARSING =====================
def test_pid_from_cb():
    q = types.SimpleNamespace(data="ef_name_5")
    assert main._pid_from_cb(q) == 5
    q2 = types.SimpleNamespace(data="ef_price_42")
    assert main._pid_from_cb(q2) == 42


def test_product_is_new_recent():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    assert main._product_is_new(now) is True


def test_product_is_new_old():
    assert main._product_is_new("2020-01-01 00:00:00") is False


def test_product_is_new_none():
    assert main._product_is_new(None) is False


# ==================== ⏰ Buyurtma push-eslatma bosqichlari ====================
def test_order_reminders_three_thresholds_defined():
    """3 ta eslatma bosqichi bo'lishi kerak (foydalanuvchi: 2 emas, 3 marta)."""
    assert len(main.ORDER_REMINDER_MINUTES) == 3


def test_order_reminders_none_at_start():
    """Boshlanishda (10 daqiqa qoldi) hali eslatma yo'q — birinchi bosqich 5 daqiqa."""
    assert main._due_order_reminders(600, []) == []


def test_order_reminders_fire_one_at_a_time():
    """Har bosqich navbati bilan, bittadan ishga tushadi (normal 60s tiklar)."""
    fired = []
    # ~6 daqiqa qoldi
    due = main._due_order_reminders(350, fired)
    assert due == [6]
    fired += due
    assert main._due_order_reminders(350, fired) == []      # qayta yubormaydi
    # ~3 daqiqa qoldi
    assert main._due_order_reminders(170, fired) == [3]
    fired.append(3)
    # ~1 daqiqa qoldi
    assert main._due_order_reminders(50, fired) == [1]


def test_order_reminders_restart_burst_then_no_dupes():
    """Restartda (fired bo'sh) qolgan oz vaqtda o'tib ketgan bosqichlar birato'la
    yuboriladi, lekin keyin takrorlanmaydi (idempotent)."""
    assert main._due_order_reminders(50, []) == [6, 3, 1]
    assert main._due_order_reminders(50, [6, 3, 1]) == []


def test_order_reminders_tolerance_late_tick():
    """Tik daqiqa chegarasidan bir oz kech tushsa ham (mas. 6 daq=360s, tik 362s'da)
    bosqich o'sha tikda ishga tushadi — 60s kechikmaydi (+3s tolerance)."""
    assert main._due_order_reminders(362, []) == [6]   # 362 <= 363 → ishlaydi
    assert main._due_order_reminders(364, []) == []    # 364 > 363 → hali emas
