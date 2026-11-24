import {NOT_REPORTED, pct, pp} from "../lib/format";

/** Per-field accuracy as horizontal bars (SVG). Null accuracy renders "not reported", not an empty bar. */
export function FieldAccuracyChart({accuracy}: {accuracy: Record<string, number | null>}) {
  const entries = Object.entries(accuracy);
  if (entries.length === 0) return <p className="muted">This checker reports no per-field accuracy.</p>;
  return <ul className="bars" aria-label="Per-field accuracy">
    {entries.map(([name, value]) => <li key={name}>
      <span className="bars__label">{name}</span>
      <svg className="bars__svg" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
        <rect className="bars__track" x="0" y="0" width="100" height="10" rx="2" />
        {value != null && <rect className="bars__fill" x="0" y="0" width={Math.max(0, Math.min(1, value)) * 100} height="10" rx="2" />}
      </svg>
      <span className={`bars__value${value == null ? " muted" : ""}`}>
        {value == null ? NOT_REPORTED : pct(value, 1)}
      </span>
    </li>)}
  </ul>;
}

/** Diverging per-field delta (B minus A) around a centre line. Full scale is +/-100 pp. */
export function DeltaChart({deltas}: {deltas: Record<string, number | null>}) {
  const entries = Object.entries(deltas);
  if (entries.length === 0) return <p className="muted">No per-field accuracy to compare.</p>;
  return <ul className="bars" aria-label="Per-field accuracy change, B minus A">
    {entries.map(([name, value]) => {
      const width = value == null ? 0 : Math.min(1, Math.abs(value)) * 50;
      const x = value != null && value < 0 ? 50 - width : 50;
      return <li key={name}>
        <span className="bars__label">{name}</span>
        <svg className="bars__svg" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
          <rect className="bars__track" x="0" y="0" width="100" height="10" rx="2" />
          {value != null && width > 0 &&
            <rect className={value > 0 ? "bars__fill bars__fill--up" : "bars__fill bars__fill--down"} x={x} y="0" width={width} height="10" />}
          <line className="bars__axis" x1="50" x2="50" y1="0" y2="10" />
        </svg>
        <span className={`bars__value${value == null ? " muted" : ""}`}>{pp(value)}</span>
      </li>;
    })}
  </ul>;
}

/** Stacked A-better / tie / B-better split of paired cases. */
export function PairedSplit({a, tie, b}: {a: number; tie: number; b: number}) {
  const total = a + tie + b;
  const share = (value: number) => (total === 0 ? 0 : (value / total) * 100);
  return <div className="split" role="img"
    aria-label={`${a} cases A better, ${tie} tied, ${b} cases B better`}>
    <div className="split__bar" aria-hidden="true">
      <span className="split__seg split__seg--a" style={{width: `${share(a)}%`}} />
      <span className="split__seg split__seg--tie" style={{width: `${share(tie)}%`}} />
      <span className="split__seg split__seg--b" style={{width: `${share(b)}%`}} />
    </div>
  </div>;
}
