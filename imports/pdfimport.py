"""PDF -> masalalar. PDF bo'laklarga (bet guruhlariga) bo'linib Claude API ga yuboriladi; skaner va formulali
sahifalar ham o'qiladi. Natija Excel bilan bir xil tekshiruvdan o'tadi va admin tasdig'ini kutadi."""
import base64, re
from io import BytesIO

from django.conf import settings
from pypdf import PdfReader, PdfWriter

from . import service
from .models import ImportJob

TOOL = {
    "name": "save_problems",
    "description": "Berilgan PDF sahifalaridagi masalalar va javob/yechimlarni saqlash",
    "input_schema": {"type": "object", "properties": {
        "problems": {"type": "array", "items": {"type": "object", "properties": {
            "topic": {"type": "string"}, "number": {"type": "integer"}, "text": {"type": "string"},
            "options": {"type": "object", "properties": {k: {"type": "string"} for k in "ABCD"}},
            "difficulty": {"type": "string", "enum": ["", "oson", "o'rta", "qiyin"]},
            "page": {"type": "integer", "description": "shu bo'lakdagi nisbiy bet raqami (1 dan)"}},
            "required": ["number", "text"]}},
        "answers": {"type": "array", "items": {"type": "object", "properties": {
            "topic": {"type": "string"}, "number": {"type": "integer"},
            "answer": {"type": "string"}, "solution": {"type": "string"}}, "required": ["number", "answer"]}},
        "last_topic": {"type": "string"}},
        "required": ["problems", "answers"]},
}

PROMPT = """You extract exercises from pages of a textbook PDF (Uzbek, Russian or English) and return them with the save_problems tool.

Rules:
- Copy each problem text EXACTLY as written. Do not translate, correct, shorten, solve or invent anything.
- Write all math in LaTeX inside $...$ (use $$...$$ for display formulas). Keep ordinary text as plain text.
- If a problem has lettered options (A-D, a-d or 1-4), put them in `options` with keys A, B, C, D. Otherwise omit `options`.
- `topic` is the title of the topic/section the item belongs to. If the heading is not visible on these pages, use "". The previous pages ended in topic: "{carry}".
- Sections like "Javoblar va yechimlar", "Javoblar", "Ответы" contain answers/solutions: put each one into `answers` with topic, number, answer (for multiple-choice give only the option letter A-D) and the full worked `solution` if shown. Never turn answer sections into problems.
- If a problem is printed together with its answer or solution, add it to both `problems` and `answers`.
- Ignore page headers, footers, page numbers and advertisements.
- Set `last_topic` to the topic that is active at the end of these pages.
- If there is nothing to extract, return empty lists."""


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=300)


def extract_chunk(pdf_bytes, carry):
    resp = _client().messages.create(
        model=settings.ANTHROPIC_MODEL, max_tokens=16000, tools=[TOOL],
        tool_choice={"type": "tool", "name": "save_problems"},
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(pdf_bytes).decode()}},
            {"type": "text", "text": PROMPT.replace("{carry}", carry or "")}]}])
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Bo'lak juda katta (javob kesilib qoldi). PDF_CHUNK_PAGES ni kamaytiring.")
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    return {"problems": [], "answers": []}


def _letter(ans, has_opts):
    if has_opts:
        m = re.match(r"\s*\(?([A-Da-d])\b", ans or "")
        if m:
            return m.group(1).upper()
    return (ans or "").strip()


def build_records(subject, forced_topic, chunks):
    """chunks: [(first_page, result_dict)] -> service.validate uchun records."""
    problems, answers, carry = [], {}, ""
    for first, res in chunks:
        c = carry
        for p in res.get("problems", []):
            c = p.get("topic") or c
            problems.append({**p, "topic": forced_topic or c, "page": first + (p.get("page") or 1) - 1})
        c = carry
        for a in res.get("answers", []):
            c = a.get("topic") or c
            answers[((forced_topic or c).casefold(), a.get("number"))] = a
        carry = res.get("last_topic") or c or carry
    records = []
    for i, p in enumerate(problems, start=1):
        a = answers.get((p["topic"].casefold(), p["number"]), {})
        opts = p.get("options") or {}
        has = sum(bool(str(v).strip()) for v in opts.values()) > 0
        records.append({"row": i, "page": p["page"], "fan": subject.name, "mavzu": p["topic"], "raqam": p["number"],
                        "savol": p["text"], **{k.lower(): str(v).strip() for k, v in opts.items()},
                        "javob": _letter(a.get("answer", ""), has), "yechim": (a.get("solution") or "").strip(),
                        "qiyinlik": p.get("difficulty", "")})
    return records


def process_pdf(job_id):
    job = ImportJob.objects.select_related("subject").get(pk=job_id)
    try:
        reader = PdfReader(job.file.path)
        n = len(reader.pages)
        if n > settings.MAX_PDF_PAGES:
            raise RuntimeError(f"PDF {settings.MAX_PDF_PAGES} betdan oshmasligi kerak (hozir {n})")
        job.pages, job.status = n, "processing"
        job.save(update_fields=["pages", "status"])
        chunks, carry, step = [], "", settings.PDF_CHUNK_PAGES
        for start in range(0, n, step):
            w = PdfWriter()
            for pg in reader.pages[start:start + step]:
                w.add_page(pg)
            buf = BytesIO(); w.write(buf)
            res = extract_chunk(buf.getvalue(), carry)
            chunks.append((start + 1, res))
            carry = res.get("last_topic") or carry
            job.done_pages = min(start + step, n)
            job.save(update_fields=["done_pages"])
        rows, errors, total = service.validate(build_records(job.subject, job.forced_topic, chunks))
        job.rows, job.report, job.total, job.valid, job.failed = rows, errors, total, len(rows), len(errors)
        job.status = "parsed"
        if total == 0:
            job.status, job.error_message = "failed", "PDF dan masala topilmadi"
    except Exception as e:                                   # noqa
        job.status, job.error_message = "failed", str(e)[:480]
    job.save()


def run_async(job_id):
    from config.background import run_bg
    run_bg("imports.pdfimport:process_pdf", job_id)
