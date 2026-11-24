import {useEffect, useRef, useState} from "react";
import {api} from "../api/client";
import type {Run} from "../api/types";
import {StatusBadge} from "../components/badges";
import {EmptyState, ErrorState, Loading} from "../components/feedback";
import {count, dateTime, duration} from "../lib/format";
import {useAsync} from "../lib/useAsync";
import {href} from "../lib/route";

function RunPanel({run, onClose}: {run: Run; onClose: () => void}) {
  const [trace] = useAsync(signal => api.trace(run.id, signal), [run.id]);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <section className="panel" aria-labelledby="run-title">
    <div className="panel__head">
      <h2 id="run-title">Run <code>{run.id}</code></h2>
      <button ref={close} className="btn btn--small" onClick={onClose}>Close</button>
    </div>
    <dl className="facts">
      <div><dt>Status</dt><dd><StatusBadge status={run.status} /></dd></div>
      <div><dt>Score</dt><dd>{run.score ?? "—"}</dd></div>
      <div><dt>Agent time</dt><dd>{duration(run.agent_duration_seconds)}</dd></div>
      <div><dt>Tokens</dt><dd>{count(run.input_tokens + run.output_tokens)}</dd></div>
      <div><dt>Model calls</dt><dd>{count(run.model_calls)}</dd></div>
      <div><dt>Tool calls</dt><dd>{count(run.tool_calls)}</dd></div>
    </dl>
    {run.failure_message && <div className="callout callout--error"><div><strong>Failure</strong><p>{run.failure_message}</p></div></div>}
    <h3>Execution trace</h3>
    {trace.status === "loading" && <Loading label="Loading trace" />}
    {trace.status === "error" && <ErrorState error={trace.error} title="Could not load trace" />}
    {trace.status === "ready" && <pre className="code">{trace.data.timeline || "No trace events were recorded."}</pre>}
  </section>;
}

export function RunsPage({refreshKey}: {refreshKey: number}) {
  const [state, reload] = useAsync(signal => api.runs(signal), [refreshKey]);
  const [selected, setSelected] = useState<Run | null>(null);
  return <>
    <div className="page-head">
      <div><p className="eyebrow">SWE-task evaluation</p><h1>Runs</h1></div>
      <button className="btn" onClick={reload}>Refresh</button>
    </div>
    {state.status === "loading" && <Loading label="Loading runs" />}
    {state.status === "error" && <ErrorState error={state.error} onRetry={reload} title="Could not load runs" />}
    {state.status === "ready" && (state.data.length === 0
      ? <EmptyState title="No evaluation runs yet">
        <p>Start one from <a href={href.experiments}>Experiments</a>, or open the <a href={href.reports}>suite reports</a>.</p>
      </EmptyState>
      : <div className="table-wrap"><table>
        <thead><tr><th>Run</th><th>Task</th><th>Agent</th><th>Status</th><th className="num">Score</th><th className="num">Duration</th><th>Started</th></tr></thead>
        <tbody>{state.data.map(run => <tr key={run.id}>
          <td><button className="link" onClick={() => setSelected(run)}>{run.id}</button></td>
          <td>{run.task_id}</td><td>{run.agent}</td>
          <td><StatusBadge status={run.status} /></td>
          <td className="num">{run.score ?? "—"}</td>
          <td className="num">{duration(run.agent_duration_seconds)}</td>
          <td>{dateTime(run.created_at)}</td>
        </tr>)}</tbody>
      </table></div>)}
    {selected && <RunPanel run={selected} onClose={() => setSelected(null)} />}
  </>;
}
