# TTS pause fix — design

## Intent

Spoken chat sounds like "Username. <pause>. says. <pause>. text". Kill the gaps
between the parts while keeping the two-voice setup (username ≠ text voices).

## Why it happens

`handler.tts` renders `{user} says {text}` into three segments (username,
literal, text). Each segment is a separate Kokoro generation, synthesized
serially, and Kokoro pads every clip with silence at its edges. Three clips →
two joins → a pause at each, plus a wait while the long text clip generates
after the short ones.

## Decisions

- Keep per-placeholder voices (user's call — config deliberately sets two).
- Remove "says" from the default template (user's call): `"{user} {text}"`.

## Approach

1. **Merge adjacent segments** with equal `(voice, target)` in
   `handler_tts.render()`; indices renumbered 0..n-1. With two voices the
   request becomes two clips ("username " + text); with no voice map it
   collapses to one clip. Benefits `tts.say` equally (fewer process spawns).
2. **Trim edge silence** in `tts_mlx.render_segment()` after generation:
   drop leading/trailing samples under an amplitude threshold (0.01), keep a
   20 ms pad so onsets don't click. Tightens the one remaining join.
3. Update the default template, the local config, `config.toml.example`
   comment, README, and the tests that pin the old segmentation.

## Non-goals

- Parallel per-segment generation: one model instance, thread-safety of
  `model.generate` is undocumented; the merge already removes the serial
  overhead that mattered.
- Sentence-chunked streaming playback for very long messages — revisit if a
   gap is still audible once generation of a long text outruns playback.

## Approaches considered

- **Single voice everywhere** — one clip, zero joins, but throws away the
  two-voice feature the config deliberately uses. Rejected by the user.
- **Parallel synthesis** — marginal gain (< 1 s) and a crash/garbage-audio
  risk. Deferred (non-goal above).
- **Merge + trim** — keeps both voices, removes one join entirely and tightens
  the other. Chosen.
