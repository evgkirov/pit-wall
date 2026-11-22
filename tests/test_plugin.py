import asyncio
import logging

from pitwall.core.channels import Channel
from pitwall.core.plugin import Context


def test_context_carries_wiring():
    ctx = Context(
        instance="reader",
        config={"a": 1},
        logger=logging.getLogger("t"),
        messages=Channel("messages"),
        speak=Channel("speak"),
        audio=Channel("audio"),
        stopping=asyncio.Event(),
    )
    assert ctx.instance == "reader" and ctx.config == {"a": 1} and not ctx.stopping.is_set()


class DummyPlugin:
    """Records lifecycle calls; runs until stopped. Reused by Tasks 5, 6, 10."""

    name = "test.dummy"

    def __init__(self, config: dict | None = None):
        self.calls: list[str] = []
        self.ctx: Context | None = None

    async def start(self, ctx: Context) -> None:
        self.calls.append("start")
        self.ctx = ctx
        await ctx.stopping.wait()

    async def stop(self, ctx: Context) -> None:
        self.calls.append("stop")
