# TTS Pause Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the audible gaps between username / "says" / text in spoken chat while keeping per-placeholder voices.

**Architecture:** `handler.tts` renders the utterance template into `Segment`s; TTS plugins synthesize each segment to a file; `output.local` plays them in index order. The fix merges adjacent segments that share `(voice, target)` at render time (one join disappears; single-voice configs collapse to one clip) and trims the silence Kokoro pads onto clip edges in `tts.mlx` (the remaining join tightens). The default template loses the word "says".

**Tech Stack:** Python 3.15+, asyncio, numpy (dev-only, for tests of the trim).

**Spec:** `docs/superpowers/specs/2026-11-22-tts-pause-fix-design.md`

## Global Constraints

- All tooling through `uv`; gates in CI order: `make lint && make typecheck && make test`.
- ruff line-length 100; mypy checks `src/` only; pytest-asyncio is `asyncio_mode = "auto"` (async tests need no marker).
- Tests are hermetic: no network, no macOS, no mlx-audio import. `numpy` becomes a dev dependency (Task 3) so trim tests run everywhere.
- Keep the numpy import inside `tts_mlx` functions (lazy): the module must import without the mlxaudio extra.
- Preserve the hot-reload invariant: no config-format break; `template` stays a plain string value.
- Conventional commits (`fix(handler): ...`, `docs: ...`); user-facing changes ship README/example-config edits in the same commit.
- After editing `config.toml.example`, run `tests/test_config.py::test_example_config_loads_and_names_known_plugins`.

## Review Focus

1. All-silent audio (Kokoro glitch) reaching the trim must not crash or slice negatively — pinned in Task 3.
2. Audio shorter than the 20 ms pad must clamp to array bounds, not underflow — pinned in Task 3.
3. Segments sharing a voice but routed to different targets must NOT merge (wrong speaker routing) — pinned in Task 1.
4. Indices after a merge must stay contiguous `0..n-1`; `output.local` stalls 5 s then flushes out of order on any gap — pinned in Task 1.
5. A template with no placeholders must still render one literal segment — pinned in Task 1.

---

### Task 0: Land the design docs

**Files:**
- Create: already written — `docs/superpowers/specs/2026-11-22-tts-pause-fix-design.md`, this plan.

- [ ] **Step 1: Commit spec and plan**

```bash
git add docs/superpowers/specs/2026-11-22-tts-pause-fix-design.md docs/superpowers/plans/2026-11-22-tts-pause-fix.md
git commit -m "docs: add tts pause fix design spec and plan"
```

### Task 1: Merge adjacent same-voice segments in `render()`

**Files:**
- Modify: `src/pitwall/plugins/handler_tts.py` (`render`, lines 45-80, plus its docstring)
- Test: `tests/test_handler_tts.py` (update 3 pinned tests, add 4)

**Interfaces:**
- Produces: `render(template, message, voices=None, targets=None, target=None) -> tuple[Segment, ...]` — same signature, new contract: after splitting, adjacent segments whose `(voice, target)` pairs are equal are concatenated into one `Segment` (text joined), indices renumbered `0..n-1`. `Segment` and `SpeakRequest` are unchanged.

- [ ] **Step 1: Update the pinned tests and write the new failing ones**

Update in `tests/test_handler_tts.py`:

```python
def test_render_default_template_no_maps():
    segs = render("{user} says: {text}", msg("hi"), {})
    assert [s.text for s in segs] == ["alice says: hi"]
    assert all(s.voice is None and s.target is None for s in segs)
    assert [s.index for s in segs] == [0]


def test_render_voices_targets_and_literal_inheritance():
    segs = render(
        "{user} says: {text}",
        msg("hi"),
        voices={"user": "samantha", "text": "daniel"},
        targets={"text": "cloud"},
    )
    assert [s.text for s in segs] == ["alice says: ", "hi"]
    assert [s.voice for s in segs] == ["samantha", "daniel"]
    assert [s.target for s in segs] == [None, "cloud"]
    assert [s.index for s in segs] == [0, 1]


def test_render_request_target_fills_placeholders():
    segs = render("{user}: {text}", msg("b"), {}, target="mac")
    assert len(segs) == 1  # same voice+target throughout: merged
    assert all(s.target == "mac" for s in segs)
```

