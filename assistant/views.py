import json
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings

from accounts.models import SiteConfig, audit
from accounts.permissions import HasActiveAccess, IsTeacher
from content.models import Subject
from materials.models import ProblemSource
from materials.views import accessible_materials
from . import service
from .models import AICache, AIRequest


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def used_today(user):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return AIRequest.objects.filter(user=user, created_at__gte=start, kind__in=["ai", "cache"]).count()


def limit_for(user):
    return None if (user.is_admin_role or user.role == "teacher") else SiteConfig.get().ai_daily_limit


class QuotaView(APIView):
    permission_classes = [HasActiveAccess]

    def get(self, request):
        return Response({"used": used_today(request.user), "limit": limit_for(request.user)})


class SolveView(APIView):
    """Fan + mavzu + raqam -> masalani bazadan va fayllardan topib yechish.
    JSON qaytaradi (tayyor/topilmadi/tanlang) yoki AI kerak bo'lsa SSE oqimi (Content-Type: text/event-stream)."""
    permission_classes = [HasActiveAccess]
    throttle_scope = "ai"

    def post(self, request):
        d, user = request.data, request.user
        subject = Subject.objects.filter(pk=d.get("subject"), is_active=True).first()
        if not subject:
            raise ValidationError("Fanni tanlang")
        explain = bool(d.get("explain"))
        problem = src = None
        qtext = known = ""

        if d.get("text"):                                              # erkin matn rejimi
            qtext = service.sanitize(d["text"])
            if len(qtext) < 3:
                raise ValidationError("Savol matni juda qisqa")
        elif d.get("source_id"):                                       # fayldan topilgan ro'yxatdan tanlandi
            src = ProblemSource.objects.filter(pk=d["source_id"], file__material__in=accessible_materials(user).filter(subject=subject)).select_related("file").first()
            if not src:
                raise ValidationError("Manba topilmadi")
            qtext, known = src.text, src.solution_text
        else:
            try:
                number = int(d.get("number"))
            except (TypeError, ValueError):
                raise ValidationError("Masala raqamini kiriting")
            problem = service.find_problem(subject.id, d.get("topic"), number)
            if problem:
                qtext, known = service.problem_text(problem), problem.solution
            else:
                matches, exact = service.find_sources(user, subject.id, d.get("topic"), number)
                if not matches:
                    return Response({"status": "not_found", "message": "Bazada topilmadi. Savolni matn sifatida yozib yuborishingiz mumkin."})
                if len(matches) > 1 or not exact:
                    return Response({"status": "choose", "matches": [
                        {"id": m.id, **service.source_info(m), "preview": m.text[:160], "has_solution": bool(m.solution_text)} for m in matches]})
                src = matches[0]
                qtext, known = src.text, src.solution_text

        info = service.source_info(src, problem)
        if known and not explain:                                      # tayyor yechim — AI chaqirilmaydi, limit sarflanmaydi
            AIRequest.objects.create(user=user, subject=subject, problem=problem, source=src, kind="db", question_text=qtext[:2000], answer=known)
            return Response({"status": "ready", "answer": known, "ai_generated": False, "source": info,
                             "can_explain": True, "problem_id": problem.id if problem else None})

        lim = limit_for(user)
        if lim is not None and used_today(user) >= lim:
            return Response({"error": {"status": 429, "detail": f"Kunlik AI limiti tugadi ({lim} ta). Ertaga qayta urinib ko'ring."}}, status=429)

        mode = "explain" if known else "solve"
        key = service.cache_key(mode, subject.id, qtext, known)
        hit = AICache.objects.filter(key=key).first()
        if hit:
            r = AIRequest.objects.create(user=user, subject=subject, problem=problem, source=src, kind="cache", cached=True,
                                         question_text=qtext[:2000], answer=hit.answer)
            return Response({"status": "ready", "answer": hit.answer, "ai_generated": True, "cached": True, "source": info,
                             "request_id": r.id})
        if not settings.ANTHROPIC_API_KEY:
            return Response({"error": {"status": 503, "detail": "AI yordamchi hozircha sozlanmagan (administratorga murojaat qiling)"}}, status=503)

        page = service.page_pdf(src) if src else None

        def gen():
            yield sse("meta", {"ai_generated": True, "cached": False, "source": info, "mode": mode})
            usage, parts, size = {}, [], 0
            try:
                for delta in service.stream_claude(subject.name, mode, qtext, known, page, usage):
                    size += len(delta)
                    if size > service.MAX_ANSWER_CHARS:            # javob uzunligi cheklangan
                        break
                    parts.append(delta)
                    yield sse("delta", {"t": delta})
            except Exception:                                      # noqa
                yield sse("error", {"detail": "AI hozir javob bera olmadi, keyinroq urinib ko'ring"})
                return
            answer = "".join(parts).strip()
            if not answer:
                yield sse("error", {"detail": "AI bo'sh javob qaytardi"}); return
            with transaction.atomic():
                AICache.objects.update_or_create(key=key, defaults={"answer": answer})
                r = AIRequest.objects.create(user=user, subject=subject, problem=problem, source=src, kind="ai",
                                             question_text=qtext[:2000], answer=answer, tokens=usage.get("tokens", 0))
            yield sse("done", {"request_id": r.id})

        resp = StreamingHttpResponse(gen(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp


class ApproveView(APIView):
    """Ustoz AI yechimini tasdiqlab, rasmiy yechim sifatida bazaga saqlaydi."""
    permission_classes = [IsTeacher]

    def post(self, request, pk):
        r = AIRequest.objects.filter(pk=pk, kind__in=["ai", "cache"]).select_related("problem__topic", "source").first()
        if not r or not r.answer:
            raise ValidationError("So'rov topilmadi")
        if r.problem:
            if not request.user.can_manage_subject(r.problem.topic.subject_id):
                raise ValidationError("Bu fan sizga biriktirilmagan")
            r.problem.solution = r.answer; r.problem.save(update_fields=["solution"])
            audit(request.user, "ai_solution_approved", f"problem:{r.problem_id}")
        elif r.source:
            r.source.solution_text, r.source.verified = r.answer, True; r.source.save()
            audit(request.user, "ai_solution_approved", f"source:{r.source_id}")
        else:
            raise ValidationError("Bu yechimni saqlashga masala/manba biriktirilmagan")
        return Response({"saved": True})
