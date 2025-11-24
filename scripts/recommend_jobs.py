"""Job Recommendation Script

This script uses the matching engine to analyze job postings and a parsed resume,
then recommends the top k most relevant jobs based on semantic similarity.

Usage:
    python scripts/recommend_jobs.py --resume path/to/resume.pdf --jobs jobs.json --top-k 10

Features:
- Semantic similarity scoring using sentence-transformers
- Seniority level filtering (filters senior roles for junior candidates)
- Configurable minimum similarity threshold
- Detailed output with match scores
- Option to save recommendations to JSON file
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import argparse
import json
import logging
import os
from typing import Dict, Any, List, Optional

from server.app.services.resume_parser import parse_resume_file
from server.app.services.matching_engine import rank_jobs_for_resume
from get_data import fetch_jobs

# MongoDB imports (optional)
try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def load_jobs_from_file(jobs_file: str) -> List[Dict[str, Any]]:
    """Load jobs from a JSON file.
    
    Args:
        jobs_file: Path to the jobs JSON file
        
    Returns:
        List of job dictionaries
        
    Raises:
        FileNotFoundError: If jobs file doesn't exist
        ValueError: If no jobs found in file
    """
    p = Path(jobs_file)
    if not p.exists():
        raise FileNotFoundError(f"Jobs file not found: {jobs_file}")
    
    logger.info(f"Loading jobs from {jobs_file}")
    
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse JSON from {jobs_file}: {e}")
    
    # Extract jobs list (handle different JSON structures)
    jobs = []
    if isinstance(data, dict):
        for k in ("jobs", "data", "results", "items"):
            if k in data and isinstance(data[k], list):
                jobs = data[k]
                break
        if not jobs:
            # Find the largest list in the dict
            lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
            if lists:
                jobs = max(lists, key=lambda kv: len(kv[1]))[1]
    elif isinstance(data, list):
        jobs = data
    
    if not jobs:
        raise ValueError(f"No jobs found in {jobs_file}")
    
    logger.info(f"Loaded {len(jobs)} jobs")
    return jobs


def load_jobs_from_mongodb(
    connection_string: Optional[str] = None,
    database: str = "jobs",
    collection: str = "jobs",
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Load jobs from MongoDB.
    
    Args:
        connection_string: MongoDB connection string (uses env vars if None)
        database: Database name (default: "jobs")
        collection: Collection name (default: "jobs")
        limit: Maximum number of jobs to load (None = all)
    
    Returns:
        List of job dictionaries
        
    Raises:
        ImportError: If pymongo is not installed
        ConnectionFailure: If cannot connect to MongoDB
        ValueError: If no jobs found
    """
    if not MONGODB_AVAILABLE:
        raise ImportError(
            "pymongo is not installed. Install it with: pip install pymongo"
        )
    
    # Use environment variables if connection string not provided
    if connection_string is None:
        env_mongo = os.getenv("MONGO_URL")
        if env_mongo:
            connection_string = env_mongo
        else:
            m_user = os.getenv("MONGO_USER")
            m_pass = os.getenv("MONGO_PASS")
            if m_user and m_pass:
                connection_string = f"mongodb+srv://{m_user}:{m_pass}@cluster0.xdbs2l7.mongodb.net/"
            else:
                connection_string = "mongodb://localhost:27017/"
    
    logger.info(f"Connecting to MongoDB: {database}.{collection}")
    
    try:
        client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
    except ConnectionFailure as e:
        raise ConnectionFailure(f"Failed to connect to MongoDB: {e}")
    
    db = client[database]
    coll = db[collection]
    
    # Query jobs
    cursor = coll.find({}).limit(limit) if limit else coll.find({})
    jobs_raw = list(cursor)
    
    if not jobs_raw:
        client.close()
        raise ValueError(f"No jobs found in {database}.{collection}")
    
    # Extract jobs from payload field if using the populate_database format
    jobs = []
    for doc in jobs_raw:
        if "payload" in doc:
            # Document stored by populate_database tool
            jobs.append(doc["payload"])
        else:
            # Direct job document
            job = dict(doc)
            # Remove MongoDB _id field (not JSON serializable)
            if "_id" in job:
                del job["_id"]
            jobs.append(job)
    
    client.close()
    logger.info(f"Loaded {len(jobs)} jobs from MongoDB")
    return jobs


