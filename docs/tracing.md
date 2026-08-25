# Tracing and replay

Trace events are append-only and sequenced per run. State changes, model calls, tool calls/results,
evaluation, and errors share provider-neutral fields. Inputs/outputs are bounded summaries; write
contents are replaced with character counts. Token counts and latency are measurements, not guesses.

The local recorder writes one JSONL artifact per run using validated run IDs. `agentscope replay`
renders it without executing code or calling a model. The relational schema indexes run/sequence,
event type, and timestamp. Large logs and patches will move behind a content-addressed `ArtifactStore`
while database rows retain hashes and locations.

Replay is inspection, not re-execution. Trace forking requires explicit snapshot and causality models
and is deferred.

