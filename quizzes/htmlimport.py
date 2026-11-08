"""HTML viktorina faylini (RAW_QUESTIONS massivi bor) o'qib, saytga tayyor test qilib joylash.
Yuklangan HTML HECH QACHON bajarilmaydi va foydalanuvchilarga berilmaydi — faqat matn sifatida tahlil qilinadi."""
import hashlib, html, json, math, random, re

from django.db import transaction
from django.db.models import Max

from content.models import Problem, Subject, Topic
from .models import Test, TestQuestion

try:
    import json5
except ImportError:                        # noqa
    json5 = None

MAX_BYTES = 2 * 1024 * 1024
MAX_QUESTIONS = 200
QKEYS = ("q", "question", "text", "savol", "title", "name")
OKEYS = ("opts", "options", "variants", "choices", "answers", "javoblar")
CKEYS = ("correct", "answer", "correctIndex", "correct_index", "right", "javob")
TAG = re.compile(r"<[^>]+>")


def _match_bracket(s, i):
    """s[i] ('[' yoki '{') ga mos yopuvchi qavs indeksi; satr va izohlar hisobga olinadi."""
    n, depth, j = len(s), 0, i
    while j < n:
        c = s[j]
        if c in "\"'`":
            q = c; j += 1
            while j < n and s[j] != q:
                j += 2 if s[j] == "\\" else 1
        elif c == "/" and s[j:j + 2] == "//":
            k = s.find("\n", j); j = n if k == -1 else k; continue
        elif c == "/" and s[j:j + 2] == "/*":
            k = s.find("*/", j + 2); j = n if k == -1 else k + 1
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _loads(text):
    if json5:
        return json5.loads(text)
    t = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text)       # kalitlarni qo'shtirnoqqa olish
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return json.loads(t)


def _first(d, keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


def _clean(v):
    s = html.unescape(TAG.sub("", str(v))).strip()
    return s


def _correct_index(raw, opts):
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)) and float(raw).is_integer():
        i = int(raw); return i if 0 <= i < len(opts) else None
    if isinstance(raw, str):
        t = raw.strip()
        if t.isdigit():
            i = int(t); return i if 0 <= i < len(opts) else None
        if len(t) == 1 and t.upper() in "ABCD"[:len(opts)]:
            return "ABCD".index(t.upper())
        for i, o in enumerate(opts):
            if o == _clean(t):
                return i
    return None


