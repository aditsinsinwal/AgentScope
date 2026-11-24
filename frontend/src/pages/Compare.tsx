import {api} from "../api/client";
import {DeltaChart, PairedSplit} from "../components/charts";
import {SourceBadge} from "../components/badges";
import {ErrorState, Loading} from "../components/feedback";
import {Tile} from "../components/Tile";
import {pp, signed} from "../lib/format";
import {href} from "../lib/route";
import {useAsync} from "../lib/useAsync";

export const COMPARE_NOTE =
  "Counts only, no significance. Deterministic checks, not a human preference judgement.";

function Picker({label, value, options, onChange}: {
  label: string; value: string; options: string[]; onChange: (value: string) => void;
}) {
  return <label>{label}
    <select value={value} onChange={event => onChange(event.target.value)}>
      <option value="">Select a report…</option>
      {options.map(option => <option key={option} value={option}>{option}</option>)}
    </select></label>;
}

export function ComparePage({a, b}: {a: string; b: string}) {
  const [list] = useAsync(signal => api.reports(signal), []);
  const [state, reload] = useAsync(
    signal => (a && b ? api.compare(a, b, signal) : Promise.resolve(null)), [a, b]);
  const options = list.status === "ready" ? list.data.map(row => row.report_id) : [];
  const go = (nextA: string, nextB: string) => {
    window.location.hash = href.compare(nextA, nextB);
  };
  return <>
    <div className="page-head"><div><p className="eyebrow">Paired comparison</p><h1>Compare reports</h1></div></div>
    <div className="filters card">
      <Picker label="A (baseline)" value={a} options={options} onChange={value => go(value, b)} />
      <Picker label="B (candidate)" value={b} options={options} onChange={value => go(a, value)} />
    </div>
    <p className="note" role="note">{COMPARE_NOTE}</p>
    {list.status === "error" && <ErrorState error={list.error} title="Could not load suite reports" />}
    {!(a && b) && <p className="muted">Choose two reports of the same suite to compare.</p>}
    {a && b && state.status === "loading" && <Loading label="Comparing" />}
    {a && b && state.status === "error" && <ErrorState error={state.error} onRetry={reload} title="Could not compare" />}
    {state.status === "ready" && state.data && (() => {
      const c = state.data;
      return <>
        <p className="meta">
          <span>A: <a href={href.report(c.a.report_id)}>{c.a.report_id}</a> <SourceBadge source={c.a_source} /></span>
          <span>B: <a href={href.report(c.b.report_id)}>{c.b.report_id}</a> <SourceBadge source={c.b_source} /></span>
          <span>suite <code>{c.suite_id}</code></span>
        </p>
        {c.warnings.map(text => <div key={text} className="callout callout--replay" role="note"><div><p>{text}</p></div></div>)}
        <section className="tiles" aria-label="Paired case counts">
          <Tile label="B better" value={String(c.b_better)} note="B scored higher" />
          <Tile label="Tie" value={String(c.tie)} note="same score" />
          <Tile label="A better" value={String(c.a_better)} note="A scored higher" />
          <Tile label="Paired cases" value={String(c.n_paired)} note={c.n_unpaired ? `${c.n_unpaired} unpaired` : "all cases paired"} />
        </section>
        <PairedSplit a={c.a_better} tie={c.tie} b={c.b_better} />
        <p className="muted">A case counts as a tie when both sides have the same field-match score. That score ignores format validity, so a format-only difference shows up in the pass and format deltas below, not here.</p>
        <section className="tiles" aria-label="Aggregate deltas (B minus A)">
          <Tile label="Pass rate Δ" value={pp(c.pass_rate_delta)} note={`passed only in B: ${c.passed_b_only}, only in A: ${c.passed_a_only}`} />
          <Tile label="Format valid Δ" value={pp(c.format_valid_rate_delta)} note={`valid only in B: ${c.format_valid_b_only}, only in A: ${c.format_valid_a_only}`} />
          <Tile label="Mean content score Δ" value={signed(c.mean_score_delta)} />
        </section>
        <section className="card" aria-labelledby="delta-h">
          <h2 id="delta-h">Per-field accuracy change (B minus A)</h2>
          <DeltaChart deltas={c.field_accuracy_delta} />
        </section>
      </>;
    })()}
  </>;
}
