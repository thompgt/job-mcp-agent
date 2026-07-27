"use client";

import { useState } from "react";

import { type MatchResult, type ParsedResume } from "@/lib/api";
import { CapabilityBanner, CapabilityFooter } from "@/components/capability-banner";
import { LetterStep } from "@/components/letter-step";
import { MatchStep } from "@/components/match-step";
import { ResumeStep } from "@/components/resume-step";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * One page, three steps, top to bottom.
 *
 * The state that matters is small — a resume, a match result, a chosen job —
 * so it lives here rather than behind a store. Anything more elaborate would
 * be scaffolding around four values.
 */
export default function Home() {
  const [resume, setResume] = useState<ParsedResume | null>(null);
  const [matches, setMatches] = useState<MatchResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  return (
    <main id="main" className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">CareerCraft</h1>
        <p className="text-muted-foreground">
          Parse your resume, find roles you are actually competitive for, and draft a letter
          grounded in both. Nothing leaves this machine except the job search itself.
        </p>
      </header>

      <CapabilityBanner />

      <ResumeStep
        resume={resume}
        onParsed={(parsed) => {
          setResume(parsed);
          // A new resume invalidates results ranked against the old one.
          setMatches(null);
          setJobId(null);
        }}
      />

      <MatchStep
        resumeId={resume?.id ?? null}
        result={matches}
        onResult={(result) => {
          setMatches(result);
          setJobId(null);
        }}
        onPick={setJobId}
        selectedJobId={jobId}
      />

      <LetterStep jobId={jobId} resumeId={resume?.id ?? null} />

      <CapabilityFooter apiUrl={API_URL} />
    </main>
  );
}
