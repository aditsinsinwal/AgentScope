import {type ReactNode, useState} from "react";
import {api, DEMO_BANNER, isDemo} from "../api/client";
import {href} from "../lib/route";
import {useAsync} from "../lib/useAsync";
import {TokenField} from "./TokenField";

const NAV = [
  {key: "runs", label: "Runs", to: href.runs},
  {key: "experiments", label: "Experiments", to: href.experiments},
  {key: "reports", label: "Suite reports", to: href.reports},
  {key: "compare", label: "Compare", to: href.compare()},
] as const;

export function Layout({section, children, onTokenChange}: {
  section: string;
  children: ReactNode;
  onTokenChange: () => void;
}) {
  const [nonce, setNonce] = useState(0);
  const [health] = useAsync(signal => api.health(signal), [nonce]);
  const version = health.status === "ready" ? health.data.version : null;
  const demo = isDemo();
  return <div className="shell">
    <a className="skip" href="#main">Skip to content</a>
    <header className="topbar">
      <a className="brand" href={href.reports} aria-label="AgentScope home">
        <span className="brand__mark" aria-hidden="true">AS</span>AgentScope
      </a>
      <nav aria-label="Primary">
        {NAV.map(item => <a key={item.key} href={item.to}
          aria-current={section === item.key ? "page" : undefined}>{item.label}</a>)}
        {!demo && <a href="/docs">API docs</a>}
      </nav>
      <div className="topbar__right">
        {!demo && <TokenField onChange={() => {
          setNonce(value => value + 1);
          onTokenChange();
        }} />}
        <span className={`conn${version ? " conn--on" : ""}`} role="status">
          <i aria-hidden="true" />{version ? (demo ? `demo v${version}` : `API v${version}`) : health.status === "loading" ? "connecting" : "API unreachable"}
        </span>
      </div>
    </header>
    <main id="main" tabIndex={-1}>{children}</main>
    <footer className="footer">
      <span>Deterministic checks only. Not a human preference judgement.</span>
    </footer>
    {demo && <div className="demo-banner" role="note">{DEMO_BANNER}</div>}
  </div>;
}
