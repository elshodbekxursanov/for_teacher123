import random
from django.db import transaction
from rest_framework import serializers

from content.models import Problem, Topic
from .models import Test, TestQuestion


def pool(subject, topics):
    qs = Problem.objects.filter(status="published", topic__subject=subject)
    return qs.filter(topic__in=topics) if topics else qs


class TestReadSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else ""

    class Meta:
        model = Test
        fields = ["id", "title", "subject", "subject_name", "topics", "question_count", "time_limit", "question_time",
                  "shuffle", "shuffle_options", "instant_feedback", "is_published", "created_by", "created_at"]


class TestWriteSerializer(serializers.ModelSerializer):
    topics = serializers.PrimaryKeyRelatedField(queryset=Topic.objects.all(), many=True, required=False)
    problem_ids = serializers.ListField(child=serializers.IntegerField(), required=False, write_only=True)

    class Meta:
        model = Test
        fields = ["id", "title", "subject", "topics", "question_count", "time_limit", "question_time", "shuffle",
                  "shuffle_options", "instant_feedback", "is_published", "problem_ids"]

    def validate(self, a):
        subject = a.get("subject") or (self.instance.subject if self.instance else None)
        topics = a.get("topics", [])
        req = self.context.get("request")
        if subject is None:
            return a
        if req and not req.user.can_manage_subject(subject.id):
            raise serializers.ValidationError({"subject": "Bu fan sizga biriktirilmagan"})
        if any(t.subject_id != subject.id for t in topics):
            raise serializers.ValidationError({"topics": "Mavzu boshqa fanga tegishli"})
        if self.instance is None:
            ids = a.get("problem_ids")
            if ids:
                if Problem.objects.filter(id__in=set(ids), status="published", topic__subject=subject).count() != len(set(ids)):
                    raise serializers.ValidationError({"problem_ids": "Masala topilmadi yoki boshqa fanga tegishli"})
            elif pool(subject, topics).count() < a["question_count"]:
                raise serializers.ValidationError({"question_count": f"Bazada faqat {pool(subject, topics).count()} ta masala bor"})
        return a

    @transaction.atomic
    def create(self, v):
        topics, ids = v.pop("topics", []), v.pop("problem_ids", None)
        chosen = list(dict.fromkeys(ids)) if ids else random.sample(
            list(pool(v["subject"], topics).values_list("id", flat=True)), v["question_count"])
        v["question_count"] = len(chosen)
        test = Test.objects.create(**v)
        test.topics.set(topics)
        TestQuestion.objects.bulk_create([TestQuestion(test=test, problem_id=pid, order=i) for i, pid in enumerate(chosen)])
        return test

    def update(self, instance, v):                  # savollar to'plami o'zgarmaydi, faqat sozlamalar
        v.pop("problem_ids", None); v.pop("topics", None); v.pop("question_count", None)
        return super().update(instance, v)
