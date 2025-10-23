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

- Feedback loop for iterative resume improvement
- ATS compatibility and autofill integration
- International job market support
