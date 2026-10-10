import pytest


@pytest.mark.parametrize(
    "overrides",
    [
        {"recipients": []},                      # empty list
        {"course_name": "   "},                  # blank course
        {"issuer_name": ""},                     # missing issuer
        {"issue_date": "not-a-date"},
        {"recipients": "Alice"},                 # wrong type
    ],
)
def test_request_level_validation_rejects_whole_request(client, make_payload, overrides):
    r = client.post("/api/v1/jobs", json=make_payload(**overrides))
    assert r.status_code == 422


def test_missing_required_fields_rejected(client):
    assert client.post("/api/v1/jobs", json={"recipients": [{"name": "A"}]}).status_code == 422


def test_too_many_recipients_rejected(client, make_payload):
    from app.config import settings

    too_many = [{"name": f"P{i}"} for i in range(settings.max_recipients_per_job + 1)]
    assert client.post("/api/v1/jobs", json=make_payload(too_many)).status_code == 422


def test_invalid_recipients_fail_individually_valid_ones_still_generated(client, make_payload):
    recipients = [
        {"name": "Good One", "email": "good@example.com"},
        {"name": "   "},                                    # blank name
        {"email": "noname@example.com"},                    # missing name
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": "x" * 101},                                # too long
        "just a string",                                    # wrong shape
        {"name": "Good Two"},
    ]
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()
    job = client.get(f"/api/v1/jobs/{job['id']}").json()

    assert job["status"] == "completed_with_errors"
    assert job["progress"] == {
        "total": 7, "pending": 0, "generated": 2, "failed": 5, "percent_complete": 100.0,
    }
    failed = client.get(f"/api/v1/jobs/{job['id']}/certificates?status=failed").json()["items"]
    assert [f["position"] for f in failed] == [1, 2, 3, 4, 5]
    assert all(f["error"].startswith("Validation error") for f in failed)
    assert all(f["download_url"] is None for f in failed)


def test_duplicate_email_in_same_request_is_rejected_for_the_duplicate(client, make_payload):
    recipients = [{"name": "A", "email": "dup@example.com"}, {"name": "B", "email": "DUP@example.com"}]
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()
    items = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"]
    assert [i["status"] for i in items] == ["generated", "failed"]
    assert "duplicate" in items[1]["error"]


def test_names_are_trimmed(client, make_payload):
    job = client.post("/api/v1/jobs", json=make_payload([{"name": "  Asha Rao  "}])).json()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]
    assert item["recipient_name"] == "Asha Rao"
