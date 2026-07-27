"use client";

import { useState } from "react";
import { ExternalLink, Search } from "lucide-react";

import { api, ApiError, type JobMatch, type MatchResult, type Strategy } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Alert,
  Badge,
  Input,
  Label,
  ScoreBar,
  Select,
  Spinner,
} from "@/components/ui/primitives";

export function MatchStep({
  resumeId,
  result,
  onResult,
  onPick,
  selectedJobId,
}: {
  resumeId: string | null;
  result: MatchResult | null;
  onResult: (result: MatchResult) => void;
  onPick: (jobId: string) => void;
  selectedJobId: string | null;
}) {
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("auto");
  const [filterSeniority, setFilterSeniority] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    setBusy(true);
    setError(null);
    try {
      onResult(
        await api.match({
          resume_id: resumeId,
          query,
          location,
          strategy,
          filter_seniority: filterSeniority,
          min_score: 0,
        }),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.full : "The search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>2. Find matching roles</CardTitle>
        <CardDescription>
          Every result says which of your skills the posting asks for, and which it asks for that
          your resume does not mention.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="query">Role</Label>
            <Input
              id="query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="data analyst"
              onKeyDown={(e) => e.key === "Enter" && !busy && resumeId && search()}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="location">Region</Label>
            <Input
              id="location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="USA (optional)"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="strategy">Ranking</Label>
            <Select
              id="strategy"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as Strategy)}
            >
              <option value="auto">Automatic</option>
              <option value="keyword">Keyword and skill overlap</option>
              <option value="embedding">Semantic (needs the embeddings extra)</option>
            </Select>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={filterSeniority}
                onChange={(e) => setFilterSeniority(e.target.checked)}
                className="size-4 rounded border-input"
              />
              Hide roles I am not yet eligible for
            </label>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={search} disabled={busy || !resumeId}>
            <Search aria-hidden />
            Find matches
          </Button>
          {!resumeId ? (
            <span className="text-sm text-muted-foreground">Parse a resume first.</span>
          ) : null}
          {busy ? <Spinner label="Ranking postings…" /> : null}
        </div>

        {error ? <Alert title="Could not search">{error}</Alert> : null}

        {result ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {result.matches.length} of {result.jobs_considered} postings ·{" "}
              {result.strategy_used} ranking
              {result.jobs_filtered_out
                ? ` · ${result.jobs_filtered_out} filtered out as out of reach`
                : ""}
            </p>

            {/* The service explains an empty result rather than returning a
                bare zero, so show what it said. */}
            {(result.notes ?? []).map((note) => (
              <Alert key={note} tone="info">
                {note}
              </Alert>
            ))}

            {result.matches.map((m) => (
              <MatchRow
                key={m.job.id}
                match={m}
                selected={m.job.id === selectedJobId}
                onPick={() => onPick(m.job.id)}
              />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MatchRow({
  match,
  selected,
  onPick,
}: {
  match: JobMatch;
  selected: boolean;
  onPick: () => void;
}) {
  const { job } = match;
  return (
    <div
      className={`space-y-3 rounded-lg border p-4 transition-colors ${
        selected ? "border-primary bg-accent/50" : ""
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{job.title}</p>
          <p className="text-sm text-muted-foreground">
            {[job.company, job.location].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className="text-sm font-semibold tabular-nums">
          {(match.score * 100).toFixed(0)}%
        </span>
      </div>

      <ScoreBar value={match.score} />

      <div className="flex flex-wrap gap-1.5">
        {(match.matched_skills ?? []).map((s) => (
          <Badge key={s} variant="match">
            {s}
          </Badge>
        ))}
        {(match.missing_skills ?? []).map((s) => (
          <Badge key={s} variant="gap">
            {s}
          </Badge>
        ))}
      </div>

      {match.rationale ? (
        <p className="text-sm text-muted-foreground">{match.rationale}</p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={selected ? "default" : "outline"} onClick={onPick}>
          {selected ? "Selected" : "Write a letter for this"}
        </Button>
        {job.url ? (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-2 rounded-md px-3 text-xs font-medium hover:bg-accent"
          >
            <ExternalLink className="size-4" aria-hidden />
            View posting
          </a>
        ) : null}
      </div>
    </div>
  );
}
