import {type FormEvent, useState} from "react";
import {api} from "../api/client";
import type {ExperimentResults, ExperimentView} from "../api/types";
import {ErrorState, Loading} from "../components/feedback";
import {useAsync} from "../lib/useAsync";
import {href} from "../lib/route";

const STORE = "agentscope.experiments";

function loadIds(): string[] {
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(STORE) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function saveIds(ids: string[]): void {
  try {
    window.sessionStorage.setItem(STORE, JSON.stringify(ids));
  } catch {
    /* ignore */
  }
}

function ExperimentCard({id}: {id: string}) {
  const [state] = useAsync(async signal => {
    const [experiment, results] = await Promise.all([
      api.experiment(id, signal), api.experimentResults(id, signal),
    ]);
    return {experiment, results};
  }, [id]);
  if (state.status === "loading") return <Loading label="Loading experiment" />;
  if (state.status === "error") return <ErrorState error={state.error} title={`Experiment ${id}`} />;
  const {experiment, results}: {experiment: ExperimentView; results: ExperimentResults} = state.data;
  return <article className="card">
    <h3>{experiment.name}</h3>
    <p className="meta"><span><code>{experiment.id}</code></span><span>seed {experiment.seed}</span>
      <span>{experiment.configuration_names.join(", ")}</span></p>
    <dl className="facts">
      <div><dt>Runs</dt><dd>{results.run_count}</dd></div>
      <div><dt>Completed</dt><dd>{results.completed_count}</dd></div>
      <div><dt>Solve rate</dt><dd>{results.solve_rate == null ? "not reported" : `${(results.solve_rate * 100).toFixed(0)}%`}</dd></div>
      <div><dt>Average score</dt><dd>{results.average_score}</dd></div>
    </dl>
    <p className="muted">{results.warning}</p>
  </article>;
}

export function ExperimentsPage() {
  const [taskPath, setTaskPath] = useState("examples/cart-empty-500/task.yaml");
  const [name, setName] = useState("Dashboard evaluation");
  const [seed, setSeed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [ids, setIds] = useState(loadIds);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(taskPath.trim());
      const experiment = await api.createExperiment({name: name.trim(), task_ids: [task.id], seed});
      await api.runExperiment(experiment.id);
      const next = [experiment.id, ...ids];
      saveIds(next);
      setIds(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason : new Error(String(reason)));
    } finally {
      setBusy(false);
    }
  };

  return <>
    <div className="page-head"><div><p className="eyebrow">SWE-task evaluation</p><h1>Experiments</h1></div></div>
    <form className="form card" onSubmit={event => void submit(event)}>
      <h2>New evaluation</h2>
      <label>Task definition path
        <input value={taskPath} onChange={event => setTaskPath(event.target.value)} required />
        <small>Path to a task YAML file on the AgentScope server.</small>
      </label>
      <label>Experiment name
        <input value={name} onChange={event => setName(event.target.value)} required />
      </label>
      <label>Reproducibility seed
        <input type="number" value={seed} onChange={event => setSeed(Number(event.target.value))} />
      </label>
      {error && <ErrorState error={error} title="Could not queue the evaluation" />}
      <div><button className="btn btn--primary" type="submit" disabled={busy || !taskPath.trim() || !name.trim()}>
        {busy ? "Queuing…" : "Queue evaluation"}</button></div>
    </form>
    <h2>This session</h2>
    {ids.length === 0
      ? <p className="muted">Experiments you queue here appear below. Their runs are listed under <a href={href.runs}>Runs</a>. The API keeps experiments in memory only.</p>
      : <div className="cards">{ids.map(id => <ExperimentCard key={id} id={id} />)}</div>}
  </>;
}
