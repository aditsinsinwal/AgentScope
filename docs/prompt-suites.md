# Prompt suites

A prompt suite runs a chat model over a JSONL set of prompts and scores every answer with
**deterministic checkers**. There is no LLM judge: the same outputs always produce the same
scores. Results are written in a form a blind human A/B tool can consume.

The scores answer narrow, mechanical questions (is the answer in the required shape, do the
fields equal the reference). They are **not a human preference judgement** and every artifact
says so. Use them as a pre-screen or as supplementary evidence.

Everything lives in `agentscope/suites/` and is reached through `agentscope suite ...`. The
existing SWE-task pipeline is untouched.

## Suite definition (YAML)

```yaml
id: task-cards-demo            # ^[a-z0-9][a-z0-9_-]{1,63}$
kind: prompt_suite             # required, must be exactly this
name: Task-card extraction     # display name (not part of the fingerprint)
version: "1"
cases: cases.jsonl             # relative to this file; may not escape its directory
system_prompt: |               # optional
  Reply with exactly these five lines ...
generation: {temperature: 0, seed: 0, max_tokens: 200}
checker:
  type: field_lines
  fields: [TASK, OWNER, DUE, PRIORITY, NOTE]
  allowed_values: {PRIORITY: [Low, Medium, High]}
  strict_line_count: true
```

Unknown keys are rejected everywhere, including settings that do not apply to the chosen
checker type (so a typo cannot silently disable a rule).

`generation` defaults: `temperature: 0`, `seed: 0`, `max_tokens: 512`. `seed: null` or
`max_tokens: null` omit the parameter from the request.

### Cases file (JSONL)

One object per line (lines are split on `\n` only; U+2028/U+2029/U+0085 inside strings are
ordinary characters, and `outputs.jsonl` writes them as `\u` escapes): `{"id", "prompt", "reference"?, "metadata"?}`. Ids match
`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`. Rejected, with the 1-based line number in the error:
invalid JSON, unknown keys, blank prompts, duplicate ids. Blank lines are skipped. The default
limit is 10,000 cases (`--max-cases`).

### Fingerprint

`sha256` over id, version, system prompt, generation parameters, the checker settings that
apply to its type, and the raw bytes of the cases file (length-prefixed, so fields cannot bleed
into each other). Changing any of these changes what a run measures, so `suite compare` refuses
to compare runs with different fingerprints.

## Checkers

All checkers trim whitespace and accept **one** wrapping markdown code fence. None accepts a
chatty preamble. Each returns `CaseCheck(passed, score in [0,1], format_valid, fields, detail)`.

| type | passes when | `format_valid` | `score` |
|---|---|---|---|
| `exact` | normalised output equals the reference (NFC, whitespace collapsed; `case_insensitive` optional) | output non-empty | 1 or 0 |
| `regex` | output `fullmatch`es (default) or `search`es `pattern` (`ignore_case` optional) | same as passed | 1 or 0 |
| `field_lines` | format valid and every field matches the reference | see below | matched fields / total fields |
| `json_keys` | output is a JSON object containing all `keys` | same as passed | present keys / required keys |

`exact` needs a reference on every case (the loader checks). Regex patterns (the `regex` package, a superset of `re`) are limited to 2,000
characters; only the first 100,000 characters of an output are examined; and every match has a
hard deadline (`timeout_seconds`, default 1.0). A pattern that exceeds it fails that check with
detail `regex timed out` instead of hanging. Checks run in a worker thread so other cases keep
progressing.

### `field_lines`

Parses `KEY: value` lines, splitting on the first colon (values may contain colons). Keys are
case-sensitive and must touch the colon. `format_valid` is true only if:

- every configured field appears exactly once with a non-empty value,
- values respect `allowed_values` (case-sensitive: the rubric names exact labels),
- fields are in the configured order (`ordered`, default true),
- there are no other non-empty lines (`strict_line_count`, default true; set false to ignore
  extra lines anywhere).

Lines are split on `\n` / `\r\n` only, so `TASK: a PRIORITY: High` on one physical line is
not a card. Per-field `matched` compares to the reference field, normalised and case-insensitive. The score
counts matches even when the format is invalid, so "right content, wrong format" is visible
(`score 1.0, format_valid false`). `passed = format_valid and all fields matched`.

Without a reference there is nothing to match: `matched` is `null`, the score is format-only
(1.0 if valid, else 0.0) and `passed = format_valid`.

## Providers and the loopback guard

| `--provider` | endpoint | loopback enforced |
|---|---|---|
| `ollama` | `http://127.0.0.1:11434/v1` | always |
| `lmstudio` | `http://127.0.0.1:1234/v1` | always |
| `openai-compatible` | `--base-url` (required) | with `--local-only` |
| `replay` | none (reads `--replay-outputs`) | n/a |

