import type {
  ApiErrorEnvelope,
  ValidationDetail,
} from "@/lib/types";

/**
 * Base URL of the API. Baked in at build time by Next.js.
 *
 * - `NEXT_PUBLIC_API_BASE_URL` wins when set (see `.env.example`).
 * - Production (backend serving `out/`): `/api/v1`.
 * - Development: `http://localhost:8000/api/v1`.
 */
const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();

export const API_BASE_URL = (
  configuredBase ||
  (process.env.NODE_ENV === "production"
    ? "/api/v1"
    : "http://localhost:8000/api/v1")
).replace(/\/+$/, "");

export const SESSION_EXPIRED_EVENT = "vyos:session-expired";

/**
 * Access token lives in memory only. Never write it to localStorage,
 * sessionStorage, IndexedDB or a cookie — the refresh token is HttpOnly.
 */
let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

export interface ApiErrorOptions {
  status: number;
  code: string;
  details?: ValidationDetail[] | Record<string, unknown> | null;
  requestId?: string | null;
  retryAfterSeconds?: number;
  url?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ValidationDetail[] | Record<string, unknown> | null;
  readonly requestId: string | null;
  readonly retryAfterSeconds?: number;
  readonly url?: string;

  constructor(message: string, options: ApiErrorOptions) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details ?? null;
    this.requestId = options.requestId ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds;
    this.url = options.url;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  static async fromResponse(
    response: Response,
    url?: string,
  ): Promise<ApiError> {
    let message = response.statusText || "Request failed";
    let code = `http_${response.status}`;
    let details: ValidationDetail[] | Record<string, unknown> | null = null;
    let requestId: string | null = null;

    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = (await response.json().catch(() => null)) as
        | ApiErrorEnvelope
        | null;
      if (body && typeof body === "object" && body.error) {
        message = body.error.message || message;
        code = body.error.code || code;
        details = body.error.details ?? null;
        requestId = body.error.request_id ?? null;
      }
    } else {
      const text = await response.text().catch(() => "");
      if (text.trim()) message = text.trim().slice(0, 500);
    }

    const retryAfterHeader = response.headers.get("retry-after");
    const retryAfterSeconds = retryAfterHeader
      ? Number.parseInt(retryAfterHeader, 10)
      : undefined;

    return new ApiError(message, {
      status: response.status,
      code,
      details,
      requestId,
      retryAfterSeconds: Number.isFinite(retryAfterSeconds)
        ? retryAfterSeconds
        : undefined,
      url,
    });
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function buildUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

function networkError(url: string, _cause: unknown): ApiError {
  return new ApiError(
    "Cannot reach the API server. Check that the backend is running and the API base URL is correct.",
    {
      status: 0,
      code: "network_error",
      url,
      details: null,
    },
  );
}

interface RawRequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  headers?: HeadersInit;
  csrf?: boolean;
  token?: string | null;
}

async function rawRequest<T>(
  path: string,
  options: RawRequestOptions = {},
): Promise<T> {
  const url = buildUrl(path);
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (options.csrf) {
    headers.set("X-Requested-With", "vyos-mgmt");
  }
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      credentials: "include",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store",
      mode: "cors",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw networkError(url, error);
  }

  if (!response.ok) {
    throw await ApiError.fromResponse(response, url);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/**
 * Refresh once, serialized across tabs when the Web Locks API is available.
 *
 * Refresh tokens rotate. Two tabs refreshing concurrently would both present
 * the same cookie; the backend treats the second replay as a stolen token and
 * revokes the family. The lock makes the second tab wait until the first has
 * received (and the browser has stored) the rotated cookie.
 */
async function refreshWithCrossTabLock(): Promise<
  import("@/lib/types").TokenResponse
> {
  const perform = () =>
    rawRequest<import("@/lib/types").TokenResponse>("/auth/refresh", {
      method: "POST",
      csrf: true,
    });

  if (typeof navigator !== "undefined" && navigator.locks?.request) {
    return navigator.locks.request("vyos-mgmt:refresh", perform);
  }
  return perform();
}

/**
 * Refresh the session using the HttpOnly cookie. Single-flight: all concurrent
 * callers in this tab share one request; the cross-tab lock covers other tabs.
 */
let refreshInFlight: Promise<import("@/lib/types").TokenResponse> | null = null;

export function refreshSession(): Promise<import("@/lib/types").TokenResponse> {
  if (!refreshInFlight) {
    refreshInFlight = refreshWithCrossTabLock()
      .then((tokens) => {
        setAccessToken(tokens.access_token);
        return tokens;
      })
      .catch((error: unknown) => {
        clearAccessToken();
        throw error;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

const NO_REFRESH_PATHS = ["/auth/login", "/auth/refresh", "/auth/logout"];

function isSessionExpired(error: ApiError): boolean {
  return (
    error.status === 401 &&
    error.code !== "invalid_credentials"
  );
}

async function performRequest<T>(
  path: string,
  options: RawRequestOptions,
  allowRefresh: boolean,
): Promise<T> {
  const token = accessToken;
  try {
    return await rawRequest<T>(path, { ...options, token });
  } catch (error) {
    if (
      !allowRefresh ||
      !(error instanceof ApiError) ||
      error.status !== 401 ||
      NO_REFRESH_PATHS.some((p) => path.startsWith(p))
    ) {
      throw error;
    }

    if (!isSessionExpired(error)) {
      throw error;
    }

    try {
      await refreshSession();
    } catch (refreshError) {
      clearAccessToken();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
      throw refreshError;
    }

    // Retry exactly once with the new access token.
    return rawRequest<T>(path, { ...options, token: accessToken });
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  headers?: HeadersInit;
  csrf?: boolean;
}

export function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return performRequest<T>(path, options, true);
}

export const api = {
  get<T>(path: string, signal?: AbortSignal) {
    return request<T>(path, { method: "GET", signal });
  },
  post<T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) {
    return request<T>(path, { ...options, method: "POST", body });
  },
  put<T>(path: string, body?: unknown) {
    return request<T>(path, { method: "PUT", body });
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, { method: "PATCH", body });
  },
  delete<T>(path: string, body?: unknown) {
    return request<T>(path, { method: "DELETE", body });
  },
};

export function buildQuery(
  params: Record<string, string | number | boolean | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
