"""
Web Frontend for Job Application Pipeline.

This provides a beautiful UI for the MCP job application pipeline with:
- Resume upload and parsing
- Background job fetching and MongoDB population
- Job matching and recommendations
- Job details view
- Cover letter generation with download
"""
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import asyncio
import json
import sys
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

# Add project root
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from fastmcp import Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Application Pipeline")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for session state
sessions: Dict[str, Dict[str, Any]] = {}

# MCP server URL
MCP_SERVER_URL = "http://127.0.0.1:8002/mcp"

async def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Helper to call MCP tools and extract results."""
    try:
        async with Client(MCP_SERVER_URL) as client:
            result = await client.call_tool(tool_name, arguments)
            
            # Extract result from CallToolResult
            if hasattr(result, 'content'):
                result_data = result.content[0].text if result.content else {}
                if isinstance(result_data, str):
                    result_data = json.loads(result_data)
            else:
                result_data = result
            
            return result_data
    except Exception as e:
        logger.exception(f"Error calling MCP tool {tool_name}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def background_job_fetching(session_id: str, job_count: int = 50):
    """Background task to fetch jobs and populate MongoDB."""
    logger.info(f"[{session_id}] Starting background job fetching")
    
    try:
        # Update session status
        sessions[session_id]["job_fetch_status"] = "fetching"
        
        # Step 1: Fetch jobs
        fetch_result = await call_mcp_tool("fetch_job_data", {
            "count": job_count,
            "out_path": f"jobs_{session_id}.json"
        })
        
        if fetch_result.get("status") != "success":
            sessions[session_id]["job_fetch_status"] = "error"
            sessions[session_id]["job_fetch_error"] = fetch_result.get("error", "Unknown error")
            return
        
        sessions[session_id]["jobs_file"] = f"jobs_{session_id}.json"
        sessions[session_id]["job_fetch_status"] = "populating"
        
        # Step 2: Populate MongoDB
        populate_result = await call_mcp_tool("populate_mongodb", {
            "out_path": f"jobs_{session_id}.json"
        })
        
        if populate_result.get("status") == "success":
            sessions[session_id]["job_fetch_status"] = "completed"
            sessions[session_id]["total_jobs"] = populate_result.get("total_jobs", 0)
            logger.info(f"[{session_id}] Background job fetching completed")
        else:
            sessions[session_id]["job_fetch_status"] = "completed_no_mongo"
            sessions[session_id]["total_jobs"] = fetch_result.get("fetched", 0)
            logger.info(f"[{session_id}] Jobs fetched but MongoDB population failed")
        
    except Exception as e:
        logger.exception(f"[{session_id}] Error in background job fetching: {e}")
        sessions[session_id]["job_fetch_status"] = "error"
        sessions[session_id]["job_fetch_error"] = str(e)

# HTML Frontend
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Application Assistant</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }
        
        .upload-section {
            text-align: center;
            padding: 40px 20px;
            border: 3px dashed #667eea;
            border-radius: 8px;
            background: #f8f9ff;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .upload-section:hover {
            background: #f0f3ff;
            border-color: #764ba2;
        }
        
        .upload-section.drag-over {
            background: #e8ecff;
            border-color: #667eea;
            transform: scale(1.02);
        }
        
        .upload-icon {
            font-size: 3em;
            margin-bottom: 15px;
        }
        
        input[type="file"] {
            display: none;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 25px;
            font-size: 16px;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            font-weight: 600;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            margin: 5px;
        }
        
        .status-parsing { background: #fef3c7; color: #92400e; }
        .status-fetching { background: #dbeafe; color: #1e3a8a; }
        .status-completed { background: #d1fae5; color: #065f46; }
        .status-error { background: #fee2e2; color: #991b1b; }
        
        .resume-info {
            background: #f0f3ff;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }
        
        .resume-info h3 {
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .job-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .job-card {
            background: white;
            border: 2px solid #e5e7eb;
            border-radius: 12px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .job-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.3);
            transform: translateY(-3px);
        }
        
        .job-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: linear-gradient(90deg, #667eea, #764ba2);
        }
        
        .job-title {
            font-size: 1.3em;
            font-weight: 700;
            color: #1f2937;
            margin-bottom: 8px;
        }
        
        .job-company {
            color: #6b7280;
            font-size: 1.1em;
            margin-bottom: 5px;
        }
        
        .job-location {
            color: #9ca3af;
            font-size: 0.9em;
            margin-bottom: 10px;
        }
        
        .match-score {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            margin-top: 10px;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1000;
            overflow-y: auto;
            padding: 20px;
        }
        
        .modal-content {
            background: white;
            max-width: 800px;
            margin: 50px auto;
            border-radius: 12px;
            padding: 30px;
            position: relative;
        }
        
        .modal-close {
            position: absolute;
            top: 20px;
            right: 20px;
            font-size: 2em;
            cursor: pointer;
            color: #6b7280;
            transition: color 0.2s;
        }
        
        .modal-close:hover {
            color: #991b1b;
        }
        
        .job-description {
            color: #4b5563;
            line-height: 1.6;
            margin: 20px 0;
            white-space: pre-wrap;
        }
        
        .cover-letter-section {
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }
        
        .cover-letter-text {
            background: white;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #e5e7eb;
            white-space: pre-wrap;
            line-height: 1.8;
            font-family: 'Georgia', serif;
            color: #1f2937;
            margin-top: 15px;
        }
        
        .loading-spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f4f6;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .progress-section {
            display: flex;
            justify-content: space-around;
            margin: 30px 0;
        }
        
        .progress-item {
            text-align: center;
            flex: 1;
        }
        
        .progress-icon {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .progress-label {
            font-weight: 600;
            color: #4b5563;
        }
        
        .hidden {
            display: none;
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .info-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        
        .info-label {
            color: #6b7280;
            font-size: 0.85em;
            margin-bottom: 5px;
        }
        
        .info-value {
            color: #1f2937;
            font-size: 1.2em;
            font-weight: 700;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Job Application Assistant</h1>
            <p>Upload your resume and let AI find your perfect match</p>
        </div>
        
        <!-- Step 1: Upload Resume -->
        <div class="card" id="uploadCard">
            <h2>📄 Upload Your Resume</h2>
            <div class="upload-section" id="uploadSection" onclick="document.getElementById('resumeFile').click()">
                <div class="upload-icon">📤</div>
                <h3>Click or drag to upload your resume</h3>
                <p>Supports PDF, DOCX, and TXT files</p>
                <input type="file" id="resumeFile" accept=".pdf,.docx,.doc,.txt" onchange="handleResumeUpload(event)">
            </div>
            
            <div id="progressSection" class="progress-section hidden">
                <div class="progress-item">
                    <div class="progress-icon">📄</div>
                    <div class="progress-label">Resume Parsing</div>
                    <div id="resumeStatus" class="status-badge status-parsing">Processing...</div>
                </div>
                <div class="progress-item">
                    <div class="progress-icon">🔍</div>
                    <div class="progress-label">Job Fetching</div>
                    <div id="jobFetchStatus" class="status-badge status-fetching">Searching...</div>
                </div>
                <div class="progress-item">
                    <div class="progress-icon">🎯</div>
                    <div class="progress-label">Matching</div>
                    <div id="matchStatus" class="status-badge">Waiting...</div>
                </div>
            </div>
        </div>
        
        <!-- Step 2: Resume Info -->
        <div class="card hidden" id="resumeCard">
            <h2>✅ Resume Parsed Successfully</h2>
            <div class="resume-info">
                <h3 id="resumeName">Loading...</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">Skills</div>
                        <div class="info-value" id="skillsCount">0</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Experience</div>
                        <div class="info-value" id="experienceCount">0</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Education</div>
                        <div class="info-value" id="educationCount">0</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Jobs Found</div>
                        <div class="info-value" id="totalJobs">0</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Step 3: Job Recommendations -->
        <div class="card hidden" id="jobsCard">
            <h2>🎯 Recommended Jobs</h2>
            <p style="color: #6b7280; margin-bottom: 20px;">Click on a job to view details and generate a cover letter</p>
            <div id="jobList" class="job-list"></div>
        </div>
    </div>
    
    <!-- Job Details Modal -->
    <div id="jobModal" class="modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeJobModal()">&times;</span>
            <h2 id="modalJobTitle">Job Title</h2>
            <p id="modalJobCompany" style="color: #6b7280; font-size: 1.1em; margin-bottom: 10px;"></p>
            <p id="modalJobLocation" style="color: #9ca3af; margin-bottom: 10px;"></p>
            <div id="modalMatchScore"></div>
            
            <div style="margin: 20px 0;">
                <h3>Job Details</h3>
                <div id="modalJobDescription" class="job-description"></div>
            </div>
            
            <div style="margin: 20px 0;">
                <button class="btn" onclick="generateCoverLetter()" id="generateBtn">
                    ✨ Generate Cover Letter
                </button>
            </div>
            
            <div id="coverLetterSection" class="cover-letter-section hidden">
                <h3>📝 Your Cover Letter</h3>
                <div id="coverLetterText" class="cover-letter-text"></div>
                <button class="btn" onclick="downloadCoverLetter()" style="margin-top: 15px;">
                    📥 Download as Text
                </button>
                <button class="btn" onclick="openInNewTab()" style="margin-top: 15px; margin-left: 10px;">
                    🔗 Open in New Tab
                </button>
            </div>
        </div>
    </div>
    
    <script>
        let sessionId = null;
        let parsedResume = null;
        let matchedJobs = [];
        let currentJob = null;
        let currentCoverLetter = null;
        let pollInterval = null;
        
        // Drag and drop
        const uploadSection = document.getElementById('uploadSection');
        
        uploadSection.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadSection.classList.add('drag-over');
        });
        
        uploadSection.addEventListener('dragleave', () => {
            uploadSection.classList.remove('drag-over');
        });
        
        uploadSection.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadSection.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) {
                document.getElementById('resumeFile').files = e.dataTransfer.files;
                handleResumeUpload({target: {files: [file]}});
            }
        });
        
        async function handleResumeUpload(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            // Show progress section
            document.getElementById('progressSection').classList.remove('hidden');
            document.getElementById('uploadSection').style.display = 'none';
            
            // Create session and upload resume
            const formData = new FormData();
            formData.append('resume', file);
            
            try {
                const response = await fetch('/api/upload-resume', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.status === 'success') {
                    sessionId = result.session_id;
                    parsedResume = result.parsed_resume;
                    
                    // Update resume status
                    updateStatus('resumeStatus', 'Completed', 'completed');
                    
                    // Show resume info
                    displayResumeInfo(result.parsed_resume);
                    
                    // Start polling for job fetch status
                    startPolling();
                } else {
                    updateStatus('resumeStatus', 'Error', 'error');
                    alert('Failed to parse resume: ' + result.error);
                }
            } catch (error) {
                updateStatus('resumeStatus', 'Error', 'error');
                alert('Error uploading resume: ' + error.message);
            }
        }
        
        function updateStatus(elementId, text, statusClass) {
            const element = document.getElementById(elementId);
            element.textContent = text;
            element.className = 'status-badge status-' + statusClass;
        }
        
        function displayResumeInfo(resume) {
            document.getElementById('resumeCard').classList.remove('hidden');
            document.getElementById('resumeName').textContent = resume.name || 'Unknown';
            document.getElementById('skillsCount').textContent = (resume.skills || []).length;
            document.getElementById('experienceCount').textContent = (resume.experience || []).length;
            document.getElementById('educationCount').textContent = (resume.education || []).length;
        }
        
        async function startPolling() {
            pollInterval = setInterval(async () => {
                try {
                    const response = await fetch('/api/status/' + sessionId);
                    const status = await response.json();
                    
                    // Update job fetch status
                    if (status.job_fetch_status === 'fetching') {
                        updateStatus('jobFetchStatus', 'Fetching...', 'fetching');
                    } else if (status.job_fetch_status === 'populating') {
                        updateStatus('jobFetchStatus', 'Populating DB...', 'fetching');
                    } else if (status.job_fetch_status === 'completed' || status.job_fetch_status === 'completed_no_mongo') {
                        updateStatus('jobFetchStatus', 'Completed', 'completed');
                        document.getElementById('totalJobs').textContent = status.total_jobs || 0;
                        
                        // Stop polling and start matching
                        clearInterval(pollInterval);
                        await matchJobs();
                    } else if (status.job_fetch_status === 'error') {
                        updateStatus('jobFetchStatus', 'Error', 'error');
                        clearInterval(pollInterval);
                    }
                } catch (error) {
                    console.error('Polling error:', error);
                }
            }, 1000);
        }
        
        async function matchJobs() {
            updateStatus('matchStatus', 'Matching...', 'fetching');
            
            try {
                const response = await fetch('/api/match-jobs/' + sessionId, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({top_k: 6})
                });
                
                const result = await response.json();
                
                if (result.status === 'success') {
                    updateStatus('matchStatus', 'Completed', 'completed');
                    matchedJobs = result.matches;
                    displayJobs(result.matches);
                } else {
                    updateStatus('matchStatus', 'Error', 'error');
                    alert('Failed to match jobs: ' + result.error);
                }
            } catch (error) {
                updateStatus('matchStatus', 'Error', 'error');
                alert('Error matching jobs: ' + error.message);
            }
        }
        
        function displayJobs(jobs) {
            document.getElementById('jobsCard').classList.remove('hidden');
            const jobList = document.getElementById('jobList');
            
            jobList.innerHTML = jobs.map((match, index) => {
                const job = match;
                const title = job.jobTitle || job.title || 'Unknown Position';
                const company = job.companyName || job.company || 'Unknown Company';
                const location = job.jobGeo || job.location || job.job_location || 'Location not specified';
                const similarity = ((job.similarity || 0) * 100).toFixed(1);
                
                return `
                    <div class="job-card" onclick="showJobDetails(${index})">
                        <div class="job-title">${title}</div>
                        <div class="job-company">🏢 ${company}</div>
                        <div class="job-location">📍 ${location}</div>
                        <div class="match-score">✨ ${similarity}% Match</div>
                    </div>
                `;
            }).join('');
        }
        
        function showJobDetails(index) {
            currentJob = matchedJobs[index];
            const job = currentJob;
            
            document.getElementById('modalJobTitle').textContent = job.jobTitle || job.title || 'Unknown Position';
            document.getElementById('modalJobCompany').textContent = '🏢 ' + (job.companyName || job.company || 'Unknown Company');
            document.getElementById('modalJobLocation').textContent = '📍 ' + (job.jobGeo || job.location || job.job_location || 'Location not specified');
            
            const similarity = ((job.similarity || 0) * 100).toFixed(1);
            document.getElementById('modalMatchScore').innerHTML = `<div class="match-score">✨ ${similarity}% Match</div>`;
            
            const description = job.jobDescription || job.description || job.jobExcerpt || 'No description available';
            document.getElementById('modalJobDescription').textContent = description;
            
            // Reset cover letter section
            document.getElementById('coverLetterSection').classList.add('hidden');
            document.getElementById('generateBtn').disabled = false;
            document.getElementById('generateBtn').innerHTML = '✨ Generate Cover Letter';
            
            document.getElementById('jobModal').style.display = 'block';
        }
        
        function closeJobModal() {
            document.getElementById('jobModal').style.display = 'none';
        }
        
        async function generateCoverLetter() {
            const btn = document.getElementById('generateBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="loading-spinner"></span> Generating...';
            
            try {
                const response = await fetch('/api/generate-cover-letter/' + sessionId, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({job: currentJob})
                });
                
                const result = await response.json();
                
                if (result.status === 'success') {
                    currentCoverLetter = result.cover_letter;
                    document.getElementById('coverLetterText').textContent = result.cover_letter;
                    document.getElementById('coverLetterSection').classList.remove('hidden');
                    btn.innerHTML = '✅ Generated!';
                } else {
                    alert('Failed to generate cover letter: ' + result.error);
                    btn.disabled = false;
                    btn.innerHTML = '✨ Generate Cover Letter';
                }
            } catch (error) {
                alert('Error generating cover letter: ' + error.message);
                btn.disabled = false;
                btn.innerHTML = '✨ Generate Cover Letter';
            }
        }
        
        function downloadCoverLetter() {
            const blob = new Blob([currentCoverLetter], {type: 'text/plain'});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'cover_letter.txt';
            a.click();
            window.URL.revokeObjectURL(url);
        }
        
        function openInNewTab() {
            const newWindow = window.open();
            newWindow.document.write('<html><head><title>Cover Letter</title>');
            newWindow.document.write('<style>body{font-family:Georgia,serif;max-width:800px;margin:50px auto;padding:20px;line-height:1.8;}</style>');
            newWindow.document.write('</head><body>');
            newWindow.document.write('<pre style="white-space:pre-wrap;">' + currentCoverLetter + '</pre>');
            newWindow.document.write('</body></html>');
            newWindow.document.close();
        }
        
        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('jobModal');
            if (event.target === modal) {
                closeJobModal();
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main HTML page."""
    return HTML_TEMPLATE

