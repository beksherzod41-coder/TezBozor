"""tezbozor_design formatlash yordamchilari uchun testlar (Telegram'siz, toza)."""
from tezbozor_design import (fmt_price, fmt_phone, fmt_order_id, fmt_status,
                             human_address, looks_like_coords)


def test_fmt_price_groups_thousands():
    out = fmt_price(45000)
    assert out.endswith("so'm")
    # Mingliklar ajratuvchi (uzilmas bo'sh joy) bilan
    assert "45" in out and "000" in out


def test_fmt_price_handles_bad_input():
    # Xato kirsa ham yiqilmaydi
    assert "so'm" in fmt_price("xato")


def test_fmt_phone_uzbek_full():
    assert fmt_phone("998901234567") == "+998 90 123 45 67"


def test_fmt_phone_empty():
    assert fmt_phone("") == "Kiritilmagan"


def test_fmt_order_id_padded():
    assert fmt_order_id(48201) == "#TB-048201"


def test_fmt_status_known_and_unknown():
    assert "Yetkazildi" in fmt_status("delivered")
    assert fmt_status("nomalum") == "nomalum"


def test_looks_like_coords():
    assert looks_like_coords("41.31, 69.24") is True
    assert looks_like_coords("Chilonzor 5-kvartal") is False


def test_human_address_filters_raw_coords():
    assert human_address("41.31, 69.24") is None
    assert human_address("Chilonzor 5") == "Chilonzor 5"
    assert human_address("") is None
