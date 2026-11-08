from io import BytesIO
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter
from rest_framework.test import APIClient

from accounts.models import User
from content.models import Problem, Subject
from imports import pdfimport
from imports.models import ImportJob

pytestmark = pytest.mark.django_db
PW = "Str0ng!pass9"


def login(username, **kw):
    User.objects.create_user(username, password=PW, access_type="free", **kw)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + c.post("/api/auth/login/", {"username": username, "password": PW}, format="json").data["access"])
    return c


def pdf(pages):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    b = BytesIO(); w.write(b)
    return SimpleUploadedFile("kitob.pdf", b.getvalue(), content_type="application/pdf")


def test_pdf_pipeline_merges_answers_across_chunks(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY, settings.PDF_CHUNK_PAGES = "sk-test", 2
    Subject.objects.create(name="Algebra", slug="algebra")
    calls = []
    results = [
        {"problems": [{"topic": "Tenglamalar", "number": 1, "text": "$x+9=15$", "options": {"A": "5", "B": "6", "C": "7", "D": "8"}, "page": 1},
                      {"topic": "", "number": 2, "text": "$2x=10$", "page": 2}], "answers": [], "last_topic": "Tenglamalar"},
        {"problems": [{"topic": "", "number": 3, "text": "javobsiz masala", "page": 1}],
         "answers": [{"topic": "", "number": 1, "answer": "B) 6", "solution": "$x=6$"},
                     {"topic": "", "number": 2, "answer": "5", "solution": "$x=5$"}], "last_topic": "Tenglamalar"},
    ]
    monkeypatch.setattr(pdfimport, "extract_chunk", lambda b, carry: (calls.append(carry), results[len(calls) - 1])[1])
    monkeypatch.setattr(pdfimport, "run_async", pdfimport.process_pdf)           # testda fon oqimsiz
    admin = login("adm", role="admin")
    r = admin.post("/api/imports/pdf/", {"file": pdf(4), "subject": Subject.objects.get().id}, format="multipart")
    assert r.status_code == 202, r.data
    job = admin.get(f"/api/imports/{r.data['id']}/").data
    assert job["status"] == "parsed" and job["pages"] == 4 and job["done_pages"] == 4
    assert calls == ["", "Tenglamalar"]                                   # mavzu keyingi bo'lakka uzatiladi
    assert (job["total"], job["valid"], job["failed"]) == (3, 2, 1)
    assert "javob topilmadi" in job["errors"][0]["reason"] and job["errors"][0]["page"] == 3
    rows = admin.get(f"/api/imports/{job['id']}/rows/").data
    assert [x["topic"] for x in rows] == ["Tenglamalar"] * 2 and rows[0]["answer"] == "B" and rows[0]["has_solution"]
    done = admin.post(f"/api/imports/{job['id']}/confirm/", {"exclude": [rows[1]["row"]]}, format="json").data
    assert done["created"] == 1 and Problem.objects.count() == 1
    p = Problem.objects.get()
    assert p.type == "test" and p.correct_answer == "B" and p.solution == "$x=6$"


def test_pdf_admin_only_and_key_required(settings):
    s = Subject.objects.create(name="Algebra", slug="algebra")
    teacher, admin = login("t", role="teacher"), login("a", role="admin")
    settings.ANTHROPIC_API_KEY = "k"
    assert teacher.post("/api/imports/pdf/", {"file": pdf(1), "subject": s.id}, format="multipart").status_code == 403
    settings.ANTHROPIC_API_KEY = ""
    r = admin.post("/api/imports/pdf/", {"file": pdf(1), "subject": s.id}, format="multipart")
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in str(r.data)
    settings.ANTHROPIC_API_KEY = "k"
    assert admin.post("/api/imports/pdf/", {"file": SimpleUploadedFile("a.docx", b"x"), "subject": s.id}, format="multipart").status_code == 400


def test_pdf_failure_reported(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "k"
    s = Subject.objects.create(name="Algebra", slug="algebra")
    def boom(b, carry): raise RuntimeError("API xatosi")
    monkeypatch.setattr(pdfimport, "extract_chunk", boom)
    monkeypatch.setattr(pdfimport, "run_async", pdfimport.process_pdf)
    admin = login("a2", role="admin")
    r = admin.post("/api/imports/pdf/", {"file": pdf(1), "subject": s.id, "topic": "Forced"}, format="multipart")
    j = admin.get(f"/api/imports/{r.data['id']}/").data
    assert j["status"] == "failed" and "API xatosi" in j["error"]
