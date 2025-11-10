from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import logging

from ..controllers.mcp_controller import MCPController

router = APIRouter()
logger = logging.getLogger(__name__)


class IngestResponse(BaseModel):
    imported: int


class JobSummary(BaseModel):
    id: int
    title: Optional[str]
    company: Optional[str]
    location: Optional[str]


@router.post("/ingest", response_model=IngestResponse)
def ingest_jobs(count: int = 100, out_path: Optional[str] = None):
    controller = MCPController.instance()
    logger.info("API request: ingest count=%s out_path=%s", count, out_path)
    n = controller.ingest(count=count, out_path=out_path)
    return IngestResponse(imported=int(n))


@router.get("/jobs", response_model=List[JobSummary])
def list_jobs():
    controller = MCPController.instance()
    logger.info("API request: list_jobs")
    return controller.list_jobs()


@router.post("/jobs/{job_id}/claim")
def claim_job(job_id: int):
    controller = MCPController.instance()
    logger.info("API request: claim_job %s", job_id)
    ok = controller.claim_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Job already claimed or not found")
    return {"status": "claimed"}


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, result: dict):
    controller = MCPController.instance()
    logger.info("API request: complete_job %s", job_id)
    ok = controller.complete_job(job_id, result)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "completed"}
