"""Plugin registry: plugin name -> factory."""

from collections.abc import Callable

from pitwall.core.config import InstanceSpec
from pitwall.core.plugin import Plugin

Factory = Callable[[], Plugin]

_factories: dict[str, Factory] = {}


class UnknownPluginError(Exception):
    """Raised when a config references a plugin name that is not registered."""


def register(name: str, factory: Factory) -> None:
    _factories[name] = factory


def factory_for(plugin: str) -> Factory:
    try:
        return _factories[plugin]
    except KeyError:
        msg = f"unknown plugin: {plugin}"
        raise UnknownPluginError(msg) from None


def build(spec: InstanceSpec) -> Plugin:
    return factory_for(spec.plugin)()
