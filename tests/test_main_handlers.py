"""`main.py` savat handlerlari uchun async testlar (mock'langan update/context).

Sof funksiyalardan keyingi qadam: HAQIQIY Telegram handlerlarini ishga tushirib,
ular savatni (context.user_data) va DB o'qishini to'g'ri qilishini sinaymiz.
Telegram Update/Context yengil fake bilan almashtiriladi; DB esa conftest'dagi
vaqtinchalik haqiqiy SQLite (main.db monkeypatch qilinadi). `asyncio.run` bilan
haydaymiz — pytest-asyncio plagini SHART EMAS (CI'da ham ishlaydi).
"""
import asyncio
import os
import types
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("BOT_TOKEN", "test:test")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DB_BACKEND", "sqlite")

import main  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeQuery:
    """Telegram CallbackQuery o'rni: data + async metodlar (chaqiruvni yozadi)."""
    def __init__(self, data, message=None):
        self.data = data
        self.message = message
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.edit_message_reply_markup = AsyncMock()


def make_update(query, tg_id, chat_id=555):
    return types.SimpleNamespace(
        callback_query=query,
        effective_user=types.SimpleNamespace(id=tg_id),
        effective_chat=types.SimpleNamespace(id=chat_id),
        message=types.SimpleNamespace(reply_text=AsyncMock()),
    )


def make_context():
    return types.SimpleNamespace(
        user_data={"lang": "uz"},  # get_lang keshdan oladi — DB so'rovi shart emas
        bot=types.SimpleNamespace(send_message=AsyncMock()),
    )


@pytest.fixture
def env(db, seller, buyer, product, monkeypatch):
    """main.db'ni vaqtinchalik bazaga ulaydi + UI-yangilovchi yordamchilarni jim qiladi."""
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "_refresh_catalog_footer", AsyncMock())
    monkeypatch.setattr(main, "_refresh_cart_add_button", AsyncMock())
    return types.SimpleNamespace(db=db, seller=seller, buyer=buyer, product=product)


# ============================ cart_add ============================
def test_cart_add_valid(env):
    q = FakeQuery(f"cart_add_{env.product}")
    ctx = make_context()
    run(main.cart_add(make_update(q, 2002), ctx))   # 2002 = xaridor
    cart = main._cart(ctx)
    assert cart is not None
    assert cart["items"][str(env.product)]["qty"] == 1
    assert q.answer.await_count == 1


def test_cart_add_own_product_blocked(env):
    q = FakeQuery(f"cart_add_{env.product}")
    ctx = make_context()
    run(main.cart_add(make_update(q, 1001), ctx))   # 1001 = sotuvchining o'zi
    assert main._cart(ctx) is None
    assert q.answer.call_args.kwargs.get("show_alert") is True


def test_cart_add_missing_product_alerts(env):
    q = FakeQuery("cart_add_999999")
    ctx = make_context()
    run(main.cart_add(make_update(q, 2002), ctx))
    assert main._cart(ctx) is None
    assert q.answer.call_args.kwargs.get("show_alert") is True


def test_cart_add_other_shop_prompts_and_keeps_cart(env):
    s2 = env.db.create_user(telegram_id=3003, phone_number="998905556677",
                            name="S2", role="seller")
    p2 = env.db.create_product(seller_id=s2, name="Boshqa", price=1000, stock_count=5)
    ctx = make_context()
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{env.product}"), 2002), ctx))
    # Boshqa do'kon mahsuloti — tasdiq so'raydi, savatni o'zgartirmaydi
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{p2}"), 2002), ctx))
    assert ctx.bot.send_message.await_count == 1
    cart = main._cart(ctx)
    assert cart["seller_id"] == env.seller
    assert str(p2) not in cart["items"]


# ========================== cart_reset_add ==========================
def test_cart_reset_add_switches_shop(env):
    s2 = env.db.create_user(telegram_id=3003, phone_number="998905556677",
                            name="S2", role="seller")
    p2 = env.db.create_product(seller_id=s2, name="Boshqa", price=1000, stock_count=5)
    ctx = make_context()
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{env.product}"), 2002), ctx))
    q = FakeQuery(f"cart_reset_add_{p2}")
    run(main.cart_reset_add(make_update(q, 2002), ctx))
    cart = main._cart(ctx)
    assert cart["seller_id"] == s2
    assert str(p2) in cart["items"]
    assert str(env.product) not in cart["items"]
    assert q.edit_message_text.await_count == 1


# ========================== cart_inc / cart_dec ==========================
def test_cart_inc_and_dec_flow(env):
    ctx = make_context()
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{env.product}"), 2002), ctx))
    assert main._cart_count(ctx) == 1
    run(main.cart_inc(make_update(FakeQuery(f"cart_inc_{env.product}"), 2002), ctx))
    assert main._cart_count(ctx) == 2
    run(main.cart_dec(make_update(FakeQuery(f"cart_dec_{env.product}"), 2002), ctx))
    assert main._cart_count(ctx) == 1
    run(main.cart_dec(make_update(FakeQuery(f"cart_dec_{env.product}"), 2002), ctx))
    assert main._cart_count(ctx) == 0  # oxirgi ➖ savatdan o'chiradi


