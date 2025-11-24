"""FastAPI Frontend for Job Application MCP Server

This FastAPI application provides REST API endpoints to interact with the
MCP job application pipeline server. It exposes web-friendly endpoints for:
- Fetching and storing jobs
- Parsing resumes
- Generating cover letters
- Running the complete pipeline
- Job recommendations

Run with: uvicorn server.api_frontend:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import logging

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Local imports
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

# Initialize FastAPI app
app = FastAPI(
    title="Job Application Pipeline API",
    description="REST API for job searching, resume parsing, and cover letter generation",
    version="1.0.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Request/Response Models
# =============================================================================

class FetchJobsRequest(BaseModel):
    count: int = Field(100, ge=1, le=500, description="Number of jobs to fetch")
    out_path: str = Field("jobs.json", description="Output file path")


class FetchJobsResponse(BaseModel):
    status: str
    fetched: int
    out_path: str
    message: str


class ParseResumeResponse(BaseModel):
    status: str
    name: Optional[str] = None
    skills: List[str] = []
    experience_count: int = 0
    education_count: int = 0
    message: str


class GenerateCoverLetterRequest(BaseModel):
    resume_data: Dict[str, Any] = Field(..., description="Parsed resume data")
    job_data: Dict[str, Any] = Field(..., description="Job posting data")
    model_name: str = Field("llama3.2", description="LLM model name")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Generation temperature")


class GenerateCoverLetterResponse(BaseModel):
    status: str
    cover_letter: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    message: str


class RecommendJobsRequest(BaseModel):
    resume_data: Dict[str, Any] = Field(..., description="Parsed resume data")
    jobs_file: str = Field("jobs.json", description="Path to jobs JSON file")
    top_k: int = Field(10, ge=1, le=50, description="Number of recommendations")
    min_similarity: float = Field(0.25, ge=0.0, le=1.0, description="Minimum similarity threshold")
    filter_senior: bool = Field(True, description="Filter senior roles for junior candidates")


class RecommendJobsResponse(BaseModel):
    status: str
    recommendations: List[Dict[str, Any]] = []
    count: int
    message: str


class PipelineRequest(BaseModel):
    job_count: int = Field(50, ge=1, le=200, description="Number of jobs to fetch")
    jobs_file: str = Field("jobs.json", description="Output file for jobs")
    mongo_url: str = Field("mongodb://localhost:27017", description="MongoDB connection URL")
    generate_first_cover_letter: bool = Field(True, description="Generate cover letter for first job")


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    """Health check and API information."""
    return {
        "service": "Job Application Pipeline API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "fetch_jobs": "/api/jobs/fetch",
            "parse_resume": "/api/resume/parse",
            "generate_cover_letter": "/api/cover-letter/generate",
            "recommend_jobs": "/api/jobs/recommend",
            "complete_pipeline": "/api/pipeline/run"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# -----------------------------------------------------------------------------
# Job Fetching
# -----------------------------------------------------------------------------

@app.post("/api/jobs/fetch", response_model=FetchJobsResponse)
async def fetch_jobs_endpoint(request: FetchJobsRequest):
    """Fetch job listings from the API and save to file.
    
    This endpoint fetches remote job postings and stores them in a JSON file.
    """
    logger.info(f"Fetching {request.count} jobs to {request.out_path}")
    
    try:
        jobs = fetch_jobs(count=request.count, out_path=request.out_path)
        resolved_path = Path(request.out_path).resolve()
        
        return FetchJobsResponse(
            status="success",
            fetched=len(jobs),
            out_path=str(resolved_path),
            message=f"Successfully fetched {len(jobs)} jobs"
        )
    except Exception as e:
        logger.exception(f"Failed to fetch jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch jobs: {str(e)}")


@app.get("/api/jobs/list")
async def list_jobs(
    jobs_file: str = Query("jobs.json", description="Path to jobs JSON file"),
    limit: int = Query(50, ge=1, le=500, description="Maximum jobs to return")
):
    """List jobs from the stored jobs file."""
    logger.info(f"Listing jobs from {jobs_file}")
    
    p = Path(jobs_file)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Jobs file not found: {jobs_file}")
    
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        
        # Extract jobs list
        jobs = []
        if isinstance(data, dict):
            for k in ("jobs", "data", "results", "items"):
                if k in data and isinstance(data[k], list):
                    jobs = data[k]
                    break
        elif isinstance(data, list):
            jobs = data
        
        return {
            "status": "success",
            "total": len(jobs),
            "returned": min(len(jobs), limit),
            "jobs": jobs[:limit]
        }
    except Exception as e:
        logger.exception(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


# -----------------------------------------------------------------------------
# Resume Parsing
# -----------------------------------------------------------------------------

@app.post("/api/resume/parse", response_model=ParseResumeResponse)
async def parse_resume_endpoint(
    file: UploadFile = File(..., description="Resume file (PDF, DOCX, or TXT)")
):
    """Parse an uploaded resume file.
    
    Accepts PDF, DOCX, or TXT files and extracts structured information
    including name, skills, experience, education, and projects.
    """
    logger.info(f"Parsing resume: {file.filename}")
    
    # Save uploaded file temporarily
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    
    temp_path = temp_dir / file.filename
    try:
        # Write uploaded file
        content = await file.read()
        temp_path.write_bytes(content)
        
        # Parse resume
        parsed = parse_resume_file(temp_path)
        
        return ParseResumeResponse(
            status="success",
            name=parsed.get("name"),
            skills=parsed.get("skills", []),
            experience_count=len(parsed.get("experience", [])),
            education_count=len(parsed.get("education", [])),
            message=f"Successfully parsed resume for {parsed.get('name', 'Unknown')}"
        )
    except Exception as e:
        logger.exception(f"Failed to parse resume: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse resume: {str(e)}")
    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()


@app.post("/api/resume/parse-path")
async def parse_resume_path_endpoint(resume_path: str = Form(...)):
    """Parse a resume from a file path on the server.
    
    This is useful when the resume is already stored on the server.
    """
    logger.info(f"Parsing resume from path: {resume_path}")
    
    p = Path(resume_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Resume file not found: {resume_path}")
    
    try:
        parsed = parse_resume_file(p)
        
        return {
            "status": "success",
            "parsed": parsed,
            "message": f"Successfully parsed resume for {parsed.get('name', 'Unknown')}"
        }
    except Exception as e:
        logger.exception(f"Failed to parse resume: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse resume: {str(e)}")


# -----------------------------------------------------------------------------
# Cover Letter Generation
# -----------------------------------------------------------------------------

@app.post("/api/cover-letter/generate", response_model=GenerateCoverLetterResponse)
async def generate_cover_letter_endpoint(request: GenerateCoverLetterRequest):
    """Generate a personalized cover letter.
    
    Takes parsed resume data and job posting data to create a tailored
    cover letter using an LLM (Ollama).
    """
    job_title = request.job_data.get("title") or request.job_data.get("jobTitle") or "Unknown"
    company = request.job_data.get("company") or request.job_data.get("companyName") or "Unknown"
    
    logger.info(f"Generating cover letter for {job_title} at {company}")
    
    try:
        letter = generate_cover_letter(
            request.resume_data,
            request.job_data,
            model_name=request.model_name,
            temperature=request.temperature
        )
        
        return GenerateCoverLetterResponse(
            status="success",
            cover_letter=letter,
            job_title=job_title,
            company=company,
            message="Cover letter generated successfully"
        )
    except Exception as e:
        logger.exception(f"Failed to generate cover letter: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate cover letter: {str(e)}"
        )


# -----------------------------------------------------------------------------
# Job Recommendations
# -----------------------------------------------------------------------------

@app.post("/api/jobs/recommend", response_model=RecommendJobsResponse)
async def recommend_jobs_endpoint(request: RecommendJobsRequest):
    """Get job recommendations based on resume.
    
    Uses semantic similarity (sentence-transformers) to rank jobs
    by relevance to the candidate's resume.
    """
    logger.info(f"Generating {request.top_k} job recommendations")
    
    # Load jobs
    p = Path(request.jobs_file)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Jobs file not found: {request.jobs_file}")
    
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        
        # Extract jobs list
        jobs = []
        if isinstance(data, dict):
            for k in ("jobs", "data", "results", "items"):
                if k in data and isinstance(data[k], list):
                    jobs = data[k]
                    break
        elif isinstance(data, list):
            jobs = data
        
        if not jobs:
            raise HTTPException(status_code=404, detail="No jobs found in file")
        
        # Rank jobs
        recommendations = rank_jobs_for_resume(
            request.resume_data,
            jobs,
            top_k=request.top_k,
            min_similarity=request.min_similarity,
            filter_senior_for_grads=request.filter_senior
        )
        
        return RecommendJobsResponse(
            status="success",
            recommendations=recommendations,
            count=len(recommendations),
            message=f"Found {len(recommendations)} relevant jobs"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to recommend jobs: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to recommend jobs: {str(e)}"
        )


# -----------------------------------------------------------------------------
# Complete Pipeline
# -----------------------------------------------------------------------------

@app.post("/api/pipeline/run")
async def run_pipeline_endpoint(
    request: PipelineRequest,
    resume_file: UploadFile = File(..., description="Resume file to process")
):
    """Execute the complete job application pipeline.
    
    This endpoint orchestrates:
    1. Fetch jobs from API
    2. Parse uploaded resume
    3. Recommend top jobs
    4. (Optional) Generate cover letter for best match
    """
    logger.info("Starting complete pipeline")
    
    # Create temp directory
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    resume_path = temp_dir / resume_file.filename
    
    try:
        # Save uploaded resume
        content = await resume_file.read()
        resume_path.write_bytes(content)
        
        results = {"status": "running", "stages": {}}
        
        # Stage 1: Fetch jobs
        logger.info("Stage 1: Fetching jobs")
        try:
            jobs = fetch_jobs(count=request.job_count, out_path=request.jobs_file)
            results["stages"]["fetch"] = {
                "status": "success",
                "count": len(jobs)
            }
        except Exception as e:
            logger.exception(f"Fetch failed: {e}")
            results["stages"]["fetch"] = {"status": "error", "error": str(e)}
            results["status"] = "failed_at_fetch"
            return JSONResponse(content=results, status_code=500)
        
        # Stage 2: Parse resume
        logger.info("Stage 2: Parsing resume")
        try:
            parsed_resume = parse_resume_file(resume_path)
            results["stages"]["parse"] = {
                "status": "success",
                "name": parsed_resume.get("name"),
                "skills_count": len(parsed_resume.get("skills", []))
            }
        except Exception as e:
            logger.exception(f"Parse failed: {e}")
            results["stages"]["parse"] = {"status": "error", "error": str(e)}
            results["status"] = "failed_at_parse"
            return JSONResponse(content=results, status_code=500)
        
        # Stage 3: Recommend jobs
        logger.info("Stage 3: Recommending jobs")
        try:
            recommendations = rank_jobs_for_resume(
                parsed_resume,
                jobs,
                top_k=10,
                min_similarity=0.25,
                filter_senior_for_grads=True
            )
            results["stages"]["recommend"] = {
                "status": "success",
                "count": len(recommendations),
                "top_jobs": recommendations[:5]  # Include top 5 in results
            }
        except Exception as e:
            logger.exception(f"Recommendation failed: {e}")
            results["stages"]["recommend"] = {"status": "error", "error": str(e)}
        
        # Stage 4: Generate cover letter for best match
        if request.generate_first_cover_letter and recommendations:
            logger.info("Stage 4: Generating cover letter")
            try:
                best_job = recommendations[0]
                cover_letter = generate_cover_letter(parsed_resume, best_job)
                results["stages"]["cover_letter"] = {
                    "status": "success",
                    "job_title": best_job.get("jobTitle") or best_job.get("title"),
                    "company": best_job.get("companyName") or best_job.get("company"),
                    "similarity": best_job.get("similarity"),
                    "letter": cover_letter
                }
            except Exception as e:
                logger.exception(f"Cover letter generation failed: {e}")
                results["stages"]["cover_letter"] = {"status": "error", "error": str(e)}
        
        results["status"] = "success"
        logger.info("Pipeline completed successfully")
        return results
        
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {str(e)}")
    finally:
        # Cleanup
        if resume_path.exists():
            resume_path.unlink()


# =============================================================================
# Run Server
# =============================================================================

if __name__ == "__main__":
    logger.info("Starting FastAPI server on http://0.0.0.0:8000")
    uvicorn.run(
        "server.api_frontend:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
