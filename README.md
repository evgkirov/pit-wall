# PitWall

A modular, read-only Twitch chat reader for your own streams. It connects to
your channel's chat anonymously (no credentials), reads messages aloud through
the macOS `say` synthesizer, and plays them in order — usernames and messages
can use different voices.

## Usage

```sh
make run        # runs `uv run pitwall`
make test       # pytest
make lint       # ruff check + format check
make typecheck  # mypy
make format     # autofix + reformat
```

Install the git hooks once (hygiene + ruff + mypy on every commit):

```sh
uv tool install pre-commit && pre-commit install
```

On first run PitWall tells you where it expects its config:

```
$XDG_CONFIG_HOME/pitwall/config.toml   (~/.config/pitwall/config.toml by default)
```

A minimal config — read every message from `shroud`'s chat aloud:

```toml
[[sink.twitch]]
channel = "shroud"

[[handler.tts]]
alias = "reader"

[[tts.say]]
alias = "voice"

[[output.local]]
alias = "speakers"
```

Per-part voices (usernames in Samantha, messages in Daniel):

```toml
[[handler.tts]]
voices = { user = "samantha", text = "daniel" }

[[tts.say]]
voices = { samantha = "Samantha", daniel = "Daniel" }
```

Save the file while PitWall is running and it rebuilds itself in-process —
invalid changes are rejected and the previous graph keeps running.

The full architecture (typed channels, plugin instances, routing by target,
the synthesizer/sequencer audio pipeline) is described in
[`docs/superpowers/specs/2026-11-22-pitwall-design.md`](docs/superpowers/specs/2026-11-22-pitwall-design.md).
