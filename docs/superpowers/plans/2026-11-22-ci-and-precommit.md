# pre-commit + GitHub Actions CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pre-commit hooks (hygiene + ruff + mypy) and a GitHub Actions workflow running lint, typecheck, and tests.

**Architecture:** Two config files, no product code. `.pre-commit-config.yaml` runs hygiene hooks from `pre-commit/pre-commit-hooks` plus three `local` hooks invoking the project's own pinned tools through `uv run`. `.github/workflows/ci.yml` reuses the Makefile targets so CI commands are identical to local ones.

**Tech Stack:** pre-commit, uv, GitHub Actions (`actions/checkout`, `astral-sh/setup-uv`), existing Makefile targets (`lint`, `typecheck`, `test`).

**Spec:** `docs/superpowers/specs/2026-11-22-ci-and-precommit-design.md`

## Global Constraints

- Python `>=3.15`; tools resolved via `uv.lock` — hooks must go through `uv run`, never `pip install` into the venv.
- Makefile is the single source of truth for command spellings; CI calls `make`, not raw tool invocations.
- ruff config excludes `docs/`; hooks must pass `--force-exclude` so the exclusion holds when pre-commit passes filenames.
- Repo commits use conventional-commit prefixes (`feat:`, `fix:`); use `ci:` for these tasks.
- Branch is `main`; remote is `git@github.com:evgkirov/pitwall.git`. `gh` is installed but **not authenticated** — no `gh run` commands; verify CI via the Actions page URL. A global `pre-commit` binary exists at `/opt/homebrew/bin/pre-commit`.

## Review Focus

- Excluded paths: ruff hooks receiving `docs/` filenames via pre-commit must skip them — `--force-exclude` in both ruff hooks; verified by `pre-commit run --all-files` passing while `docs/` files exist.
- Hook drift: the mypy hook must be plain `uv run mypy` (reads `files = ["src"]` from pyproject) so hook and `make typecheck` are the same command — verified by hook passing on a repo where `make typecheck` passes.
- Hygiene hooks silently rewriting tracked files: `pre-commit run --all-files` must end with `git status` clean (fixes either absent or committed with the task).
- CI runner has no Python 3.15: `setup-uv` must get `python-version: "3.15"` explicitly or `uv sync` depends on runner system Python.
- Dead workflow from a typo'd ref or invalid YAML: resolve action tags from `git ls-remote` and parse the YAML before commit; real proof is the first run on push.

---

### Task 1: pre-commit config + README dev-setup line

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `README.md` (after the `make` block in Usage, lines 10-16)

**Interfaces:**
- Consumes: Makefile targets (`lint` = `ruff check` + `ruff format --check`, `typecheck` = `mypy` on `src/`).
- Produces: installed `.git/hooks/pre-commit`; README instruction `uv tool install pre-commit && pre-commit install`.

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0  # placeholder; autoupdate in Step 2 pins the real latest
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-merge-conflict
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check --force-exclude
        language: system
        types_or: [python, pyi]
      - id: ruff-format
        name: ruff format
        entry: uv run ruff format --force-exclude
        language: system
        types_or: [python, pyi]
      - id: mypy
        name: mypy
        entry: uv run mypy
        language: system
        pass_filenames: false
        types_or: [python, pyi]
```

- [ ] **Step 2: Pin hook revs to latest**

Run: `pre-commit autoupdate`
Expected: updates `pre-commit-hooks` `rev` to the newest tag (prints `updating ...`).

- [ ] **Step 3: Run all hooks against the whole repo**

Run: `pre-commit run --all-files`
Expected: every hook `Passed` (first run installs hook envs). If hygiene hooks `Fixed` files, re-run until `Passed`, then include the fixes in this task's commit.

- [ ] **Step 4: Verify repo is clean after hooks**

Run: `git status --porcelain`
Expected: only `.pre-commit-config.yaml` (and later README) as modified/untracked — no hook-modified source files left dirty.

- [ ] **Step 5: Install the git hook**

Run: `pre-commit install`
Expected: `pre-commit installed at .git/hooks/pre-commit`, file exists.

- [ ] **Step 6: Add README dev-setup line**

In `README.md`, directly after the `make` code block (after line 16), add a line of prose — "Install the git hooks once (hygiene + ruff + mypy on every commit):" — followed by a `sh` code block containing exactly:

```sh
uv tool install pre-commit && pre-commit install
```

- [ ] **Step 7: Commit (this commit runs through the new hook)**

```bash
git add .pre-commit-config.yaml README.md
git commit -m "ci: add pre-commit hooks"
```

Expected: commit succeeds and the hook output is visible during it (proves Step 5).

### Task 2: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Makefile targets `lint`, `typecheck`, `test`; `uv.lock` for caching.
- Produces: CI runs on push to `main` and on pull requests.

- [ ] **Step 1: Resolve latest major-version tags for the two actions**

Run: `git ls-remote --tags --refs https://github.com/actions/checkout.git | tail -5` and the same for `https://github.com/astral-sh/setup-uv.git`
Expected: tag lists; use the highest major (`vN` or `vN.N.N`) of each in Step 2.

- [ ] **Step 2: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<tag from Step 1>
      - uses: astral-sh/setup-uv@<tag from Step 1>
        with:
          python-version: "3.15"
          enable-cache: true
      - run: make lint
      - run: make typecheck
      - run: make test
```

- [ ] **Step 3: Validate the YAML parses**

Run: `uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add github actions workflow"
```

- [ ] **Step 5: Push and confirm the first run**

```bash
git push origin main
```

Expected: push succeeds and triggers the first CI run. Report
`https://github.com/evgkirov/pitwall/actions` to the human partner to
confirm the run goes green (gh is not authenticated, so the confirmation is
theirs to make — or ask them to run `gh auth login` first).
