import type {
  Comparison, ExperimentResults, ExperimentView, Health, ReportSummary, Run, RunBatchView,
  SuiteReport, TaskView, TraceView,
} from "./types";

const TOKEN_KEY = "agentscope.api-token";

/** Bearer token lives in sessionStorage only: it is gone when the tab closes. */
export function getToken(): string {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(value: string): void {
  try {
    if (value) window.sessionStorage.setItem(TOKEN_KEY, value);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token simply is not remembered */
  }
}

/** Error carrying the API's error envelope: {code, message, request_id}. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Envelope = {code?: unknown; message?: unknown; request_id?: unknown};

/** True in the static GitHub Pages build (`VITE_DEMO=1`): data is read from committed JSON. */
export const isDemo = (): boolean => import.meta.env.VITE_DEMO === "1";

export const DEMO_UNAVAILABLE = "demo_unavailable";
export const DEMO_BANNER = "Static demo: replayed recorded outputs, no model was called.";

/**
 * Map a live API path to the static file written by scripts/build_demo_data.py.
 * Endpoints that need the live server (runs, experiments, writes) are not in the demo.
 */
export function demoUrl(path: string, method = "GET"): string {
  const [pathname = "", search = ""] = path.split("?");
  const base = `${import.meta.env.BASE_URL}demo/api/v1`;
  const unavailable = () => new ApiError(
    "Not available in the static demo. It serves recorded replay reports only.",
    0, DEMO_UNAVAILABLE, null);
  if (method !== "GET") throw unavailable();
  if (pathname === "/api/v1/health") return `${base}/health.json`;
  if (pathname === "/api/v1/suite-reports") return `${base}/suite-reports.json`;
  const report = /^\/api\/v1\/suite-reports\/([^/]+)$/.exec(pathname);
  if (report) return `${base}/suite-reports/${report[1]}.json`;
  if (pathname === "/api/v1/suite-compare") {
    const query = new URLSearchParams(search);
    const a = query.get("a"), b = query.get("b");
    if (a && b) return `${base}/suite-compare/${encodeURIComponent(a)}__${encodeURIComponent(b)}.json`;
  }
  throw unavailable();
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const demo = isDemo();
  const url = demo ? demoUrl(path, init.method ?? "GET") : path;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const token = demo ? "" : getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(url, {...init, headers});
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
    throw new ApiError("Could not reach the AgentScope API.", 0, "network_error", null);
  }
  if (demo && (!response.ok || !(response.headers.get("content-type") ?? "").includes("application/json"))) {
    throw new ApiError(
      "This report or pair is not in the static demo.", response.status, DEMO_UNAVAILABLE, null);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as Envelope | null;
    const str = (value: unknown): string | null => (typeof value === "string" ? value : null);
    throw new ApiError(
      str(body?.message) ?? `API request failed (${response.status})`,
      response.status,
      str(body?.code) ?? "http_error",
      str(body?.request_id) ?? response.headers.get("x-request-id"),
    );
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      demo
        ? "The demo data file could not be loaded."
        : "The API returned an unexpected response. Start AgentScope with `agentscope serve`.",
      response.status,
      "unexpected_response",
      null,
    );
  }
  return (await response.json()) as T;
}

const enc = encodeURIComponent;
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/api/v1/health", {signal}),
  runs: (signal?: AbortSignal) => request<Run[]>("/api/v1/runs?limit=100", {signal}),
  trace: (id: string, signal?: AbortSignal) =>
    request<TraceView>(`/api/v1/runs/${enc(id)}/trace`, {signal}),
  createTask: (definitionPath: string) =>
    post<TaskView>("/api/v1/tasks", {definition_path: definitionPath}),
  createExperiment: (body: {name: string; task_ids: string[]; seed: number}) =>
    post<ExperimentView>("/api/v1/experiments", {...body, configurations: [{name: "mock"}]}),
  runExperiment: (id: string) => post<RunBatchView>(`/api/v1/experiments/${enc(id)}/run`),
  experiment: (id: string, signal?: AbortSignal) =>
    request<ExperimentView>(`/api/v1/experiments/${enc(id)}`, {signal}),
  experimentResults: (id: string, signal?: AbortSignal) =>
    request<ExperimentResults>(`/api/v1/experiments/${enc(id)}/results`, {signal}),
  reports: (signal?: AbortSignal) => request<ReportSummary[]>("/api/v1/suite-reports", {signal}),
  report: (id: string, signal?: AbortSignal) =>
    request<SuiteReport>(`/api/v1/suite-reports/${enc(id)}`, {signal}),
  compare: (a: string, b: string, signal?: AbortSignal) =>
    request<Comparison>(`/api/v1/suite-compare?a=${enc(a)}&b=${enc(b)}`, {signal}),
};
