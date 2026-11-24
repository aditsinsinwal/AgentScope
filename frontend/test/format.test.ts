import {describe, expect, it} from "vitest";
import {count, ms, NOT_REPORTED, pct, pp, score, signed, tokenTotal} from "../src/lib/format";

describe("formatting", () => {
  it("renders null as not reported, never zero", () => {
    expect(pct(null)).toBe(NOT_REPORTED);
    expect(ms(null)).toBe(NOT_REPORTED);
    expect(score(undefined)).toBe(NOT_REPORTED);
    expect(count(null)).toBe(NOT_REPORTED);
    expect(pp(null)).toBe(NOT_REPORTED);
    expect(signed(null)).toBe(NOT_REPORTED);
  });

  it("keeps a real zero as zero", () => {
    expect(pct(0, 1)).toBe("0.0%");
    expect(ms(0)).toBe("0 ms");
    expect(count(0)).toBe("0");
  });

  it("formats percentage-point and signed deltas", () => {
    expect(pp(0.125)).toBe("+12.5 pp");
    expect(pp(-0.25)).toBe("-25.0 pp");
    expect(pp(0)).toBe("0.0 pp");
    expect(signed(0.05)).toBe("+0.05");
    expect(signed(-0.5)).toBe("-0.50");
    expect(signed(0.0001)).toBe("0.00");
  });

  it("scales latency and only totals tokens when something reported", () => {
    expect(ms(1500)).toBe("1.50 s");
    expect(ms(42.4)).toBe("42 ms");
    expect(tokenTotal({prompt: null, completion: null, cases_reporting: 0})).toBe(NOT_REPORTED);
    expect(tokenTotal({prompt: 1000, completion: 234, cases_reporting: 3})).toBe("1,234");
  });
});
