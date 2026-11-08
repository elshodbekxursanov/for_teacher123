from django.conf import settings
from django.db import models


class AICache(models.Model):
    key = models.CharField(max_length=64, unique=True)       # savol + yechim mazmuni xeshi
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class AIRequest(models.Model):
    class Kind(models.TextChoices):
        DB = "db", "Bazadagi tayyor yechim"
        AI = "ai", "AI yechdi"
        CACHE = "cache", "Keshdan"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_requests")
    subject = models.ForeignKey("content.Subject", null=True, on_delete=models.SET_NULL)
    problem = models.ForeignKey("content.Problem", null=True, blank=True, on_delete=models.SET_NULL)
    source = models.ForeignKey("materials.ProblemSource", null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=5, choices=Kind.choices)
    question_text = models.TextField(blank=True)
    answer = models.TextField(blank=True)
    tokens = models.PositiveIntegerField(default=0)
    cached = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
