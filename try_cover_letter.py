#!/usr/bin/env python
"""
Quick local harness to test the resume parser + cover letter generator
against real job listings fetched from the Jobicy demo API.

Usage (from repo root):

    python try_cover_letter.py

Make sure you have:
  - a valid resume file on disk
  - Ollama running if you want LLM generation (otherwise fallback text is used)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from get_data import fetch_jobs
from server.app.services.resume_parser import parse_resume_file
from server.app.services.cover_letter_generator import generate_cover_letter


# --- config section: tweak these for your local testing ----------------------

# Point this at your actual resume file
RESUME_PATH = Path("../Downloads/resume.pdf")

# How many jobs to fetch from the API
JOB_COUNT = 15

# How many of the fetched jobs to generate letters for (to keep output manageable)
NUM_JOBS_TO_SAMPLE = 3


# --- helper functions --------------------------------------------------------


def _summarize_job(job: Dict[str, Any]) -> str:
    """Create a one-line human-readable summary for printing."""
    title = job.get("jobTitle") or job.get("title") or job.get("name") or "Unknown role"
    company = job.get("companyName") or job.get("company") or job.get("org") or "Unknown company"
    geo = job.get("jobGeo") or job.get("location") or job.get("job_location") or "Unknown location"
    return f"{title} at {company} — {geo}"


def load_resume() -> Dict[str, Any]:
    """Parse the resume file using the shared resume parser."""
    if not RESUME_PATH.exists():
        raise FileNotFoundError(
            f"Resume file not found at {RESUME_PATH!s}. "
            "Update RESUME_PATH in try_cover_letter.py."
        )
    print(f"Parsing resume from: {RESUME_PATH}")
    resume_data = parse_resume_file(RESUME_PATH)
    print(f"Parsed resume for: {resume_data.get('name') or 'Unknown candidate'}")
    return resume_data


def load_jobs() -> List[Dict[str, Any]]:
    """Fetch jobs from the demo API via get_data.fetch_jobs."""
    print(f"\nFetching up to {JOB_COUNT} jobs from Jobicy API...")
    jobs = fetch_jobs(count=JOB_COUNT, out_path="jobs.json")
    if not jobs:
        print("No jobs were parsed from the API response.")
    else:
        print(f"Retrieved {len(jobs)} jobs.")
    return jobs


def main() -> None:
    # 1) Parse resume
    resume = load_resume()

    # 2) Fetch jobs from the API
    jobs = load_jobs()
    if not jobs:
        return

    # 3) Sample a few jobs and generate letters
    print("\n===== Generating cover letters for sampled jobs =====\n")

    for idx, job in enumerate(jobs[:NUM_JOBS_TO_SAMPLE], start=1):
        job_summary = _summarize_job(job)
        print("=" * 80)
        print(f"Job {idx}: {job_summary}")
        print("=" * 80)

        letter = generate_cover_letter(resume, job)

        print("\n--- GENERATED COVER LETTER ---\n")
        print(letter)
        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()

