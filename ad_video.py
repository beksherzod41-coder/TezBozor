"""TezBozor — 🎬 AI video-reklama (reels-uslub klip) generatori.

Mahsulot rasm(lar)i + qisqa AI "hook" matnidan 10–14 soniyalik VERTIKAL (9:16)
reklama klipi yasaydi. Tashqi pullik video-API YO'Q — hammasi serverda:
  • Pillow — har kadr brend-uslubda (ad_design bilan bir xil ko'rinish):
    xira (blur) fon, yumaloq burchakli mahsulot rasmi, pastki gradient,
    NARX (yirik) + yashil CTA pill + optom belgisi
  • ffmpeg — Ken Burns (sekin zoom kirish/chiqish) + silliq krossfeyd +
    H.264 mp4 (faststart — Telegram'da darhol oqadi)

Klip tuzilishi: [HOOK kadri] → [mahsulot kadr(lar)i] (3 tagacha rasm).
Bitta rasm bo'lsa ham 2 xil harakat bilan 2 segment chiqadi.

MUHIM: modul HECH QACHON istisno tashlamaydi — har qanday xatoda None
qaytaradi (chaqiruvchi rasmli reklamaga qaytadi). ffmpeg topilmasa
is_enabled() False. Rasm ustida emoji ishlatilmaydi (ad_design bilan bir
qoida — PIL rangli emojini chiza olmaydi), emoji caption matnida qoladi.
"""

import io
import logging
import os
import shutil
import subprocess
import tempfile
import unicodedata

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# ad_design bilan BIR XIL brend ko'rinish — shrift/rang/gradient yordamchilari
try:
    from ad_design import (_load_font, _fit_font, _rounded, _norm_spaces,
                           _contain, _rounded_mask, _bottom_gradient,
                           ACCENT, CTA_BG, CTA_INK, PILL_BG, INK, INK_SOFT,
                           OPTOM_DOT)
    _DESIGN_OK = True
except Exception:
    _DESIGN_OK = False

# Chiqish parametrlari — 720x1280 (9:16): sifat/CPU muvozanati (1 yadroli VPS
# ham ~15-30 soniyada renderlaydi). Kadrlar 1.3x katta chiziladi — zoompan
# zoom paytida sifat yo'qolmasin.
OUT_W, OUT_H = 720, 1280
FPS = 24
SEG_DUR = 3.0        # har segment (soniya)
XFADE = 0.6          # krossfeyd (soniya)
OVERSAMPLE = 1.3
FFMPEG_TIMEOUT = 240

_MUSIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "ad_music.mp3")


def is_enabled() -> bool:
    """ffmpeg + Pillow + ad_design yordamchilari mavjudmi."""
    return _PIL_OK and _DESIGN_OK and shutil.which("ffmpeg") is not None