def _find_questions(src):
    best = (0, None)
    for m in re.finditer(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[", src):
        start = m.end() - 1
        end = _match_bracket(src, start)
        if end < 0:
            continue
        try:
            arr = _loads(src[start:end + 1])
        except Exception:                  # noqa
            continue
        good = [x for x in arr if isinstance(x, dict) and _first(x, QKEYS) is not None and isinstance(_first(x, OKEYS), list)] if isinstance(arr, list) else []
        if len(good) > best[0]:
            best = (len(good), arr)
    return best[1]


def _seconds(src, names):
    m = re.search(rf"(?:const|let|var)\s+(?:{'|'.join(names)})\s*=\s*(\d+)(?:\s*\*\s*(\d+))?\s*[;,\n/]", src, re.I)
    return int(m.group(1)) * int(m.group(2) or 1) if m else 0


def parse(raw_bytes):
    src = raw_bytes.decode("utf-8", errors="ignore")
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", src, re.S | re.I) or re.search(r"<h1[^>]*>(.*?)</h1>", src, re.S | re.I)
    if m:
        title = re.split(r"\s[—–-]\s", _clean(m.group(1)))[0].strip()[:200]
    res = {"title": title or "Test", "question_time": _seconds(src, ["QUESTION_TIME", "QUESTION_SECONDS", "TIME_PER_QUESTION", "PER_QUESTION"]),
           "total_seconds": _seconds(src, ["TOTAL_TIME", "TOTAL_SECONDS", "QUIZ_TIME", "TEST_TIME"]),
           "questions": [], "errors": [], "warnings": []}
    arr = _find_questions(src)
    if not arr:
        res["errors"].append({"n": 0, "reason": "Fayldan savollar massivi topilmadi (masalan: const RAW_QUESTIONS = [ {q:\"..\", opts:[..], correct:0}, ... ])"})
        return res
    if len(arr) > MAX_QUESTIONS:
        res["errors"].append({"n": 0, "reason": f"Savollar {MAX_QUESTIONS} tadan oshmasligi kerak"}); return res
    stripped = False
    for n, item in enumerate(arr, 1):
        if not isinstance(item, dict):
            res["errors"].append({"n": n, "reason": "Savol obyekt emas"}); continue
        q_raw, o_raw = _first(item, QKEYS), _first(item, OKEYS)
        stripped = stripped or TAG.search(str(q_raw) + "".join(map(str, o_raw or []))) is not None
        q = _clean(q_raw) if q_raw is not None else ""
        opts = [_clean(o) for o in o_raw] if isinstance(o_raw, list) else []
        if not q or len(q) > 5000:
            res["errors"].append({"n": n, "reason": "Savol matni bo'sh yoki juda uzun"}); continue
        if not 2 <= len(opts) <= 4:
            res["errors"].append({"n": n, "reason": f"Variantlar soni 2–4 bo'lishi kerak (hozir {len(opts)})"}); continue
        if any(not o or len(o) > 500 for o in opts):
            res["errors"].append({"n": n, "reason": "Variant bo'sh yoki juda uzun"}); continue
        if len(set(opts)) != len(opts):
            res["errors"].append({"n": n, "reason": "Variantlar takrorlangan"}); continue
        ci = _correct_index(_first(item, CKEYS), opts)
        if ci is None:
            res["errors"].append({"n": n, "reason": "To'g'ri javob aniqlanmadi (indeks, A–D harfi yoki variant matni bo'lishi kerak)"}); continue
        res["questions"].append({"q": q, "options": opts, "correct": ci})
    if stripped:
        res["warnings"].append("Matndagi HTML teglar olib tashlandi")
    qs = res["questions"]
    if len(qs) >= 5 and sum(x["correct"] == 0 for x in qs) / len(qs) > 0.8:
        res["warnings"].append("Deyarli hamma to'g'ri javob birinchi variantda — saytga joylashda variantlar tasodifiy aralashtiriladi va test paytida har bir o'quvchiga alohida aralashadi")
    if not res["question_time"]:
        res["warnings"].append("Savol vaqti topilmadi — test savol vaqtisiz (erkin navigatsiya) rejimida bo'ladi")
    return res


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@transaction.atomic
def create_test(user, subject, topic_name, parsed, publish, dig):
    """subject berilmasa: savollar yashirin "HTML testlar" fanida qoralama sifatida saqlanadi (faqat test ichida ko'rinadi)."""
    hidden = subject is None
    inner = Subject.objects.get_or_create(slug="html-testlar", defaults={"name": "HTML testlar", "is_active": False})[0] if hidden else subject
    topic = Topic.objects.filter(subject=inner, name__iexact=topic_name).first() or Topic.objects.create(subject=inner, name=topic_name[:200])
    start = (topic.problems.aggregate(m=Max("number"))["m"] or 0) + 1
    rng, qs = random.Random(dig), parsed["questions"]
    problems = []
    for i, q in enumerate(qs):
        perm = list(range(len(q["options"]))); rng.shuffle(perm)       # bazada ham to'g'ri javob doim "A" bo'lib qolmasin
        opts = [q["options"][k] for k in perm]
        diff = "easy" if i < len(qs) / 3 else "medium" if i < 2 * len(qs) / 3 else "hard"      # fayl "osondan murakkabga" tartiblangan
        problems.append(Problem.objects.create(
            topic=topic, number=start + i, text=q["q"], type="test", correct_answer="ABCD"[perm.index(q["correct"])],
            difficulty=diff, status="draft" if hidden else "published", created_by=user, **{f"option_{'abcd'[j]}": o for j, o in enumerate(opts)}))
    total = parsed["total_seconds"]
    test = Test.objects.create(
        title=parsed["title"], subject=subject, question_count=len(qs), time_limit=math.ceil(total / 60) if total else 0,
        question_time=parsed["question_time"], shuffle=False, shuffle_options=True, instant_feedback=bool(parsed["question_time"]),
        is_published=publish, created_by=user, source_hash=dig)
    test.topics.set([topic])
    TestQuestion.objects.bulk_create([TestQuestion(test=test, problem=p, order=i) for i, p in enumerate(problems)])
    return test
