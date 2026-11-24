import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {ErrorState} from "../src/components/feedback";
import {ApiError} from "../src/api/client";
import {ComparePage, COMPARE_NOTE} from "../src/pages/Compare";
import {failingFields, filterCases, SuiteReportDetailPage} from "../src/pages/SuiteReportDetail";
import {comparison, jsonResponse, report} from "./fixtures";

function route(table: Record<string, () => Response>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const hit = Object.entries(table).find(([prefix]) => url.startsWith(prefix));
    return hit ? hit[1]() : jsonResponse({code: "not_found", message: "nope", request_id: "r"}, 404);
  }));
}

describe("pages", () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("report detail shows REPLAY, 'not reported' for null metrics and never invents zeros", async () => {
    route({"/api/v1/suite-reports/good": () => jsonResponse(report)});
    render(<SuiteReportDetailPage id="good" />);
    await screen.findByRole("heading", {name: /good/});
    expect(screen.getAllByText("REPLAY").length).toBeGreaterThan(0);
    const tiles = within(screen.getByLabelText("Aggregate metrics"));
    expect(tiles.getByText("Latency p50").nextElementSibling?.textContent).toBe("not reported");
    expect(tiles.getByText("Tokens").nextElementSibling?.textContent).toBe("not reported");
    expect(tiles.getByText("Pass rate").nextElementSibling?.textContent).toBe("50.0%");
    expect(screen.getByRole("list", {name: "Per-field accuracy"}).textContent).toContain("not reported");
    expect(screen.getByText(/1 case\(s\) produced no output/)).toBeTruthy();
  });

  it("filters the case table", async () => {
    route({"/api/v1/suite-reports/good": () => jsonResponse(report)});
    render(<SuiteReportDetailPage id="good" />);
    await screen.findByText("t01");
    fireEvent.change(screen.getByLabelText("Filter"), {target: {value: "failed"}});
    expect(screen.queryByText("t01")).toBeNull();
    expect(screen.getByText("t02")).toBeTruthy();
    expect(within(screen.getByRole("table")).getByText("DUE")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Filter"), {target: {value: "error"}});
    expect(screen.getByText("replay output missing")).toBeTruthy();
  });

  it("filter helpers", () => {
    expect(failingFields(report.cases[1]!)).toEqual(["DUE"]);
    expect(failingFields(report.cases[2]!)).toEqual([]);
    expect(filterCases(report.cases, "passed", "").map(c => c.id)).toEqual(["t01"]);
    expect(filterCases(report.cases, "all", "T0").length).toBe(3);
  });

  it("compare view shows paired counts, deltas and the counts-only note", async () => {
    route({"/api/v1/suite-reports/compare": () => jsonResponse(comparison),
      "/api/v1/suite-reports": () => jsonResponse([comparison.a, comparison.b])});
    render(<ComparePage a="chatty" b="good" />);
    const counts = within(await screen.findByLabelText("Paired case counts"));
    expect(counts.getByText("B better").nextElementSibling?.textContent).toBe("3");
    expect(counts.getByText("Tie").nextElementSibling?.textContent).toBe("4");
    expect(counts.getByText("A better").nextElementSibling?.textContent).toBe("1");
    const deltas = within(screen.getByLabelText("Aggregate deltas (B minus A)"));
    expect(deltas.getByText("Pass rate Δ").nextElementSibling?.textContent).toBe("-12.5 pp");
    expect(deltas.getByText("Format valid Δ").nextElementSibling?.textContent).toBe("+25.0 pp");
    expect(screen.getByText(COMPARE_NOTE)).toBeTruthy();
    expect(screen.getByRole("list", {name: /accuracy change/i}).textContent).toContain("+12.5 pp");
  });

  it("renders the error envelope message and request id", async () => {
    route({"/api/v1/suite-reports/bad": () =>
      jsonResponse({code: "invalid_report", message: "results.json failed schema validation", request_id: "req-42"}, 422)});
    render(<SuiteReportDetailPage id="bad" />);
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert.textContent).toContain("req-42"));
    expect(alert.textContent).toContain("results.json failed schema validation");
    expect(alert.textContent).toContain("invalid_report");
  });

  it("prompts for a token on 401", () => {
    render(<ErrorState error={new ApiError("missing or invalid bearer token", 401, "unauthorized", "r1")} />);
    expect(screen.getByRole("alert").textContent).toContain("requires an API token");
  });
});
