import csv, random
from io import BytesIO
from datetime import timedelta
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import HasActiveAccess, IsTeacher
from content.models import Problem, Subject
from . import htmlimport, services
from .models import Attempt, AttemptAnswer, Test
from .serializers import TestReadSerializer, TestWriteSerializer


class TestViewSet(viewsets.ModelViewSet):
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve", "start"):
            return [HasActiveAccess()]
        return [IsTeacher()]

    def get_serializer_class(self):
        return TestWriteSerializer if self.action in ("create", "update", "partial_update") else TestReadSerializer

    def get_queryset(self):
        u = self.request.user
        qs = Test.objects.select_related("subject")
        if u.is_admin_role:
            return qs
        if u.role == "teacher":
            return qs.filter(created_by=u) if self.request.method not in ("GET", "POST") else qs.filter(Q(created_by=u) | Q(is_published=True))
        return qs.filter(is_published=True).filter(Q(subject__isnull=True) | Q(subject__is_active=True))

    def perform_create(self, s):
        s.save(created_by=self.request.user)

    def perform_destroy(self, test):
        ids = list(test.questions.values_list("problem_id", flat=True))
        test.delete()                                # urinishlar va natijalar ham o'chadi
        Problem.objects.filter(id__in=ids, topic__subject__slug="html-testlar").delete()      # yashirin savollar tozalanadi

    def _own(self, test):
        u = self.request.user
        if not (u.is_admin_role or test.created_by_id == u.id):
            raise PermissionDenied("Bu test sizga tegishli emas")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        test = self.get_object()
        problems = [tq.problem for tq in test.questions.select_related("problem")]
        if not problems:
            raise ValidationError("Testda savollar yo'q")
        att = Attempt.objects.filter(user=request.user, test=test, finished_at__isnull=True).first()
        if att:
            services.refresh(att)
        if not att or att.finished_at:
            now = timezone.now()
            att = Attempt.objects.create(user=request.user, test=test, question_started_at=now,
                                         deadline=now + timedelta(minutes=test.time_limit) if test.time_limit else None)
            if test.shuffle:
                random.shuffle(problems)
            AttemptAnswer.objects.bulk_create([AttemptAnswer(attempt=att, problem=p, order=i,
                                              option_order=services.make_order(p) if test.shuffle_options else "") for i, p in enumerate(problems)])
        return Response(services.payload(att, request), status=201)

    @action(detail=False, methods=["post"], url_path="import-html")
    def import_html(self, request):
        """HTML viktorina faylini (RAW_QUESTIONS) saytga tayyor test qilib joylash. dry_run=1 — faqat ko'rib chiqish."""
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith((".html", ".htm")):
            raise ValidationError("HTML fayl tanlang")
        if f.size > htmlimport.MAX_BYTES:
            raise ValidationError("Fayl 2 MB dan oshmasligi kerak")
        raw = f.read()
        parsed, dig = htmlimport.parse(raw), htmlimport.digest(raw)
        dup = Test.objects.filter(source_hash=dig).first()
        if str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes"):
            return Response({**parsed, "duplicate": dup.id if dup else None})
        subject = None                              # fan ixtiyoriy: berilmasa test mustaqil, savollar yashirin saqlanadi
        if request.data.get("subject"):
            subject = Subject.objects.filter(pk=request.data.get("subject"), is_active=True).first()
            if not subject:
                raise ValidationError("Fan topilmadi")
            if not request.user.can_manage_subject(subject.id):
                raise PermissionDenied("Bu fan sizga biriktirilmagan")
        if parsed["errors"] or not parsed["questions"]:
            raise ValidationError("Faylda xatolar bor: " + "; ".join(f"{e['n']}-savol: {e['reason']}" if e["n"] else e["reason"] for e in parsed["errors"][:5]))
        if dup:
            return Response({"detail": "Bu fayl avval yuklangan", "test": dup.id}, status=409)
        publish = str(request.data.get("publish", "1")).lower() in ("1", "true", "yes")
        topic = (request.data.get("topic") or parsed["title"]).strip()[:200]
        test = htmlimport.create_test(request.user, subject, topic, parsed, publish, dig)
        return Response({"imported": len(parsed["questions"]), "warnings": parsed["warnings"], "test": TestReadSerializer(test).data}, status=201)

    def _rows(self, test):
        for a in test.attempts.filter(finished_at__isnull=False).select_related("user"):
            yield {"id": a.id, "student": a.user.first_name or a.user.username, "username": a.user.username, "grade": a.user.grade,
                   "score": a.score, "total": a.total, "percent": a.percent,
                   "seconds": int((a.finished_at - a.started_at).total_seconds()), "finished_at": a.finished_at}

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        test = self.get_object(); self._own(test)
        return Response(list(self._rows(test)))

    @action(detail=True, methods=["get"], url_path="results-csv")
    def results_csv(self, request, pk=None):
        test = self.get_object(); self._own(test)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="test-{test.id}-natijalar.csv"'
        resp.write("\ufeff")
        w = csv.writer(resp)
        w.writerow(["O'quvchi", "Guruh/sinf", "Login", "Ball", "Jami", "Foiz", "Sarflangan vaqt (s)", "Tugagan vaqti"])
        for r in self._rows(test):
            w.writerow([r["student"], r["grade"], r["username"], r["score"], r["total"], r["percent"], r["seconds"], r["finished_at"]])
        return resp


    @action(detail=True, methods=["get"], url_path="results-xlsx")
    def results_xlsx(self, request, pk=None):
        """Excel: umumiy natijalar + har bir o'quvchining savollar bo'yicha javoblari."""
        from openpyxl import Workbook
        test = self.get_object(); self._own(test)
        wb = Workbook(); ws = wb.active; ws.title = "Umumiy natijalar"
        ws.append(["№", "O'quvchi", "Guruh/sinf", "Login", "To'g'ri", "Jami", "Foiz", "Sarflangan vaqt (s)", "Tugagan vaqti"])
        rows = list(self._rows(test))
        for i, r in enumerate(rows, 1):
            ws.append([i, r["student"], r["grade"], r["username"], r["score"], r["total"], r["percent"], r["seconds"],
                       r["finished_at"].replace(tzinfo=None) if r["finished_at"] else ""])
        det = wb.create_sheet("Javoblar")
        det.append(["O'quvchi", "Savol №", "Savol", "O'quvchi javobi", "To'g'ri javob", "Natija"])
        for a in AttemptAnswer.objects.filter(attempt__test=test, attempt__finished_at__isnull=False).select_related("attempt__user", "problem").order_by("attempt_id", "order"):
            p, orig = a.problem, services.to_original(a.answer, a.option_order)
            txt = lambda L: getattr(p, f"option_{L.lower()}", "") if p.type == "test" and L in list("ABCD") else L
            det.append([a.attempt.user.first_name or a.attempt.user.username, a.order + 1, p.text, txt(orig) or "—", txt(p.correct_answer),
                        "To'g'ri" if a.is_correct else "Xato"])
        buf = BytesIO(); wb.save(buf)
        resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="test-{test.id}-natijalar.xlsx"'
        return resp


class AttemptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    pagination_class = None

    def get_queryset(self):
        return Attempt.objects.filter(user=self.request.user).select_related("test")

    def list(self, request):
        rows = self.get_queryset().filter(finished_at__isnull=False)[:50]
        return Response([{"id": a.id, "test": a.test.title, "score": a.score, "total": a.total,
                          "percent": a.percent, "finished_at": a.finished_at} for a in rows])

    def retrieve(self, request, pk=None):
        return Response(services.payload(services.refresh(self.get_object()), request))

    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        att = services.refresh(self.get_object())
        if att.finished_at:
            raise ValidationError("Test yakunlangan yoki vaqt tugagan")
        text = str(request.data.get("answer", ""))[:500]
        rows = list(att.answers.select_related("problem"))
        seq = services.sequential(att)
        if seq:
            row = rows[att.current_index]
            if str(row.problem_id) != str(request.data.get("problem")):
                raise ValidationError("Bu savol uchun vaqt tugagan")
            if att.test.instant_feedback and row.answer:
                raise ValidationError("Bu savolga javob allaqachon berilgan")
        else:
            row = next((r for r in rows if str(r.problem_id) == str(request.data.get("problem"))), None)
            if not row:
                raise ValidationError("Bu savol testda yo'q")
        row.answer = text
        row.save(update_fields=["answer"])
        out = {"saved": True}
        if seq and att.test.instant_feedback:       # faqat ketma-ket rejimda (orqaga qaytib bo'lmaydi) darrov ko'rsatiladi
            out.update(is_correct=services.is_right(row, text), correct=services.correct_shown(row))
        return Response(out)

    @action(detail=True, methods=["post"])
    def next(self, request, pk=None):
        """Ketma-ket rejim: keyingi savolga o'tish (vaqt tugaganda yoki javobdan keyin)."""
        att = services.refresh(self.get_object())
        try:
            frm = int(request.data.get("from_index", -1))
        except (TypeError, ValueError):
            frm = -1
        if not att.finished_at and services.sequential(att) and frm == att.current_index:
            att.current_index += 1
            att.question_started_at = timezone.now()
            if att.current_index >= att.answers.count():
                services.grade(att)
            else:
                att.save(update_fields=["current_index", "question_started_at"])
        return Response(services.payload(att, request))

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        att = self.get_object()
        if not att.finished_at:
            services.grade(att)
        return Response(services.payload(att, request))
