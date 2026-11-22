"""The runtime: builds a plugin graph from config and runs it."""

import asyncio
import logging
from dataclasses import dataclass, field

from pitwall.core.channels import Channel, split_by_target
from pitwall.core.config import Config, InstanceSpec
from pitwall.core.events import Audio, Message, SpeakRequest
from pitwall.core.plugin import Context, Plugin
from pitwall.core.registry import Factory, factory_for


@dataclass
class _Entry:
    spec: InstanceSpec
    factory: Factory
    plugin: Plugin
    ctx: Context
    task: asyncio.Task | None = field(default=None)


class Runtime:
    """Owns the channel set and the plugin instance tasks for one graph."""

    def __init__(
        self,
        backoff_start: float = 1.0,
        backoff_cap: float = 30.0,
        stop_timeout: float = 5.0,
    ) -> None:
        self._backoff_start = backoff_start
        self._backoff_cap = backoff_cap
        self._stop_timeout = stop_timeout
        self._entries: list[_Entry] = []
        self._channels: tuple[Channel[Message], Channel[SpeakRequest], Channel[Audio]] | None = None

    @property
    def running(self) -> bool:
        return bool(self._entries)

    async def start(self, config: Config) -> None:
        channels, entries = self._build(config)
        self._launch(channels, entries)

    async def apply_config(self, config: Config) -> bool:
        """Swap to a new graph; keep the old one running if the new one is invalid."""
        try:
            channels, entries = self._build(config)
        except Exception as exc:
            logging.getLogger("pitwall").error("config change rejected: %s", exc)
            return False
        await self.stop()
        self._launch(channels, entries)
        return True

    def _build(
        self, config: Config
    ) -> tuple[
        tuple[Channel[Message], Channel[SpeakRequest], Channel[Audio]],
        list[_Entry],
    ]:
        messages = Channel[Message]("messages")
        speak = Channel[SpeakRequest]("speak", splitter=split_by_target)
        audio = Channel[Audio]("audio")
        channels = (messages, speak, audio)

        entries: list[_Entry] = []
        for spec in config.instances:
            if not spec.enabled:
                continue
            factory = factory_for(spec.plugin)  # raises UnknownPluginError
            plugin = factory(spec.config)
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
        return channels, entries

    def _launch(
        self,
        channels: tuple[Channel[Message], Channel[SpeakRequest], Channel[Audio]],
        entries: list[_Entry],
    ) -> None:
        for entry in entries:
            entry.task = asyncio.create_task(self._supervise(entry), name=entry.spec.name)
        self._channels = channels
        self._entries = entries

    async def stop(self) -> None:
        entries, self._entries = self._entries, []
        for entry in entries:
            entry.ctx.stopping.set()
        if entries:
            tasks = [e.task for e in entries if e.task]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self._stop_timeout,
                )
            except TimeoutError:
                logging.getLogger("pitwall").warning(
                    "plugins did not stop within %.1fs; cancelling stragglers",
                    self._stop_timeout,
                )
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        for entry in entries:
            try:
                await entry.plugin.stop(entry.ctx)
            except Exception:
                logging.getLogger("pitwall").exception("stop failed for %s", entry.spec.name)
        self._channels = None

    async def _supervise(self, entry: _Entry) -> None:
        """Run a plugin, restarting it with backoff whenever it crashes.

        A clean return means the plugin finished its work; only an exception
        restarts it (with a fresh instance from the factory).
        """
        backoff = self._backoff_start
        first_attempt = True
        while not entry.ctx.stopping.is_set():
            plugin = entry.plugin if first_attempt else entry.factory(entry.spec.config)
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
