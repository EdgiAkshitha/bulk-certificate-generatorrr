from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.services import jobs as svc
from app.schemas import JobCreate


def test_completed_job_status_and_progress(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload()).json()
    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "completed"
    assert body["progress"] == {
        "total": 2, "pending": 0, "generated": 2, "failed": 0, "percent_complete": 100.0,
    }
    assert body["started_at"] and body["completed_at"]


def test_all_invalid_recipients_marks_job_failed(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload([{"name": ""}, {"nope": 1}])).json()
    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "failed"
    assert body["progress"]["failed"] == 2


def test_progress_reflects_partially_processed_job():
    """A job that hasn't been processed yet reports everything valid as pending."""
    with SessionLocal() as db:
        job, _ = svc.create_job(
            db,
            JobCreate(
                course_name="C", issuer_name="I",
                recipients=[{"name": "A"}, {"name": "B"}, {"name": ""}],
            ),
        )
        assert job.status == JobStatus.QUEUED.value
        p = svc.get_progress(db, job)
        assert (p.total, p.pending, p.generated, p.failed) == (3, 2, 0, 1)
        assert p.percent_complete == 33.3

        # simulate the worker finishing exactly one certificate
        cert = db.query(Certificate).filter_by(job_id=job.id, status="pending").first()
        cert.status = CertificateStatus.GENERATED.value
        db.commit()
        p = svc.get_progress(db, job)
        assert (p.pending, p.generated, p.failed) == (1, 1, 1)
        assert p.percent_complete == 66.7
