"""handler.tts: turn chat messages into speak requests.

Renders each passing message through an utterance template into ordered
segments with per-placeholder voice keys and routing targets.
"""

import asyncio
import re
import uuid
from collections.abc import Callable

from pitwall.core.events import Message, Segment, SpeakRequest
from pitwall.core.plugin import Context

Filter = Callable[[Message], bool]
FilterFactory = Callable[[dict], Filter]
FILTERS: dict[str, FilterFactory] = {}

DEFAULT_TEMPLATE = "{user} {text}"
_PLACEHOLDERS = ("user", "text")
_PLACEHOLDER_RE = re.compile(r"\{(user|text)\}")
_ANY_BRACE_RE = re.compile(r"\{(\w+)\}")


def _min_length_factory(cfg: dict) -> Filter:
    minimum = cfg.get("min", 2)

    def passes(message: Message) -> bool:
        return len(message.text) >= minimum

    return passes


FILTERS["min_length"] = _min_length_factory


def validate_template(template: str) -> None:
    for match in _ANY_BRACE_RE.finditer(template):
        key = match.group(1)
        if key not in _PLACEHOLDERS:
            msg = f"unknown template placeholder {{{key}}}: allowed {list(_PLACEHOLDERS)}"
            raise ValueError(msg)


def render(
    template: str,
    message: Message,
    voices: dict[str, str] | None = None,
    targets: dict[str, str] | None = None,
    target: str | None = None,
) -> tuple[Segment, ...]:
    """Split a template into segments; literals inherit the preceding placeholder.

    Adjacent segments sharing both voice and target are merged into one, so a
    request only breaks where the voice or routing actually changes.
    """
    validate_template(template)
    voices = voices or {}
    targets = targets or {}
    values = {"user": message.user, "text": message.text}

    segments: list[Segment] = []
    last_voice: str | None = None
    last_target: str | None = None
    position = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        literal = template[position : match.start()]
        key = match.group(1)
        if literal:
            segments.append(
                Segment(literal, voice=last_voice, target=last_target, index=len(segments))
            )
        last_voice = voices.get(key)
        last_target = targets.get(key) or target
        segments.append(
            Segment(values[key], voice=last_voice, target=last_target, index=len(segments))
        )
        position = match.end()
    trailing = template[position:]
    if trailing:
        segments.append(
            Segment(trailing, voice=last_voice, target=last_target, index=len(segments))
        )

    merged: list[Segment] = []
    for segment in segments:
        # Routing falls back to the request-level target, so a leading literal
        # stored as None can share a target with the placeholders after it.
        effective = segment.target or target
        if merged and (segment.voice, effective) == (merged[-1].voice, merged[-1].target):
            merged[-1] = Segment(
                merged[-1].text + segment.text,
                voice=segment.voice,
                target=merged[-1].target,
                index=merged[-1].index,
            )
        else:
            merged.append(
                Segment(segment.text, voice=segment.voice, target=effective, index=len(merged))
            )
    return tuple(merged)


class TtsHandlerPlugin:
    name = "handler.tts"

    def __init__(self, config: dict | None = None):
        cfg = dict(config or {})
        self._template = cfg.pop("template", DEFAULT_TEMPLATE)
        self._voices = cfg.pop("voices", {}) or {}
        self._targets = cfg.pop("targets", {}) or {}
        self._target = cfg.pop("target", None)
        filters_cfg = cfg.pop("filters", {}) or {}

        # Fail at construction (graph build), before any message flows.
        validate_template(self._template)
        self._chain: list[Filter] = []
        for name, filter_cfg in filters_cfg.items():
            factory = FILTERS.get(name)
            if factory is None:
                msg = f"unknown filter {name!r}: known {sorted(FILTERS)}"
                raise ValueError(msg)
            self._chain.append(factory(filter_cfg))

    async def start(self, ctx: Context) -> None:
        queue = ctx.messages.subscribe(ctx.instance)
        while not ctx.stopping.is_set():
            get_task = asyncio.ensure_future(queue.get())
            stop_task = asyncio.ensure_future(ctx.stopping.wait())
            done, _ = await asyncio.wait({get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                get_task.cancel()
                break
            stop_task.cancel()
            message = get_task.result()
            await self._handle(ctx, message)

    async def stop(self, ctx: Context) -> None:
        ctx.messages.unsubscribe(ctx.instance)

    async def _handle(self, ctx: Context, message: Message) -> None:
        if message.kind != "chat":
            return
        if not all(passes(message) for passes in self._chain):
            return
        segments = render(self._template, message, self._voices, self._targets, self._target)
        await ctx.speak.publish(
            SpeakRequest(
                request_id=uuid.uuid4().hex,
                segments=segments,
                source=message.source,
                user=message.user,
                target=self._target,
            )
        )
