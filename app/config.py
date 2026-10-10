"""Application settings, read from environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/certificates.db")
    )
    storage_dir: Path = field(
        default_factory=lambda: Path(os.getenv("STORAGE_DIR", "./data/certificates"))
    )
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))  # empty = auth disabled (dev)
    public_base_url: str = field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    )
    max_recipients_per_job: int = field(
        default_factory=lambda: int(os.getenv("MAX_RECIPIENTS_PER_JOB", "1000"))
    )


settings = Settings()
