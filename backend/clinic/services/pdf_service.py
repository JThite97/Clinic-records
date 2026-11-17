"""ReportLab PDFs: letterhead prescriptions and full patient records.

The prescription is laid out so that a single visit always fits on one page
of A4 or Letter: the clinical content sits in a fixed frame between the
letterhead and the signature block and is shrunk to fit if it is very long.
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepInFrame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

log = logging.getLogger(__name__)

INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
ACCENT = colors.HexColor("#0f766e")
RULE = colors.HexColor("#d1d5db")

_ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10, textColor=MUTED)
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=ACCENT, spaceBefore=4)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=INK, spaceBefore=8, spaceAfter=2)
RX = ParagraphStyle("rx", parent=BODY, fontName="Helvetica-Bold", fontSize=16, leading=18, textColor=ACCENT)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")


def _p(text, style=BODY) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _page(paper: str):
    return LETTER if (paper or "").lower() == "letter" else A4


def _fmt_date(v) -> str:
    if not v:
        return ""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return v
    if isinstance(v, datetime):
        return v.strftime("%d %b %Y")
    if isinstance(v, date):
        return v.strftime("%d %b %Y")
    return str(v)


def _image(path: Path | None):
    if path and path.exists():
        return str(path)
    return None


class _Letterhead:
    """Draws header + footer on each page."""

    def __init__(self, clinic: dict, documents_root: Path | None, signature: bool):
        self.c = clinic
        self.root = documents_root
        self.signature = signature

    def __call__(self, canv, doc):
        w, h = doc.pagesize
        c = self.c
        canv.saveState()
        top = h - 15 * mm
        x = 18 * mm
        logo = _image(self.root / c["logo_path"]) if (self.root and c.get("logo_path")) else None
        if logo:
            try:
                canv.drawImage(logo, x, top - 16 * mm, width=18 * mm, height=18 * mm, preserveAspectRatio=True, mask="auto")
                x += 22 * mm
            except Exception:  # bad image must not break printing
                log.exception("logo could not be drawn")
        canv.setFillColor(INK)
        canv.setFont("Helvetica-Bold", 15)
        canv.drawString(x, top - 4 * mm, c.get("clinic_name") or "")
        canv.setFont("Helvetica", 8.5)
        canv.setFillColor(MUTED)
        lines = [c.get("clinic_address", "")]
        contact = "  |  ".join(v for v in (c.get("clinic_phone"), c.get("clinic_email")) if v)
        if contact:
            lines.append(contact)
        yy = top - 9 * mm
        for ln in lines:
            for sub in str(ln).splitlines():
                canv.drawString(x, yy, sub[:110])
                yy -= 3.6 * mm
        # Doctor block (right)
        rx_ = w - 18 * mm
        canv.setFillColor(INK)
        canv.setFont("Helvetica-Bold", 11)
        canv.drawRightString(rx_, top - 4 * mm, c.get("doctor_name") or "")
        canv.setFont("Helvetica", 8.5)
        canv.setFillColor(MUTED)
        if c.get("doctor_qualifications"):
            canv.drawRightString(rx_, top - 9 * mm, c["doctor_qualifications"][:70])
        if c.get("doctor_registration"):
            canv.drawRightString(rx_, top - 12.6 * mm, f"Reg. No. {c['doctor_registration']}"[:70])
        canv.setStrokeColor(ACCENT)
        canv.setLineWidth(1.2)
        canv.line(18 * mm, h - 36 * mm, w - 18 * mm, h - 36 * mm)

        # Footer
        if self.signature:
            sig = _image(self.root / c["signature_path"]) if (self.root and c.get("signature_path")) else None
            sy = 30 * mm
            if sig:
                try:
                    canv.drawImage(sig, w - 68 * mm, sy, width=50 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto")
                except Exception:
                    log.exception("signature could not be drawn")
            canv.setStrokeColor(RULE)
            canv.setLineWidth(0.6)
            canv.line(w - 70 * mm, sy - 1 * mm, w - 18 * mm, sy - 1 * mm)
            canv.setFillColor(INK)
            canv.setFont("Helvetica-Bold", 9)
            canv.drawRightString(w - 18 * mm, sy - 5 * mm, c.get("doctor_name") or "Doctor's signature")
            canv.setFont("Helvetica", 7.5)
            canv.setFillColor(MUTED)
            canv.drawRightString(w - 18 * mm, sy - 8.5 * mm, "Signature")
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.6)
        canv.line(18 * mm, 16 * mm, w - 18 * mm, 16 * mm)
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(MUTED)
        canv.drawString(18 * mm, 11.5 * mm, (c.get("footer_note") or "")[:130])
        canv.drawRightString(w - 18 * mm, 11.5 * mm, f"Page {doc.page}")
        canv.restoreState()


def _patient_block(patient: dict, when: str, extra: str = "") -> Table:
    age = patient.get("age")
    sex = {"M": "Male", "F": "Female", "O": "Other"}.get(patient.get("sex") or "", "")
    age_sex = " / ".join(v for v in (f"{age} y" if age is not None else "", sex) if v)
    data = [
        [_p("Patient", SMALL), _p(patient.get("full_name"), CELLB), _p("ID", SMALL), _p(patient.get("patient_number") or "", CELLB)],
        [_p("Age / Sex", SMALL), _p(age_sex, CELL), _p("Date", SMALL), _p(when, CELL)],
        [_p("Phone", SMALL), _p(patient.get("phone"), CELL), _p("Blood group", SMALL), _p(patient.get("blood_group"), CELL)],
    ]
    if patient.get("allergies"):
        data.append([_p("Allergies", SMALL), Paragraph(f'<font color="#b91c1c"><b>{escape(patient["allergies"])}</b></font>', CELL), "", ""])
    if extra:
        data.append([_p("Visit", SMALL), _p(extra, CELL), "", ""])
    t = Table(data, colWidths=[22 * mm, 78 * mm, 22 * mm, 52 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]
    for r in range(3, len(data)):
        style.append(("SPAN", (1, r), (3, r)))
    t.setStyle(TableStyle(style))
    return t


def _vitals_line(v: dict) -> str:
    parts = []
    if v.get("bp_systolic") and v.get("bp_diastolic"):
        parts.append(f"BP {v['bp_systolic']}/{v['bp_diastolic']} mmHg")
    if v.get("pulse"):
        parts.append(f"Pulse {v['pulse']}/min")
    if v.get("temperature"):
        parts.append(f"Temp {v['temperature']} °C")
    if v.get("spo2"):
        parts.append(f"SpO2 {v['spo2']}%")
    if v.get("resp_rate"):
        parts.append(f"RR {v['resp_rate']}/min")
    if v.get("weight"):
        parts.append(f"Wt {v['weight']} kg")
    if v.get("height"):
        parts.append(f"Ht {v['height']} cm")
    return "   ·   ".join(parts)


def _rx_table(items: list[dict], width: float) -> Table:
    head = [_p("#", SMALL), _p("Medicine", SMALL), _p("Dose", SMALL), _p("Frequency", SMALL), _p("Duration", SMALL), _p("Instructions", SMALL)]
    rows = [head]
    for i, it in enumerate(items, 1):
        name = it.get("medicine_name", "")
        form = it.get("form") or ""
        title = f"<b>{escape(name)}</b>" + (f' <font color="#6b7280" size="8">{escape(form)}</font>' if form else "")
        instr = " ".join(v for v in (it.get("timing"), it.get("instructions")) if v)
        if it.get("quantity"):
            instr = (instr + f" (Qty {it['quantity']})").strip()
        rows.append([
            _p(str(i), CELL), Paragraph(title, CELL), _p(it.get("dose"), CELL),
            _p(it.get("frequency"), CELL), _p(it.get("duration"), CELL), _p(instr, CELL),
        ])
    cw = [8 * mm, width * 0.36, width * 0.12, width * 0.14, width * 0.12]
    cw.append(width - sum(cw))
    t = Table(rows, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _clinical_flowables(visit: dict, width: float, include_rx_symbol: bool = True) -> list:
    out: list = []
    vit = _vitals_line(visit)
    if vit:
        out += [_p("VITALS", LABEL), _p(vit)]
    for key, label in (("chief_complaint", "COMPLAINTS"), ("history", "HISTORY"), ("examination", "EXAMINATION"), ("diagnosis", "DIAGNOSIS")):
        if visit.get(key):
            out += [_p(label, LABEL), _p(visit[key])]
    items = (visit.get("prescription") or {}).get("items") or []
    if items:
        out.append(Spacer(1, 5))
        if include_rx_symbol:
            out.append(Paragraph("R<sub>x</sub>", RX))
        out.append(_rx_table(items, width))
    rx_notes = (visit.get("prescription") or {}).get("notes")
    if rx_notes:
        out += [_p("NOTES", LABEL), _p(rx_notes)]
    if visit.get("advice"):
        out += [_p("ADVICE", LABEL), _p(visit["advice"])]
    if visit.get("follow_up_date"):
        out += [_p("FOLLOW-UP", LABEL), _p(_fmt_date(visit["follow_up_date"]))]
    return out


def prescription_pdf(visit: dict, patient: dict, clinic: dict, documents_root: Path | None = None) -> bytes:
    """One-page letterhead prescription for a single visit."""
    buf = io.BytesIO()
    pagesize = _page(clinic.get("paper_size", "A4"))
    w, h = pagesize
    doc = BaseDocTemplate(buf, pagesize=pagesize, title=f"Prescription {patient.get('patient_number', '')}",
                          author=clinic.get("doctor_name", ""), leftMargin=18 * mm, rightMargin=18 * mm)
    frame_w = w - 36 * mm
    frame = Frame(18 * mm, 42 * mm, frame_w, h - 40 * mm - 42 * mm, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="rx", frames=[frame], onPage=_Letterhead(clinic, documents_root, signature=True))])
    extra = ""
    if visit.get("amends_id"):
        extra = "Amended record" + (f": {visit.get('amendment_reason')}" if visit.get("amendment_reason") else "")
    content = [_patient_block(patient, _fmt_date(visit.get("visit_date")), extra), Spacer(1, 4)]
    content += _clinical_flowables(visit, frame_w)
    # Shrink to fit so a single visit never spills onto a second page.
    doc.build([KeepInFrame(frame_w, frame._aH, content, mode="shrink")])
    return buf.getvalue()


def patient_record_pdf(patient: dict, visits: list[dict], documents: list[dict], clinic: dict, documents_root: Path | None = None) -> bytes:
    """Full patient record: demographics and every visit (newest first)."""
    buf = io.BytesIO()
    pagesize = _page(clinic.get("paper_size", "A4"))
    w, h = pagesize
    doc = BaseDocTemplate(buf, pagesize=pagesize, title=f"Patient record {patient.get('patient_number', '')}")
    frame_w = w - 36 * mm
    frame = Frame(18 * mm, 20 * mm, frame_w, h - 40 * mm - 20 * mm, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="rec", frames=[frame], onPage=_Letterhead(clinic, documents_root, signature=False))])
    story: list = [Paragraph("Patient record", H2), _patient_block(patient, _fmt_date(date.today()))]
    for key, label in (("address", "ADDRESS"), ("chronic_conditions", "CHRONIC CONDITIONS"), ("notes", "NOTES")):
        if patient.get(key):
            story += [_p(label, LABEL), _p(patient[key])]
    story.append(Paragraph(f"Visits ({len(visits)})", H2))
    if not visits:
        story.append(_p("No visits recorded.", SMALL))
    for v in visits:
        head = _fmt_date(v.get("visit_date"))
        if v.get("amends_id"):
            head += "  (amended" + (f": {v.get('amendment_reason')}" if v.get("amendment_reason") else "") + ")"
        block = [Spacer(1, 4), Table([[Paragraph(f"<b>{escape(head)}</b>", BODY)]], colWidths=[frame_w],
                                      style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
                                                        ("LEFTPADDING", (0, 0), (-1, -1), 4)]))]
        block += _clinical_flowables(v, frame_w, include_rx_symbol=False)
        story += block
    if documents:
        story.append(Paragraph(f"Documents ({len(documents)})", H2))
        for d in documents:
            story.append(_p(f"{_fmt_date(d.get('uploaded_at'))}  ·  {d.get('category', '').title()}  ·  {d.get('title')}  ({d.get('original_filename')})", SMALL))
    doc.build(story)
    return buf.getvalue()


def page_count(pdf: bytes) -> int:
    import re

    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))
