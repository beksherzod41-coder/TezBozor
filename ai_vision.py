"""TezBozor — Gemini MULTIMODAL qatlami (rasm, audio, rasm-generatsiya).

ai_assistant.py matnli AI (OpenAI-mos /chat/completions) bilan ishlaydi va
DeepSeek fallback'iga ega. Bu modul esa Gemini'ning NATIVE generateContent
API'sidan foydalanadi, chunki quyidagilar faqat native API'da bor:

  • inline rasm/audio yuborish (mahsulot rasmi, to'lov cheki, ovozli xabar)
  • rasm GENERATSIYASI (reklama banneri, gemini-2.5-flash-image)

DeepSeek'da vision/audio YO'Q — shuning uchun bu yerda fallback provayder yo'q;
har bir funksiya xatoda istisno TASHLAMAYDI, {"error": "..."} yoki None
qaytaradi, chaqiruvchi foydalanuvchiga tushunarli xabar ko'rsatadi.

Xato kodlari (error maydoni):
  quota    — 429 (bepul tarif tugadi / billing kerak)
  auth     — 401/403 (kalit noto'g'ri)
  timeout  — so'rov vaqti tugadi
  http     — boshqa HTTP xato
  disabled — GEMINI_API_KEY yo'q
  parse    — javobni o'qib bo'lmadi

.env:
  GEMINI_API_KEY        — majburiy (ai_assistant bilan bir xil kalit)
  GEMINI_MODEL          — matn/vision model (default gemini-flash-latest)
  GEMINI_IMAGE_MODEL    — rasm-generatsiya modeli (default gemini-2.5-flash-image;
                          billing talab qiladi — xato bo'lsa chaqiruvchi PIL
                          dizayniga (ad_design.py) qaytadi)
"""

import asyncio
import base64
import json
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

_KEY = os.getenv("GEMINI_API_KEY", "").strip()
_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest"
_IMAGE_MODEL = (os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
                or "gemini-2.5-flash-image")

# Vision/audio uchun MODEL ZANJIRI (fallback). DIQQAT: bu kalit YANGI proyekt —
# eski pinned modellar (gemini-2.5-flash, gemini-2.0-flash...) "no longer available
# to new users" (404) beradi; faqat "-latest" aliaslar ishlaydi. gemini-flash-latest
# (=gemini-3.5-flash) tez-tez 503 "high demand" beradi, gemini-flash-lite-latest esa
# ancha barqaror. Shuning uchun lite'ni BIRINCHI sinaymiz, 5xx/timeout bo'lsa to'liq
# flash'ga o'tamiz. GEMINI_VISION_MODEL env bilan birinchi modelni almashtirsa bo'ladi.
_VISION_MODEL = (os.getenv("GEMINI_VISION_MODEL", "gemini-flash-lite-latest").strip()
                 or "gemini-flash-lite-latest")
_MODEL_CHAIN = [_VISION_MODEL] + [m for m in (_MODEL,) if m and m != _VISION_MODEL]
_BASE = os.getenv("GEMINI_NATIVE_BASE_URL",
                  "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")

TIMEOUT = 75.0          # vision/audio so'rovlari matnga qaraganda og'irroq
IMAGE_TIMEOUT = 120.0   # rasm generatsiyasi eng og'ir amal
MAX_INLINE_BYTES = 18 * 1024 * 1024   # Gemini inline limiti ~20MB; zaxira bilan


def is_enabled() -> bool:
    """Multimodal AI ishlaydimi (Gemini kaliti bormi)."""
    return bool(_KEY)


def _inline_part(data: bytes, mime: str) -> dict:
    return {"inline_data": {"mime_type": mime,
                            "data": base64.b64encode(data).decode()}}


