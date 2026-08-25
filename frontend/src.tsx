import {type FormEvent, useCallback, useEffect, useMemo, useState} from "react";
import {createRoot} from "react-dom/client";
import "./style.css";

type Run = {
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

type Health = {status: string; version: string; sandbox: string};
type Trace = {run_id: string; timeline: string};
type TaskView = {id: string};
type ExperimentView = {id: string};
type RunBatchView = {run_ids: string[]};

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {...init, headers});
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {message?: string} | null;
    throw new Error(payload?.message || `API request failed (${response.status})`);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      "The API returned an unexpected response. Start AgentScope with `agentscope serve`.",
    );
  }
  return response.json() as Promise<T>;
}

function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, {signal});
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, {method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return "—";
  if (seconds < 0.001) return "<1 ms";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  return `${seconds.toFixed(1)} s`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function MetricCard({label, value, note}: {label: string; value: string; note: string}) {
  return <article className="metric-card">
    <p>{label}</p><strong>{value}</strong><span>{note}</span>
  </article>;
}

function StatusBadge({status}: {status: string}) {
  return <span className={`status status--${status}`}>
    <i aria-hidden="true" />{status.replaceAll("_", " ")}
  </span>;
}

function EmptyState({onCreate}: {onCreate: () => void}) {
  return <div className="empty-state">
    <div className="empty-state__mark" aria-hidden="true">A</div>
    <h3>No evaluation runs yet</h3>
    <p>Run the deterministic example, then refresh this page to inspect its measured result.</p>
    <button className="primary-button" onClick={onCreate}>Run your first evaluation</button>
  </div>;
}

function NewRunDialog({busy, error, onClose, onSubmit}: {
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (value: {taskPath: string; name: string; seed: number}) => Promise<void>;
}) {
  const [taskPath, setTaskPath] = useState("examples/cart-empty-500/task.yaml");
  const [name, setName] = useState("Dashboard evaluation");
  const [seed, setSeed] = useState(0);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void onSubmit({taskPath: taskPath.trim(), name: name.trim(), seed});
  };

  return <>
    <button className="scrim" onClick={onClose} aria-label="Close new evaluation" disabled={busy} />
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="new-run-title">
      <div className="modal__head">
        <div><p className="section-label">Evaluation setup</p><h2 id="new-run-title">New evaluation</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Close new evaluation" disabled={busy}>×</button>
      </div>
      <form onSubmit={submit}>
        <label>Task definition path
          <input value={taskPath} onChange={event => setTaskPath(event.target.value)} required autoFocus />
          <small>Path to a task YAML file on the AgentScope server.</small>
        </label>
        <label>Experiment name
          <input value={name} onChange={event => setName(event.target.value)} required />
        </label>
        <label>Reproducibility seed
          <input type="number" value={seed} onChange={event => setSeed(Number(event.target.value))} />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal__actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary-button" type="submit" disabled={busy || !taskPath.trim() || !name.trim()}>
            {busy ? "Queuing evaluation…" : "Queue evaluation"}
          </button>
        </div>
      </form>
    </section>
  </>;
}

