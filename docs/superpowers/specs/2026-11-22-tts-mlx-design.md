# tts.mlx — MLX-Audio TTS plugin

**Status:** proposed · **Date:** 2026-11-22

## Intent

Add `tts.mlx`, a second synthesizer plugin built on [mlx-audio], so chat is read
with local neural voices instead of the macOS `say` voices. Swappable with
`tts.say` purely via config — same pipeline, same output plugin.

[mlx-audio]: https://pypi.org/project/mlx-audio/

## Why

`say` voices sound robotic. mlx-audio runs high-quality neural TTS locally on
the Apple Silicon machines this project already targets.

## Goals

- **Model-agnostic passthrough**: a `model` config key takes any mlx-audio
  model repo; voice names pass straight through to the model.
- **Documented default**: kokoro (`mlx-community/Kokoro-82M-bf16`) — fast,
  ~100 MB, preset voices like `af_heart`.
- **Same seam as `tts.say`**: writes WAV temp files, publishes `Audio` events;
  `output.local` plays them unchanged (`afplay` handles WAV).

## Non-goals

Streaming/chunked synthesis; voice cloning (`ref_audio`); STT/STS; any change
to `tts.say`.

## Anti-goals

- `mlx-audio` as a required dependency — CI runs ubuntu-latest and the suite
  is hermetic.
- Breaking the hot-reload invariant: a failed rebuild is logged and the
  previous plugin graph keeps running.

## Approaches

- **Model-agnostic passthrough (chosen)**: one plugin, any model, loose
  validation — per-model quirks surface at runtime.
- **Pinned to one model (rejected)**: tighter defaults and validation, but
  locked in; a second model later means a second plugin.

## Design

- Plugin name `tts.mlx`; module registered in `register_builtins()` and importable
  without mlx-audio installed — `mlx_audio` is imported lazily, with a clear
  error pointing at the missing extra.
- Optional extra in `pyproject.toml`:
  `[project.optional-dependencies] mlxaudio = ["mlx-audio[tts]>=0.6"]`.
- Config keys: `model` (default: the kokoro repo above), `voice` (default voice
  name), `voices` (key → model voice name, same shape as `tts.say`), `speed`
  (float multiplier; no `rate` equivalent).
- The model loads during `start()` via `asyncio.to_thread`, so a bad model name
  fails the rebuild loudly while the old graph keeps running. Synthesis runs in
  a thread too (MLX inference is synchronous).
- Unknown voice keys log a warning and fall back to the default voice — parity
  with `tts.say`.
- Tests fake the model exactly as the existing tests fake `say`/`afplay`: no
  network, no macOS, no MLX.

## Left to the builder

- Exact generate-result handling: sample rate and `mx.array` → WAV (stdlib
  `wave` or mlx-audio's save utils).
- Whether `config.toml.example` ships the `[[tts.mlx]]` block commented out
  with an install note for the extra.
