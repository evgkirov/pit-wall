import asyncio

import pytest
from watchfiles import awatch  # noqa: F401  (ensures dep present)

from pitwall.core.config import Config, InstanceSpec, load_config
from pitwall.core.registry import register
from pitwall.core.runtime import Runtime
from tests.test_plugin import DummyPlugin


def spec(name, plugin="test.dummy"):
    return InstanceSpec(name=name, plugin=plugin, config={})


async def test_valid_change_rebuilds_graph():
    built: list = []

    class Recording(DummyPlugin):
        def __init__(self, config=None):
            super().__init__()
            built.append(self)

    register("test.rebuild", Recording)
    rt = Runtime()
    await rt.start(Config(instances=(spec("a", "test.rebuild"),)))
    await asyncio.sleep(0.01)
    first = built[0]
    assert first.calls == ["start"]

    assert await rt.apply_config(Config(instances=(spec("b", "test.rebuild"),))) is True
    await asyncio.sleep(0.01)
    assert first.calls == ["start", "stop"]  # old graph fully stopped
    assert built[1].calls == ["start"]  # new graph running
    await rt.stop()


async def test_invalid_change_keeps_old_graph():
    built: list = []

    class Recording(DummyPlugin):
        def __init__(self, config=None):
            super().__init__()
            built.append(self)

    register("test.rebuild2", Recording)
    rt = Runtime()
    await rt.start(Config(instances=(spec("a", "test.rebuild2"),)))
    await asyncio.sleep(0.01)

    bad = Config(instances=(spec("a", "test.rebuild2"), spec("x", "nope.plugin")))
    assert await rt.apply_config(bad) is False
    await asyncio.sleep(0.01)
    assert built[0].calls == ["start"]  # still running
    assert not built[0].ctx.stopping.is_set()
    await rt.stop()
    assert built[0].calls == ["start", "stop"]


async def test_watch_skips_malformed(tmp_path):
    from pitwall.core.config import watch_config

    path = tmp_path / "config.toml"
    path.write_text('[[sink.twitch]]\nchannel = "shroud"\n')
    cfg_a = load_config(path)

    collected: list = []

    async def collect():
        async for config in watch_config(path, debounce=0.05):
            collected.append(config)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.3)
    path.write_text("[broken")  # malformed: must be skipped, not crash the watch
    await asyncio.sleep(0.3)
    path.write_text('[[sink.twitch]]\nchannel = "other"\n')
    cfg_b = load_config(path)
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Only valid configs are yielded (FSEvents may also deliver the initial
    # write late); the malformed one is skipped, never raised, and B lands last.
    assert collected
    assert all(config in (cfg_a, cfg_b) for config in collected)
    assert collected[-1] == cfg_b
