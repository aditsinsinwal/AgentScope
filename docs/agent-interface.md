# Agent interface

`Agent.run(task, environment)` is async and provider-neutral. `AgentEnvironment` exposes only typed
tool definitions and `call_tool`; it exposes neither a host shell nor hidden-test paths. `AgentResult`
reports completion, steps, tool calls, and factual token usage.

`MockAgent` executes a fixed `MockAction` sequence, making CI deterministic and free. The
OpenAI-compatible adapter implements host-side chat/tool calling; the API key never enters the
sandbox. Rate limiting and step exhaustion become explicit agent errors. Provider-specific payloads
are contained in the adapter.

Adding a provider means implementing the protocol, mapping usage conservatively, and testing with a
mock HTTP transport. Real-provider tests must remain disabled unless credentials are explicitly set.

