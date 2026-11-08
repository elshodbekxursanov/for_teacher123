from django.contrib.auth.models import AbstractUser
from django.core.cache import cache
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "O'quvchi"
        TEACHER = "teacher", "Ustoz"
        ADMIN = "admin", "Administrator"

    class Access(models.TextChoices):
        FREE = "free", "Tekin (admin yaratgan)"
        PAID = "paid", "Pullik"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    access_type = models.CharField(max_length=5, choices=Access.choices, default=Access.PAID)
    valid_until = models.DateTimeField(null=True, blank=True)       # FREE: null = cheksiz
    must_change_password = models.BooleanField(default=False)
    grade = models.CharField("sinf/daraja", max_length=30, blank=True)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_users")
    # Ustoz qaysi fanlarni boshqaradi (bo'sh = hamma fan)
    teaching_subjects = models.ManyToManyField("content.Subject", blank=True, related_name="teachers")
    active_sid = models.CharField(max_length=36, blank=True)         # bitta faol sessiya rejimi uchun

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def subscription_state(self):
        if not self.is_active:
            return "blocked"
        if self.is_admin_role:
            return "active"
        if self.access_type == self.Access.FREE:
            return "active" if (self.valid_until is None or self.valid_until > timezone.now()) else "expired"
        return "active" if (self.valid_until and self.valid_until > timezone.now()) else "expired"

    @property
    def has_active_access(self):
        return self.subscription_state == "active"

    def can_manage_subject(self, subject_id):
        if self.is_admin_role:
            return True
        if self.role != self.Role.TEACHER:
            return False
        ids = set(self.teaching_subjects.values_list("id", flat=True))
        return not ids or subject_id in ids


class SiteConfig(models.Model):
    """Administrator sozlamalari (bitta yozuv)."""
    ai_daily_limit = models.PositiveIntegerField(default=20, help_text="O'quvchiga kuniga AI so'rovlar soni")
    force_password_change = models.BooleanField(default=True, help_text="Admin yaratgan hisob birinchi kirishda parol almashtiradi")
    single_session = models.BooleanField(default=False, help_text="Bir vaqtda faqat bitta faol sessiya")

    @classmethod
    def get(cls):
        obj = cache.get("siteconfig")
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set("siteconfig", obj, 15)
        return obj

    def save(self, *a, **kw):
        self.pk = 1
        super().save(*a, **kw)
        cache.delete("siteconfig")


class AuditLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    object = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def audit(user, action, obj=""):
    AuditLog.objects.create(user=user if getattr(user, "pk", None) else None, action=action, object=str(obj)[:200])
