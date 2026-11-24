# Contributing

## Setup

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Release gates

Every change must pass these three commands. CI runs them on Python 3.12 and 3.13.

```bash
pytest              # tests plus the coverage gate (fail_under in pyproject.toml)
ruff check .        # lint
mypy agentscope     # strict type checking
```

CI also runs `ruff format --check .`, so run `ruff format .` before committing.

## Optional integration tests

Docker, PostgreSQL, and provider tests are opt-in and skipped by default. See the
"Development" section of the README for the environment variables and `pytest -m` selection.

## Commit style

Use short, imperative subjects with a conventional prefix such as `fix:`, `feat:`, `ci:`,
`docs:`, or `chore:`. Keep each commit to one logical change.
