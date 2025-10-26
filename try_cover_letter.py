from server.app.services.resume_parser import parse_resume_file
from server.app.services.cover_letter_generator import generate_cover_letter

# 1. point this to a real resume PDF/DOCX/TXT you have locally
RESUME_PATH = "/Users/peterk/Downloads/kaloev_peter_resume.pdf"

# 2. make a fake job posting (mimic what your queue stores from fetch_jobs)
job_posting = {
    "title": "Data Analyst Intern",
    "companyName": "Acme Insights",
    "location": "New York, NY",
    "description": (
        "We're looking for an intern who can analyze large datasets, build dashboards, "
        "and communicate insights to business stakeholders. SQL and Python required. "
        "Experience with pandas preferred."
    ),
}

def main():
    # parse the resume into structured fields
    resume_data = parse_resume_file(RESUME_PATH)

    # generate the cover letter text
    letter = generate_cover_letter(resume_data, job_posting)

    print("===== RESUME PARSED DATA (debug) =====")
    for k, v in resume_data.items():
        print(f"{k}: {type(v)} -> {v if isinstance(v, (str, int)) else ''}")

    print("\n===== GENERATED COVER LETTER =====\n")
    print(letter)
    print("\n==================================\n")

if __name__ == "__main__":
    main()
