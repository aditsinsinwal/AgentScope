/** Formatting helpers. A missing measurement is "not reported", never zero. */

export const NOT_REPORTED = "not reported";

export function pct(value: number | null | undefined, digits = 0): string {
  return value == null ? NOT_REPORTED : `${(value * 100).toFixed(digits)}%`;
}

/** Signed percentage-point delta, e.g. "+12.5 pp". */
export function pp(delta: number | null | undefined): string {
  if (delta == null) return NOT_REPORTED;
  const points = delta * 100;
  const text = Math.abs(points) < 0.05 ? "0.0" : points.toFixed(1);
  return `${points > 0.05 ? "+" : ""}${text} pp`;
}

export function signed(delta: number | null | undefined, digits = 2): string {
  if (delta == null) return NOT_REPORTED;
  const text = Math.abs(delta) < 0.5 * 10 ** -digits ? (0).toFixed(digits) : delta.toFixed(digits);
  return delta > 0 && Number(text) !== 0 ? `+${text}` : text;
}

export function score(value: number | null | undefined): string {
  return value == null ? NOT_REPORTED : value.toFixed(2);
}

export function ms(value: number | null | undefined): string {
  if (value == null) return NOT_REPORTED;
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

export function count(value: number | null | undefined): string {
  return value == null ? NOT_REPORTED : new Intl.NumberFormat("en-US").format(value);
}

export function duration(seconds: number): string {
  if (seconds <= 0) return "—";
  if (seconds < 0.001) return "<1 ms";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  return `${seconds.toFixed(1)} s`;
}

export function dateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

/** Token totals: only report a figure when at least one case reported usage. */
export function tokenTotal(
  tokens: {prompt: number | null; completion: number | null; cases_reporting: number},
): string {
  if (tokens.cases_reporting === 0 || (tokens.prompt == null && tokens.completion == null)) {
    return NOT_REPORTED;
  }
  return count((tokens.prompt ?? 0) + (tokens.completion ?? 0));
}
