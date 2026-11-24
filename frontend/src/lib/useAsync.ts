import {useCallback, useEffect, useRef, useState} from "react";
import {ApiError} from "../api/client";

export type AsyncState<T> =
  | {status: "loading"}
  | {status: "error"; error: ApiError | Error}
  | {status: "ready"; data: T};

/** Run an abortable loader whenever `deps` change; `reload` refetches. */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): [AsyncState<T>, () => void] {
  const [state, setState] = useState<AsyncState<T>>({status: "loading"});
  const [tick, setTick] = useState(0);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    const controller = new AbortController();
    setState({status: "loading"});
    loader.current(controller.signal).then(
      data => setState({status: "ready", data}),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({status: "error", error: error instanceof Error ? error : new Error(String(error))});
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick(value => value + 1), []);
  return [state, reload];
}
