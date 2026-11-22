# Design: pre-commit hooks + GitHub Actions CI

Date: 2026-11-22

## Intent

Keep lint, typecheck, and test failures out of `main` and out of local commits.
Developers get fast feedback on commit; CI runs the full suite on every push
and PR.

## Goals

- pre-commit framework (option A) with hygiene hooks + ruff + mypy on commit.
- GitHub Actions running `make lint typecheck test` on push to `main` and on
  PRs.

## Non-goals

- No pre-push / on-commit test runs (suite is ~5s but belongs in CI).
- No OS or Python matrix (project targets Python 3.15 only, ubuntu runner).
- No publish, release, or deploy jobs.

## Approaches

- **A. pre-commit framework** (chosen) — standard, self-documenting, one-time
  `pre-commit install`. ruff/mypy run as `local` hooks via `uv run`, so
  versions come from `uv.lock` (single source of truth).
- **B. plain hooks dir + `core.hooksPath`** — rejected: homegrown, per-contributor
  opt-in step, no ecosystem hooks.

## The design

**`.pre-commit-config.yaml`:**

- Hygiene hooks from `pre-commit/pre-commit-hooks`: `trailing-whitespace`,
  `end-of-file-fixer`, `check-yaml`, `check-toml`, `check-merge-conflict`.
- `ruff-check` local hook: `uv run ruff check --force-exclude` (filenames
  passed, so only changed files).
- `ruff-format` local hook: `uv run ruff format --force-exclude` (filenames
  passed).
- `mypy` local hook: `uv run mypy`, `pass_filenames: false` (matches
  `make typecheck`, which checks `src/` per pyproject).

**`.github/workflows/ci.yml`:**

- Triggers: `push` to `main`, `pull_request`.
- One job on `ubuntu-latest`: checkout → `astral-sh/setup-uv` (with uv.lock
  caching enabled; let uv fetch its managed Python 3.15) → `make lint` →
  `make typecheck` → `make test`. Reusing the Makefile keeps CI identical to
  local commands.

**README:** short dev-setup line: `uv tool install pre-commit && pre-commit install`.

## Left to the builder

- Exact action versions/pins and setup-uv options.
- Hook `rev` pin for `pre-commit-hooks`.

## Note

Local `.venv` had stale shebangs from the pre-rename project path; it was
recreated on 2026-11-22 and `make test` (74 passed) works again.
