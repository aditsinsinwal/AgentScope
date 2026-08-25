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
