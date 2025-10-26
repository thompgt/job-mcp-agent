from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from ..controllers.mcp_controller import MCPController

router = APIRouter()


class IngestResponse(BaseModel):
    imported: int


class JobSummary(BaseModel):
    id: int
    title: str | None
    company: str | None
    location: str | None


@router.post("/ingest", response_model=IngestResponse)
def ingest_jobs():
    controller = MCPController.instance()
    n = controller.ingest()
    return IngestResponse(imported=n)


@router.get("/jobs", response_model=List[JobSummary])
def list_jobs():
    controller = MCPController.instance()
    return controller.list_jobs()


@router.post("/jobs/{job_id}/claim")
def claim_job(job_id: int):
    controller = MCPController.instance()
    ok = controller.claim_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Job already claimed or not found")
    return {"status": "claimed"}


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, result: dict):
    controller = MCPController.instance()
    ok = controller.complete_job(job_id, result)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "completed"}


@router.post("/parse-resume")
async def parse_resume(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    try:
        return parse_resume_file(tmp_path)
    finally:
        try: tmp_path.unlink(missing_ok=True)
        except Exception: pass
