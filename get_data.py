"""Modular job ingestion from multiple sources.

This refactored version uses a provider-based architecture to allow
easy integration of multiple job sources (Jobicy, Indeed, RapidAPI, etc.).
"""
import json
from pathlib import Path
import requests
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseJobProvider(ABC):
    """Abstract base class for all job providers."""
    
    @abstractmethod
    def fetch_jobs(self, count: int) -> List[Dict[str, Any]]:
        """Fetch jobs from the provider.
        
        Args:
            count: Number of jobs to attempt to fetch.
            
        Returns:
            A list of job dictionaries.
        """
        pass

    def normalize_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize job fields to a common schema.
        
        Standard fields: title, company, location, description, url, source.
        """
        # Default implementation just returns the job as is
        return job

class JobicyProvider(BaseJobProvider):
    """Fetches jobs from Jobicy API."""
    
    def __init__(self, geo: str = "usa", industry: str = "dev"):
        self.geo = geo
        self.industry = industry
        self.url = "https://jobicy.com/api/v2/remote-jobs"
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def fetch_jobs(self, count: int) -> List[Dict[str, Any]]:
        params = {
            "count": count,
            "geo": self.geo,
            "industry": self.industry
        }
        
        logger.info(f"Fetching jobs from Jobicy: {self.geo}/{self.industry}")
        try:
            r = requests.get(self.url, params=params, headers=self.headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            
            jobs = []
            if isinstance(data, dict):
                for k in ("jobs", "data", "results", "items"):
                    if k in data and isinstance(data[k], list):
                        jobs = data[k]
                        break
                if not jobs:
                    # Try finding any list in the response
                    lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
                    if lists:
                        jobs = max(lists, key=lambda kv: len(kv[1]))[1]
            elif isinstance(data, list):
                jobs = data
                
            return [self.normalize_job(j) for j in jobs]
        except Exception as e:
            logger.error(f"Jobicy fetch failed: {e}")
            return []

    def normalize_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Jobicy fields to standard schema by ensuring standard fields exist."""
        # Ensure we don't modify the original if not needed, but here it's fine
        job["title"] = job.get("title") or job.get("jobTitle")
        job["company"] = job.get("company") or job.get("companyName")
        job["location"] = job.get("location") or job.get("jobGeo") or "Remote"
        job["description"] = job.get("description") or job.get("jobDescription")
        job["url"] = job.get("url") or job.get("jobUrl")
        job["source"] = job.get("source") or "Jobicy"
        return job

class MockProvider(BaseJobProvider):
    """A mock provider for testing purposes."""
    
    def fetch_jobs(self, count: int) -> List[Dict[str, Any]]:
        logger.info(f"Generating {count} mock jobs")
        mock_jobs = []
        for i in range(count):
            mock_jobs.append({
                "title": f"Software Engineer {i}",
                "company": f"TechCorp {i}",
                "location": "Remote",
                "description": f"This is a mock job description for position {i}.",
                "url": f"https://example.com/jobs/{i}",
                "source": "Mock"
            })
        return mock_jobs

class MultiSourceJobProvider:
    """Orchestrates job fetching from multiple providers."""
    
    def __init__(self, providers: List[BaseJobProvider]):
        self.providers = providers

    def fetch_all(self, count_per_provider: int = 50) -> List[Dict[str, Any]]:
        all_jobs = []
        for provider in self.providers:
            jobs = provider.fetch_jobs(count_per_provider)
            all_jobs.extend(jobs)
            logger.info(f"Fetched {len(jobs)} jobs from {provider.__class__.__name__}")
        return all_jobs

def fetch_jobs(count: int = 100, out_path: Path | str = "jobs.json", use_mock: bool = False) -> list:
    """Fetch jobs from available sources and save to out_path.
    
    Maintained for backward compatibility.
    """
    out_path = Path(out_path)
    
    providers = [JobicyProvider()]
    if use_mock:
        providers.append(MockProvider())
        
    orchestrator = MultiSourceJobProvider(providers)
    
    # If we want a specific total count, we divide by providers
    count_per = max(1, count // len(providers))
    all_jobs = orchestrator.fetch_all(count_per)
    
    # Save the data
    # For backward compatibility with scripts expecting the raw Jobicy structure,
    # we might need to be careful, but the new standard schema is better.
    # Most tools in this project seem to handle 'payload' or direct access.
    
    output_data = {"jobs": all_jobs, "count": len(all_jobs)}
    
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Saved {len(all_jobs)} jobs to {out_path}")
    return all_jobs

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch jobs from multiple sources.")
    parser.add_argument("--count", type=int, default=100, help="Total jobs to fetch")
    parser.add_argument("--out", type=str, default="jobs.json", help="Output file path")
    parser.add_argument("--mock", action="store_true", help="Include mock provider")
    args = parser.parse_args()
    
    fetch_jobs(count=args.count, out_path=args.out, use_mock=args.mock)
