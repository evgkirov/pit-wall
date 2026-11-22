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
- Run as one command (`make run`) with graceful start / stop / restart.
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

**Routing.** A segment may name a `target` (an instance alias); it falls back
to the request's `target`, and failing that the request is broadcast to every
TTS instance. The `speak` channel splits a request per distinct target,
delivering each instance a sub-request holding its segments with their original
indices intact.

**Ordering lives at the output.** TTS instances are *synthesizers*: they turn
each segment into an `Audio` event tagged `(request_id, index)` and never touch
the speaker. The output instance is the *player*: it buffers per `request_id`
and plays parts in `index` order. Parts may therefore be synthesized in
parallel — even by different backends, say `tts.say` for usernames and a future
`tts.elevenlabs` for messages — and still play as one utterance, in order.

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
them: each top-level key is a **plugin name** whose value is an array of
instance tables — two `[[tts.say]]` blocks are two instances with different
configs — and each instance is identified by its `alias` (defaulting to the
plugin name's last dotted component: `sink.twitch` → `twitch`), unique across
the whole file. A plugin can be instantiated any number of times. Future
external plugins would resolve via setuptools entry points — not built in v1,
but the registry shape leaves the seam open.

**Data models** (dataclasses in `core/events.py`):

- `Message(source, user, text, ts, kind="chat", raw=None)`
- `Segment(text, voice=None, target=None, index=0)` — one spoken part.
  `voice` is a voice *key* the TTS instance resolves (`None` = its default
  voice); `target` is an instance alias (falls back to the request's target);
  `index` is the part's position in the utterance.
- `SpeakRequest(request_id, segments, source=None, user=None, meta=None,
  target=None)` — a unique `request_id` (assigned by the handler) plus an
  ordered tuple of `Segment`s.
- `Audio(path, request_id, index, source=None, user=None)` — a synthesized
  audio file (AIFF from `say`, whatever a backend produces) plus its ordering
  tags.

**v1 plugins**

- `sink.twitch` — read-only Twitch chat via `twitchio`, connected with the
  simplest credential mode it supports: **anonymous** (`justinfan`) preferred,
  an app token (`chat:read`) as fallback. No user OAuth in v1. Reconnects on
  drop. Publishes `Message` to `messages`.
- `handler.tts` — the "read messages via TTS" handler. Consumes `messages`; each
  message runs through a **filter chain** (always: skip whispers, skip the bot's
  own user; then any configured filters), and survivors are published to `speak`
  rendered through an utterance template.
  - *Filter infrastructure*: the handler's `filters` key is an ordered table
    of named filters (`{ min_length = { min = 2 } }`); a message must pass
    **all** of them, in order, to be spoken. v1 ships one example filter,
    `min_length`, which skips messages shorter than 2 characters; everything
    else is read. More named filters (by user, keyword, emote-only) drop in
    later without touching core.
  - *Utterance template*: how a `Message` becomes spoken segments. Default
    `"{user} says: {text}"` (configurable). Rendering splits the template into
    a segment per placeholder; an optional `voices` map (placeholder → voice
    key, e.g. `{user = "samantha", text = "daniel"}`) keys any placeholder's
    part, and a literal run joins the preceding placeholder's voice — so the
    default template reads "Alice says:" in the username's voice and the
    message text in another.
  - *Routing*: an optional `target` config pins the handler's requests to one
    TTS instance; an optional `targets` map (placeholder → alias) routes a
    single placeholder elsewhere — e.g. usernames to `tts.say`, messages to a
    future `tts.elevenlabs`. Unset means broadcast. A literal run joins the
    preceding placeholder's voice **and** target.
  This is the only v1 handler; command handling is a future handler.
- `tts.say` — a *synthesizer*: for each segment of a request, resolve the
  voice (default `voice` and `rate`, a `voices` map of key → `say` voice name,
  unknown key → warning + default), run
  `say -o <tmpfile> [-v <voice>] [-r rate] "<text>"`, and publish
  `Audio(path=tmpfile, request_id, index)` to `audio`. It never plays audio
  itself.
- `output.local` — the *player*: consumes `audio`, buffers parts per
  `request_id`, and plays them in `index` order via `afplay`, deleting each
  file after playback. A stall timeout flushes a partial request so a lost
  part can't block the queue forever. A future `output.discord` consumes the
  same channel the same way.

**Config & restart**

- Path: `$XDG_CONFIG_HOME/pitwall/config.toml` (fallback
  `~/.config/pitwall/config.toml`; `$XDG_CONFIG_HOME` may be unset).
- Shape: every top-level key is a **plugin name** whose value is an array of
  instance tables (`[[plugin.name]]`). Each instance table has an optional
  string `alias` — its identity, what `target` and voice keys reference —
  defaulting to the plugin name's last dotted component (`sink.twitch` →
  `twitch`); an optional `enabled` (default `true`); and the rest is that
  instance's config. A duplicate alias, explicit or derived (two alias-less
  `[[tts.say]]` blocks both become `say`), is a config error. Filters live
  inline in the handler instance as an ordered table (`name → config`).
  v1 example (one of everything; usernames read in Samantha, messages in
  Daniel):

