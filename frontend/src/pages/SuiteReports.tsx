import {useState} from "react";
import {api} from "../api/client";
import {SourceBadge} from "../components/badges";
import {EmptyState, ErrorState, Loading} from "../components/feedback";
import {count, dateTime, pct} from "../lib/format";
import {href} from "../lib/route";
import {useAsync} from "../lib/useAsync";

export function SuiteReportsPage({refreshKey}: {refreshKey: number}) {
  const [state, reload] = useAsync(signal => api.reports(signal), [refreshKey]);
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (id: string) =>
    setPicked(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id].slice(-2));
  const [a, b] = picked;
  return <>
    <div className="page-head">
      <div><p className="eyebrow">Prompt suites</p><h1>Suite reports</h1></div>
      <div className="actions">
        <a className={`btn${picked.length === 2 ? " btn--primary" : ""}`}
          aria-disabled={picked.length !== 2}
          href={picked.length === 2 ? href.compare(a, b) : undefined}
          onClick={event => picked.length !== 2 && event.preventDefault()}>
          Compare selected ({picked.length}/2)</a>
        <button className="btn" onClick={reload}>Refresh</button>
      </div>
    </div>
    {state.status === "loading" && <Loading label="Loading reports" />}
    {state.status === "error" && <ErrorState error={state.error} onRetry={reload} title="Could not load suite reports" />}
    {state.status === "ready" && (state.data.length === 0
      ? <EmptyState title="No suite reports found">
        <p>Write one with <code>agentscope suite run --suite … --out artifacts/suite-reports/&lt;name&gt;</code>,
          or point <code>AGENTSCOPE_REPORTS_DIR</code> at a directory of report folders (each containing <code>results.json</code>).</p>
      </EmptyState>
      : <div className="table-wrap"><table>
        <caption className="sr-only">Suite reports. Select two to compare.</caption>
        <thead><tr><th><span className="sr-only">Select</span></th><th>Report</th><th>Suite</th><th>Model</th><th>Source</th>
          <th className="num">Cases</th><th className="num">Pass rate</th><th className="num">Format valid</th><th>Finished</th></tr></thead>
        <tbody>{state.data.map(row => <tr key={row.report_id} className={picked.includes(row.report_id) ? "is-selected" : undefined}>
          <td><input type="checkbox" aria-label={`Select ${row.report_id} for comparison`}
            checked={picked.includes(row.report_id)} onChange={() => toggle(row.report_id)} /></td>
          <td><a href={href.report(row.report_id)}><strong>{row.report_id}</strong></a></td>
          <td>{row.suite_id} <span className="muted">v{row.suite_version}</span></td>
          <td>{row.model} <span className="muted">{row.provider}</span></td>
          <td><SourceBadge source={row.source} /></td>
          <td className="num">{count(row.n)}{row.n_failed > 0 && <span className="muted"> ({row.n_failed} failed)</span>}</td>
          <td className="num">{pct(row.pass_rate, 1)}</td>
          <td className="num">{pct(row.format_valid_rate, 1)}</td>
          <td>{dateTime(row.finished_at)}</td>
        </tr>)}</tbody>
      </table></div>)}
  </>;
}
