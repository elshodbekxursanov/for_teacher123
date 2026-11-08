import pytest
from django.core.cache import cache

@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def _no_background_threads(monkeypatch):
    """Testlarda fon oqimi ishga tushmasin (SQLite bloklanmasligi uchun); funksiyalar to'g'ridan-to'g'ri chaqiriladi."""
    monkeypatch.setattr("materials.views.run_bg", lambda *a, **k: None)
