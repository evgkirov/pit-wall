import asyncio
import logging

import pytest

from pitwall.core.channels import Channel
from pitwall.core.events import Message
from pitwall.core.plugin import Context
from pitwall.plugins.handler_tts import TtsHandlerPlugin, render


def msg(text, kind="chat"):
    return Message(source="twitch", user="alice", text=text, ts=1.0, kind=kind)


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


def test_render_rejects_unknown_placeholder():
    with pytest.raises(ValueError, match="foo"):
        render("{foo}", msg("b"), {})


def test_unknown_filter_name_raises_at_construction():
    with pytest.raises(ValueError, match="nope"):
        TtsHandlerPlugin({"filters": {"nope": {}}})


def test_unknown_template_placeholder_raises_at_construction():
    with pytest.raises(ValueError, match="foo"):
        TtsHandlerPlugin({"template": "{user} said {foo}"})


class Harness:
    """A handler instance wired to real channels, plus a fake TTS subscriber."""

    def __init__(self, config: dict, subscriber: str = "fake-tts"):
        self.ctx = Context(
            instance="reader",
            config=config,
            logger=logging.getLogger("pitwall.reader"),
            messages=Channel("messages"),
            speak=Channel("speak"),
            audio=Channel("audio"),
            stopping=asyncio.Event(),
        )
        self.speak_q = self.ctx.speak.subscribe(subscriber)
        self.plugin = TtsHandlerPlugin(config)

    async def run(self, *messages: Message) -> None:
        task = asyncio.create_task(self.plugin.start(self.ctx))
        await asyncio.sleep(0.01)  # let it subscribe
        for message in messages:
            await self.ctx.messages.publish(message)
        await asyncio.sleep(0.05)  # let it process
        self.ctx.stopping.set()
        await asyncio.wait_for(task, timeout=1)
        await self.plugin.stop(self.ctx)


async def test_short_message_filtered():
    h = Harness({"filters": {"min_length": {"min": 2}}})
    await h.run(msg("x"), msg("xy"))
    assert h.speak_q.qsize() == 1
    assert h.speak_q.get_nowait().segments[-1].text.endswith("xy")


async def test_min_length_honors_configured_min():
    h = Harness({"filters": {"min_length": {"min": 5}}})
    await h.run(msg("abc"), msg("abcdef"))
    assert h.speak_q.qsize() == 1
    assert h.speak_q.get_nowait().segments[-1].text.endswith("abcdef")


async def test_whisper_not_spoken():
    h = Harness({})
    await h.run(msg("hello there", kind="whisper"), msg("hello there"))
    assert h.speak_q.qsize() == 1


async def test_request_ids_unique():
    h = Harness({})
    await h.run(msg("one"), msg("two"))
    first, second = h.speak_q.get_nowait(), h.speak_q.get_nowait()
    assert first.request_id != second.request_id


async def test_target_forwarded_to_request():
    h = Harness({"target": "mix"}, subscriber="mix")
    await h.run(msg("hi"))
    assert h.speak_q.get_nowait().target == "mix"
