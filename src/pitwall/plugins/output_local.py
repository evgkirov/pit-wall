"""output.local: sequence and play synthesized audio files via `afplay`."""

import asyncio
from pathlib import Path

from pitwall.core.events import Audio
from pitwall.core.plugin import Context


async def create_subprocess(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(*args)
    if await proc.wait() != 0:
        msg = f"{args[0]} exited with code {proc.returncode}"
        raise RuntimeError(msg)


class LocalOutputPlugin:
    name = "output.local"

    def __init__(self, config: dict | None = None):
        cfg = dict(config or {})
        self._stall_timeout = float(cfg.get("stall_timeout", 5.0))

    async def start(self, ctx: Context) -> None:
        queue = ctx.audio.subscribe(ctx.instance)
        buffer: dict[str, dict[int, str]] = {}
        next_index: dict[str, int] = {}
        while True:
            get_task = asyncio.ensure_future(queue.get())
            stop_task = asyncio.ensure_future(ctx.stopping.wait())
            done, _ = await asyncio.wait(
                {get_task, stop_task},
                timeout=self._stall_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:  # stall: nothing arrived; flush anything stuck on a gap
                get_task.cancel()
                stop_task.cancel()
                await self._flush_stalled(ctx, buffer, next_index)
                continue
            if stop_task in done:
                get_task.cancel()
                break
            stop_task.cancel()
            event = get_task.result()
            rid = self._buffer(buffer, next_index, event)
            await self._drain(ctx, buffer, next_index, rid)
        for rid in list(buffer):
            for path in buffer.pop(rid).values():
                Path(path).unlink(missing_ok=True)

    async def stop(self, ctx: Context) -> None:
        ctx.audio.unsubscribe(ctx.instance)

    def _buffer(self, buffer: dict, next_index: dict, event: Audio) -> str:
        buffer.setdefault(event.request_id, {})[event.index] = event.path
        next_index.setdefault(event.request_id, 0)
        return event.request_id

    async def _drain(self, ctx: Context, buffer: dict, next_index: dict, rid: str) -> None:
        while rid in buffer and next_index[rid] in buffer[rid]:
            path = buffer[rid].pop(next_index[rid])
            await self._play(ctx, path)
            next_index[rid] += 1
            if not buffer[rid]:
                del buffer[rid]  # keep next_index[rid]: more parts may still come

    async def _flush_stalled(self, ctx: Context, buffer: dict, next_index: dict) -> None:
        for rid in list(buffer):
            ctx.logger.warning(
                "flushing stalled request %s: playing %d of %d buffered parts out of "
                "order; a synthesized part was lost",
                rid,
                len(buffer[rid]),
                max(buffer[rid]) + 1,
            )
            parts = buffer.pop(rid)
            next_index.pop(rid, None)
            for index in sorted(parts):
                await self._play(ctx, parts[index])
        # Requests whose buffer emptied cleanly are complete; reap their state.
        for rid in [r for r in next_index if r not in buffer]:
            del next_index[rid]

    async def _play(self, ctx: Context, path: str) -> None:
        try:
            await create_subprocess(["afplay", path])
        except Exception:
            ctx.logger.exception("afplay failed for %s", path)
        finally:
            Path(path).unlink(missing_ok=True)
