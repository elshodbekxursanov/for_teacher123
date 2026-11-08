from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import AuditLog, SiteConfig, User


@admin.register(User)
class U(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Bilim Markazi", {"fields": ("role", "access_type", "valid_until", "must_change_password", "grade", "teaching_subjects")}),)
    list_display = ("username", "first_name", "role", "access_type", "valid_until", "is_active")
    filter_horizontal = UserAdmin.filter_horizontal + ("teaching_subjects",)

admin.site.register(SiteConfig)
admin.site.register(AuditLog, list_display=("user", "action", "object", "created_at"))
