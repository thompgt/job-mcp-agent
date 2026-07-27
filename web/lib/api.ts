/**
 * The API client.
 *
 * Types come from `lib/schema.d.ts`, generated from the FastAPI OpenAPI
 * schema with `npm run generate:api`, so a response shape that changes on the
 * Python side breaks the build here rather than at runtime in a user's
 * browser.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Job = Schemas["Job"];
export type JobSearchResult = Schemas["JobSearchResult"];
export type ParsedResume = Schemas["ParsedResume"];
export type ResumeSummary = Schemas["ResumeSummary"];
export type JobMatch = Schemas["JobMatch"];
export type MatchResult = Schemas["MatchResult"];
export type CoverLetter = Schemas["CoverLetter"];
export type LetterBrief = Schemas["LetterBrief"];
export type Capabilities = Schemas["Capabilities"];
export type Capability = Schemas["Capability"];
export type SavedJob = Schemas["SavedJob"];
export type HealthResponse = Schemas["HealthResponse"];

export type Tone = NonNullable<Schemas["LetterRequest"]["tone"]>;
export type Length = NonNullable<Schemas["LetterRequest"]["length"]>;
export type Strategy = NonNullable<Schemas["MatchRequest"]["strategy"]>;

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * An error the API described, rather than one the network produced.
 *
 * The API answers failures with `{code, message, remedy}` — the remedy names
 * the setting or command that fixes it — so the UI can show something more
 * useful than "request failed".
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly remedy?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The whole message, remedy included, ready to display. */
  get full(): string {
    return this.remedy ? `${this.message} ${this.remedy}` : this.message;
  }
}

async function toError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `Request failed with status ${response.status}.`;
  let remedy: string | null = null;

  try {
    const body = await response.json();
    if (typeof body?.code === "string") {
      code = body.code;
      message = body.message ?? message;
      remedy = body.remedy ?? null;
    } else if (Array.isArray(body?.detail)) {
      // FastAPI's own 422 shape, which is not our error envelope.
      code = "validation_failed";
      message = body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  } catch {
    // A non-JSON body means the server is not the one we think it is.
  }
  return new ApiError(response.status, code, message, remedy);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch (cause) {
    throw new ApiError(
      0,
      "unreachable",
      `Could not reach the CareerCraft API at ${BASE}.`,
      "Start it with `careercraft api`, or check NEXT_PUBLIC_API_URL.",
    );
  }

  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  capabilities: () => request<Capabilities>("/api/capabilities"),

  searchJobs: (body: { query?: string; location?: string; limit?: number; refresh?: boolean }) =>
    post<JobSearchResult>("/api/jobs/search", body),
  recentJobs: () => request<Job[]>("/api/jobs/recent"),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  savedJobs: () => request<SavedJob[]>("/api/jobs/saved"),
  saveJob: (id: string, note = "") => post<Job>(`/api/jobs/${id}/save`, { note }),
  unsaveJob: (id: string) => request<void>(`/api/jobs/${id}/save`, { method: "DELETE" }),

  parseText: (text: string, sourceName?: string) =>
    post<ParsedResume>("/api/resumes/parse", { text, source_name: sourceName ?? null }),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ParsedResume>("/api/resumes/upload", { method: "POST", body: form });
  },
  listResumes: () => request<ResumeSummary[]>("/api/resumes"),
  getResume: (id: string) => request<ParsedResume>(`/api/resumes/${id}`),
  deleteResume: (id: string) => request<void>(`/api/resumes/${id}`, { method: "DELETE" }),

  match: (body: {
    resume_id?: string | null;
    query?: string;
    location?: string;
    top_k?: number;
    min_score?: number;
    strategy?: Strategy;
    filter_seniority?: boolean;
  }) => post<MatchResult>("/api/match", body),

  generateLetter: (body: {
    job_id: string;
    resume_id?: string | null;
    tone?: Tone;
    length?: Length;
  }) => post<{ id: string; letter: CoverLetter }>("/api/letters", body),
};
