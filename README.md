# Bulk Certificate Generator

A backend API that accepts **one request containing many recipients**, generates a PDF
certificate for each valid recipient from a single predefined template, tracks progress, and
lets the client retrieve the results (one by one or as a ZIP).

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, SQLite (default) / PostgreSQL, ReportLab (PDF), pytest.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

No other setup is needed: tables and the storage folder are created on startup
(`./data/` by default; see `.env.example` for settings).

## Run

```bash
uvicorn app.main:app --reload
```

Web UI: <http://127.0.0.1:8000/> (paste recipients or load a CSV, watch live progress, download PDFs / ZIP, retry failures)

Interactive API docs: <http://127.0.0.1:8000/docs>

Optional - PostgreSQL via Docker: `docker compose up --build`

## Run tests

```bash
pytest
```

Tests use an isolated temporary SQLite DB and temp storage; they never touch `./data`.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/jobs` | Submit a bulk request (returns `202` + job id) |
| GET | `/api/v1/jobs/{job_id}` | Job status + progress counts |
| GET | `/api/v1/jobs/{job_id}/certificates?status=&limit=&offset=` | Per-recipient results (filter `status=failed` to see errors) |
| GET | `/api/v1/certificates/{certificate_id}/download` | Download one PDF |
| GET | `/api/v1/jobs/{job_id}/download` | ZIP of all successfully generated PDFs |
| POST | `/api/v1/jobs/{job_id}/retry` | Re-run certificates that failed during *generation* |
| GET | `/api/v1/verify/{certificate_id}` | Public verification (target of the QR code on each PDF) |
| GET | `/health` | Liveness |

Optional header on `POST /jobs`: `Idempotency-Key: <string>` - repeating a request with the same
key returns the original job (`200`) instead of generating everything twice.
If the `API_KEY` env var is set, every endpoint except `/health` and `/verify` requires `X-API-Key`.

### Submit a request

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "course_name": "Python for Backend Engineers",
    "issuer_name": "AEREO Academy",
    "issue_date": "2026-10-01",
    "recipients": [
      {"name": "Asha Rao",  "email": "asha@example.com"},
      {"name": "Ben Carter"},
      {"name": "", "email": "broken"}
    ]
  }'
```

Response (`202 Accepted`):

```json
{
  "id": "6f0c…", "status": "queued",
  "progress": {"total": 3, "pending": 2, "generated": 0, "failed": 1, "percent_complete": 33.3},
  "certificates_url": "http://…/api/v1/jobs/6f0c…/certificates",
  "download_url": "http://…/api/v1/jobs/6f0c…/download", "…": "…"
}
```

`issue_date` is optional (defaults to today). Recipient fields: `name` (required, 1-100 chars),
`email` (optional, valid address).

### Check progress

```bash
curl -s http://127.0.0.1:8000/api/v1/jobs/<job_id>
```

Job `status`: `queued` → `processing` → `completed` | `completed_with_errors` | `failed`.
`progress` gives `total / pending / generated / failed / percent_complete`.

### Find out what failed

```bash
curl -s "http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates?status=failed"
```

Each item has `position` (index in your submitted list), the recipient, and an `error` message.

### Retrieve certificates

```bash
# one certificate (use download_url from the listing)
curl -OJ http://127.0.0.1:8000/api/v1/certificates/<certificate_id>/download
# everything that succeeded, as a ZIP (available once the job has finished)
curl -OJ http://127.0.0.1:8000/api/v1/jobs/<job_id>/download
```

## Deploy (Render, free)

1. Push the repo to GitHub.
2. On <https://render.com>: **New + → Blueprint**, select the repo (it reads `render.yaml`).
3. After the first deploy, set `PUBLIC_BASE_URL` to your service URL so QR codes link correctly.

Note: on the free tier the disk is ephemeral, so data resets on restart. Use PostgreSQL and
object storage for anything permanent.

## Demo / load test

```bash
uvicorn app.main:app &
python scripts/demo.py --n 1000      # 1000 recipients, 5% deliberately invalid
```
Roughly 1000 certificates in ~30 s on my test machine (about 18 ms per PDF is rendering).

## Design decisions

