import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from content.models import PracticeAnswer, Problem, Subject, Topic
from imports.models import ImportJob
from notifications.models import Notification
from quizzes.models import Test

pytestmark = pytest.mark.django_db
PW = "Str0ng!pass9"


def api(username, **kw):
    kw.setdefault("access_type", "free")
    u = User.objects.create_user(username, password=PW, **kw)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + c.post("/api/auth/login/", {"username": username, "password": PW}, format="json").data["access"])
    return c, u


def test_new_test_notifies_students_and_mark_read():
    c, stu = api("stu1")
    api("stu2")
    sub = Subject.objects.create(name="Matematika", slug="mat")
    Test.objects.create(title="Algebra 1", subject=sub, question_count=10)
    r = c.get("/api/notifications/")
    assert r.data["unread"] == 1 and r.data["results"][0]["title"] == "Yangi test"
    assert Notification.objects.count() == 2                      # ikkala o'quvchiga
    assert c.post("/api/notifications/read/").data["unread"] == 0
    assert c.get("/api/notifications/").data["unread"] == 0


def test_notifications_are_private():
    a, ua = api("pa")
    b, _ = api("pb")
    Notification.objects.create(user=ua, title="Faqat A uchun")
    assert b.get("/api/notifications/").data["results"] == []


def test_my_activity_counts_practice_answers():
    c, u = api("act1")
    sub = Subject.objects.create(name="Fizika", slug="fiz")
    top = Topic.objects.create(subject=sub, name="Mexanika")
    p = Problem.objects.create(topic=top, number=1, text="2+2", status="published")
    PracticeAnswer.objects.create(user=u, problem=p, answer="4", is_correct=True)
    d = c.get("/api/stats/activity/?days=7").data
    assert d["days"] == 7 and len(d["series"]) == 7 and d["total"] == 1
    assert d["series"][-1]["date"] == timezone.localdate().isoformat() and d["series"][-1]["count"] == 1


def test_admin_activity_admin_only_and_lists_active_students():
    adm, _ = api("adm9", role="admin")
    stu, u = api("stu9", first_name="Ali")
    sub = Subject.objects.create(name="Kimyo", slug="kim")
    top = Topic.objects.create(subject=sub, name="Atom")
    p = Problem.objects.create(topic=top, number=1, text="x", status="published")
    PracticeAnswer.objects.create(user=u, problem=p, answer="1", is_correct=False)
    assert stu.get("/api/admin/activity/").status_code == 403
    d = adm.get("/api/admin/activity/?days=500").data
    assert d["days"] == 90 and d["active_users"]["week"] == 1
    assert d["active_users"]["top"][0]["name"] == "Ali"


def test_import_list_has_file_info_and_download_is_scoped():
    t1, u1 = api("tch1", role="teacher")
    t2, _ = api("tch2", role="teacher")
    job = ImportJob.objects.create(user=u1, file=SimpleUploadedFile("masalalar.xlsx", b"abc"))
    row = t1.get("/api/imports/").data[0]
    assert row["name"].startswith("masalalar") and row["size"] == 3
    assert b"".join(t1.get(f"/api/imports/{job.id}/download/").streaming_content) == b"abc"
    assert t2.get(f"/api/imports/{job.id}/download/").status_code == 404
