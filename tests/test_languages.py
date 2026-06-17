"""Tarjima lug'ati uchun testlar — har bir kalit uz va ru tillarida bo'lishi shart."""
import languages as L


def test_every_key_has_uz_and_ru():
    missing = []
    for key, entry in L._TEXTS.items():
        if not isinstance(entry, dict):
            continue
        for lang in ("uz", "ru"):
            if lang not in entry:
                missing.append(f"{key}:{lang}")
    assert not missing, f"Yetishmayotgan tarjimalar: {missing}"


def test_t_returns_key_when_missing():
    assert L.t("uz", "___mavjud_emas___") == "___mavjud_emas___"


def test_t_formats_kwargs():
    out = L.t("uz", "countdown_line", mins=9, until="14:30")
    assert "9" in out and "14:30" in out


def test_t_survives_missing_kwarg():
    # Yetishmayotgan o'zgaruvchi bo'lsa ham yiqilmaydi (kalit nomi qaytmaydi)
    out = L.t("uz", "countdown_line")
    assert isinstance(out, str)


def test_new_feature_keys_exist():
    new_keys = [
        "countdown_sep", "badge_in_progress", "badge_awaiting_settlement",
        "row_progress_tag", "orders_title_inprogress", "pickup_received_buyer",
        "pickup_seller_finalize", "pickup_seller_finalize_group",
        "btn_finalize_payment", "buyer_awaiting_finalize",
    ]
    for k in new_keys:
        assert L.t("uz", k) != k, f"Kalit topilmadi: {k}"
        assert L.t("ru", k) != k, f"Kalit topilmadi (ru): {k}"