function RunDetail({run, onClose}: {run: Run; onClose: () => void}) {
  const [trace, setTrace] = useState("");
  const [traceError, setTraceError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setTrace("");
    setTraceError("");
    getJson<Trace>(`/api/v1/runs/${encodeURIComponent(run.id)}/trace`, controller.signal)
      .then(value => setTrace(value.timeline || "No trace events were recorded."))
      .catch(reason => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setTraceError(reason instanceof Error ? reason.message : "Unable to load trace");
      });
    return () => controller.abort();
  }, [run.id]);

  return <aside className="detail-panel" role="dialog" aria-modal="true" aria-labelledby="detail-title">
    <div className="detail-panel__head">
      <div><p className="section-label">Run detail</p><h2 id="detail-title">{run.id}</h2></div>
      <button className="icon-button" onClick={onClose} aria-label="Close run detail">×</button>
    </div>
    <div className="detail-grid">
      <div><span>Status</span><StatusBadge status={run.status} /></div>
      <div><span>Score</span><strong>{run.score === null ? "—" : `${run.score} / 100`}</strong></div>
      <div><span>Agent time</span><strong>{formatDuration(run.agent_duration_seconds)}</strong></div>
      <div><span>Tokens</span><strong>{formatNumber(run.input_tokens + run.output_tokens)}</strong></div>
      <div><span>Model calls</span><strong>{formatNumber(run.model_calls)}</strong></div>
      <div><span>Tool calls</span><strong>{formatNumber(run.tool_calls)}</strong></div>
    </div>
    {run.failure_message && <div className="failure-box"><strong>Failure</strong><p>{run.failure_message}</p></div>}
    <div className="trace-head"><h3>Execution trace</h3><span>Read only</span></div>
    {traceError
      ? <p className="inline-error">{traceError}</p>
      : <pre className="trace">{trace || "Loading trace…"}</pre>}
  </aside>;
}

