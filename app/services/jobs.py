"""Business logic: create jobs, validate recipients, generate certificates."""
import logging
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus, new_id, utcnow
from app.schemas import JobCreate, Progress, RecipientIn
from app.services import pdf

logger = logging.getLogger(__name__)

COMMIT_BATCH = 20  # progress becomes visible to pollers every N certificates


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'recipient'}: {e['msg']}" for e in exc.errors()
    )


def create_job(db: Session, payload: JobCreate, idempotency_key: str | None = None) -> tuple[Job, bool]:
    """Persist a job plus one Certificate row per submitted recipient.

    Each recipient is validated on its own. Invalid ones are stored as FAILED with
    a reason (so the client can see exactly which rows were rejected and why);
    valid ones are stored as PENDING and picked up by the background worker.

    Returns (job, created). With an Idempotency-Key, a repeated request returns the
    original job (created=False) instead of generating everything twice.
    """
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing:
            return existing, False
    job = Job(
        course_name=payload.course_name,
        issuer_name=payload.issuer_name,
        issue_date=payload.issue_date,
        template=payload.template,
        total_count=len(payload.recipients),
        idempotency_key=idempotency_key,
    )
    seen_emails: set[str] = set()

    for position, raw in enumerate(payload.recipients):
        cert = Certificate(job=job, position=position, raw_data=_json_safe(raw))
        try:
            if not isinstance(raw, dict):
                raise ValueError("recipient must be an object with a 'name' field")
            recipient = RecipientIn.model_validate(raw)
            cert.recipient_name = recipient.name
            cert.recipient_email = recipient.email
            if recipient.email:
                if recipient.email in seen_emails:
                    raise ValueError(f"duplicate recipient email in this request: {recipient.email}")
                seen_emails.add(recipient.email)
            cert.status = CertificateStatus.PENDING.value
        except ValidationError as exc:
            cert.status = CertificateStatus.FAILED.value
            cert.failure_type = "validation"
            cert.error = f"Validation error - {_format_validation_error(exc)}"
        except ValueError as exc:
            cert.status = CertificateStatus.FAILED.value
            cert.failure_type = "validation"
            cert.error = f"Validation error - {exc}"

    db.add(job)
    try:
        db.commit()
    except IntegrityError:  # two identical requests raced on the same Idempotency-Key
        db.rollback()
        return db.scalar(select(Job).where(Job.idempotency_key == idempotency_key)), False
    return job, True


def _json_safe(raw):
    """Keep the original payload for debugging, but only if it's JSON-storable."""
    return raw if isinstance(raw, (dict, list, str, int, float, bool)) or raw is None else str(raw)


def certificate_path(job_id: str, cert_id: str) -> Path:
    return settings.storage_dir / "jobs" / job_id / f"{cert_id}.pdf"


def process_job(job_id: str) -> None:
    """Background worker. Generates every PENDING certificate of the job.

    Each certificate is isolated in its own try/except, so one failure never blocks
    the others. Results are committed in small batches so progress is visible to
    status polling while the job runs. If the process dies mid-batch, those rows stay
    PENDING and are simply regenerated on resume (rendering overwrites atomically).
    """
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("process_job: job %s not found", job_id)
            return
        try:
            # Atomic claim: only one worker can move queued -> processing, so a job is
            # never processed twice (e.g. duplicate enqueue after a restart).
            claimed = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
                .values(status=JobStatus.PROCESSING.value, started_at=utcnow())
            ).rowcount
            db.commit()
            if not claimed:
                return
            db.refresh(job)

            pending = db.scalars(
                select(Certificate)
                .where(
                    Certificate.job_id == job_id,
                    Certificate.status == CertificateStatus.PENDING.value,
                )
                .order_by(Certificate.position)
            ).all()

            for i, cert in enumerate(pending, 1):
                _generate_one(db, job, cert)
                if i % COMMIT_BATCH == 0:  # batch commits: ~2x faster than a commit per row
                    db.commit()
            db.commit()

            _finalize(db, job)
        except Exception:  # unexpected infrastructure failure (DB down, ...)
            logger.exception("Job %s crashed", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            job.status = JobStatus.FAILED.value
            job.completed_at = utcnow()
            db.commit()


def _generate_one(db: Session, job: Job, cert: Certificate) -> None:
    try:
        dest = certificate_path(job.id, cert.id)
        pdf.render_certificate(
            pdf.CertificateData(
                certificate_id=cert.id,
                recipient_name=cert.recipient_name,
                course_name=job.course_name,
                issuer_name=job.issuer_name,
                issue_date=job.issue_date,
                template=job.template or "classic",
                verify_url=f"{settings.public_base_url}/api/v1/verify/{cert.id}",
            ),
            dest,
        )
        cert.status = CertificateStatus.GENERATED.value
        cert.file_path = str(dest)
        cert.generated_at = utcnow()
        cert.error = None
        cert.failure_type = None
    except Exception as exc:
        logger.exception("Certificate %s (job %s) failed", cert.id, job.id)
        cert.status = CertificateStatus.FAILED.value
        cert.failure_type = "generation"
        cert.error = f"Generation failed - {type(exc).__name__}: {exc}"


def _finalize(db: Session, job: Job) -> None:
    p = get_progress(db, job)
    if p.generated == 0:
        job.status = JobStatus.FAILED.value
    elif p.failed > 0:
        job.status = JobStatus.COMPLETED_WITH_ERRORS.value
    else:
        job.status = JobStatus.COMPLETED.value
    job.completed_at = utcnow()
    db.commit()


def get_progress(db: Session, job: Job) -> Progress:
    rows = dict(
        db.execute(
            select(Certificate.status, func.count())
            .where(Certificate.job_id == job.id)
            .group_by(Certificate.status)
        ).all()
    )
    pending = rows.get(CertificateStatus.PENDING.value, 0)
    generated = rows.get(CertificateStatus.GENERATED.value, 0)
    failed = rows.get(CertificateStatus.FAILED.value, 0)
    total = job.total_count
    done = generated + failed
    return Progress(
        total=total,
        pending=pending,
        generated=generated,
        failed=failed,
        percent_complete=round(100 * done / total, 1) if total else 100.0,
    )


def safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip()
    return "_".join(cleaned.split()) or "certificate"


def recover_stale_jobs(db: Session) -> list[str]:
    """Run at startup. Jobs left 'processing' by a crash/restart are put back to 'queued'
    and returned together with already-queued ones so they can be re-enqueued.
    Safe to resume: process_job only touches certificates that are still PENDING,
    so already generated certificates are never regenerated.
    Assumes a single API instance (with several, use a real queue / row locks)."""
    db.execute(
        update(Job)
        .where(Job.status == JobStatus.PROCESSING.value)
        .values(status=JobStatus.QUEUED.value)
    )
    db.commit()
    return list(db.scalars(select(Job.id).where(Job.status == JobStatus.QUEUED.value)))


def requeue_failed_generations(db: Session, job: Job) -> int:
    """Retry only certificates that failed during *generation* (transient errors).
    Validation failures need corrected input, so retrying them would be pointless."""
    n = db.execute(
        update(Certificate)
        .where(
            Certificate.job_id == job.id,
            Certificate.status == CertificateStatus.FAILED.value,
            Certificate.failure_type == "generation",
        )
        .values(status=CertificateStatus.PENDING.value, error=None, failure_type=None)
    ).rowcount
    if n:
        job.status = JobStatus.QUEUED.value
        job.completed_at = None
    db.commit()
    return n
