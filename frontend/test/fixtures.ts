import type {Comparison, SuiteReport, ReportSummary} from "../src/api/types";

const field = (matched: boolean) => ({present: true, valid: true, matched});

export const report: SuiteReport = {
  schema_version: 1,
  suite: {id: "task-cards-demo", name: "Task cards", version: "1", fingerprint: "ab".repeat(32), n_cases: 3},
  run: {
    source: "replay", provider: "replay", model: "replay", base_url_host: null,
    started_at: "2026-01-01T10:00:00Z", finished_at: "2026-01-01T10:00:01Z", concurrency: 1,
  },
  cases: [
    {id: "t01", status: "ok", error: null, output_chars: 10, latency_ms: null, prompt_tokens: null,
      completion_tokens: null, finish_reason: "replay",
      check: {passed: true, score: 1, format_valid: true, detail: "ok",
        fields: {TASK: field(true), DUE: field(true)}}},
    {id: "t02", status: "ok", error: null, output_chars: 10, latency_ms: null, prompt_tokens: null,
      completion_tokens: null, finish_reason: "replay",
      check: {passed: false, score: 0.5, format_valid: true, detail: "DUE mismatch",
        fields: {TASK: field(true), DUE: field(false)}}},
    {id: "t03", status: "error", error: "replay output missing", check: null, output_chars: null,
      latency_ms: null, prompt_tokens: null, completion_tokens: null, finish_reason: null},
  ],
  aggregate: {
    n: 3, n_failed: 1, n_scored: 2, format_valid_rate: 1, pass_rate: 0.5, mean_score: 0.75,
    field_accuracy: {TASK: 1, DUE: 0.5, NOTE: null},
    latency_ms: {p50: null, p95: null, method: "nearest-rank", n: 0},
    tokens: {prompt: null, completion: null, cases_reporting: 0},
  },
  note: "Deterministic checks only; not a human preference judgement.",
};

const summary = (id: string): ReportSummary => ({
  report_id: id, suite_id: "task-cards-demo", suite_name: "Task cards", suite_version: "1",
  model: "replay", provider: "replay", source: "replay", n: 8, n_failed: 0, pass_rate: 0.5,
  format_valid_rate: 1, finished_at: "2026-01-01T10:00:01Z",
});

export const comparison: Comparison = {
  suite_id: "task-cards-demo", fingerprint_match: true, warnings: [], n_paired: 8, n_unpaired: 0,
  b_better: 3, tie: 4, a_better: 1, format_valid_b_only: 2, format_valid_a_only: 0,
  passed_b_only: 2, passed_a_only: 1, format_valid_rate_delta: 0.25, pass_rate_delta: -0.125,
  mean_score_delta: 0.05, field_accuracy_delta: {TASK: 0, DUE: 0.125, NOTE: null},
  a_source: "replay", b_source: "replay", a: summary("chatty"), b: summary("good"),
};

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: {"content-type": "application/json", ...headers},
  });
}