`--base-url` may override a preset's address, but the guard still applies. `require_loopback`
accepts only `http`/`https` URLs whose host is the literal `localhost`, an IPv4 address in
`127.0.0.0/8`, or `::1`. It rejects `127.0.0.1.example.com`, `0.0.0.0`, `127.1`, decimal-integer
hosts, `http://127.0.0.1@evil.com`, any userinfo, any query string or fragment
(`http://127.0.0.1#@evil.com/`), IPv4-mapped IPv6, zone ids, backslashes and
whitespace, and other schemes. It performs no DNS lookup. The one accepted assumption is that the
OS resolves `localhost` to loopback. The HTTP client ignores proxy environment variables and does
not follow redirects, so a loopback request cannot be silently rerouted.

The OpenAI-compatible client is non-streaming and shares its retry policy
(`agentscope/agents/providers/retry.py`) with the agent provider. Up to 3 attempts; only
replay-safe transport errors (connect, read/write error, protocol error, pool timeout), HTTP 429
and 5xx are retried, with capped exponential backoff and full jitter. `Retry-After` (seconds
form) is honoured, floored at the backoff base and capped. A `ReadTimeout` (the request may
already be processed) is not retried unless `AGENTSCOPE_PROVIDER_RETRY_READ_TIMEOUT=true`.
Unsupported URLs, proxy errors, other 4xx and malformed responses fail at once. The API key, if any, is read from the environment variable named by
`--api-key-env`, sent only in the `Authorization` header, and scrubbed from error messages and
traces. Token counts come from the server's `usage` block and are `null` when absent; they are
never estimated.

`replay` serves recorded `{"id", "output"}` lines. Nothing is generated: results carry
`"source": "replay"`, latency and tokens are `null`, and the report and compare output say so.

## Running

```
agentscope suite validate SUITE.yaml
agentscope suite run --suite SUITE.yaml --provider ollama --model llama3.2 --out runs/base
agentscope suite compare runs/base/results.json runs/tuned/results.json [--json] [--allow-mismatch] \
    [--resamples 10000] [--confidence 0.95] [--seed 0]
```

`run` options: `--base-url`, `--replay-outputs`, `--local-only`, `--api-key-env`,
`--concurrency` (default 1: local models), `--case-timeout` seconds (default 120; the TOTAL budget for one case, covering every retry
attempt and backoff), `--request-timeout` seconds per HTTP attempt (default
`min(60, case-timeout / 2)`, and it must be smaller than `--case-timeout`),
`--request-timeout`, `--max-cases`,
`--out` (default `<reports_dir>/<suite>-<provider>-<model>`, where `reports_dir` is the
`AGENTSCOPE_REPORTS_DIR` setting, default `artifacts/suite-reports`, the directory the dashboard reads),
`--overwrite`, `--no-trace-text`.

Exit codes: `0` success, `1` at least one case produced no output, `2` invalid input or a
guard rejection.

## Artifacts

| file | contents |
|---|---|
| `outputs.jsonl` | exactly `{"id": ..., "output": ...}` per line, `ensure_ascii=False`, suite case order |
| `results.json` | schema_version 1: suite id/version/fingerprint/checker, run info (`source`, provider, model, base-url host only, params, UTC start/finish, concurrency), per-case check results, aggregate |
| `trace.jsonl` | append-only, one event per line in the existing `TraceEvent` shape: `suite_started`, a `model_call` and an `evaluation` event per case, `suite_finished` |
| `report.md` | human summary; states "Deterministic checks only; not a human preference judgement" |

**Failed cases.** A case fails when the provider errors, the case times out, or a replay id is
missing. Nothing is invented for it: it is listed in `results.json` and `report.md` with its
error, it is **omitted from `outputs.jsonl`**, and the CLI exits 1 with a message. A downstream
tool that needs every id will reject the incomplete file, which is the intent: fix the failure and
rerun rather than judge a partial set.

**Aggregates** are computed over scored (successful) cases. `mean_score` (the JSON name) is the
mean *content* score: for `field_lines` it counts matched fields even when the format is
invalid, so reports label it "Mean content score (field matches; ignores format)" and it
should be read next to `format_valid_rate`; `n_failed` is reported separately.
`format_valid_rate`, `pass_rate`, `mean_score` and per-field accuracy are `null` when nothing was
scored. Latency p50/p95 use the nearest-rank method (the value at rank `ceil(p/100 * n)` of the
sorted successful latencies) and are `null` when no latency was measured. Token totals are the sum
over cases and are `null` unless every scored case reported usage; `cases_reporting` says how many
did. Latency is the time of the successful HTTP attempt, excluding retry backoff.

**Traces** store prompts and outputs locally in full (API keys redacted). With
`--no-trace-text` they store only character counts and SHA-256 hashes. `results.json` never holds
output text, only length and hash. A run refuses to write into a directory that already holds
artifacts unless `--overwrite` is given, so traces from two runs are never mixed.

## Comparing two runs

`suite compare A B` requires equal suite fingerprints (otherwise exit 2; `--allow-mismatch`
compares shared ids with a warning). It reports, over cases scored on both sides: how many are
better in B, tied, or better in A by score; how many were format-valid or passed on only one
side; and rate and per-field accuracy deltas (B minus A).

