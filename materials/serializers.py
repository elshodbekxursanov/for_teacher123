from rest_framework import serializers
from .models import Material, MaterialFile, ProblemSource


class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialFile
        fields = ["id", "original_name", "ext", "size", "pages", "extract_status", "extract_error"]


class MaterialAdminSerializer(serializers.ModelSerializer):
    files = FileSerializer(many=True, read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    access_users = serializers.PrimaryKeyRelatedField(source="allowed_users", many=True, read_only=True)

    class Meta:
        model = Material
        fields = ["id", "title", "subject", "subject_name", "topic", "month", "description", "status", "access",
                  "allow_download", "is_archived", "access_users", "files", "created_at"]


class SourceSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source="file.original_name", read_only=True)

    class Meta:
        model = ProblemSource
        fields = ["id", "file", "file_name", "page", "topic_label", "number", "text", "solution_text", "verified"]
