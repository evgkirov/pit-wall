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
            entry.task = asyncio.create_task(self._supervise(entry), name=entry.spec.name)
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

    async def _supervise(self, entry: _Entry) -> None:
        """Run a plugin, restarting it with backoff whenever it crashes.

        A clean return means the plugin finished its work; only an exception
        restarts it (with a fresh instance from the factory).
        """
        backoff = self._backoff_start
        first_attempt = True
        while not entry.ctx.stopping.is_set():
            plugin = entry.plugin if first_attempt else entry.factory()
            first_attempt = False
            entry.plugin = plugin
            try:
                await plugin.start(entry.ctx)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                entry.ctx.logger.exception(
                    "plugin %s crashed; restarting in %.1fs", entry.spec.name, backoff
                )
                try:
                    await asyncio.wait_for(entry.ctx.stopping.wait(), timeout=backoff)
                    return  # stopping set during backoff
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, self._backoff_cap)
