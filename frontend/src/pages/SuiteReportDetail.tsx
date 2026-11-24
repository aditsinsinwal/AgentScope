import {useMemo, useState} from "react";
import {api} from "../api/client";
import type {CaseResult} from "../api/types";
import {PassBadge, SourceBadge} from "../components/badges";
import {FieldAccuracyChart} from "../components/charts";
import {ErrorState, Loading} from "../components/feedback";
import {Tile} from "../components/Tile";
import {count, dateTime, ms, NOT_REPORTED, pct, score, tokenTotal} from "../lib/format";
import {href} from "../lib/route";
import {useAsync} from "../lib/useAsync";

export function failingFields(c: CaseResult): string[] {
  const fields = c.check?.fields;
  if (!fields) return [];
  return Object.entries(fields)
    .filter(([, f]) => f.matched === false || !f.present || !f.valid)
    .map(([name]) => name);
}

type Filter = "all" | "failed" | "passed" | "format" | "error";

export function filterCases(cases: CaseResult[], filter: Filter, query: string): CaseResult[] {
  const needle = query.trim().toLowerCase();
  return cases.filter(c => {
    if (needle && !c.id.toLowerCase().includes(needle)) return false;
    switch (filter) {
      case "failed": return c.status === "ok" && c.check?.passed === false;
      case "passed": return c.check?.passed === true;
      case "format": return c.check?.format_valid === false;
      case "error": return c.status === "error";
      default: return true;
    }
  });
}

export function SuiteReportDetailPage({id}: {id: string}) {
  const [state, reload] = useAsync(signal => api.report(id, signal), [id]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const cases = state.status === "ready" ? state.data.cases : [];
  const shown = useMemo(() => filterCases(cases, filter, query), [cases, filter, query]);
  return <>
    <p className="crumbs"><a href={href.reports}>Suite reports</a> / <span>{id}</span></p>
    {state.status === "loading" && <Loading label="Loading report" />}
    {state.status === "error" && <ErrorState error={state.error} onRetry={reload} title="Could not load report" />}
    {state.status === "ready" && (() => {
      const {suite, run, aggregate: agg} = state.data;
      return <>
        <div className="page-head">
          <div>
            <p className="eyebrow">{suite.id} <span className="muted">v{suite.version}</span></p>
            <h1>{id} <SourceBadge source={run.source} /></h1>
            <p className="meta">
              <span>{run.provider} / <strong>{run.model}</strong>{run.base_url_host && ` @ ${run.base_url_host}`}</span>
              <span>finished {dateTime(run.finished_at)}</span>
              <span>fingerprint <code>{suite.fingerprint.slice(0, 12)}</code></span>
            </p>
          </div>
          <a className="btn" href={href.compare(id)}>Compare…</a>
        </div>
        {run.source === "replay" && <div className="callout callout--replay" role="note">
          <div><strong>REPLAY: recorded outputs, not a model run.</strong>
            <p>These scores come from re-checking previously recorded outputs. No model was called, so latency and token counts are not reported.</p></div>
        </div>}
        <section aria-label="Aggregate metrics" className="tiles">
          <Tile label="Pass rate" value={pct(agg.pass_rate, 1)} note={`${agg.n_scored} scored of ${agg.n} cases`} />
          <Tile label="Format valid" value={pct(agg.format_valid_rate, 1)} />
          <Tile label="Mean content score" value={score(agg.mean_score)} note="field matches; ignores format" />
          <Tile label="Latency p50" value={ms(agg.latency_ms.p50)} note={agg.latency_ms.n ? `n=${agg.latency_ms.n}` : undefined} />
          <Tile label="Latency p95" value={ms(agg.latency_ms.p95)} note={agg.latency_ms.n ? agg.latency_ms.method : undefined} />
          <Tile label="Tokens" value={tokenTotal(agg.tokens)}
            note={agg.tokens.cases_reporting ? `${agg.tokens.cases_reporting} cases reporting` : undefined} />
        </section>
        {agg.n_failed > 0 && <div className="callout callout--error" role="note"><div>
          <strong>{agg.n_failed} case(s) produced no output.</strong><p>Rates cover scored cases only.</p></div></div>}
        <section className="card" aria-labelledby="acc-h">
          <h2 id="acc-h">Per-field accuracy</h2>
          <FieldAccuracyChart accuracy={agg.field_accuracy} />
        </section>
        <section aria-labelledby="cases-h">
          <div className="page-head page-head--tight">
            <h2 id="cases-h">Cases <span className="muted">({shown.length} of {cases.length})</span></h2>
            <div className="filters">
              <label>Filter
                <select value={filter} onChange={event => setFilter(event.target.value as Filter)}>
                  <option value="all">All cases</option><option value="failed">Failed</option>
                  <option value="passed">Passed</option><option value="format">Format invalid</option>
                  <option value="error">Errors</option>
                </select></label>
              <label>Case id
                <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search id" /></label>
            </div>
          </div>
          {shown.length === 0
            ? <p className="muted">No cases match this filter.</p>
            : <div className="table-wrap"><table>
              <thead><tr><th>Case</th><th>Format</th><th>Result</th><th className="num">Score</th><th>Failing fields</th><th>Error / detail</th></tr></thead>
              <tbody>{shown.map(c => <tr key={c.id}>
                <td><code>{c.id}</code></td>
                <td>{c.check ? (c.check.format_valid ? "valid" : <span className="bad">invalid</span>) : NOT_REPORTED}</td>
                <td>{c.check ? <PassBadge passed={c.check.passed} /> : <span className="badge badge--bad">error</span>}</td>
                <td className="num">{score(c.check?.score)}</td>
                <td>{failingFields(c).join(", ") || "—"}</td>
                <td className="wrap">{c.error ?? (c.check && !c.check.passed ? c.check.detail : "—")}</td>
              </tr>)}</tbody>
            </table></div>}
        </section>
        <p className="muted">{count(suite.n_cases)} cases in suite. {state.data.note}</p>
      </>;
    })()}
  </>;
}
