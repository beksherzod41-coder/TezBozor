"""TezBozor — mahsulot rasmidan reklama dizayni yasaydi (Pillow).

Mahsulotning HAQIQIY rasmi ustiga professional reklama elementlari qo'shadi:
  • kvadrat (1080x1080) reklama formati, fonida xira (blur) qilingan rasm
  • markazda to'liq ko'rinadigan mahsulot rasmi
  • pastki chap burchakda yorqin NARX yorlig'i
  • yuqori chap burchakda BADGE (masalan "YANGI" / "ORIGINAL")
  • pastda do'kon nomi paneli
  • rangli ramka

MUHIM: bu modul HECH QACHON istisno tashlamaydi — har qanday xato yoki Pillow
yo'qligida None qaytaradi, chaqiruvchi asl rasmga qaytadi. Telegram'da PIL rangli
emoji'ni ishonchli chiza olmaydi, shuning uchun rasm ustida emoji ishlatilmaydi
(emojilar reklama matni/caption ichida qoladi).
"""

import io
import re
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    _PIL_OK = True
except Exception:  # Pillow o'rnatilmagan
    _PIL_OK = False

CANVAS = 1080                 # reklama kvadrati o'lchami (px)
ACCENT = (255, 71, 51)       # asosiy urg'u rangi (yorqin qizil-to'q sariq)
ACCENT_DARK = (200, 40, 25)
OPTOM_COLOR = (22, 163, 74)  # optom rozetkasi — yashil (ulgurji/tejam belgisi)

# Shrift nomzodlari — server (Linux/PythonAnywhere) va Windows dev uchun
_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\segoeuib.ttf",
]
_REG_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
]

# Maxsus (ko'rinmas) bo'shliqlar — ba'zi shriftlarda ular .notdef glifi (□ yoki '#')
# bo'lib chiqadi. fmt_price minglarni   (uzilmas bo'shliq) bilan ajratadi, shu
# sababli rasm ustida narx "11 000" emas "11#000" bo'lib ko'rinardi. Oddiy bo'shliqqa
# aylantiramiz — u har doim to'g'ri chiziladi.
_SPACE_RE = re.compile("[    ⁠﻿​]")


def _norm_spaces(s):
    return _SPACE_RE.sub(" ", s or "")


def is_enabled() -> bool:
    return _PIL_OK


def _load_font(bold: bool, size: int):
    """Mos shriftni topib yuklaydi. Topilmasa — Pillow standart shriftiga qaytadi."""
    candidates = _BOLD_CANDIDATES if bold else _REG_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)   # Pillow >= 10
    except Exception:
        return ImageFont.load_default()


