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
  has_metrics: boolean;
  will_auto_publish: boolean;
  published_at: string | null;
  external_url: string | null;
  publish_error: string | null;
}

export interface Integration {
  platform: string;
  label: string;
  configured: boolean;
  connected: boolean;
  account_name: string | null;
  status: "active" | "needs_reconnect" | null;
  auto_publish: boolean | null;
  expires_at: string | null;
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

export interface Metrics {
  impressions: number;
  reactions: number;
  comments: number;
  shares: number;
  saves: number;
  clicks: number;
  follows: number;
  leads: number;
}

export interface Group {
  key: string;
  label: string;
  posts: number;
  impressions: number;
  avg_impressions: number;
  engagements: number;
  engagement_rate: number | null;
  clicks: number;
  ctr: number | null;
  follows: number;
  leads: number;
  lift: number | null;
}

export interface Finding {
  dimension: string;
  dimension_title: string;
  key: string;
  label: string;
  posts: number;
  lift: number | null;
  message: string;
}

export interface PostView {
  slot_id: number;
  topic: string;
  platform: string;
  post_type: string;
  stage: Stage;
  scheduled_at: string;
  impressions: number;
  engagement_rate: number;
  leads: number;
}

export interface MixSuggestion {
  ready: boolean;
  changed: boolean;
  current: Record<Stage, number>;
  suggested: Record<Stage, number>;
  reasons: string[];
}

export interface Insights {
  range_days: number;
  totals: { posts: number; impressions: number; engagements: number; engagement_rate: number | null; clicks: number; ctr: number | null; follows: number; leads: number; published: number; measured: number };
  breakdowns: Record<"platform" | "pillar" | "post_type" | "stage", Group[]>;
  worked: Finding[];
  didnt: Finding[];
  recommendations: string[];
  top: PostView[];
  bottom: PostView[];
  adherence: { due: number; published: number; skipped: number; rate: number | null };
  mix: Record<Stage, { planned: number; published: number }>;
  mix_suggestion: MixSuggestion;
  waiting: { slot_id: number; topic: string; platform: string; scheduled_at: string }[];
  note: string | null;
}

export interface ImportResult {
  imported: number;
  errors: { row: number; message: string }[];
}

export interface Reply {
  id: number;
  venture_id: number;
  platform: "reddit" | "linkedin" | "x";
  community: string | null;
  source_url: string | null;
  feed_item_id: number | null;
  question_text: string;
  community_rules: string | null;
  reply_draft: string;
  post_idea_title: string | null;
  post_idea: string | null;
  notes: string | null;
  status: "open" | "posted" | "dismissed";
  plan_slot_id: number | null;
  warnings: string[];
  created_at: string;
}

export interface Opportunity {
  id: number;
  title: string;
  url: string;
  source_label: string;
  source_type: string;
  engagement: number;
  age_hours: number;
  score: number;
}

export interface ReplyRequest {
  platform: "reddit" | "linkedin" | "x";
  question_text?: string;
  source_url?: string;
  community?: string;
  community_rules?: string;
  feed_item_id?: number;
  instructions?: string;
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

  getInsights: (vid: number, days: number, mix?: Record<Stage, number>) =>
    request<Insights>(`/ventures/${vid}/insights?days=${days}${mix ? `&tofu=${mix.tofu}&mofu=${mix.mofu}&bofu=${mix.bofu}` : ""}`),
  getMetrics: (vid: number, slotId: number) => request<(Metrics & { slot_id: number }) | null>(`/ventures/${vid}/plan/slots/${slotId}/metrics`),
  saveMetrics: (vid: number, slotId: number, data: Metrics) => request<Metrics>(`/ventures/${vid}/plan/slots/${slotId}/metrics`, json("PUT", data)),
  importMetrics: (vid: number, csv: string) => request<ImportResult>(`/ventures/${vid}/metrics/import`, json("POST", { csv })),

  listIntegrations: (vid: number) => request<Integration[]>(`/ventures/${vid}/integrations`),
  connectIntegration: (vid: number, platform: string) => request<{ authorize_url: string }>(`/ventures/${vid}/integrations/${platform}/connect`, { method: "POST" }),
  updateIntegration: (vid: number, platform: string, auto_publish: boolean) => request<Integration>(`/ventures/${vid}/integrations/${platform}`, json("PATCH", { auto_publish })),
  disconnectIntegration: (vid: number, platform: string) => request<void>(`/ventures/${vid}/integrations/${platform}`, { method: "DELETE" }),
  publishNow: (vid: number, slotId: number) => request<PlanSlot>(`/ventures/${vid}/plan/slots/${slotId}/publish`, { method: "POST" }),

  listOpportunities: (vid: number) => request<Opportunity[]>(`/ventures/${vid}/replies/opportunities`),
  listReplies: (vid: number, status: "open" | "posted" | "dismissed") => request<Reply[]>(`/ventures/${vid}/replies?status=${status}`),
  draftReply: (vid: number, data: ReplyRequest) => request<Reply>(`/ventures/${vid}/replies/draft`, json("POST", data)),
  updateReply: (vid: number, id: number, data: Partial<Pick<Reply, "reply_draft" | "status" | "post_idea" | "post_idea_title">>) => request<Reply>(`/ventures/${vid}/replies/${id}`, json("PATCH", data)),
  redraftReply: (vid: number, id: number, instructions: string | null) => request<Reply>(`/ventures/${vid}/replies/${id}/redraft`, json("POST", { instructions })),
  replyToPlan: (vid: number, id: number, data: { scheduled_at: string; platform: string; post_type?: string }) => request<{ slot_id: number }>(`/ventures/${vid}/replies/${id}/to-plan`, json("POST", data)),
  deleteReply: (vid: number, id: number) => request<void>(`/ventures/${vid}/replies/${id}`, { method: "DELETE" }),

  listUsers: () => request<User[]>("/users"),
  createUser: (data: { name: string; email: string; password: string; role: Role }) =>
    request<User>("/users", json("POST", data)),
  updateUser: (id: number, data: Partial<{ name: string; role: Role; is_active: boolean; password: string }>) =>
    request<User>(`/users/${id}`, json("PATCH", data)),
};
