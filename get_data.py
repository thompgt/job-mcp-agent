"""Download job listings and save to jobs.json.

This file was extracted from the first cell of `eda.ipynb` and adapted to be
executable as a standalone script.
"""
import json
from pathlib import Path
import requests


def fetch_jobs(count: int = 100, out_path: Path | str = "jobs.json") -> list:
    """Fetch jobs from a demo API and save raw response to out_path.

    Returns the parsed list of jobs (may be empty if API structure differs).
    """
    out_path = Path(out_path)
    url = f"https://jobicy.com/api/v2/remote-jobs?count={count}&geo=usa&industry=dev"
    headers = {"User-Agent": "Mozilla/5.0"}

    print(f"Fetching jobs from: {url}")
    r = requests.get(url, headers=headers, timeout=15)
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception as e:
        print("Failed to decode JSON:", e)
        data = {}

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    jobs = []
    if isinstance(data, dict):
        for k in ("jobs", "data", "results", "items"):
            if k in data and isinstance(data[k], list):
                jobs = data[k]
                break

        if not jobs:
            lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
            if lists:
                jobs = max(lists, key=lambda kv: len(kv[1]))[1]
    elif isinstance(data, list):
        jobs = data

    print(f"Saved raw response to {out_path}. Parsed {len(jobs)} jobs (may be 0 if structure differs).")
    for job in jobs[:20]:
        title = job.get('jobTitle') or job.get('title') or job.get('name')
        company = job.get('companyName') or job.get('company') or job.get('org')
        geo = job.get('jobGeo') or job.get('location') or job.get('job_location')
        print(f"{title} at {company} — {geo}")

    return jobs


if __name__ == "__main__":
    fetch_jobs()
