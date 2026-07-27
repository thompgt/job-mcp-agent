"""Resume parsing against a known-good synthetic document.

These are the closest thing this project has to golden tests. The fixture is
synthetic on purpose: the repository once carried a real resume, and a parser
test suite is exactly the place that habit creeps back in.
"""

from __future__ import annotations

import pytest

from careercraft.core.resume.parse import parse_resume_text, split_sections


@pytest.fixture
def parsed(resume_text: str):
    return parse_resume_text(resume_text, source_name="synthetic_resume.txt")


def test_finds_the_candidate_name(parsed):
    assert parsed.name == "Jane Doe"


def test_finds_contacts(parsed):
    assert parsed.contacts.email == "jane.doe@example.com"
    assert parsed.contacts.phone is not None
    assert "janedoe" in (parsed.contacts.github or "")
    assert "janedoe" in (parsed.contacts.linkedin or "")


def test_finds_the_expected_skills(parsed):
    expected = {"Python", "SQL", "pandas", "scikit-learn", "PyTorch", "Docker", "AWS", "Tableau"}
    assert expected <= set(parsed.skills)


def test_detects_every_section(parsed):
    assert {"education", "skills", "experience", "projects"} <= set(parsed.sections_detected)


def test_extracts_both_roles(parsed):
    orgs = {e.organization for e in parsed.experience}
    assert "Acme Analytics" in orgs
    assert "Northwind Labs" in orgs


def test_bullets_are_not_mistaken_for_employers(parsed):
    """A sentence starting with a capital verb is a highlight, not a company."""
    orgs = {e.organization for e in parsed.experience}
    assert not any(o.startswith("Built") or o.startswith("Automated") for o in orgs)
    highlights = [h for e in parsed.experience for h in e.highlights]
    assert any("ETL pipelines" in h for h in highlights)


def test_extracts_projects(parsed):
    names = {p.name for p in parsed.projects}
    assert "Transit Delay Forecaster" in names


def test_education_captures_the_degree(parsed):
    assert parsed.education
    assert any("B.S." in e.text or e.degree for e in parsed.education)


def test_backend_is_regex_without_spacy(parsed):
    assert parsed.backend in {"regex", "spacy", "spacy+layout", "layout"}


def test_raw_length_and_search_text(parsed, resume_text):
    # Measured after normalisation, so it is close to but not equal to the
    # source length — collapsed whitespace and stripped control characters.
    assert 0 < parsed.raw_length <= len(resume_text)
    text = parsed.to_search_text()
    assert "Skills:" in text
    assert "Python" in text


def test_empty_input_does_not_explode():
    result = parse_resume_text("")
    assert result.skills == []
    assert result.name is None


def test_split_sections_recognises_variant_headers():
    sections = split_sections("WORK EXPERIENCE\nAcme\n\nTECHNICAL SKILLS\nPython\n\nEDUCATION\nBSc")
    assert "experience" in sections
    assert "skills" in sections
    assert "education" in sections


def test_split_sections_tolerates_a_typo():
    """Headers are matched fuzzily; 'EXPERINCE' should still land."""
    sections = split_sections("EXPERINCE\nAcme Corp\nDid things\n")
    assert "experience" in sections
