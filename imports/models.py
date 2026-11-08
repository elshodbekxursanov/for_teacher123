from django.conf import settings
from django.db import models


class ImportJob(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Qayta ishlanmoqda"
        FAILED = "failed", "Xato"
        PARSED = "parsed", "Tekshirildi"
        CONFIRMED = "confirmed", "Tasdiqlandi"
        ROLLED_BACK = "rolled_back", "Qaytarildi"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_jobs")
    source = models.CharField(max_length=5, default="excel")        # excel | pdf
    subject = models.ForeignKey("content.Subject", null=True, blank=True, on_delete=models.SET_NULL)
    forced_topic = models.CharField(max_length=200, blank=True)
    pages = models.PositiveIntegerField(default=0)
    done_pages = models.PositiveIntegerField(default=0)
    error_message = models.CharField(max_length=500, blank=True)
    file = models.FileField(upload_to="imports/")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PARSED)
    total = models.PositiveIntegerField(default=0)
    valid = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    rows = models.JSONField(default=list)            # tekshiruvdan o'tgan qatorlar
    report = models.JSONField(default=list)          # xato qatorlar: [{row, reason}]
    undo = models.JSONField(default=dict)            # qaytarish uchun
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
