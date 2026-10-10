def test_create_job_returns_202_and_job_id(client, make_payload):
    r = client.post("/api/v1/jobs", json=make_payload())
    assert r.status_code == 202
    body = r.json()
    assert body["id"]
    assert body["progress"]["total"] == 2
    assert body["course_name"] == "Python for Backend Engineers"


def test_bulk_request_creates_one_certificate_per_recipient(client, make_payload):
    recipients = [{"name": f"Person {i}", "email": f"p{i}@example.com"} for i in range(50)]
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()
    listing = client.get(f"/api/v1/jobs/{job['id']}/certificates?limit=500").json()
    assert listing["total"] == 50
    assert [c["position"] for c in listing["items"]] == list(range(50))


def test_unknown_job_returns_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404


def test_web_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Bulk Certificate Generator" in r.text
