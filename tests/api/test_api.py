"""The HTTP API."""

from __future__ import annotations

import pytest

RESUME_FIELDS = {"id", "name", "skills", "experience", "education", "projects"}


# ------------------------------------------------------------------ meta


async def test_health_reports_more_than_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["llm_available"] is False
    assert "jobs" in body["stats"]


async def test_capabilities_names_the_fix_for_anything_missing(client):
    body = (await client.get("/api/capabilities")).json()
    assert body["transport"] == "http"
    for cap in body["capabilities"]:
        if not cap["available"]:
            assert cap["enable_with"]


async def test_the_openapi_schema_is_generated(client):
    schema = (await client.get("/openapi.json")).json()
    assert schema["info"]["title"] == "CareerCraft"
    assert "/api/match" in schema["paths"]
    # The frontend generates its client from this; unnamed shapes make that
    # client unusable.
    assert "ParsedResume" in schema["components"]["schemas"]
    assert "MatchResult" in schema["components"]["schemas"]


# --------------------------------------------------------------- resumes


async def test_parse_text(client, resume_text):
    response = await client.post("/api/resumes/parse", json={"text": resume_text})
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= RESUME_FIELDS
    assert body["name"] == "Jane Doe"
    assert "Python" in body["skills"]


async def test_parse_rejects_an_empty_body(client):
    assert (await client.post("/api/resumes/parse", json={"text": ""})).status_code == 422


async def test_parse_rejects_unknown_fields(client, resume_text):
    response = await client.post(
        "/api/resumes/parse", json={"text": resume_text, "path": "/etc/passwd"}
    )
    assert response.status_code == 422, "extra='forbid' must reject a smuggled path"


async def test_upload_and_parse(client, resume_text):
    response = await client.post(
        "/api/resumes/upload",
        files={"file": ("cv.txt", resume_text.encode(), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Jane Doe"


async def test_upload_rejects_an_unsupported_type(client):
    response = await client.post(
        "/api/resumes/upload",
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_upload_enforces_the_size_cap(client, settings):
    settings.max_upload_bytes = 512
    response = await client.post(
        "/api/resumes/upload",
        files={"file": ("cv.txt", b"x" * 4096, "text/plain")},
    )
    assert response.status_code == 400


async def test_the_upload_temp_file_does_not_survive(client, settings, resume_text):
    await client.post(
        "/api/resumes/upload",
        files={"file": ("cv.txt", resume_text.encode(), "text/plain")},
    )
    assert list(settings.upload_dir.iterdir()) == []


async def test_list_and_get_and_delete_a_resume(client, resume_text):
    parsed = (await client.post("/api/resumes/parse", json={"text": resume_text})).json()
    listed = (await client.get("/api/resumes")).json()
    assert [r["id"] for r in listed] == [parsed["id"]]

    fetched = (await client.get(f"/api/resumes/{parsed['id']}")).json()
    assert fetched["name"] == "Jane Doe"

    assert (await client.delete(f"/api/resumes/{parsed['id']}")).status_code == 204
    assert (await client.get("/api/resumes")).json() == []


async def test_an_unknown_resume_is_a_404_with_a_remedy(client):
    response = await client.get("/api/resumes/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["remedy"]


# ------------------------------------------------------------------ jobs


async def test_search_then_fetch_a_job(client):
    search = (await client.post("/api/jobs/search", json={"query": "data", "limit": 5})).json()
    assert search["jobs"]
    job_id = search["jobs"][0]["id"]

    fetched = (await client.get(f"/api/jobs/{job_id}")).json()
    assert fetched["id"] == job_id


async def test_search_validates_its_limit(client):
    assert (await client.post("/api/jobs/search", json={"limit": 0})).status_code == 422
    assert (await client.post("/api/jobs/search", json={"limit": 999})).status_code == 422


async def test_recent_jobs(client):
    await client.post("/api/jobs/search", json={"query": "data", "limit": 5})
    assert (await client.get("/api/jobs/recent")).json()


async def test_save_list_and_unsave(client):
    search = (await client.post("/api/jobs/search", json={"query": "data", "limit": 5})).json()
    job_id = search["jobs"][0]["id"]

    assert (await client.post(f"/api/jobs/{job_id}/save", json={"note": "yes"})).status_code == 200
    saved = (await client.get("/api/jobs/saved")).json()
    assert saved[0]["note"] == "yes"
    assert saved[0]["job"]["id"] == job_id

    assert (await client.delete(f"/api/jobs/{job_id}/save")).status_code == 204
    assert (await client.get("/api/jobs/saved")).json() == []


async def test_an_unknown_job_is_a_404(client):
    assert (await client.get("/api/jobs/nope")).status_code == 404


# -------------------------------------------------------- match & letters


async def test_match_returns_ranked_results(client, resume_text):
    parsed = (await client.post("/api/resumes/parse", json={"text": resume_text})).json()
    response = await client.post(
        "/api/match", json={"resume_id": parsed["id"], "query": "data", "min_score": 0.0}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"]
    assert body["strategy_used"] == "keyword"
    assert all(m["rationale"] for m in body["matches"])


async def test_match_validates_min_score(client):
    assert (await client.post("/api/match", json={"min_score": 5})).status_code == 422


async def test_the_web_ui_gets_prose_not_a_brief(client, resume_text):
    """allow_brief defaults to false here: a browser has no model to write from."""
    parsed = (await client.post("/api/resumes/parse", json={"text": resume_text})).json()
    search = (await client.post("/api/jobs/search", json={"query": "data", "limit": 5})).json()

    response = await client.post(
        "/api/letters",
        json={"job_id": search["jobs"][0]["id"], "resume_id": parsed["id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["letter"]["generated_by"] == "template"
    assert body["letter"]["text"]

    fetched = (await client.get(f"/api/letters/{body['id']}")).json()
    assert fetched["text"] == body["letter"]["text"]


async def test_a_letter_for_an_unknown_job_is_a_404(client):
    assert (await client.post("/api/letters", json={"job_id": "nope"})).status_code == 404


# ------------------------------------------------------------------ auth


@pytest.fixture
def token_client(settings, service):
    import httpx

    from careercraft.api.app import create_app

    settings.auth_token = "s3cret"
    app = create_app(settings)
    app.state.service = service
    app.state.settings = settings
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_a_configured_token_is_required(token_client):
    async with token_client as c:
        assert (await c.get("/api/resumes")).status_code == 401
        assert (
            await c.get("/api/resumes", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        ok = await c.get("/api/resumes", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200


async def test_health_stays_open_so_probes_work(token_client):
    async with token_client as c:
        assert (await c.get("/api/health")).status_code == 200
