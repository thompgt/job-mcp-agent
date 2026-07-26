"""Render the CareerCraft architecture diagram to docs/assets/architecture.png.

Pure matplotlib so it works without a Graphviz `dot` binary on PATH.

Usage:
    python scripts/make_architecture_diagram.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "architecture.png"

# ---------------------------------------------------------------- palette
INK = "#1c2434"
MUTED = "#596375"
EDGE = "#94a0b2"

BAND = "#f3f5f9"
BAND_EDGE = "#e2e6ee"

FILL = {
    "client": "#e6eefc",
    "web": "#dae8f7",
    "agent": "#e7e2f8",
    "mcp": "#d8ece9",
    "svc": "#fbeade",
    "ext": "#ebedf2",
}
STROKE = {
    "client": "#4c7bd9",
    "web": "#3f7fb5",
    "agent": "#7a63c4",
    "mcp": "#3f9c8a",
    "svc": "#d08a4a",
    "ext": "#96a0af",
}

# horizontal content area (x < GUTTER is reserved for rotated band labels)
GUTTER = 15.0
CORRIDOR_X = 12.4   # clear vertical lane between band labels and the boxes

fig, ax = plt.subplots(figsize=(16.0, 11.5), dpi=170)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")
fig.patch.set_facecolor("white")

boxes: dict[str, tuple[float, float, float, float]] = {}


def band(y, h, label):
    ax.add_patch(
        FancyBboxPatch(
            (1.5, y), 97.0, h,
            boxstyle="round,pad=0,rounding_size=1.0",
            facecolor=BAND, edgecolor=BAND_EDGE, linewidth=1.0, zorder=0,
        )
    )
    ax.text(
        5.0, y + h / 2, label,
        fontsize=9.2, color=MUTED, fontweight="bold",
        ha="center", va="center", rotation=90, zorder=1,
    )


def box(key, x, y, w, h, title, subtitle="", kind="svc", dashed=False, fs=11.0):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0,rounding_size=0.8",
            facecolor=FILL[kind], edgecolor=STROKE[kind],
            linewidth=1.6, linestyle="--" if dashed else "-", zorder=2,
        )
    )
    cx = x + w / 2
    if subtitle:
        ax.text(cx, y + h * 0.70, title, fontsize=fs, fontweight="bold",
                color=INK, ha="center", va="center", zorder=3)
        ax.text(cx, y + h * 0.32, subtitle, fontsize=8.2, color=MUTED,
                ha="center", va="center", zorder=3, linespacing=1.45)
    else:
        ax.text(cx, y + h / 2, title, fontsize=fs, fontweight="bold",
                color=INK, ha="center", va="center", zorder=3)
    boxes[key] = (x, y, w, h)


def anchor(key, side, t=0.5):
    x, y, w, h = boxes[key]
    return {
        "t": (x + w * t, y + h),
        "b": (x + w * t, y),
        "l": (x, y + h * t),
        "r": (x + w, y + h * t),
    }[side]


def arrow(src, ssid, dst, dsid, label="", dashed=False, rad=0.0,
          sa=0.5, da=0.5, lx=0.0, ly=0.0, fs=8.2):
    p0 = anchor(src, ssid, sa)
    p1 = anchor(dst, dsid, da)
    ax.add_patch(
        FancyArrowPatch(
            p0, p1, arrowstyle="-|>", mutation_scale=12,
            linewidth=1.4, color=EDGE,
            linestyle="--" if dashed else "-",
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=2, shrinkB=3, zorder=1,
        )
    )
    if label:
        ax.text((p0[0] + p1[0]) / 2 + lx, (p0[1] + p1[1]) / 2 + ly, label,
                fontsize=fs, color=MUTED, ha="center", va="center", zorder=4,
                bbox=dict(boxstyle="round,pad=0.24", fc="white", ec="none",
                          alpha=0.95))


# ---------------------------------------------------------------- title
ax.text(1.5, 99.0, "CareerCraft — Job Application MCP Agent",
        fontsize=18.5, fontweight="bold", color=INK, ha="left", va="top")
ax.text(1.5, 95.8,
        "Resume in  →  semantic job match  →  LLM cover letter out.   "
        "Every capability is reached through an MCP tool boundary.",
        fontsize=10.2, color=MUTED, ha="left", va="top")

# ---------------------------------------------------------------- bands
band(81.5, 10.5, "CLIENT")
band(66.5, 13.0, "WEB / API")
band(52.5, 12.0, "AGENT")
band(35.5, 15.0, "MCP SERVERS")
band(18.5, 15.0, "SERVICES")
band(3.5, 13.0, "EXTERNAL")

# ---------------------------------------------------------------- client
box("browser", GUTTER + 0.5, 83.4, 41, 6.8,
    "Browser UI  ·  HTML + WebSocket",
    "rendered inline by web_frontend.py  ·  live progress over ws://:8000/ws/{session_id}",
    kind="client")
box("static", 57, 83.4, 40, 6.8,
    "frontend/index.html   (alternate UI)",
    "static page against the REST API on :8000",
    kind="client", dashed=True)

# ---------------------------------------------------------------- web tier
box("webfe", GUTTER + 0.5, 68.0, 24.5, 10.0,
    "web_frontend.py   :8000",
    "FastAPI + WebSocket\nupload-resume · status\nmatch-jobs · generate-cover-letter",
    kind="web")
box("apife", 41, 68.0, 29, 10.0,
    "server/api_frontend.py   :8000",
    "FastAPI REST (alt entrypoint)\njobs/fetch · resume/parse · pipeline/run\ncover-letter/generate · cover-letter/eval",
    kind="web", dashed=True)
box("appapi", 72.5, 68.0, 24.5, 10.0,
    "server/app/main.py   /api",
    "queue dev API\ningest · jobs\nclaim · complete",
    kind="web", dashed=True)

# ---------------------------------------------------------------- agent
box("agent", GUTTER + 0.5, 54.0, 43, 9.2,
    "agent.py  ·  JobApplicationAgent",
    "plans the run, adapts search parameters, explains matches\n"
    "reasons with Ollama, calls tools through fastmcp.Client",
    kind="agent")
box("ctrl", 60, 54.0, 37, 9.2,
    "MCPController",
    "singleton over the job queue\nMongo → Redis → in-memory fallback",
    kind="web", dashed=True)

# ---------------------------------------------------------------- mcp
box("pipeline", GUTTER + 0.5, 37.2, 39.5, 11.6,
    "server/mcp_pipeline_server.py   :8002/mcp",
    "run_complete_pipeline · parse_resume · create_cover_letter\n"
    "match_jobs_to_resume · match_jobs_from_resume_path\n"
    "fetch_job_data · populate_mongodb",
    kind="mcp")
box("queuemcp", 56, 37.2, 41, 11.6,
    "server/fastmcp_server.py   :8001/mcp",
    "ingest · list_jobs · claim · complete\n"
    "fetch_data · parse_resume · populate_database\n"
    "generate_cover_letter_tool",
    kind="mcp", dashed=True)

# ---------------------------------------------------------------- services
SY, SH = 20.2, 11.6
box("parser", GUTTER + 0.5, SY, 18.5, SH,
    "resume_parser.py",
    "PDF / DOCX / TXT →\nstructured dict\nPyMuPDF layout sections,\nOCR fallback, spaCy skills",
    kind="svc", fs=10.2)
box("match", 36.5, SY, 18.5, SH,
    "matching_engine.py",
    "rank_jobs_for_resume()\nMiniLM embeddings +\ncosine similarity, seniority\n& degree pre-filters",
    kind="svc", fs=10.2)
box("cover", 57.5, SY, 18.5, SH,
    "cover_letter_generator.py",
    "generate_cover_letter()\nLangChain ChatOllama\nprompt with tone ×\nlength controls",
    kind="svc", fs=10.2)
box("data", 78.5, SY, 18.5, SH,
    "get_data.py · queue.py",
    "pluggable job providers\n(Jobicy, Mock) and the\nclaim/complete work queue",
    kind="svc", fs=10.2)

# ---------------------------------------------------------------- external
EY, EH = 5.2, 8.4
box("models", GUTTER + 0.5, EY, 25.5, EH,
    "spaCy  ·  sentence-transformers",
    "en_core_web_sm  ·  all-MiniLM-L6-v2",
    kind="ext", fs=10.2)
box("ollama", 44.5, EY, 27.0, EH,
    "Ollama   (local LLM)",
    "llama3.2:1b by default\nruns on localhost — no cloud API key",
    kind="ext", fs=10.2)
box("mongo", 74.0, EY, 11.0, EH,
    "MongoDB", "jobs, sessions\nSHA-256 dedupe", kind="ext", fs=10.2)
box("jobicy", 86.5, EY, 10.5, EH,
    "Jobicy API", "remote job\nfeed", kind="ext", fs=10.2)

# ---------------------------------------------------------------- edges
arrow("browser", "b", "webfe", "t", "HTTP + WebSocket", sa=0.35, da=0.55, lx=-7.5)
arrow("static", "b", "apife", "t", "REST", dashed=True, sa=0.4, da=0.6, rad=-0.08)

arrow("webfe", "b", "agent", "t", "invokes the agent", sa=0.5, da=0.28, lx=-8.0)
arrow("apife", "b", "pipeline", "t", "direct service calls",
      dashed=True, sa=0.35, da=0.80, rad=0.10, lx=9.5, ly=-1.2)
arrow("appapi", "b", "ctrl", "t", dashed=True, sa=0.5, da=0.75)

arrow("agent", "b", "pipeline", "t", "MCP tool calls  (fastmcp.Client → HTTP)",
      sa=0.42, da=0.42, ly=0.4)
# agent -> Ollama (reasoning prompts). Routed orthogonally through the corridor
# between the SERVICES and EXTERNAL bands so it does not cross any box.
_ax0, _ay0 = anchor("agent", "l", 0.35)
_corridor_y = 17.4
_ollama_x = anchor("ollama", "t", 0.12)[0]
ax.plot([_ax0, CORRIDOR_X], [_ay0, _ay0], color=EDGE, lw=1.4, ls="--", zorder=1)
ax.plot([CORRIDOR_X, CORRIDOR_X], [_ay0, _corridor_y], color=EDGE, lw=1.4,
        ls="--", zorder=1)
ax.plot([CORRIDOR_X, _ollama_x], [_corridor_y, _corridor_y], color=EDGE, lw=1.4,
        ls="--", zorder=1)
ax.add_patch(
    FancyArrowPatch(
        (_ollama_x, _corridor_y), anchor("ollama", "t", 0.12),
        arrowstyle="-|>", mutation_scale=12, linewidth=1.4, color=EDGE,
        linestyle="--", shrinkA=0, shrinkB=3, zorder=1,
    )
)
ax.text((CORRIDOR_X + _ollama_x) / 2, _corridor_y + 0.05, "agent reasoning prompts",
        fontsize=8.2, color=MUTED, ha="center", va="center", zorder=4,
        bbox=dict(boxstyle="round,pad=0.24", fc="white", ec="none", alpha=0.95))

arrow("ctrl", "b", "queuemcp", "t", dashed=True, sa=0.5, da=0.6)

arrow("pipeline", "b", "parser", "t", sa=0.18, da=0.5)
arrow("pipeline", "b", "match", "t", sa=0.50, da=0.4)
arrow("pipeline", "b", "cover", "t", sa=0.78, da=0.35)
arrow("pipeline", "b", "data", "t", dashed=True, sa=0.95, da=0.25, rad=-0.06)
arrow("queuemcp", "b", "data", "t", dashed=True, sa=0.75, da=0.7)
arrow("queuemcp", "b", "cover", "t", dashed=True, sa=0.20, da=0.75, rad=0.06)

arrow("parser", "b", "models", "t", sa=0.5, da=0.28)
arrow("match", "b", "models", "t", sa=0.4, da=0.72, rad=-0.06)
arrow("cover", "b", "ollama", "t", "ChatOllama", sa=0.5, da=0.6, lx=5.0)
arrow("data", "b", "mongo", "t", sa=0.35, da=0.5, rad=0.06)
arrow("data", "b", "jobicy", "t", sa=0.75, da=0.5, rad=-0.06)

ax.text(1.5, 1.6,
        "solid = primary path exercised by notebooks/demo.ipynb and docker compose        "
        "dashed = alternate or secondary entrypoint",
        fontsize=8.4, color=MUTED, ha="left", va="bottom", style="italic")

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, bbox_inches="tight", facecolor="white", pad_inches=0.22)
print(f"wrote {OUT}")
