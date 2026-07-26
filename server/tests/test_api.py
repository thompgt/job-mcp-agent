import json
from fastapi.testclient import TestClient

from server.app.main import app


client = TestClient(app)


def fake_fetch_jobs(count: int = 100, out_path=None):
    # Signature must accept the kwargs MCPController.ingest() passes through.
    return [
        {"title": "SWE Intern", "companyName": "Acme", "location": "Remote"},
        {"title": "Data Analyst", "companyName": "Beta", "location": "NYC"},
    ]


def test_ingest_and_list(monkeypatch):
    # patch fetch_jobs used by MCPController
    import server.app.controllers.mcp_controller as mc

    monkeypatch.setattr(mc, "fetch_jobs", fake_fetch_jobs)

    r = client.post("/api/ingest")
    assert r.status_code == 200
    data = r.json()
    assert data["imported"] == 2

    r2 = client.get("/api/jobs")
    assert r2.status_code == 200
    jobs = r2.json()
    assert len(jobs) >= 2


def test_claim_and_complete(monkeypatch):
    import server.app.controllers.mcp_controller as mc

    monkeypatch.setattr(
        mc,
        "fetch_jobs",
        lambda *a, **kw: [{"title": "Test", "companyName": "Co", "location": "X"}],
    )

    r = client.post("/api/ingest")
    assert r.status_code == 200

    # list jobs and pick first id
    r2 = client.get("/api/jobs")
    jobs = r2.json()
    job_id = jobs[0]["id"]

    r3 = client.post(f"/api/jobs/{job_id}/claim")
    assert r3.status_code == 200

    r4 = client.post(f"/api/jobs/{job_id}/complete", json={"ok": True})
    assert r4.status_code == 200
