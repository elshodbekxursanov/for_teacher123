from django.db import transaction
import os
from django.http import FileResponse, HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from django.conf import settings

from accounts.permissions import IsAdminRole, IsTeacher
from content.models import Subject
from . import pdfimport, service
from .models import ImportJob


def _size(j):
    try:
        return j.file.size if j.file else 0
    except (OSError, ValueError):
        return 0


def brief(j, full=False):
    d = {"id": j.id, "source": j.source, "status": j.status, "pages": j.pages, "done_pages": j.done_pages,
         "error": j.error_message, "total": j.total, "valid": j.valid, "failed": j.failed,
         "created": j.created, "updated": j.updated, "skipped": j.skipped, "created_at": j.created_at,
         "name": os.path.basename(j.file.name) if j.file else "", "size": _size(j)}
    if full:
        d["errors"] = j.report
    return d


class ImportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsTeacher]
    throttle_scope = "import"
    parser_classes = [MultiPartParser, JSONParser]
    pagination_class = None

    def get_queryset(self):
        qs = ImportJob.objects.all()
        return qs if self.request.user.is_admin_role else qs.filter(user=self.request.user)

    def list(self, request):
        return Response([brief(j) for j in self.get_queryset()[:30]])

    def retrieve(self, request, pk=None):
        return Response(brief(self.get_object(), True))

    def create(self, request):
        f = request.FILES.get("file")
        if not f:
            raise ValidationError("Fayl tanlanmagan")
        if not f.name.lower().endswith(".xlsx"):
            raise ValidationError("Faqat .xlsx fayl qabul qilinadi")
        if f.size > service.MAX_BYTES:
            raise ValidationError("Fayl 5 MB dan oshmasligi kerak")
        try:
            rows, errors, total = service.parse(f, request.user, str(request.data.get('auto_subjects', '')).lower() in ('1', 'true', 'yes'))
        except ValueError as e:
            raise ValidationError(str(e))
        f.seek(0)
        job = ImportJob.objects.create(user=request.user, file=f, total=total, valid=len(rows),
                                       failed=len(errors), rows=rows, report=errors)
        return Response(brief(job, True), status=201)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        job = self.get_object()
        if job.status != "parsed":
            raise ValidationError("Import allaqachon tasdiqlangan")
        exclude = {int(x) for x in (request.data.get("exclude") or [])}
        if exclude:
            job.rows = [r for r in job.rows if r["row"] not in exclude]
            job.valid = len(job.rows)
        with transaction.atomic():
            service.apply(job, request.user)
        return Response(brief(job, True))

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        job = self.get_object()
        if job.status != "confirmed":
            raise ValidationError("Faqat tasdiqlangan importni qaytarish mumkin")
        with transaction.atomic():
            service.rollback(job)
        return Response(brief(job, True))

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        job = self.get_object()
        if not job.file:
            raise ValidationError("Fayl topilmadi")
        try:
            return FileResponse(job.file.open("rb"), as_attachment=True, filename=os.path.basename(job.file.name))
        except OSError:
            raise ValidationError("Fayl serverda topilmadi")

    @action(detail=False, methods=["get"])
    def template(self, request):
        r = HttpResponse(service.template_bytes(),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r["Content-Disposition"] = 'attachment; filename="masalalar-shablon.xlsx"'
        return r

    @action(detail=True, methods=["get"])
    def rows(self, request, pk=None):
        job = self.get_object()
        return Response([{"row": r["row"], "page": r.get("page"), "topic": r["topic"], "number": r["number"],
                          "text": r["text"][:300], "type": r["type"], "answer": r["answer"],
                          "has_solution": bool(r["solution"])} for r in job.rows])

    @action(detail=False, methods=["post"], url_path="pdf", permission_classes=[IsAdminRole])
    def pdf(self, request):
        """Administrator PDF yuklaydi; qayta ishlash fonda ketadi."""
        f, sid = request.FILES.get("file"), request.data.get("subject")
        if not settings.ANTHROPIC_API_KEY:
            raise ValidationError("ANTHROPIC_API_KEY sozlanmagan (server .env / muhit o'zgaruvchisi)")
        if not f or not f.name.lower().endswith(".pdf"):
            raise ValidationError("PDF fayl tanlang")
        if f.size > settings.MAX_PDF_BYTES:
            raise ValidationError("PDF 50 MB dan oshmasligi kerak")
        subject = Subject.objects.filter(pk=sid, is_active=True).first()
        if not subject:
            raise ValidationError("Fan tanlang")
        job = ImportJob.objects.create(user=request.user, file=f, source="pdf", subject=subject,
                                       forced_topic=str(request.data.get("topic", "")).strip()[:200], status="processing")
        pdfimport.run_async(job.id)
        return Response(brief(job, True), status=202)