**Background processing (not synchronous).** `POST /jobs` stores the job and returns `202`
immediately; FastAPI's `BackgroundTasks` generates the certificates after the response is sent.
Rendering 1,000 PDFs inside a request would hold the connection open and risk client/proxy
timeouts. Clients poll `GET /jobs/{id}`.
*Crash safety:* `BackgroundTasks` runs in-process, so a restart could strand a job. On startup
`recover_stale_jobs` moves `processing` jobs back to `queued` and re-runs them. This is safe
because `process_job` only touches certificates still `pending` (already generated ones are never
redone), and a job is *claimed* with an atomic `UPDATE ... WHERE status='queued'` so it can't run
twice. It assumes one API instance; for several, move `process_job(job_id)` (a plain function that
only needs a job id) onto Celery/RQ + Redis.

**Retry.** Failures are typed (`failure_type`: `validation` or `generation`). `/retry` re-queues only
generation failures - a bad email will never succeed on retry, a transient disk error might.

**Idempotency.** `Idempotency-Key` (unique column) protects against client retries/double clicks
creating duplicate jobs; a race on the same key is resolved by the unique constraint.

**Verification.** Each PDF carries a QR code to `/verify/{id}` (UUID, unguessable) so a certificate
can be checked as genuine. Set `PUBLIC_BASE_URL` to your real host so QR links are correct.

**Auth.** Optional shared API key (constant-time comparison). Chosen over JWT because this is a
service-to-service API with no user accounts; `/verify` stays public by design.

**Two levels of validation.**
1. *Request level* (malformed JSON, missing course/issuer, empty list, more than
   `MAX_RECIPIENTS_PER_JOB` = 1000, bad date) → whole request rejected with `422`.
2. *Recipient level* (blank/too-long name, bad email, wrong shape, duplicate email in the same
   request) → only that recipient is stored as `failed` with a clear reason; the rest proceed.
   This honours "invalid rows must not block valid ones" and tells the client exactly which
   rows to fix, at the cost of a successful `202` even when some rows are bad (check `progress`).

**Failure isolation.** Every certificate is generated in its own `try/except`. One failure is
recorded on that row (`status=failed`, `error=…`) and the loop continues. Results are committed
in batches of 20, so progress is visible while the job runs; if the process dies mid-batch, those
rows are still `pending` and are simply regenerated on resume.
Final job status: all OK → `completed`; mixed → `completed_with_errors`; none → `failed`.

**Progress is computed, not cached.** Counts come from a `GROUP BY status` over the certificates
table, so they can never drift from the real state (no separate counters to keep in sync).

**Storage.** PDFs are written to `STORAGE_DIR/jobs/<job_id>/<certificate_id>.pdf`, via a temp file
+ atomic rename so a crash never leaves a half-written file. The DB stores metadata and the path.
IDs are UUIDs, so certificate URLs aren't guessable by incrementing a number.

**Template.** A single landscape-A4 template drawn with ReportLab (no external assets, no
templating engine, deterministic output). Contains recipient name, course, issue date, issuer and
the certificate ID.

**Schema.** `jobs` (1) → `certificates` (N); unique `(job_id, position)`; indexes on `job_id` and
`status`. Tables are created with `create_all` - I'd add Alembic migrations before real deployments.

## Known limitations / possible next steps

- Multi-instance deployment needs a real queue; no rate limiting; API key not per-tenant.
- Built-in PDF fonts (Helvetica) only cover Latin characters; for other scripts register a
  Unicode TTF font in `app/services/pdf.py`.
- Retention/cleanup of old files; S3-compatible storage instead of local disk.

## Project layout

```
app/
  main.py            FastAPI app + startup
  static/index.html  single-page UI (plain HTML/JS, no build step)
  config.py          settings from env vars
  database.py        engine / session / get_db
  models.py          Job, Certificate (+ status enums)
  schemas.py         request/response + per-recipient validation
  routers/jobs.py    HTTP endpoints
  services/jobs.py   create_job, process_job, progress (business logic)
  services/pdf.py    certificate template rendering (+ QR code)
  security.py        API-key dependency
tests/               pytest suite (36 tests: create, validation, generation, status, failures,
                     retrieval, auth, idempotency, retry, crash recovery, verification, UI)
scripts/demo.py      end-to-end demo / load test
.github/workflows    CI running pytest on every push
```
