"""The MCP surface: tools, resources, prompts and error mapping."""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

EXPECTED_TOOLS = {
    "search_jobs",
    "get_job",
    "parse_resume",
    "list_resumes",
    "match_jobs",
    "generate_cover_letter",
    "save_job",
}


# ------------------------------------------------------------ discovery


async def test_the_advertised_tool_set_is_exactly_what_we_intend(client):
    assert {t.name for t in await client.list_tools()} == EXPECTED_TOOLS


async def test_every_tool_has_a_description_and_a_schema(client):
    for tool in await client.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert tool.inputSchema
        # The host model reads output shapes to plan its next call.
        assert tool.outputSchema, f"{tool.name} has no outputSchema"


async def test_the_instructions_point_at_the_capabilities_resource(server):
    assert "careercraft://capabilities" in (server.instructions or "")


async def test_resources_and_templates_are_registered(client):
    static = {str(r.uri) for r in await client.list_resources()}
    templates = {t.uriTemplate for t in await client.list_resource_templates()}
    assert "careercraft://capabilities" in static
    assert "careercraft://resumes" in static
    assert "careercraft://jobs/recent" in static
    assert "careercraft://resume/{resume_id}" in templates
    assert "careercraft://job/{job_id}" in templates
    assert "careercraft://letters/{letter_id}" in templates


async def test_prompts_are_registered(client):
    assert {p.name for p in await client.list_prompts()} == {
        "job_search_workflow",
        "tailor_cover_letter",
        "resume_feedback",
    }


# ---------------------------------------------------------------- tools


async def test_parse_resume_returns_structured_output(client, resume_text):
    result = await client.call_tool("parse_resume", {"text": resume_text})
    assert result.data.name == "Jane Doe"
    assert "Python" in result.data.skills
    assert result.data.id


async def test_search_and_get_job_round_trip(client):
    search = await client.call_tool("search_jobs", {"query": "data", "limit": 5})
    assert search.data.jobs
    job_id = search.data.jobs[0].id
    fetched = await client.call_tool("get_job", {"job_id": job_id})
    assert fetched.data.id == job_id


async def test_the_full_workflow(client, resume_text):
    parsed = await client.call_tool("parse_resume", {"text": resume_text})
    matched = await client.call_tool(
        "match_jobs", {"resume_id": parsed.data.id, "query": "data", "min_score": 0.0}
    )
    assert matched.data.matches
    top = matched.data.matches[0]
    assert top.rationale

    letter = await client.call_tool(
        "generate_cover_letter", {"job_id": top.job.id, "resume_id": parsed.data.id}
    )
    # No Ollama in tests, so the brief path is the one exercised.
    assert letter.data.generated_by == "brief"
    assert letter.data.brief.paragraph_plan


async def test_match_without_a_resume_id_uses_the_latest(client, resume_text):
    await client.call_tool("parse_resume", {"text": resume_text})
    result = await client.call_tool("match_jobs", {"query": "data", "min_score": 0.0})
    assert result.data.matches


async def test_list_resumes_after_parsing(client, resume_text):
    await client.call_tool("parse_resume", {"text": resume_text})
    result = await client.call_tool("list_resumes", {})
    assert len(result.data) == 1
    assert result.data[0].skills_count > 0


async def test_save_job(client):
    search = await client.call_tool("search_jobs", {"query": "data", "limit": 5})
    job_id = search.data.jobs[0].id
    saved = await client.call_tool("save_job", {"job_id": job_id, "note": "apply Monday"})
    assert saved.data.id == job_id


# --------------------------------------------------------------- errors


async def test_a_domain_error_becomes_a_tool_error_with_its_remedy(client):
    with pytest.raises(ToolError) as excinfo:
        await client.call_tool("get_job", {"job_id": "does-not-exist"})
    message = str(excinfo.value)
    assert "not_found" in message
    assert "search_jobs" in message, "the remedy must survive the mapping"