def format_job_summary(job: Dict[str, Any], rank: int) -> str:
    """Format a job for display.
    
    Args:
        job: Job dictionary with similarity score
        rank: Ranking position (1-indexed)
        
    Returns:
        Formatted string representation
    """
    title = job.get("jobTitle") or job.get("title") or job.get("name") or "Unknown Title"
    company = job.get("companyName") or job.get("company") or job.get("org") or "Unknown Company"
    location = job.get("jobGeo") or job.get("location") or job.get("job_location") or "Unknown Location"
    level = job.get("jobLevel") or "Not specified"
    similarity = job.get("similarity", 0.0)
    
    # Get URL if available
    url = job.get("url") or job.get("jobUrl") or job.get("link") or ""
    
    lines = [
        f"\n{'='*80}",
        f"Rank #{rank} | Match Score: {similarity*100:.1f}%",
        f"{'='*80}",
        f"Title:    {title}",
        f"Company:  {company}",
        f"Location: {location}",
        f"Level:    {level}",
    ]
    
    if url:
        lines.append(f"URL:      {url}")
    
    # Add job description preview if available
    desc = job.get("jobDescription") or job.get("description") or job.get("jobExcerpt") or ""
    if desc:
        # Truncate description to 200 chars
        preview = desc[:200] + "..." if len(desc) > 200 else desc
        preview = " ".join(preview.split())  # Clean up whitespace
        lines.append(f"\nDescription: {preview}")
    
    return "\n".join(lines)


