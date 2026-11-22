"""The runtime: builds a plugin graph from config and runs it."""

import asyncio
import logging
from dataclasses import dataclass, field

from pitwall.core.channels import Channel, split_by_target
from pitwall.core.config import Config, InstanceSpec
from pitwall.core.events import Audio, Message, SpeakRequest
from pitwall.core.plugin import Context, Plugin
from pitwall.core.registry import Factory, factory_for

_STOP_TIMEOUT = 5.0


@dataclass
class _Entry:
    spec: InstanceSpec
    factory: Factory
    plugin: Plugin
    ctx: Context
    task: asyncio.Task | None = field(default=None)


class Runtime:
    """Owns the channel set and the plugin instance tasks for one graph."""

    def __init__(self, backoff_start: float = 1.0, backoff_cap: float = 30.0) -> None:
        self._backoff_start = backoff_start
        self._backoff_cap = backoff_cap
        self._entries: list[_Entry] = []
        self._channels: tuple[Channel[Message], Channel[SpeakRequest], Channel[Audio]] | None = None

    @property
    def running(self) -> bool:
        return bool(self._entries)

    async def start(self, config: Config) -> None:
        messages = Channel[Message]("messages")
        speak = Channel[SpeakRequest]("speak", splitter=split_by_target)
        audio = Channel[Audio]("audio")

        entries: list[_Entry] = []
        for spec in config.instances:
            if not spec.enabled:
                continue
            factory = factory_for(spec.plugin)  # raises UnknownPluginError
            plugin = factory()
            ctx = Context(
                instance=spec.name,
                config=dict(spec.config),
                logger=logging.getLogger(f"pitwall.{spec.name}"),
                messages=messages,
                speak=speak,
                audio=audio,
                stopping=asyncio.Event(),
            )
            entries.append(_Entry(spec=spec, factory=factory, plugin=plugin, ctx=ctx))

        # Everything built; only now launch tasks.
        for entry in entries:
            entry.task = asyncio.create_task(
                self._run(entry.plugin, entry.ctx), name=entry.spec.name
            )
        self._channels = (messages, speak, audio)
        self._entries = entries

    async def stop(self) -> None:
        entries, self._entries = self._entries, []
        for entry in entries:
            entry.ctx.stopping.set()
        if entries:
            await asyncio.wait_for(
                asyncio.gather(*(e.task for e in entries if e.task), return_exceptions=True),
                timeout=_STOP_TIMEOUT,
            )
        for entry in entries:
            await entry.plugin.stop(entry.ctx)
        self._channels = None

    async def _run(self, plugin: Plugin, ctx: Context) -> None:
        await plugin.start(ctx)
