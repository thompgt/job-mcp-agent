# CareerCraft

An MCP server that turns your resume into targeted job applications — parsing,
matching and cover letters, running entirely on your machine.

Point Claude Desktop, Claude Code or Cursor at it and ask:

> Read my resume at ~/Documents/cv.pdf, find remote data roles I'd actually be
> competitive for, and tell me what I'm missing for the best one.

Nothing leaves your computer except the job-board search itself. There is no
API key, no account, and no telemetry.

[![CI](https://github.com/tpequegnot/careercraft-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/tpequegnot/careercraft-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/careercraft-mcp.svg)](https://pypi.org/project/careercraft-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/careercraft-mcp.svg)](https://pypi.org/project/careercraft-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastMCP](https://img.shields.io/badge/FastMCP-4A26C4?style=for-the-badge)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

---

## Install

### Claude Desktop

Add this to `claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "careercraft": {
      "command": "uvx",
      "args": ["careercraft-mcp"]
    }
  }
}
```

The config file lives at:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

To read PDF resumes — which you probably want — use the `[pdf]` extra:

```json
{
  "mcpServers": {
    "careercraft": {
      "command": "uvx",
      "args": ["--from", "careercraft-mcp[pdf]", "careercraft-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add careercraft -- uvx --from 'careercraft-mcp[pdf]' careercraft-mcp
```

### Cursor

Add the same `mcpServers` block to `~/.cursor/mcp.json`.

### Without an MCP host

```bash
uv tool install 'careercraft-mcp[pdf]'
careercraft doctor              # what this install can do
careercraft parse ~/cv.pdf      # parse a resume, print JSON
careercraft api                 # the HTTP API, http://127.0.0.1:8000/docs
```

---

## What it does

Seven tools, and the usual path through them is three:

| Tool | What it does |
|---|---|
| `parse_resume` | Extracts skills, roles, education and contacts from a PDF, Word or text resume. |
| `match_jobs` | Ranks postings against a resume, with per-job reasons and a *missing skills* list. |
| `generate_cover_letter` | Drafts a letter grounded in both documents. |
| `search_jobs` | Fetches remote postings. `match_jobs` will do this itself if you pass a query. |
| `get_job` | One posting in full. |
| `list_resumes` | Everything parsed so far. |
| `save_job` | Bookmarks a posting so it survives cache expiry. |

Plus resources the model can read directly — `careercraft://capabilities`,
`careercraft://resume/{id}`, `careercraft://jobs/recent` — and three prompts
(`job_search_workflow`, `tailor_cover_letter`, `resume_feedback`) that your
host will surface as slash commands.

### Matching that explains itself

Every match reports which of your skills the posting asks for **and which it
asks for that your resume never mentions**. The second list is the useful one:
it is the gap between you and the role, in the posting's own vocabulary.

```
0.68  Data Engineer at Northwind
      Shares 5 skills: Python, SQL, Airflow, AWS, ETL.
      Posting also asks for: dbt, Snowflake, Spark.
```

Postings whose seniority or degree requirement you cannot meet are filtered
out before ranking, so a new graduate does not get a list topped by Principal
Engineer roles. Pass `filter_seniority=false` to see everything.

### Cover letters without a local model

If you have [Ollama](https://ollama.com) running, letters are written by your
local model. If you do not, `generate_cover_letter` returns a **brief**
instead of prose: the themes, the evidence drawn from your resume, the
specific hooks from the posting, and a paragraph plan.

Your MCP host then writes the letter from that brief — which is usually the
*better* outcome, since the model reading it is considerably stronger than a
local 1B model. Nothing needs installing for this path to work.

---

## Install size, and what is optional

The base install is small on purpose, so `uvx careercraft-mcp` starts in
seconds rather than downloading a machine-learning stack. Every heavy
dependency is an extra, and the server reports honestly what it can do.

| Install | Size | Adds |
|---|---|---|
| `careercraft-mcp` | ~75 MB | Text resumes, keyword matching, letter briefs, templates |
| `[pdf]` | +30 MB | PDF and Word resumes, layout-aware section detection |
| `[nlp]` | +200 MB | spaCy NER, for names not on the first lines |
| `[ocr]` | +20 MB | Scanned PDFs (also needs the `tesseract` binary) |
| `[embeddings]` | **+2.5 GB** | Semantic matching instead of keyword matching |
| `[api]` | +15 MB | The HTTP API behind the web UI |
| `[all]` | ~2.8 GB | Everything |

Keyword matching is the default, not a fallback: it is TF-IDF cosine
similarity blended with skill coverage, and on job postings — which are short,
keyword-dense documents — it holds up well for a fraction of the footprint.
Install `[embeddings]` if you want semantic matching; you do not need it to
get useful results.

Run `careercraft doctor` to see what your install supports and the exact
command to enable the rest.

---

## Configuration

Everything is an environment variable, which is how MCP hosts configure
servers:

```json
{
  "mcpServers": {
    "careercraft": {
      "command": "uvx",
      "args": ["--from", "careercraft-mcp[pdf]", "careercraft-mcp"],
      "env": {
        "CAREERCRAFT_ALLOWED_PATHS": "/Users/you/Documents",
        "CAREERCRAFT_OLLAMA_MODEL": "llama3.2:3b"
      }
    }
  }
}
```

| Variable | Default | Meaning |
|---|---|---|
| `CAREERCRAFT_DATA_DIR` | platform data dir | Where the SQLite database and uploads live |
| `CAREERCRAFT_ALLOWED_PATHS` | `~` | Roots `parse_resume(path=…)` may read from |
| `CAREERCRAFT_MAX_UPLOAD_BYTES` | `10485760` | Upload size cap |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Set to `disabled` to turn generation off |
| `CAREERCRAFT_OLLAMA_MODEL` | `llama3.2:1b` | Any model you have pulled |
| `CAREERCRAFT_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Used only with `[embeddings]` |
| `CAREERCRAFT_TRANSPORT` | `stdio` | `stdio` or `http` |
| `CAREERCRAFT_HOST` / `CAREERCRAFT_PORT` | `127.0.0.1` / `8000` | HTTP bind |
| `CAREERCRAFT_AUTH_TOKEN` | *(none)* | Required to bind anything but loopback |
| `CAREERCRAFT_LOG_LEVEL` | `INFO` | |

`careercraft info` prints the resolved configuration.

---

## Privacy and safety

- **Your resume stays local.** It is parsed on your machine and stored in a
  local SQLite file. The only outbound request is the job-board search, which
  sends your query string and nothing else.
- **Paths are allow-listed.** `parse_resume(path=…)` resolves symlinks and then
  checks containment, so a path outside `CAREERCRAFT_ALLOWED_PATHS` is refused
  rather than read.
- **Local paths are refused entirely over HTTP.** Under `--transport http` the
  caller is not necessarily you, so `path=` is rejected outright; upload
  instead.
- **The server refuses to expose itself unsafely.** Binding to anything but
  loopback without `CAREERCRAFT_AUTH_TOKEN` is an error, not a warning.
- **Delete everything** by removing the data directory `careercraft info`
  reports.

---

## Docker

```bash
docker compose up
```

Brings up the API on `http://127.0.0.1:8000` and the web UI on
`http://127.0.0.1:3000`, both on loopback. The compose file already points
`OLLAMA_BASE_URL` at `host.docker.internal` so a host-side Ollama is reachable
from the container.

---

## Development

```bash
git clone https://github.com/tpequegnot/careercraft-mcp
cd careercraft-mcp
uv venv && uv pip install -e '.[all,dev]'
pre-commit install

pytest
ruff check src tests
mypy
```

The layering is enforced by the linter, not by convention:
`careercraft.core` may not import `fastmcp`, `fastapi` or `sqlite3`, so the
domain logic stays testable and reusable without any of them.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the rest, and
[docs/MIGRATION-PLAN.md](docs/MIGRATION-PLAN.md) for why the architecture is
shaped the way it is.

---

## License

MIT. See [LICENSE](LICENSE).
