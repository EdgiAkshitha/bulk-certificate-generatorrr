import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Certificate, Job
from app.schemas import JobCreate
from app.services import jobs as svc
from app.services import pdf

real_render = pdf.render_certificate


# ---------- authentication ----------
@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "s3cret")


def test_api_requires_key_when_configured(client, make_payload, secured):
    assert client.post("/api/v1/jobs", json=make_payload()).status_code == 401
    assert client.post("/api/v1/jobs", json=make_payload(), headers={"X-API-Key": "wrong"}).status_code == 401
    ok = client.post("/api/v1/jobs", json=make_payload(), headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 202


def test_health_and_verify_stay_public(client, make_payload, secured):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/verify/unknown").status_code == 404  # reachable, not 401


# ---------- idempotency ----------
def test_same_idempotency_key_returns_same_job(client, make_payload):
    h = {"Idempotency-Key": "abc-123"}
    first = client.post("/api/v1/jobs", json=make_payload(), headers=h)
    second = client.post("/api/v1/jobs", json=make_payload(), headers=h)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    with SessionLocal() as db:
        assert db.query(Job).count() == 1


# ---------- retry ----------
def test_retry_regenerates_only_generation_failures(client, make_payload, monkeypatch):
    def flaky(data, dest):
        if data.recipient_name == "Bob":
            raise RuntimeError("transient")
        return real_render(data, dest)

    monkeypatch.setattr(pdf, "render_certificate", flaky)
    recipients = [{"name": "Alice"}, {"name": "Bob"}, {"name": ""}]  # "" = validation failure
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["progress"]["failed"] == 2

    monkeypatch.setattr(pdf, "render_certificate", real_render)  # "fixed"
    assert client.post(f"/api/v1/jobs/{job['id']}/retry").status_code == 202
    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "completed_with_errors"
    assert body["progress"]["generated"] == 2
    failed = client.get(f"/api/v1/jobs/{job['id']}/certificates?status=failed").json()["items"]
    assert [f["failure_type"] for f in failed] == ["validation"]  # not retried
    # nothing left to retry now
    assert client.post(f"/api/v1/jobs/{job['id']}/retry").status_code == 409


# ---------- crash recovery ----------
def test_recovery_resumes_interrupted_job_without_regenerating_done_certs(client, make_payload):
    from app.models import CertificateStatus, JobStatus

    with SessionLocal() as db:
        job, _ = svc.create_job(
            db, JobCreate(course_name="C", issuer_name="I", recipients=[{"name": "A"}, {"name": "B"}])
        )
        job_id = job.id
        # simulate a crash: job stuck in 'processing', first cert already done
        job.status = JobStatus.PROCESSING.value
        first = db.query(Certificate).filter_by(job_id=job_id, position=0).one()
        pdf_path = svc.certificate_path(job_id, first.id)
        real_render(pdf.CertificateData(first.id, "A", "C", "I", job.issue_date), pdf_path)
        first.status, first.file_path = CertificateStatus.GENERATED.value, str(pdf_path)
        db.commit()
        mtime = pdf_path.stat().st_mtime_ns

        stale = svc.recover_stale_jobs(db)
        assert job_id in stale
    for j in stale:
        svc.process_job(j)

    body = client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "completed" and body["progress"]["generated"] == 2
    assert pdf_path.stat().st_mtime_ns == mtime  # untouched


def test_job_is_never_processed_twice(client, make_payload, monkeypatch):
    calls = []
    monkeypatch.setattr(pdf, "render_certificate", lambda d, p: calls.append(d) or real_render(d, p))
    job = client.post("/api/v1/jobs", json=make_payload([{"name": "A"}])).json()
    svc.process_job(job["id"])  # duplicate enqueue: claim fails, no-op
    assert len(calls) == 1


# ---------- verification ----------
def test_verify_endpoint_and_qr_link_in_pdf(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload([{"name": "Asha Rao"}])).json()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]
    r = client.get(f"/api/v1/verify/{item['id']}")
    assert r.status_code == 200
    assert r.json()["valid"] is True and r.json()["recipient_name"] == "Asha Rao"
    assert client.get("/api/v1/verify/nope").status_code == 404
