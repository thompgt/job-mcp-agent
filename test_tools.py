"""Test MCP Pipeline Server Tools using FastMCP Client."""
import asyncio
from fastmcp import Client
import json

async def test_server():
    print("=" * 70)
    print("Testing MCP Pipeline Server")
    print("=" * 70)
    
    try:
        # Connect to the server
        async with Client("http://127.0.0.1:8002/mcp") as client:
            print("✓ Connected to MCP server\n")
            
            # Test 1: List all available tools
            print("-" * 70)
            print("TEST 1: Listing Available Tools")
            print("-" * 70)
            tools = await client.list_tools()
            for i, tool in enumerate(tools, 1):
                print(f"\n{i}. {tool.name}")
                print(f"   Description: {tool.description[:100]}...")
            
            print(f"\n✓ Found {len(tools)} tools\n")
            
            # Test 2: Fetch jobs
            print("-" * 70)
            print("TEST 2: Fetching Jobs")
            print("-" * 70)
            call_result = await client.call_tool("fetch_job_data", {
                "count": 5,
                "out_path": "test_jobs.json"
            })
            
            # Extract the actual result from CallToolResult
            if hasattr(call_result, 'content'):
                # Handle CallToolResult object
                result = call_result.content[0].text if call_result.content else {}
                if isinstance(result, str):
                    result = json.loads(result)
            else:
                result = call_result
            
            print(json.dumps(result, indent=2))
            
            if result.get("status") == "success":
                print(f"\n✓ Successfully fetched {result.get('fetched')} jobs")
            else:
                print(f"\n✗ Failed: {result.get('error')}")
            
            # Test 3: Populate MongoDB (optional - comment out if no MongoDB)
            print("\n" + "-" * 70)
            print("TEST 3: Populating MongoDB")
            print("-" * 70)
            try:
                call_result = await client.call_tool("populate_mongodb", {
                    "out_path": "test_jobs.json"
                })
                
                # Extract result
                if hasattr(call_result, 'content'):
                    result = call_result.content[0].text if call_result.content else {}
                    if isinstance(result, str):
                        result = json.loads(result)
                else:
                    result = call_result
                
                print(json.dumps(result, indent=2))
                
                if result.get("status") == "success":
                    print(f"\n✓ Inserted: {result.get('inserted')}, "
                          f"Existing: {result.get('existing')}, "
                          f"Errors: {result.get('errors')}")
                else:
                    print(f"\n✗ Failed: {result.get('error')}")
            except Exception as e:
                print(f"⚠ Skipped (MongoDB not available): {e}")
            
            # Test 4: Parse resume
            print("\n" + "-" * 70)
            print("TEST 4: Parsing Resume")
            print("-" * 70)
            resume_path = input("\nEnter path to your resume file (or press Enter to skip): ").strip()
            
            # Remove quotes if user copied path with quotes
            resume_path = resume_path.strip('"').strip("'")
            
            # Convert to absolute path if relative
            if resume_path:
                from pathlib import Path
                resume_file = Path(resume_path)
                
                # If relative path, make it absolute
                if not resume_file.is_absolute():
                    resume_file = Path.cwd() / resume_file
                
                resume_path = str(resume_file)
                print(f"Using resume path: {resume_path}")
                
                if not resume_file.exists():
                    print(f"\n✗ File not found: {resume_path}")
                    print(f"   Current directory: {Path.cwd()}")
                    print(f"   Available PDF/DOCX files:")
                    found_files = False
                    for f in Path.cwd().glob("*.pdf"):
                        print(f"     - {f.name}")
                        found_files = True
                    for f in Path.cwd().glob("*.docx"):
                        print(f"     - {f.name}")
                        found_files = True
                    if not found_files:
                        print(f"     (none found)")
                    resume_path = None
            
            if resume_path:
                call_result = await client.call_tool("parse_resume", {
                    "resume_path": resume_path
                })
                
                # Extract result
                if hasattr(call_result, 'content'):
                    result = call_result.content[0].text if call_result.content else {}
                    if isinstance(result, str):
                        result = json.loads(result)
                else:
                    result = call_result
                
                if result.get("status") == "success":
                    parsed = result.get("parsed", {})
                    print(f"\n✓ Resume parsed successfully!")
                    print(f"   Name: {parsed.get('name', 'Unknown')}")
                    print(f"   Skills: {len(parsed.get('skills', []))}")
                    print(f"   Experience: {len(parsed.get('experience', []))}")
                    print(f"   Education: {len(parsed.get('education', []))}")
                    
                    # Test 5: Match jobs to resume
                    print("\n" + "-" * 70)
                    print("TEST 5: Matching Jobs to Resume")
                    print("-" * 70)
                    call_result = await client.call_tool("match_jobs_to_resume", {
                        "resume": parsed,
                        "jobs_source": "file",
                        "jobs_file": "test_jobs.json",
                        "top_k": 5
                    })
                    
                    # Extract result
                    if hasattr(call_result, 'content'):
                        result = call_result.content[0].text if call_result.content else {}
                        if isinstance(result, str):
                            result = json.loads(result)
                    else:
                        result = call_result
                    
                    if result.get("status") == "success":
                        matches = result.get("matches", [])
                        print(f"\n✓ Found {len(matches)} matching jobs:")
                        
                        for i, match in enumerate(matches[:3], 1):
                            job = match.get("job", {})
                            similarity = match.get("similarity", 0)
                            print(f"\n   {i}. {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}")
                            print(f"      Similarity: {similarity:.1%}")
                            print(f"      Location: {job.get('location', 'Unknown')}")
                    else:
                        print(f"\n✗ Matching failed: {result.get('error')}")
                    
                    # Test 6: Generate cover letter for first match
                    print("\n" + "-" * 70)
                    print("TEST 6: Generating Cover Letter")
                    print("-" * 70)
                    generate = input("\nGenerate cover letter for top match? (y/n): ").strip().lower()
                    
                    if generate == 'y' and result.get("matches"):
                        first_match = result["matches"][0]
                        first_job = first_match.get("job", {})
                        
                        call_result = await client.call_tool("create_cover_letter", {
                            "resume": parsed,
                            "job": first_job
                        })
                        
                        # Extract result
                        if hasattr(call_result, 'content'):
                            cover_result = call_result.content[0].text if call_result.content else {}
                            if isinstance(cover_result, str):
                                cover_result = json.loads(cover_result)
                        else:
                            cover_result = call_result
                        
                        if cover_result.get("status") == "success":
                            print(f"\n✓ Cover letter generated!")
                            print(f"   Job: {cover_result.get('job_title')} at {cover_result.get('company')}")
                            print(f"   Length: {cover_result.get('letter_length')} characters")
                            print(f"\n   First 300 characters:")
                            print(f"   {cover_result.get('cover_letter', '')[:300]}...")
                        else:
                            print(f"\n✗ Failed: {cover_result.get('error')}")
                    
                    # Test 7: One-step matching from resume path
                    print("\n" + "-" * 70)
                    print("TEST 7: One-Step Match from Resume Path")
                    print("-" * 70)
                    call_result = await client.call_tool("match_jobs_from_resume_path", {
                        "resume_path": resume_path,
                        "jobs_source": "file",
                        "jobs_file": "test_jobs.json",
                        "top_k": 3
                    })
                    
                    # Extract result
                    if hasattr(call_result, 'content'):
                        result = call_result.content[0].text if call_result.content else {}
                        if isinstance(result, str):
                            result = json.loads(result)
                    else:
                        result = call_result
                    
                    if result.get("status") == "success":
                        print(f"\n✓ One-step matching successful!")
                        print(f"   Resume: {result.get('resume_info', {}).get('name', 'Unknown')}")
                        print(f"   Matches: {result.get('matches_count', 0)}")
                    else:
                        print(f"\n✗ Failed: {result.get('error')}")
                        
                else:
                    print(f"\n✗ Failed to parse resume: {result.get('error')}")
                    print(f"   Detail: {result.get('detail', 'N/A')}")
            else:
                print("⏭️  Skipped resume-related tests")
            
            # Test 8: Complete pipeline (optional)
            print("\n" + "-" * 70)
            print("TEST 8: Complete Pipeline")
            print("-" * 70)
            run_pipeline = input("\nRun complete pipeline? (y/n): ").strip().lower()
            
            if run_pipeline == 'y' and resume_path:
                call_result = await client.call_tool("run_complete_pipeline", {
                    "resume_path": resume_path,
                    "job_count": 10,
                    "jobs_file": "pipeline_test.json",
                    "generate_cover_letter_for_first": True
                })
                
                # Extract result
                if hasattr(call_result, 'content'):
                    result = call_result.content[0].text if call_result.content else {}
                    if isinstance(result, str):
                        result = json.loads(result)
                else:
                    result = call_result
                
                print("\nPipeline Results:")
                print(json.dumps(result, indent=2))
            
            print("\n" + "=" * 70)
            print("✓ All tests completed!")
            print("=" * 70)
            
    except Exception as e:
        print(f"\n✗ Error connecting to server: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        print("\nMake sure the server is running:")
        print("  python server/mcp_pipeline_server.py")

if __name__ == "__main__":
    asyncio.run(test_server())