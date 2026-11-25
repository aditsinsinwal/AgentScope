import {cleanup, render, screen} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {api, ApiError, demoUrl, DEMO_BANNER} from "../src/api/client";
import {App} from "../src/App";
import {jsonResponse, report} from "./fixtures";

describe("static demo mode", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_DEMO", "1");
    window.location.hash = "";
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("maps API paths to static JSON files under the base path", () => {
    const base = import.meta.env.BASE_URL;
    expect(demoUrl("/api/v1/health")).toBe(`${base}demo/api/v1/health.json`);
    expect(demoUrl("/api/v1/suite-reports")).toBe(`${base}demo/api/v1/suite-reports.json`);
    expect(demoUrl("/api/v1/suite-reports/replay-good"))
      .toBe(`${base}demo/api/v1/suite-reports/replay-good.json`);
    expect(demoUrl("/api/v1/suite-compare?a=replay-chatty&b=replay-good"))
      .toBe(`${base}demo/api/v1/suite-compare/replay-chatty__replay-good.json`);
  });

  it("reads static files, sends no token, and never touches /api", async () => {
    window.sessionStorage.setItem("agentscope.api-token", "s3cret");
    const fetchMock = vi.fn(async () => jsonResponse(report));
    vi.stubGlobal("fetch", fetchMock);
    await api.report("replay-good");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("demo/api/v1/suite-reports/replay-good.json");
    expect(url).not.toMatch(/^\/api\//);
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("refuses live-only endpoints and writes without a network call", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const error = await api.runs().catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({code: "demo_unavailable"});
    await expect(api.createTask("x.yaml")).rejects.toMatchObject({code: "demo_unavailable"});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the banner, hides the token field and marks Runs as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    window.location.hash = "#/runs";
    render(<App />);
    expect(screen.getByRole("note").textContent).toBe(DEMO_BANNER);
    expect(DEMO_BANNER).toBe("Static demo: replayed recorded outputs, no model was called.");
    expect(screen.queryByLabelText("API token")).toBeNull();
    expect(await screen.findByText("Not available in the static demo")).toBeTruthy();
  });

  it("has no banner outside demo mode", () => {
    vi.stubEnv("VITE_DEMO", "");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(<App />);
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByLabelText("API token")).toBeTruthy();
  });
});
