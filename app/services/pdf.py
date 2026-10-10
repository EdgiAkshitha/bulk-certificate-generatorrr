"""Certificate rendering. One fixed template: landscape A4 PDF built with ReportLab."""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class CertificateData:
    certificate_id: str
    recipient_name: str
    course_name: str
    issuer_name: str
    issue_date: date
    verify_url: str = ""


def render_certificate(data: CertificateData, dest: Path) -> Path:
    """Render the certificate to `dest`. Written to a temp file and renamed, so a
    crash mid-render never leaves a half-written PDF at the final path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".pdf.tmp")
    width, height = landscape(A4)
    cx = width / 2

    c = canvas.Canvas(str(tmp), pagesize=(width, height), pageCompression=0)
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issuer_name)

    # double border
    c.setStrokeColor(colors.HexColor("#1f3a5f"))
    c.setLineWidth(4)
    c.rect(25, 25, width - 50, height - 50)
    c.setLineWidth(1)
    c.rect(35, 35, width - 70, height - 70)

    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.setFont("Helvetica-Bold", 38)
    c.drawCentredString(cx, height - 130, "CERTIFICATE OF COMPLETION")

    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica", 16)
    c.drawCentredString(cx, height - 190, "This is to certify that")

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(cx, height - 250, data.recipient_name)
    c.setLineWidth(0.8)
    c.line(cx - 220, height - 262, cx + 220, height - 262)

    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica", 16)
    c.drawCentredString(cx, height - 305, "has successfully completed")

    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(cx, height - 345, data.course_name)

    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica", 13)
    c.drawString(80, 90, f"Issued on: {data.issue_date.strftime('%d %B %Y')}")
    c.drawRightString(width - 80, 90, f"Issued by: {data.issuer_name}")
    c.setFont("Helvetica", 9)
    c.drawCentredString(cx, 55, f"Certificate ID: {data.certificate_id}")

    if data.verify_url:  # QR code -> public verification endpoint
        size = 80
        qr = QrCodeWidget(data.verify_url)
        x0, y0, x1, y1 = qr.getBounds()
        d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        d.add(qr)
        renderPDF.draw(d, c, cx - size / 2, 100)
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, 90, "Scan to verify")

    c.showPage()
    c.save()
    os.replace(tmp, dest)
    return dest
