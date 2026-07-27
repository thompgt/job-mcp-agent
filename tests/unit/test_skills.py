"""Skill extraction.

The interesting cases are all about *not* matching: the vocabulary contains
one- and two-letter entries ("c", "r", "go", "ml") that appear inside ordinary
English constantly, so most of this file is false-positive regression tests.
"""

from __future__ import annotations

from careercraft.core.resume.skills import extract_skills, skill_overlap


def test_finds_canonical_skills():
    found = extract_skills("Experienced with Python, PostgreSQL and Docker.")
    assert {"Python", "PostgreSQL", "Docker"} <= set(found)


def test_aliases_map_to_one_canonical_name():
    found = extract_skills("Worked in JS and TypeScript, deploying to k8s.")
    assert "JavaScript" in found
    assert "TypeScript" in found
    assert "Kubernetes" in found


def test_results_are_deduplicated():
    found = extract_skills("python Python PYTHON py3 Python3")
    assert found.count("Python") == 1


def test_ambiguous_single_letters_need_delimiters():
    """'c' and 'r' must not fire on ordinary prose."""
    prose = "I can go there and see the results of our research."
    found = extract_skills(prose)
    assert "C" not in found
    assert "R" not in found
    assert "Go" not in found


def test_ambiguous_terms_do_fire_in_a_skills_list():
    found = extract_skills("Languages: C, R, Go, Python")
    assert {"C", "R", "Go", "Python"} <= set(found)


def test_no_substring_matches_inside_longer_words():
    found = extract_skills("We used Airflow and Sparkling water in Javanese docs.")
    assert "AI" not in found
    assert "Java" not in found


def test_plus_and_hash_names_survive_word_boundaries():
    found = extract_skills("Strong in C++ and C#.")
    assert "C++" in found
    assert "C#" in found


def test_skill_overlap_splits_matched_and_missing():
    matched, missing = skill_overlap(
        ["Python", "SQL"],
        "We need Python, Kubernetes and Terraform experience.",
    )
    assert matched == ["Python"]
    assert {"Kubernetes", "Terraform"} <= set(missing)
    assert "SQL" not in missing


def test_skill_overlap_on_empty_inputs():
    matched, missing = skill_overlap([], "")
    assert matched == []
    assert missing == []


def test_extra_terms_extend_the_vocabulary():
    assert "Splunk" not in extract_skills("Monitored with Splunk daily.")
    assert "Splunk" in extract_skills("Monitored with Splunk daily.", extra_terms=("Splunk",))