def _text_w(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_font(draw, text, bold, max_w, start_size, min_size=18):
    """Matn max_w ga sig'guncha shrift o'lchamini kichraytiradi."""
    size = start_size
    while size > min_size:
        font = _load_font(bold, size)
        if _text_w(draw, text, font) <= max_w:
            return font
        size -= 2
    return _load_font(bold, min_size)


def _rounded(draw, box, radius, fill):
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    except Exception:
        draw.rectangle(box, fill=fill)


def _cover_to_square(img, size):
    """Rasmni kvadratga to'ldirib kesadi (cover)."""
    w, h = img.size
    scale = size / min(w, h)
    nw, nh = max(size, int(w * scale)), max(size, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - size) // 2
    top = (nh - size) // 2
    return img.crop((left, top, left + size, top + size))


def _contain(img, size):
    """Rasmni kvadrat ichiga to'liq sig'diradi (contain)."""
    w, h = img.size
    scale = min(size / w, size / h)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def build_ad_image(image_bytes, *, price_text="", badge_text="", shop_text="", optom_text=""):
    """Reklama rasmini yasaydi va JPEG bytes qaytaradi. Xato bo'lsa — None.

    image_bytes — Telegram'dan yuklab olingan mahsulot rasmi (bytes).
    price_text  — masalan "250 000 so'm" (emojisiz).
    badge_text  — masalan "YANGI" yoki "ORIGINAL" (emojisiz, qisqa).
    shop_text   — do'kon nomi (emojisiz).
    optom_text  — optom rozetkasi matni (masalan "OPTOM · 1 PACHKA = 6 DONA");
                  bo'sh bo'lsa rozetka chizilmaydi. Yuqori O'NG burchakda, yashil.
    """
    if not _PIL_OK or not image_bytes:
        return None
    # Ko'rinmas bo'shliqlarni oddiy bo'shliqqa aylantiramiz (narx "11#000" bug'i)
    price_text = _norm_spaces(price_text)
    badge_text = _norm_spaces(badge_text)
    shop_text = _norm_spaces(shop_text)
    optom_text = _norm_spaces(optom_text)
    try:
        src = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # 1) Fon — xira, qoraytirilgan cover; ustiga markazga contain mahsulot
        bg = _cover_to_square(src, CANVAS).filter(ImageFilter.GaussianBlur(24))
        dark = Image.new("RGB", (CANVAS, CANVAS), (0, 0, 0))
        bg = Image.blend(bg, dark, 0.35)

        fg = _contain(src, int(CANVAS * 0.92))
        canvas = bg.copy()
        canvas.paste(fg, ((CANVAS - fg.width) // 2, (CANVAS - fg.height) // 2))

        draw = ImageDraw.Draw(canvas, "RGBA")

        # 2) Rangli ramka — OLIB TASHLANDI (rasm ustiga qizil ramka qo'yilmaydi)

        margin = 46

        # 3) Badge — yuqori chap burchak (qisqa matn)
        bt = (badge_text or "").strip().upper()[:16]
        if bt:
            bfont = _fit_font(draw, bt, True, int(CANVAS * 0.5), 52)
            pad_x, pad_y = 28, 16
            tw = _text_w(draw, bt, bfont)
            bx0, by0 = margin, margin
            bx1 = bx0 + tw + pad_x * 2
            by1 = by0 + 52 + pad_y
            _rounded(draw, [bx0, by0, bx1, by1], 18, ACCENT)
            draw.text((bx0 + pad_x, by0 + pad_y // 2), bt, font=bfont, fill=(255, 255, 255))

        # 3b) OPTOM rozetkasi — yuqori O'NG burchak (yashil; dona savdodan ajralib tursin)
        ot = (optom_text or "").strip().upper()[:30]
        if ot:
            ofont = _fit_font(draw, ot, True, int(CANVAS * 0.62), 46, min_size=26)
            pad_x, pad_y = 26, 15
            tw = _text_w(draw, ot, ofont)
            obbox = draw.textbbox((0, 0), ot, font=ofont)
            oh = obbox[3] - obbox[1]
            ox1 = CANVAS - margin
            oy0 = margin
            ox0 = ox1 - tw - pad_x * 2
            oy1 = oy0 + oh + pad_y * 2
            _rounded(draw, [ox0 + 5, oy0 + 7, ox1 + 5, oy1 + 7], 16, (0, 0, 0, 110))  # soya
            _rounded(draw, [ox0, oy0, ox1, oy1], 16, OPTOM_COLOR)
            draw.text((ox0 + pad_x, oy0 + pad_y - obbox[1]), ot, font=ofont, fill=(255, 255, 255))

        # 4) Narx yorlig'i — pastki chap burchak (eng yirik, urg'uli)
        pt = (price_text or "").strip()
        if pt:
            pfont = _fit_font(draw, pt, True, int(CANVAS * 0.72), 92, min_size=40)
            pad_x, pad_y = 38, 24
            tw = _text_w(draw, pt, pfont)
            bbox = draw.textbbox((0, 0), pt, font=pfont)
            th = bbox[3] - bbox[1]
            px0 = margin
            py1 = CANVAS - margin - 64           # do'kon paneli uchun joy qoldiramiz
            px1 = px0 + tw + pad_x * 2
            py0 = py1 - th - pad_y * 2
            # soya
            _rounded(draw, [px0 + 6, py0 + 8, px1 + 6, py1 + 8], 22, (0, 0, 0, 110))
            _rounded(draw, [px0, py0, px1, py1], 22, ACCENT)
            draw.text((px0 + pad_x, py0 + pad_y - bbox[1]), pt, font=pfont, fill=(255, 255, 255))

        # 5) Do'kon paneli — pastda, yarim shaffof qora chiziq
        st = (shop_text or "").strip()
        if st:
            sfont = _fit_font(draw, st, False, CANVAS - margin * 2 - 40, 40, min_size=22)
            bar_h = 64
            draw.rectangle([0, CANVAS - bar_h, CANVAS, CANVAS], fill=(0, 0, 0, 150))
            bbox = draw.textbbox((0, 0), st, font=sfont)
            th = bbox[3] - bbox[1]
            draw.text((margin, CANVAS - bar_h + (bar_h - th) // 2 - bbox[1]),
                      st, font=sfont, fill=(255, 255, 255))

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=88, optimize=True)
        out.seek(0)
        return out.getvalue()
    except Exception as e:
        log.warning(f"Reklama dizaynini yasashda xato: {e}")
        return None
