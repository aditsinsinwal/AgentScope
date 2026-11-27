import type {ReactNode} from "react";
import {ApiError, DEMO_UNAVAILABLE} from "../api/client";

export function ErrorState({error, onRetry, title = "Request failed"}: {
  error: Error;
  onRetry?: () => void;
  title?: string;
}) {
  const api = error instanceof ApiError ? error : null;
  if (api?.code === DEMO_UNAVAILABLE) return <DemoUnavailable detail={error.message} />;
  const needsToken = api?.status === 401;
  return <div className="callout callout--error" role="alert">
    <div>
      <strong>{needsToken ? "Authentication required" : title}</strong>
      <p>{needsToken
        ? "This server requires an API token. Enter it in the token field in the header."
        : error.message}</p>
      {api && <p className="meta">
        <span>HTTP {api.status || "—"}</span>
        <span>code <code>{api.code}</code></span>
        {api.requestId && <span>request id <code>{api.requestId}</code></span>}
      </p>}
    </div>
    {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
  </div>;
}

export function Loading({label = "Loading"}: {label?: string}) {
  return <div className="loading" role="status" aria-live="polite">
    <span className="loading__bar" /><span className="loading__bar" /><span className="loading__bar" />
    <span className="sr-only">{label}…</span>
  </div>;
}

export function EmptyState({title, children}: {title: string; children?: ReactNode}) {
  return <div className="empty">
    <h3>{title}</h3>
    {children}
  </div>;
}

/** Shown instead of pages that need the live server when running the static demo. */
export function DemoUnavailable({name, detail}: {name?: string; detail?: string}) {
  return <div className="callout" role="status">
    <div>
      <strong>Not available in the static demo</strong>
      <p>{detail ?? `${name ?? "This page"} needs a running AgentScope server.`}</p>
      <p>Run <code>agentscope serve</code> locally to use it. The demo shows suite reports and the
        compare view built from recorded replay outputs.</p>
    </div>
  </div>;
}
