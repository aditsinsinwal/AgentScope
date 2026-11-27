import {useState} from "react";
import {isDemo} from "./api/client";
import {DemoUnavailable} from "./components/feedback";
import {Layout} from "./components/Layout";
import {useRoute} from "./lib/route";
import {ComparePage} from "./pages/Compare";
import {ExperimentsPage} from "./pages/Experiments";
import {RunsPage} from "./pages/Runs";
import {SuiteReportDetailPage} from "./pages/SuiteReportDetail";
import {SuiteReportsPage} from "./pages/SuiteReports";

export function App() {
  const route = useRoute();
  // Bumped when the token changes so every page refetches with the new credentials.
  const [refreshKey, setRefreshKey] = useState(0);
  const [section = "reports", param] = route.segments;
  let page;
  switch (section) {
    case "runs":
      page = isDemo() ? <DemoUnavailable name="Runs" /> : <RunsPage refreshKey={refreshKey} />;
      break;
    case "experiments":
      page = isDemo() ? <DemoUnavailable name="Experiments" /> : <ExperimentsPage key={refreshKey} />;
      break;
    case "compare":
      page = <ComparePage key={refreshKey} a={route.query.get("a") ?? ""} b={route.query.get("b") ?? ""} />;
      break;
    case "reports":
      page = param
        ? <SuiteReportDetailPage key={`${param}:${refreshKey}`} id={param} />
        : <SuiteReportsPage refreshKey={refreshKey} />;
      break;
    default: page = <SuiteReportsPage refreshKey={refreshKey} />;
  }
  return <Layout section={section} onTokenChange={() => setRefreshKey(value => value + 1)}>{page}</Layout>;
}
