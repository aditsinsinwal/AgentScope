import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, describe, expect, it, vi} from "vitest";
import {ErrorBoundary} from "../src/components/ErrorBoundary";
import {parseHash} from "../src/lib/route";

afterEach(cleanup);

describe("robustness", () => {
  it("parseHash survives malformed percent-escapes", () => {
    expect(parseHash("#/reports/%E0%A4%A").segments).toEqual(["reports", "%E0%A4%A"]);
    expect(parseHash("#/reports/a%20b").segments).toEqual(["reports", "a b"]);
  });

  it("ErrorBoundary shows a recoverable panel instead of a blank page", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let broken = true;
    function Maybe() {
      if (broken) throw new Error("kaboom");
      return <p>recovered</p>;
    }
    render(<ErrorBoundary><Maybe /></ErrorBoundary>);
    expect(screen.getByRole("alert").textContent).toContain("kaboom");
    broken = false;
    fireEvent.click(screen.getByText("Try again"));
    expect(screen.getByText("recovered")).toBeTruthy();
  });
});
