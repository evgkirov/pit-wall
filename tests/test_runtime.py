import asyncio

import pytest

from pitwall.core.config import Config, InstanceSpec
from pitwall.core.registry import register
from pitwall.core.runtime import Runtime
from tests.test_plugin import DummyPlugin


def spec(name, plugin="test.dummy", enabled=True):
    return InstanceSpec(name=name, plugin=plugin, config={}, enabled=enabled)


def recording_factory(built: list) -> type:
    class RecordingDummy(DummyPlugin):
        def __init__(self, config: dict | None = None):
            super().__init__()
            built.append(self)

    return RecordingDummy


async def test_start_runs_and_stop_stops_plugins():
    built: list = []
    register("test.runtime.dummy", recording_factory(built))
    rt = Runtime()
    await rt.start(
        Config(
            instances=(
                spec("a", plugin="test.runtime.dummy"),
                spec("b", plugin="test.runtime.dummy"),
            )
        )
    )
    await asyncio.sleep(0)  # let tasks enter start()
    assert len(built) == 2
    assert all(p.calls == ["start"] for p in built)
    await rt.stop()
    assert all(p.calls == ["start", "stop"] for p in built)


async def test_disabled_instances_are_not_built():
    built: list = []
    register("test.runtime.disabled", recording_factory(built))
    rt = Runtime()
    await rt.start(Config(instances=(spec("a", plugin="test.runtime.disabled", enabled=False),)))
    assert built == []
    await rt.stop()


async def test_unknown_plugin_aborts_before_any_start():
    built: list = []
    register("test.runtime.known", recording_factory(built))
    rt = Runtime()
    with pytest.raises(Exception, match="nope.plugin"):
        await rt.start(
            Config(
                instances=(spec("a", plugin="test.runtime.known"), spec("b", plugin="nope.plugin"))
            )
        )
    await asyncio.sleep(0)
    assert all(p.calls == [] for p in built)  # built, never started
    await rt.stop()


async def test_crashing_plugin_is_restarted():
    class Flaky(DummyPlugin):
        attempts = 0

        async def start(self, ctx):
            Flaky.attempts += 1
            if Flaky.attempts == 1:
                raise RuntimeError("boom")
            await ctx.stopping.wait()

    register("test.flaky", Flaky)
    rt = Runtime(backoff_start=0.0)
    await rt.start(Config(instances=(InstanceSpec(name="flaky", plugin="test.flaky", config={}),)))
    await asyncio.sleep(0.05)
    assert Flaky.attempts == 2
    await rt.stop()


async def test_crashing_plugin_does_not_kill_neighbor():
    class Flaky(DummyPlugin):
        attempts = 0

        async def start(self, ctx):
            Flaky.attempts += 1
            raise RuntimeError("boom")

    built: list = []
    register("test.flaky2", Flaky)
    register("test.neighbor", recording_factory(built))
    rt = Runtime(backoff_start=0.0)
    await rt.start(
        Config(
            instances=(
                InstanceSpec(name="flaky", plugin="test.flaky2", config={}),
                spec("neighbor", plugin="test.neighbor"),
            )
        )
    )
    await asyncio.sleep(0.05)
    assert Flaky.attempts >= 2  # flaky keeps being restarted
    assert built[0].calls == ["start"]  # neighbor still running, unharmed
    await rt.stop()
