"""Certificate rendering. Several selectable landscape-A4 templates built with ReportLab.

To add a template: write a `_draw_xxx(c, data, W, H)` function and register it in TEMPLATES.
"""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

DEFAULT_TEMPLATE = "classic"


@dataclass(frozen=True)
class CertificateData:
    certificate_id: str
    recipient_name: str
    course_name: str
    issuer_name: str
    issue_date: date
    verify_url: str = ""
    template: str = DEFAULT_TEMPLATE


# ---------- helpers ----------

def _hex(value: str):
    return colors.HexColor(value)


def _fit(text: str, font: str, size: float, max_width: float, min_size: float = 9) -> float:
    """Shrink the font size until `text` fits in `max_width` (long names/courses)."""
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _text(c, x, y, text, font, size, color, align="center", max_width=None):
    if max_width:
        size = _fit(text, font, size, max_width)
    c.setFillColor(_hex(color) if isinstance(color, str) else color)
    c.setFont(font, size)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def _qr(c, url: str, x: float, y: float, size: float) -> None:
    qr = QrCodeWidget(url)
    x0, y0, x1, y1 = qr.getBounds()
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(qr)
    renderPDF.draw(d, c, x, y)


def _date_str(data: CertificateData) -> str:
    return data.issue_date.strftime("%d %B %Y")


# ---------- templates ----------

def _draw_classic(c, data, W, H):
    cx = W / 2
    c.setStrokeColor(_hex("#1f3a5f"))
    c.setLineWidth(4)
    c.rect(25, 25, W - 50, H - 50)
    c.setLineWidth(1)
    c.rect(35, 35, W - 70, H - 70)

    _text(c, cx, H - 130, "CERTIFICATE OF COMPLETION", "Helvetica-Bold", 38, "#1f3a5f")
    _text(c, cx, H - 190, "This is to certify that", "Helvetica", 16, "#444444")
    _text(c, cx, H - 250, data.recipient_name, "Helvetica-Bold", 34, "#000000", max_width=W - 160)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(cx - 220, H - 262, cx + 220, H - 262)
    _text(c, cx, H - 305, "has successfully completed", "Helvetica", 16, "#444444")
    _text(c, cx, H - 345, data.course_name, "Helvetica-Bold", 24, "#1f3a5f", max_width=W - 160)

    _text(c, 80, 90, f"Issued on: {_date_str(data)}", "Helvetica", 13, "#444444", "left")
    _text(c, W - 80, 90, f"Issued by: {data.issuer_name}", "Helvetica", 13, "#444444", "right",
          max_width=300)
    _text(c, cx, 55, f"Certificate ID: {data.certificate_id}", "Helvetica", 9, "#444444")
    if data.verify_url:
        _qr(c, data.verify_url, cx - 40, 100, 80)
        _text(c, cx, 90, "Scan to verify", "Helvetica", 8, "#444444")


