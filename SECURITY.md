# Security

## Reporting a vulnerability

Please report security issues through GitHub's private
[security advisory](https://github.com/thompgt/job-mcp-agent/security/advisories/new)
form rather than a public issue. Expect an acknowledgement within a week.

## Threat model

CareerCraft handles resumes — full name, contact details, employment history —
and can read files from disk on request. The design assumes that is worth
protecting.

**Where the data goes.** Resumes are parsed locally and stored in a local
SQLite database. The only outbound request the base install makes is the job
board search, which carries the query string and nothing else. With Ollama
configured, resume and posting text are sent to that daemon, which is
loopback by default. There is no telemetry and no analytics.

**Reading local paths.** `parse_resume(path=…)` is the one tool that touches
arbitrary files. Paths are expanded, resolved through symlinks, and then
checked for containment under `CAREERCRAFT_ALLOWED_PATHS` (default: the
user's home directory). Resolution happens before the containment check, so
a symlink pointing outside an allowed root is refused rather than followed.

Under HTTP transport `path=` is refused outright. Over stdio the server runs
as the user and reads what the user could read anyway; over HTTP the caller
is not necessarily the user, and a tool that reads server-side paths on
request is a file-disclosure primitive.

**Uploads.** The client-supplied filename is discarded rather than sanitised —
only a validated extension survives, and the file lands under a generated
name. Bodies are streamed with the size cap enforced as bytes arrive, and a
body that exceeds it leaves nothing on disk.

**Network exposure.** The server binds loopback by default and refuses to
bind anything else without `CAREERCRAFT_AUTH_TOKEN`. A wildcard CORS origin
alongside a token is also refused, since that hands the token to any page the
browser visits. `CAREERCRAFT_ALLOW_UNAUTHENTICATED_BIND=1` exists for
container networks where the port is not otherwise reachable; it logs a
warning every time it is used.

## What is out of scope

- **Prompt injection through job postings.** Postings are third-party text
  that reaches your model, and stripping HTML removes tags, not instructions.
  CareerCraft now fences posting text between
  `-----BEGIN/END UNTRUSTED JOB POSTING-----` markers, defangs any copy of
  those markers found inside the posting so it cannot close its own fence,
  and tells both the cover-letter model and the MCP host that the fenced span
  is data. That is defence in depth, not a guarantee — no delimiter scheme
  makes a language model immune. Treat generated letters as drafts and read
  them.
- **Ollama itself.** If you point `OLLAMA_BASE_URL` at a remote daemon, your
  resume text goes to that host. That is your decision to make; the default
  is loopback.
- **The accuracy of matching.** A low score is not a judgement and a high one
  is not an endorsement.

## Supported versions

The latest minor release receives security fixes.
