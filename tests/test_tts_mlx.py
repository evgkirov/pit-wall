import asyncio
import logging
import sys
import time
from pathlib import Path

import pytest

from pitwall.core.channels import Channel
from pitwall.core.events import Segment, SpeakRequest
from pitwall.core.plugin import Context
from pitwall.core.registry import factory_for
from pitwall.plugins import register_builtins, tts_mlx
from pitwall.plugins.tts_mlx import DEFAULT_MODEL, MlxTtsPlugin


class FakeLoader:
    def __init__(self, error: Exception | None = None):
        self.repos: list[str] = []
        self.error = error

    def __call__(self, repo: str):
        self.repos.append(repo)
        if self.error:
            raise self.error
        return object()


class FakeRenderer:
    """Records (text, voice, speed); can fail N times or sleep per call."""

    def __init__(self, failures: int = 0, delay: float = 0.0):
        self.calls: list[tuple[str, str | None, float | None]] = []
        self.failures = failures
        self.delay = delay

    def __call__(self, model, text, voice, speed, path):
        self.calls.append((text, voice, speed))
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("synthesis boom")
        if self.delay:
            time.sleep(self.delay)
        Path(path).write_bytes(b"RIFF")


def make_ctx(config: dict) -> Context:
    return Context(
        instance="mix",
        config=config,
        logger=logging.getLogger("pitwall.mix"),
        messages=Channel("messages"),
        speak=Channel("speak"),
        audio=Channel("audio"),
        stopping=asyncio.Event(),
    )


async def run_mlx(
    config: dict,
    requests: list[SpeakRequest],
    loader: FakeLoader,
    renderer: FakeRenderer,
    monkeypatch,
    settle: float = 0.05,
):
    monkeypatch.setattr(tts_mlx, "load_model", loader)
    monkeypatch.setattr(tts_mlx, "render_segment", renderer)
    ctx = make_ctx(config)
    audio_q = ctx.audio.subscribe("speakers")
    plugin = MlxTtsPlugin(config)
    task = asyncio.create_task(plugin.start(ctx))
    await asyncio.sleep(0.01)
    for request in requests:
        await ctx.speak.publish(request)
    await asyncio.sleep(settle)
    ctx.stopping.set()
    await asyncio.wait_for(task, timeout=5)
    await plugin.stop(ctx)
    return audio_q


def request(*segments: Segment, rid="r1") -> SpeakRequest:
    return SpeakRequest(request_id=rid, segments=segments)


def test_registered_in_builtin_registry():
    register_builtins()
    assert factory_for("tts.mlx") is MlxTtsPlugin


def test_missing_extra_raises_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_audio", None)
    with pytest.raises(RuntimeError, match="mlxaudio"):
        tts_mlx.load_model("mlx-community/Kokoro-82M-bf16")


async def test_model_defaults_to_kokoro_repo(monkeypatch):
    loader = FakeLoader()
    await run_mlx({}, [request(Segment("hi", index=0))], loader, FakeRenderer(), monkeypatch)
    assert loader.repos == [DEFAULT_MODEL]


async def test_model_config_override(monkeypatch):
    loader = FakeLoader()
    await run_mlx(
        {"model": "mlx-community/Kokoro-82M-8bit"},
        [request(Segment("hi", index=0))],
        loader,
        FakeRenderer(),
        monkeypatch,
    )
    assert loader.repos == ["mlx-community/Kokoro-82M-8bit"]


async def test_renders_segments_with_resolved_voices_and_speed(monkeypatch):
    renderer = FakeRenderer()
    await run_mlx(
        {"voices": {"user": "af_heart", "text": "am_michael"}, "speed": 1.2},
        [request(Segment("alice", voice="user", index=0), Segment("hi", voice="text", index=1))],
        FakeLoader(),
        renderer,
        monkeypatch,
    )
    assert renderer.calls == [("alice", "af_heart", 1.2), ("hi", "am_michael", 1.2)]


async def test_audio_events_carry_request_id_and_index(monkeypatch):
    q = await run_mlx(
        {},
        [request(Segment("a", index=0), Segment("b", index=1))],
        FakeLoader(),
        FakeRenderer(),
        monkeypatch,
    )
    events = [q.get_nowait(), q.get_nowait()]
    assert [e.index for e in events] == [0, 1]
    assert all(e.request_id == "r1" for e in events)
    assert all(e.path.endswith(".wav") for e in events)
    assert all(Path(e.path).exists() for e in events)
    for e in events:
        Path(e.path).unlink()


async def test_unknown_voice_key_falls_back_with_warning(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="pitwall.mix")
    renderer = FakeRenderer()
    await run_mlx(
        {"voice": "af_heart"},
        [request(Segment("hi", voice="ghost", index=0))],
        FakeLoader(),
        renderer,
        monkeypatch,
    )
    assert renderer.calls == [("hi", "af_heart", None)]
    assert "ghost" in caplog.text


async def test_render_failure_logged_not_fatal(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="pitwall.mix")
    renderer = FakeRenderer(failures=1)
    q = await run_mlx(
        {},
        [request(Segment("a", index=0), Segment("b", index=1))],
        FakeLoader(),
        renderer,
        monkeypatch,
    )
    assert len(renderer.calls) == 2  # second segment still synthesized
    assert "segment" in caplog.text  # first failure logged
    assert q.qsize() == 1  # no Audio for the failed segment
    event = q.get_nowait()
    assert event.index == 1
    Path(event.path).unlink()


async def test_slow_render_preserves_order(monkeypatch):
    renderer = FakeRenderer(delay=0.03)
    q = await run_mlx(
        {},
        [request(Segment("a", index=0), Segment("b", index=1), Segment("c", index=2))],
        FakeLoader(),
        renderer,
        monkeypatch,
        settle=0.25,
    )
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e.index for e in events] == [0, 1, 2]
    assert [c[0] for c in renderer.calls] == ["a", "b", "c"]
    for e in events:
        Path(e.path).unlink()


async def test_unicode_survives(monkeypatch):
    renderer = FakeRenderer()
    await run_mlx({}, [request(Segment("😀 hi", index=0))], FakeLoader(), renderer, monkeypatch)
    assert renderer.calls[0][0] == "😀 hi"


async def test_model_load_failure_propagates_from_start(monkeypatch):
    loader = FakeLoader(error=RuntimeError("no such repo"))
    monkeypatch.setattr(tts_mlx, "load_model", loader)
    ctx = make_ctx({})
    plugin = MlxTtsPlugin({})
    with pytest.raises(RuntimeError, match="no such repo"):
        await asyncio.wait_for(plugin.start(ctx), timeout=5)
    await plugin.stop(ctx)
