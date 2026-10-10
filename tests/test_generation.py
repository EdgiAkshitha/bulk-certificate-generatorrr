from datetime import date
from pathlib import Path

from app.services import pdf


def test_render_certificate_creates_pdf_with_recipient_details(tmp_path):
    dest = tmp_path / "out" / "c.pdf"
    pdf.render_certificate(
        pdf.CertificateData("cert-123", "Asha Rao", "Intro to GIS", "AEREO", date(2026, 10, 1)), dest
    )
    data = dest.read_bytes()
    assert data.startswith(b"%PDF")
    for text in (b"Asha Rao", b"Intro to GIS", b"AEREO", b"cert-123", b"01 October 2026"):
        assert text in data
    assert not list(dest.parent.glob("*.tmp")), "temp file must be cleaned up"


def test_job_generates_all_certificates_on_disk(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload()).json()
    items = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"]
    assert len(items) == 2 and all(i["status"] == "generated" for i in items)
    from app.config import settings

    files = list((settings.storage_dir / "jobs" / job["id"]).glob("*.pdf"))
    assert len(files) == 2
