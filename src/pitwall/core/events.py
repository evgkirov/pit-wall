"""Core event dataclasses shared across channels and plugins."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    """A chat message consumed from a sink."""

    source: str
    user: str
    text: str
    ts: float
    kind: str = "chat"
    raw: dict | None = None


@dataclass(frozen=True, slots=True)
class Segment:
    """One spoken part of an utterance.

    `voice` is a voice KEY resolved by the synthesizing instance;
    `target` is an instance alias; `index` is the part's position in the
    utterance.
    """

    text: str
    voice: str | None = None
    target: str | None = None
    index: int = 0


@dataclass(frozen=True, slots=True)
class SpeakRequest:
    """An utterance to synthesize: ordered segments under one request id."""

    request_id: str
    segments: tuple[Segment, ...]
    source: str | None = None
    user: str | None = None
    meta: dict | None = None
    target: str | None = None


@dataclass(frozen=True, slots=True)
class Audio:
    """A synthesized audio file plus its ordering tags."""

    path: str
    request_id: str
    index: int
    source: str | None = None
    user: str | None = None
