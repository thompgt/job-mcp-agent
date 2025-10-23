# 🧠 CareerCraft Agent: Technical Workflow & Objectives

CareerCraft is a context-aware job application automation agent that leverages LangChain and the Model Context Protocol (MCP) to intelligently match resumes with job postings and generate personalized cover letters.

---

## 🎯 Agent Objectives

The CareerCraft agent is designed to:

- Automate the end-to-end job application process for college students and early professionals.
- Contextually match resumes to job postings using semantic similarity.
- Generate tailored cover letters using large language models.
- Integrate real-time job data from public APIs.
- Operate within a multi-agent orchestration framework using MCP.

---

## ⚙️ Technical Workflow

### 1. 🔍 Job Retrieval
- **Source:** RapidAPI, Handshake, Indeed
- **Format:** Structured JSON with fields like `title`, `company`, `location`, `type`, `description`
- **Purpose:** Populate the agent’s job pool with real-time listings

### 2. 📄 Resume Parsing
- **Tools:** SpaCy + Regex
- **Output:** Structured resume fields (skills, experience, education)
- **Purpose:** Extract semantic features for matching

### 3. 🧠 Contextual Matching Engine
- **Method:** Sentence-transformers for embedding generation
- **Matching:** Cosine similarity between resume and job description embeddings
- **Purpose:** Identify high-relevance job opportunities

### 4. ✍️ Cover Letter Generation
- **Framework:** LangChain
- **Model:** GPT-based LLMs
- **Personalization:** Inject resume features and job context into prompt templates
- **Purpose:** Produce coherent, customized cover letters

### 5. 🕸️ Agent Orchestration
- **Protocol:** Model Context Protocol (MCP)
- **Role:** Coordinate sub-agents for retrieval, parsing, matching, and generation
- **Interface:** Streamlit frontend for user interaction

---

## 📏 Evaluation Metrics

- **Relevance Accuracy:** Human-labeled job–resume match scores
- **Text Quality:** Coherence and alignment via cosine similarity and user feedback
- **Performance:** Latency and automation completeness

---

## 🧪 Future Enhancements


## Running the MCP server (dev)

This repository contains a minimal, development MCP server implemented with FastAPI. The server uses an in-memory queue and is suitable for local testing and development.

Prerequisites
- Python 3.10+
- A working internet connection to install dependencies

Windows (cmd.exe) quick start

1. Create and activate a virtual environment:

```cmd
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:

```cmd
pip install -r requirements.txt
```

3. Start the server (uvicorn):

```cmd
uvicorn server.app.main:app --reload --port 8000
```

4. Try the API endpoints (example using curl/powershell or a browser):

- Trigger ingestion (calls `get_data.fetch_jobs`):

```cmd
curl -X POST http://127.0.0.1:8000/api/ingest
```

- List jobs:

```cmd
curl http://127.0.0.1:8000/api/jobs
```

Notes
- The in-memory queue is not persistent. For production, use Redis/RabbitMQ and a real DB (Postgres).
- The ingest endpoint calls `get_data.fetch_jobs()` which may perform HTTP requests; tests use a mocked fetch to avoid network I/O.

Running tests

With the virtualenv active and dependencies installed, run:

```cmd
pytest -q
```
