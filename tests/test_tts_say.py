import asyncio
import logging
from pathlib import Path

from pitwall.core.channels import Channel
from pitwall.core.events import Segment, SpeakRequest
from pitwall.core.plugin import Context
from pitwall.plugins import tts_say
from pitwall.plugins.tts_say import SayTtsPlugin, synth_args


def test_synth_args_with_voice_and_rate():
    cfg = {"voice": "Alex", "rate": 200, "voices": {"d": "Daniel"}}
    args = synth_args(cfg, Segment("hi", "d"), "/tmp/x.aiff")
    assert args == ["say", "-o", "/tmp/x.aiff", "-v", "Daniel", "-r", "200", "hi"]


def test_synth_args_defaults():
    assert synth_args({}, Segment("hi"), "/tmp/x.aiff") == ["say", "-o", "/tmp/x.aiff", "hi"]


class FakeSubprocess:
    """Records args; can be told to fail N times or to serialize start/end."""

    def __init__(self, failures: int = 0, delay: float = 0.0):
        self.calls: list[list[str]] = []
        self.events: list[tuple[str, list[str]]] = []
        self.failures = failures
        self.delay = delay

    async def __call__(self, args: list[str]) -> None:
        self.events.append(("start", list(args)))
        if self.failures > 0:
            self.failures -= 1
            raise FileNotFoundError(f"no binary: {args[0]}")
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append(list(args))
        self.events.append(("end", list(args)))


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


async def run_say(config: dict, requests: list[SpeakRequest], fake: FakeSubprocess, monkeypatch):
    monkeypatch.setattr(tts_say, "create_subprocess", fake)
    ctx = make_ctx(config)
    audio_q = ctx.audio.subscribe("speakers")
    plugin = SayTtsPlugin(config)
    task = asyncio.create_task(plugin.start(ctx))
    await asyncio.sleep(0.01)
    for request in requests:
        await ctx.speak.publish(request)
    await asyncio.sleep(0.05)
    ctx.stopping.set()
    await asyncio.wait_for(task, timeout=1)
    await plugin.stop(ctx)
    return audio_q


def request(*segments: Segment, rid="r1") -> SpeakRequest:
    return SpeakRequest(request_id=rid, segments=segments)


async def test_segments_synthesized_in_order(monkeypatch):
    fake = FakeSubprocess(delay=0.01)
    await run_say(
        {},
        [request(Segment("alice", index=0), Segment(" says: ", index=1), Segment("hi", index=2))],
        fake,
        monkeypatch,
    )
    assert [c[-1] for c in fake.calls] == ["alice", " says: ", "hi"]
    assert [c[0] for c in fake.calls] == ["say", "say", "say"]
    assert all("-o" in c for c in fake.calls)
    # strictly sequential: each start waits for the previous end
    kinds = [e[0] for e in fake.events]
    assert kinds == ["start", "end"] * 3


async def test_audio_events_carry_request_id_and_index(monkeypatch, tmp_path):
    fake = FakeSubprocess()
    q = await run_say(
        {}, [request(Segment("a", index=0), Segment("b", index=1))], fake, monkeypatch
    )
    events = [q.get_nowait(), q.get_nowait()]
    assert [e.index for e in events] == [0, 1]
    assert all(e.request_id == "r1" for e in events)
    assert all(Path(e.path).exists() for e in events)
    for e in events:
        Path(e.path).unlink()


async def test_unknown_voice_key_falls_back_with_warning(monkeypatch, caplog):
    fake = FakeSubprocess()
    caplog.set_level(logging.WARNING, logger="pitwall.mix")
    await run_say(
        {"voice": "Alex"},
        [request(Segment("hi", voice="ghost", index=0))],
        fake,
        monkeypatch,
    )
    assert fake.calls[0] == ["say", "-o", fake.calls[0][2], "-v", "Alex", "hi"]
    assert "ghost" in caplog.text


async def test_unicode_survives(monkeypatch):
    fake = FakeSubprocess()
    await run_say({}, [request(Segment("😀 hi", index=0))], fake, monkeypatch)
    assert fake.calls[0][-1] == "😀 hi"


async def test_missing_say_binary_logged_not_fatal(monkeypatch, caplog):
    fake = FakeSubprocess(failures=1)
    caplog.set_level(logging.ERROR, logger="pitwall.mix")
    q = await run_say(
        {}, [request(Segment("a", index=0), Segment("b", index=1))], fake, monkeypatch
    )
    assert len(fake.calls) == 1  # second segment still synthesized
    assert "say" in caplog.text  # first failure logged
    assert q.qsize() == 1  # no Audio for the failed segment
    event = q.get_nowait()
    assert event.index == 1
    Path(event.path).unlink()
