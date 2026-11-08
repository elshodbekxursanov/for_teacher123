import base64
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone


def activate(pay, provider, tx_id):
    """Obunani faollashtirish/uzaytirish. Chaqiruvchi tranzaksiya ichida va select_for_update bilan bo'lishi kerak."""
    now = timezone.now()
    pay.status, pay.paid_at, pay.provider, pay.provider_tx_id = "paid", now, provider, str(tx_id)
    pay.save()
    u = pay.user
    base = u.valid_until if (u.valid_until and u.valid_until > now) else now
    u.valid_until = base + timedelta(days=settings.PLANS[pay.plan]["days"])
    u.save(update_fields=["valid_until"])
    from notifications.services import notify
    notify(u, "To'lov qabul qilindi", f"Obuna {u.valid_until:%d.%m.%Y} gacha uzaytirildi", "/profile")


def revoke(pay):
    """Bajarilgan to'lov qaytarilganda (Payme refund) berilgan kunlarni ayiradi."""
    u = pay.user
    if u.valid_until:
        u.valid_until -= timedelta(days=settings.PLANS[pay.plan]["days"])
        u.save(update_fields=["valid_until"])


def checkout_urls(pay):
    back = f"{settings.FRONTEND_URL}/payment/result?id={pay.id}"
    raw = f"m={settings.PAYME_MERCHANT_ID};ac.order_id={pay.id};a={pay.amount * 100};c={back}"
    host = "https://test.paycom.uz/" if settings.PAYME_TEST else "https://checkout.paycom.uz/"
    click = "https://my.click.uz/services/pay?" + urlencode({
        "service_id": settings.CLICK_SERVICE_ID, "merchant_id": settings.CLICK_MERCHANT_ID,
        "amount": f"{pay.amount:.2f}", "transaction_param": pay.id, "return_url": back})
    return {"payme": host + base64.b64encode(raw.encode()).decode(), "click": click}