```toml
[[sink.twitch]]                 # no alias → defaults to "twitch"
channel = "<your channel>"      # the only required value

[[handler.tts]]
alias = "reader"
template = "{user} says: {text}"
filters = { min_length = { min = 2 } }           # applied in order, all must pass
voices = { user = "samantha", text = "daniel" }  # placeholder → voice key
# target = "mix"                # pin to one TTS alias; all when unset
# targets = { text = "cloud" }  # per-placeholder alias override (e.g. ElevenLabs)

[[tts.say]]
alias = "mix"                   # synthesizes parts in order; playback is output's
voice = "Alex"                  # default for unkeyed parts
rate = 180
voices = { samantha = "Samantha", daniel = "Daniel" }  # key → say voice name

[[tts.say]]
alias = "backup"                # same plugin, second instance, disabled
enabled = false
voice = "Alex"

[[output.local]]
alias = "speakers"
```
- Watched with `watchfiles`. On change: validate; if valid, **gracefully tear
  down and rebuild** the plugin graph in-process (stop all plugin tasks, close
  the Twitch connection, start the new graph). If invalid / malformed —
  including a `target` naming an unknown or disabled alias — keep the
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
- Config is **plugin-keyed arrays**: each top-level key is a plugin name whose
  value is an array of instance tables; each instance has a file-wide-unique
  `alias` and optional `enabled`; the same plugin can be instantiated multiple
  times (e.g. two `tts.say` voices).
- Routing is **target-based**: an event may name a target instance; delivery
  goes there only, or to every instance on the channel when unset.
- The pipeline is **synthesizer/sequencer**: TTS instances synthesize parts to
  audio files tagged `(request_id, index)` and never touch the speaker; the
  output instance sequences and plays them. Per-part routing across TTS
  backends (say for usernames, ElevenLabs for messages) works without
  reordering or overlap.
- The user-facing entrypoint is `make run`.
- If `twitchio` can't run on Python 3.15, the Python pin bends (the newest
  version twitchio supports, via `uv`); hand-rolling IRC is a last resort.

## Calls the author is making (correct these on the doc if wrong)

- `tts.say` defaults to the system default voice; `voice` / `rate` are
  configurable per instance.
- Filters are named predicates declared inline in a `handler.tts` instance's
  `filters` table — not a separate plugin type yet; they get promoted if they
  ever need behavior beyond a config table.
- Layout: a `src/pitwall/` package — core in `core/`, plugins in `plugins/`,
  entry via `__main__.py` plus a `pitwall` console script. The user-facing
  entrypoint is a Makefile: `make run` (wraps `uv run pitwall`), with
  `make test` and `make lint` alongside.
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
