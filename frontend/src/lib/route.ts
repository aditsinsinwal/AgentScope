import {useEffect, useState} from "react";

/** Minimal hash router: "#/reports/abc?x=1" -> {segments: ["reports","abc"], query}. */
export type Route = {segments: string[]; query: URLSearchParams};

export function parseHash(hash: string): Route {
  const [path = "", search = ""] = hash.replace(/^#/, "").split("?");
  return {
    segments: path.split("/").filter(Boolean).map(part => decodeURIComponent(part)),
    query: new URLSearchParams(search),
  };
}

export function useRoute(): Route {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parseHash(hash);
}

export const href = {
  runs: "#/runs",
  experiments: "#/experiments",
  reports: "#/reports",
  report: (id: string) => `#/reports/${encodeURIComponent(id)}`,
  compare: (a?: string, b?: string) => {
    const query = new URLSearchParams();
    if (a) query.set("a", a);
    if (b) query.set("b", b);
    const text = query.toString();
    return text ? `#/compare?${text}` : "#/compare";
  },
};
