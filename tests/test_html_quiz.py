import pathlib
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from content.models import Problem, Subject, Topic
from quizzes import htmlimport
from quizzes.models import Attempt, Test

pytestmark = pytest.mark.django_db
PW = "Str0ng!pass9"
SAMPLE = (pathlib.Path(__file__).parent / "fixtures" / "kasrlar_test.html").read_bytes()


def client(username, **kw):
    User.objects.create_user(username, password=PW, access_type="free", **kw)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + c.post("/api/auth/login/", {"username": username, "password": PW}, format="json").data["access"])
    return c


def up(c, data=SAMPLE, name="test.html", **extra):
    return c.post("/api/tests/import-html/", {"file": SimpleUploadedFile(name, data), **extra}, format="multipart")


def test_parse_sample_file():
    r = htmlimport.parse(SAMPLE)
    assert r["title"] == "Kasrlar ustida amallar" and len(r["questions"]) == 20 and not r["errors"]
    assert (r["question_time"], r["total_seconds"]) == (60, 1500)
    assert all(q["correct"] == 0 for q in r["questions"]) and any("birinchi variantda" in w for w in r["warnings"])


def test_parse_without_json5(monkeypatch):
    monkeypatch.setattr(htmlimport, "json5", None)
    assert len(htmlimport.parse(SAMPLE)["questions"]) == 20


def test_parse_rejects_bad_questions():
    bad = b"""<title>X</title><script>const QUESTIONS=[
      {question:"a?", options:["1","2","3","4","5"], answer:0},
      {question:"b?", options:["1","2"], answer:7},
      {question:"c?", options:["1","2"], answer:"B"},
      {question:"<b>d</b>?", options:["x","y"], answer:"y"}];</script>"""
    r = htmlimport.parse(bad)
    assert [e["n"] for e in r["errors"]] == [1, 2] and [q["correct"] for q in r["questions"]] == [1, 1]
    assert r["questions"][1]["q"] == "d?" and any("teglar" in w for w in r["warnings"])
    assert htmlimport.parse(b"<html>hech narsa yo'q</html>")["errors"][0]["n"] == 0


def test_import_dry_run_import_duplicate_and_permissions():
    s = Subject.objects.create(name="Matematika", slug="mat")
    tch, stu = client("t1", role="teacher"), client("s1")
    assert up(stu, subject=s.id).status_code == 403
    assert up(tch, name="a.exe", subject=s.id).status_code == 400
    prev = up(tch, dry_run="1").data
    assert len(prev["questions"]) == 20 and prev["duplicate"] is None and Test.objects.count() == 0       # ko'rib chiqish hech narsa yozmaydi
    r = up(tch, subject=s.id)
    assert r.status_code == 201 and r.data["imported"] == 20
    t = Test.objects.get()
    assert (t.question_count, t.time_limit, t.question_time, t.shuffle_options, t.instant_feedback) == (20, 25, 60, True, True)
    assert Topic.objects.get().name == "Kasrlar ustida amallar" and Problem.objects.count() == 20
    letters = set(Problem.objects.values_list("correct_answer", flat=True))
    assert len(letters) > 1                                                      # bazada hammasi "A" emas
    for p in Problem.objects.all():                                              # to'g'ri javob matni saqlangan
        assert getattr(p, "option_" + p.correct_answer.lower()) in htmlimport.parse(SAMPLE)["questions"][p.number - 1]["options"]
    assert up(tch, subject=s.id).status_code == 409 and up(tch, dry_run="1").data["duplicate"] == t.id
    assert Test.objects.count() == 1 and Problem.objects.count() == 20


