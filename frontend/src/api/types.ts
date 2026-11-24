/** Wire types mirroring agentscope/api/schemas.py and agentscope/suites/results.py. */

export type Health = {status: string; version: string; sandbox: string};

export type Run = {
  id: string;
  task_id: string;
  agent: string;
  status: string;
  seed: number;
  task_hash: string;
  created_at: string;
  updated_at: string;
  passed: boolean | null;
  score: string | null;
  agent_duration_seconds: number;
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  failure_message: string | null;
};

export type TraceView = {run_id: string; timeline: string};
export type TaskView = {id: string; name: string; version: string; fingerprint: string};
export type ExperimentView = {
  id: string;
  name: string;
  task_ids: string[];
  configuration_names: string[];
  seed: number;
};
export type RunBatchView = {run_ids: string[]};
export type ExperimentResults = {
  run_count: number;
  completed_count: number;
  solve_rate: number | null;
  average_score: string;
  average_model_calls: number | null;
  average_tool_calls: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  warning: string;
};

export type ReportSource = "generated" | "replay";

export type ReportSummary = {
  report_id: string;
  suite_id: string;
  suite_name: string;
  suite_version: string;
  model: string;
  provider: string;
  source: ReportSource;
  n: number;
  n_failed: number;
  pass_rate: number | null;
  format_valid_rate: number | null;
  finished_at: string;
};

export type FieldResult = {present: boolean; valid: boolean; matched: boolean | null};

export type CaseResult = {
  id: string;
  status: "ok" | "error";
  error: string | null;
  check: {
    passed: boolean;
    score: number;
    format_valid: boolean;
    fields: Record<string, FieldResult> | null;
    detail: string;
  } | null;
  output_chars: number | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  finish_reason: string | null;
};

export type Aggregate = {
  n: number;
  n_failed: number;
  n_scored: number;
  format_valid_rate: number | null;
  pass_rate: number | null;
  mean_score: number | null;
  field_accuracy: Record<string, number | null>;
  latency_ms: {p50: number | null; p95: number | null; method: string; n: number};
  tokens: {prompt: number | null; completion: number | null; cases_reporting: number};
};

export type SuiteReport = {
  schema_version: number;
  suite: {id: string; name: string; version: string; fingerprint: string; n_cases: number};
  run: {
    source: ReportSource;
    provider: string;
    model: string;
    base_url_host: string | null;
    started_at: string;
    finished_at: string;
    concurrency: number;
  };
  cases: CaseResult[];
  aggregate: Aggregate;
  note: string;
};

export type Comparison = {
  suite_id: string;
  fingerprint_match: boolean;
  warnings: string[];
  n_paired: number;
  n_unpaired: number;
  b_better: number;
  tie: number;
  a_better: number;
  format_valid_b_only: number;
  format_valid_a_only: number;
  passed_b_only: number;
  passed_a_only: number;
  format_valid_rate_delta: number | null;
  pass_rate_delta: number | null;
  mean_score_delta: number | null;
  field_accuracy_delta: Record<string, number | null>;
  a_source: ReportSource;
  b_source: ReportSource;
  a: ReportSummary;
  b: ReportSummary;
};
