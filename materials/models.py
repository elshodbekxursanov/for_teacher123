import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models

private_storage = FileSystemStorage(location=settings.PRIVATE_ROOT)     # base_url yo'q -> ochiq havola yo'q


def validate_month(v):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
        raise ValidationError("Oy YYYY-MM ko'rinishida bo'lishi kerak")


class Material(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        PUBLISHED = "published", "E'lon qilingan"

    class Access(models.TextChoices):
        ALL = "all", "Hamma foydalanuvchilar"
        SELECTED = "selected", "Tanlanganlar"

    title = models.CharField(max_length=200)
    subject = models.ForeignKey("content.Subject", on_delete=models.CASCADE, related_name="materials")
    topic = models.ForeignKey("content.Topic", null=True, blank=True, on_delete=models.SET_NULL)
    month = models.CharField(max_length=7, validators=[validate_month])
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    access = models.CharField(max_length=10, choices=Access.choices, default=Access.ALL)
    allow_download = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    allowed_users = models.ManyToManyField(settings.AUTH_USER_MODEL, through="MaterialAccess", blank=True, related_name="+")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month", "-created_at"]
        indexes = [models.Index(fields=["month", "status"])]


class MaterialAccess(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["material", "user"], name="uniq_material_user")]


class MaterialFile(models.Model):
    class Extract(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        READY = "ready", "Tayyor"
        OCR = "ocr", "OCR/AI kerak"
        ERROR = "error", "Xato"

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(storage=private_storage, upload_to="materials/%Y/%m/")
    original_name = models.CharField(max_length=255)
    ext = models.CharField(max_length=8)
    size = models.PositiveBigIntegerField(default=0)
    pages = models.PositiveIntegerField(default=0)
    extract_status = models.CharField(max_length=8, choices=Extract.choices, default=Extract.PENDING)
    extract_error = models.CharField(max_length=300, blank=True)
    checksum = models.CharField(max_length=64, blank=True)


class ProblemSource(models.Model):
    """Fayldan ajratilgan alohida misol (qidiruv va AI uchun)."""
    file = models.ForeignKey(MaterialFile, on_delete=models.CASCADE, related_name="sources")
    page = models.PositiveIntegerField(default=1)
    topic_label = models.CharField(max_length=200, blank=True)
    number = models.PositiveIntegerField()
    text = models.TextField()
    solution_text = models.TextField(blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["file", "page", "number"]
        indexes = [models.Index(fields=["number"]), models.Index(fields=["topic_label"])]
