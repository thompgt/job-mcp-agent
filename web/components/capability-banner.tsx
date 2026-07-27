"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Check, ChevronDown } from "lucide-react";

import { api, type Capabilities } from "@/lib/api";
import { Badge } from "@/components/ui/primitives";

/**
 * What this install can do, and what it would take to do more.
 *
 * Worth surfacing rather than hiding: without the [pdf] extra a PDF upload
 * fails for a reason nobody would guess from the error, and the fix is one
 * pip command that the API already knows how to name.
 */
export function CapabilityBanner() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => setCaps(null));
  }, []);

  if (!caps) return null;

  const missing = caps.capabilities.filter((c) => !c.available);
  const notable = missing.filter((c) => c.name === "pdf_text" || c.name === "llm_cover_letters");

  return (
    <div className="rounded-lg border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm"
      >
        {missing.length === 0 ? (
          <Check className="size-4 text-success" aria-hidden />
        ) : (
          <AlertTriangle className="size-4 text-warning" aria-hidden />
        )}
        <span className="flex-1">
          {missing.length === 0
            ? "Every feature is available."
            : notable.length > 0
              ? `${notable.map(labelFor).join(" and ")} unavailable in this install.`
              : `${missing.length} optional feature${missing.length === 1 ? "" : "s"} not installed.`}
        </span>
        <span className="text-xs text-muted-foreground">v{caps.version}</span>
        <ChevronDown
          className={`size-4 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {open ? (
        <ul className="space-y-2 border-t px-4 py-3">
          {caps.capabilities.map((c) => (
            <li key={c.name} className="flex flex-wrap items-baseline gap-2 text-sm">
              <Badge variant={c.available ? "match" : "secondary"}>
                {c.available ? "on" : "off"}
              </Badge>
              <span className="font-medium">{c.name}</span>
              <span className="text-muted-foreground">{c.detail}</span>
              {c.enable_with ? (
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{c.enable_with}</code>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function labelFor(c: Capabilities["capabilities"][number]): string {
  if (c.name === "pdf_text") return "PDF reading";
  if (c.name === "llm_cover_letters") return "local letter writing";
  return c.name;
}

export function CapabilityFooter({ apiUrl }: { apiUrl: string }) {
  return (
    <p className="text-center text-xs text-muted-foreground">
      Everything runs locally. Your resume never leaves this machine.{" "}
      <a className="underline" href={`${apiUrl}/docs`} target="_blank" rel="noreferrer">
        API docs
      </a>
    </p>
  );
}
