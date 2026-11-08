from collections import defaultdict
from django.db.models import Count, Q, Sum
from datetime import timedelta
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasActiveAccess, IsAdminRole, IsTeacher
from assistant.models import AIRequest
from content.models import PracticeAnswer, Problem, Subject
from payments.models import Payment
from quizzes.models import Attempt, AttemptAnswer, Test


class MyStats(APIView):
    """O'quvchi: fanlar bo'yicha yechilgan masalalar foizi, aniqlik, qiynalgan mavzular, test tarixi."""
    permission_classes = [HasActiveAccess]

    def get(self, request):
        u = request.user
        pa = PracticeAnswer.objects.filter(user=u).values_list("problem_id", "problem__topic_id", "problem__topic__name", "problem__topic__subject_id", "is_correct")
        ta = AttemptAnswer.objects.filter(attempt__user=u, attempt__finished_at__isnull=False, is_correct__isnull=False) \
            .values_list("problem_id", "problem__topic_id", "problem__topic__name", "problem__topic__subject_id", "is_correct")
        solved, per_subj, per_topic = defaultdict(set), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0, "", 0])
        for pid, tid, tname, sid, ok in list(pa) + list(ta):
            per_subj[sid][0] += 1; per_subj[sid][1] += ok
            t = per_topic[tid]; t[0] += 1; t[1] += ok; t[2] = tname; t[3] = sid
            if ok:
                solved[sid].add(pid)
        totals = dict(Problem.objects.filter(status="published").values_list("topic__subject_id").annotate(c=Count("id")))
        subjects = []
        for s in Subject.objects.filter(is_active=True):
            n, c = per_subj[s.id]; tot = totals.get(s.id, 0)
            subjects.append({"id": s.id, "name": s.name, "icon": s.icon, "total_problems": tot, "solved": len(solved[s.id]),
                             "percent_solved": round(len(solved[s.id]) / tot * 100, 1) if tot else 0,
                             "answers": n, "correct": c, "accuracy": round(c / n * 100, 1) if n else None})
        names = dict(Subject.objects.values_list("id", "name"))
        weak = sorted(({"topic_id": tid, "topic": v[2], "subject": names.get(v[3], ""), "answers": v[0], "accuracy": round(v[1] / v[0] * 100, 1)}
                       for tid, v in per_topic.items() if v[0] >= 3 and v[1] / v[0] < 0.6), key=lambda x: x["accuracy"])[:5]
        att = Attempt.objects.filter(user=u, finished_at__isnull=False)
        avg = att.aggregate(a=Sum("percent"), n=Count("id"))
        return Response({"subjects": subjects, "struggling": weak,
                         "tests": {"count": avg["n"], "avg_percent": round(avg["a"] / avg["n"], 1) if avg["n"] else 0}})


class TeacherStats(APIView):
    """Ustoz: o'z o'quvchilari natijalari va eng ko'p xato qilingan masalalar."""
    permission_classes = [IsTeacher]

    def get(self, request):
        tests = Test.objects.all() if request.user.is_admin_role else Test.objects.filter(created_by=request.user)
        att = Attempt.objects.filter(test__in=tests, finished_at__isnull=False).select_related("user")
        students = defaultdict(lambda: {"attempts": 0, "sum": 0.0, "last": None, "name": "", "username": ""})
        for a in att:
            s = students[a.user_id]; s["attempts"] += 1; s["sum"] += a.percent
            s["name"], s["username"] = a.user.first_name or a.user.username, a.user.username
            s["last"] = max(filter(None, [s["last"], a.finished_at]))
        rows = [{"user": k, "name": v["name"], "username": v["username"], "attempts": v["attempts"],
                 "avg_percent": round(v["sum"] / v["attempts"], 1), "last": v["last"]} for k, v in students.items()]
        hard = AttemptAnswer.objects.filter(attempt__in=att, is_correct__isnull=False).values(
            "problem_id", "problem__number", "problem__topic__name", "problem__text").annotate(
            total=Count("id"), wrong=Count("id", filter=Q(is_correct=False))).filter(total__gte=2).order_by("-wrong")[:10]
        return Response({"students": sorted(rows, key=lambda r: r["avg_percent"]),
                         "hardest": [{"problem": h["problem_id"], "number": h["problem__number"], "topic": h["problem__topic__name"],
                                      "text": h["problem__text"][:140], "wrong": h["wrong"], "total": h["total"],
                                      "error_rate": round(h["wrong"] / h["total"] * 100, 1)} for h in hard if h["wrong"]],
                         "tests": tests.count()})


