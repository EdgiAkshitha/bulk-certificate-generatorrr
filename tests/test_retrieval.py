import io
import zipfile


def test_download_single_certificate(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload()).json()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]
    r = client.get(item["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and b"Asha Rao" in r.content
    assert "certificate_Asha_Rao.pdf" in r.headers["content-disposition"]


def test_download_all_as_zip(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload()).json()
    r = client.get(f"/api/v1/jobs/{job['id']}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert zf.namelist() == ["0001_Asha_Rao.pdf", "0002_Ben_Carter.pdf"]
    assert all(zf.read(n).startswith(b"%PDF") for n in zf.namelist())


def test_zip_conflict_while_job_not_finished(client, make_payload):
    from app.database import SessionLocal
    from app.schemas import JobCreate
    from app.services import jobs as svc

    with SessionLocal() as db:
        job, _ = svc.create_job(db, JobCreate(course_name="C", issuer_name="I", recipients=[{"name": "A"}]))
    assert client.get(f"/api/v1/jobs/{job.id}/download").status_code == 409


def test_unknown_certificate_404(client):
    assert client.get("/api/v1/certificates/nope/download").status_code == 404


def test_missing_file_on_disk_returns_410(client, make_payload):
    from pathlib import Path

    job = client.post("/api/v1/jobs", json=make_payload([{"name": "A"}])).json()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]
    from app.database import SessionLocal
    from app.models import Certificate

    with SessionLocal() as db:
        Path(db.get(Certificate, item["id"]).file_path).unlink()
    assert client.get(item["download_url"]).status_code == 410


def test_pagination_and_status_filter(client, make_payload):
    recipients = [{"name": f"P{i}"} for i in range(5)] + [{"name": ""}]
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()
    page = client.get(f"/api/v1/jobs/{job['id']}/certificates?limit=2&offset=4").json()
    assert page["total"] == 6 and [i["position"] for i in page["items"]] == [4, 5]
    only_ok = client.get(f"/api/v1/jobs/{job['id']}/certificates?status=generated").json()
    assert only_ok["total"] == 5
    assert client.get(f"/api/v1/jobs/{job['id']}/certificates?status=bogus").status_code == 422
