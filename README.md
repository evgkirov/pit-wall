# PitWall

A modular, read-only Twitch chat reader for your own streams. It connects to
your channel's chat anonymously (no credentials), reads messages aloud through
the macOS `say` synthesizer (or local neural voices via mlx-audio), and plays
them in order — usernames and messages can use different voices.

## Usage

```sh
make run        # runs `uv run pitwall`
make test       # pytest
make lint       # ruff check + format check
make typecheck  # mypy
make format     # autofix + reformat
```

Pick a specific config with `make run CONFIG=path/to/config.toml` (or
`pitwall -c <path>`); without it the default path below is used.

Install the git hooks once (hygiene + ruff + mypy on every commit):

```sh
uv tool install pre-commit && pre-commit install
```

On first run PitWall tells you where it expects its config:

```
$XDG_CONFIG_HOME/pitwall/config.toml   (~/.config/pitwall/config.toml by default)
```

A commented template lives in [`config.toml.example`](config.toml.example) —
copy it to the default path and edit. A minimal config — read every message
from `shroud`'s chat aloud:

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

### Neural voices (Apple Silicon)

Swap `say` for local neural voices with
[mlx-audio](https://github.com/Neywa-Labs/mlx-audio):

```sh
uv sync --extra mlxaudio
```

```toml
[[tts.mlx]]
alias = "voice"
model = "mlx-community/Kokoro-82M-bf16"   # any mlx-audio model repo
voices = { user = "af_heart", text = "am_michael" }
speed = 1.0
```

The first run downloads model weights from Hugging Face; startup loads the
model into memory (a few seconds). `voice`/`voices`/`speed` mirror `tts.say`,
with model-specific voice names instead of macOS voice names.

Save the file while PitWall is running and it rebuilds itself in-process —
invalid changes are rejected and the previous graph keeps running.

The full architecture (typed channels, plugin instances, routing by target,
the synthesizer/sequencer audio pipeline) is described in
[`docs/superpowers/specs/2026-11-22-pitwall-design.md`](docs/superpowers/specs/2026-11-22-pitwall-design.md).
