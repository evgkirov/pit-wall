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
        def __init__(self):
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
