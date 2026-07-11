"""TezBozor — mahsulot rasmidan reklama dizayni yasaydi (Pillow).

Zamonaviy, minimal uslub (qo'pol qizil qutilar YO'Q):
  • kvadrat (1080x1080) format, fonida xira (blur) qilingan rasm
  • markazda mahsulot rasmi — yumaloq burchak + yumshoq soya (premium ko'rinish)
  • pastda silliq qora gradient — rasmni to'smaydi, matnni o'qiladigan qiladi
  • gradient ustida: kichik urg'u chizig'i, do'kon nomi (kichik, shaffof oq),
    NARX (yirik, toza oq) — reklamadagi asosiy xabar
  • optom belgisi — yuqori o'ngda muzli (yarim shaffof) pill, yashil nuqta bilan
  • ortiqcha yozuv yo'q: rasm asosiy qahramon bo'lib qoladi

MUHIM: bu modul HECH QACHON istisno tashlamaydi — har qanday xato yoki Pillow
yo'qligida None qaytaradi, chaqiruvchi asl rasmga qaytadi. Telegram'da PIL rangli
emoji'ni ishonchli chiza olmaydi, shuning uchun rasm ustida emoji ishlatilmaydi
(emojilar reklama matni/caption ichida qoladi).
"""

import io
import logging
import unicodedata

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    _PIL_OK = True
except Exception:  # Pillow o'rnatilmagan
    _PIL_OK = False

CANVAS = 1080                 # reklama kvadrati o'lchami (px)
ACCENT = (255, 96, 64)        # urg'u rangi — iliq marjon (faqat kichik detallar uchun)
OPTOM_DOT = (52, 211, 122)    # optom pill ichidagi yashil nuqta
PILL_BG = (12, 14, 18, 165)   # muzli (frosted) pill foni — yarim shaffof to'q
INK = (255, 255, 255)         # asosiy matn — toza oq
INK_SOFT = (255, 255, 255, 210)  # ikkilamchi matn — yumshoq oq

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

def _norm_spaces(s):
    """Barcha bo'shliq va ko'rinmas belgilarni ODDIY bo'shliqqa aylantiradi.

    fmt_price minglarni U+00A0 (uzilmas bo'shliq) bilan ajratadi; ba'zi shriftlarda
    (ayniqsa server fallback shriftida) bunday belgilar .notdef glifi (□) bo'lib
    chiqadi — narx "4 500" o'rniga "4□500" ko'rinardi. Belgilarni sanab chiqish
    o'rniga umumiy qoida: har qanday whitespace (isspace) + Zs (bo'shliqlar) +
    Cf (ko'rinmas format belgilari: ZWSP, WJ, BOM...) → " "."""
    out = []
    for ch in (s or ""):
        if ch.isspace() or unicodedata.category(ch) in ("Zs", "Cf"):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


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


