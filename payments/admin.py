from django.contrib import admin
from .models import Payment
admin.site.register(Payment, list_display=("user", "plan", "amount", "status", "created_at"))
