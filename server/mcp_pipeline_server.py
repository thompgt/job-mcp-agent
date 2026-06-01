"""MCP Pipeline Server with Traditional Decorators

A complete MCP server that orchestrates the full job application pipeline:
1. Fetch job data from API
2. Populate MongoDB with jobs
3. Parse resume file (PDF/DOCX/TXT)
4. Generate cover letters for specific jobs

This uses FastMCP with decorator-based tools for a traditional MCP approach.
"""
from __future__ import annotations

import sys
from pathlib import Path
import asyncio
import json
import hashlib
import logging
import os
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastmcp import FastMCP
from get_data import fetch_jobs
from server.app.services.resume_parser import parse_resume_file
from server.app.services.cover_letter_generator import generate_cover_letter
from server.app.services.matching_engine import rank_jobs_for_resume

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP("JobApplicationPipeline")


# =============================================================================
# Tool 1: Fetch Jobs
# =============================================================================

@mcp.tool()
def fetch_job_data(count: int = 100, out_path: str = "jobs.json") -> dict:
    """Fetch job listings from the API and save to a JSON file.
    
    Args:
        count: Number of jobs to fetch (default: 100)
        out_path: Output file path for the fetched jobs (default: "jobs.json")
    
    Returns:
        Dictionary with 'fetched' count and 'out_path' location
    """
    logger.info(f"Fetching {count} jobs to {out_path}")
    
    try:
        jobs = fetch_jobs(count=count, out_path=out_path)
        resolved_path = Path(out_path).resolve()
        
        logger.info(f"Successfully fetched {len(jobs)} jobs")
        return {
            "status": "success",
            "fetched": len(jobs),
            "out_path": str(resolved_path)
        }
    except Exception as e:
        logger.exception(f"Failed to fetch jobs: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fetched": 0
        }


# =============================================================================
# Tool 2: Populate MongoDB
# =============================================================================

@mcp.tool()
def populate_mongodb(
    out_path: str = "jobs.json",
    mongo_url: str = "mongodb://localhost:27017"
) -> dict:
    """Populate MongoDB with jobs from a JSON file.
    
    Deduplicates jobs by computing SHA256 hash of normalized job payload.
    Uses environment variables MONGO_URL, MONGO_USER, MONGO_PASS if available.
    
    Args:
        out_path: Path to the jobs JSON file (default: "jobs.json")
        mongo_url: MongoDB connection URL (default: "mongodb://localhost:27017")
    
    Returns:
        Dictionary with 'inserted', 'existing', 'errors' counts and status
    """
    logger.info(f"Populating MongoDB from {out_path}")
    
    # Override with environment variables
    env_mongo = os.getenv("MONGO_URL")
    if env_mongo:
        if "<db_password>" in env_mongo:
            env_mongo = env_mongo.replace("<db_password>", quote_plus(os.getenv("MONGO_PASS", "")))
        mongo_url = env_mongo
    else:
        m_user = os.getenv("MONGO_USER")
        m_pass = os.getenv("MONGO_PASS")
        if m_user and m_pass:
            mongo_url = f"mongodb+srv://{m_user}:{m_pass}@cluster0.xdbs2l7.mongodb.net/"
    
    # Read jobs file
    p = Path(out_path)
    if not p.exists():
        logger.warning(f"Jobs file does not exist: {out_path}")
        return {
            "status": "error",
            "error": "file_not_found",
            "inserted": 0,
            "existing": 0,
            "errors": 0
        }
    
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.exception(f"Failed to parse JSON from {out_path}: {e}")
        return {
            "status": "error",
            "error": "json_parse_failed",
            "detail": str(e),
            "inserted": 0,
            "existing": 0,
            "errors": 0
        }
    
    # Extract jobs list
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
    
    if not jobs:
        logger.warning(f"No jobs found in {out_path}")
        return {
            "status": "error",
            "error": "no_jobs_found",
            "inserted": 0,
            "existing": 0,
            "errors": 0
        }
    
    # Connect to MongoDB
    try:
        import pymongo
        from pymongo.errors import DuplicateKeyError
    except ImportError:
        logger.error("pymongo not installed")
        return {
            "status": "error",
            "error": "pymongo_not_installed",
            "inserted": 0,
            "existing": 0,
            "errors": 0
        }
    
    try:
        client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        logger.info("Connected to MongoDB")
    except Exception as e:
        logger.exception(f"Failed to connect to MongoDB: {e}")
        return {
            "status": "error",
            "error": "mongo_connection_failed",
            "detail": str(e),
            "inserted": 0,
            "existing": 0,
            "errors": 0
        }
    
    db = client["jobs"]
    col = db["jobs"]
    
    # Create unique index on source_hash
    try:
        col.create_index("source_hash", unique=True)
    except Exception:
        logger.debug("Index on source_hash already exists")
    
    # Normalize and insert jobs
    def _normalize(job_obj: dict) -> dict:
        j = dict(job_obj)
        for fld in ("fetched_at", "scraped_at", "request_id", "crawl_id", "id"):
            j.pop(fld, None)
        return j
    
    inserted = 0
    existing = 0
    errors = 0
    
    for job in jobs:
        try:
            norm = _normalize(job)
            payload_str = json.dumps(norm, sort_keys=True, ensure_ascii=False)
            h = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            doc = {"source_hash": h, "payload": job}
            
            try:
                res = col.update_one({"source_hash": h}, {"$setOnInsert": doc}, upsert=True)
                if getattr(res, "upserted_id", None) is not None:
                    inserted += 1
                else:
                    existing += 1
            except DuplicateKeyError:
                existing += 1
        except Exception as e:
            logger.exception(f"Failed to insert job: {e}")
            errors += 1
    
    logger.info(f"MongoDB population complete: {inserted} inserted, {existing} existing, {errors} errors")
    return {
        "status": "success",
        "inserted": inserted,
        "existing": existing,
        "errors": errors,
        "total_jobs": len(jobs)
    }


