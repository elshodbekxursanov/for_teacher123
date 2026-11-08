from io import BytesIO
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from accounts.models import User
from content.models import Problem, Subject, Topic
from quizzes.models import Attempt

pytestmark = pytest.mark.django_db
PW = "Str0ng!pass9"


def client(username, **kw):
    User.objects.create_user(username, password=PW, access_type="free", **kw)
    c = APIClient()
    tok = c.post("/api/auth/login/", {"username": username, "password": PW}, format="json").data["access"]
    c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
    return c


@pytest.fixture
def base():
    s = Subject.objects.create(name="Algebra", slug="algebra")
    t = Topic.objects.create(subject=s, name="Tenglamalar")
    for i in range(1, 6):
        Problem.objects.create(topic=t, number=i, text=f"q{i}", correct_answer="B", solution=f"sol{i}",
                               option_a="1", option_b="2", option_c="3", option_d="4")
    return s, t


def test_quiz_flow_no_leak_and_grading(base):
    s, t = base
    teacher, student = client("t1", role="teacher"), client("s1")
    r = teacher.post("/api/tests/", {"title": "T1", "subject": s.id, "topics": [t.id], "question_count": 3,
                                     "time_limit": 10, "shuffle": True}, format="json")
    assert r.status_code == 201, r.data
    assert student.post("/api/tests/", {}, format="json").status_code == 403
    assert teacher.post("/api/tests/", {"title": "x", "subject": s.id, "question_count": 99}, format="json").status_code == 400
    start = student.post(f"/api/tests/{r.data['id']}/start/").data
    body = str(start)
    assert len(start["questions"]) == 3 and "correct_answer" not in body and "solution" not in body
    aid = start["id"]
    for q in start["questions"][:2]:
        assert student.post(f"/api/attempts/{aid}/answer/", {"problem": q["id"], "answer": "B"}, format="json").data == {"saved": True}
    assert "correct_answer" not in str(student.get(f"/api/attempts/{aid}/").data)      # davomida sizmaydi
    res = student.post(f"/api/attempts/{aid}/finish/").data
    assert res["finished"] and res["score"] == 2 and res["total"] == 3 and res["percent"] == 66.7
    assert all("solution" in i for i in res["items"])
    assert student.post(f"/api/attempts/{aid}/answer/", {"problem": start["questions"][2]["id"], "answer": "B"}, format="json").status_code == 400
    rows = teacher.get(f"/api/tests/{r.data['id']}/results/").data
    assert rows[0]["score"] == 2
    assert b"s1" in teacher.get(f"/api/tests/{r.data['id']}/results-csv/").content
    assert student.get(f"/api/tests/{r.data['id']}/results/").status_code == 403


def test_deadline_autofinish(base):
    s, t = base
    teacher, student = client("t2", role="teacher"), client("s2")
    tid = teacher.post("/api/tests/", {"title": "T", "subject": s.id, "question_count": 2, "time_limit": 5}, format="json").data["id"]
    a = student.post(f"/api/tests/{tid}/start/").data
    from datetime import timedelta
    from django.utils import timezone
    Attempt.objects.filter(id=a["id"]).update(deadline=timezone.now() - timedelta(minutes=1))
    assert student.post(f"/api/attempts/{a['id']}/answer/", {"problem": a["questions"][0]["id"], "answer": "B"}, format="json").status_code == 400
    assert student.get(f"/api/attempts/{a['id']}/").data["finished"] is True


def xlsx(rows):
    wb = Workbook(); ws = wb.active
    ws.append(["fan", "mavzu", "raqam", "savol", "A", "B", "C", "D", "javob", "yechim", "qiyinlik"])
    for r in rows:
        ws.append(r)
    b = BytesIO(); wb.save(b)
    return SimpleUploadedFile("m.xlsx", b.getvalue())


