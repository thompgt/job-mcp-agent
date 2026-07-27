"use client";

import { useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";

import { api, ApiError, type ParsedResume } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, Badge, Spinner, Textarea } from "@/components/ui/primitives";

export function ResumeStep({
  resume,
  onParsed,
}: {
  resume: ParsedResume | null;
  onParsed: (resume: ParsedResume) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function run(work: () => Promise<ParsedResume>) {
    setBusy(true);
    setError(null);
    try {
      onParsed(await work());
    } catch (e) {
      setError(e instanceof ApiError ? e.full : "Something went wrong parsing that resume.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>1. Your resume</CardTitle>
        <CardDescription>
          Upload a PDF or Word file, or paste the text. It is parsed on this machine.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.rtf"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) run(() => api.uploadResume(file));
              e.target.value = "";
            }}
          />
          <Button onClick={() => fileInput.current?.click()} disabled={busy}>
            <Upload aria-hidden />
            Upload a file
          </Button>
          {busy ? <Spinner label="Parsing…" /> : null}
        </div>

        <div className="space-y-2">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="…or paste your resume text here."
            aria-label="Resume text"
          />
          <Button
            variant="outline"
            disabled={busy || text.trim().length === 0}
            onClick={() => run(() => api.parseText(text))}
          >
            <FileText aria-hidden />
            Parse pasted text
          </Button>
        </div>

        {error ? <Alert title="Could not parse that">{error}</Alert> : null}
        {resume ? <ResumeSummaryCard resume={resume} /> : null}
      </CardContent>
    </Card>
  );
}

function ResumeSummaryCard({ resume }: { resume: ParsedResume }) {
  const warnings = resume.parse_warnings ?? [];
  return (
    <div className="space-y-3 rounded-lg border bg-muted/40 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">{resume.name ?? "Name not detected"}</p>
        <p className="text-xs text-muted-foreground">
          {resume.skills?.length ?? 0} skills · {resume.experience?.length ?? 0} roles ·{" "}
          {resume.education?.length ?? 0} education entries
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(resume.skills ?? []).map((s) => (
          <Badge key={s} variant="secondary">
            {s}
          </Badge>
        ))}
      </div>

      {warnings.length > 0 ? (
        <Alert tone="info" title="The parser was unsure about some of this">
          {/* Worth showing rather than hiding: a parser struggling with a
              section is a fair signal an applicant tracking system will too. */}
          <ul className="list-inside list-disc">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
    </div>
  );
}
