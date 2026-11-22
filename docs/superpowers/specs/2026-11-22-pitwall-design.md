# PitWall — Design (v1)

## Intent & why

PitWall is a small, modular Twitch chat bot for the owner's own streams, run
locally on macOS from a single terminal command. v1 is a **chat reader**: it
connects to a read-only Twitch chat and reads each message aloud via the macOS
`say` utility, so a streamer who can't watch chat while streaming can hear it.

The architecture is deliberately modular — a typed-channel pipeline with
pluggable sinks, message handlers, TTS engines, and voice outputs — because the
concept foresees growth (more sinks, more TTS providers, output to Discord, a
Web/TUI front-end). v1 builds the seam; future work drops into it.

## Goals (v1)

- Connect to a Twitch chat **read-only** and consume messages.
- Read chat messages aloud via the macOS `say` utility, passing each message
  through a configurable filter chain.
- A modular, typed-channel pipeline (sink → handler → TTS → output) with a
  registry and per-plugin config.
- A single `.toml` config under `$XDG_CONFIG_HOME/pitwall/`, watched; a change
  rebuilds the running plugin graph.
- Run as one command (`uv run pitwall`) with graceful start / stop / restart.
- Clean, type-checked, linted, tested code (ruff + pytest).

## Non-goals (v1)

- Sending chat messages / any Twitch write — the connection is **read-only**
  (anonymous or app token, `chat:read` only; no user OAuth).
- `!ping` and any command handling — deferred to a future `handler.commands`
  plugin.
- Any UI (Web/TUI), non-macOS output, or additional streaming services — the
  architecture must not block them, but none are built.
- Persisting state or a database.

## Anti-goals (what would make this a failure even if it technically works)

- A hard-coded plugin chain that can't take a second sink / TTS / output without
  touching core.
- A config change that crashes the bot or requires a relaunch from the shell.
- One plugin's exception taking down the whole process.

## Constraints

- Python 3.15+, `uv`, `ruff` (lint + format). macOS `say` is available.
- A single local process; no external services or process supervisors.
- `say` writes to the local audio device itself — there are no audio bytes to
  route in v1.

## Approaches considered

For wiring the plugin pipeline, three real models:

- **A. Flat pipeline** — fixed ordered slots (one sink → ordered handlers → one
  TTS → one output). Simplest to picture and test, but rigid: a second
  sink / TTS / output, or a handler that injects into a later stage, breaks it.
- **B. Event bus** — a central pub/sub where any plugin subscribes to any event.
  Maximally flexible (a future Web/TUI is "just another subscriber"), but
  ordering is implicit and tracing "why was *this* message spoken" means reading
  every subscriber.
- **C. Typed channels (chosen)** — keep the four-stage *picture* but implement it
  as a small registry of typed `asyncio` queues (`messages`, `speak`, `audio`).
  It reads like a pipeline, but any number of consumers register per channel and
  a new channel is just another queue. B's flexibility with A's readability.

**Chosen: C.** It matches the concept's four plugin types 1:1, keeps every stage
independently testable, and is the cheapest model that still satisfies the
extensibility goal. A is too rigid for the stated future; B is too loose to
debug when a streamer asks "why did that get read."

## Architecture (chosen: typed channels)

**Runtime.** `asyncio`. The `pitwall` process *is* the loop. Each plugin runs
as its own task under a supervisor.

**Channels** (`asyncio.Queue`):

- `messages`: `Message` (from sinks) → message handlers.
- `speak`: `SpeakRequest` (from handlers) → TTS.
- `audio`: `Audio` (from TTS) → voice output.

**Targeted delivery.** An event carrying a `target` (an instance name) is
delivered only to the instance it names on that channel; without one it goes to
every instance on the channel. This is what lets two `tts.say` instances (say,
different voices) coexist without reading every message twice.

**Plugin contract.** Every plugin implements an async lifecycle:

```python
class Plugin(Protocol):
    name: str
    async def start(self, ctx: Context) -> None: ...
    async def stop(self, ctx: Context) -> None: ...
```

A `Context` gives a plugin the channels it publishes to, its validated config
section, a logger, and a cancel signal. A plugin's *role* (sink / handler /
TTS / output) is just which channels it reads and writes — nothing in core
assumes a fixed slot, which is what keeps it extensible.

**Registry & instances.** Built-in plugins register by name (`sink.twitch`,
`handler.tts`, `tts.say`, `output.local`); a name resolves to an import path
(e.g. `sink.twitch` → `pitwall.plugins.sink_twitch`). The config instantiates
them: each config table is one **instance** of a plugin — `[voice_daniel]` and
`[voice_samantha]` are two instances of `tts.say` with different configs —
identified by its table name. A plugin can be instantiated any number of
times. Future external plugins would resolve via setuptools entry points — not
built in v1, but the registry shape leaves the seam open.

**Data models** (dataclasses in `core/events.py`):

- `Message(source, user, text, ts, kind="chat", raw=None)`
- `SpeakRequest(text, source=None, user=None, meta=None, target=None)` —
  `target` names the TTS instance that should read it (see targeted delivery).
- `Audio(text, source=None, user=None, played=False)` — in v1 it carries the
  text plus a "played" marker; a future TTS returns bytes/stream that an output
  consumes.

**v1 plugins**

- `sink.twitch` — read-only Twitch chat via `twitchio`, connected with the
  simplest credential mode it supports: **anonymous** (`justinfan`) preferred,
  an app token (`chat:read`) as fallback. No user OAuth in v1. Reconnects on
  drop. Publishes `Message` to `messages`.
