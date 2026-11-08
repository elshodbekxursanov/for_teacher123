from django.contrib import admin
from .models import AIRequest
admin.site.register(AIRequest, list_display=("user", "kind", "tokens", "created_at"))