# =============================================================================
# Tool 3: Parse Resume
# =============================================================================

@mcp.tool()
def parse_resume(resume_path: str) -> dict:
    """Parse a resume file (PDF, DOCX, or TXT) into structured data.
    
    Args:
        resume_path: Path to the resume file
    
    Returns:
        Dictionary with parsed resume data including name, skills, experience, etc.
    """
    logger.info(f"Parsing resume: {resume_path}")
    
    p = Path(resume_path)
    if not p.exists():
        logger.warning(f"Resume file not found: {resume_path}")
        return {
            "status": "error",
            "error": "file_not_found",
            "path": str(p)
        }
    
    try:
        parsed = parse_resume_file(p)
        logger.info(f"Successfully parsed resume: {parsed.get('name', 'Unknown')}")
        return {
            "status": "success",
            "parsed": parsed,
            "path": str(p),
            "skills_count": len(parsed.get("skills", [])),
            "experience_count": len(parsed.get("experience", [])),
            "education_count": len(parsed.get("education", []))
        }
    except Exception as e:
        logger.exception(f"Failed to parse resume: {e}")
        return {
            "status": "error",
            "error": "parse_failed",
            "detail": str(e),
            "path": str(p)
        }


# =============================================================================
# Tool 4: Generate Cover Letter
# =============================================================================

@mcp.tool()
def create_cover_letter(
    resume: Dict[str, Any],
    job: Dict[str, Any],
    model_name: str = "llama3.2:1b",
    temperature: float = 0.7,
    tone: str = "professional",
    length: str = "medium"
) -> dict:
    """Generate a personalized cover letter for a job posting.
    
    Args:
        resume: Parsed resume dictionary from parse_resume tool
        job: Job posting dictionary
        model_name: LLM model name for generation (default: "llama3.2")
        temperature: Temperature for text generation (default: 0.7)
        tone: Tone of the letter (professional, enthusiastic, concise, academic)
        length: Length of the letter (short, medium, long)
    
    Returns:
        Dictionary with the generated cover letter or error
    """
    # Handle different job field naming conventions
    # Extract job data if wrapped in a match object with similarity score
    job_data = job.get("job", job) if "job" in job else job
    
    # Normalize field names
    job_title = (
        job_data.get("title") or 
        job_data.get("jobTitle") or 
        job_data.get("name") or 
        job_data.get("position") or 
        "Unknown"
    )
    company = (
        job_data.get("company") or 
        job_data.get("companyName") or 
        job_data.get("company_name") or 
        job_data.get("employer") or 
        "Unknown"
    )
    
    logger.info(f"Generating cover letter for {job_title} at {company} (Tone: {tone}, Length: {length})")
    
    try:
        letter = generate_cover_letter(
            resume,
            job_data,
            model_name=model_name,
            temperature=temperature,
            tone=tone,
            length=length
        )
        
        logger.info("Cover letter generated successfully")
        return {
            "status": "success",
            "cover_letter": letter,
            "job_title": job_title,
            "company": company,
            "letter_length": len(letter),
            "parameters": {
                "tone": tone,
                "length": length
            }
        }
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Failed to generate cover letter: {error_msg}")
        logger.error(f"Full exception: {repr(e)}")
        return {
            "status": "error",
            "error": "generation_failed",
            "detail": error_msg,
            "exception_type": type(e).__name__
        }


