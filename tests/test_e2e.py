import asyncio

from pitwall.core.config import load_config
from pitwall.core.plugin import Context
from pitwall.core.registry import register
from pitwall.core.runtime import Runtime
from pitwall.plugins import output_local as output_local_mod
from pitwall.plugins import register_builtins
from pitwall.plugins import tts_say as tts_say_mod


class RecordingSubprocess:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def __call__(self, args: list[str]) -> None:
        self.calls.append(list(args))


class FakeSink:
    """Publishes one chat message on start, then finishes."""

    name = "test.sink"

    def __init__(self, config=None):
        self._config = config or {}

    async def start(self, ctx: Context) -> None:
        from pitwall.core.events import Message

        # A real sink crosses the network before its first message; emulate that
        # latency so downstream plugins have subscribed by the time we publish.
        await asyncio.sleep(0.05)
        await ctx.messages.publish(
            Message(source="twitch", user="alice", text="hello world", ts=1.0)
        )

    async def stop(self, ctx: Context) -> None:
        pass


CONFIG = """
[[test.sink]]

[[handler.tts]]
alias = "reader"
voices = { user = "samantha", text = "daniel" }

[[tts.say]]
voices = { samantha = "Samantha", daniel = "Daniel" }

[[output.local]]
alias = "speakers"
"""


async def test_end_to_end_synthesizes_and_plays_in_order(tmp_path, monkeypatch):
    say_sub = RecordingSubprocess()
    play_sub = RecordingSubprocess()
    monkeypatch.setattr(tts_say_mod, "create_subprocess", say_sub)
    monkeypatch.setattr(output_local_mod, "create_subprocess", play_sub)

    register("test.sink", FakeSink)
    register_builtins()

    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG)
    config = load_config(config_path)

    rt = Runtime()
    await rt.start(config)
    await asyncio.sleep(1.0)  # message → render → say → afplay
    await rt.stop()

    say_texts = [c[-1] for c in say_sub.calls if c[0] == "say"]
    assert say_texts == ["alice", " says: ", "hello world"]
    say_voices = [c[c.index("-v") + 1] for c in say_sub.calls if c[0] == "say"]
    assert say_voices == ["Samantha", "Samantha", "Daniel"]

    # afplay plays exactly the files say produced, in segment order
    say_files = [c[c.index("-o") + 1] for c in say_sub.calls if c[0] == "say"]
    play_files = [c[1] for c in play_sub.calls]
    assert play_files == say_files
    assert all(c[0] == "afplay" for c in play_sub.calls)
