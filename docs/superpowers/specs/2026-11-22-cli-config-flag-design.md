# CLI `-c` config flag, Makefile passthrough, config example — design

**Date:** 2026-11-22
**Status:** approved (short design — small change)

## Intent

`pitwall -c <path>` (same argument as the existing `--config <path>`) selects
the config file; with no flag, the default is used:
`$XDG_CONFIG_HOME/pitwall/config.toml`, falling back to
`~/.config/pitwall/config.toml`. `make run` can forward a config:
`make run CONFIG=<path>`.

## Why

`--config` already existed; `-c` was rejected by argparse ("unrecognized
arguments"). The Makefile `run` target had no way to pass a config through.

## Goals / non-goals

- Goals: `-c` short flag; `make run CONFIG=...`; `config.toml.example`
  template at the repo root; tests; README notes.
- Non-goals: positional config argument; changing the default location;
  multi-config merging; generating configs interactively.

## Approaches

1. **Short flag on the existing argument (chosen):** `("-c", "--config")` on
   the existing argparse argument. One line; both spellings work; `-c`
   appears in `--help` for free.
2. Positional `pitwall <path>`: less discoverable, collides with future
   flags — rejected.
3. Makefile `ARGS=` raw passthrough (`make run ARGS="-c x.toml"`): more
   general but less guided than a named `CONFIG` variable — rejected.

Example template:

1. **Commented file at the repo root (chosen):** `config.toml.example` —
   copy-paste starting point; a test keeps it loadable and free of dead
   plugin names.
2. README-only examples (status quo): readable but not `cp`-able — kept as
   documentation, insufficient alone.
3. `config.example.toml` naming (TOML extension visible to editors): the
   partner asked for `config.toml.example` — followed their name.

## Decisions

- `-c` and `--config` are the same argument (from the conversation).
- Makefile: `CONFIG` variable via `$(if $(CONFIG),-c "$(CONFIG)")` so plain
  `make run` stays identical to today — my call.
- Add missing `typecheck` to `.PHONY` while touching the Makefile — my call
  (drive-by fix, it was the only phony target left out).
- `config.toml.example` holds the minimal working config (placeholder
  channel, the four built-in plugin tables) with per-part voices and
  `enabled = false` shown as comments — my call, mirroring the README's two
  documented configs.
- A test loads the example through `load_config` and resolves every plugin
  name via the registry, so the template can't drift into invalid TOML or
  unknown plugins — my call.

## Left to the builder

Nothing open.
