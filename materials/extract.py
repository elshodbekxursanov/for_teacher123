"""Fayldan matn ajratish va misollarga bo'lish (indekslash)."""
import re
from pypdf import PdfReader

ALLOWED = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "jpg", "jpeg", "png"}
TEXT_EXT = {"pdf", "docx", "pptx", "xlsx", "txt"}          # eski .doc/.ppt/.xls matn ajratilmaydi (saqlanadi, indekslanmaydi)


def pages_of(path, ext):
    """-> [(bet_raqami, matn)]"""
    if ext == "pdf":
        return [(i, (p.extract_text() or "")) for i, p in enumerate(PdfReader(path).pages, 1)]
    if ext == "docx":
        from docx import Document
        d = Document(path)
        lines = [p.text for p in d.paragraphs]
        for t in d.tables:
            lines += [" | ".join(c.text for c in r.cells) for r in t.rows]
        return [(1, "\n".join(lines))]
    if ext == "pptx":
        from pptx import Presentation
        out = []
        for i, s in enumerate(Presentation(path).slides, 1):
            out.append((i, "\n".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame)))
        return out
    if ext == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        return [(i, "\n".join(" | ".join(str(c) for c in r if c is not None) for r in ws.iter_rows(values_only=True)))
                for i, ws in enumerate(wb.worksheets, 1)]
    if ext == "txt":
        return [(1, open(path, encoding="utf-8", errors="ignore").read())]
    return []


PFX = r"(?:№|#|N°|Masala|Misol|Задача|Пример)"
NUM1 = re.compile(rf"^\s*(?:{PFX}\s*)?(\d{{1,4}})\s*[.)](?:\s+|$)(.*)$", re.I)       # "12." "12)" "№ 12." (o'nlik kasr emas)
NUM2 = re.compile(rf"^\s*{PFX}\s*(\d{{1,4}})\s*[:\-.)]?\s*(.*)$", re.I)             # "№ 12 ..." "Masala 12"
TOPIC = re.compile(r"^\s*(?:mavzu|тема|topic)\s*[:\-–]\s*(.+)$", re.I)
SOL = re.compile(r"\n\s*(?:yechim|yechish|решение|solution)\s*[:.]", re.I)


def _heading(line):
    t = line.strip()
    return 4 <= len(t) <= 80 and t.upper() == t and sum(c.isalpha() for c in t) >= 4 and not NUM1.match(t)


def segment(pages):
    """pages -> [{page, topic_label, number, text, solution_text}]"""
    out, topic, cur = [], "", None

    def flush():
        nonlocal cur
        if cur and cur["text"].strip():
            text = cur["text"].strip()
            m = SOL.search("\n" + text)
            sol = ""
            if m:
                cut = m.start() - 1 if m.start() > 0 else 0
                text, sol = text[:max(cut, 0)].strip(), text[max(cut, 0):].strip()
                sol = re.sub(r"^\s*(?:yechim|yechish|решение|solution)\s*[:.]\s*", "", sol, flags=re.I)
            if text:
                out.append({**{k: cur[k] for k in ("page", "topic_label", "number")}, "text": text[:5000], "solution_text": sol[:5000]})
        cur = None

    for page, text in pages:
        for line in text.splitlines():
            if not line.strip():
                continue
            m = TOPIC.match(line)
            if m:
                flush(); topic = m.group(1).strip()[:200]; continue
            if _heading(line):
                flush(); topic = line.strip()[:200]; continue
            m = NUM1.match(line) or NUM2.match(line)
            if m:
                flush()
                cur = {"page": page, "topic_label": topic, "number": int(m.group(1)), "text": m.group(2)}
            elif cur is not None:
                cur["text"] += "\n" + line
    flush()
    return out
