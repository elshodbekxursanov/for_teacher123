from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        PAID = "paid", "To'langan"
        CANCELLED = "cancelled", "Bekor qilingan"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    plan = models.CharField(max_length=5)
    amount = models.PositiveIntegerField()              # so'm; faqat serverda belgilanadi
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=10, blank=True)          # payme | click
    provider_tx_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Payme tranzaksiya holati (1 yaratilgan, 2 bajarilgan, -1/-2 bekor), vaqtlar — millisekund
    payme_state = models.IntegerField(null=True, blank=True)
    payme_create_time = models.BigIntegerField(default=0)
    payme_perform_time = models.BigIntegerField(default=0)
    payme_cancel_time = models.BigIntegerField(default=0)
    payme_reason = models.IntegerField(null=True, blank=True)
    # Click
    click_trans_id = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]
