import pytest

from pitwall.core.config import InstanceSpec
from pitwall.core.registry import UnknownPluginError, build, register
from tests.test_plugin import DummyPlugin


def test_build_unknown_plugin_raises():
    with pytest.raises(UnknownPluginError, match="nope.plugin"):
        build(InstanceSpec(name="x", plugin="nope.plugin", config={}))


def test_registered_factory_builds():
    register("test.dummy", DummyPlugin)
    assert isinstance(build(InstanceSpec(name="x", plugin="test.dummy", config={})), DummyPlugin)