class AdminStats(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        now = timezone.now()
        users = User.objects.all()
        paid = Payment.objects.filter(status="paid")
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        by_month = paid.annotate(m=TruncMonth("paid_at")).values("m").annotate(n=Count("id"), s=Sum("amount")).order_by("-m")[:6]
        return Response({
            "users": {"total": users.count(), "students": users.filter(role="student").count(), "teachers": users.filter(role="teacher").count(),
                      "free": users.filter(access_type="free").count(), "blocked": users.filter(is_active=False).count(),
                      "paid_active": users.filter(access_type="paid", valid_until__gt=now, is_active=True).count()},
            "content": {"problems": Problem.objects.count(), "published": Problem.objects.filter(status="published").count(),
                        "tests": Test.objects.count(), "attempts": Attempt.objects.filter(finished_at__isnull=False).count()},
            "ai": {"today": AIRequest.objects.filter(created_at__gte=start, kind__in=["ai", "cache"]).count(),
                   "total": AIRequest.objects.filter(kind__in=["ai", "cache"]).count(),
                   "cached": AIRequest.objects.filter(kind="cache").count(), "tokens": AIRequest.objects.aggregate(t=Sum("tokens"))["t"] or 0},
            "payments": {"count": paid.count(), "revenue": paid.aggregate(s=Sum("amount"))["s"] or 0, "pending": Payment.objects.filter(status="pending").count(),
                         "by_month": [{"month": r["m"].strftime("%Y-%m") if r["m"] else "", "count": r["n"], "revenue": r["s"]} for r in by_month]}})


def _days(request):
    try:
        return max(7, min(90, int(request.query_params.get("days", 30))))
    except ValueError:
        return 30


def _series(sources, days):
    """sources: [(queryset, sana_maydoni)] -> kunlar bo'yicha hodisalar soni (bo'sh kunlar 0)."""
    today = timezone.localdate()
    first = today - timedelta(days=days - 1)
    acc = defaultdict(int)
    for qs, field in sources:
        rows = qs.filter(**{f"{field}__date__gte": first}).annotate(d=TruncDate(field)).values("d").annotate(n=Count("id"))
        for r in rows:
            acc[r["d"]] += r["n"]
    return [{"date": (first + timedelta(days=i)).isoformat(), "count": acc[first + timedelta(days=i)]} for i in range(days)]


class MyActivity(APIView):
    """O'quvchining kunlik faolligi: mashq javoblari + yakunlangan testlar + AI so'rovlar."""
    permission_classes = [HasActiveAccess]

    def get(self, request):
        u, days = request.user, _days(request)
        series = _series([(PracticeAnswer.objects.filter(user=u), "created_at"),
                          (Attempt.objects.filter(user=u, finished_at__isnull=False), "finished_at"),
                          (AIRequest.objects.filter(user=u), "created_at")], days)
        return Response({"days": days, "total": sum(x["count"] for x in series), "series": series})


class AdminActivity(APIView):
    """Platforma bo'yicha kunlik faollik va oxirgi 7 kunda faol o'quvchilar."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        days = _days(request)
        series = _series([(PracticeAnswer.objects.all(), "created_at"),
                          (Attempt.objects.filter(finished_at__isnull=False), "finished_at"),
                          (AIRequest.objects.all(), "created_at")], days)
        now = timezone.now()
        week, prev = now - timedelta(days=7), now - timedelta(days=14)

        def active(a, b=None):
            ids = set()
            for qs, f in ((PracticeAnswer.objects, "created_at"), (Attempt.objects.filter(finished_at__isnull=False), "finished_at"), (AIRequest.objects, "created_at")):
                q = qs.filter(**{f"{f}__gte": a})
                if b:
                    q = q.filter(**{f"{f}__lt": b})
                ids |= set(q.values_list("user_id", flat=True))
            return ids

        cur, before = active(week), active(prev, week)
        users = {u.id: u for u in User.objects.filter(id__in=cur, role="student")}
        counts = defaultdict(int)
        for qs, f in ((PracticeAnswer.objects, "created_at"), (Attempt.objects.filter(finished_at__isnull=False), "finished_at"), (AIRequest.objects, "created_at")):
            for uid, n in qs.filter(**{f"{f}__gte": week, "user_id__in": list(users)}).values_list("user_id").annotate(n=Count("id")):
                counts[uid] += n
        top = sorted(users.values(), key=lambda x: -counts[x.id])[:12]
        change = round((len(cur) - len(before)) / len(before) * 100) if before else None
        return Response({"days": days, "total": sum(x["count"] for x in series), "series": series,
                         "active_users": {"week": len(cur), "total_students": User.objects.filter(role="student", is_active=True).count(),
                                          "change_percent": change,
                                          "top": [{"id": x.id, "name": x.first_name or x.username, "events": counts[x.id]} for x in top]}})