def _draw_elegant(c, data, W, H):
    cx = W / 2
    ink, gold = "#3b2a14", "#b8860b"
    c.setFillColor(_hex("#fbf6e9"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setStrokeColor(_hex(gold))
    c.setLineWidth(3)
    c.rect(22, 22, W - 44, H - 44)
    c.setLineWidth(0.8)
    c.rect(32, 32, W - 64, H - 64)

    _text(c, cx, H - 125, "Certificate", "Times-Bold", 54, ink)
    _text(c, cx, H - 155, "OF COMPLETION", "Helvetica", 13, gold)
    c.setStrokeColor(_hex(gold))
    c.setLineWidth(1)
    c.line(cx - 90, H - 170, cx + 90, H - 170)
    _text(c, cx, H - 205, "This certificate is proudly presented to", "Times-Italic", 17, "#5a4a32")
    _text(c, cx, H - 262, data.recipient_name, "Times-BoldItalic", 40, ink, max_width=W - 170)
    c.line(cx - 190, H - 274, cx + 190, H - 274)
    _text(c, cx, H - 312, "for successfully completing", "Times-Italic", 16, "#5a4a32")
    _text(c, cx, H - 350, data.course_name, "Times-Bold", 26, ink, max_width=W - 170)

    _text(c, 85, 90, f"Date: {_date_str(data)}", "Times-Roman", 14, ink, "left")
    _text(c, W - 85, 90, data.issuer_name, "Times-Roman", 14, ink, "right", max_width=300)
    _text(c, cx, 52, f"Certificate ID: {data.certificate_id}", "Times-Roman", 9, "#5a4a32")
    if data.verify_url:
        _qr(c, data.verify_url, cx - 38, 100, 76)
        _text(c, cx, 90, "Scan to verify", "Times-Italic", 8, "#5a4a32")


def _draw_modern(c, data, W, H):
    navy, teal = "#0f172a", "#14b8a6"
    band = 230
    c.setFillColor(_hex(navy))
    c.rect(0, 0, band, H, stroke=0, fill=1)
    c.setFillColor(_hex(teal))
    c.rect(band, 0, 8, H, stroke=0, fill=1)

    _text(c, 30, H - 110, "CERTIFICATE", "Helvetica-Bold", 26, "#ffffff", "left")
    _text(c, 30, H - 132, "OF COMPLETION", "Helvetica", 12, teal, "left")
    _text(c, 30, 300, "ISSUED ON", "Helvetica-Bold", 8, teal, "left")
    _text(c, 30, 283, _date_str(data), "Helvetica", 13, "#ffffff", "left", max_width=band - 50)
    _text(c, 30, 245, "ISSUED BY", "Helvetica-Bold", 8, teal, "left")
    _text(c, 30, 228, data.issuer_name, "Helvetica", 13, "#ffffff", "left", max_width=band - 50)
    if data.verify_url:
        c.setFillColor(colors.white)
        c.rect(40, 50, 110, 110, stroke=0, fill=1)
        _qr(c, data.verify_url, 48, 58, 94)
        _text(c, 40, 36, "Scan to verify", "Helvetica", 8, "#ffffff", "left")

    x0, mw = band + 60, W - band - 60 - 50
    _text(c, x0, H - 175, "This certifies that", "Helvetica", 15, "#64748b", "left")
    _text(c, x0, H - 232, data.recipient_name, "Helvetica-Bold", 38, navy, "left", max_width=mw)
    c.setFillColor(_hex(teal))
    c.rect(x0, H - 252, 70, 4, stroke=0, fill=1)
    _text(c, x0, H - 300, "has successfully completed", "Helvetica", 15, "#64748b", "left")
    _text(c, x0, H - 338, data.course_name, "Helvetica-Bold", 26, navy, "left", max_width=mw)
    _text(c, W - 50, 40, f"ID: {data.certificate_id}", "Helvetica", 8, "#94a3b8", "right")


def _draw_minimal(c, data, W, H):
    left = 80
    c.setStrokeColor(_hex("#bbbbbb"))
    c.setLineWidth(0.5)
    c.line(60, H - 60, W - 60, H - 60)
    c.line(60, 60, W - 60, 60)

    t = c.beginText(left, H - 112)
    t.setFont("Helvetica", 12)
    t.setFillColor(colors.black)
    t.setCharSpace(3)  # letter-spaced heading
    t.textOut("CERTIFICATE OF COMPLETION")
    t.setCharSpace(0)  # reset, otherwise spacing leaks into later text
    c.drawText(t)
    _text(c, left, H - 190, "Presented to", "Helvetica", 13, "#888888", "left")
    _text(c, left, H - 247, data.recipient_name, "Helvetica", 44, "#111111", "left", max_width=W - 2 * left)
    _text(c, left, H - 292, "for completing", "Helvetica", 13, "#888888", "left")
    _text(c, left, H - 327, data.course_name, "Helvetica-Bold", 22, "#111111", "left", max_width=W - 2 * left)

    _text(c, left, 112, _date_str(data), "Helvetica", 11, "#111111", "left")
    _text(c, left, 95, f"Issued by {data.issuer_name}", "Helvetica", 11, "#555555", "left", max_width=420)
    _text(c, left, 42, f"ID {data.certificate_id}", "Helvetica", 7, "#999999", "left")
    if data.verify_url:
        _qr(c, data.verify_url, W - left - 64, 80, 64)
        _text(c, W - left - 32, 70, "Scan to verify", "Helvetica", 7, "#999999")


def _draw_royal(c, data, W, H):
    cx = W / 2
    burgundy, gold = "#5b0f1a", "#9a7b1c"
    c.setFillColor(_hex(burgundy))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.rect(28, 28, W - 56, H - 56, stroke=0, fill=1)
    c.setStrokeColor(_hex(gold))
    c.setLineWidth(1.5)
    c.rect(36, 36, W - 72, H - 72)
    c.setLineWidth(0.5)
    c.rect(42, 42, W - 84, H - 84)
    c.setFillColor(_hex(gold))
    for x, y in ((30, 30), (W - 44, 30), (30, H - 44), (W - 44, H - 44)):
        c.rect(x, y, 14, 14, stroke=0, fill=1)

    _text(c, cx, H - 118, "CERTIFICATE", "Times-Bold", 42, burgundy)
    _text(c, cx, H - 146, "OF COMPLETION", "Times-Roman", 16, gold)
    c.setStrokeColor(_hex(gold))
    c.setLineWidth(1)
    c.line(cx - 70, H - 160, cx + 70, H - 160)
    _text(c, cx, H - 200, "This is proudly presented to", "Times-Italic", 16, "#555555")
    _text(c, cx, H - 255, data.recipient_name, "Times-Bold", 36, "#111111", max_width=W - 170)
    c.line(cx - 200, H - 267, cx + 200, H - 267)
    _text(c, cx, H - 305, "for the successful completion of", "Times-Italic", 16, "#555555")
    _text(c, cx, H - 343, data.course_name, "Times-Bold", 24, burgundy, max_width=W - 170)

    _text(c, 85, 92, f"Date: {_date_str(data)}", "Times-Roman", 13, "#333333", "left")
    _text(c, W - 85, 92, data.issuer_name, "Times-Roman", 13, "#333333", "right", max_width=300)
    _text(c, cx, 56, f"Certificate ID: {data.certificate_id}", "Times-Roman", 9, "#555555")
    if data.verify_url:
        _qr(c, data.verify_url, cx - 38, 102, 76)
        _text(c, cx, 92, "Scan to verify", "Times-Italic", 8, "#555555")


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    description: str
    draw: Callable


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template("classic", "Classic Blue", "Navy double border, centered, sans-serif", _draw_classic),
        Template("elegant", "Elegant Gold", "Cream paper, gold border, serif italic", _draw_elegant),
        Template("modern", "Modern Sidebar", "Dark side panel with teal accent, left-aligned", _draw_modern),
        Template("minimal", "Minimal", "Clean white, lots of space, thin lines", _draw_minimal),
        Template("royal", "Royal Burgundy", "Burgundy frame with gold details, formal serif", _draw_royal),
    )
}


def render_certificate(data: CertificateData, dest: Path) -> Path:
    """Render the certificate to `dest`. Written to a temp file and renamed, so a
    crash mid-render never leaves a half-written PDF at the final path."""
    template = TEMPLATES.get(data.template)
    if template is None:
        raise ValueError(f"Unknown template: {data.template!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".pdf.tmp")
    width, height = landscape(A4)

    c = canvas.Canvas(str(tmp), pagesize=(width, height), pageCompression=0)
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issuer_name)
    template.draw(c, data, width, height)
    c.showPage()
    c.save()
    os.replace(tmp, dest)
    return dest
