// Thin client for the local FastAPI server.
import type { User } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const TOKEN_KEY = "cr_token";
const USER_KEY = "cr_user";

let base = "";
let onAuthLost: (() => void) | null = null;

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Works out where the API lives: same origin when the UI is served by the
 *  server itself, the sidecar port inside Tauri, or 127.0.0.1:8000 in dev. */
export async function initApi(): Promise<void> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<{ port: number }>("server_info");
    base = `http://127.0.0.1:${info.port}`;
  } else if (import.meta.env.DEV) {
    base = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
  } else {
    base = "";
  }
}

export const apiBase = () => base;

export function setAuthLostHandler(fn: () => void) { onAuthLost = fn; }

function safeGet(k: string): string | null { try { return sessionStorage.getItem(k); } catch { return null; } }
function safeSet(k: string, v: string | null) {
  try { if (v === null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch { /* ignore */ }
}

export const auth = {
  token: () => safeGet(TOKEN_KEY),
  user: (): User | null => { const u = safeGet(USER_KEY); return u ? JSON.parse(u) as User : null; },
  set(token: string, user: User) { safeSet(TOKEN_KEY, token); safeSet(USER_KEY, JSON.stringify(user)); },
  clear() { safeSet(TOKEN_KEY, null); safeSet(USER_KEY, null); },
};

export function url(path: string, withToken = false): string {
  const t = auth.token();
  if (!withToken || !t) return base + path;
  return base + path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const t = auth.token();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(base + path, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  } catch {
    throw new ApiError(0, "Cannot reach the Clinic Records server. Is it running?");
  }
  if (res.status === 401 || res.status === 423) {
    if (!path.startsWith("/api/auth/login")) { auth.clear(); onAuthLost?.(); }
  }
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    let msg = (data && data.detail) || `Request failed (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    throw new ApiError(res.status, String(msg));
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body ?? {}),
  put: <T>(p: string, body: unknown) => request<T>("PUT", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
  upload: <T>(p: string, form: FormData) => request<T>("POST", p, undefined, form),
};
