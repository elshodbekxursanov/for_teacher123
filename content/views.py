from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView, get_object_or_404
from rest_framework.response import Response

from accounts.permissions import HasActiveAccess, IsAdminRole, IsTeacher
from .models import PracticeAnswer, Problem, Subject, Topic
from .serializers import (AnswerInSerializer, ProblemManageSerializer, ProblemPublicSerializer,
                          SubjectSerializer, TopicSerializer)

PUBLISHED = Q(problems__status="published")


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_queryset(self):
        return Subject.objects.filter(is_active=True).annotate(
            problem_count=Count("topics__problems", filter=Q(topics__problems__status="published")))

    @action(detail=True, methods=["get"])
    def topics(self, request, pk=None):
        qs = Topic.objects.filter(subject_id=pk, subject__is_active=True).annotate(
            problem_count=Count("problems", filter=Q(problems__status="published")))
        return Response(TopicSerializer(qs, many=True).data)


class ProblemViewSet(viewsets.ModelViewSet):
    """O'qish: har kim (faol obuna). Yozish: ustoz/admin."""

    def get_permissions(self):
        if self.action in ("list", "retrieve", "answer"):
            return [HasActiveAccess()]
        return [IsTeacher()]

    def _manage_list(self):
        u = self.request.user
        return self.action == "list" and self.request.query_params.get("manage") and (u.is_admin_role or u.role == "teacher")

    def get_serializer_class(self):
        if self.action in ("retrieve", "answer") or (self.action == "list" and not self._manage_list()):
            return ProblemPublicSerializer
        return ProblemManageSerializer

    def _check(self, topic):
        if not self.request.user.can_manage_subject(topic.subject_id):
            raise PermissionDenied("Bu fan sizga biriktirilmagan")

    def get_queryset(self):
        qs = Problem.objects.select_related("topic__subject")
        u = self.request.user
        if not (u.is_admin_role or u.role == "teacher") or (self.action in ("list", "retrieve", "answer") and not self._manage_list()):
            qs = qs.filter(status="published", topic__subject__is_active=True)
        p = self.request.query_params
        if p.get("subject"):
            qs = qs.filter(topic__subject_id=p["subject"])      # fanlar to'liq ajratilgan
        if p.get("topic"):
            qs = qs.filter(topic_id=p["topic"])
        if p.get("difficulty"):
            qs = qs.filter(difficulty=p["difficulty"])
        if p.get("q"):
            q = p["q"]
            cond = Q(text__icontains=q) | Q(topic__name__icontains=q) | Q(topic__subject__name__icontains=q)
            if q.isdigit():
                cond |= Q(number=int(q))
            qs = qs.filter(cond)
        return qs

    def perform_create(self, s):
        self._check(s.validated_data["topic"])
        s.save(created_by=self.request.user)

    def perform_update(self, s):
        self._check(s.instance.topic)
        if "topic" in s.validated_data:
            self._check(s.validated_data["topic"])
        s.save()

    def perform_destroy(self, inst):
        self._check(inst.topic)
        inst.delete()

    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        problem = self.get_object()
        s = AnswerInSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ok = problem.is_correct_answer(s.validated_data["answer"])
        PracticeAnswer.objects.create(user=request.user, problem=problem,
                                      answer=s.validated_data["answer"], is_correct=ok)
        return Response({"is_correct": ok})     # yechim bu yerda qaytarilmaydi


class TopicSolutionsView(ListAPIView):
    """Mavzu oxiridagi «Javoblar va yechimlar»."""
    permission_classes = [HasActiveAccess]
    pagination_class = None

    def list(self, request, pk=None):
        topic = get_object_or_404(Topic, pk=pk, subject__is_active=True)
        rows = topic.problems.filter(status="published").order_by("number").values(
            "id", "number", "correct_answer", "solution")
        return Response({"topic": topic.name, "items": list(rows)})


class AdminSubjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    pagination_class = None
    queryset = Subject.objects.all().annotate(problem_count=Count("topics__problems"))

    def get_serializer_class(self):
        from .serializers import SubjectAdminSerializer
        return SubjectAdminSerializer


class AdminTopicViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    pagination_class = None

    def get_serializer_class(self):
        from .serializers import TopicAdminSerializer
        return TopicAdminSerializer

    def get_queryset(self):
        qs = Topic.objects.annotate(problem_count=Count("problems"))
        sid = self.request.query_params.get("subject")
        return qs.filter(subject_id=sid) if sid else qs
