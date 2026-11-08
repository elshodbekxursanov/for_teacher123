from django.contrib import admin
from .models import Attempt, Test
admin.site.register(Test, list_display=("title", "subject", "question_count", "time_limit", "is_published"))
admin.site.register(Attempt, list_display=("user", "test", "score", "total", "percent", "finished_at"))
