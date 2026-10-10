import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.services.pdf import DEFAULT_TEMPLATE, TEMPLATES

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class RecipientIn(BaseModel):
    """Validated form of ONE recipient. Validated per-item (see services/jobs.py)
    so a single bad row doesn't reject the whole bulk request."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        if _CONTROL_CHARS.search(v):
            raise ValueError("name contains control characters")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("email is not a valid address")
        return v


class JobCreate(BaseModel):
    """Request-level validation. Problems here reject the whole request (422).
    Items in `recipients` are intentionally loose; they're validated individually."""

    course_name: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(min_length=1, max_length=200)
    issue_date: date = Field(default_factory=date.today)
    template: str = DEFAULT_TEMPLATE
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients_per_job)

    @field_validator("course_name", "issuer_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


    @field_validator("template")
    @classmethod
    def _known_template(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in TEMPLATES:
            raise ValueError(f"unknown template; choose one of: {', '.join(TEMPLATES)}")
        return v


class Progress(BaseModel):
    total: int
    pending: int
    generated: int
    failed: int
    percent_complete: float  # share of certificates no longer pending


class JobOut(BaseModel):
    id: str
    status: str
    course_name: str
    issuer_name: str
    issue_date: date
    template: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: Progress
    certificates_url: str
    download_url: str


class CertificateOut(BaseModel):
    id: str
    position: int
    recipient_name: str | None
    recipient_email: str | None
    status: str
    error: str | None
    failure_type: str | None
    generated_at: datetime | None
    download_url: str | None


class CertificateList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]
