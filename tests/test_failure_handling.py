import pytest

from app.services import pdf

real_render = pdf.render_certificate


@pytest.fixture
def explode_for_bob(monkeypatch):
    def flaky(data, dest):
        if data.recipient_name == "Bob":
            raise RuntimeError("disk exploded")
        return real_render(data, dest)

    monkeypatch.setattr(pdf, "render_certificate", flaky)


def test_one_generation_failure_does_not_block_others(client, make_payload, explode_for_bob):
    recipients = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}]
    job = client.post("/api/v1/jobs", json=make_payload(recipients)).json()

    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "completed_with_errors"
    assert body["progress"]["generated"] == 2
    assert body["progress"]["failed"] == 1

    items = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"]
    by_name = {i["recipient_name"]: i for i in items}
    assert by_name["Alice"]["status"] == "generated"
    assert by_name["Carol"]["status"] == "generated"
    assert by_name["Bob"]["status"] == "failed"
    assert "disk exploded" in by_name["Bob"]["error"]
    assert by_name["Bob"]["download_url"] is None


def test_failed_certificate_cannot_be_downloaded(client, make_payload, explode_for_bob):
    job = client.post("/api/v1/jobs", json=make_payload([{"name": "Bob"}, {"name": "Alice"}])).json()
    bob = client.get(f"/api/v1/jobs/{job['id']}/certificates?status=failed").json()["items"][0]
    assert client.get(f"/api/v1/certificates/{bob['id']}/download").status_code == 409


def test_zip_contains_only_successful_certificates(client, make_payload, explode_for_bob):
    import io, zipfile

    job = client.post(
        "/api/v1/jobs", json=make_payload([{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}])
    ).json()
    r = client.get(f"/api/v1/jobs/{job['id']}/download")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["0001_Alice.pdf", "0003_Carol.pdf"]


def test_every_generation_failing_marks_job_failed(client, make_payload, monkeypatch):
    def boom(data, dest):
        raise OSError("no space left")

    monkeypatch.setattr(pdf, "render_certificate", boom)
    job = client.post("/api/v1/jobs", json=make_payload()).json()
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "failed"
    assert client.get(f"/api/v1/jobs/{job['id']}/download").status_code == 404
