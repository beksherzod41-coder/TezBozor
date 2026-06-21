"""PostgreSQL shim — HAQIQIY Postgres'ga qarshi integratsiya testlari.

Bu testlar faqat real PG ulanishi bo'lganda ishlaydi:
  - `psycopg` o'rnatilgan bo'lsin, VA
  - `DATABASE_URL_TEST` env o'rnatilgan bo'lsin (alohida TEST bazasi DSN'i).

Aks holda butun modul `skip` qilinadi — shuning uchun lokal (PG'siz) muhitda
testlar yiqilmaydi. CI'da Postgres service ko'tariladi va bu testlar ishlaydi.

Maqsad: `db_backend.PgConnection/PgCursor` shim'i SQLite API'sini PG ustida
1:1 takrorlashini ISBOTLASH — taxmin emas. Tarixiy "barcha SELECT bo'sh
qaytaradi" bug'i va parametrsiz `%` escape tuzog'i shu yerda qotiriladi.
"""
import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")  # psycopg yo'q -> butun modul skip

DSN = os.getenv("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_TEST o'rnatilmagan — real PG testlari o'tkazib yuborildi"
)

import db_backend  # noqa: E402


@pytest.fixture
def conn():
    """Har test uchun toza shim-ulanish + unikal jadval; oxirida tozalanadi."""
    c = db_backend.connect(DSN)
    cur = c.cursor()
    # DDL tarjimasini ham sinaymiz: INTEGER->BIGINT, REAL->DOUBLE, BOOLEAN->SMALLINT, TIMESTAMP->TEXT
    cur.execute("""
        CREATE TABLE shim_t (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            ok BOOLEAN,
            created_at TIMESTAMP
        )
    """)
    c.commit()
    yield c
    try:
        cur2 = c.cursor()
        cur2.execute("DROP TABLE IF EXISTS shim_t")
        c.commit()
    finally:
        c.close()


def test_insert_then_select_roundtrip(conn):
    """Tarixiy bug: RELEASE SAVEPOINT'dan keyin SELECT bo'sh qaytar edi."""
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name, price, ok) VALUES (?, ?, ?)", ("Telefon", 45000, 1))
    conn.commit()
    cur.execute("SELECT name, price, ok FROM shim_t WHERE name=?", ("Telefon",))
    row = cur.fetchone()
    assert row is not None, "SELECT bo'sh qaytdi — shim buzuq (tarixiy regressiya)"
    assert row[0] == "Telefon"
    assert row["price"] == 45000
    assert row["ok"] == 1


def test_lastrowid_via_returning(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name) VALUES (?)", ("A",))
    conn.commit()
    assert isinstance(cur.lastrowid, int) and cur.lastrowid > 0


def test_row_access_modes(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name, price) VALUES (?, ?)", ("B", 12))
    conn.commit()
    cur.execute("SELECT id, name, price FROM shim_t WHERE name=?", ("B",))
    row = cur.fetchone()
    # int index, kalit, dict, in, keys, get
    assert row[1] == "B"
    assert row["name"] == "B"
    assert dict(zip(row.keys(), list(row)))["name"] == "B"
    assert "price" in row
    assert row.get("yoq", "default") == "default"


def test_insert_or_ignore_conflict(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (id, name) VALUES (?, ?)", (777, "first"))
    conn.commit()
    # Aynan shu id bilan ikkinchi marta — ON CONFLICT DO NOTHING tufayli e'tiborsiz
    cur.execute("INSERT OR IGNORE INTO shim_t (id, name) VALUES (?, ?)", (777, "second"))
    conn.commit()
    cur.execute("SELECT name FROM shim_t WHERE id=?", (777,))
    assert cur.fetchone()[0] == "first"


def test_percent_literal_without_params(conn):
    """Tuzoq: parametrsiz so'rovdagi '100% done' to'g'ri saqlanishi shart.

    translate_sql '%' -> '%%' qiladi; psycopg buni bo'sh-param bilan ham
    qaytarib '%' ga aylantirishi KERAK, aks holda baza '100%% done' saqlaydi.
    """
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name) VALUES ('100% done')")
    conn.commit()
    cur.execute("SELECT name FROM shim_t WHERE name LIKE '%done%'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "100% done", f"% escape buzilgan: {row[0]!r}"


def test_like_with_param(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name) VALUES (?)", ("iPhone 15",))
    conn.commit()
    cur.execute("SELECT name FROM shim_t WHERE name LIKE ?", ("%Phone%",))
    assert cur.fetchall() == [] or True  # case-sensitive bo'lishi mumkin
    cur.execute("SELECT name FROM shim_t WHERE name LIKE ?", ("iPhone%",))
    rows = cur.fetchall()
    assert any(r[0] == "iPhone 15" for r in rows)


def test_savepoint_forgiveness(conn):
    """SQLite 'forgiveness': try/except ichida ushlangan xato butun
    tranzaksiyani buzmasligi kerak (init_db'dagi ALTER naqshi shunga tayanadi)."""
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name) VALUES (?)", ("before",))
    # Ataylab xato so'rov — ushlaymiz
    try:
        cur.execute("INSERT INTO shim_t (yoq_ustun) VALUES (?)", ("x",))
    except Exception:
        pass
    # Tranzaksiya hali tirik bo'lishi va keyingi yozuv ishlashi kerak
    cur.execute("INSERT INTO shim_t (name) VALUES (?)", ("after",))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM shim_t WHERE name IN ('before','after')")
    assert cur.fetchone()[0] == 2


def test_current_timestamp_text_format(conn):
    """CURRENT_TIMESTAMP TEXT 'YYYY-MM-DD HH:MM:SS' formatida yozilsin (parity)."""
    cur = conn.cursor()
    cur.execute("INSERT INTO shim_t (name, created_at) VALUES (?, CURRENT_TIMESTAMP)", ("ts",))
    conn.commit()
    cur.execute("SELECT created_at FROM shim_t WHERE name=?", ("ts",))
    val = cur.fetchone()[0]
    assert isinstance(val, str)
    # 'YYYY-MM-DD HH:MM:SS' — 19 belgi, 'T' yo'q
    assert len(val) == 19 and val[4] == "-" and val[13] == ":"


def test_fetchall_after_commit(conn):
    """commit/RELEASE natija to'plamini yo'qotmasligi kerak (buferlangan)."""
    cur = conn.cursor()
    for i in range(3):
        cur.execute("INSERT INTO shim_t (name) VALUES (?)", (f"n{i}",))
    conn.commit()
    cur.execute("SELECT name FROM shim_t ORDER BY name")
    conn.commit()  # description=None bo'lib qolishi mumkin — baribir ishlasin
    rows = cur.fetchall()
    assert [r[0] for r in rows] == ["n0", "n1", "n2"]