# =============================================================================
# Tool 5: Match Jobs to Resume
# =============================================================================

@mcp.tool()
def match_jobs_to_resume(
    resume: Dict[str, Any],
    jobs_source: str = "mongodb",
    jobs_file: str = "jobs.json",
    mongo_url: str = "mongodb://localhost:27017",
    top_k: int = 10,
    min_similarity: float = 0.25,
    filter_senior_for_grads: bool = True,
    model_name: str = "all-MiniLM-L6-v2"
) -> dict:
    """Match and rank jobs for a parsed resume using semantic similarity.
    
    Uses sentence-transformers to compute similarity between resume and job descriptions,
    with optional seniority filtering to remove senior roles for junior candidates.
    
    Args:
        resume: Parsed resume dictionary from parse_resume tool
        jobs_source: Source of jobs - "mongodb" or "file" (default: "mongodb")
        jobs_file: Path to jobs JSON file if jobs_source="file" (default: "jobs.json")
        mongo_url: MongoDB connection URL if jobs_source="mongodb"
        top_k: Number of top matching jobs to return (default: 10)
        min_similarity: Minimum cosine similarity threshold (default: 0.25)
        filter_senior_for_grads: Filter out senior roles for junior candidates (default: True)
        model_name: Sentence-transformers model name (default: "all-MiniLM-L6-v2")
    
    Returns:
        Dictionary with matched jobs, each augmented with similarity score
    """
    logger.info(f"Matching jobs from {jobs_source} for resume")
    
    # Load jobs from specified source
    jobs = []
    
    if jobs_source == "mongodb":
        # Override with environment variables
        env_mongo = os.getenv("MONGO_URL")
        if env_mongo:
            if "<db_password>" in env_mongo:
                env_mongo = env_mongo.replace("<db_password>", quote_plus(os.getenv("MONGO_PASS", "")))
            mongo_url = env_mongo
        else:
            m_user = os.getenv("MONGO_USER")
            m_pass = os.getenv("MONGO_PASS")
            if m_user and m_pass:
                mongo_url = f"mongodb+srv://{m_user}:{m_pass}@cluster0.xdbs2l7.mongodb.net/"
        
        try:
            import pymongo
        except ImportError:
            logger.error("pymongo not installed")
            return {
                "status": "error",
                "error": "pymongo_not_installed",
                "matches": []
            }
        
        try:
            client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            logger.info("Connected to MongoDB")
            
            db = client["jobs"]
            col = db["jobs"]
            
            # Load all jobs from MongoDB
            docs = list(col.find({}))
            jobs = [doc.get("payload", doc) for doc in docs]
            logger.info(f"Loaded {len(jobs)} jobs from MongoDB")
            
        except Exception as e:
            logger.exception(f"Failed to load jobs from MongoDB: {e}")
            return {
                "status": "error",
                "error": "mongo_connection_failed",
                "detail": str(e),
                "matches": []
            }
    
    elif jobs_source == "file":
        p = Path(jobs_file)
        if not p.exists():
            logger.warning(f"Jobs file not found: {jobs_file}")
            return {
                "status": "error",
                "error": "file_not_found",
                "path": str(p),
                "matches": []
            }
        
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            
            # Extract jobs list
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
            
            logger.info(f"Loaded {len(jobs)} jobs from {jobs_file}")
            
        except Exception as e:
            logger.exception(f"Failed to load jobs from file: {e}")
            return {
                "status": "error",
                "error": "file_read_failed",
                "detail": str(e),
                "matches": []
            }
    
    else:
        return {
            "status": "error",
            "error": "invalid_jobs_source",
            "detail": f"jobs_source must be 'mongodb' or 'file', got '{jobs_source}'",
            "matches": []
        }
    
    if not jobs:
        logger.warning("No jobs available for matching")
        return {
            "status": "error",
            "error": "no_jobs_available",
            "matches": []
        }
    
    # Perform matching
    try:
        matches = rank_jobs_for_resume(
            resume,
            jobs,
            top_k=top_k,
            min_similarity=min_similarity,
            filter_senior_for_grads=filter_senior_for_grads,
            model_name=model_name
        )
        
        logger.info(f"Found {len(matches)} matching jobs")
        
        return {
            "status": "success",
            "matches": matches,
            "total_jobs_considered": len(jobs),
            "matches_count": len(matches),
            "top_k": top_k,
            "min_similarity": min_similarity
        }
        
    except Exception as e:
        logger.exception(f"Failed to match jobs: {e}")
        return {
            "status": "error",
            "error": "matching_failed",
            "detail": str(e),
            "matches": []
        }