def test_sequential_quiz_with_feedback_and_shuffled_options():
    s = Subject.objects.create(name="Matematika", slug="mat")
    tch, stu = client("t2", role="teacher"), client("s2")
    up(tch, subject=s.id)
    tid = Test.objects.get().id
    start = stu.post(f"/api/tests/{tid}/start/").data
    aid = start["id"]
    assert start["sequential"] and start["question_time"] == 60 and start["total"] == 20 and start["index"] == 0
    assert len(start["questions"]) == 1 and "correct_answer" not in str(start) and "solution" not in str(start)
    expected = 0
    for i in range(20):
        cur = stu.get(f"/api/attempts/{aid}/").data
        q = cur["questions"][0]
        assert cur["index"] == i
        r = stu.post(f"/api/attempts/{aid}/answer/", {"problem": q["id"], "answer": "A"}, format="json").data
        assert r["saved"] and r["correct"] in "ABCD"
        expected += r["is_correct"]
        assert stu.post(f"/api/attempts/{aid}/answer/", {"problem": q["id"], "answer": "B"}, format="json").status_code == 400    # javob qulflanadi
        out = stu.post(f"/api/attempts/{aid}/next/", {"from_index": i}, format="json").data
        assert stu.post(f"/api/attempts/{aid}/next/", {"from_index": i}, format="json").data.get("index", 99) in (i + 1, 99) or out["finished"]
    res = stu.get(f"/api/attempts/{aid}/").data
    assert res["finished"] and res["total"] == 20 and res["score"] == expected
    for it in res["items"]:                                                       # aralash variantlarda ko'rsatilgan harf bo'yicha mos
        assert it["is_correct"] == (it["your_answer"] == it["correct_answer"])
    assert len({tuple(it[f"option_{k}"] for k in "abcd") for it in res["items"]}) == 20
    xl = tch.get(f"/api/tests/{tid}/results-xlsx/")
    assert xl.status_code == 200 and xl["Content-Type"].startswith("application/vnd.openxmlformats")
    assert stu.get(f"/api/tests/{tid}/results-xlsx/").status_code == 403


def test_question_timeout_advances_and_total_deadline():
    s = Subject.objects.create(name="Matematika", slug="mat")
    tch, stu = client("t3", role="teacher"), client("s3")
    up(tch, subject=s.id)
    tid = Test.objects.get().id
    a = stu.post(f"/api/tests/{tid}/start/").data
    first = a["questions"][0]["id"]
    Attempt.objects.filter(id=a["id"]).update(question_started_at=timezone.now() - timedelta(seconds=125))   # 2 savol vaqti o'tdi
    cur = stu.get(f"/api/attempts/{a['id']}/").data
    assert cur["index"] == 2 and cur["questions"][0]["id"] != first
    assert stu.post(f"/api/attempts/{a['id']}/answer/", {"problem": first, "answer": "A"}, format="json").status_code == 400
    Attempt.objects.filter(id=a["id"]).update(deadline=timezone.now() - timedelta(minutes=1))
    done = stu.get(f"/api/attempts/{a['id']}/").data
    assert done["finished"] and done["score"] == 0 and done["total"] == 20


def test_standalone_html_test_without_subject_and_delete():
    tch, stu = client("t4", role="teacher"), client("s4")
    r = up(tch)                                                  # fan ham, mavzu ham berilmaydi
    assert r.status_code == 201, r.data
    t = Test.objects.get()
    assert t.subject is None and t.is_published
    assert Problem.objects.count() == 20 and set(Problem.objects.values_list("status", flat=True)) == {"draft"}
    assert Subject.objects.get().is_active is False                                           # Fanlar ro'yxatida ko'rinmaydi
    assert stu.get("/api/subjects/").data == []
    assert stu.get("/api/problems/").data["count"] == 0                                       # masalalar bazasini to'ldirmaydi
    lst = stu.get("/api/tests/").data
    assert len(lst) == 1 and lst[0]["subject_name"] == "" and lst[0]["question_time"] == 60
    a = stu.post(f"/api/tests/{t.id}/start/").data
    for i in range(20):
        q = stu.get(f"/api/attempts/{a['id']}/").data["questions"][0]
        stu.post(f"/api/attempts/{a['id']}/answer/", {"problem": q["id"], "answer": "A"}, format="json")
        stu.post(f"/api/attempts/{a['id']}/next/", {"from_index": i}, format="json")
    res = stu.get(f"/api/attempts/{a['id']}/").data
    assert res["finished"] and res["total"] == 20 and len(res["items"]) == 20
    assert tch.patch(f"/api/tests/{t.id}/", {"is_published": False}, format="json").status_code == 200
    assert stu.get("/api/tests/").data == []                                                  # yashirilgan test ko'rinmaydi
    assert stu.delete(f"/api/tests/{t.id}/").status_code == 403
    assert tch.delete(f"/api/tests/{t.id}/").status_code == 204
    assert Test.objects.count() == 0 and Problem.objects.count() == 0 and Attempt.objects.count() == 0
    assert up(tch).status_code == 201                                                         # o'chirilgach qayta joylash mumkin
