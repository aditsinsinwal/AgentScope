# Security threat model

## Assets and adversary

AgentScope protects worker hosts, credentials, other runs, hidden tests, trace integrity, and the
control database from malicious repository code and mistaken agent actions. Repository code and
model output are untrusted. Operators and the Docker daemon are trusted in v0.1.

## Controls

- one network-disabled, ephemeral, unprivileged container per run;
- dropped capabilities, no-new-privileges, read-only root, bounded writable tmpfs;
- CPU, memory, process, and time limits; forced cleanup;
- relative path validation and symlink escape checks in local development;
- typed tools, bounded reads/writes, argv execution without a shell, executable allowlist;
- agent container destroyed before hidden tests enter a separate evaluator container;
- credentials used only by the host-side provider adapter;
- no Docker socket or host workspace mount inside the sandbox;
- bounded/redacted trace summaries.

## HTTP API controls

- Optional bearer token (`AGENTSCOPE_API_TOKEN`), compared in constant time, required for every
  `/api/` route except `/api/v1/health`. When unset the API is open, intended only for loopback
  development; `agentscope serve` logs one warning if it binds a non-loopback host without a token.
  The generated `/openapi.json`, `/docs` and `/redoc` need the token too. The static dashboard
  shell is served without authentication; whether the dashboard can supply a token is a property of
  the dashboard build, not of the API. An empty `AGENTSCOPE_API_TOKEN` is treated as a
  misconfiguration: authentication stays off and a warning is logged at startup.
- Request bodies are limited (`AGENTSCOPE_MAX_REQUEST_BYTES`, default 1 MiB); larger declared or
  chunked bodies get `413`.
- Errors use one JSON envelope (`code`, `message`, `request_id`, optional `details`). Validation
  details omit submitted values; unexpected errors return a generic message and are logged
  server-side with the request id. `X-Request-ID` is echoed when it is a short `[A-Za-z0-9._-]`
  token, otherwise a new id is generated.
- CORS is not enabled; no cross-origin caller is trusted.
- Provider errors carry the status code and a retryable flag, never the API key, request body or
  response body.
- `POST /api/v1/tasks` still loads any server-readable `definition_path`; a token is the only guard,
  so do not expose the API to untrusted callers.

## Known limitations

Docker shares the host kernel and is not a perfect hostile-code boundary. The default Docker daemon
is highly privileged. The example image still needs continuous vulnerability scanning and signing.
The SDK cannot reliably kill a single timed-out exec, so AgentScope destroys the whole container.
Allowlisted Python/pytest can execute arbitrary repository code inside the container by design.
Network-disabled containers may still expose kernel interfaces. API authentication, authorization,
tenant isolation, artifact encryption/retention, seccomp/AppArmor profiles, rootless Docker, image
provenance enforcement, audit logging, evaluator-in-a-second-container, and secret-manager integration
are required before multi-tenant internet exposure.

Run workers on dedicated, patched hosts with no sensitive mounts or credentials. Never point
`LocalSandbox` at untrusted code. Treat traces as potentially sensitive and apply least-privilege
database access and retention policies.
