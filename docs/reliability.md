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

