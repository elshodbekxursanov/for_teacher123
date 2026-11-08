try:                                   # Celery faqat CELERY_BROKER_URL berilganda ishlatiladi
    from .celery import app as celery_app
except Exception:                      # noqa
    celery_app = None
