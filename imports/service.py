"""Excel (.xlsx) import: faqat QIYMATLAR o'qiladi (data_only), formula/makro bajarilmaydi."""
from io import BytesIO
from openpyxl import Workbook, load_workbook

from content.models import Problem, Subject, Topic

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
HEADERS = ["fan", "mavzu", "raqam", "savol", "A", "B", "C", "D", "javob", "yechim", "qiyinlik"]
DIFF = {"oson": "easy", "easy": "easy", "orta": "medium", "o'rta": "medium", "o‘rta": "medium", "medium": "medium",
        "qiyin": "hard", "hard": "hard", "": "medium"}


def template_bytes():
    wb = Workbook(); ws = wb.active; ws.title = "Masalalar"
    ws.append(HEADERS)
    ws.append(["Algebra", "Tenglamalar", 1, "$x+9=15$", "5", "6", "7", "8", "B", "$x=15-9=6$", "oson"])
    ws.append(["Algebra", "Tenglamalar", 2, "$2x=10$ bo'lsa, $x$ nechaga teng?", "", "", "", "", "5", "$x=10/2$", "o'rta"])
    for col, w in zip("ABCDEFGHIJK", [14, 18, 8, 40, 12, 12, 12, 12, 10, 30, 10]):
        ws.column_dimensions[col].width = w
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def read_excel(fileobj):
    """.xlsx -> records (har biri: row, fan, mavzu, raqam, savol, a..d, javob, yechim, qiyinlik)."""
    try:
        wb = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception:
        raise ValueError("Fayl .xlsx formatida emas yoki buzilgan")
    it = wb.worksheets[0].iter_rows(values_only=True)
    head = [(_s(h)).lower() for h in next(it, [])]
    miss = [h for h in ("fan", "mavzu", "raqam", "savol", "javob") if h not in head]
    if miss:
        raise ValueError("Ustunlar topilmadi: " + ", ".join(miss))
    idx = {h: head.index(h) for h in head if h}
    records = []
    for n, r in enumerate(it, start=2):
        if not any(_s(c) for c in r):
            continue
        records.append({"row": n, **{k: (_s(r[i]) if i < len(r) else "") for k, i in idx.items()}})
        if len(records) > MAX_ROWS:
            raise ValueError(f"Qatorlar {MAX_ROWS} tadan oshmasligi kerak")
    return records


def validate(records, user=None, auto_subjects=False):
    """records -> (valid_rows, errors, total). Excel va PDF uchun bir xil qoidalar."""
    subjects = {s.name.casefold(): s for s in Subject.objects.filter(is_active=True)}
    rows, errors, seen = [], [], set()
    for r in records:
        get = lambda k: _s(r.get(k, ""))
        n, page = r["row"], r.get("page")
        subj = subjects.get(get("fan").casefold())
        # Administrator "avtomatik yaratish" ni yoqqan bo'lsa, yo'q fan tasdiqlashda yaratiladi (bu yerda hech narsa yozilmaydi)
        virtual = bool(not subj and auto_subjects and user is not None and user.is_admin_role and 0 < len(get("fan")) <= 100)
        sid = subj.id if subj else "new:" + get("fan").casefold()
        topic, text, ans = get("mavzu"), get("savol"), get("javob")
        opts = {k: get(k) for k in ("a", "b", "c", "d")}
        try:
            num = int(float(get("raqam")))
        except ValueError:
            num = 0
        filled = [k for k, v in opts.items() if v]
        err = None
        if not get("fan") or not topic or not text or not ans or not get("raqam"):
            err = "Majburiy maydon bo'sh (fan, mavzu, raqam, savol, javob)" + (" — javob topilmadi" if not ans and text else "")
        elif not subj and not virtual:
            err = f"Fan topilmadi: {get('fan')}"
        elif subj and user is not None and not user.can_manage_subject(subj.id):
            err = "Bu fan sizga biriktirilmagan"
        elif num <= 0:
            err = "Raqam musbat butun son bo'lishi kerak"
        elif len(topic) > 200 or len(text) > 5000 or any(len(v) > 500 for v in opts.values()) or len(ans) > 500:
            err = "Matn uzunligi chegaradan oshdi"
        elif get("qiyinlik").lower() not in DIFF:
            err = "Qiyinlik: oson / o'rta / qiyin"
        elif filled and (len(filled) < 2 or ans.upper() not in "ABCD" or len(ans) != 1 or not opts[ans.lower()]):
            err = "Test uchun kamida 2 variant va javob A/B/C/D (to'ldirilgan variant) bo'lishi kerak"
        elif (sid, topic.casefold(), num) in seen:
            err = "Takrorlangan (fan+mavzu+raqam)"
        if err:
            errors.append({"row": n, "reason": err, **({"page": page} if page else {}), "topic": topic, "number": num or get("raqam")})
            continue
        seen.add((sid, topic.casefold(), num))
        rows.append({"row": n, "page": page, "subject": subj.id if subj else None, "subject_name": subj.name if subj else get("fan").strip(), "topic": topic, "number": num, "text": text,
                     "type": "test" if filled else "open", "a": opts["a"], "b": opts["b"], "c": opts["c"], "d": opts["d"],
                     "answer": ans.upper() if filled else ans, "solution": get("yechim"),
                     "difficulty": DIFF[get("qiyinlik").lower()]})
    return rows, errors, len(records)


