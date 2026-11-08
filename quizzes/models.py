from django.conf import settings
from django.db import models


class Test(models.Model):
    title = models.CharField(max_length=200)
    subject = models.ForeignKey("content.Subject", null=True, blank=True, on_delete=models.CASCADE, related_name="tests")
    topics = models.ManyToManyField("content.Topic", blank=True)
    question_count = models.PositiveIntegerField()
    time_limit = models.PositiveIntegerField(default=0, help_text="daqiqa; 0 = cheklovsiz")
    shuffle = models.BooleanField(default=True)
    is_published = models.BooleanField(default=True)
    question_time = models.PositiveIntegerField(default=0, help_text="har bir savolga soniya; 0 = cheklovsiz (ketma-ket rejim o'chiq)")
    shuffle_options = models.BooleanField(default=False, help_text="javob variantlari har bir urinishda aralashadi")
    instant_feedback = models.BooleanField(default=False, help_text="ketma-ket rejimda javobdan keyin to'g'ri/noto'g'ri ko'rsatiladi")
    source_hash = models.CharField(max_length=64, blank=True, db_index=True)    # HTML fayldan yuklangan bo'lsa — takror yuklashni oldini oladi
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TestQuestion(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="questions")
    problem = models.ForeignKey("content.Problem", on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["test", "problem"], name="uniq_problem_in_test")]


class Attempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="attempts")
    started_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    percent = models.FloatField(default=0)
    current_index = models.PositiveIntegerField(default=0)                  # ketma-ket rejim
    question_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    problem = models.ForeignKey("content.Problem", on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)
    option_order = models.CharField(max_length=4, blank=True)               # aralash variantlar: ko'rsatilgan A..D -> asl harf
    answer = models.CharField(max_length=500, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)       # faqat yakunlangandan keyin to'ldiriladi

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["attempt", "problem"], name="uniq_answer_per_problem")]