function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<Run | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [newRunOpen, setNewRunOpen] = useState(false);
  const [startingRun, setStartingRun] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async (background = false) => {
    background ? setRefreshing(true) : setLoading(true);
    try {
      const [runData, healthData] = await Promise.all([
        getJson<Run[]>("/api/v1/runs?limit=100"),
        getJson<Health>("/api/v1/health"),
      ]);
      setRuns(runData);
      setHealth(healthData);
      setError("");
      setLastUpdated(new Date());
      setSelected(current => current
        ? runData.find(run => run.id === current.id) ?? null
        : null);
    } catch (reason) {
      setHealth(null);
      setError(reason instanceof Error ? reason.message : "Unable to connect to AgentScope");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!selected && !newRunOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || startingRun) return;
      setSelected(null);
      setNewRunOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [newRunOpen, selected, startingRun]);

  const startEvaluation = async ({taskPath, name, seed}: {
    taskPath: string;
    name: string;
    seed: number;
  }) => {
    setStartingRun(true);
    setActionError("");
    try {
      const task = await postJson<TaskView>("/api/v1/tasks", {definition_path: taskPath});
      const experiment = await postJson<ExperimentView>("/api/v1/experiments", {
        name,
        task_ids: [task.id],
        configurations: [{name: "mock"}],
        seed,
      });
      const batch = await postJson<RunBatchView>(`/api/v1/experiments/${encodeURIComponent(experiment.id)}/run`);
      setNewRunOpen(false);
      setNotice(`${batch.run_ids.length} evaluation ${batch.run_ids.length === 1 ? "was" : "were"} queued.`);
      await load(true);
      window.setTimeout(() => void load(true), 1_200);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to queue the evaluation");
    } finally {
      setStartingRun(false);
    }
  };

  const summary = useMemo(() => {
    const evaluated = runs.filter(run => run.passed !== null);
    const passed = evaluated.filter(run => run.passed).length;
    const scores = evaluated.map(run => Number(run.score)).filter(Number.isFinite);
    const terminal = [
      "completed", "cancelled", "sandbox_failed", "agent_failed", "timed_out",
      "evaluation_failed",
    ];
    return {
      passRate: evaluated.length ? `${Math.round((passed / evaluated.length) * 100)}%` : "—",
      averageScore: scores.length
        ? (scores.reduce((sum, value) => sum + value, 0) / scores.length).toFixed(1)
        : "—",
      active: runs.filter(run => !terminal.includes(run.status)).length,
    };
  }, [runs]);

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/" aria-label="AgentScope home">
        <span>AS</span><strong>AgentScope</strong>
      </a>
      <nav aria-label="Primary">
        <a className="nav-link nav-link--active" href="#runs">Runs</a>
        <a className="nav-link" href="/docs">API</a>
      </nav>
      <div className={`connection ${health ? "connection--online" : ""}`}>
        <i aria-hidden="true" />{health ? `API ${health.version}` : "API offline"}
      </div>
    </header>

    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">Agent reliability infrastructure</p>
          <h1>Know how your agents <em>actually</em> behave.</h1>
          <p className="hero__copy">Objective evaluation, complete execution traces, and reproducible experiments for autonomous coding agents.</p>
        </div>
        <div className="hero__aside">
          <span>Sandbox</span><strong>{health?.sandbox ?? "Unavailable"}</strong>
          <small>Network disabled · hidden tests isolated</small>
        </div>
      </section>

      <section className="metrics" aria-label="Run summary">
        <MetricCard label="Total runs" value={formatNumber(runs.length)} note="Recorded evaluations" />
        <MetricCard label="Solve rate" value={summary.passRate} note="Deterministic passes" />
        <MetricCard label="Average score" value={summary.averageScore} note="Out of 100 points" />
        <MetricCard label="Active now" value={String(summary.active)} note="Queued or running" />
      </section>

      <section className="runs-section" id="runs">
        <div className="section-head">
          <div><p className="section-label">Execution history</p><h2>Recent runs</h2></div>
          <div className="section-actions">
            {lastUpdated && <span>Updated {lastUpdated.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}</span>}
            <button className="primary-button primary-button--compact" onClick={() => {
              setActionError("");
              setNewRunOpen(true);
            }}>＋ New evaluation</button>
            <button className="refresh-button" onClick={() => void load(true)} disabled={refreshing}>
              <span className={refreshing ? "spin" : ""}>↻</span>{refreshing ? "Refreshing" : "Refresh"}
            </button>
          </div>
        </div>

        {error && <div className="error-banner" role="alert">
          <div><strong>Dashboard could not reach the API</strong><p>{error}</p></div>
          <button onClick={() => void load()}>Try again</button>
        </div>}

        {notice && <div className="notice-banner" role="status">
          <span>{notice}</span><button onClick={() => setNotice("")} aria-label="Dismiss message">×</button>
        </div>}

        <div className="table-wrap" aria-busy={loading}>
          {loading
            ? <div className="loading-state"><span /><span /><span /></div>
            : runs.length === 0 && !error
              ? <EmptyState onCreate={() => setNewRunOpen(true)} />
              : runs.length > 0
                ? <table>
                  <thead><tr><th>Run</th><th>Task</th><th>Agent</th><th>Status</th><th>Score</th><th>Duration</th><th>Started</th><th><span className="sr-only">Open</span></th></tr></thead>
                  <tbody>{runs.map(run => <tr key={run.id} onClick={() => setSelected(run)}>
                    <td><button className="run-link" onClick={() => setSelected(run)}>{run.id}</button></td>
                    <td>{run.task_id}</td><td>{run.agent}</td><td><StatusBadge status={run.status} /></td>
                    <td className="score-cell">{run.score ?? "—"}</td>
                    <td>{formatDuration(run.agent_duration_seconds)}</td>
                    <td>{formatDate(run.created_at)}</td><td aria-hidden="true">→</td>
                  </tr>)}</tbody>
                </table>
                : null}
        </div>
      </section>
    </main>
    <footer><span>AgentScope v{health?.version ?? "0.1.0"}</span><span>Measured behavior, never fabricated results.</span></footer>
    {selected && <>
      <button className="scrim" onClick={() => setSelected(null)} aria-label="Close run detail" />
      <RunDetail run={selected} onClose={() => setSelected(null)} />
    </>}
    {newRunOpen && <NewRunDialog
      busy={startingRun}
      error={actionError}
      onClose={() => setNewRunOpen(false)}
      onSubmit={startEvaluation}
    />}
  </div>;
}

const root = document.getElementById("root");
if (!root) throw new Error("AgentScope root element is missing");
createRoot(root).render(<Dashboard />);