It also prints paired intervals (also under `intervals` in `--json` and in
`GET /api/v1/suite-compare`). Each interval is a paired percentile bootstrap of the mean
per-case difference B minus A, over cases scored on both sides: the same case ids are resampled
together, so the spread reflects how much the difference varies from case to case, not how hard
the cases are. Defaults are 10000 resamples, 0.95 confidence and seed 0 (`--resamples` 100 to
100000, `--confidence` above 0.5 and below 1, `--seed`); the same inputs and seed always give the
same numbers. The pass/fail view adds an exact two-sided McNemar test on the cases that passed on
only one side. These are numbers with their method, not a verdict. With few cases the interval is
wide and rough: a percentile bootstrap on a handful of cases can understate the uncertainty, a
field's interval uses only the cases where both sides have that field, and with fewer than 2
paired cases every interval is `null`. Interval estimates are paired-case means, so they can
differ slightly from the aggregate rate deltas above.

## Worked example (no network, no model)

`examples/suites/task-cards/` holds a synthetic suite of 8 task-card cases and two recorded
output files: `replay-good.outputs.jsonl` (clean cards with a few content differences) and
`replay-chatty.outputs.jsonl` (preambles, trailing chatter, a disallowed priority value). The
output below was produced by running these commands in this repository.

```
$ agentscope suite validate examples/suites/task-cards/suite.yaml
OK: task-cards-demo v1 (field_lines checker)
Cases: 8
Fingerprint: 98db77dfe50402f186b1c3594859dfcdad75ae66d4d6594da4fe02fd4cc9d8aa

$ agentscope suite run --suite examples/suites/task-cards/suite.yaml --provider replay \
    --replay-outputs examples/suites/task-cards/replay-good.outputs.jsonl --out artifacts/demo/good
Suite: task-cards-demo v1  fingerprint 98db77dfe504
Source: replay  Model: replay
Cases: 8 (8 scored, 0 failed)
Format valid: 100.0%  Passed: 75.0%
Mean content score (field matches; ignores format): 0.950
  TASK: 100.0%
  OWNER: 100.0%
  DUE: 87.5%
  PRIORITY: 87.5%
  NOTE: 100.0%
Deterministic checks only; not a human preference judgement.
Artifacts: artifacts/demo/good

$ agentscope suite run --suite examples/suites/task-cards/suite.yaml --provider replay \
    --replay-outputs examples/suites/task-cards/replay-chatty.outputs.jsonl --out artifacts/demo/chatty
Suite: task-cards-demo v1  fingerprint 98db77dfe504
Source: replay  Model: replay
Cases: 8 (8 scored, 0 failed)
Format valid: 25.0%  Passed: 25.0%
Mean content score (field matches; ignores format): 0.950
  TASK: 100.0%
  OWNER: 100.0%
  DUE: 100.0%
  PRIORITY: 75.0%
  NOTE: 100.0%
Deterministic checks only; not a human preference judgement.
Artifacts: artifacts/demo/chatty

$ agentscope suite compare artifacts/demo/chatty/results.json artifacts/demo/good/results.json
warning: A is a replay of recorded outputs, not a generated run
warning: B is a replay of recorded outputs, not a generated run
Suite: task-cards-demo
Paired cases: 8 (unpaired: 0); B better: 0, tie: 8, A better: 0
Format valid only in B: 6, only in A: 0; passed only in B: 4, only in A: 0
Format valid rate delta (B - A): +75.0 pp
Pass rate delta (B - A): +50.0 pp
Mean content score delta (field matches; ignores format) (B - A): +0.000
  DUE accuracy delta: -12.5 pp
  NOTE accuracy delta: +0.0 pp
  OWNER accuracy delta: +0.0 pp
  PRIORITY accuracy delta: +12.5 pp
  TASK accuracy delta: +0.0 pp
Counts only; no significance is claimed. Not a human preference judgement.

$ agentscope suite run --suite examples/suites/task-cards/suite.yaml --provider ollama \
    --model demo --base-url https://api.example.com/v1 --out artifacts/demo/x
error: host 'api.example.com' is not loopback (allowed: localhost, 127.0.0.0/8, ::1)
```

The compare output shows why the format and content views are kept separate: the chatty run's
content is as good as the clean run's (every score ties), but 6 of its 8 answers are not
format-valid.

Python API: `load_suite`, `build_chat_model`, `ReplayChatModel`, `SuiteRunner`,
`compare_results` and `require_loopback` are exported from `agentscope.suites`.

## Known limits

- Deterministic checks cannot judge quality, tone or usefulness beyond the configured rules.
- `localhost` is trusted to resolve to loopback; no DNS verification is done.
- Per-case latency is wall time of one HTTP attempt; it is not a controlled benchmark.
- Concurrency above 1 is allowed but will perturb latency numbers on a single local model.
