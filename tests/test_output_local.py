import asyncio
import logging
from pathlib import Path

from pitwall.core.channels import Channel
from pitwall.core.events import Audio
from pitwall.core.plugin import Context
from pitwall.plugins import output_local
from pitwall.plugins.output_local import LocalOutputPlugin


class FakeSubprocess:
    def __init__(self, failures: int = 0, delay: float = 0.0):
        self.calls: list[list[str]] = []
        self.events: list[tuple[str, list[str]]] = []
        self.failures = failures
        self.delay = delay

    async def __call__(self, args: list[str]) -> None:
        self.events.append(("start", list(args)))
        if self.failures > 0:
            self.failures -= 1
            raise FileNotFoundError(f"no binary: {args[0]}")
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append(list(args))
        self.events.append(("end", list(args)))


def make_ctx(config: dict) -> Context:
    return Context(
        instance="speakers",
        config=config,
        logger=logging.getLogger("pitwall.speakers"),
        messages=Channel("messages"),
        speak=Channel("speak"),
        audio=Channel("audio"),
        stopping=asyncio.Event(),
    )


async def run_output(config: dict, events: list[Audio], fake, monkeypatch, settle=0.05):
    monkeypatch.setattr(output_local, "create_subprocess", fake)
    ctx = make_ctx(config)
    plugin = LocalOutputPlugin(config)
    task = asyncio.create_task(plugin.start(ctx))
    await asyncio.sleep(0.01)
    for event in events:
        await ctx.audio.publish(event)
    await asyncio.sleep(settle)
    ctx.stopping.set()
    await asyncio.wait_for(task, timeout=2)
    await plugin.stop(ctx)


def audio(path: str, index: int, rid: str = "r1") -> Audio:
    return Audio(path=path, request_id=rid, index=index)


async def test_plays_in_index_order(monkeypatch, tmp_path):
    files = {i: str(tmp_path / f"{i}.aiff") for i in (0, 1)}
    for p in files.values():
        Path(p).write_bytes(b"x")
    fake = FakeSubprocess()
    await run_output({}, [audio(files[1], 1), audio(files[0], 0)], fake, monkeypatch)
    assert [c[1] for c in fake.calls] == [files[0], files[1]]
    assert all(c[0] == "afplay" for c in fake.calls)


async def test_playback_is_sequential(monkeypatch, tmp_path):
    files = {i: str(tmp_path / f"{i}.aiff") for i in (0, 1)}
    for p in files.values():
        Path(p).write_bytes(b"x")
    fake = FakeSubprocess(delay=0.02)
    await run_output({}, [audio(files[0], 0), audio(files[1], 1)], fake, monkeypatch)
    kinds = [e[0] for e in fake.events]
    assert kinds == ["start", "end", "start", "end"]


async def test_files_deleted_after_playback(monkeypatch, tmp_path):
    p0 = tmp_path / "0.aiff"
    p1 = tmp_path / "1.aiff"
    p0.write_bytes(b"x")
    p1.write_bytes(b"x")
    fake = FakeSubprocess()
    await run_output({}, [audio(str(p1), 1), audio(str(p0), 0)], fake, monkeypatch)
    assert not p0.exists() and not p1.exists()


async def test_stall_timeout_flushes_gapped_request(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="pitwall.speakers")
    p0 = tmp_path / "0.aiff"
    p2 = tmp_path / "2.aiff"
    q0 = tmp_path / "r3.aiff"
    for p in (p0, p2, q0):
        p.write_bytes(b"x")
    fake = FakeSubprocess()
    # r1: parts 0 and 2 — part 1 was lost in synthesis; 2 must wait for the flush.
    # r3: a healthy later request that must not be blocked by r1's gap.
    await run_output(
        {"stall_timeout": 0.05},
        [audio(str(p0), 0, rid="r1"), audio(str(p2), 2, rid="r1"), audio(str(q0), 0, rid="r3")],
        fake,
        monkeypatch,
        settle=0.3,
    )
    played = [c[1] for c in fake.calls]
    assert played == [str(p0), str(q0), str(p2)]  # 0 plays, r3 plays, stuck 2 flushes last
    assert "r1" in caplog.text
    assert not p2.exists()


async def test_missing_afplay_logged_not_fatal(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="pitwall.speakers")
    p0 = tmp_path / "0.aiff"
    p1 = tmp_path / "1.aiff"
    for p in (p0, p1):
        p.write_bytes(b"x")
    fake = FakeSubprocess(failures=1)
    await run_output({}, [audio(str(p0), 0), audio(str(p1), 1)], fake, monkeypatch)
    assert len(fake.calls) == 1
    assert "afplay" in caplog.text
    assert not p0.exists() and not p1.exists()  # cleaned up either way
