import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {api, ApiError, getToken, setToken} from "../src/api/client";
import {jsonResponse} from "./fixtures";

describe("api client", () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("sends the stored token as a Bearer header, and none when unset", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    await api.reports();
    const first = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(first[1].headers).has("Authorization")).toBe(false);

    setToken("s3cret");
    await api.reports();
    const second = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(new Headers(second[1].headers).get("Authorization")).toBe("Bearer s3cret");
  });

  it("keeps the token in sessionStorage only", () => {
    setToken("abc");
    expect(window.sessionStorage.getItem("agentscope.api-token")).toBe("abc");
    expect(window.localStorage.length).toBe(0);
    setToken("");
    expect(getToken()).toBe("");
  });

  it("turns the error envelope into an ApiError with request id", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      jsonResponse({code: "invalid_report", message: "results.json failed schema validation", request_id: "req-9"}, 422)));
    const error = await api.report("x").catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422, code: "invalid_report", requestId: "req-9",
      message: "results.json failed schema validation",
    });
  });

  it("falls back to a generic message for non-envelope errors and network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", {status: 502})));
    await expect(api.reports()).rejects.toMatchObject({status: 502, code: "http_error"});
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(api.reports()).rejects.toMatchObject({code: "network_error"});
  });

  it("url-encodes ids", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await api.report("a/b c");
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/suite-reports/a%2Fb%20c");
  });
});
