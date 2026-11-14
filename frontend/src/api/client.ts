// Thin wrapper around fetch for the LaundryConnect API.
// The Vite dev server proxies /api to the FastAPI backend (vite.config.ts).

const TOKEN_KEY = "lc_token";

// sessionStorage: the login ends when the browser tab closes. A production
// build should move to an httpOnly cookie so scripts can't read the token.
let token: string | null = safeGet();

function safeGet(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(value: string | null) {
  token = value;
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) – keep the token in memory only */
  }
}

export function getToken() {
  return token;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

// Turn FastAPI error bodies into one readable sentence
function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(" → ");
        const msg = (d.msg ?? "Invalid value").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return status === 0 ? "Can't reach the server" : `Request failed (${status})`;
}

type Options = {
  method?: string;
  json?: unknown;
  form?: FormData | URLSearchParams;
  headers?: Record<string, string>;
};

let onUnauthorised: (() => void) | null = null;
export function setUnauthorisedHandler(fn: () => void) {
  onUnauthorised = fn;
}

async function send(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running?", null);
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && token && onUnauthorised) onUnauthorised();
    throw new ApiError(res.status, messageFrom(detail, res.status), detail);
  }
  return res;
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const res = await send(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// For images and documents behind login: returns an object URL to show or open
export async function apiBlobUrl(path: string): Promise<string> {
  const res = await send(path, {});
  return URL.createObjectURL(await res.blob());
}
