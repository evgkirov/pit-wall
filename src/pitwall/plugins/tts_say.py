"""tts.say: synthesize segments to AIFF files with the macOS `say` binary.

A synthesizer only — it never plays audio; the output plugin sequences and
plays the files this plugin produces.
"""

import asyncio
import os
import tempfile
from pathlib import Path

from pitwall.core.events import Audio, Segment, SpeakRequest
from pitwall.core.plugin import Context


def resolve_voice(config: dict, key: str | None) -> str | None:
    """Resolve a voice key to a `say` voice name; fall back to the default."""
    if key is not None:
        voices = config.get("voices", {})
        if key in voices:
            return voices[key]
        return config.get("voice")
    return config.get("voice")


def synth_args(config: dict, segment: Segment, out_path: str) -> list[str]:
    args = ["say", "-o", out_path]
    voice = resolve_voice(config, segment.voice)
    if voice:
        args += ["-v", voice]
    rate = config.get("rate")
    if rate is not None:
        args += ["-r", str(rate)]
    args.append(segment.text)
    return args


async def create_subprocess(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(*args)
    if await proc.wait() != 0:
        msg = f"{args[0]} exited with code {proc.returncode}"
        raise RuntimeError(msg)


class SayTtsPlugin:
    name = "tts.say"

    def __init__(self, config: dict | None = None):
        self._config = dict(config or {})

    async def start(self, ctx: Context) -> None:
        queue = ctx.speak.subscribe(ctx.instance)
        voices = self._config.get("voices", {})
        while not ctx.stopping.is_set():
            get_task = asyncio.ensure_future(queue.get())
            stop_task = asyncio.ensure_future(ctx.stopping.wait())
            done, _ = await asyncio.wait({get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                get_task.cancel()
                break
            stop_task.cancel()
            request = get_task.result()
            await self._synthesize(ctx, voices, request)

    async def stop(self, ctx: Context) -> None:
        ctx.speak.unsubscribe(ctx.instance)

    async def _synthesize(self, ctx: Context, voices: dict, request: SpeakRequest) -> None:
        for segment in request.segments:
            if segment.voice is not None and segment.voice not in voices:
                ctx.logger.warning(
                    "unknown voice key %r (segment %d of %s); using default voice",
                    segment.voice,
                    segment.index,
                    request.request_id,
                )
            fd, path = tempfile.mkstemp(suffix=".aiff", prefix=f"pitwall-{request.request_id[:8]}-")
            os.close(fd)
            try:
                await create_subprocess(synth_args(self._config, segment, path))
            except Exception:
                ctx.logger.exception(
                    "synthesis failed for segment %d of %s", segment.index, request.request_id
                )
                Path(path).unlink(missing_ok=True)
                continue
            await ctx.audio.publish(
                Audio(
                    path=path,
                    request_id=request.request_id,
                    index=segment.index,
                    source=request.source,
                    user=request.user,
                )
            )