def parse(fileobj, user=None, auto_subjects=False):
    return validate(read_excel(fileobj), user, auto_subjects)


FIELDS = ["text", "type", "option_a", "option_b", "option_c", "option_d", "correct_answer", "solution", "difficulty"]


def _slug(name):
    from django.utils.text import slugify
    base = slugify(name)[:40] or "fan"
    slug, i = base, 2
    while Subject.objects.filter(slug=slug).exists():
        slug, i = f"{base}-{i}", i + 1
    return slug


def apply(job, user):
    created_ids, created_topics, created_subjects, updated, c, u, s = [], [], [], [], 0, 0, 0
    new_subj = {}
    for r in job.rows:
        sid = r["subject"]
        if sid is None:                                  # avtomatik yaratiladigan fan
            key = r["subject_name"].casefold()
            if key not in new_subj:
                found = Subject.objects.filter(name__iexact=r["subject_name"]).first()
                if not found:
                    found = Subject.objects.create(name=r["subject_name"], slug=_slug(r["subject_name"]))
                    created_subjects.append(found.id)
                new_subj[key] = found.id
            sid = new_subj[key]
        topic = Topic.objects.filter(subject_id=sid, name__iexact=r["topic"]).first()
        if not topic:
            topic = Topic.objects.create(subject_id=sid, name=r["topic"])
            created_topics.append(topic.id)
        vals = dict(text=r["text"], type=r["type"], option_a=r["a"], option_b=r["b"], option_c=r["c"],
                    option_d=r["d"], correct_answer=r["answer"], solution=r["solution"], difficulty=r["difficulty"])
        p = Problem.objects.filter(topic=topic, number=r["number"]).first()
        if not p:
            p = Problem.objects.create(topic=topic, number=r["number"], created_by=user, status="published", **vals)
            created_ids.append(p.id); c += 1
        elif any(getattr(p, k) != v for k, v in vals.items()):
            updated.append({"id": p.id, **{k: getattr(p, k) for k in FIELDS}})
            for k, v in vals.items():
                setattr(p, k, v)
            p.save(); u += 1
        else:
            s += 1
    job.created, job.updated, job.skipped, job.status = c, u, s, "confirmed"
    job.undo = {"created": created_ids, "topics": created_topics, "subjects": created_subjects, "updated": updated}
    job.save()


def rollback(job):
    Problem.objects.filter(id__in=job.undo.get("created", [])).delete()
    for snap in job.undo.get("updated", []):
        Problem.objects.filter(id=snap["id"]).update(**{k: snap[k] for k in FIELDS})
    Topic.objects.filter(id__in=job.undo.get("topics", []), problems__isnull=True).delete()
    Subject.objects.filter(id__in=job.undo.get("subjects", []), topics__isnull=True).delete()
    job.status = "rolled_back"
    job.save()