def _rounded_mask(size, radius):
    """Yumaloq burchakli oq maska (L rejim) — rasmni chiroyli joylash uchun."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    try:
        d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    except Exception:
        d.rectangle([0, 0, size[0] - 1, size[1] - 1], fill=255)
    return m


def _bottom_gradient(width, height, max_alpha=232):
    """Pastga qarab quyuqlashuvchi silliq qora gradient (RGBA)."""
    grad = Image.new("L", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        grad.putpixel((0, y), int(max_alpha * (t ** 1.35)))
    grad = grad.resize((width, height))
    layer = Image.new("RGBA", (width, height), (7, 9, 13, 255))
    layer.putalpha(grad)
    return layer


def _pill(canvas, draw, text, *, top, right=None, left=None, size=34, dot=None):
    """Muzli (yarim shaffof to'q) pill — burchak belgilari uchun. Matn oq, KICHIK."""
    font = _fit_font(draw, text, True, int(CANVAS * 0.6), size, min_size=22)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 30, 18
    dot_w = (th + 14) if dot else 0
    w = tw + pad_x * 2 + dot_w
    h = th + pad_y * 2
    x0 = (CANVAS - right - w) if right is not None else (left or 0)
    box = [x0, top, x0 + w, top + h]
    _rounded(draw, box, h // 2, PILL_BG)
    tx = x0 + pad_x
    if dot:
        r = th // 2 - 1
        cy = top + h // 2
        draw.ellipse([tx, cy - r, tx + r * 2, cy + r], fill=dot)
        tx += dot_w
    draw.text((tx, top + pad_y - bbox[1]), text, font=font, fill=INK)
    return box


def build_ad_image(image_bytes, *, price_text="", badge_text="", shop_text="", optom_text=""):
    """Reklama rasmini yasaydi va JPEG bytes qaytaradi. Xato bo'lsa — None.

    image_bytes — Telegram'dan yuklab olingan mahsulot rasmi (bytes).
    price_text  — masalan "250 000 so'm" (emojisiz).
    badge_text  — ixtiyoriy qisqa belgi (emojisiz); bo'sh bo'lsa chizilmaydi.
    shop_text   — do'kon nomi (emojisiz).
    optom_text  — optom belgisi matni (masalan "OPTOM · 1 PACHKA = 6 DONA");
                  bo'sh bo'lsa chizilmaydi. Yuqori O'NG burchakda pill.
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

        # 1) Fon — kuchli xira, yengil qoraytirilgan cover
        bg = _cover_to_square(src, CANVAS).filter(ImageFilter.GaussianBlur(30))
        dark = Image.new("RGB", (CANVAS, CANVAS), (10, 12, 16))
        canvas = Image.blend(bg, dark, 0.38).convert("RGBA")

        # 2) Mahsulot — yumaloq burchak + yumshoq soya, biroz tepaga surilgan
        #    (pastdagi gradient/matn rasmga tegmasligi uchun)
        fg = _contain(src, int(CANVAS * 0.86))
        fx = (CANVAS - fg.width) // 2
        fy = max(40, (CANVAS - fg.height) // 2 - int(CANVAS * 0.045))
        radius = 36
        shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        _rounded(sd, [fx - 4, fy + 10, fx + fg.width + 4, fy + fg.height + 22], radius + 6, (0, 0, 0, 130))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas.alpha_composite(shadow)
        canvas.paste(fg, (fx, fy), _rounded_mask(fg.size, radius))

        # 3) Pastki gradient — matn zonasi (rasmni qoplamaydi, silliq quyuqlashadi)
        grad_h = int(CANVAS * 0.36)
        canvas.alpha_composite(_bottom_gradient(CANVAS, grad_h), (0, CANVAS - grad_h))

        draw = ImageDraw.Draw(canvas, "RGBA")
        margin = 56

        # 4) Matn bloki — pastki chap: urg'u chizig'i → do'kon nomi → NARX
        y_cursor = CANVAS - margin
        pt = (price_text or "").strip()
        if pt:
            pfont = _fit_font(draw, pt, True, int(CANVAS * 0.72), 104, min_size=44)
            pbbox = draw.textbbox((0, 0), pt, font=pfont)
            ph = pbbox[3] - pbbox[1]
            y_cursor -= ph
            draw.text((margin, y_cursor - pbbox[1]), pt, font=pfont, fill=INK)
            y_cursor -= 22

        st = (shop_text or "").strip().upper()
        if st:
            sfont = _fit_font(draw, st, False, int(CANVAS * 0.6), 36, min_size=24)
            sbbox = draw.textbbox((0, 0), st, font=sfont)
            sh = sbbox[3] - sbbox[1]
            y_cursor -= sh
            draw.text((margin, y_cursor - sbbox[1]), st, font=sfont, fill=INK_SOFT)
            y_cursor -= 20

        # kichik urg'u chizig'i — brend rangi shu yerda, xolos (katta qizil qutilar yo'q)
        if pt or st:
            _rounded(draw, [margin, y_cursor - 8, margin + 88, y_cursor], 4, ACCENT)

        # 5) Optom pill — yuqori O'NG (muzli, yashil nuqta bilan)
        ot = (optom_text or "").strip().upper()[:30]
        if ot:
            _pill(canvas, draw, ot, top=margin - 8, right=margin - 8, size=34, dot=OPTOM_DOT)

        # 6) Ixtiyoriy badge — yuqori CHAP (faqat berilsa; odatda berilmaydi)
        bt = (badge_text or "").strip().upper()[:16]
        if bt:
            _pill(canvas, draw, bt, top=margin - 8, left=margin - 8, size=34)

        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
        out.seek(0)
        return out.getvalue()
    except Exception as e:
        log.warning(f"Reklama dizaynini yasashda xato: {e}")
        return None
