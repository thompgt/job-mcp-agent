"""Run fetch_data then populate_database via the in-process FastMCP client.

This script is safe to run from anywhere on Windows: it inserts the project root
into sys.path so `import server` works.
"""
import sys
from pathlib import Path
import dotenv
dotenv.load_dotenv()

# ensure project root (parent of scripts/) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import argparse
import asyncio
from fastmcp import Client
from server.fastmcp_server import mcp


async def main(count: int, out_path: str, resume_path: str | None):
    async with Client(mcp) as client:
        print("Calling fetch_data tool...")
        fetch_res = await client.call_tool("fetch_data", {"count": count, "out_path": out_path})
        print("fetch_data ->", fetch_res)

        out_path_val = None
        try:
            out_path_val = fetch_res.data.get("out_path")
        except Exception:
            try:
                out_path_val = fetch_res.structured_content.get("out_path")
            except Exception:
                out_path_val = None

        final_out = out_path_val or out_path
        print("Calling populate_database tool... (out_path=", final_out, ")")
        pop_res = await client.call_tool("populate_database", {"out_path": final_out})
        print("populate_database ->", pop_res)

        if resume_path:
            print("Calling parse_resume tool for:", resume_path)
            parse_res = await client.call_tool("parse_resume", {"resume_path": resume_path})
            print("parse_resume ->", parse_res)
            # extract parsed resume dict
            parsed_resume = None
            try:
                parsed_resume = parse_res.data.get("parsed")
            except Exception:
                try:
                    parsed_resume = parse_res.structured_content.get("parsed")
                except Exception:
                    parsed_resume = None

            # Load the fetched jobs file and pick the first job to generate a cover letter
            if parsed_resume is not None:
                import json
                from pathlib import Path
                p = Path(final_out)
                jobs = []
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
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
                    except Exception:
                        jobs = []

                if jobs:
                    first_job = jobs[0]
                    print("Calling generate_cover_letter tool for first job: ", first_job.get("title") or first_job.get("jobTitle") or first_job.get("name"))
                    gen_res = await client.call_tool("generate_cover_letter_tool", {"resume": parsed_resume, "job": first_job})
                    print("generate_cover_letter_tool ->", gen_res)
                else:
                    print("No jobs available in fetched file to generate cover letter.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5, help="how many jobs to fetch")
    parser.add_argument("--out", type=str, default="jobs.json", help="output file path for fetched jobs")
    parser.add_argument("--resume", type=str, default=None, help="optional resume file path to parse (pdf/docx/txt)")
    args = parser.parse_args()
    resume_path_= "C:\\Users\\thoma\\Downloads\\ai-final-project\\job-mcp-agent\\Thomas_Pequegnot_Resume.pdf"
    asyncio.run(main(count=args.count, out_path=args.out, resume_path=resume_path_))
