"""
TezBozor Mini App backend (FastAPI) — Faza 1.

- Bot bilan AYNAN bir xil PostgreSQL bazaga ulanadi (database.py qayta ishlatiladi)
  → ma'lumot avtomatik 1:1, sinxronlash kerak emas.
- Telegram WebApp `initData` imzosini bot tokeni bilan tekshiradi (xavfsizlik).
- Mahsulot rasmlari Telegram file_id — ularni web'da ko'rsatish uchun rasm-proksi
  (getFile → yuklab → disk-cache → stream).

Ishga tushirish (lokal/sinov):
    uvicorn webapp_server:app --host 127.0.0.1 --port 8080

Kerakli paketlar:  fastapi  uvicorn[standard]  httpx
"""
import os
import hashlib
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx

from database import Database
from webapp_auth import validate_init_data

BOT_TOKEN = os.getenv("BOT_TOKEN")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp_static")
IMG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img_cache")
os.makedirs(IMG_CACHE_DIR, exist_ok=True)

db = Database()  # DB_BACKEND / DATABASE_URL .env'dan o'qiladi
app = FastAPI(title="TezBozor Mini App API")


# ============================================================
# initData TEKSHIRUVI (Telegram WebApp xavfsizligi) — webapp_auth.py'da
# ============================================================
def require_auth(authorization: str):
    """Authorization sarlavhasi: "tma <initData>". To'g'ri bo'lmasa 401."""
    init_data = ""
    if authorization and authorization.startswith("tma "):
        init_data = authorization[4:]
    auth = validate_init_data(init_data, BOT_TOKEN)
    if not auth:
        raise HTTPException(status_code=401, detail="invalid initData")
    return auth


def _rows(result):
    """Row-larni JSON uchun dict'ga aylantiradi (PG shim _Row ham, sqlite3.Row ham)."""
    if not result:
        return []
    return [dict(r) for r in result]


# ============================================================
# API
# ============================================================
@app.get("/api/categories")
def api_categories(authorization: str = Header(None)):
    require_auth(authorization)
    return _rows(db.get_categories())


@app.get("/api/products")
def api_products(
    authorization: str = Header(None),
    q: str = Query(None),
    category_id: int = Query(None),
    sort: str = Query("rating"),
    region_id: int = Query(None),
):
    require_auth(authorization)
    items = db.search_products(
        query=q, category_id=category_id, sort_by=sort, region_id=region_id
    )
    return _rows(items)


@app.get("/api/products/{product_id}")
def api_product_detail(product_id: int, authorization: str = Header(None)):
    require_auth(authorization)
    product = db.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="not found")
    product = dict(product)
    product["images"] = db.get_product_images(product_id)  # file_id ro'yxati
    return product


@app.get("/api/image/{file_id}")
async def api_image(file_id: str):
    """Telegram file_id'ni haqiqiy rasmga aylantiradi (getFile → yuklab → cache → stream)."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="no token")
    # Disk-cache (getFile rate-limitiga tushmaslik uchun)
    safe = hashlib.sha256(file_id.encode()).hexdigest()
    cache_path = os.path.join(IMG_CACHE_DIR, safe + ".jpg")
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=604800"})
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            meta = await client.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                params={"file_id": file_id},
            )
            data = meta.json()
            if not data.get("ok"):
                raise HTTPException(status_code=404, detail="file not found")
            path = data["result"]["file_path"]
            img = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
            img.raise_for_status()
            content = img.content
        with open(cache_path, "wb") as f:
            f.write(content)
        return Response(content=content, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"image proxy xatosi ({file_id[:12]}...): {e}")
        raise HTTPException(status_code=502, detail="image fetch failed")


_bot_username_cache = {"value": None}


@app.get("/api/config")
async def api_config(authorization: str = Header(None)):
    require_auth(authorization)
    # bot username — buyurtma tugmasi bot'ga deep-link qilishi uchun (getMe, keshlanadi)
    if _bot_username_cache["value"] is None and BOT_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
                d = r.json()
                if d.get("ok"):
                    _bot_username_cache["value"] = d["result"]["username"]
        except Exception:
            pass
    return {"bot_username": _bot_username_cache["value"]}


@app.get("/api/health")
def api_health():
    return {"ok": True, "backend": db.backend}


# ============================================================
# FRONTEND (static)
# ============================================================
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
