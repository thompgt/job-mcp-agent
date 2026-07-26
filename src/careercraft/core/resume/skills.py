"""Skill vocabulary and extraction.

Extraction is plain regex over a curated vocabulary. That is deliberate: it
means skills work in the base install, with no spaCy and no model download.
v1 routed this through a spaCy ``PhraseMatcher``, which produced the same
answers but made a 500 MB dependency mandatory for a case-insensitive
substring search.

The vocabulary maps a canonical name to its aliases, so ``Postgres``,
``PostgreSQL`` and ``psql`` all normalise to one skill and matching does not
double-count them.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

#: canonical name -> aliases (the canonical name is always matched too)
SKILL_VOCABULARY: dict[str, tuple[str, ...]] = {
    # languages
    "Python": ("python", "python3"),
    "Java": ("java",),
    "JavaScript": ("javascript", "js", "es6"),
    "TypeScript": ("typescript", "ts"),
    "C++": ("c++", "cpp"),
    "C": ("c",),
    "C#": ("c#", "csharp"),
    "Go": ("go", "golang"),
    "Rust": ("rust",),
    "Ruby": ("ruby",),
    "PHP": ("php",),
    "Swift": ("swift",),
    "Kotlin": ("kotlin",),
    "Scala": ("scala",),
    "R": ("r",),
    "MATLAB": ("matlab",),
    "SQL": ("sql",),
    "Bash": ("bash", "shell scripting", "zsh"),
    "HTML": ("html", "html5"),
    "CSS": ("css", "css3", "sass", "scss"),
    # data / ML
    "pandas": ("pandas",),
    "NumPy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn", "scikit learn"),
    "TensorFlow": ("tensorflow", "keras"),
    "PyTorch": ("pytorch", "torch"),
    "Hugging Face": ("hugging face", "huggingface", "transformers"),
    "LangChain": ("langchain",),
    "Machine Learning": ("machine learning", "ml models", "supervised learning"),
    "Deep Learning": ("deep learning", "neural networks"),
    "NLP": ("nlp", "natural language processing"),
    "Computer Vision": ("computer vision", "opencv"),
    "LLMs": ("llm", "llms", "large language models", "prompt engineering", "rag"),
    "Statistics": ("statistics", "statistical analysis", "hypothesis testing"),
    "Data Analysis": ("data analysis", "data analytics", "exploratory data analysis", "eda"),
    "Data Visualization": ("data visualization", "matplotlib", "seaborn", "plotly", "d3.js"),
    "Tableau": ("tableau",),
    "Power BI": ("power bi", "powerbi"),
    "Excel": ("excel", "vba", "pivot tables"),
    # data engineering
    "Spark": ("spark", "pyspark", "apache spark"),
    "Hadoop": ("hadoop", "mapreduce"),
    "Airflow": ("airflow", "apache airflow"),
    "dbt": ("dbt",),
    "Kafka": ("kafka", "apache kafka"),
    "ETL": ("etl", "elt", "data pipelines"),
    "Snowflake": ("snowflake",),
    "BigQuery": ("bigquery",),
    "Redshift": ("redshift",),
    "Databricks": ("databricks",),
    # databases
    "PostgreSQL": ("postgresql", "postgres", "psql"),
    "MySQL": ("mysql", "mariadb"),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch", "opensearch"),
    "DynamoDB": ("dynamodb",),
    # cloud / infra
    "AWS": ("aws", "amazon web services", "ec2", "s3", "lambda"),
    "GCP": ("gcp", "google cloud"),
    "Azure": ("azure", "microsoft azure"),
    "Docker": ("docker", "containerization"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "Linux": ("linux", "unix"),
    "CI/CD": ("ci/cd", "cicd", "continuous integration", "github actions", "jenkins", "gitlab ci"),
    "Git": ("git", "github", "gitlab", "version control"),
    "Ansible": ("ansible",),
    "Nginx": ("nginx",),
    # web / app
    "React": ("react", "react.js", "reactjs"),
    "Next.js": ("next.js", "nextjs"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Angular": ("angular", "angularjs"),
    "Node.js": ("node.js", "nodejs", "node"),
    "Django": ("django",),
    "Flask": ("flask",),
    "FastAPI": ("fastapi",),
    "Spring": ("spring", "spring boot"),
    "GraphQL": ("graphql",),
    "REST APIs": ("rest api", "rest apis", "restful", "rest"),
    "gRPC": ("grpc",),
    "Tailwind CSS": ("tailwind", "tailwind css"),
    # practice
    "Testing": ("unit testing", "pytest", "jest", "test automation", "tdd"),
    "Agile": ("agile", "scrum", "kanban"),
    "Microservices": ("microservices",),
    "System Design": ("system design", "distributed systems"),
    "Security": ("security", "penetration testing", "oauth", "cryptography"),
    "Technical Writing": ("technical writing", "documentation"),
    # finance / quant, since this codebase leans that way
    "Financial Modeling": ("financial modeling", "dcf", "valuation"),
    "Quantitative Analysis": ("quantitative analysis", "quantitative research", "econometrics"),
    "Bloomberg": ("bloomberg", "bloomberg terminal"),
    "Risk Management": ("risk management", "var modeling"),
}

#: Terms so short they match inside ordinary prose ("go to", "r&d", "c of").
#: These are only accepted when they stand alone in a delimited list, which is
#: how skills sections are actually written.
_AMBIGUOUS = frozenset({"c", "r", "go", "js", "ts", "ml", "rest", "node", "spring", "swift"})

#: A single delimiter character. Kept one char wide so it can sit inside a
#: look-behind, which Python requires to be fixed-width.
_DELIM_CLASS = r"[,;|/•\t\n·]"


@lru_cache(maxsize=8)
def _compiled(extra_terms: tuple[str, ...] = ()) -> list[tuple[str, re.Pattern[str]]]:
    """Build one compiled pattern per canonical skill, longest alias first."""
    vocab: dict[str, list[str]] = {k: [k, *v] for k, v in SKILL_VOCABULARY.items()}
    for term in extra_terms:
        vocab.setdefault(term, [term])

    compiled: list[tuple[str, re.Pattern[str]]] = []
    for canonical, aliases in vocab.items():
        alts = sorted({a.lower() for a in aliases}, key=len, reverse=True)
        safe, risky = [], []
        for alias in alts:
            (risky if alias in _AMBIGUOUS else safe).append(re.escape(alias))
        parts = []
        if safe:
            parts.append(rf"(?<![A-Za-z0-9+#_-])(?:{'|'.join(safe)})(?![A-Za-z0-9+#_-])")
        if risky:
            group = "|".join(risky)
            parts.append(
                rf"(?:^|(?<={_DELIM_CLASS}))[ ]*(?:{group})[ ]*(?={_DELIM_CLASS}|$)"
            )
        compiled.append((canonical, re.compile("|".join(parts), re.IGNORECASE | re.MULTILINE)))
    return compiled


def load_extra_terms(path: Path | None) -> tuple[str, ...]:
    """Read one extra skill per line from ``path``. Missing file is not fatal."""
    if path is None or not Path(path).is_file():
        return ()
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ()
    return tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def extract_skills(text: str, *, extra_terms: tuple[str, ...] = ()) -> list[str]:
    """Return the canonical skills mentioned in ``text``, sorted."""
    if not text:
        return []
    found = {canonical for canonical, rx in _compiled(extra_terms) if rx.search(text)}
    return sorted(found, key=str.lower)


def skill_overlap(resume_skills: list[str], job_text: str) -> tuple[list[str], list[str]]:
    """Split the skills a posting mentions into ones the resume has and hasn't.

    Returns ``(matched, missing)``. ``missing`` is the genuinely useful half —
    it tells the candidate what to address in a cover letter.
    """
    job_skills = set(extract_skills(job_text))
    have = {s.lower() for s in resume_skills}
    matched = sorted((s for s in job_skills if s.lower() in have), key=str.lower)
    missing = sorted((s for s in job_skills if s.lower() not in have), key=str.lower)
    return matched, missing
