# Contributing

## Setup

```bash
uv venv
uv pip install -e '.[all,dev]'
pre-commit install
```

`[all]` pulls sentence-transformers and therefore torch — about 2.5 GB. If
you are not touching the embedding path, `-e '.[pdf,api,dev]'` is enough; the
tests that need the heavy extras are marked and skip themselves.

## Checks

```bash
pytest
ruff check src tests
ruff format src tests
mypy
```

CI runs all four on Linux, macOS and Windows across Python 3.10 and 3.13,
plus one job on the **base install with no extras at all** — that one exists
because the optional-dependency design is only real if it is tested.

## Architecture

```
src/careercraft/
  core/            domain logic — no transport, no storage, no frameworks
    resume/        extraction, parsing, skill vocabulary
    matching/      seniority filters, keyword and embedding scorers
    jobs/          job board providers
    letters/       prompts, briefs, templates
  adapters/        SQLite, filesystem, Ollama
  mcp/             the MCP server
  api/             the HTTP API
  service.py       one object that owns everything and implements every operation
```

The layering is enforced by ruff, not by convention: `core/` may not import
`fastmcp`, `fastapi` or `sqlite3`, and a stray import is a lint failure. The
point is that domain logic stays testable without any of them, and that the
two transports cannot drift apart — v1 implemented the pipeline once in the
MCP server and again in the API, and by the end they gave different answers.

**Both transports are shells over `CareerCraftService`.** If you find yourself
adding logic to a route handler or a tool function, it belongs in the service.

## Adding an optional dependency

Heavy dependencies are the thing this project is most careful about; `uvx
careercraft-mcp` has to start in seconds.

1. Add an extra in `pyproject.toml`. Never a hard dependency.
2. Gate the import behind `importlib.util.find_spec`, and import it inside
   the function that needs it, not at module scope.
3. Raise `DependencyMissing(feature, extra)` when it is absent — it builds the
   install command for you.
4. Add an entry to `careercraft.capabilities.collect` so `careercraft doctor`
   and the `careercraft://capabilities` resource stay honest.
5. Make sure the base-install CI job still passes.

## Tests

- **Never commit a real resume.** `tests/fixtures/` holds synthetic ones, and
  a pre-commit hook refuses any PDF or Word document outside that directory.
- MCP behaviour is tested through `fastmcp.Client(server)` — the in-memory
  transport speaks the real protocol, so the tests assert the wire contract
  rather than Python function calls.
- HTTP integrations are mocked with `respx`. No test touches the network.
- `tests/mcp/test_stdio_purity.py` spawns the real console script. If you
  change anything about logging, imports or startup, run it.

## Errors

Every error raised deliberately carries a `remedy`: a sentence naming the
command or setting that fixes it. The model reading a failed tool result is
usually the one who has to act on it, and "an error occurred" gives it nothing
to work with.

Failed tools raise `ToolError`. They never return an error-shaped success.

## Commits

Conventional Commits. Explain *why* in the body — the diff already covers
what.
