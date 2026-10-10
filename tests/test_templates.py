from datetime import date

import pytest

from app.services import pdf


@pytest.mark.parametrize("template_id", list(pdf.TEMPLATES))
def test_every_template_renders_recipient_details(tmp_path, template_id):
    dest = tmp_path / f"{template_id}.pdf"
    pdf.render_certificate(
        pdf.CertificateData("cert-1", "Asha Rao", "Intro to GIS", "AEREO", date(2026, 10, 1),
                            verify_url="http://x/verify/1", template=template_id),
        dest,
    )
    data = dest.read_bytes()
    assert data.startswith(b"%PDF")
    for text in (b"Asha Rao", b"Intro to GIS", b"AEREO", b"cert-1", b"01 October 2026"):
        assert text in data


def test_very_long_name_still_renders(tmp_path):
    long_name = "Bartholomew Maximilian Featherstonehaugh-Cholmondeley " * 2
    for template_id in pdf.TEMPLATES:
        pdf.render_certificate(
            pdf.CertificateData("c", long_name.strip()[:100], "x" * 120, "y" * 120, date(2026, 1, 1),
                                template=template_id),
            tmp_path / f"{template_id}.pdf",
        )


def test_unknown_template_raises(tmp_path):
    with pytest.raises(ValueError):
        pdf.render_certificate(
            pdf.CertificateData("c", "A", "B", "C", date(2026, 1, 1), template="nope"), tmp_path / "x.pdf"
        )


def test_template_list_endpoint(client):
    items = client.get("/api/v1/templates").json()
    assert {t["id"] for t in items} == set(pdf.TEMPLATES)


def test_template_preview_returns_pdf(client):
    r = client.get("/api/v1/templates/elegant/preview")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/api/v1/templates/nope/preview").status_code == 404


def test_job_defaults_to_classic(client, make_payload):
    assert client.post("/api/v1/jobs", json=make_payload()).json()["template"] == "classic"


def test_job_uses_chosen_template(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload(template="royal")).json()
    assert job["template"] == "royal"
    after = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert after["template"] == "royal"
    assert after["progress"]["generated"] == 2


def test_unknown_template_rejected_with_422(client, make_payload):
    assert client.post("/api/v1/jobs", json=make_payload(template="nope")).status_code == 422
