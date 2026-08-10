"""Settings parsing and the bind-safety guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from careercraft.errors import ValidationFailed
from careercraft.settings import Settings, get_settings


def test_defaults_are_loopback_and_stdio():
    s = Settings()
    assert s.transport == "stdio"
    assert s.host in {"127.0.0.1", "localhost"}


def test_derived_paths_live_under_the_data_dir(tmp_path: Path):
    s = Settings(data_dir=tmp_path)
    assert s.db_path.parent == tmp_path
    assert s.upload_dir.parent == tmp_path


def test_ensure_dirs_creates_them(tmp_path: Path):
    s = Settings(data_dir=tmp_path / "nested" / "deeper")
    s.ensure_dirs()
    assert s.data_dir.is_dir()
    assert s.upload_dir.is_dir()


def test_allowed_paths_accepts_a_comma_separated_string(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CAREERCRAFT_ALLOWED_PATHS", f"{tmp_path},{tmp_path / 'other'}")
    assert len(Settings().allowed_paths) == 2


def test_allowed_paths_accepts_json(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CAREERCRAFT_ALLOWED_PATHS", f'["{tmp_path.as_posix()}"]')
    assert len(Settings().allowed_paths) == 1


def test_tildes_are_expanded():
    s = Settings(allowed_paths=[Path("~/Documents")])
    assert "~" not in str(s.allowed_paths[0])


def test_the_ollama_url_reads_a_bare_env_var(monkeypatch):
    """OLLAMA_BASE_URL is the name the ecosystem already uses."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434")
    assert Settings().ollama_base_url == "http://gpu-box:11434"


def test_the_prefixed_env_var_works_too(monkeypatch):
    monkeypatch.setenv("CAREERCRAFT_OLLAMA_MODEL", "qwen2.5:3b")
    assert Settings().ollama_model == "qwen2.5:3b"


def test_unknown_env_vars_are_ignored(monkeypatch):
    monkeypatch.setenv("CAREERCRAFT_NOT_A_REAL_SETTING", "x")
    Settings()  # must not raise


# ------------------------------------------------------- bind safety


def test_loopback_needs_no_token():
    Settings(transport="http", host="127.0.0.1").check_bind_safety()


def test_a_public_bind_without_a_token_is_refused():
    with pytest.raises(ValidationFailed) as excinfo:
        Settings(transport="http", host="0.0.0.0").check_bind_safety()
    assert "CAREERCRAFT_AUTH_TOKEN" in str(excinfo.value)


def test_a_public_bind_with_a_token_is_allowed():
    Settings(transport="http", host="0.0.0.0", auth_token="s3cret").check_bind_safety()


def test_the_container_opt_out_permits_an_unauthenticated_bind():
    """A container must bind 0.0.0.0 to receive published traffic at all."""
    Settings(transport="http", host="0.0.0.0", allow_unauthenticated_bind=True).check_bind_safety()


def test_the_opt_out_is_off_by_default():
    assert Settings().allow_unauthenticated_bind is False


def test_the_refusal_names_the_opt_out():
    with pytest.raises(ValidationFailed) as excinfo:
        Settings(transport="http", host="0.0.0.0").check_bind_safety()
    assert "CAREERCRAFT_ALLOW_UNAUTHENTICATED_BIND" in str(excinfo.value)


def test_wildcard_cors_alongside_a_token_is_refused():
    """A wildcard origin hands the token to any page the browser visits."""
    with pytest.raises(ValidationFailed):
        Settings(
            transport="http",
            host="127.0.0.1",
            auth_token="s3cret",
            cors_origins=["*"],
        ).check_bind_safety()


def test_stdio_skips_the_check_entirely():
    Settings(transport="stdio", host="0.0.0.0").check_bind_safety()


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
