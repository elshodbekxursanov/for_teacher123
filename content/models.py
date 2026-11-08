from django.conf import settings
from django.db import models


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=20, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="topics")
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["subject", "name"], name="uniq_topic_name_per_subject")]

    def __str__(self):
        return f"{self.subject} / {self.name}"


class Problem(models.Model):
    class Type(models.TextChoices):
        TEST = "test", "Test (A/B/C/D)"
        OPEN = "open", "Ochiq javob"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Oson"
        MEDIUM = "medium", "O'rta"
        HARD = "hard", "Qiyin"

    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        PUBLISHED = "published", "E'lon qilingan"

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="problems")
    number = models.PositiveIntegerField()
    text = models.TextField(help_text="LaTeX: $x^2+1$")
    image = models.ImageField(upload_to="problems/", blank=True)
    type = models.CharField(max_length=5, choices=Type.choices, default=Type.TEST)
    option_a = models.CharField(max_length=500, blank=True)
    option_b = models.CharField(max_length=500, blank=True)
    option_c = models.CharField(max_length=500, blank=True)
    option_d = models.CharField(max_length=500, blank=True)
    correct_answer = models.CharField(max_length=500)
    solution = models.TextField(blank=True)
    difficulty = models.CharField(max_length=6, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PUBLISHED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["topic", "number"]
        constraints = [models.UniqueConstraint(fields=["topic", "number"], name="uniq_problem_number_per_topic")]
        indexes = [models.Index(fields=["status", "difficulty"])]

    def __str__(self):
        return f"{self.topic} № {self.number}"

    def is_correct_answer(self, answer: str) -> bool:
        a, c = (answer or "").strip(), self.correct_answer.strip()
        return a.upper() == c.upper() if self.type == self.Type.TEST else a.lower() == c.lower()


class PracticeAnswer(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_answers")
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    answer = models.CharField(max_length=500)
    is_correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)
