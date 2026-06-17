"""Pytest umumiy fikstura'lari.

Har bir test toza, vaqtinchalik SQLite bazasida ishlaydi — haqiqiy marketplace.db
ga tegmaydi. Bu testlarni xavfsiz va takrorlanadigan qiladi.
"""
import os
import sys

import pytest

# Loyiha ildizini import yo'liga qo'shamiz (tests/ ichidan ishga tushirilsa ham)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database  # noqa: E402


@pytest.fixture
def db(tmp_path):
    """Vaqtinchalik faylga bog'langan toza Database obyekti."""
    path = tmp_path / "test_marketplace.db"
    return Database(db_path=str(path))


@pytest.fixture
def seller(db):
    """Sotuvchi (do'kon egasi) yaratadi va id qaytaradi."""
    return db.create_user(telegram_id=1001, phone_number="998901112233",
                          name="Sotuvchi", role="seller")


@pytest.fixture
def buyer(db):
    """Xaridor yaratadi va id qaytaradi."""
    return db.create_user(telegram_id=2002, phone_number="998904445566",
                          name="Xaridor", role="buyer")


@pytest.fixture
def product(db, seller):
    """Sotuvchiga tegishli, cheklangan zahirali mahsulot."""
    return db.create_product(seller_id=seller, name="Telefon korpusi",
                             price=45000, stock_count=10)


def make_order(db, buyer, seller, product, qty=1, price=45000):
    """Yordamchi: buyurtma yaratadi va id qaytaradi."""
    return db.create_order(buyer_id=buyer, seller_id=seller, product_id=product,
                           quantity=qty, total_price=price,
                           payment_method="cash", delivery_type="pickup")