@app.post("/api/upload-resume")
async def upload_resume(resume: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    Upload and parse resume, then start background job fetching.
    This acts as the main "agent coordinator".
    """
    # Create session
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "created_at": datetime.now(),
        "job_fetch_status": "pending",
        "resume_status": "parsing"
    }
    
    # Save uploaded file
    temp_path = Path(f"temp_{session_id}_{resume.filename}")
    try:
        with open(temp_path, "wb") as f:
            f.write(await resume.read())
        
        # Parse resume (Agent 1)
        logger.info(f"[{session_id}] Parsing resume")
        parse_result = await call_mcp_tool("parse_resume", {
            "resume_path": str(temp_path.absolute())
        })
        
        if parse_result.get("status") != "success":
            return JSONResponse({
                "status": "error",
                "error": "resume_parse_failed",
                "detail": parse_result.get("error", "Unknown error")
            })
        
        sessions[session_id]["parsed_resume"] = parse_result.get("parsed")
        sessions[session_id]["resume_status"] = "completed"
        
        # Start background job fetching (Agent 2)
        background_tasks.add_task(background_job_fetching, session_id, 50)
        
        return JSONResponse({
            "status": "success",
            "session_id": session_id,
            "parsed_resume": parse_result.get("parsed")
        })
        
    except Exception as e:
        logger.exception(f"Error in upload_resume: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        })
    finally:
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()

@app.get("/api/status/{session_id}")
async def get_status(session_id: str):
    """Get the current status of the session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return JSONResponse({
        "resume_status": session.get("resume_status", "unknown"),
        "job_fetch_status": session.get("job_fetch_status", "pending"),
        "total_jobs": session.get("total_jobs", 0),
        "error": session.get("job_fetch_error")
    })

@app.post("/api/match-jobs/{session_id}")
async def match_jobs(session_id: str, request: Request):
    """
    Match jobs to the parsed resume.
    This is called after both agents complete.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    parsed_resume = session.get("parsed_resume")
    jobs_file = session.get("jobs_file", f"jobs_{session_id}.json")
    
    if not parsed_resume:
        return JSONResponse({
            "status": "error",
            "error": "no_parsed_resume"
        })
    
    data = await request.json()
    top_k = data.get("top_k", 6)
    
    logger.info(f"[{session_id}] Matching jobs")
    
    # Call matching tool
    match_result = await call_mcp_tool("match_jobs_to_resume", {
        "resume": parsed_resume,
        "jobs_source": "file",
        "jobs_file": jobs_file,
        "top_k": top_k,
        "min_similarity": 0.2
    })
    
    if match_result.get("status") == "success":
        sessions[session_id]["matches"] = match_result.get("matches", [])
    
    return JSONResponse(match_result)

@app.post("/api/generate-cover-letter/{session_id}")
async def generate_cover_letter_endpoint(session_id: str, request: Request):
    """Generate cover letter for a specific job."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    parsed_resume = session.get("parsed_resume")
    
    if not parsed_resume:
        return JSONResponse({
            "status": "error",
            "error": "no_parsed_resume"
        })
    
    data = await request.json()
    job = data.get("job")
    
    logger.info(f"[{session_id}] Generating cover letter")
    
    # Call cover letter generation tool
    result = await call_mcp_tool("create_cover_letter", {
        "resume": parsed_resume,
        "job": job
    })
    
    return JSONResponse(result)

if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print("🚀 Starting Job Application Assistant")
    print("=" * 70)
    print(f"\n📱 Web Interface: http://localhost:8000")
    print(f"🔧 MCP Server: {MCP_SERVER_URL}")
    print("\n⚠️  Make sure the MCP server is running:")
    print("   python server/mcp_pipeline_server.py")
    print("\n" + "=" * 70 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