async def _generate(parts, *, system=None, model=None, max_tokens=1024,
                    temperature=0.2, json_mode=False, want_image=False,
                    timeout=TIMEOUT):
    """MARKAZIY generateContent chaqiruvi.

    Qaytaradi: {"text": str} yoki {"image": bytes, "image_mime": str}
    yoki {"error": "quota|auth|timeout|http|disabled|parse"}.
    Model aniq berilmasa (vision/audio) _MODEL_CHAIN bo'ylab fallback qiladi:
    har bir modelda 5xx'da backoff bilan qayta urinadi, davom etsa keyingi
    modelga o'tadi (gemini-flash-latest 503 bersa gemini-flash-lite-latest'ga).
    """
    if not _KEY:
        return {"error": "disabled"}
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if want_image:
        # Rasm modeli thinking/json qo'llamaydi; javob modalligini aniq so'raymiz
        payload["generationConfig"]["responseModalities"] = ["IMAGE", "TEXT"]
    else:
        # Fikrlash tokenlari max_tokens'ni yemasin (ai_assistant bilan paritet)
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    headers = {"x-goog-api-key": _KEY, "Content-Type": "application/json"}
    # Aniq model berilgan bo'lsa (masalan banner image-gen) — faqat o'sha model.
    # Aks holda vision/audio uchun fallback zanjiridan foydalanamiz.
    models = [model] if model else list(_MODEL_CHAIN)
    max_attempts = 3            # har bir model uchun 5xx'da qayta urinishlar
    last_transient = {"error": "http"}

    for mi, mdl in enumerate(models):
        url = f"{_BASE}/models/{mdl}:generateContent"
        resp = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException:
                log.warning("Gemini native: timeout (%s)", mdl)
                last_transient = {"error": "timeout"}
                resp = None
                break                       # keyingi modelga o'tamiz
            except Exception as e:
                log.warning("Gemini native: tarmoq xatosi (%s): %s", mdl, e)
                last_transient = {"error": "http"}
                resp = None
                break
            if resp.status_code in (500, 502, 503) and attempt < max_attempts:
                log.info("Gemini native: %s band %s (urinish %s/%s)",
                         resp.status_code, mdl, attempt, max_attempts)
                await asyncio.sleep(1.0 * attempt)    # 1s, 2s backoff
                continue
            break

        if resp is None:
            continue                        # timeout/tarmoq — keyingi model

        # 5xx hali ham davom etsa — vaqtinchalik, keyingi modelni sinaymiz
        if resp.status_code in (500, 502, 503):
            log.warning("Gemini native: %s hali ham band (%s)", resp.status_code, mdl)
            last_transient = {"error": "http"}
            continue

        # Vaqtinchalik bo'lmagan yakuniy javob (200 yoki 4xx) — shu yerda hal qilamiz
        if resp.status_code == 429:
            log.warning("Gemini native: 429 kvota tugadi (%s)", mdl)
            return {"error": "quota"}
        if resp.status_code in (401, 403):
            log.error("Gemini native: auth xato %s", resp.status_code)
            return {"error": "auth"}
        if resp.status_code != 200:
            log.warning("Gemini native: HTTP %s (%s): %s",
                        resp.status_code, mdl, resp.text[:300])
            return {"error": "http"}
        return _parse_response(resp, want_image)

    # Barcha modellar vaqtinchalik xato berdi
    return last_transient


def _parse_response(resp, want_image):
    """200 javobni {"text":...}/{"image":...}/{"error":"parse"} ga aylantiradi."""
    try:
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        cparts = ((cand.get("content") or {}).get("parts") or [])
        if want_image:
            for p in cparts:
                blob = p.get("inlineData") or p.get("inline_data")
                if blob and blob.get("data"):
                    return {"image": base64.b64decode(blob["data"]),
                            "image_mime": blob.get("mimeType") or blob.get("mime_type")
                            or "image/png"}
            # Rasm kelmadi (masalan, xavfsizlik bloki) — matnni qaytaramiz, log uchun
            txt = " ".join(p.get("text", "") for p in cparts).strip()
            log.warning("Gemini image-gen rasm qaytarmadi: %s", txt[:200])
            return {"error": "parse"}
        text = "".join(p.get("text", "") for p in cparts).strip()
        if not text:
            fr = cand.get("finishReason", "?")
            log.warning("Gemini native: bo'sh javob (finishReason=%s)", fr)
            return {"error": "parse"}
        return {"text": text}
    except Exception as e:
        log.warning("Gemini native: javob parse xatosi: %s", e)
        return {"error": "parse"}


