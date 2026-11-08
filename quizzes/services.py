import random
from datetime import timedelta
from django.utils import timezone

from content.serializers import ProblemPublicSerializer

GRACE = timedelta(seconds=15)       # umumiy vaqt uchun tarmoq kechikishi zaxirasi
Q_GRACE = timedelta(seconds=2)      # har bir savol uchun
LET = "ABCD"


# ---------- aralash variantlar: option_order[i] = ko'rsatilgan (LET[i]) variantning ASL harfi ----------
def make_order(problem):
    if problem.type != "test":
        return ""
    letters = [k.upper() for k in "abcd" if getattr(problem, f"option_{k}")]
    random.shuffle(letters)
    return "".join(letters)


def apply_order(data, order):
    if not order:
        return data
    d = dict(data)
    for i, orig in enumerate(order):
        d[f"option_{'abcd'[i]}"] = data[f"option_{orig.lower()}"]
    return d


def to_original(ans, order):
    a = (ans or "").strip().upper()
    if order and len(a) == 1 and a in LET[:len(order)]:
        return order[LET.index(a)]
    return a


def to_display(letter, order):
    L = (letter or "").strip().upper()
    return LET[order.index(L)] if order and L in order else letter


def is_right(row, answer):
    return bool((answer or "").strip()) and row.problem.is_correct_answer(to_original(answer, row.option_order))


def correct_shown(row):
    p = row.problem
    return to_display(p.correct_answer, row.option_order) if p.type == "test" else p.correct_answer


# ---------- baholash va vaqt ----------
def grade(attempt):
    answers = list(attempt.answers.select_related("problem"))
    score = 0
    for a in answers:
        a.is_correct = is_right(a, a.answer)
        score += a.is_correct
        a.save(update_fields=["is_correct"])
    attempt.score, attempt.total = score, len(answers)
    attempt.percent = round(score / len(answers) * 100, 1) if answers else 0
    attempt.finished_at = timezone.now()
    attempt.save()
    return attempt


def ensure_finished(attempt):
    """Umumiy vaqt tugagan bo'lsa, saqlangan javoblar bilan avtomatik yakunlaydi."""
    if not attempt.finished_at and attempt.deadline and timezone.now() > attempt.deadline + GRACE:
        grade(attempt)
    return attempt


def sequential(attempt):
    return attempt.test.question_time > 0


def advance(attempt):
    """Ketma-ket rejim: savol vaqti o'tgan bo'lsa, keyingisiga o'tkazadi (orqaga qaytish yo'q)."""
    if attempt.finished_at or not sequential(attempt):
        return attempt
    total = attempt.answers.count()
    span = timedelta(seconds=attempt.test.question_time)
    now, start, idx = timezone.now(), attempt.question_started_at or attempt.started_at, attempt.current_index
    while idx < total and now > start + span + Q_GRACE:
        idx += 1
        start += span
    if idx != attempt.current_index:
        attempt.current_index, attempt.question_started_at = idx, start
        attempt.save(update_fields=["current_index", "question_started_at"])
    if idx >= total:
        grade(attempt)
    return attempt


def refresh(attempt):
    advance(attempt)
    return ensure_finished(attempt)


def payload(attempt, request):
    ctx = {"request": request}
    t = attempt.test
    answers = list(attempt.answers.select_related("problem__topic__subject"))

    def qdata(a):
        d = apply_order(dict(ProblemPublicSerializer(a.problem, context=ctx).data), a.option_order)
        d["order"] = a.order
        return d

    if not attempt.finished_at:        # test davomida to'g'ri javob va yechim YUBORILMAYDI
        base = {"id": attempt.id, "finished": False, "test": t.title, "deadline": attempt.deadline,
                "sequential": sequential(attempt), "instant_feedback": t.instant_feedback}
        if base["sequential"]:         # faqat joriy savol yuboriladi
            cur = answers[attempt.current_index]
            return {**base, "question_time": t.question_time, "index": attempt.current_index, "total": len(answers),
                    "question_started_at": attempt.question_started_at, "server_now": timezone.now(),
                    "questions": [qdata(cur)], "answers": {str(cur.problem_id): cur.answer} if cur.answer else {}}
        return {**base, "questions": [qdata(a) for a in answers], "answers": {str(a.problem_id): a.answer for a in answers if a.answer}}
    return {"id": attempt.id, "finished": True, "test": t.title, "score": attempt.score, "total": attempt.total,
            "percent": attempt.percent, "started_at": attempt.started_at, "finished_at": attempt.finished_at,
            "duration_seconds": int((attempt.finished_at - attempt.started_at).total_seconds()),
            "items": [{**qdata(a), "your_answer": a.answer, "is_correct": a.is_correct,
                       "correct_answer": correct_shown(a), "solution": a.problem.solution} for a in answers]}