async def test_a_failure_is_never_dressed_up_as_a_result(client):
    """v1 returned {"status": "error"} with a success frame around it."""
    with pytest.raises(ToolError):
        await client.call_tool("parse_resume", {})


async def test_schema_violations_are_rejected_before_the_handler(client):
    with pytest.raises(ToolError):
        await client.call_tool("match_jobs", {"min_score": 42})


async def test_a_path_outside_the_allow_list_is_refused(client, tmp_path, resume_text):
    outside = tmp_path.parent / "outside_the_root.txt"
    outside.write_text(resume_text, encoding="utf-8")
    try:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("parse_resume", {"path": str(outside)})
        assert "access_denied" in str(excinfo.value)
    finally:
        outside.unlink(missing_ok=True)


async def test_a_path_under_the_allow_list_is_accepted(client, tmp_path, resume_text):
    inside = tmp_path / "cv.txt"
    inside.write_text(resume_text, encoding="utf-8")
    result = await client.call_tool("parse_resume", {"path": str(inside)})
    assert result.data.name == "Jane Doe"


async def test_local_paths_are_refused_under_http_transport(
    settings, service, tmp_path, resume_text
):
    from fastmcp import Client

    from careercraft.mcp.server import build_server

    settings.transport = "http"
    inside = tmp_path / "cv.txt"
    inside.write_text(resume_text, encoding="utf-8")

    async with Client(build_server(settings, service=service)) as c:
        with pytest.raises(ToolError) as excinfo:
            await c.call_tool("parse_resume", {"path": str(inside)})
        assert "access_denied" in str(excinfo.value)
        # text= still works, so the tool is not simply unavailable
        assert (await c.call_tool("parse_resume", {"text": resume_text})).data.name


# ------------------------------------------------------------ resources


async def test_capabilities_resource_is_readable_and_honest(client):
    payload = json.loads((await client.read_resource("careercraft://capabilities"))[0].text)
    names = {c["name"] for c in payload["capabilities"]}
    assert "keyword_matching" in names
    assert payload["default_match_strategy"] in {"keyword", "embedding"}
    for cap in payload["capabilities"]:
        if not cap["available"]:
            assert cap["enable_with"], f"{cap['name']} is unavailable with no way to enable it"


async def test_resource_templates_resolve(client, resume_text):
    parsed = await client.call_tool("parse_resume", {"text": resume_text})
    body = (await client.read_resource(f"careercraft://resume/{parsed.data.id}"))[0].text
    assert "Jane Doe" in body

    search = await client.call_tool("search_jobs", {"query": "data", "limit": 3})
    job_id = search.data.jobs[0].id
    assert job_id in (await client.read_resource(f"careercraft://job/{job_id}"))[0].text


async def test_recent_jobs_resource(client):
    await client.call_tool("search_jobs", {"query": "data", "limit": 5})
    payload = json.loads((await client.read_resource("careercraft://jobs/recent"))[0].text)
    assert payload


async def test_saved_jobs_resource_carries_the_notes(client):
    search = await client.call_tool("search_jobs", {"query": "data", "limit": 3})
    job_id = search.data.jobs[0].id
    await client.call_tool("save_job", {"job_id": job_id, "note": "chase this"})
    payload = json.loads((await client.read_resource("careercraft://saved"))[0].text)
    assert payload[0]["note"] == "chase this"


# -------------------------------------------------------------- prompts


async def test_the_workflow_prompt_names_the_role(client):
    result = await client.get_prompt("job_search_workflow", {"role": "data analyst"})
    body = result.messages[0].content.text
    assert "data analyst" in body
    assert "careercraft://capabilities" in body


async def test_the_letter_prompt_covers_the_brief_path(client):
    result = await client.get_prompt("tailor_cover_letter", {"job_id": "abc"})
    body = result.messages[0].content.text
    assert "abc" in body
    assert "brief" in body


async def test_the_feedback_prompt_asks_for_concrete_edits(client):
    body = (await client.get_prompt("resume_feedback", {})).messages[0].content.text
    assert "missing_skills" in body