Add:

```python
def test_render_merges_adjacent_same_voice_segments():
    segs = render(
        "{user} says {text}", msg("hi"), voices={"user": "af_heart", "text": "am_michael"}
    )
    assert [s.text for s in segs] == ["alice says ", "hi"]
    assert [s.voice for s in segs] == ["af_heart", "am_michael"]
    assert [s.index for s in segs] == [0, 1]


def test_render_no_maps_collapses_to_one_segment():
    segs = render("{user} says {text}", msg("hi"), {})
    assert [s.text for s in segs] == ["alice says hi"]


def test_render_does_not_merge_across_targets():
    segs = render("{user} says {text}", msg("hi"), targets={"text": "cloud"})
    # literal keeps the user's target (None); text is routed to cloud: no merge
    assert [s.text for s in segs] == ["alice says ", "hi"]
    assert [s.target for s in segs] == [None, "cloud"]
    assert [s.index for s in segs] == [0, 1]


def test_render_template_without_placeholders_is_one_literal():
    segs = render("hello world", msg("hi"), {})
    assert [s.text for s in segs] == ["hello world"]
    assert segs[0].index == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handler_tts.py -q`
Expected: FAIL — the merge tests see 3 segments where they assert 1 or 2.

- [ ] **Step 3: Implement the merge in `render()`**

After the existing split loop builds `segments`, walk it once appending to a
result list: when a segment's `(voice, target)` equals the previous result
entry's, replace that entry with a new `Segment(prev.text + cur.text, ...)`
(same voice/target, same index); otherwise append with `index=len(result)`.
Update `render`'s docstring to state the merge contract.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handler_tts.py -q`
Expected: PASS (all, including the untouched filter/harness tests).

- [ ] **Step 5: Commit**

```bash
git add src/pitwall/plugins/handler_tts.py tests/test_handler_tts.py
git commit -m "fix(handler): merge adjacent segments with the same voice and target"
```

### Task 2: Drop "says" from the default template

**Files:**
- Modify: `src/pitwall/plugins/handler_tts.py:19` (`DEFAULT_TEMPLATE`)
- Modify: `config.toml.example` ([[handler.tts]] block)
- Modify: `README.md` (only if it names the default template — check first)
- Modify: `config.toml` (local, gitignored — not committed)
- Test: `tests/test_handler_tts.py`

**Interfaces:**
- Consumes: Task 1's `render` merge contract.
- Produces: `DEFAULT_TEMPLATE = "{user} {text}"`.

- [ ] **Step 1: Write the failing test**

```python
async def test_default_template_is_user_then_text_without_says():
    assert "{user}" in DEFAULT_TEMPLATE and "{text}" in DEFAULT_TEMPLATE
    assert "says" not in DEFAULT_TEMPLATE
    h = Harness({})
    await h.run(msg("hi"))
    segs = h.speak_q.get_nowait().segments
    assert [s.text for s in segs] == ["alice hi"]
```

Import `DEFAULT_TEMPLATE` alongside `render` in the test file's import line.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handler_tts.py::test_default_template_is_user_then_text_without_says -v`
Expected: FAIL with ImportError (`DEFAULT_TEMPLATE` not imported yet) or "says" assertion.

- [ ] **Step 3: Change the default and ship the docs**

Set `DEFAULT_TEMPLATE = "{user} {text}"` in `handler_tts.py`. In
`config.toml.example`, add a commented line to the `[[handler.tts]]` block:
`# template = "{user} {text}"  # default; nothing but a space is spoken`.
Grep `README.md` for the old template or "says"; update any hit, else leave it.

- [ ] **Step 4: Run the config pinning test**

Run: `uv run pytest tests/test_handler_tts.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pitwall/plugins/handler_tts.py tests/test_handler_tts.py config.toml.example README.md
git commit -m "fix(handler): drop \"says\" from the default utterance template"
```