@mcp.tool()
def match_jobs_from_resume_path(
    resume_path: str,
    jobs_source: str = "mongodb",
    jobs_file: str = "jobs.json",
    mongo_url: str = "mongodb://localhost:27017",
    top_k: int = 10,
    min_similarity: float = 0.25,
    filter_senior_for_grads: bool = True,
    model_name: str = "all-MiniLM-L6-v2"
) -> dict:
    """Parse resume and match jobs in one step.
    
    Convenience tool that combines parse_resume and match_jobs_to_resume.
    
    Args:
        resume_path: Path to the resume file
        jobs_source: Source of jobs - "mongodb" or "file" (default: "mongodb")
        jobs_file: Path to jobs JSON file if jobs_source="file" (default: "jobs.json")
        mongo_url: MongoDB connection URL if jobs_source="mongodb"
        top_k: Number of top matching jobs to return (default: 10)
        min_similarity: Minimum cosine similarity threshold (default: 0.25)
        filter_senior_for_grads: Filter out senior roles for junior candidates (default: True)
        model_name: Sentence-transformers model name (default: "all-MiniLM-L6-v2")
    
    Returns:
        Dictionary with parsed resume info and matched jobs
    """
    logger.info(f"Parsing resume and matching jobs for: {resume_path}")
    
    # Parse resume using the actual function
    p = Path(resume_path)
    if not p.exists():
        return {
            "status": "error",
            "error": "file_not_found",
            "path": str(p),
            "matches": []
        }
    
    try:
        parsed_resume = parse_resume_file(p)
    except Exception as e:
        logger.exception(f"Failed to parse resume: {e}")
        return {
            "status": "error",
            "error": "resume_parse_failed",
            "detail": str(e),
            "matches": []
        }
    
    # Load jobs from specified source
    jobs = []
    
    if jobs_source == "mongodb":
        # Override with environment variables
        env_mongo = os.getenv("MONGO_URL")
        if env_mongo:
            if "<db_password>" in env_mongo:
                env_mongo = env_mongo.replace("<db_password>", quote_plus(os.getenv("MONGO_PASS", "")))
            mongo_url = env_mongo
        else:
            m_user = os.getenv("MONGO_USER")
            m_pass = os.getenv("MONGO_PASS")
            if m_user and m_pass:
                mongo_url = f"mongodb+srv://{m_user}:{m_pass}@cluster0.xdbs2l7.mongodb.net/"
        
        try:
            import pymongo
            client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            logger.info("Connected to MongoDB")
            
            db = client["jobs"]
            col = db["jobs"]
            docs = list(col.find({}))
            jobs = [doc.get("payload", doc) for doc in docs]
            logger.info(f"Loaded {len(jobs)} jobs from MongoDB")
            
        except Exception as e:
            logger.exception(f"Failed to load jobs from MongoDB: {e}")
            return {
                "status": "error",
                "error": "mongo_connection_failed",
                "detail": str(e),
                "matches": []
            }
    
    elif jobs_source == "file":
        p_jobs = Path(jobs_file)
        if not p_jobs.exists():
            return {
                "status": "error",
                "error": "file_not_found",
                "path": str(p_jobs),
                "matches": []
            }
        
        try:
            data = json.loads(p_jobs.read_text(encoding="utf-8"))
            
            # Extract jobs list
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
            
            logger.info(f"Loaded {len(jobs)} jobs from {jobs_file}")
            
        except Exception as e:
            logger.exception(f"Failed to load jobs from file: {e}")
            return {
                "status": "error",
                "error": "file_read_failed",
                "detail": str(e),
                "matches": []
            }
    
    if not jobs:
        return {
            "status": "error",
            "error": "no_jobs_available",
            "matches": []
        }
    
    # Perform matching using the actual function
    try:
        matches = rank_jobs_for_resume(
            parsed_resume,
            jobs,
            top_k=top_k,
            min_similarity=min_similarity,
            filter_senior_for_grads=filter_senior_for_grads,
            model_name=model_name
        )
        
        logger.info(f"Found {len(matches)} matching jobs")
        
        # Combine results
        return {
            "status": "success",
            "resume_info": {
                "name": parsed_resume.get("name"),
                "skills_count": len(parsed_resume.get("skills", [])),
                "experience_count": len(parsed_resume.get("experience", [])),
                "education_count": len(parsed_resume.get("education", []))
            },
            "matches": matches,
            "total_jobs_considered": len(jobs),
            "matches_count": len(matches)
        }
        
    except Exception as e:
        logger.exception(f"Failed to match jobs: {e}")
        return {
            "status": "error",
            "error": "matching_failed",
            "detail": str(e),
            "matches": []
        }