def save_recommendations(
    recommendations: List[Dict[str, Any]],
    output_file: str,
    resume_name: str
) -> None:
    """Save recommendations to a JSON file.
    
    Args:
        recommendations: List of recommended jobs
        output_file: Path to output JSON file
        resume_name: Name of the candidate
    """
    output_data = {
        "candidate": resume_name,
        "total_recommendations": len(recommendations),
        "recommendations": recommendations
    }
    
    p = Path(output_file)
    with p.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved recommendations to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Recommend jobs based on resume analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Recommend jobs from existing jobs file
  python scripts/recommend_jobs.py --resume resume.pdf --jobs jobs.json --top-k 10

  # Fetch fresh jobs and recommend
  python scripts/recommend_jobs.py --resume resume.pdf --fetch 100 --top-k 15

  # Load jobs from MongoDB (using env vars)
  python scripts/recommend_jobs.py --resume resume.pdf --mongodb --top-k 10

  # Load jobs from MongoDB (custom connection)
  python scripts/recommend_jobs.py --resume resume.pdf --mongodb --mongo-uri mongodb://localhost:27017 --mongo-database jobs --mongo-collection jobs

  # Save recommendations to file
  python scripts/recommend_jobs.py --resume resume.pdf --jobs jobs.json --output recommendations.json

  # Adjust similarity threshold
  python scripts/recommend_jobs.py --resume resume.pdf --jobs jobs.json --min-similarity 0.3
        """
    )
    
    # Resume input
    parser.add_argument(
        "--resume",
        type=str,
        required=True,
        help="Path to resume file (PDF, DOCX, or TXT)"
    )
    
    # Jobs input (mutually exclusive)
    job_group = parser.add_mutually_exclusive_group(required=True)
    job_group.add_argument(
        "--jobs",
        type=str,
        help="Path to jobs JSON file"
    )
    job_group.add_argument(
        "--fetch",
        type=int,
        metavar="COUNT",
        help="Fetch COUNT jobs from API instead of using existing file"
    )
    job_group.add_argument(
        "--mongodb",
        action="store_true",
        help="Load jobs from MongoDB (uses env vars or --mongo-* options)"
    )
    
    # MongoDB options (only used with --mongodb)
    parser.add_argument(
        "--mongo-uri",
        type=str,
        help="MongoDB connection string (default: from MONGO_URL env or localhost)"
    )
    parser.add_argument(
        "--mongo-database",
        type=str,
        default="jobs",
        help="MongoDB database name (default: jobs)"
    )
    parser.add_argument(
        "--mongo-collection",
        type=str,
        default="jobs",
        help="MongoDB collection name (default: jobs)"
    )
    parser.add_argument(
        "--mongo-limit",
        type=int,
        help="Limit number of jobs to load from MongoDB"
    )
    
    # Recommendation parameters
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of top recommendations to show (default: 10)"
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.25,
        help="Minimum similarity threshold (0.0-1.0, default: 0.25)"
    )
    parser.add_argument(
        "--no-filter-senior",
        action="store_true",
        help="Disable filtering of senior roles for junior candidates"
    )
    
    # Output options
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Save recommendations to JSON file"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Sentence-transformers model name (default: all-MiniLM-L6-v2)"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Step 1: Parse resume
        logger.info(f"Parsing resume: {args.resume}")
        resume_path = Path(args.resume)
        
        if not resume_path.exists():
            logger.error(f"Resume file not found: {args.resume}")
            return 1
        
        parsed_resume = parse_resume_file(resume_path)
        candidate_name = parsed_resume.get("name", "Unknown")
        skills = parsed_resume.get("skills", [])
        experience_count = len(parsed_resume.get("experience", []))
        
        logger.info(f"Resume parsed for: {candidate_name}")
        logger.info(f"Skills found: {len(skills)}")
        logger.info(f"Experience entries: {experience_count}")
        
        if args.verbose and skills:
            logger.debug(f"Skills: {', '.join(sorted(skills))}")
        
        # Step 2: Load or fetch jobs
        if args.jobs:
            jobs = load_jobs_from_file(args.jobs)
        elif args.mongodb:
            if not MONGODB_AVAILABLE:
                logger.error("pymongo is not installed. Install with: pip install pymongo")
                return 1
            try:
                jobs = load_jobs_from_mongodb(
                    connection_string=args.mongo_uri,
                    database=args.mongo_database,
                    collection=args.mongo_collection,
                    limit=args.mongo_limit
                )
            except Exception as e:
                logger.error(f"Failed to load jobs from MongoDB: {e}")
                return 1
        else:
            logger.info(f"Fetching {args.fetch} jobs from API")
            jobs = fetch_jobs(count=args.fetch, out_path="jobs_temp.json")
        
        if not jobs:
            logger.error("No jobs available for recommendation")
            return 1
        
        # Step 3: Rank jobs
        logger.info(f"Ranking jobs using model: {args.model}")
        recommendations = rank_jobs_for_resume(
            parsed_resume,
            jobs,
            top_k=args.top_k,
            min_similarity=args.min_similarity,
            filter_senior_for_grads=not args.no_filter_senior,
            model_name=args.model
        )
        
        # Step 4: Display results
        print("\n" + "="*80)
        print(f"JOB RECOMMENDATIONS FOR: {candidate_name}")
        print("="*80)
        print(f"Total jobs analyzed: {len(jobs)}")
        print(f"Recommendations found: {len(recommendations)}")
        print(f"Minimum similarity: {args.min_similarity*100:.1f}%")
        print(f"Model: {args.model}")
        
        if not recommendations:
            print("\n⚠ No jobs found matching the criteria.")
            print("Try lowering --min-similarity or fetching more jobs.")
            return 0
        
        for i, job in enumerate(recommendations, start=1):
            print(format_job_summary(job, i))
        
        print("\n" + "="*80)
        print(f"Showing top {len(recommendations)} recommendations")
        print("="*80 + "\n")
        
        # Step 5: Save to file if requested
        if args.output:
            save_recommendations(recommendations, args.output, candidate_name)
            print(f"✓ Recommendations saved to: {args.output}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
