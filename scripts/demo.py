"""End-to-end demo / load test against a running server (stdlib only).

    uvicorn app.main:app &            # in another terminal
    python scripts/demo.py --n 1000   # submits N recipients (5% deliberately invalid)
"""
import argparse
import json
import time
import urllib.request


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--api-key", default="")
    a = ap.parse_args()
    h = {"X-API-Key": a.api_key} if a.api_key else {}

    recipients = [
        {"name": "" if i % 20 == 19 else f"Participant {i}", "email": f"p{i}@example.com"}
        for i in range(a.n)
    ]
    t0 = time.perf_counter()
    job = call("POST", f"{a.base}/api/v1/jobs", {
        "course_name": "Python for Backend Engineers", "issuer_name": "AEREO Academy",
        "recipients": recipients}, h)
    print(f"accepted in {time.perf_counter() - t0:.2f}s -> job {job['id']}")

    while True:
        job = call("GET", f"{a.base}/api/v1/jobs/{job['id']}", headers=h)
        p = job["progress"]
        print(f"  {job['status']:<22} {p['percent_complete']:>5}%  ok={p['generated']} failed={p['failed']}")
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.5)
    print(f"finished in {time.perf_counter() - t0:.2f}s")
    print("download all:", job["download_url"])


if __name__ == "__main__":
    main()
