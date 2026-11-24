import {Component, type ErrorInfo, type ReactNode} from "react";

/** Top-level guard: a render error shows a recoverable panel instead of a blank page. */
export class ErrorBoundary extends Component<{children: ReactNode}, {error: Error | null}> {
  state: {error: Error | null} = {error: null};

  static getDerivedStateFromError(error: Error) {
    return {error};
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("dashboard render error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <main className="callout callout--error" role="alert">
      <div>
        <strong>Something went wrong displaying this page.</strong>
        <p>{this.state.error.message}</p>
        <p className="meta"><span>Your data is unaffected; this is a display error.</span></p>
      </div>
      <div className="actions">
        <button className="btn" onClick={() => this.setState({error: null})}>Try again</button>
        <a className="btn" href="#/reports" onClick={() => this.setState({error: null})}>Back to reports</a>
      </div>
    </main>;
  }
}
