# CLI `-c` Config Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept `-c <path>` as a short form of `--config` on the `pitwall` CLI, let `make run CONFIG=<path>` forward it, and ship a tested `config.toml.example` template at the repo root.

**Architecture:** One-line argparse change in `src/pitwall/cli.py` adds the short flag to the existing `--config` argument; the Makefile `run` target gains an optional `CONFIG` variable that expands to `-c "<path>"` only when set; `config.toml.example` mirrors the README's minimal config with commented optional keys and is pinned by a loading test. Default behavior (`$XDG_CONFIG_HOME`/`~/.config/pitwall/config.toml`) is untouched.

**Tech Stack:** Python 3.15, argparse, pytest, make.

**Spec:** `docs/superpowers/specs/2026-11-22-cli-config-flag-design.md`

## Global Constraints

- `-c` and `--config` must remain the same argument (same dest, same `default=None`).
- Plain `make run` must expand to exactly `uv run pitwall` — no stray args.
- No new dependencies.

## Review Focus

- `-c` with a nonexistent path must exit 1 with the path in stderr, no traceback — pinned by Task 1's test.
- `make run` with no `CONFIG` must pass no stray arguments — pinned by Task 2's `make -n run` check.
- `make run CONFIG=...` must quote the path so spaces survive the shell — pinned by Task 2's `make -n run CONFIG=...` check.
- `-c` with no value: argparse's own usage error (exit 2) is accepted as standard behavior; not re-implemented.
- `--help` must list `-c` alongside `--config` — argparse does this automatically once the flag string is added; eyeballed in Task 1 Step 4.
- The example template must never drift into invalid TOML, duplicate aliases, or plugin names the registry doesn't know — pinned by Task 3's test, which `load_config`s the example and resolves every plugin through `factory_for`.

---

### Task 1: `-c` short flag on the CLI

**Files:**
- Modify: `src/pitwall/cli.py:59-61`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `main(argv) -> int` and `default_config_path() -> Path` in `src/pitwall/cli.py`.
- Produces: unchanged public surface; `main(["-c", "<path>"])` behaves exactly like `main(["--config", "<path>"])`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`, next to the existing `--config` tests:

```python
def test_short_config_flag(tmp_path, capsys):
    assert main(["-c", str(tmp_path / "nope.toml")]) == 1
    err = capsys.readouterr().err
    assert "nope.toml" in err
    assert "Traceback" not in err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_short_config_flag -v`
Expected: FAIL — SystemExit(2), argparse "unrecognized arguments: -c ..."

- [ ] **Step 3: Implement the short flag**

In `src/pitwall/cli.py`, change the argument registration to `parser.add_argument("-c", "--config", type=Path, default=None, help=...)` — keep dest and help text as they are.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_short_config_flag -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pitwall/cli.py tests/test_cli.py
git commit -m "feat(cli): accept -c as short form of --config"
```

### Task 2: Makefile `CONFIG` passthrough + README note

**Files:**
- Modify: `Makefile` (`.PHONY` line, `run` target)
- Modify: `README.md` (usage section)

**Interfaces:**
- Consumes: Task 1's `-c` flag.
- Produces: `make run CONFIG=<path>` → `uv run pitwall -c "<path>"`; plain `make run` unchanged.

- [ ] **Step 1: Update the Makefile**

Add `typecheck` to `.PHONY`. Above the `run` target add the comment `# make run CONFIG=path/to/config.toml`; change the recipe to `uv run pitwall $(if $(CONFIG),-c "$(CONFIG)")`.

- [ ] **Step 2: Verify both expansions**

Run: `make -n run`
Expected output: `uv run pitwall`

Run: `make -n run CONFIG="my config.toml"`
Expected output: `uv run pitwall -c "my config.toml"`

- [ ] **Step 3: README note**

In `README.md`, after the `make` usage block, one sentence: a config can be selected with `make run CONFIG=path/to/config.toml` (or `pitwall -c <path>`); without it the default path is used.

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: both pass (the full `make test` gate runs once, after Task 3).

- [ ] **Step 5: Commit**

```bash
git add Makefile README.md
git commit -m "feat(make): forward CONFIG to pitwall -c; document it"
```

### Task 3: `config.toml.example` template

**Files:**
- Create: `config.toml.example`
- Modify: `README.md` (config section)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `load_config(path) -> Config` from `pitwall.core.config`; `register_builtins()` from `pitwall.plugins`; `factory_for(plugin) -> Factory` from `pitwall.core.registry`.
- Produces: repo-root template users copy to `~/.config/pitwall/config.toml`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_example_config_loads_and_names_known_plugins():
    register_builtins()
    example = Path(__file__).parents[1] / "config.toml.example"
    config = load_config(example)
    assert config.instances
    for spec in config.instances:
        factory_for(spec.plugin)
```

with imports `from pathlib import Path`, `from pitwall.core.registry import
factory_for`, and `from pitwall.plugins import register_builtins` added to
the file's existing import block.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_example_config_loads_and_names_known_plugins -v`
Expected: FAIL — ConfigError "config not found" (the file doesn't exist yet)

- [ ] **Step 3: Create `config.toml.example`**

Header comments: copy destination (`$XDG_CONFIG_HOME/pitwall/config.toml`,
`~/.config/pitwall/config.toml` by default) and the hot-reload note. Body:
the README's minimal config — `[[sink.twitch]]` with `channel = "shroud"`,
`[[handler.tts]]` with `alias = "reader"`, `[[tts.say]]` with
`alias = "voice"`, `[[output.local]]` with `alias = "speakers"` — plus the
per-part voices pairing from the README and an `enabled = false` line, all
as comments inside their tables.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_example_config_loads_and_names_known_plugins -v`
Expected: PASS

- [ ] **Step 5: README pointer**

In `README.md`'s config section, one sentence before the minimal example:
a commented template lives in [`config.toml.example`](config.toml.example) —
copy it to the default path and edit.

- [ ] **Step 6: Run the full gate**

Run: `make test && make lint && make typecheck`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add config.toml.example tests/test_config.py README.md
git commit -m "feat(config): ship tested config.toml.example template"
```