def _extract_json(text: str):
    """Model javobidan JSON obyektni ishonchli sug'urib oladi.

    responseMimeType=application/json bilan odatda toza JSON keladi, lekin
    fallback sifatida ```json ... ``` qobiq va atrofdagi matnni ham ko'taramiz."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except Exception:
        pass
    # Balanslangan birinchi {...} blokni topamiz
    start = t.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


async def _json_vision_call(parts, *, system, max_tokens=800, temperature=0.2):
    """Vision → JSON: umumiy qolip. {"error":...} yoki dict qaytaradi."""
    res = await _generate(parts, system=system, max_tokens=max_tokens,
                          temperature=temperature, json_mode=True)
    if res.get("error"):
        return res
    data = _extract_json(res["text"])
    if not isinstance(data, dict):
        return {"error": "parse"}
    return data


# ============================================================
# 1) RASMDAN MAHSULOT — nom/tavsif/kategoriya/narx taklifi
# ============================================================
async def analyze_product_photo(image_bytes, *, mime="image/jpeg",
                                categories=None, lang="uz"):
    """Mahsulot rasmini tahlil qiladi va e'lon qoralamasini taklif etadi.

    Qaytaradi:
      {"name","description","category","price_min","price_max",
       "unit","tags":[...], "confidence": 0..1}
    yoki {"error": "..."}. Narxlar UZS (so'm), int; aniqlab bo'lmasa None."""
    if not image_bytes or len(image_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    ru = lang == "ru"
    cats = ", ".join(c for c in (categories or []) if c)[:1500]
    ans_lang = "ruscha" if ru else "o'zbekcha (lotin)"
    system = (
        "Sen O'zbekistondagi mahalliy do'kon uchun mahsulot e'lonlari tuzuvchi "
        "yordamchisan. Rasmni diqqat bilan o'rgan va SOTUVGA mos e'lon qoralamasini tuz.\n"
        f"Javob tili: {ans_lang}.\n"
        "FAQAT JSON qaytar, boshqa matn yozma. Maydonlar:\n"
        '{"name": "qisqa savdo nomi (max 60 belgi)",\n'
        ' "description": "2-4 jumlali jonli, halol tavsif (xususiyatlar, kimga mos)",\n'
        f' "category": "quyidagi ro\'yxatdan ENG mosi yoki null: [{cats}]",\n'
        ' "price_min": narx_taklifi_min_UZS_int_yoki_null,\n'
        ' "price_max": narx_taklifi_max_UZS_int_yoki_null,\n'
        ' "unit": "dona|kg|litr|metr|pachka|null",\n'
        ' "tags": ["2-5 ta qidiruv kalit so\'zi"],\n'
        ' "confidence": 0.0-1.0}\n'
        "Narxni O'zbekiston bozori (2026) uchun realistik baholab ber; ishonching "
        "past bo'lsa null qoldir. Rasmda mahsulot aniq ko'rinmasa confidence<0.4 qil."
    )
    prompt = ("Определи товар на фото и составь черновик объявления."
              if ru else
              "Rasmdagi mahsulotni aniqlab, e'lon qoralamasini tuz.")
    data = await _json_vision_call(
        [_inline_part(image_bytes, mime), {"text": prompt}],
        system=system, max_tokens=700, temperature=0.4)
    if data.get("error"):
        return data
    # Tozalash — model ba'zan satr ichida raqam qaytaradi
    out = {
        "name": str(data.get("name") or "").strip()[:80],
        "description": str(data.get("description") or "").strip()[:800],
        "category": (str(data.get("category")).strip()
                     if data.get("category") else None),
        "unit": (str(data.get("unit")).strip().lower()
                 if data.get("unit") else None),
        "tags": [str(x).strip() for x in (data.get("tags") or []) if x][:6],
    }
    for k in ("price_min", "price_max"):
        v = data.get(k)
        try:
            out[k] = int(float(re.sub(r"[^\d.]", "", str(v)))) if v not in (None, "") else None
        except Exception:
            out[k] = None
    try:
        out["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except Exception:
        out["confidence"] = 0.5
    if not out["name"]:
        return {"error": "parse"}
    return out


# ============================================================
# 2) TO'LOV CHEKINI TEKSHIRISH — summa/karta solishtirish
# ============================================================
async def verify_receipt(image_bytes, *, mime="image/jpeg", expected_amount,
                         expected_card_digits="", lang="uz"):
    """To'lov cheki (skrinshot)ni o'qib, kutilgan summa/karta bilan solishtiradi.

    expected_card_digits — sotuvchi kartasining OXIRGI 4 raqami (bo'sh bo'lishi mumkin).
    Qaytaradi:
      {"is_receipt": bool, "amount": int|None, "card_digits": "1234"|None,
       "datetime_text": str|None, "bank": str|None,
       "amount_match": bool|None, "card_match": bool|None,
       "verdict": "match"|"mismatch"|"unclear", "summary": str}
    yoki {"error": "..."}."""
    if not image_bytes or len(image_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    ru = lang == "ru"
    system = (
        "Sen to'lov cheklari (bank ilova skrinshotlari)ni o'quvchi tekshiruvchisan. "
        "Skrinshotdan to'lov ma'lumotlarini aniq ko'chir. Hech narsani TAXMIN QILMA — "
        "ko'rinmasa null qoldir. FAQAT JSON:\n"
        '{"is_receipt": bool  // bu umuman to\'lov cheki/kvitansiyami,\n'
        ' "amount": int|null  // o\'tkazilgan summa (UZS, tiyinsiz),\n'
        ' "card_digits": "qabul qiluvchi karta OXIRGI 4 raqami"|null,\n'
        ' "datetime_text": "chekdagi sana/vaqt matni"|null,\n'
        ' "bank": "ilova/bank nomi"|null,\n'
        ' "status_text": "chekdagi holat (muvaffaqiyatli/xato...)"|null}\n'
        "DIQQAT: card_digits — PUL QABUL QILUVCHI (получатель) kartasi bo'lsin, "
        "yuboruvchiniki emas. Ikkalasi ham ko'rinsa qabul qiluvchinikini ol."
    )
    prompt = ("Прочитай этот чек об оплате и выпиши данные."
              if ru else "Ushbu to'lov chekini o'qib, ma'lumotlarni ko'chir.")
    data = await _json_vision_call(
        [_inline_part(image_bytes, mime), {"text": prompt}],
        system=system, max_tokens=400, temperature=0.0)
    if data.get("error"):
        return data

    is_receipt = bool(data.get("is_receipt"))
    amount = None
    try:
        raw = data.get("amount")
        if raw not in (None, ""):
            amount = int(float(re.sub(r"[^\d.]", "", str(raw))))
    except Exception:
        amount = None
    card_digits = re.sub(r"\D", "", str(data.get("card_digits") or ""))[-4:] or None

    amount_match = None
    if amount is not None and expected_amount:
        # Ba'zi cheklar tiyinda yozadi (12 000,00) — parse int'ga to'g'rilangan.
        amount_match = abs(amount - int(expected_amount)) < 1
    card_match = None
    want4 = re.sub(r"\D", "", str(expected_card_digits or ""))[-4:]
    if card_digits and want4:
        card_match = card_digits == want4

    if not is_receipt:
        verdict = "unclear"
    elif amount_match and (card_match is not False):
        verdict = "match"
    elif amount_match is False or card_match is False:
        verdict = "mismatch"
    else:
        verdict = "unclear"

    # Sotuvchiga tayyor 1-2 jumlali xulosa (tilga mos)
    def _fmt(n):
        return f"{n:,}".replace(",", " ") if isinstance(n, int) else "?"
    if ru:
        parts_txt = []
        parts_txt.append("Это не похоже на чек." if not is_receipt else
                         f"Чек: {_fmt(amount)} сум" +
                         (f", карта *{card_digits}" if card_digits else ""))
        if verdict == "match":
            parts_txt.append("✅ Сумма и карта совпадают.")
        elif verdict == "mismatch":
            if amount_match is False:
                parts_txt.append(f"❌ Ожидалось {_fmt(int(expected_amount))} сум.")
            if card_match is False:
                parts_txt.append(f"❌ Карта не совпадает (ожидалось *{want4}).")
        else:
            parts_txt.append("⚠️ Не удалось проверить автоматически — проверьте вручную.")
        summary = " ".join(parts_txt)
    else:
        parts_txt = []
        parts_txt.append("Bu chekka o'xshamaydi." if not is_receipt else
                         f"Chek: {_fmt(amount)} so'm" +
                         (f", karta *{card_digits}" if card_digits else ""))
        if verdict == "match":
            parts_txt.append("✅ Summa va karta mos keldi.")
        elif verdict == "mismatch":
            if amount_match is False:
                parts_txt.append(f"❌ Kutilgan summa: {_fmt(int(expected_amount))} so'm.")
            if card_match is False:
                parts_txt.append(f"❌ Karta mos emas (kutilgan: *{want4}).")
        else:
            parts_txt.append("⚠️ Avtomatik tekshirib bo'lmadi — qo'lda ko'rib chiqing.")
        summary = " ".join(parts_txt)

    return {"is_receipt": is_receipt, "amount": amount, "card_digits": card_digits,
            "datetime_text": data.get("datetime_text"), "bank": data.get("bank"),
            "amount_match": amount_match, "card_match": card_match,
            "verdict": verdict, "summary": summary}


# ============================================================
# 3) OVOZLI XABAR — transkripsiya (qidiruv/buyurtma uchun)
# ============================================================
async def transcribe_voice(audio_bytes, *, mime="audio/ogg", lang="uz"):
    """Ovozli xabarni matnga aylantiradi (o'zbek/rus aralash nutqni qo'llaydi).

    Qaytaradi {"text": "..."} yoki {"error": "..."}."""
    if not audio_bytes or len(audio_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    system = (
        "Sen ovozli xabarlarni matnga aylantiruvchi transkripsiya xizmatisan. "
        "Nutq o'zbekcha, ruscha yoki aralash bo'lishi mumkin. Aytilganini AYNAN "
        "yoz (o'zbekchani lotin alifbosida), hech narsa qo'shma, izoh berma. "
        "Faqat transkripsiya matnini qaytar."
    )
    res = await _generate(
        [_inline_part(audio_bytes, mime),
         {"text": "Bu ovozli xabarni matnga aylantir."}],
        system=system, max_tokens=500, temperature=0.0)
    if res.get("error"):
        return res
    text = res["text"].strip().strip('"')
    if not text:
        return {"error": "parse"}
    return {"text": text}


# ============================================================
# 3b) RASM ORQALI QIDIRUV — xaridor rasmi → qidiruv kalit so'zlari
# ============================================================
async def identify_image_for_search(image_bytes, *, mime="image/jpeg",
                                    categories=None, lang="uz"):
    """Xaridor yuborgan rasmdagi mahsulotni aniqlab, qidiruv so'rovini tuzadi.

    Qaytaradi:
      {"label": "qisqa mahsulot nomi", "keywords": [...], "category": str|None}
    yoki {"error": "..."}. label — qidiruv qatoriga yoziladigan matn."""
    if not image_bytes or len(image_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    ru = lang == "ru"
    cats = ", ".join(c for c in (categories or []) if c)[:1500]
    ans_lang = "ruscha" if ru else "o'zbekcha (lotin)"
    system = (
        "Sen mahalliy onlayn do'kon qidiruv yordamchisisan. Xaridor topmoqchi "
        "bo'lgan narsaning RASMINI yuboradi — rasmdagi asosiy mahsulotni aniqla "
        "va do'kon katalogidan qidirish uchun so'rov tuz.\n"
        f"Javob tili: {ans_lang}.\n"
        "FAQAT JSON qaytar:\n"
        '{"label": "mahsulotning qisqa umumiy nomi (2-4 so\'z)",\n'
        ' "keywords": ["3-6 ta qidiruv kalit so\'zi: umumiy nom, brend/model, '
        "o'zbekcha VA ruscha sinonimlar\"],\n"
        f' "category": "quyidagi ro\'yxatdan ENG mosi yoki null: [{cats}]"}}\n'
        "Kalit so'zlar QISQA bo'lsin (1-2 so'zdan), eng umumiysi birinchi. "
        "Rasmda aniq mahsulot ko'rinmasa label va keywords'ni null/bo'sh qil."
    )
    prompt = ("Что за товар на фото? Составь поисковый запрос."
              if ru else
              "Rasmda qanday mahsulot bor? Qidiruv so'rovini tuz.")
    data = await _json_vision_call(
        [_inline_part(image_bytes, mime), {"text": prompt}],
        system=system, max_tokens=300, temperature=0.2)
    if data.get("error"):
        return data
    label = str(data.get("label") or "").strip()[:80] if data.get("label") else ""
    kws = [str(x).strip()[:60] for x in (data.get("keywords") or [])
           if x and str(x).strip()][:6]
    if not label and not kws:
        return {"error": "parse"}
    if label and label.lower() not in [k.lower() for k in kws]:
        kws.insert(0, label)
    return {"label": label or kws[0], "keywords": kws,
            "category": (str(data.get("category")).strip()
                         if data.get("category") else None)}


# ============================================================
# 4) RASM MODERATSIYASI — sifat/moslik avto-tekshiruvi
# ============================================================
async def moderate_image(image_bytes, *, mime="image/jpeg",
                         product_name="", lang="uz"):
    """Mahsulot rasmini tekshiradi: sifat, mahsulotga aloqadorlik, taqiqlangan kontent.

    Qaytaradi:
      {"ok": bool, "label": "ok"|"low_quality"|"unrelated"|"prohibited",
       "quality": 0-10, "reason": str}
    yoki {"error": "..."}. ok=False — flag; bloklash siyosatini chaqiruvchi hal qiladi."""
    if not image_bytes or len(image_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    ru = lang == "ru"
    reason_lang = "кратко по-русски" if ru else "qisqa sabab o'zbekcha"
    system = (
        "Sen onlayn do'kon mahsulot rasmlarini tekshiruvchi moderatorsan. "
        "FAQAT JSON qaytar:\n"
        '{"label": "ok"            // yaxshi mahsulot rasmi\n'
        '        | "low_quality"   // juda xira/qorong\'i/kesilgan, mahsulot tanib bo\'lmas\n'
        '        | "unrelated"     // mahsulotga aloqasiz (mem, hujjat, tasodifiy skrinshot)\n'
        '        | "prohibited",   // taqiqlangan: yalang\'ochlik, zo\'ravonlik, qurol, giyohvand modda\n'
        ' "quality": 0-10,          // foto sifati bahosi\n'
        f' "reason": "{reason_lang}"}}\n'
        "Oddiy telefon fotosi ham 'ok' — mukammal studiya sifati talab qilinmaydi. "
        "Faqat haqiqatan yaroqsiz rasmlarni belgila."
    )
    hint = (f"Ожидаемый товар: {product_name}" if ru else
            f"Kutilayotgan mahsulot: {product_name}") if product_name else ""
    prompt = ("Проверь это фото товара." if ru else
              "Ushbu mahsulot rasmini tekshir.") + ("\n" + hint if hint else "")
    data = await _json_vision_call(
        [_inline_part(image_bytes, mime), {"text": prompt}],
        system=system, max_tokens=200, temperature=0.0)
    if data.get("error"):
        return data
    label = str(data.get("label") or "ok").strip().lower()
    if label not in ("ok", "low_quality", "unrelated", "prohibited"):
        label = "ok"
    try:
        quality = max(0, min(10, int(float(data.get("quality", 7)))))
    except Exception:
        quality = 7
    return {"ok": label == "ok", "label": label, "quality": quality,
            "reason": str(data.get("reason") or "").strip()[:300]}


# ============================================================
# 5) REKLAMA BANNERI — Gemini rasm generatsiyasi
# ============================================================
async def generate_banner_image(image_bytes, *, mime="image/jpeg",
                                product_name="", price_text="",
                                shop_name="", style_hint="", lang="uz"):
    """Mahsulot rasmidan professional reklama banneri YARATADI (image-gen model).

    Muvaffaqiyatda {"image": bytes, "image_mime": str}; xatoda {"error": "..."} —
    chaqiruvchi ad_design.build_ad_image (PIL) fallback'iga qaytishi kerak.
    DIQQAT: image-gen modeli billing talab qiladi; 429/403 kutilgan holat."""
    if not image_bytes or len(image_bytes) > MAX_INLINE_BYTES:
        return {"error": "parse"}
    ru = lang == "ru"
    txt_lang = "русском" if ru else "o'zbek (lotin)"
    prompt = (
        "Create a professional square (1:1) advertising banner for a local "
        "marketplace, using the attached product photo as the hero image.\n"
        f"- Product: {product_name or 'product'}\n"
        + (f"- Show the price prominently, exactly this text: {price_text}\n"
           if price_text else "")
        + (f"- Shop name (small, elegant): {shop_name}\n" if shop_name else "")
        + (f"- Style: {style_hint}\n" if style_hint else "")
        + f"- All visible text must be in {txt_lang} language, spelled EXACTLY "
          "as given above — do not invent or translate text.\n"
        "- Clean modern design: soft gradient background, good contrast, "
        "the product sharp and appetizing, price on a bright badge.\n"
        "- No watermarks, no fake logos, no extra invented text or numbers."
    )
    res = await _generate(
        [_inline_part(image_bytes, mime), {"text": prompt}],
        model=_IMAGE_MODEL, want_image=True, max_tokens=8192,
        temperature=0.7, timeout=IMAGE_TIMEOUT)
    return res


# ============================================================
# Foydalanuvchi xabarlari (uz/ru) — chaqiruvchilar uchun yagona lug'at
# ============================================================
_ERR_MSGS = {
    "quota":    ("AI hozir band (kunlik limit). Birozdan so'ng qayta urinib ko'ring.",
                 "ИИ сейчас занят (дневной лимит). Попробуйте чуть позже."),
    "auth":     ("AI sozlamasida xatolik. Administratorga xabar bering.",
                 "Ошибка настройки ИИ. Сообщите администратору."),
    "timeout":  ("AI javobi kechikdi. Qayta urinib ko'ring.",
                 "ИИ не успел ответить. Попробуйте ещё раз."),
    "http":     ("AI bilan aloqa uzildi. Qayta urinib ko'ring.",
                 "Связь с ИИ прервалась. Попробуйте ещё раз."),
    "disabled": ("AI xizmati o'chirilgan.", "Сервис ИИ отключён."),
    "parse":    ("AI javobini o'qib bo'lmadi. Boshqa rasm/yozuv bilan urinib ko'ring.",
                 "Не удалось разобрать ответ ИИ. Попробуйте с другим фото/текстом."),
}


def error_message(code: str, lang: str = "uz") -> str:
    """Xato kodini foydalanuvchiga ko'rsatiladigan matnga aylantiradi."""
    uz, ru = _ERR_MSGS.get(code, _ERR_MSGS["http"])
    return ru if lang == "ru" else uz