def test_excel_import_errors_dedupe_rollback(base):
    s, t = base
    teacher, student = client("t3", role="teacher"), client("s3")
    f = xlsx([["Algebra", "Tenglamalar", 1, "yangi q1", "1", "2", "3", "4", "C", "yech", "qiyin"],        # yangilanadi
              ["Algebra", "Yangi mavzu", 7, "q7", "1", "2", "", "", "A", "", "oson"],                    # yaratiladi
              ["Algebra", "Yangi mavzu", 8, "2+2=?", "", "", "", "", "4", "", ""],                       # ochiq
              ["Algebra", "Tenglamalar", 9, "xato", "1", "2", "3", "4", "Z", "", ""],                    # xato javob harfi
              ["Yo'q fan", "X", 1, "q", "", "", "", "", "1", "", ""],                                     # fan yo'q
              ["Algebra", "", 2, "q", "", "", "", "", "1", "", ""]])                                      # bo'sh majburiy
    r = teacher.post("/api/imports/", {"file": f}, format="multipart")
    assert r.status_code == 201 and (r.data["total"], r.data["valid"], r.data["failed"]) == (6, 3, 3), r.data
    assert sorted(e["row"] for e in r.data["errors"]) == [5, 6, 7]
    jid = r.data["id"]
    assert Problem.objects.count() == 5                                  # tasdiqlanguncha yozilmaydi
    c = teacher.post(f"/api/imports/{jid}/confirm/").data
    assert (c["created"], c["updated"]) == (2, 1) and Problem.objects.get(topic=t, number=1).text == "yangi q1"
    assert teacher.post(f"/api/imports/{jid}/confirm/").status_code == 400
    # qayta yuklash dublikat yaratmaydi
    r2 = teacher.post("/api/imports/", {"file": xlsx([["Algebra", "Tenglamalar", 1, "yangi q1", "1", "2", "3", "4", "C", "yech", "qiyin"]])}, format="multipart")
    c2 = teacher.post(f"/api/imports/{r2.data['id']}/confirm/").data
    assert (c2["created"], c2["updated"], c2["skipped"]) == (0, 0, 1) and Problem.objects.count() == 7
    teacher.post(f"/api/imports/{jid}/rollback/")
    assert Problem.objects.count() == 5 and Problem.objects.get(topic=t, number=1).text == "q1"
    assert student.post("/api/imports/", {"file": xlsx([])}, format="multipart").status_code == 403
    assert teacher.post("/api/imports/", {"file": SimpleUploadedFile("a.xlsm", b"x")}, format="multipart").status_code == 400
    assert teacher.get("/api/imports/template/").status_code == 200


def test_excel_unknown_subject_error_and_admin_auto_create(base):
    teacher, admin = client("t5", role="teacher"), client("a5", role="admin")
    rows = [["Fizika", "Mexanika", 1, "q1", "1", "2", "", "", "A", "", "oson"], ["Fizika", "Mexanika", 2, "q2", "", "", "", "", "5", "", ""]]
    r = admin.post("/api/imports/", {"file": xlsx(rows)}, format="multipart")
    assert r.data["valid"] == 0 and r.data["errors"][0]["reason"] == "Fan topilmadi: Fizika"            # standart: aniq xato
    assert teacher.post("/api/imports/", {"file": xlsx(rows), "auto_subjects": "1"}, format="multipart").data["valid"] == 0   # ustoz fan yarata olmaydi
    r = admin.post("/api/imports/", {"file": xlsx(rows), "auto_subjects": "1"}, format="multipart")
    assert (r.data["valid"], r.data["failed"]) == (2, 0) and not Subject.objects.filter(name="Fizika").exists()       # tasdiqlanguncha yaratilmaydi
    c = admin.post(f"/api/imports/{r.data['id']}/confirm/").data
    assert c["created"] == 2 and Subject.objects.get(name="Fizika").slug == "fizika" and Problem.objects.filter(topic__subject__name="Fizika").count() == 2
    admin.post(f"/api/imports/{r.data['id']}/rollback/")
    assert not Subject.objects.filter(name="Fizika").exists() and Problem.objects.count() == 5