- `handler.tts` — the "read messages via TTS" handler. Consumes `messages`; each
  message runs through a **filter chain** (always: skip whispers, skip the bot's
  own user; then any configured filters), and survivors are published to `speak`
  rendered through an utterance template.
  - *Filter infrastructure*: the config declares a list of named filters a
    message must **all** pass to be spoken. v1 ships one example filter,
    `min_length`, which skips messages shorter than 2 characters; everything
    else is read. More named filters (by user, keyword, emote-only) drop in
    later without touching core.
  - *Utterance template*: how a `Message` becomes spoken text. Default
    `"{user} says: {text}"` (configurable).
  - *Target*: optional `target` config pins the handler's output to one TTS
    instance (sets `SpeakRequest.target`); unset means every TTS instance
    reads. A future filter could set it per message (e.g. a per-viewer voice).
  This is the only v1 handler; command handling is a future handler.
- `tts.say` — consumes `speak`; runs `say [-v voice] [-r rate] "<text>"` as a
  subprocess to play locally; publishes `Audio(..., played=True)` to `audio`.
- `output.local` — consumes `audio`; in v1 it confirms / logs playback. This is
  the seam: a future `output.discord` / `output.pulse` consumes the same channel.

**Seam note.** Because `say` writes to the device itself, the `audio`→`output`
stage is real plumbing but `say` does the device write in v1; `output.local` is
a thin confirmation and becomes the real output router when a future TTS returns
routable audio.

**Config & restart**

- Path: `$XDG_CONFIG_HOME/pitwall/config.toml` (fallback
  `~/.config/pitwall/config.toml`; `$XDG_CONFIG_HOME` may be unset).
- Shape: every top-level table is one **plugin instance** — the table name is
  the instance ID, `plugin` names the plugin, and the remaining keys are that
  instance's config. `enabled = false` disables an instance (default `true`);
  there is no separate enabled list. A table missing its `plugin` key is a
  config error. Filters live in a nested `filters` table inside their handler
  instance. v1 example (one of everything, plus a second disabled voice):

```toml
[twitch]
plugin = "sink.twitch"
channel = "<your channel>"      # the only required value

[reader]                        # an instance of handler.tts
plugin = "handler.tts"
template = "{user} says: {text}"
filters = ["min_length"]
# target = "voice_daniel"       # pin to one TTS instance; all when unset

[reader.filters.min_length]
min = 2

[voice_daniel]
plugin = "tts.say"
voice = "Daniel"

[voice_samantha]                # same plugin, second instance
plugin = "tts.say"
voice = "Samantha"
enabled = false

[speakers]
plugin = "output.local"
```
- Watched with `watchfiles`. On change: validate; if valid, **gracefully tear
  down and rebuild** the plugin graph in-process (stop all plugin tasks, close
  the Twitch connection, start the new graph). If invalid / malformed —
  including a `target` naming an unknown or disabled instance — keep the
  last-good graph and log the error. No shell relaunch.
- Signals: `SIGINT` / `SIGTERM` → graceful shutdown (stop plugins, close
  connections, exit).

**Resilience.** Each plugin task runs under a supervisor that logs exceptions
and restarts the plugin with backoff, so a single plugin's failure can't take
down the loop. `twitchio` handles chat reconnection.

## Decisions settled with the user

- Pipeline: typed channels (option C).
- Read-only Twitch with the simplest credential mode: anonymous (`justinfan`)
  preferred, app token fallback; no message sending and no user OAuth in v1.
- `!ping` deferred.
- `say` for TTS, local audio output, macOS only for v1.
- Single command; config-driven restart happens in-process.
- The handler ships **filter infrastructure** with an example filter that skips
  messages under 2 characters; everything else is read.
- The utterance includes the username by default: `"{user} says: {text}"`.
- Config is **instance-based**: one table per plugin instance (a `plugin` key
  plus a free-form instance name), `enabled` per instance; the same plugin can
  be instantiated multiple times (e.g. two `tts.say` voices).
- Routing is **target-based**: an event may name a target instance; delivery
  goes there only, or to every instance on the channel when unset.
- If `twitchio` can't run on Python 3.15, the Python pin bends (the newest
  version twitchio supports, via `uv`); hand-rolling IRC is a last resort.

## Calls the author is making (correct these on the doc if wrong)

- `tts.say` defaults to the system default voice; `voice` / `rate` are
  configurable per instance.
- Filters are named predicates declared in a nested
  `[instance.filters.<name>]` table inside a `handler.tts` instance — not a
  separate plugin type yet; they get promoted if they ever need behavior beyond
  a config table.
- Layout: a `src/pitwall/` package — core in `core/`, plugins in `plugins/`,
  entry via `__main__.py` plus a `pitwall` console script.
- Testing: `pytest` + `pytest-asyncio`; mock `say` (assert the command line) and
  mock `twitchio` (feed synthetic messages). Ruff for lint + format.

## Left to the builder

- Confirm twitchio's anonymous (`justinfan`) vs. app-token support and write the
  connection accordingly; note its reconnection behavior.
- The filter-chain API surface inside `handler.tts` and the template syntax
  (str.format-style vs. simple `{user}` / `{text}` substitution).
- A backpressure policy if `say` can't keep up (drop oldest vs. queue) on the
  `speak` / `audio` channels.
- The precise `Context` / registry API surface.
- Graceful-teardown ordering (which channel drains first on stop).
- How the `say` subprocess is launched per request, and whether long messages are
  chunked.
