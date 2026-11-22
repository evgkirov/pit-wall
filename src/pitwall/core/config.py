"""Config loading and validation: plugin-keyed arrays of instance tables."""

import logging
import tomllib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from watchfiles import awatch


class ConfigError(Exception):
    """User-facing configuration error; names the offending table/key."""


@dataclass(frozen=True)
class InstanceSpec:
    """One plugin instance from config; `name` is the resolved alias."""

    name: str
    plugin: str
    config: dict
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    instances: tuple[InstanceSpec, ...]


def load_config(path: Path) -> Config:
    try:
        data = tomllib.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        msg = f"config not found: {path}"
        raise ConfigError(msg) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"config is unreadable: {path}: {exc}"
        raise ConfigError(msg) from exc

    plugins: list[tuple[str, list]] = []
    _walk_plugins((), data, plugins)

    instances: list[InstanceSpec] = []
    for plugin, tables in plugins:
        for table in tables:
            if not isinstance(table, dict):
                msg = f"[{plugin}]: each [[{plugin}]] entry must be a table"
                raise ConfigError(msg)
            instances.append(_spec(plugin, table))

    _validate_aliases(instances)
    _validate_targets(instances)
    return Config(instances=tuple(instances))


def _walk_plugins(path: tuple[str, ...], node: object, out: list[tuple[str, list]]) -> None:
    """Flatten plugin-keyed arrays: [[a.b]] parses as {a: {b: [table]}}."""
    if isinstance(node, list):
        out.append((".".join(path), node))
    elif isinstance(node, dict):
        for key, value in node.items():
            _walk_plugins((*path, key), value, out)
    else:
        dotted = ".".join(path)
        msg = f"[{dotted}]: expected an array of instance tables ([[{dotted}]])"
        raise ConfigError(msg)


def _spec(plugin: str, table: dict) -> InstanceSpec:
    config = dict(table)
    alias = config.pop("alias", None)
    if alias is None:
        alias = plugin.split(".")[-1]
    if not isinstance(alias, str) or not alias:
        msg = f"[{plugin}]: alias must be a non-empty string"
        raise ConfigError(msg)
    enabled = config.pop("enabled", True)
    if not isinstance(enabled, bool):
        msg = f"[{plugin}] alias {alias!r}: enabled must be a boolean"
        raise ConfigError(msg)
    return InstanceSpec(name=alias, plugin=plugin, config=config, enabled=enabled)


def _validate_aliases(instances: list[InstanceSpec]) -> None:
    seen: dict[str, str] = {}
    for spec in instances:
        if (previous := seen.get(spec.name)) is not None:
            msg = f"duplicate alias {spec.name!r}: [{previous}] and [{spec.plugin}]"
            raise ConfigError(msg)
        seen[spec.name] = spec.plugin


def _validate_targets(instances: list[InstanceSpec]) -> None:
    enabled = {spec.name for spec in instances if spec.enabled}
    for spec in instances:
        target = spec.config.get("target")
        if target is None:
            continue
        if target not in enabled:
            msg = (
                f"[{spec.plugin}] alias {spec.name!r}: target {target!r} "
                "must name an enabled instance"
            )
            raise ConfigError(msg)


async def watch_config(
    path: Path, *, debounce: float = 1.6, step: float = 0.05
) -> AsyncIterator[Config]:
    """Yield a new Config on every valid change of the config file.

    Malformed changes are logged and skipped; the watch never crashes.
    """
    path = Path(path).resolve()
    logger = logging.getLogger("pitwall.watch")
    async for changes in awatch(path.parent, debounce=int(debounce * 1000), step=int(step * 1000)):
        for _, changed in changes:
            if Path(changed).resolve() != path:
                continue
            try:
                config = load_config(path)
                if not config.instances:
                    # Editors truncate-then-write; an empty file mid-save must not
                    # tear down the running graph.
                    msg = "config has no instances"
                    raise ConfigError(msg)
                yield config
            except ConfigError as exc:
                logger.error("config change rejected: %s", exc)
