from django.contrib import admin
from .models import Problem, Subject, Topic

admin.site.register(Subject, prepopulated_fields={"slug": ("name",)}, list_display=("name", "order", "is_active"))
admin.site.register(Topic, list_display=("name", "subject", "order"))
admin.site.register(Problem, list_display=("topic", "number", "type", "difficulty", "status"), list_filter=("topic__subject", "status"))