def test_cart_inc_respects_stock_cap(env):
    p1 = env.db.create_product(seller_id=env.seller, name="Yagona", price=2000, stock_count=1)
    ctx = make_context()
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{p1}"), 2002), ctx))
    assert main._cart_count(ctx) == 1
    q = FakeQuery(f"cart_inc_{p1}")
    run(main.cart_inc(make_update(q, 2002), ctx))
    # Zahira 1 ta — ko'paymaydi, ogohlantirish chiqadi
    assert main._cart_count(ctx) == 1
    assert q.answer.call_args.kwargs.get("show_alert") is True


# ============================ cart_view ============================
def test_cart_view_empty(env):
    q = FakeQuery("cart_view")
    ctx = make_context()
    run(main.cart_view(make_update(q, 2002), ctx))
    # Bo'sh savat — edit_message_text chaqiriladi (xabar almashtiriladi)
    assert q.edit_message_text.await_count == 1


def test_cart_view_with_items_shows_total(env):
    ctx = make_context()
    run(main.cart_add(make_update(FakeQuery(f"cart_add_{env.product}"), 2002), ctx))
    run(main.cart_inc(make_update(FakeQuery(f"cart_inc_{env.product}"), 2002), ctx))
    q = FakeQuery("cart_view")
    run(main.cart_view(make_update(q, 2002), ctx))
    assert q.edit_message_text.await_count == 1
    # Yuborilgan matn 2 dona × 45000 = 90000 summasini hisobga oladi
    assert main._cart_total(ctx) == 90000


# ==================== ADMIN yangi buyurtma bildirishnomasi ====================
def test_admin_notified_on_new_order(env, monkeypatch):
    """Yangi buyurtmada ADMIN ham Telegram push olsin. `_dispatch_order_notification`
    bot va Mini App uchun YAGONA o'tish nuqtasi — admin xabari shu yerda, BIR marta.
    Og'ir yordamchilar (sotuvchi push'i, xodim fan-out) mock'lanadi, faqat admin
    yo'nalishini tekshiramiz (ADMIN_ID=1, test boshida o'rnatilgan)."""
    db = env.db
    oid = db.create_order(buyer_id=env.buyer, seller_id=env.seller,
                          product_id=env.product, quantity=2, total_price=90000,
                          payment_method="cash", delivery_type="pickup")
    monkeypatch.setattr(main, "_send_order_notification", AsyncMock(return_value=(1, False)))
    monkeypatch.setattr(main, "_fanout_order_to_staff", AsyncMock())
    ctx = types.SimpleNamespace(
        bot=types.SimpleNamespace(send_message=AsyncMock(), send_location=AsyncMock()),
        application=types.SimpleNamespace(job_queue=None),
    )
    run(main._dispatch_order_notification(ctx, oid))
    calls = ctx.bot.send_message.await_args_list
    assert any(c.kwargs.get("chat_id") == 1 and "Yangi buyurtma" in (c.kwargs.get("text") or "")
               for c in calls), "Adminga (chat_id=1) yangi buyurtma push'i ketmadi"


# ==================== KANAL POSTI: video bilan / videosiz ====================
def _channel_bot():
    """post_product_to_channel uchun fake bot (hamma send_* chaqiruvlarni yozadi)."""
    return types.SimpleNamespace(
        get_me=AsyncMock(return_value=types.SimpleNamespace(username="TestBot")),
        send_video=AsyncMock(return_value=types.SimpleNamespace(message_id=11)),
        send_photo=AsyncMock(return_value=types.SimpleNamespace(message_id=12, photo=[])),
        send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=13)),
    )


def test_channel_post_uses_video_when_present(env, monkeypatch):
    """Mahsulotda video bo'lsa kanal posti VIDEO + caption + tugma bilan chiqadi
    (rasm yuborilmaydi, dizayn ham yasalmaydi)."""
    env.db.update_product_fields(env.product, video_file_id="VID_chan")
    monkeypatch.setattr(main, "CHANNEL_ID", "@testchan")
    monkeypatch.setattr(main, "_build_ad_caption", AsyncMock(return_value=("Reklama matni", None)))
    design_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(main, "_build_ad_design_bytes", design_mock)
    bot = _channel_bot()
    run(main.post_product_to_channel(types.SimpleNamespace(bot=bot), env.product))
    assert bot.send_video.await_count == 1, "video posti ketishi shart"
    kw = bot.send_video.await_args.kwargs
    assert kw["video"] == "VID_chan" and kw["caption"] == "Reklama matni"
    assert kw["reply_markup"] is not None, "Sotib olish tugmasi bo'lishi shart"
    assert bot.send_photo.await_count == 0
    assert design_mock.await_count == 0, "video borida dizayn yasalmasin (CPU tejash)"


def test_channel_post_photo_flow_when_no_video(env, monkeypatch):
    """Videosiz mahsulot — eski oqim (rasm/dizayn), send_video chaqirilmaydi."""
    monkeypatch.setattr(main, "CHANNEL_ID", "@testchan")
    monkeypatch.setattr(main, "_build_ad_caption", AsyncMock(return_value=("Matn", None)))
    monkeypatch.setattr(main, "_build_ad_design_bytes", AsyncMock(return_value=None))
    bot = _channel_bot()
    run(main.post_product_to_channel(types.SimpleNamespace(bot=bot), env.product))
    assert bot.send_video.await_count == 0
    # fixture mahsulotida rasm yo'q -> matnli post; rasmli bo'lsa send_photo bo'lardi
    assert bot.send_message.await_count + bot.send_photo.await_count >= 1
