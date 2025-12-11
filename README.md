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


## 🚀 Running the Application

### Prerequisites
- Python 3.10+
- MongoDB (local or Atlas connection)
- Ollama installed and running (for cover letter generation)
- Internet connection for API calls and model download
- Homebrew to simplify installing Python and Git if on MacOS

### Setup Steps

**1. Install Homebrew (optional but convenient):**

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

**2. Install Ollama and Pull Required Models**

Download and install Ollama from [ollama.ai](https://ollama.ai)

Then pull the required model:

```cmd
ollama pull llama3.2:1b
```

To verify Ollama is running:

```cmd
ollama list
```

You should see `llama3.2:1b` in the list of available models.

---

### Quick Start (Recommended)

**Option 1: Using the Launcher Script**

The easiest way to start both the MCP server and web frontend:

```cmd
python launch.py
```

This will:
1. Start the MCP Pipeline Server on port 8002 (`http://127.0.0.1:8002/mcp`)
2. Start the Web Frontend on port 8000 (`http://127.0.0.1:8000`)
3. Automatically open your browser to the application

Both servers run in separate terminal windows. Close those windows to stop the servers.

---

### Manual Setup (If Launcher Doesn't Work)

**Step 1: Create and activate a virtual environment**

```cmd
python -m venv .venv
.venv\Scripts\activate
```

**Step 2: Install dependencies**

```cmd
pip install -r requirements.txt
```

**Step 3: Configure environment variables (optional)**

Create a `.env` file in the project root:

```env
MONGO_URL=mongodb://localhost:27017
# Or for MongoDB Atlas:
# MONGO_USER=your_username
# MONGO_PASS=your_password
```

**Step 4: Start the MCP Server**

Open a terminal and run:

```cmd
python server\mcp_pipeline_server.py
```

The MCP server will start on `http://127.0.0.1:8002/mcp`

**Step 5: Start the Web Frontend**

Open a **second terminal** and run:

```cmd
python web_frontend.py
```

The web frontend will start on `http://127.0.0.1:8000`

**Step 6: Open your browser**

Navigate to `http://127.0.0.1:8000`

---

### Available MCP Tools

The FastMCP server exposes 6 tools:

1. **`fetch_job_data`** - Fetch job listings from API
2. **`populate_mongodb`** - Store jobs in MongoDB with deduplication
3. **`parse_resume`** - Parse resume files (PDF/DOCX/TXT)
4. **`create_cover_letter`** - Generate personalized cover letters
5. **`match_jobs_to_resume`** - Semantic job matching using embeddings
6. **`run_complete_pipeline`** - Orchestrate the full pipeline

---

### Testing the MCP Server Directly

You can test individual MCP tools using curl or the FastMCP client:

```cmd
curl -X POST http://127.0.0.1:8002/mcp ^
  -H "Content-Type: application/json" ^
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"fetch_job_data\",\"arguments\":{\"count\":10}},\"id\":1}"
```

---

### Running Tests

With the virtualenv active and dependencies installed:

```cmd
pytest -q
```

---

### Notes

- **Ollama must be running** for cover letter generation to work. Start Ollama before launching the application.
- MongoDB connection is optional for job fetching but required for job storage and matching from database
- The matching engine will download sentence-transformer models on first run (~90MB)
- Different LLM models can be specified via the `model_name` parameter (default: `llama3.2:1b`)
- For production deployment, use proper process managers and secure MongoDB connections