# =============================================================================
# Tool 6: Complete Pipeline
# =============================================================================

@mcp.tool()
def run_complete_pipeline(
    resume_path: str,
    job_count: int = 50,
    jobs_file: str = "jobs.json",
    mongo_url: str = "mongodb://localhost:27017",
    generate_cover_letter_for_first: bool = True
) -> dict:
    """Execute the complete job application pipeline.
    
    This orchestrates all steps:
    1. Fetch jobs from API
    2. Populate MongoDB
    3. Parse resume
    4. Match jobs to resume
    5. (Optional) Generate cover letter for best match
    
    Args:
        resume_path: Path to resume file
        job_count: Number of jobs to fetch (default: 50)
        jobs_file: Output file for fetched jobs (default: "jobs.json")
        mongo_url: MongoDB connection URL
        generate_cover_letter_for_first: Whether to generate cover letter for best match
    
    Returns:
        Dictionary with results from each pipeline stage
    """
    logger.info("Starting complete pipeline")
    results = {
        "status": "running",
        "stages": {}
    }
    
    # Stage 1: Fetch jobs
    logger.info("Stage 1: Fetching jobs")
    fetch_result = fetch_job_data(count=job_count, out_path=jobs_file)
    results["stages"]["fetch"] = fetch_result
    
    if fetch_result.get("status") != "success":
        results["status"] = "failed_at_fetch"
        return results
    
    # Stage 2: Populate MongoDB
    logger.info("Stage 2: Populating MongoDB")
    populate_result = populate_mongodb(out_path=jobs_file, mongo_url=mongo_url)
    results["stages"]["populate"] = populate_result
    
    # Stage 3: Parse resume
    logger.info("Stage 3: Parsing resume")
    parse_result = parse_resume(resume_path=resume_path)
    results["stages"]["parse"] = parse_result
    
    if parse_result.get("status") != "success":
        results["status"] = "failed_at_parse"
        return results
    
    parsed_resume = parse_result.get("parsed")
    
    # Stage 4: Match jobs to resume
    logger.info("Stage 4: Matching jobs to resume")
    match_result = match_jobs_to_resume(
        resume=parsed_resume,
        jobs_source="file",
        jobs_file=jobs_file,
        top_k=10,
        min_similarity=0.25
    )
    results["stages"]["match"] = match_result
    
    # Stage 5: Generate cover letter for best match (optional)
    if generate_cover_letter_for_first and match_result.get("status") == "success":
        matches = match_result.get("matches", [])
        if matches:
            logger.info("Stage 5: Generating cover letter for top match")
            
            try:
                best_match = matches[0]
                # Extract job data from match object (which has structure {"job": {...}, "similarity": 0.x})
                job_data = best_match.get("job", best_match) if isinstance(best_match, dict) and "job" in best_match else best_match
                
                cover_letter_result = create_cover_letter(
                    resume=parsed_resume,
                    job=job_data
                )
                results["stages"]["cover_letter"] = cover_letter_result
            except Exception as e:
                logger.exception(f"Failed to generate cover letter: {e}")
                results["stages"]["cover_letter"] = {
                    "status": "error",
                    "error": str(e)
                }
        else:
            results["stages"]["cover_letter"] = {
                "status": "skipped",
                "reason": "no_matching_jobs"
            }
    
    results["status"] = "success"
    logger.info("Pipeline completed successfully")
    return results


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    """Run the MCP server with HTTP transport.
    
    The server exposes all tools via the /mcp endpoint on port 8002.
    
    You can test it with the FastMCP client:
        from fastmcp import Client
        async with Client(mcp) as client:
            result = await client.call_tool("fetch_job_data", {"count": 10})
    """
    logger.info("Starting MCP Pipeline Server on http://127.0.0.1:8002/mcp")
    mcp.run(transport="http", host="127.0.0.1", port=8002, path="/mcp")
