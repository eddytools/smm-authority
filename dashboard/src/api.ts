const BASE: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "smm_token";

export type Role = "admin" | "user";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Venture {
  id: number;
  owner_id: number;
  owner_email: string;
  name: string;
  description: string | null;
  niche: string | null;
  website_url: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface VentureInput {
  name: string;
  description: string | null;
  niche: string | null;
  website_url: string | null;
}

export const PLATFORMS = ["linkedin", "x", "reddit", "instagram", "youtube", "blog", "newsletter"] as const;
export type Platform = (typeof PLATFORMS)[number];

export interface PlatformPlan {
  platform: Platform;
  cadence_per_week: number;
  is_primary: boolean;
  reason?: string | null;
}

export interface BriefData {
  icp: { industry?: string | null; company_size?: string | null; roles: string[]; pains: string[]; goals: string[]; objections: string[]; channels: string[] };
  ideation: { niche_statement?: string | null; unique_angle?: string | null; pillars: string[]; proof_assets: string[]; opinions: string[] };
  offer: { offer?: string | null; lead_magnets: string[]; cta_url?: string | null; booking_url?: string | null };
  voice: { tone?: string | null; dos: string[]; donts: string[]; writing_samples: string[] };
  platforms: PlatformPlan[];
}

export interface BriefVersion {
  venture_id: number;
  version: number;
  data: BriefData;
  created_by_id: number | null;
  created_at: string;
}

export interface BriefVersionSummary {
  version: number;
  created_by_id: number | null;
  created_at: string;
}

export interface BriefSuggestion {
  ideation: BriefData["ideation"];
  platforms: PlatformPlan[];
  rationale: string;
}

export type SourceType = "rss" | "reddit" | "google_news";
export interface Source {
  id: number;
  type: SourceType;
  target: string;
  label: string | null;
  enabled: boolean;
  last_fetched_at: string | null;
  last_status: "ok" | "error" | null;
  last_error: string | null;
}

export type ItemStatus = "new" | "saved" | "dismissed";
export interface FeedItem {
  id: number;
  source_id: number;
  source_type: SourceType;
  source_label: string;
  url: string;
  title: string;
  summary: string | null;
  author: string | null;
  published_at: string;
  engagement: number;
  rule_score: number;
  relevance: number | null;
  why_it_matters: string | null;
  status: ItemStatus;
}

export interface RefreshResult {
  new_items: number;
  sources: { source_id: number; status: string; new_items: number; error: string | null }[];
}

export type Stage = "tofu" | "mofu" | "bofu";
export type SlotStatus = "idea" | "drafted" | "in_review" | "approved" | "scheduled" | "published" | "analysed" | "skipped" | "archived";

export interface Framework {
  stages: { key: Stage; goal: string; post_types: { key: string; label: string; guidance: string; platforms: string[] }[] }[];
  statuses: SlotStatus[];
  transitions: Record<SlotStatus, SlotStatus[]>;
}

export interface PlanSlot {
  id: number;
  venture_id: number;
  scheduled_at: string;
  platform: string;
  post_type: string;
  stage: Stage;
  pillar: string | null;
  topic: string;
  cta: string | null;
  draft: string | null;
  status: SlotStatus;
  locked: boolean;
  reactive: boolean;
  source_item_id: number | null;
  warnings: string[];
}

export interface DraftResult {
  draft: string;
  hooks: string[];
  notes: string;
  warnings: string[];
}

export interface GenerateResult {
  created: number;
  removed: number;
  kept: number;
  by_stage: Record<Stage, number>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get: (): string | null => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, t);
    } catch {
      /* storage unavailable; session lasts until reload */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const msg = (first.msg ?? fallback).replace(/^Value error, /, "");
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
    // "body" just means the whole request; only name an actual field
    return typeof field === "string" && field !== "body" ? `${field}: ${msg}` : msg;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is it running?");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && auth && token) onUnauthorized();
    throw new ApiError(res.status, errorMessage(body, res.statusText));
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({ method, body: JSON.stringify(data) });

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", json("POST", { email, password }), false),
  register: (name: string, email: string, password: string) =>
    request<User>("/auth/register", json("POST", { name, email, password }), false),
  me: () => request<User>("/auth/me"),

  listVentures: (scope: "mine" | "all", includeArchived: boolean) =>
    request<Venture[]>(`/ventures?scope=${scope}&include_archived=${includeArchived}`),
  getVenture: (id: number) => request<Venture>(`/ventures/${id}`),
  createVenture: (data: VentureInput) => request<Venture>("/ventures", json("POST", data)),
  updateVenture: (id: number, data: Partial<VentureInput> & { is_archived?: boolean }) =>
    request<Venture>(`/ventures/${id}`, json("PATCH", data)),
  deleteVenture: (id: number) => request<void>(`/ventures/${id}`, { method: "DELETE" }),

  getBrief: (ventureId: number) => request<BriefVersion | null>(`/ventures/${ventureId}/brief`),
  getBriefVersion: (ventureId: number, version: number) => request<BriefVersion>(`/ventures/${ventureId}/brief/versions/${version}`),
  listBriefVersions: (ventureId: number) => request<BriefVersionSummary[]>(`/ventures/${ventureId}/brief/versions`),
  saveBrief: (ventureId: number, data: BriefData) => request<BriefVersion>(`/ventures/${ventureId}/brief`, json("PUT", data)),
  suggestBrief: (ventureId: number, inputs: Partial<BriefData>) =>
    request<BriefSuggestion>(`/ventures/${ventureId}/brief/suggest`, json("POST", inputs)),

  listSources: (vid: number) => request<Source[]>(`/ventures/${vid}/sources`),
  addSource: (vid: number, data: { type: SourceType; target: string }) => request<Source>(`/ventures/${vid}/sources`, json("POST", data)),
  updateSource: (vid: number, id: number, data: { enabled: boolean }) => request<Source>(`/ventures/${vid}/sources/${id}`, json("PATCH", data)),
  deleteSource: (vid: number, id: number) => request<void>(`/ventures/${vid}/sources/${id}`, { method: "DELETE" }),
  listFeed: (vid: number, status: "new" | "saved" | "dismissed") => request<FeedItem[]>(`/ventures/${vid}/feed?status=${status}&limit=100`),
  setItemStatus: (vid: number, id: number, status: ItemStatus) => request<FeedItem>(`/ventures/${vid}/feed/${id}`, json("PATCH", { status })),
  refreshFeed: (vid: number) => request<RefreshResult>(`/ventures/${vid}/feed/refresh`, { method: "POST" }),
  scoreFeed: (vid: number) => request<{ scored: number }>(`/ventures/${vid}/feed/score`, { method: "POST" }),

  getFramework: () => request<Framework>("/planner/framework"),
  listPlan: (vid: number) => request<PlanSlot[]>(`/ventures/${vid}/plan?limit=500`),
  generatePlan: (vid: number, data: { start_date: string; period: "week" | "month"; timezone: string; mix: Record<Stage, number>; replace: boolean }) =>
    request<GenerateResult>(`/ventures/${vid}/plan/generate`, json("POST", data)),
  updateSlot: (vid: number, id: number, data: Partial<Pick<PlanSlot, "scheduled_at" | "platform" | "post_type" | "topic" | "pillar" | "cta" | "draft" | "status" | "locked">>) =>
    request<PlanSlot>(`/ventures/${vid}/plan/slots/${id}`, json("PATCH", data)),
  draftSlot: (vid: number, id: number, instructions: string | null) =>
    request<DraftResult>(`/ventures/${vid}/plan/slots/${id}/draft`, json("POST", { instructions })),
  deleteSlot: (vid: number, id: number) => request<void>(`/ventures/${vid}/plan/slots/${id}`, { method: "DELETE" }),

  listUsers: () => request<User[]>("/users"),
  createUser: (data: { name: string; email: string; password: string; role: Role }) =>
    request<User>("/users", json("POST", data)),
  updateUser: (id: number, data: Partial<{ name: string; role: Role; is_active: boolean; password: string }>) =>
    request<User>(`/users/${id}`, json("PATCH", data)),
};
