"""_json_from_text — model javobidan JSON ajratish (regressiya testlari).

Sabab: ilgari greedy `re.search(r"\\{.*\\}", DOTALL)` ishlatilgan edi. Model JSON
dan keyin izoh yozib, izohda qavs uchrasa `Extra data` xatosi chiqardi va
funksiya butunlay ishlamay qolardi (jonli Gemini javobida kuzatilgan).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_assistant import _json_from_text  # noqa: E402


def test_oddiy_json():
    assert _json_from_text('{"a": 1}') == {"a": 1}


def test_json_dan_keyin_qavsli_izoh():
    """ASOSIY HOLAT: JSON dan keyin qavs bor matn — avval buzilardi."""
    txt = '{"summary": "xulosa", "plan": ["a"]}\n\nIzoh: {bu qo\'shimcha matn}'
    assert _json_from_text(txt) == {"summary": "xulosa", "plan": ["a"]}


def test_json_dan_oldin_matn():
    txt = 'Mana natija:\n{"ok": true}'
    assert _json_from_text(txt) == {"ok": True}


def test_markdown_blok():
    txt = '```json\n{"x": [1, 2]}\n```'
    assert _json_from_text(txt) == {"x": [1, 2]}


def test_ichma_ich_obyekt():
    txt = '{"a": {"b": {"c": 1}}, "d": 2}'
    assert _json_from_text(txt) == {"a": {"b": {"c": 1}}, "d": 2}


def test_qator_ichidagi_qavs_sanalmaydi():
    """Matn ichidagi } qavs hisobini buzmasligi kerak."""
    txt = '{"text": "narx }{ belgisi", "n": 5}'
    assert _json_from_text(txt) == {"text": "narx }{ belgisi", "n": 5}


def test_ekranlangan_qoshtirnoq():
    txt = '{"text": "u \\"salom\\" dedi", "n": 1}'
    assert _json_from_text(txt) == {"text": 'u "salom" dedi', "n": 1}


def test_yaroqsiz_kirish_none_qaytaradi():
    assert _json_from_text("") is None
    assert _json_from_text("umuman JSON yo'q") is None
    assert _json_from_text('{"buzuq": ') is None
    assert _json_from_text(None) is None
