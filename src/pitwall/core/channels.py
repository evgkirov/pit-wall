"""Typed channels: named-instance delivery with optional event splitting."""

import asyncio
import logging
from collections.abc import Callable

from pitwall.core.events import SpeakRequest

type Splitter[T] = Callable[[T], list[tuple[str | None, T]]]


def split_by_target(request: SpeakRequest) -> list[tuple[str | None, SpeakRequest]]:
    """Group a request's segments by effective target (segment, then request).

    Each distinct target gets one sub-request holding its segments with their
    original indices intact. A request with no effective targets anywhere is
    returned whole, broadcast.
    """
    groups: dict[str | None, list] = {}
    order: list[str | None] = []
    for segment in request.segments:
        target = segment.target or request.target
        if target not in groups:
            groups[target] = []
            order.append(target)
        groups[target].append(segment)
    if not groups:
        return [(None, request)]
    result: list[tuple[str | None, SpeakRequest]] = []
    for target in order:
        result.append(
            (
                target,
                SpeakRequest(
                    request_id=request.request_id,
                    segments=tuple(groups[target]),
                    source=request.source,
                    user=request.user,
                    meta=request.meta,
                    target=target,
                ),
            )
        )
    return result


class Channel[T]:
    """A queue-backed channel delivering events to named subscriber instances.

    Without a splitter, an event goes to the instance named by its `target`
    attribute (when present and set), or to every subscriber. With a splitter,
    the event is split into (target, sub-event) pairs first and each pair is
    delivered by the same rule.
    """

    def __init__(self, name: str, splitter: Splitter[T] | None = None) -> None:
        self.name = name
        self._splitter = splitter
        self._subscribers: dict[str, asyncio.Queue[T]] = {}

    def subscribe(self, instance: str) -> asyncio.Queue[T]:
        queue: asyncio.Queue[T] = asyncio.Queue()
        self._subscribers[instance] = queue
        return queue

    def unsubscribe(self, instance: str) -> None:
        self._subscribers.pop(instance, None)

    def _deliver(self, target: str | None, event: T) -> None:
        if target is None:
            for subscriber_queue in self._subscribers.values():
                subscriber_queue.put_nowait(event)
        elif (target_queue := self._subscribers.get(target)) is not None:
            target_queue.put_nowait(event)
        else:
            logging.getLogger("pitwall.channels").warning(
                "channel %s: no subscriber named %r; event dropped", self.name, target
            )

    async def publish(self, event: T) -> None:
        if self._splitter is not None:
            for target, sub in self._splitter(event):
                self._deliver(target, sub)
        else:
            self._deliver(getattr(event, "target", None), event)
