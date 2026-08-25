# Sandboxing

`DockerSandbox` creates one ephemeral container per run with disabled network, dropped Linux
capabilities, `no-new-privileges`, an unprivileged UID, read-only root, bounded tmpfs, CPU/memory/PID
limits, command deadlines, and forced cleanup. Repository files are archived into `/workspace`;
commands use Docker exec with argv, never a shell. The Docker socket and provider secrets are absent.
After the agent exits, a traversal-filtered tar stream freezes the workspace. Evaluation runs in a
second fresh container, so hidden tests never enter the agent container.

Build the pinned Python image with:

```bash
docker build -t agentscope-sandbox:py312 -f sandbox/Dockerfile .
```

`LocalSandbox` exists solely for deterministic unit tests and trusted development. It is explicitly
not isolated. See the threat model in `security.md` before operating on untrusted repositories.
