"""Certificate rendering: one predefined landscape-A4 template drawn with ReportLab."""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class CertificateData:
    certificate_id: str
    recipient_name: str
    course_name: str
    issuer_name: str
    issue_date: date
    verify_url: str = ""


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


# ---------- the template ----------

def _draw_certificate(c, data, W, H):
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


def render_certificate(data: CertificateData, dest: Path) -> Path:
    """Render the certificate to `dest`. Written to a temp file and renamed, so a
    crash mid-render never leaves a half-written PDF at the final path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".pdf.tmp")
    width, height = landscape(A4)

    c = canvas.Canvas(str(tmp), pagesize=(width, height), pageCompression=0)
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issuer_name)
    _draw_certificate(c, data, width, height)
    c.showPage()
    c.save()
    os.replace(tmp, dest)
    return dest
