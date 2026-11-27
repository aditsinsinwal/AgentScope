import {DEMO_BANNER, isDemo} from "../api/client";

/** Persistent demo notice. Rendered outside the ErrorBoundary so it survives a crash. */
export function DemoBanner() {
  return isDemo() ? <div className="demo-banner" role="note">{DEMO_BANNER}</div> : null;
}
