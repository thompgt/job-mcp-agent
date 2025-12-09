"""
Intelligent MCP Agent Layer using Ollama Llama 3.2

This agent orchestrates the job application pipeline by:
1. Making autonomous decisions based on candidate profile
2. Adaptively adjusting search parameters
3. Using LLM reasoning to optimize the workflow
4. Providing intelligent recommendations
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastmcp import Client
import ollama

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class JobApplicationAgent:
    """
    Intelligent agent that uses MCP tools with LLM reasoning.
    
    The agent makes autonomous decisions about:
    - How many jobs to fetch based on candidate profile
    - Similarity thresholds for matching
    - Whether to retry with different parameters
    - Which jobs are best fits and why
    """
    
    def __init__(
        self,
        mcp_server_url: str = "http://127.0.0.1:8002/mcp",
        model_name: str = "llama3.2:1b"  # Faster 1B model (3-4x speedup)
    ):
        self.mcp_url = mcp_server_url
        self.model_name = model_name
        self.client = None
        self.available_tools = []
        
    async def __aenter__(self):
        """Initialize MCP client connection."""
        self.client = await Client(self.mcp_url).__aenter__()
        
        # Get available tools from MCP server
        tools = await self.client.list_tools()
        self.available_tools = [
            {"name": tool.name, "description": tool.description}
            for tool in tools
        ]
        logger.info(f"🤖 Agent: Connected to MCP server with {len(self.available_tools)} tools")
        
        return self
        
    async def __aexit__(self, *args):
        """Clean up MCP client connection."""
        if self.client:
            await self.client.__aexit__(*args)
    
    async def execute_job_search(
        self,
        resume_path: str,
        preferences: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Autonomously execute intelligent job search workflow.
        
        The agent will:
        1. Parse and analyze the resume
        2. Use LLM to understand candidate profile
        3. Make intelligent decisions about search parameters
        4. Fetch and match jobs
        5. Provide reasoning for recommendations
        
        Args:
            resume_path: Path to candidate's resume
            preferences: Optional user preferences (job_count, top_k, etc.)
            
        Returns:
            Comprehensive results with agent reasoning
        """
        preferences = preferences or {}
        start_time = datetime.now()
        
        logger.info("=" * 70)
        logger.info("🤖 AGENT: Starting Intelligent Job Search Workflow")
        logger.info("=" * 70)
        
        # Step 1: Parse Resume
        logger.info("\n🚀 OPTIMIZED: Running Steps 1-4 in Parallel...")
        
        jobs_file = f"agent_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # OPTIMIZATION: Parse resume and fetch jobs IN PARALLEL
        parse_task = asyncio.create_task(
            self._call_mcp_tool("parse_resume", {"resume_path": resume_path})
        )
        
        # Use default job count first, we'll adjust if needed
        initial_job_count = preferences.get('job_count', 50)
        fetch_task = asyncio.create_task(
            self._call_mcp_tool("fetch_job_data", {
                "count": initial_job_count,
                "out_path": jobs_file
            })
        )
        
        # Wait for both to complete
        logger.info("   📄 Step 1: Parsing resume...")
        logger.info("   🔍 Step 4: Fetching jobs...")
        parse_result, fetch_result = await asyncio.gather(parse_task, fetch_task)
        
        if parse_result.get("status") != "success":
            return self._error_response("resume_parsing_failed", parse_result)
        
        if fetch_result.get("status") != "success":
            return self._error_response("job_fetch_failed", fetch_result)
        
        parsed_resume = parse_result.get("parsed")
        logger.info(f"✅ Resume parsed: {parsed_resume.get('name', 'Unknown')}")
        logger.info(f"✅ Fetched {fetch_result.get('fetched', 0)} jobs")
        
        # OPTIMIZATION: Populate MongoDB in background (don't wait)
        logger.info("\n💾 STEP 5: Populating MongoDB (background)...")
        asyncio.create_task(
            self._call_mcp_tool("populate_mongodb", {"out_path": jobs_file})
        )
        
        # Step 2: Analyze Candidate Profile with LLM
        logger.info("\n🧠 STEP 2: Analyzing Candidate Profile with LLM...")
        candidate_analysis = await self._analyze_candidate_profile(parsed_resume)
        logger.info(f"📊 Analysis complete:")
        logger.info(f"   - Experience Level: {candidate_analysis['experience_level']}")
        logger.info(f"   - Career Stage: {candidate_analysis['career_stage']}")
        logger.info(f"   - Key Skills: {', '.join(candidate_analysis['top_skills'][:5])}")
        
        # Step 3: Determine Optimal Search Parameters
        logger.info("\n⚙️  STEP 3: Determining Optimal Search Parameters...")
        search_params = await self._determine_search_parameters(
            candidate_analysis,
            preferences
        )
        # Use already fetched job count
        search_params['job_count'] = fetch_result.get('fetched', initial_job_count)
        logger.info(f"🎯 Search Parameters:")
        logger.info(f"   - Jobs fetched: {search_params['job_count']}")
        logger.info(f"   - Similarity threshold: {search_params['min_similarity']}")
        logger.info(f"   - Top K matches: {search_params['top_k']}")
        logger.info(f"   - Reasoning: {search_params['reasoning']}")
        
        # Note: MongoDB population happening in background
        populate_result = {"status": "background", "message": "Running in background"}
        
        if populate_result.get("status") == "success":
            logger.info(f"✅ MongoDB updated: {populate_result.get('inserted', 0)} new, "
                       f"{populate_result.get('existing', 0)} existing")
        else:
            logger.warning(f"⚠️  MongoDB population skipped: {populate_result.get('error')}")
        
        # Step 6: Match Jobs with Adaptive Strategy
        logger.info("\n🎯 STEP 6: Matching Jobs to Candidate...")
        match_result = await self._call_mcp_tool("match_jobs_to_resume", {
            "resume": parsed_resume,
            "jobs_source": "file",
            "jobs_file": jobs_file,
            "top_k": search_params['top_k'],
            "min_similarity": search_params['min_similarity'],
            "filter_senior_for_grads": candidate_analysis['experience_level'] == 'junior'
        })
        
        if match_result.get("status") != "success":
            return self._error_response("matching_failed", match_result)
        
        matches = match_result.get("matches", [])
        logger.info(f"✅ Found {len(matches)} matching jobs")
        
        # Step 7: Adaptive Retry if Needed
        if len(matches) < 3 and search_params['min_similarity'] > 0.2:
            logger.info("\n🔄 STEP 7: Too few matches, retrying with relaxed criteria...")
            retry_params = {
                "resume": parsed_resume,
                "jobs_source": "file",
                "jobs_file": jobs_file,
                "top_k": search_params['top_k'] * 2,
                "min_similarity": 0.2,
                "filter_senior_for_grads": False
            }
            match_result = await self._call_mcp_tool("match_jobs_to_resume", retry_params)
            matches = match_result.get("matches", [])
            logger.info(f"✅ Retry found {len(matches)} matches")
        
        # Step 8: LLM Analysis of Top Matches
        logger.info("\n🤔 STEP 8: Analyzing Top Matches with LLM...")
        match_insights = await self._analyze_job_matches(
            parsed_resume,
            matches[:5],
            candidate_analysis
        )
        
        # Step 9: Generate Cover Letters (if requested)
        cover_letters = []
        if preferences.get("generate_cover_letters", False):
            logger.info("\n✍️  STEP 9: Generating Cover Letters...")
            num_letters = min(preferences.get("cover_letter_count", 3), len(matches))
            
            for i, match in enumerate(matches[:num_letters], 1):
                logger.info(f"   Generating cover letter {i}/{num_letters}...")
                cover_result = await self._call_mcp_tool("create_cover_letter", {
                    "resume": parsed_resume,
                    "job": match,
                    "model_name": self.model_name
                })
                
                if cover_result.get("status") == "success":
                    cover_letters.append({
                        "job_index": i - 1,
                        "job_title": cover_result.get("job_title"),
                        "company": cover_result.get("company"),
                        "cover_letter": cover_result.get("cover_letter"),
                        "length": cover_result.get("letter_length")
                    })
            
            logger.info(f"✅ Generated {len(cover_letters)} cover letters")
        
        # Calculate execution time
        execution_time = (datetime.now() - start_time).total_seconds()
        
        logger.info("\n" + "=" * 70)
        logger.info(f"✅ AGENT: Workflow completed in {execution_time:.2f}s")
        logger.info("=" * 70)
        
        # Return comprehensive results
        return {
            "status": "success",
            "execution_time_seconds": execution_time,
            "agent_reasoning": {
                "candidate_analysis": candidate_analysis,
                "search_parameters": search_params,
                "match_insights": match_insights
            },
            "candidate": {
                "name": parsed_resume.get("name"),
                "skills": parsed_resume.get("skills", []),
                "skills_count": len(parsed_resume.get("skills", [])),
                "experience_count": len(parsed_resume.get("experience", [])),
                "education_count": len(parsed_resume.get("education", []))
            },
            "job_search": {
                "total_jobs_fetched": fetch_result.get("fetched", 0),
                "matches_found": len(matches),
                "matches": matches,
                "mongodb_status": populate_result.get("status")
            },
            "cover_letters": cover_letters
        }
    
    async def _analyze_candidate_profile(self, resume: Dict[str, Any]) -> Dict[str, Any]:
        """Use LLM to analyze candidate profile and determine experience level."""
        
        # Prepare resume summary for LLM
        resume_summary = f"""
Candidate Name: {resume.get('name', 'Unknown')}

Skills ({len(resume.get('skills', []))}):
{', '.join(resume.get('skills', [])[:20])}

Experience ({len(resume.get('experience', []))} positions):
"""
        for i, exp in enumerate(resume.get('experience', [])[:5], 1):
            resume_summary += f"\n{i}. {exp.get('title', 'Unknown')} at {exp.get('organization', 'Unknown')}"
            if exp.get('period'):
                resume_summary += f" ({exp['period']})"
        
        resume_summary += f"\n\nEducation ({len(resume.get('education', []))} entries):\n"
        for edu in resume.get('education', [])[:3]:
            if isinstance(edu, dict):
                resume_summary += f"- {edu.get('text', str(edu))}\n"
            else:
                resume_summary += f"- {edu}\n"
        
        # Use LLM to analyze
        prompt = f"""Analyze this candidate's profile and provide a brief assessment.

{resume_summary}

Based on this information, provide a JSON response with:
1. experience_level: "junior", "mid", or "senior"
2. career_stage: brief description (e.g., "Entry-level software engineer", "Senior full-stack developer")
3. top_skills: array of 5 most important/marketable skills
4. years_estimate: estimated years of professional experience (number)
5. strengths: brief description of key strengths

Respond ONLY with valid JSON, no additional text."""

        try:
            response = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options={"temperature": 0.3}
            )
            
            # Extract JSON from response
            response_text = response['response'].strip()
            
            # Try to parse JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            analysis = json.loads(response_text)
            
            return analysis
            
        except Exception as e:
            logger.warning(f"LLM analysis failed, using heuristics: {e}")
            # Fallback to heuristic analysis
            experience_count = len(resume.get('experience', []))
            years_estimate = experience_count * 2.5
            
            if years_estimate < 2:
                level = "junior"
            elif years_estimate < 7:
                level = "mid"
            else:
                level = "senior"
            
            return {
                "experience_level": level,
                "career_stage": f"{level.capitalize()} professional with ~{int(years_estimate)} years experience",
                "top_skills": resume.get('skills', [])[:5],
                "years_estimate": int(years_estimate),
                "strengths": "Diverse skill set with practical experience"
            }
    
    async def _determine_search_parameters(
        self,
        candidate_analysis: Dict[str, Any],
        preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LLM reasoning to determine optimal search parameters."""
        
        prompt = f"""You are an expert job search advisor. Based on this candidate profile, determine optimal job search parameters.

Candidate Profile:
- Experience Level: {candidate_analysis['experience_level']}
- Career Stage: {candidate_analysis['career_stage']}
- Years of Experience: ~{candidate_analysis.get('years_estimate', 0)}
- Top Skills: {', '.join(candidate_analysis.get('top_skills', []))}

User Preferences:
- Requested job count: {preferences.get('job_count', 'not specified')}
- Requested top_k: {preferences.get('top_k', 'not specified')}

Determine optimal parameters and provide reasoning. Consider:
- Junior candidates need fewer, more targeted jobs with higher match threshold
- Senior candidates can handle more jobs with lower threshold
- Mid-level candidates need balanced approach

Respond ONLY with valid JSON:
{{
    "job_count": <number 20-100>,
    "min_similarity": <number 0.2-0.4>,
    "top_k": <number 3-10>,
    "reasoning": "<brief explanation of choices>"
}}"""

        try:
            response = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options={"temperature": 0.3}
            )
            
            response_text = response['response'].strip()
            
            # Extract JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            params = json.loads(response_text)
            
            # Override with user preferences if specified
            if preferences.get('job_count'):
                params['job_count'] = preferences['job_count']
            if preferences.get('top_k'):
                params['top_k'] = preferences['top_k']
            if preferences.get('min_similarity'):
                params['min_similarity'] = preferences['min_similarity']
            
            return params
            
        except Exception as e:
            logger.warning(f"LLM parameter determination failed, using defaults: {e}")
            
            # Fallback heuristics
            level = candidate_analysis['experience_level']
            years = candidate_analysis.get('years_estimate', 0)
            
            if level == 'junior' or years < 2:
                return {
                    "job_count": preferences.get('job_count', 30),
                    "min_similarity": preferences.get('min_similarity', 0.35),
                    "top_k": preferences.get('top_k', 5),
                    "reasoning": "Junior candidate: fewer, highly targeted jobs with strict matching"
                }
            elif level == 'senior' or years > 10:
                return {
                    "job_count": preferences.get('job_count', 80),
                    "min_similarity": preferences.get('min_similarity', 0.25),
                    "top_k": preferences.get('top_k', 10),
                    "reasoning": "Senior candidate: more opportunities with flexible matching"
                }
            else:
                return {
                    "job_count": preferences.get('job_count', 50),
                    "min_similarity": preferences.get('min_similarity', 0.3),
                    "top_k": preferences.get('top_k', 6),
                    "reasoning": "Mid-level candidate: balanced approach"
                }
    
    async def _analyze_job_matches(
        self,
        resume: Dict[str, Any],
        matches: List[Dict[str, Any]],
        candidate_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LLM to provide insights on top job matches."""
        
        if not matches:
            return {"insights": "No matches to analyze"}
        
        # Prepare match summary
        match_summary = f"""Candidate: {resume.get('name')}
Career Stage: {candidate_analysis['career_stage']}
Top Skills: {', '.join(candidate_analysis.get('top_skills', []))}

Top {len(matches)} Job Matches:
"""
        for i, match in enumerate(matches, 1):
            job = match
            title = job.get('jobTitle') or job.get('title', 'Unknown')
            company = job.get('companyName') or job.get('company', 'Unknown')
            similarity = (job.get('similarity', 0) * 100)
            match_summary += f"\n{i}. {title} at {company} ({similarity:.1f}% match)"
        
        prompt = f"""{match_summary}

Provide brief insights about these matches:
1. Which job(s) seem like the best fit and why?
2. Any concerns or considerations?
3. Overall assessment of the match quality

Keep it concise (3-4 sentences total). Respond ONLY with valid JSON:
{{
    "best_match": "<job number and why>",
    "considerations": "<any concerns>",
    "overall_assessment": "<brief assessment>"
}}"""

        try:
            response = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options={"temperature": 0.4}
            )
            
            response_text = response['response'].strip()
            
            # Extract JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            insights = json.loads(response_text)
            return insights
            
        except Exception as e:
            logger.warning(f"LLM match analysis failed: {e}")
            return {
                "best_match": f"Job 1 with {matches[0].get('similarity', 0)*100:.1f}% similarity",
                "considerations": "Review all matches for best fit",
                "overall_assessment": f"Found {len(matches)} potential matches"
            }
    
    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool and extract the result."""
        try:
            result = await self.client.call_tool(tool_name, arguments)
            
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
                "error": str(e),
                "tool": tool_name
            }
    
    def _error_response(self, reason: str, detail: Any) -> Dict[str, Any]:
        """Generate error response."""
        return {
            "status": "failed",
            "reason": reason,
            "detail": detail
        }


async def main():
    """Example usage of the agent."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python agent.py <resume_path> [--generate-cover-letters]")
        print("\nExample:")
        print("  python agent.py Thomas_Pequegnot_Resume.pdf")
        print("  python agent.py Thomas_Pequegnot_Resume.pdf --generate-cover-letters")
        return
    
    resume_path = sys.argv[1]
    generate_letters = "--generate-cover-letters" in sys.argv
    
    print("\n" + "=" * 70)
    print("🤖 Job Application Agent - Powered by Ollama Llama 3.2")
    print("=" * 70 + "\n")
    
    # Create and run agent
    async with JobApplicationAgent(model_name="llama3.2") as agent:
        result = await agent.execute_job_search(
            resume_path=resume_path,
            preferences={
                "generate_cover_letters": generate_letters,
                "cover_letter_count": 3
            }
        )
        
        # Display results
        if result["status"] == "success":
            print("\n" + "=" * 70)
            print("📊 RESULTS")
            print("=" * 70)
            
            print(f"\n👤 Candidate: {result['candidate']['name']}")
            print(f"   Skills: {result['candidate']['skills_count']}")
            print(f"   Experience: {result['candidate']['experience_count']} positions")
            
            print(f"\n🤖 Agent Analysis:")
            reasoning = result['agent_reasoning']
            print(f"   Experience Level: {reasoning['candidate_analysis']['experience_level']}")
            print(f"   Career Stage: {reasoning['candidate_analysis']['career_stage']}")
            print(f"   Search Strategy: {reasoning['search_parameters']['reasoning']}")
            
            print(f"\n🎯 Job Matches: {result['job_search']['matches_found']} found")
            print(f"   Total Jobs Fetched: {result['job_search']['total_jobs_fetched']}")
            
            if result['job_search']['matches']:
                print("\n   Top 3 Matches:")
                for i, match in enumerate(result['job_search']['matches'][:3], 1):
                    title = match.get('jobTitle') or match.get('title', 'Unknown')
                    company = match.get('companyName') or match.get('company', 'Unknown')
                    similarity = (match.get('similarity', 0) * 100)
                    print(f"   {i}. {title} at {company} ({similarity:.1f}% match)")
            
            print(f"\n💡 Agent Insights:")
            insights = reasoning.get('match_insights', {})
            print(f"   Best Match: {insights.get('best_match', 'N/A')}")
            print(f"   Assessment: {insights.get('overall_assessment', 'N/A')}")
            
            if result.get('cover_letters'):
                print(f"\n✍️  Cover Letters Generated: {len(result['cover_letters'])}")
                for cl in result['cover_letters']:
                    print(f"   - {cl['job_title']} at {cl['company']} ({cl['length']} chars)")
            
            print(f"\n⏱️  Execution Time: {result['execution_time_seconds']:.2f}s")
            
            # Save results
            output_file = f"agent_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"\n💾 Full results saved to: {output_file}")
            
        else:
            print(f"\n❌ Agent failed: {result.get('reason')}")
            print(f"   Detail: {result.get('detail')}")


if __name__ == "__main__":
    asyncio.run(main())
