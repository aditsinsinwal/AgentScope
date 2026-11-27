import {App} from "./App";
import {DemoBanner} from "./components/DemoBanner";
import {ErrorBoundary} from "./components/ErrorBoundary";

export function Root() {
  return <>
    <ErrorBoundary><App /></ErrorBoundary>
    <DemoBanner />
  </>;
}
