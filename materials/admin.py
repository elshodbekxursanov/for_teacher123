from django.contrib import admin
from .models import Material, MaterialFile, ProblemSource
admin.site.register(Material, list_display=("title", "subject", "month", "status", "access", "is_archived"))
admin.site.register(MaterialFile, list_display=("original_name", "material", "extract_status", "pages"))
admin.site.register(ProblemSource, list_display=("number", "topic_label", "file", "page", "verified"))
