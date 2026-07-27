# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-26

First release as a packaged MCP server. This is a rewrite; the tag
`v0-legacy` marks the last commit of the previous codebase.

### Added

- **MCP server** with seven tools (`search_jobs`, `get_job`, `parse_resume`,
  `list_resumes`, `match_jobs`, `generate_cover_letter`, `save_job`), seven
  resources and three prompts, over stdio or streamable HTTP.
- **`careercraft-mcp` / `careercraft` console scripts**, installable with
  `uvx` or `pipx`. `careercraft doctor` reports what an install can do and
  the exact command to enable what it cannot.
- **Letter briefs.** When no local model is reachable,
  `generate_cover_letter` returns grounded themes, evidence and a paragraph
  plan for the calling model to write from, instead of failing.
- **Missing-skills reporting.** Every match names the skills a posting asks
  for that the resume does not mention.
- **Optional extras** — `[pdf]`, `[nlp]`, `[ocr]`, `[embeddings]`, `[api]` —
  so the base install is ~75 MB rather than ~3 GB, with keyword matching as a
  genuine default rather than a degraded fallback.
- **HTTP API** and OpenAPI schema behind the `[api]` extra.
- **SQLite storage** in the platform data directory, WAL mode, schema
  versioned by `PRAGMA user_version`.
- Path allow-listing, streamed uploads with the size cap enforced as bytes
  arrive, and a bind-safety guard that refuses to expose an unauthenticated
  server on a routable interface.
- 211 tests, including one that spawns the real console script and asserts
  every byte on stdout is a JSON-RPC frame.

### Changed

- **Job ids are content-addressed on title, company and URL** rather than on
  the whole payload. Previously any upstream edit — a reformatted
  description, a changed view counter — minted a new id and the same posting
  reappeared as a duplicate.
- **Providers raise instead of returning `[]`.** A failed fetch and an empty
  result set are now distinguishable, so a model can no longer report "no such
  roles exist" when the job board was simply down.
- **Failed tools raise `ToolError`** carrying the remedy, instead of returning
  `{"status": "error"}` inside a success frame that reads to the calling model
  as a result.
- **Matching thresholds are comparable across strategies.** The keyword path
  now produces a TF-IDF cosine blended with skill coverage, so `min_score`
  means the same thing whichever strategy runs.
- One HTTP client per provider for the process lifetime, rather than one per
  call — constructing an `AsyncClient` loads a TLS trust store, roughly 0.8s
  per search on Windows.

### Removed

- MongoDB, replaced by SQLite. The one collection in use was
  `{source_hash, payload}`.
- LangChain, replaced by direct calls to the Ollama HTTP API — ~120 MB of
  dependencies for one `invoke()` against a single JSON endpoint.
- The duplicate implementations: two MCP servers, three FastAPI apps and two
  UIs, which had already drifted into disagreeing with each other.
