# CareerCraft v2 — migration plan

Rewriting this project from a class assignment into a **production-ready MCP
server that other people can install and use**.

Distribution name: `careercraft-mcp` · import package: `careercraft`

---

## 1. Why

The v1 tree has three competing FastAPI apps, two MCP servers, two UIs, and a
parallel non-MCP reimplementation of the whole pipeline in
`server/api_frontend.py`, held together by `sys.path` hacks and five launcher
scripts. The `docker-compose.yml` cannot work: its healthcheck curls `/mcp`
then `/`, but `server/app/main.py` mounts only `/api/*`, so both 404 and the
`api` service never becomes healthy. `frontend` then waits on a
`depends_on: api` with no `condition: service_healthy`.

It also can't be *installed*. There is no package, no entry point, no lockfile
— you clone it and run scripts.

## 2. Decisions (locked)

| Question | Decision |
|---|---|
| Primary deliverable | **MCP server first** — `uvx careercraft-mcp` into Claude Desktop / Claude Code / Cursor. stdio primary, streamable-HTTP secondary. |
| LLM backend | **Ollama only.** No cloud providers. Accessed behind a swappable `LLMProvider` protocol so every non-LLM tool works when Ollama is absent. |
| Rewrite scope | **Consolidate hard.** One core library, one MCP server, one API, one UI. Delete the duplicates. `src/` layout. |
| Frontend | Next.js + TypeScript + Tailwind + shadcn/ui, typed client generated from the FastAPI OpenAPI schema. |

## 3. Target layout

```
src/careercraft/
  settings.py  logging.py  errors.py  models.py  capabilities.py
  core/resume/{extract,parse,skills}.py
  core/matching/{base,keyword,embedding,heuristics,service}.py
  core/letters/{templates,prompts,generator}.py
  core/jobs/{service.py,providers/{base,jobicy,mock}.py}
  adapters/llm/{base,ollama,null,registry}.py
  adapters/storage/{base,sqlite,models}.py
  adapters/files.py
  mcp/{server,tools,resources,prompts}.py
  api/{app,deps,schemas,routers/}
  cli.py
tests/{unit,mcp,api,fixtures}/   web/   scripts/   docs/
```

**Module boundary rule:** `core/**` may import only `models` / `errors` /
`settings` / stdlib. Never `adapters`, `mcp`, `api`, `fastmcp`, `fastapi`,
`sqlalchemy`. Enforced by ruff `flake8-tidy-imports` banned-api.

## 4. MCP surface

Seven tools replace the fourteen spread across two v1 servers.

| Tool | Signature |
|---|---|
| `search_jobs` | `(query, location, limit=25, remote_only=True, refresh=False)` |
| `get_job` | `(job_id)` |
| `parse_resume` | `(path=None, text=None, persist=True)` |
| `match_jobs` | `(resume_id=None, query=None, top_k=10, min_score=0.25, strategy="auto", filter_seniority=True)` |
| `generate_cover_letter` | `(job_id, resume_id=None, tone, length, model=None, allow_template=True)` |
| `list_resumes` | `(limit=20)` |
| `save_job` / `list_saved_jobs` | shortlist |

Dropped: `run_complete_pipeline` (a hardcoded 5-stage orchestration inside one
tool defeats MCP — it becomes the `job_search_workflow` **prompt**, driven by
the host model), `match_jobs_from_resume_path` (→ `resume_id` param),
`populate_mongodb` (→ internal), all queue tools.

**Resources:** `careercraft://capabilities`, `://resumes`, `://resume/{id}`,
`://jobs/recent`, `://job/{id}`, `://letters/{id}`.
**Prompts:** `job_search_workflow`, `tailor_cover_letter`, `resume_feedback`.

## 5. Weight budget

`sentence-transformers` pulls ~2–2.5 GB of torch. That is disqualifying for
`uvx`. Three-layer defence:

1. It is an **extra**, never a base dependency.
2. **Keyword matching is the default strategy** — a real BM25-ish scorer, not
   an ImportError accident. (v1's `_fallback_keyword_score` returned
   `matched/total` and was compared against the same `min_similarity=0.25`
   cosine threshold; those scores are not comparable. Fixed.)
3. Deferred import + `anyio.to_thread` + `CapacityLimiter(1)` for torch.

Extras: `pdf`, `nlp`, `ocr`, `embeddings`, `llm`, `api`, `all`.

```
uvx careercraft-mcp                                    # instant, keyword matching
uvx --from 'careercraft-mcp[pdf,nlp]' careercraft-mcp  # good parsing, ~200 MB
uvx --from 'careercraft-mcp[all]' careercraft-mcp      # semantic, ~2.5 GB
```

## 6. Storage

MongoDB is dropped. Its `jobs` collection is `{source_hash, payload}` — a
key-value blob store, i.e. one SQLite table. v2 uses SQLite (WAL, in a
`platformdirs` data dir) via SQLAlchemy 2.0 async + aiosqlite.

## 7. Non-negotiables

- **stdio purity.** All logging to stderr; stdout carries only JSON-RPC
  frames. A test asserts stdout is byte-empty after a tool call.
- **Error semantics.** No `{"status": "error"}` returns — that is invisible to
  the protocol. Raise `ToolError` with a remedy naming the exact fix command.
- **Uploads.** The client filename is discarded; files are written to
  `settings.upload_dir / f"{uuid4().hex}{validated_suffix}"`, streamed in
  64 KB chunks under a hard `max_bytes`.
- **Path access.** `expanduser().resolve(strict=True)` then `is_relative_to`
  against `settings.allowed_paths`. `path=` is **rejected outright** in HTTP
  transport mode.
- **Bind guard.** Refuse to start when binding a non-loopback interface
  without an auth token. CORS `"*"` + `allow_credentials` rejected at startup.

## 8. Phases

| # | Phase | Output |
|---|---|---|
| 0 | Safety net | `v0-legacy` tag, `rewrite/v2` branch, LICENSE, gitignore, golden parser fixtures |
| 1 | Scaffold | `pyproject.toml`, ruff/mypy/pytest config, pre-commit, CI |
| 2 | Core domain | `models`, `core/*`, `adapters/llm`, `adapters/storage` |
| 3 | MCP server | `mcp/*`, `cli.py`; ship `0.1.0a1` and install it into Claude Desktop |
| 4 | Deletion | one `git rm` commit — only after the replacement is proven |
| 5 | HTTP API | `api/*`, SSE progress |
| 6 | Frontend | Next.js + shadcn/ui |
| 7 | Distribution | Dockerfile, compose, release workflow, README, `server.json` |

Critical path is 1 → 2 → 3 → 4. Phase 4 must **not** be parallelised with 3.

## 9. Open risks

1. `resume_parser.py`'s heavy imports are module-level and unguarded
   (v1 lines 25–29). Making them lazy is real work. Mitigation: golden
   fixtures committed in Phase 0; treat the port as *moved with import
   surgery*, not rewritten.
2. The regex-only parser backend may be too weak. If so, promote `[nlp]` to a
   base dependency.
3. **Ollama absence is the common case** for a public MCP server. So
   `generate_cover_letter` returns a structured *brief* (matched skills,
   company hooks, paragraph plan) when no LLM is reachable and lets the host
   model write the letter. Ollama is the optional upgrade, not the gate.
4. `uvx --from 'pkg[extra]'` is unfamiliar — the exact JSON must be tested on
   a clean machine.
5. Python 3.13 wheel lag for spacy/torch — pin the `test-full` CI job to 3.12.

## 10. Repo history caveat

`Thomas_Pequegnot_Resume.pdf` is a real personal resume and it is **in git
history**. Removing it from `HEAD` does not remove it. Before this repo goes
public, either run `git filter-repo` or accept it. Tests never use it —
`tests/fixtures/` holds synthetic resumes only.