def probe_has_audio(path) -> bool:
    """Faylda haqiqiy audio oqim bormi (ffprobe). Sotuvchi yuklagan musiqani
    tekshirish uchun — buzuq/yolg'on fayl klip renderini yiqitmasin."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, timeout=20)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def strip_emoji(s: str) -> str:
    """Rasm ustiga chiqadigan matndan emoji/symbol belgilarini olib tashlaydi
    (PIL ularni chiza olmaydi — □ bo'lib qolardi)."""
    out = []
    for ch in (s or ""):
        if ord(ch) > 0xFFFF or unicodedata.category(ch) in ("So", "Sk", "Cs"):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def _cover(img, w, h):
    """Rasmni w×h maydonni to'ldirib kesadi (cover)."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = max(w, int(iw * scale)), max(h, int(ih * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap_lines(draw, text, font, max_w, max_lines=3):
    """So'z bo'yicha o'rash — har qator max_w dan oshmaydi."""
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), cand, font=font)
        if bbox[2] - bbox[0] <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def _pill_at(canvas, draw, text, *, top, right, W, size, dot=None):
    """Muzli pill — istalgan kenglikdagi kanvas uchun (ad_design._pill vertikal
    kanvasda ishlamaydi — u kvadrat CANVAS o'lchamiga bog'langan)."""
    font = _fit_font(draw, text, True, int(W * 0.8), size, min_size=18)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 22, 13
    dot_w = (th + 12) if dot else 0
    w, h = tw + pad_x * 2 + dot_w, th + pad_y * 2
    x0 = W - right - w
    _rounded(draw, [x0, top, x0 + w, top + h], h // 2, PILL_BG)
    tx = x0 + pad_x
    if dot:
        r = th // 2 - 1
        cy = top + h // 2
        draw.ellipse([tx, cy - r, tx + r * 2, cy + r], fill=dot)
        tx += dot_w
    draw.text((tx, top + pad_y - bbox[1]), text, font=font, fill=INK)


def _cta_at(canvas, draw, text, *, bottom, right, W, H, size):
    """Yashil CTA pill — pastki o'ng (vertikal kanvas versiyasi)."""
    font = _fit_font(draw, text, True, int(W * 0.6), size, min_size=20)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 26, 16
    w, h = tw + pad_x * 2, th + pad_y * 2
    x0, y0 = W - right - w, bottom - h
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    _rounded(sd, [x0, y0 + 6, x0 + w, y0 + h + 10], h // 2, (10, 60, 30, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas.alpha_composite(shadow)
    _rounded(draw, [x0, y0, x0 + w, y0 + h], h // 2, CTA_BG)
    draw.text((x0 + pad_x, y0 + pad_y - bbox[1]), text, font=font, fill=CTA_INK)
    return [x0, y0, x0 + w, y0 + h]


def _frame_base(src, W, H, *, blur=28, darken=0.38):
    """Umumiy fon: xira cover + qoraytirish."""
    bg = _cover(src, W, H).filter(ImageFilter.GaussianBlur(blur))
    dark = Image.new("RGB", (W, H), (10, 12, 16))
    return Image.blend(bg, dark, darken).convert("RGBA")


def _frame_hook(src, W, H, *, hook_text, brand_text=""):
    """1-kadr: katta HOOK matni (diqqatni tortadi), ostida kichik brend."""
    canvas = _frame_base(src, W, H, blur=40, darken=0.62)
    draw = ImageDraw.Draw(canvas, "RGBA")
    hook = strip_emoji(_norm_spaces(hook_text or "")).upper()
    max_w = int(W * 0.84)
    size = int(W * 0.115)
    font = _load_font(True, size)
    lines = _wrap_lines(draw, hook, font, max_w)

    def _widest(lns, f):
        return max((draw.textbbox((0, 0), ln, font=f)[2] for ln in lns), default=0)

    # 3 qatordan oshsa YOKI bitta uzun so'z max_w dan chiqsa — shriftni kichraytiramiz
    # (word-wrap yagona uzun so'zni bo'lolmaydi, kadr chetiga tegib qolardi)
    while (len(lines) > 3 or _widest(lines, font) > max_w) and size > int(W * 0.055):
        size = int(size * 0.9)
        font = _load_font(True, size)
        lines = _wrap_lines(draw, hook, font, max_w)
    line_h = int(size * 1.22)
    total_h = line_h * len(lines)
    y = (H - total_h) // 2 - int(H * 0.02)
    # kichik urg'u chizig'i — matn tepasida (brend rangi)
    _rounded(draw, [(W - 84) // 2, y - 34, (W + 84) // 2, y - 26], 4, ACCENT)
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        lw = bbox[2] - bbox[0]
        draw.text(((W - lw) // 2 - bbox[0], y - bbox[1]), ln, font=font, fill=INK)
        y += line_h
    bt = strip_emoji(_norm_spaces(brand_text or "")).upper()
    if bt:
        bfont = _fit_font(draw, bt, False, int(W * 0.6), int(W * 0.042), min_size=16)
        bbox = draw.textbbox((0, 0), bt, font=bfont)
        bw = bbox[2] - bbox[0]
        draw.text(((W - bw) // 2 - bbox[0], y + 18 - bbox[1]), bt, font=bfont,
                  fill=INK_SOFT)
    return canvas.convert("RGB")


def _frame_product(src, W, H, *, price_text="", shop_text="", cta_text="",
                   optom_text=""):
    """Mahsulot kadri — ad_design bilan bir uslub, vertikal (9:16) joylashuv."""
    canvas = _frame_base(src, W, H)
    # mahsulot rasmi — yumaloq burchak + soya, markazdan biroz tepada
    fg = _contain(src, int(W * 0.88))
    if fg.height > int(H * 0.60):
        fg = _contain(src, int(H * 0.60))
    fx = (W - fg.width) // 2
    fy = max(int(H * 0.09), int(H * 0.40) - fg.height // 2)
    radius = 30
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    _rounded(sd, [fx - 4, fy + 8, fx + fg.width + 4, fy + fg.height + 18],
             radius + 6, (0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(shadow)
    canvas.paste(fg, (fx, fy), _rounded_mask(fg.size, radius))

    grad_h = int(H * 0.30)
    canvas.alpha_composite(_bottom_gradient(W, grad_h), (0, H - grad_h))
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = int(W * 0.055)

    cta_box = None
    ct = strip_emoji(_norm_spaces(cta_text or "")).strip().upper()[:20]
    if ct:
        cta_box = _cta_at(canvas, draw, ct, bottom=H - margin, right=margin,
                          W=W, H=H, size=int(W * 0.045))

    y_cursor = H - margin
    price_max_w = int(W * 0.72)
    if cta_box is not None:
        price_max_w = min(price_max_w, max(int(W * 0.34), cta_box[0] - margin - 20))
    pt = strip_emoji(_norm_spaces(price_text or "")).strip()
    if pt:
        pfont = _fit_font(draw, pt, True, price_max_w, int(W * 0.105), min_size=30)
        pbbox = draw.textbbox((0, 0), pt, font=pfont)
        ph = pbbox[3] - pbbox[1]
        y_cursor -= ph
        draw.text((margin, y_cursor - pbbox[1]), pt, font=pfont, fill=INK)
        y_cursor -= 16
    st = strip_emoji(_norm_spaces(shop_text or "")).strip().upper()
    if st:
        sfont = _fit_font(draw, st, False, int(W * 0.6), int(W * 0.038), min_size=17)
        sbbox = draw.textbbox((0, 0), st, font=sfont)
        sh = sbbox[3] - sbbox[1]
        y_cursor -= sh
        draw.text((margin, y_cursor - sbbox[1]), st, font=sfont, fill=INK_SOFT)
        y_cursor -= 14
    if pt or st:
        _rounded(draw, [margin, y_cursor - 7, margin + 72, y_cursor], 4, ACCENT)

    ot = strip_emoji(_norm_spaces(optom_text or "")).strip().upper()[:30]
    if ot:
        _pill_at(canvas, draw, ot, top=margin, right=margin, W=W,
                 size=int(W * 0.036), dot=OPTOM_DOT)
    return canvas.convert("RGB")


def _zoom_expr(idx, seg_frames):
    """Ken Burns: juft segment — sekin zoom-in, toq — zoom-out. Har kadr uchun
    zoom qiymati 'on' (chiqish kadri raqami) dan hisoblanadi — silliq harakat."""
    rate = 0.12 / max(1, seg_frames)
    if idx % 2 == 0:
        return f"min(1.0+{rate:.6f}*on,1.12)"
    return f"max(1.12-{rate:.6f}*on,1.0)"


def build_ad_clip(images, *, hook_text="", price_text="", shop_text="",
                  cta_text="SOTIB OLISH", optom_text="", brand_text="",
                  out_w=OUT_W, out_h=OUT_H, fps=FPS, seg_dur=SEG_DUR,
                  xfade=XFADE, music_path=None, timeout=FFMPEG_TIMEOUT):
    """Reels-uslub reklama klipi yasaydi va MP4 bytes qaytaradi. Xatoda None.

    images — mahsulot rasmlari (bytes ro'yxati, 1..3 ishlatiladi).
    Qolgan matnlar rasm USTIGA chiziladi (emojisiz), shuning uchun qisqa bo'lsin.
    music_path — fon musiqa boshqaruvi:
      None (standart) — assets/ad_music.mp3 bo'lsa avtomatik qo'shiladi;
      ""              — musiqa ATAYLAB o'chirilgan (sotuvchi tanlovi);
      yo'l            — aynan shu mp3 ishlatiladi.
    """
    if not is_enabled() or not images:
        return None
    try:
        srcs = []
        for b in images[:3]:
            try:
                srcs.append(Image.open(io.BytesIO(b)).convert("RGB"))
            except Exception:
                continue
        if not srcs:
            return None

        # Kadrlar zoompan uchun 1.3x katta chiziladi (zoom sifat yo'qotmasin)
        rw, rh = int(out_w * OVERSAMPLE) // 2 * 2, int(out_h * OVERSAMPLE) // 2 * 2
        frames = []
        if (hook_text or "").strip():
            frames.append(_frame_hook(srcs[0], rw, rh, hook_text=hook_text,
                                      brand_text=brand_text))
        kw = dict(price_text=price_text, shop_text=shop_text,
                  cta_text=cta_text, optom_text=optom_text)
        for s in srcs:
            frames.append(_frame_product(s, rw, rh, **kw))
        if len(srcs) == 1:
            # bitta rasm — o'sha kadr 2-marta, boshqa harakat bilan (klip quruq
            # bo'lib qolmasin)
            frames.append(_frame_product(srcs[0], rw, rh, **kw))
        if not frames:
            return None

        if music_path is None and os.path.exists(_MUSIC_PATH):
            music_path = _MUSIC_PATH

        tmp = tempfile.mkdtemp(prefix="adclip_")
        try:
            paths = []
            for i, fr in enumerate(frames):
                p = os.path.join(tmp, f"f{i}.png")
                fr.save(p, format="PNG")
                paths.append(p)

            n = len(paths)
            seg_frames = int(seg_dur * fps)
            total = n * seg_dur - (n - 1) * xfade

            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            for p in paths:
                cmd += ["-loop", "1", "-framerate", str(fps), "-t",
                        f"{seg_dur:.3f}", "-i", p]
            has_music = bool(music_path and os.path.exists(music_path))
            if has_music:
                cmd += ["-i", music_path]

            filt = []
            for i in range(n):
                filt.append(
                    f"[{i}:v]zoompan=z='{_zoom_expr(i, seg_frames)}'"
                    f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":d=1:s={out_w}x{out_h}:fps={fps}[v{i}]")
            if n == 1:
                filt.append(f"[v0]format=yuv420p[vout]")
            else:
                prev = "v0"
                length = seg_dur
                for i in range(1, n):
                    nxt = "vout" if i == n - 1 else f"x{i}"
                    off = length - xfade
                    filt.append(f"[{prev}][v{i}]xfade=transition=fade"
                                f":duration={xfade:.3f}:offset={off:.3f}[{nxt}]")
                    length = off + seg_dur
                    prev = nxt
                filt.append("[vout]format=yuv420p[vfin]")
            vmap = "[vfin]" if n > 1 else "[vout]"
            cmd += ["-filter_complex", ";".join(filt), "-map", vmap]
            if has_music:
                fade_st = max(0.0, total - 1.2)
                cmd += ["-map", f"{n}:a",
                        "-af", f"afade=t=out:st={fade_st:.2f}:d=1.2",
                        "-c:a", "aac", "-b:a", "128k", "-shortest"]
            else:
                cmd += ["-an"]
            out_path = os.path.join(tmp, "out.mp4")
            cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset",
                    "veryfast", "-crf", "26", "-movflags", "+faststart",
                    out_path]

            res = subprocess.run(cmd, capture_output=True, timeout=timeout)
            if res.returncode != 0 or not os.path.exists(out_path):
                log.warning("ffmpeg xato (%s): %s", res.returncode,
                            (res.stderr or b"")[-500:].decode("utf-8", "ignore"))
                return None
            with open(out_path, "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        log.warning(f"Video-reklama yasashda xato: {e}")
        return None
