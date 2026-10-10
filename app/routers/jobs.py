import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.security import require_api_key
from app.schemas import CertificateList, CertificateOut, JobCreate, JobOut
from app.services import jobs as svc
from app.services import pdf

router = APIRouter(prefix="/api/v1", tags=["certificates"], dependencies=[Depends(require_api_key)])
public_router = APIRouter(prefix="/api/v1", tags=["verification"])

FINISHED = {
    JobStatus.COMPLETED.value,
    JobStatus.COMPLETED_WITH_ERRORS.value,
    JobStatus.FAILED.value,
}


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


def _job_out(request: Request, db: Session, job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        course_name=job.course_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        template=job.template,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=svc.get_progress(db, job),
        certificates_url=str(request.url_for("list_certificates", job_id=job.id)),
        download_url=str(request.url_for("download_job_zip", job_id=job.id)),
    )


def _cert_out(request: Request, cert: Certificate) -> CertificateOut:
    url = None
    if cert.status == CertificateStatus.GENERATED.value:
        url = str(request.url_for("download_certificate", certificate_id=cert.id))
    return CertificateOut(
        id=cert.id,
        position=cert.position,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        status=cert.status,
        error=cert.error,
        failure_type=cert.failure_type,
        generated_at=cert.generated_at,
        download_url=url,
    )


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: JobCreate,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
):
    """Submit a bulk generation request. Returns immediately (202) with a job id;
    generation continues in the background - poll GET /jobs/{id} for progress."""
    job, created = svc.create_job(db, payload, idempotency_key)
    if created:
        background_tasks.add_task(svc.process_job, job.id)
    else:  # repeated Idempotency-Key: return the original job, don't regenerate
        response.status_code = status.HTTP_200_OK
    return _job_out(request, db, job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    return _job_out(request, db, _get_job_or_404(db, job_id))


@router.get("/jobs/{job_id}/certificates", response_model=CertificateList, name="list_certificates")
def list_certificates(
    job_id: str,
    request: Request,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Per-recipient results. Filter with ?status=failed to see only the failures."""
    _get_job_or_404(db, job_id)
    cond = [Certificate.job_id == job_id]
    if status_filter:
        cond.append(Certificate.status == status_filter.value)
    total = db.scalar(select(func.count()).select_from(Certificate).where(*cond))
    rows = db.scalars(
        select(Certificate).where(*cond).order_by(Certificate.position).limit(limit).offset(offset)
    ).all()
    return CertificateList(
        total=total, limit=limit, offset=offset, items=[_cert_out(request, c) for c in rows]
    )


@router.get("/jobs/{job_id}/download", name="download_job_zip")
def download_job_zip(job_id: str, db: Session = Depends(get_db)):
    """ZIP of every successfully generated certificate in the job."""
    job = _get_job_or_404(db, job_id)
    if job.status not in FINISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is still being processed")
    certs = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id, Certificate.status == CertificateStatus.GENERATED.value
        )
    ).all()
    if not certs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No certificates were generated for this job")

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            zf.write(c.file_path, f"{c.position + 1:04d}_{svc.safe_filename(c.recipient_name)}.pdf")
    tmp.close()
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
        background=BackgroundTask(Path(tmp.name).unlink, missing_ok=True),
    )


@router.get("/certificates/{certificate_id}/download", name="download_certificate")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    if cert.status != CertificateStatus.GENERATED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Certificate is not available (status: {cert.status})"
        )
    if not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status.HTTP_410_GONE, "Certificate file is missing from storage")
    return FileResponse(
        cert.file_path,
        media_type="application/pdf",
        filename=f"certificate_{svc.safe_filename(cert.recipient_name)}.pdf",
    )


@router.post("/jobs/{job_id}/retry", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Re-run certificates that failed during generation (not validation failures)."""
    job = _get_job_or_404(db, job_id)
    if job.status not in FINISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is still being processed")
    if svc.requeue_failed_generations(db, job) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "No generation failures to retry")
    background_tasks.add_task(svc.process_job, job.id)
    return _job_out(request, db, job)


@public_router.get("/verify/{certificate_id}")
def verify_certificate(certificate_id: str, db: Session = Depends(get_db)):
    """Public endpoint behind the QR code on each certificate: confirms it is genuine."""
    cert = db.get(Certificate, certificate_id)
    if cert is None or cert.status != CertificateStatus.GENERATED.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found or not valid")
    job = cert.job
    return {
        "valid": True,
        "certificate_id": cert.id,
        "recipient_name": cert.recipient_name,
        "course_name": job.course_name,
        "issuer_name": job.issuer_name,
        "issue_date": job.issue_date,
        "generated_at": cert.generated_at,
    }


@public_router.get("/templates")
def list_templates():
    """Available certificate templates (use the `id` as `template` when creating a job)."""
    return [
        {
            "id": t.id,
            "label": t.label,
            "description": t.description,
            "preview_url": f"/api/v1/templates/{t.id}/preview",
        }
        for t in pdf.TEMPLATES.values()
    ]


@public_router.get("/templates/{template_id}/preview")
def preview_template(template_id: str):
    """Sample PDF of a template, so you can look before choosing."""
    if template_id not in pdf.TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    from datetime import date

    with tempfile.TemporaryDirectory() as tmp:
        dest = pdf.render_certificate(
            pdf.CertificateData(
                certificate_id="preview-0000-0000",
                recipient_name="Asha Rao",
                course_name="Python for Backend Engineers",
                issuer_name="AEREO Academy",
                issue_date=date.today(),
                verify_url="https://example.com/verify/preview",
                template=template_id,
            ),
            Path(tmp) / "preview.pdf",
        )
        data = dest.read_bytes()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="preview-{template_id}.pdf"'})
