import logging
import threading
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import jobs
from app.services import jobs as job_service

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)  # no migrations for this small project
    # Resume anything a previous crash/restart interrupted (see recover_stale_jobs).
    with SessionLocal() as db:
        stale = job_service.recover_stale_jobs(db)
    if stale:
        logging.getLogger(__name__).info("Resuming %d unfinished job(s)", len(stale))
        threading.Thread(
            target=lambda: [job_service.process_job(j) for j in stale], daemon=True
        ).start()
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Submit a list of recipients, get a PDF certificate for each.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(jobs.router)
app.include_router(jobs.public_router)


@app.get("/", include_in_schema=False)
def index():
    """Small single-page UI (plain HTML/JS, no build step) on top of the API."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
