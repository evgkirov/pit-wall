"""The plugin contract and the context a plugin runs with."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from pitwall.core.channels import Channel
from pitwall.core.events import Audio, Message, SpeakRequest


class Plugin(Protocol):
    """A plugin instance.

    `start` runs until the plugin is done — normally when `ctx.stopping` is
    set. `stop` cleans up afterwards, whether `start` returned or aborted.
    """

    name: str

    async def start(self, ctx: Context) -> None: ...

    async def stop(self, ctx: Context) -> None: ...


@dataclass
class Context:
    """Everything a plugin instance needs: identity, config, wiring, stop signal."""

    instance: str
    config: dict
    logger: logging.Logger
    messages: Channel[Message]
    speak: Channel[SpeakRequest]
    audio: Channel[Audio]
    stopping: asyncio.Event
