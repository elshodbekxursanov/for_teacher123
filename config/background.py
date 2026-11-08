"""Og'ir ishlar (PDF/hujjat qayta ishlash): Celery bor bo'lsa — navbat, aks holda fon oqimi."""
import threading
from importlib import import_module

from django.conf import settings
from django.db import connection


def run_bg(path, *args):
    if settings.CELERY_BROKER_URL:
        from .tasks import call
        call.delay(path, *args)
        return
    mod, fn = path.rsplit(":", 1)
    func = getattr(import_module(mod), fn)

    def target():
        try:
            func(*args)
        finally:
            connection.close()
    threading.Thread(target=target, daemon=True).start()
