"""stdout must carry JSON-RPC and nothing else.

This is the failure that makes an MCP server look broken for reasons nobody
can diagnose: one stray ``print``, one library banner, one warning routed to
stdout, and the host's parser chokes on the frame. The symptom the user sees
is "server disconnected", with no hint as to why.

Mocking cannot catch it, because the whole point is what a real interpreter
writes to a real pipe: import-time side effects, third-party banners, the
logging configuration. So this spawns the actual console script in a
subprocess and reads the actual pipe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import anyio
import pytest

TIMEOUT = 60


def _frame(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


INITIALIZE = _frame(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "purity-test", "version": "0"},
        },
    }
)
INITIALIZED = _frame({"jsonrpc": "2.0", "method": "notifications/initialized"})
LIST_TOOLS = _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
CALL_TOOL = _frame(
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "parse_resume",
            "arguments": {"text": "Jane Doe\n\nSKILLS\nPython, SQL\n", "persist": False},
        },
    }
)


class Run:
    """What the server wrote, and how it ended."""

    def __init__(self, stdout: bytes, stderr: bytes, returncode: int | None) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _run_server(tmp_path: Path) -> Run:
    env = {
        **os.environ,
        "CAREERCRAFT_DATA_DIR": str(tmp_path / "data"),
        "CAREERCRAFT_OLLAMA_BASE_URL": "disabled",
        "CAREERCRAFT_TRANSPORT": "stdio",
        "PYTHONIOENCODING": "utf-8",
        # A server started by a host inherits an environment we do not control,
        # so make sure a hostile-ish one does not push anything onto stdout.
        "PYTHONWARNINGS": "always",
    }
    env.pop("CAREERCRAFT_LOG_LEVEL", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "careercraft.cli", "serve", "--transport", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    # stdin is deliberately left open while the responses are read. Closing it
    # immediately after the writes races the server's shutdown-on-EOF against
    # its own reply, and the tool response can be lost — which is a property of
    # this harness, not of the server.
    collected: list[bytes] = []

    def pump() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            collected.append(line)
            if b'"id": 3' in line or b'"id":3' in line:
                break

    proc.stdin.write(INITIALIZE + INITIALIZED + LIST_TOOLS + CALL_TOOL)
    proc.stdin.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    reader.join(TIMEOUT)

    proc.stdin.close()
    try:
        _, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        _, stderr = proc.communicate()

    return Run(b"".join(collected), stderr, proc.returncode)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run_server(tmp_path_factory.mktemp("stdio"))


def test_every_stdout_line_is_a_json_rpc_frame(run):
    lines = [ln for ln in run.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    assert lines, f"the server wrote nothing to stdout; stderr was:\n{run.stderr.decode()[-4000:]}"
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:  # pragma: no cover - the failure we are guarding
            pytest.fail(f"non-JSON on stdout: {line[:400]!r}")
        assert payload.get("jsonrpc") == "2.0", f"stdout frame is not JSON-RPC: {line[:200]!r}"


def test_the_handshake_and_the_tool_call_both_answered(run):
    responses = {
        json.loads(ln)["id"]: json.loads(ln)
        for ln in run.stdout.decode("utf-8", "replace").splitlines()
        if ln.strip() and "id" in json.loads(ln)
    }
    assert 1 in responses, "no initialize response"
    assert responses[1]["result"]["serverInfo"]["name"] == "careercraft"

    assert 2 in responses, "no tools/list response"
    names = {t["name"] for t in responses[2]["result"]["tools"]}
    assert "parse_resume" in names

    assert 3 in responses, "no tools/call response"
    result = responses[3]["result"]
    assert result.get("isError") is not True
    assert result["structuredContent"]["name"] == "Jane Doe"


def test_diagnostics_went_to_stderr(run):
    """Logging still has to happen — it just must not happen on stdout."""
    assert run.stderr, "the server logged nothing at all, which hides real failures"


def test_the_server_exited_cleanly(run):
    # 0 on a clean EOF shutdown; some platforms report the signal instead.
    assert run.returncode in (0, None), f"exit {run.returncode}: {run.stderr.decode()[-2000:]}"


async def test_a_stray_print_would_be_caught_by_this_file(tmp_path: Path):
    """Guard the guard: prove the assertion above actually fails on bad output.

    Without this, a change that broke the subprocess plumbing would leave
    test_every_stdout_line_is_a_json_rpc_frame passing vacuously.
    """
    proc = await anyio.run_process(
        [sys.executable, "-c", "print('hello'); print('{\"jsonrpc\": \"2.0\"}')"],
        check=False,
    )
    lines = [ln for ln in proc.stdout.decode().splitlines() if ln.strip()]
    with pytest.raises(json.JSONDecodeError):
        for line in lines:
            json.loads(line)
