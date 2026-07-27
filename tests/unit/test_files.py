"""Path allow-listing and upload handling.

This is the security surface of the package, so the tests are written as
attacks rather than as happy paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from careercraft.adapters.files import chunked, resolve_allowed, save_upload, validate_suffix
from careercraft.errors import AccessDenied, ValidationFailed


# ------------------------------------------------------------ suffixes


@pytest.mark.parametrize("name", ["cv.pdf", "CV.PDF", "resume.docx", "notes.txt", "readme.md"])
def test_supported_suffixes_are_accepted(name):
    assert validate_suffix(name).startswith(".")


@pytest.mark.parametrize("name", ["payload.exe", "script.sh", "archive.zip", "noext", "", None])
def test_unsupported_suffixes_are_rejected(name):
    with pytest.raises(ValidationFailed):
        validate_suffix(name)


def test_only_the_suffix_survives_a_hostile_filename():
    """Directory components in the client filename must not reach the path."""
    assert validate_suffix("../../../../etc/passwd.pdf") == ".pdf"
    assert validate_suffix("C:\\Windows\\System32\\evil.txt") == ".txt"


def test_a_double_extension_takes_the_last_one():
    with pytest.raises(ValidationFailed):
        validate_suffix("resume.pdf.exe")


# ----------------------------------------------------- path resolution


def test_a_file_under_an_allowed_root_resolves(tmp_path: Path):
    target = tmp_path / "cv.txt"
    target.write_text("hello", encoding="utf-8")
    assert resolve_allowed(target, [tmp_path]) == target.resolve()


def test_a_file_outside_every_root_is_refused(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(AccessDenied):
        resolve_allowed(outside, [allowed])


def test_traversal_out_of_an_allowed_root_is_refused(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(AccessDenied):
        resolve_allowed(allowed / ".." / "secret.txt", [allowed])


def test_a_symlink_escaping_the_root_is_refused(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = allowed / "innocent.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need elevation on this platform")
    with pytest.raises(AccessDenied):
        resolve_allowed(link, [allowed])


def test_a_missing_path_fails_validation_not_access(tmp_path: Path):
    with pytest.raises(ValidationFailed):
        resolve_allowed(tmp_path / "nope.txt", [tmp_path])


def test_a_directory_is_not_a_file(tmp_path: Path):
    with pytest.raises(ValidationFailed):
        resolve_allowed(tmp_path, [tmp_path])


def test_local_paths_are_refused_entirely_over_http(tmp_path: Path):
    """Under HTTP the caller is not necessarily the user running the server."""
    target = tmp_path / "cv.txt"
    target.write_text("hello", encoding="utf-8")
    with pytest.raises(AccessDenied):
        resolve_allowed(target, [tmp_path], transport="http")


def test_the_error_names_the_setting_to_change(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(AccessDenied) as excinfo:
        resolve_allowed(outside, [allowed])
    assert "CAREERCRAFT_ALLOWED_PATHS" in str(excinfo.value)


# ------------------------------------------------------------- uploads


async def test_an_upload_lands_under_a_generated_name(tmp_path: Path):
    saved = await save_upload(
        chunked(b"resume body"),
        filename="../../evil.txt",
        upload_dir=tmp_path,
        max_bytes=1024,
    )
    assert saved.parent == tmp_path
    assert saved.suffix == ".txt"
    assert "evil" not in saved.name
    assert saved.read_bytes() == b"resume body"


async def test_an_oversized_upload_leaves_nothing_behind(tmp_path: Path):
    with pytest.raises(ValidationFailed):
        await save_upload(
            chunked(b"x" * 5000, size=100),
            filename="cv.txt",
            upload_dir=tmp_path,
            max_bytes=1000,
        )
    assert list(tmp_path.iterdir()) == []


async def test_an_empty_upload_is_rejected(tmp_path: Path):
    with pytest.raises(ValidationFailed):
        await save_upload(chunked(b""), filename="cv.txt", upload_dir=tmp_path, max_bytes=1024)
    assert list(tmp_path.iterdir()) == []


async def test_two_uploads_do_not_collide(tmp_path: Path):
    a = await save_upload(chunked(b"a"), filename="cv.txt", upload_dir=tmp_path, max_bytes=99)
    b = await save_upload(chunked(b"b"), filename="cv.txt", upload_dir=tmp_path, max_bytes=99)
    assert a != b
