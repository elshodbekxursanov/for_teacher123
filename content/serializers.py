from rest_framework import serializers
from .models import Problem, Subject, Topic


class SubjectSerializer(serializers.ModelSerializer):
    problem_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "name", "slug", "description", "icon", "order", "problem_count"]


class TopicSerializer(serializers.ModelSerializer):
    problem_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Topic
        fields = ["id", "subject", "name", "order", "problem_count"]


class ProblemPublicSerializer(serializers.ModelSerializer):
    """Talabaga: to'g'ri javob va yechim YO'Q."""
    subject = serializers.IntegerField(source="topic.subject_id", read_only=True)
    subject_name = serializers.CharField(source="topic.subject.name", read_only=True)
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = Problem
        fields = ["id", "subject", "subject_name", "topic", "topic_name", "number", "text", "image", "type",
                  "option_a", "option_b", "option_c", "option_d", "difficulty"]


class ProblemManageSerializer(serializers.ModelSerializer):
    """Ustoz/Admin: hamma maydon."""
    class Meta:
        model = Problem
        fields = "__all__"
        read_only_fields = ["created_by", "created_at"]


class AnswerInSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=500)


class SubjectAdminSerializer(serializers.ModelSerializer):
    problem_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "name", "slug", "description", "icon", "order", "is_active", "problem_count"]


class TopicAdminSerializer(serializers.ModelSerializer):
    problem_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Topic
        fields = ["id", "subject", "name", "order", "problem_count"]
