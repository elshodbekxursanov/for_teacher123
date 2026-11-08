import base64, hashlib, socket, struct
from io import BytesIO

from django.conf import settings
from pypdf import PdfReader, PdfWriter

from . import extract
from .models import MaterialFile, ProblemSource


def sha256(f):
    h = hashlib.sha256()
    for chunk in f.chunks():
        h.update(chunk)
    f.seek(0)
    return h.hexdigest()


def scan_upload(f):
    """ClamAV (clamd INSTREAM). CLAMAV_HOST bo'sh bo'lsa o'tkazib yuboriladi. -> (ok, sabab)"""
    if not settings.CLAMAV_HOST:
        return True, ""
    try:
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=30) as s:
            s.sendall(b"zINSTREAM\0")
            for chunk in f.chunks(64 * 1024):
                s.sendall(struct.pack("!I", len(chunk)) + chunk)
            s.sendall(struct.pack("!I", 0))
            reply = s.recv(4096).decode(errors="ignore")
        f.seek(0)
        return ("OK" in reply and "FOUND" not in reply), reply.strip()
    except OSError as e:
        f.seek(0)
        return (not settings.CLAMAV_REQUIRED), f"antivirus mavjud emas: {e}"


def index_file(file_id, use_ai=False):
    """Matn ajratish + misollarga bo'lish. Skaner bo'lsa va use_ai bo'lsa — Claude vision."""
    mf = MaterialFile.objects.select_related("material").get(pk=file_id)
    try:
        if mf.ext not in extract.TEXT_EXT:
            mf.extract_status = "ocr" if mf.ext in ("jpg", "jpeg", "png") else "error"
            mf.extract_error = "Bu format matnga aylantirilmaydi" if mf.extract_status == "error" else ""
            mf.save(); return
        pages = extract.pages_of(mf.file.path, mf.ext)
        mf.pages = len(pages)
        chars = sum(len(t.strip()) for _, t in pages)
        scanned = mf.ext == "pdf" and chars < 40 * max(len(pages), 1)
        if scanned and not use_ai:
            mf.extract_status = "ocr"; mf.save()
            return
        items = ai_items(mf) if scanned else extract.segment(pages)
        mf.sources.all().delete()
        ProblemSource.objects.bulk_create([ProblemSource(file=mf, **it) for it in items])
        mf.extract_status, mf.extract_error = "ready", ""
    except Exception as e:                  # noqa
        mf.extract_status, mf.extract_error = "error", str(e)[:290]
    mf.save()


def ai_items(mf):
    from imports import pdfimport
    reader = PdfReader(mf.file.path)
    n, step, carry, problems, answers = len(reader.pages), settings.PDF_CHUNK_PAGES, "", [], {}
    for start in range(0, n, step):
        w = PdfWriter()
        for pg in reader.pages[start:start + step]:
            w.add_page(pg)
        buf = BytesIO(); w.write(buf)
        res = pdfimport.extract_chunk(buf.getvalue(), carry)
        c = carry
        for p in res.get("problems", []):
            c = p.get("topic") or c
            problems.append((c, p, start + (p.get("page") or 1)))
        c = carry
        for a in res.get("answers", []):
            c = a.get("topic") or c
            answers[(c.casefold(), a.get("number"))] = a
        carry = res.get("last_topic") or c or carry
    out = []
    for topic, p, page in problems:
        text = p["text"]
        if p.get("options"):
            text += "\n" + "\n".join(f"{k}) {v}" for k, v in p["options"].items() if v)
        a = answers.get((topic.casefold(), p["number"]), {})
        sol = " ".join(x for x in (a.get("answer", ""), a.get("solution", "")) if x).strip()
        out.append({"page": page, "topic_label": topic[:200], "number": p["number"], "text": text[:5000], "solution_text": sol[:5000]})
    return out
