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
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
    return field ? `${String(field)}: ${first.msg}` : (first.msg ?? fallback);
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

  listUsers: () => request<User[]>("/users"),
  createUser: (data: { name: string; email: string; password: string; role: Role }) =>
    request<User>("/users", json("POST", data)),
  updateUser: (id: number, data: Partial<{ name: string; role: Role; is_active: boolean; password: string }>) =>
    request<User>(`/users/${id}`, json("PATCH", data)),
};
