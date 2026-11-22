# AGENTS.md

## Session rules

- **Always use the default model** — for this session, subagents, code reviews, everything. Never look up or switch to a "more capable" model. Standing user instruction.
- **Superpowers**: creative work (features, bugfixes, planning) goes through the Superpowers skills — brainstorming → spec → plan → TDD execution → review. Follow them when they trigger; don't freelance around the process. Execution ledgers under `.superpowers/sdd/` are scratch: delete the workspace when the work lands — git history is the record.

## Commands

All tooling runs through `uv` (no manual venv management). Gate order matches CI: `make lint && make typecheck && make test`.

- `make test` / `make lint` / `make typecheck` / `make format` — see `Makefile`
- Single test: `uv run pytest tests/test_config.py -q` or `uv run pytest tests/test_config.py::test_name -v`
- Run the app: `make run` (config: `make run CONFIG=path/to/config.toml`, or `pitwall -c <path>`)

## Git

- Commit style is conventional — `feat:`, `fix:`, `docs:`, `ci:`, `chore:`, scope when it helps (`feat(cli): ...`). Check `git log` for the pattern.
- A complete change ships its docs in the same commit: user-facing changes update `README.md`; config-format changes also touch `config.toml.example` and its pinning test.

## Toolchain quirks

- **Python >= 3.15 required** (`requires-python`, `.python-version`). Don't assume an older default; `uv run` handles it.
- **ruff line-length is 100**, not the default 88; `docs/` is excluded.
- **mypy checks `src/` only** (`files = ["src"]`) — tests are not type-checked.
- **pytest-asyncio is `asyncio_mode = "auto"`** — async test functions need no marker or decorator.
- **Pre-commit hooks reformat on commit**: ruff format/check run as hooks and may modify files, failing the first commit attempt. If that happens, re-stage and commit again (`pre-commit install` once per clone).

## Testing

- The suite is hermetic: Twitch IRC and the macOS `say` binary are faked (`FakeConnection`, `FakeSubprocess` in the respective test files). No network and no macOS needed — CI runs on ubuntu-latest.
- Plugin names resolve through a **global registry**: call `register_builtins()` (from `pitwall.plugins`) before `factory_for`/`build` in any test that constructs plugins from config.

## Architecture

Event pipeline: sink → `messages` channel → handler → `speak` channel → tts → `audio` channel → output.

- `src/pitwall/core/` — the framework: typed `Channel`s, event dataclasses, the `Plugin` Protocol (`name`/`start`/`stop`), the registry, the `Runtime` that wires instances, config loading + hot reload.
- `src/pitwall/plugins/` — one module per built-in, registered under dotted names (`sink.twitch`, `handler.tts`, `tts.say`, `output.local`) in `register_builtins()`. New plugin: implement the Protocol, add a `register(...)` line there.
- Entry point: `pitwall` console script → `pitwall.cli:main`.

## Config

- TOML tables are plugin names: `[[sink.twitch]]`, `[[handler.tts]]`, etc.; multiple instances per plugin allowed (distinct `alias`es).
- The running app **hot-reloads the config on save** (watchfiles); a failed rebuild is logged and the previous plugin graph keeps running — preserve that invariant.
- `config.toml.example` (repo root) is validated by `tests/test_config.py::test_example_config_loads_and_names_known_plugins` — after editing it, run that test. A local root `config.toml` is gitignored.
- Design authority for the architecture: `docs/superpowers/specs/2026-11-22-pitwall-design.md`; specs/plans for all work live in `docs/superpowers/`.