### Task 3: Trim Kokoro's edge silence in `tts.mlx`

**Files:**
- Modify: `src/pitwall/plugins/tts_mlx.py` (`render_segment` + new helper)
- Modify: `pyproject.toml` (dev group: add `numpy`)
- Test: `tests/test_tts_mlx.py`

**Interfaces:**
- Produces: module-level `trim_silence(audio: Any, sample_rate: int) -> Any` and constants `SILENCE_THRESHOLD = 0.01`, `EDGE_PAD_SECONDS = 0.02` in `tts_mlx.py`. `render_segment` signature is unchanged (plugin tests monkeypatch it).

- [ ] **Step 1: Add numpy to the dev group and sync**

Add `"numpy"` to `dependency-groups.dev` in `pyproject.toml`, then `uv sync`.

- [ ] **Step 2: Write the failing tests**

At the top of `tests/test_tts_mlx.py`: `import numpy as np` and import
`render_segment, trim_silence, SILENCE_THRESHOLD, EDGE_PAD_SECONDS` from
`pitwall.plugins.tts_mlx`.

```python
def test_trim_silence_drops_edges_keeps_pad():
    sr = 1000  # pad = int(1000 * 0.02) = 20 samples
    audio = np.concatenate([np.zeros(300), np.full(200, 0.5), np.zeros(400)])
    trimmed = trim_silence(audio, sr)
    assert len(trimmed) == 200 + 2 * int(sr * EDGE_PAD_SECONDS)


def test_trim_silence_clamps_when_shorter_than_pad():
    audio = np.array([0.0, 0.0, 0.5, 0.0, 0.0])
    trimmed = trim_silence(audio, 100_000)  # pad huge, must clamp
    assert len(trimmed) == 5


def test_trim_silence_all_silent_unchanged():
    audio = np.zeros(500)
    assert len(trim_silence(audio, 24_000)) == 500


def test_render_segment_trims_padded_audio(tmp_path):
    class Result:
        sample_rate = 24_000
        audio = np.concatenate([np.zeros(2000), np.full(500, 0.5), np.zeros(3000)])

    class Model:
        def generate(self, text, **kwargs):
            yield Result()

    path = str(tmp_path / "out.wav")
    render_segment(Model(), "hi", None, None, path)
    with wave.open(path) as w:
        frames = w.getnframes()
    # speech at [2000, 2500); pad = 480 -> [1520, 2980) = 1460 frames
    assert frames == 1460
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_tts_mlx.py -q`
Expected: FAIL with ImportError (`trim_silence` not defined).

- [ ] **Step 4: Implement the trim**

Add `SILENCE_THRESHOLD = 0.01` and `EDGE_PAD_SECONDS = 0.02` at module level.
`trim_silence(audio, sample_rate)`: `import numpy as np` inside (keep the
module importable without the extra); `loud = np.flatnonzero(np.abs(audio) > SILENCE_THRESHOLD)`;
return `audio` unchanged when `loud` is empty; else
`audio[max(0, loud[0] - pad) : min(len(audio), loud[-1] + 1 + pad)]` with
`pad = int(sample_rate * EDGE_PAD_SECONDS)`. In `render_segment`, apply it to
the concatenated float array before the PCM conversion.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tts_mlx.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pitwall/plugins/tts_mlx.py tests/test_tts_mlx.py pyproject.toml uv.lock
git commit -m "fix(tts): trim silence kokoro pads onto clip edges"
```

### Task 4: Point the live config at the new template and run the gates

**Files:**
- Modify: `config.toml` (local, gitignored — never committed)

- [ ] **Step 1: Update the local config**

Set `template = "{user} {text}"` in the `[[handler.tts]]` block of the local
`config.toml`. If pitwall is running, the hot reload picks it up on save.

- [ ] **Step 2: Run the full gates**

Run: `make lint && make typecheck && make test`
Expected: all three green. Nothing to commit (config.toml is gitignored).
