"use client";

import { useState } from "react";
import { Copy, PenLine } from "lucide-react";

import { api, ApiError, type CoverLetter, type Length, type Tone } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, Label, Select, Spinner } from "@/components/ui/primitives";

export function LetterStep({
  jobId,
  resumeId,
}: {
  jobId: string | null;
  resumeId: string | null;
}) {
  const [tone, setTone] = useState<Tone>("professional");
  const [length, setLength] = useState<Length>("medium");
  const [letter, setLetter] = useState<CoverLetter | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function generate() {
    if (!jobId) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const { letter: result } = await api.generateLetter({
        job_id: jobId,
        resume_id: resumeId,
        tone,
        length,
      });
      setLetter(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.full : "The letter could not be generated.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!letter?.text) return;
    await navigator.clipboard.writeText(letter.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>3. Draft a cover letter</CardTitle>
        <CardDescription>
          Grounded in your resume and the posting. It will not claim a skill your resume does not
          evidence.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="tone">Tone</Label>
            <Select id="tone" value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
              <option value="professional">Professional</option>
              <option value="enthusiastic">Enthusiastic</option>
              <option value="concise">Concise</option>
              <option value="academic">Academic</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="length">Length</Label>
            <Select
              id="length"
              value={length}
              onChange={(e) => setLength(e.target.value as Length)}
            >
              <option value="short">Short (~200 words)</option>
              <option value="medium">Medium (~350 words)</option>
              <option value="long">Long (~550 words)</option>
            </Select>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={generate} disabled={busy || !jobId}>
            <PenLine aria-hidden />
            Write the letter
          </Button>
          {!jobId ? (
            <span className="text-sm text-muted-foreground">Pick a role above first.</span>
          ) : null}
          {/* A local model can take a while, so say what is happening. */}
          {busy ? <Spinner label="Drafting — this can take a minute on a local model…" /> : null}
        </div>

        {error ? <Alert title="Could not write the letter">{error}</Alert> : null}

        {letter?.text ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                {letter.word_count} words ·{" "}
                {letter.generated_by === "ollama"
                  ? `written by ${letter.model ?? "your local model"}`
                  : "assembled from a template — install Ollama for a written draft"}
              </p>
              <Button size="sm" variant="outline" onClick={copy}>
                <Copy aria-hidden />
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <article className="whitespace-pre-wrap rounded-lg border bg-muted/40 p-4 text-sm leading-relaxed">
              {letter.text}
            </article>
          </div>
        ) : null}

        {letter?.brief ? <BriefView brief={letter.brief} /> : null}
      </CardContent>
    </Card>
  );
}

/**
 * Shown when no local model was reachable.
 *
 * The API asks for prose by default, so this is rare here — but if it happens
 * the brief is genuinely useful material rather than an error, and burying it
 * would be the wrong call.
 */
function BriefView({ brief }: { brief: NonNullable<CoverLetter["brief"]> }) {
  return (
    <div className="space-y-3 rounded-lg border bg-muted/40 p-4 text-sm">
      <p className="font-medium">
        A brief for {brief.role} at {brief.company}
      </p>
      <Section title="Themes" items={brief.themes} />
      <Section title="Evidence from your resume" items={brief.evidence} />
      <Section title="Hooks from the posting" items={brief.company_hooks} />
      <Section title="Paragraph plan" items={brief.paragraph_plan} ordered />
    </div>
  );
}

function Section({
  title,
  items,
  ordered = false,
}: {
  title: string;
  items: string[];
  ordered?: boolean;
}) {
  if (items.length === 0) return null;
  const List = ordered ? "ol" : "ul";
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
      <List className={`mt-1 list-inside ${ordered ? "list-decimal" : "list-disc"} space-y-1`}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </List>
    </div>
  );
}
