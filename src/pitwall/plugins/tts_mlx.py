"""tts.mlx: synthesize segments to WAV files with local MLX-Audio models.

A synthesizer only — it never plays audio; the output plugin sequences and
plays the files this plugin produces. Needs the `mlxaudio` extra
(`uv sync --extra mlxaudio`); any mlx-audio model repo works.
"""

import asyncio
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from pitwall.core.events import Audio, SpeakRequest
from pitwall.core.plugin import Context
from pitwall.plugins.tts_say import resolve_voice

DEFAULT_MODEL = "mlx-community/Kokoro-82M-bf16"


def load_model(repo: str) -> Any:
    """Load an mlx-audio model, with a helpful error when the extra is missing."""
    try:
        from mlx_audio.tts.utils import load_model as mlx_load_model  # type: ignore[import-not-found]
    except ImportError as exc:
        msg = (
            "tts.mlx needs the mlxaudio extra — install with: "
            "uv sync --extra mlxaudio (or: pip install 'pitwall[mlxaudio]')"
        )
        raise RuntimeError(msg) from exc
    return mlx_load_model(repo)


def render_segment(
    model: Any, text: str, voice: str | None, speed: float | None, path: str
) -> None:
    """Generate speech for one segment and write it to `path` as 16-bit mono WAV."""
    kwargs: dict[str, Any] = {}
    if voice is not None:
        kwargs["voice"] = voice
    if speed is not None:
        kwargs["speed"] = speed
    chunks: list[Any] = []
    sample_rate = 0
    for result in model.generate(text, **kwargs):
        if not chunks:
            sample_rate = result.sample_rate
        chunks.append(result.audio)
    import numpy as np  # type: ignore

    audio = np.concatenate([np.asarray(c) for c in chunks])
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


class MlxTtsPlugin:
    name = "tts.mlx"

    def __init__(self, config: dict | None = None):
        self._config = dict(config or {})

    async def start(self, ctx: Context) -> None:
        repo = self._config.get("model", DEFAULT_MODEL)
        model = await asyncio.to_thread(load_model, repo)
        queue = ctx.speak.subscribe(ctx.instance)
        while not ctx.stopping.is_set():
            get_task = asyncio.ensure_future(queue.get())
            stop_task = asyncio.ensure_future(ctx.stopping.wait())
            done, _ = await asyncio.wait({get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                get_task.cancel()
                break
            stop_task.cancel()
            request = get_task.result()
            await self._synthesize(ctx, model, request)

    async def stop(self, ctx: Context) -> None:
        ctx.speak.unsubscribe(ctx.instance)

    async def _synthesize(self, ctx: Context, model: Any, request: SpeakRequest) -> None:
        voices = self._config.get("voices", {})
        speed = self._config.get("speed")
        for segment in request.segments:
            if segment.voice is not None and segment.voice not in voices:
                ctx.logger.warning(
                    "unknown voice key %r (segment %d of %s); using default voice",
                    segment.voice,
                    segment.index,
                    request.request_id,
                )
            voice = resolve_voice(self._config, segment.voice)
            fd, path = tempfile.mkstemp(suffix=".wav", prefix=f"pitwall-{request.request_id[:8]}-")
            os.close(fd)
            try:
                await asyncio.to_thread(render_segment, model, segment.text, voice, speed, path)
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
