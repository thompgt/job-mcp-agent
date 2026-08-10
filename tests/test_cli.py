"""The console entry point.

``doctor`` is the command a user runs when their MCP host says "server
failed", so it has to work with nothing installed and never raise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from careercraft import __version__
from careercraft.cli import main
from careercraft.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CAREERCRAFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CAREERCRAFT_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setenv("CAREERCRAFT_OLLAMA_BASE_URL", "disabled")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_doctor_reports_capabilities(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "keyword_matching" in out
    assert "default match strategy" in out


def test_doctor_names_the_command_for_each_missing_extra(capsys):
    main(["doctor"])
    out = capsys.readouterr().out
    for line in out.splitlines():
        if "[MISS]" in line:
            name = line.split("]")[1].split()[0]
            assert name in out.split("To enable the rest:")[-1], (
                f"{name} is reported missing with no install command"
            )


def test_info_prints_json_without_the_token(capsys, monkeypatch):
    monkeypatch.setenv("CAREERCRAFT_AUTH_TOKEN", "super-secret")
    get_settings.cache_clear()
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "auth_token" not in payload
    assert "super-secret" not in out
    assert payload["transport"] == "stdio"


def test_parse_prints_the_parsed_resume(capsys, tmp_path: Path, resume_text):
    path = tmp_path / "cv.txt"
    path.write_text(resume_text, encoding="utf-8")
    assert main(["parse", str(path), "--no-store"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "Jane Doe"
    assert "Python" in payload["skills"]


def test_parse_outside_the_allow_list_fails_with_a_message(capsys, tmp_path: Path, resume_text):
    outside = tmp_path.parent / "cli_outside.txt"
    outside.write_text(resume_text, encoding="utf-8")
    try:
        assert main(["parse", str(outside)]) == 2
        assert "error:" in capsys.readouterr().err
    finally:
        outside.unlink(missing_ok=True)


def test_parse_of_a_missing_file_fails_cleanly(capsys, tmp_path: Path):
    assert main(["parse", str(tmp_path / "nope.pdf")]) == 2
    assert "error:" in capsys.readouterr().err


def test_a_refused_bind_is_reported_not_traced(capsys, monkeypatch):
    """check_bind_safety must surface as a message, not a traceback."""
    monkeypatch.setenv("CAREERCRAFT_AUTH_TOKEN", "")
    get_settings.cache_clear()
    assert main(["serve", "--transport", "http", "--host", "0.0.0.0"]) == 2
    assert "auth token" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["api"], False), (["api", "--reload"], True)],
)
def test_reload_reaches_uvicorn(monkeypatch, argv, expected):
    """`--reload` was parsed and then dropped on the floor.

    The flag was advertised in `--help` and accepted without complaint, and
    nothing ever restarted — so a developer editing a route saw stale
    behaviour and no reason for it.
    """
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    uvicorn = pytest.importorskip("uvicorn")
    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert main(argv) == 0
    # An import string, not an app object: the reloader re-imports per change.
    assert captured["app"] == "careercraft.api.app:app"
    assert captured["reload"] is expected
