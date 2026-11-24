# Reliability and fault injection

`FaultInjectionPolicy` defines a seed, failure probability, timeout probability, and added latency.
The wrapper consumes two deterministic random values per call, so decisions can be recreated when
tool order is the same. Injected outcomes are labeled; they must not be confused with natural faults.

Measure baseline and degraded solve rate, recovery after transient errors, retries, duplicate calls,
and recovery latency from actual paired experiments. No example percentage is published as a result.

The local scheduler bounds concurrency, cancels queued jobs, and retries only
`InfrastructureFailure`. PostgreSQL workers claim with leases/heartbeats. Lease expiry does not prove
a partial model execution is safe to replay, so ambiguous attempts require reconciliation and a new
linked run rather than an exactly-once claim.


## Provider calls

The OpenAI-compatible adapter retries transport errors, HTTP 429 and 5xx with exponential backoff and
full jitter, bounded by `AGENTSCOPE_PROVIDER_MAX_ATTEMPTS`, `..._BACKOFF_BASE_SECONDS` and
`..._BACKOFF_CAP_SECONDS`. A `Retry-After` value in seconds is honoured up to the cap. Only transport errors where resending is safe (connect errors/timeouts, remote protocol, read and
write errors, pool timeout) are retried; `ReadTimeout` is opt-in via
`AGENTSCOPE_PROVIDER_RETRY_READ_TIMEOUT` because the request may already have been processed. A
`Retry-After` of 0 is floored at the backoff base. Other 4xx responses are never retried. Failures surface as `ProviderError` (retryable flag, status, attempts).
A response without a usable `choices[0].message` is a non-retryable `ProviderError`. A malformed tool
call, non-object arguments or an unknown tool is returned to the model as a tool error so the loop can
recover. `max_steps` and `AGENTSCOPE_AGENT_MAX_TOOL_CALLS` bound the loop; hitting either raises
`AgentLimitExceeded`, recorded as `agent_failed` with a `limit_exceeded:` failure message. Missing
usage is recorded as unknown (`None` in the model-call event) and counted in `Usage.unreported_calls`,
never as zero tokens.

## Cancellation and shutdown

Cancelling a run cancels the running job task, so the sandbox context manager unwinds, and the engine
(the single writer of `cancelled`, with a shielded write) records it. Jobs cancelled before they
start are marked `cancelled` through the scheduler's `on_cancelled` hook. The cancel endpoint waits a
bounded time for that to settle before returning state. Sandbox provisioning is cancel-safe: a Docker
container created after cancellation is removed when its creation call returns. Closing the scheduler (application shutdown) cancels queued and running jobs and
awaits its workers. Before this was fixed, `cancel` only cancelled the caller's future while the job
kept running, and shutdown waited for running jobs.
