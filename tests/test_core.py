import pytest
from django.conf import settings
from rest_framework.test import APIClient
from accounts.models import User
from content.models import Problem, Subject, Topic

pytestmark = pytest.mark.django_db


def sign(body):
    return hmac.new(settings.PAYMENT_CALLBACK_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def data():
    s = Subject.objects.create(name="Algebra", slug="algebra")
    s2 = Subject.objects.create(name="Ingliz tili", slug="ingliz")
    t = Topic.objects.create(subject=s, name="Tenglamalar")
    t2 = Topic.objects.create(subject=s2, name="Grammar")
    p = Problem.objects.create(topic=t, number=1, text="$x+1=2$", correct_answer="B", solution="x=1", option_a="0", option_b="1")
    Problem.objects.create(topic=t2, number=1, text="She ___ home", correct_answer="A")
    return s, t, p


def login(c, u, pw="Str0ng!pass9"):
    r = c.post("/api/auth/login/", {"username": u, "password": pw}, format="json")
    assert r.status_code == 200, r.content
    c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])


def test_anonymous_blocked(data):
    assert APIClient().get("/api/subjects/").status_code == 401


def _register(c, username, plan="1m"):
    r = c.post("/api/auth/register/", {"first_name": "Ali", "username": username, "password": "Str0ng!pass9", "plan": plan}, format="json")
    assert r.status_code == 201
    assert r.data["checkout"]["payme"].startswith("https://test.paycom.uz/") and "my.click.uz" in r.data["checkout"]["click"]
    return r


PAYME_AUTH = {"HTTP_AUTHORIZATION": "Basic " + __import__("base64").b64encode(f"Paycom:{settings.PAYME_KEY}".encode()).decode()}


def rpc(method, params, auth=True, rid=1):
    return APIClient().post("/api/payments/payme/", {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
                            format="json", **(PAYME_AUTH if auth else {})).data


def test_payme_full_flow_and_activation(data):
    c = APIClient()
    r = _register(c, "ali")
    login(c, "ali")
    assert c.get("/api/subjects/").status_code == 403                 # to'lanmagan: faqat to'lov
    oid, acc = r.data["payment_id"], {"order_id": r.data["payment_id"]}
    assert rpc("CheckPerformTransaction", {"amount": 500000, "account": acc}, auth=False)["error"]["code"] == -32504
    assert rpc("CheckPerformTransaction", {"amount": 123, "account": acc})["error"]["code"] == -31001
    assert rpc("CheckPerformTransaction", {"amount": 500000, "account": {"order_id": 99999}})["error"]["code"] == -31050
    assert rpc("CheckPerformTransaction", {"amount": 500000, "account": acc})["result"] == {"allow": True}
    t = rpc("CreateTransaction", {"id": "abc1", "time": 1, "amount": 500000, "account": acc})["result"]
    assert t["state"] == 1
    assert rpc("CreateTransaction", {"id": "abc1", "time": 1, "amount": 500000, "account": acc})["result"]["create_time"] == t["create_time"]
    assert rpc("CreateTransaction", {"id": "other", "time": 1, "amount": 500000, "account": acc})["error"]["code"] == -31052
    assert rpc("PerformTransaction", {"id": "abc1"})["result"]["state"] == 2
    assert rpc("PerformTransaction", {"id": "abc1"})["result"]["state"] == 2      # idempotent
    assert c.get("/api/subjects/").status_code == 200
    assert rpc("CheckTransaction", {"id": "abc1"})["result"]["state"] == 2
    assert rpc("CancelTransaction", {"id": "abc1", "reason": 5})["result"]["state"] == -2   # qaytarish
    assert c.get("/api/subjects/").status_code == 403


def click_data(pay_id, amount, action, trans="777", prepare=None, error=0):
    import hashlib
    d = {"click_trans_id": trans, "service_id": settings.CLICK_SERVICE_ID, "click_paydoc_id": "1",
         "merchant_trans_id": str(pay_id), "amount": amount, "action": action, "error": error, "sign_time": "2026-10-23 12:00:00"}
    parts = [trans, settings.CLICK_SERVICE_ID, settings.CLICK_SECRET_KEY, pay_id] + ([prepare] if prepare is not None else []) + [amount, action, d["sign_time"]]
    d["sign_string"] = hashlib.md5("".join(map(str, parts)).encode()).hexdigest()
    if prepare is not None:
        d["merchant_prepare_id"] = prepare
    return d


def test_click_flow(data):
    c = APIClient()
    r = _register(c, "vali", "1y")
    pid = r.data["payment_id"]
    bad = click_data(pid, "50000", 0); bad["sign_string"] = "x"
    assert c.post("/api/payments/click/prepare/", bad, format="json").data["error"] == -1
    assert c.post("/api/payments/click/prepare/", click_data(pid, "5000", 0), format="json").data["error"] == -2
    pr = c.post("/api/payments/click/prepare/", click_data(pid, "50000", 0), format="json").data
    assert pr["error"] == 0 and pr["merchant_prepare_id"] == pid
    done = c.post("/api/payments/click/complete/", click_data(pid, "50000", 1, prepare=pid), format="json").data
    assert done["error"] == 0
    assert c.post("/api/payments/click/complete/", click_data(pid, "50000", 1, prepare=pid), format="json").data["error"] == -4
    assert User.objects.get(username="vali").has_active_access


def test_client_cannot_fake_payment(data):
    c = APIClient()
    r = _register(c, "bob")
    login(c, "bob")
    assert c.post("/api/payments/click/complete/", {"merchant_trans_id": r.data["payment_id"], "error": 0}, format="json").data["error"] == -1
    assert not User.objects.get(username="bob").has_active_access


def test_subject_isolation_and_no_solution_leak(data):
    s, t, p = data
    admin = User.objects.create_user("adm", password="Str0ng!pass9", role="admin")
    stud = User.objects.create_user("stu", password="Str0ng!pass9", role="student", access_type="free")
    c = APIClient(); login(c, "stu")
    r = c.get(f"/api/problems/?subject={s.id}")
    assert r.data["count"] == 1
    item = r.data["results"][0]
    assert "solution" not in item and "correct_answer" not in item
    assert c.post(f"/api/problems/{p.id}/answer/", {"answer": "b"}, format="json").data == {"is_correct": True}
    assert c.get(f"/api/topics/{t.id}/solutions/").data["items"][0]["solution"] == "x=1"
    assert c.post("/api/problems/", {}, format="json").status_code == 403      # o'quvchi ustoz endpointiga kira olmaydi


def test_admin_creates_free_user_password_once(data):
    User.objects.create_user("adm", password="Str0ng!pass9", role="admin")
    c = APIClient(); login(c, "adm")
    r = c.post("/api/admin/users/", {"username": "ustoz1", "first_name": "Ustoz", "role": "teacher"}, format="json")
    assert r.status_code == 201 and r.data["generated_password"]
    u = User.objects.get(username="ustoz1")
    assert u.access_type == "free" and u.has_active_access and u.password != r.data["generated_password"]
