"""Console entrypoint: run the PitWall service until stopped."""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from pitwall.core.config import ConfigError, load_config, watch_config
from pitwall.core.registry import UnknownPluginError
from pitwall.core.runtime import Runtime
from pitwall.plugins import register_builtins


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "pitwall" / "config.toml"


async def _watch_and_apply(config_path: Path, runtime: Runtime) -> None:
    """Apply config changes forever; a failed rebuild must not end the watch."""
    async for new_config in watch_config(config_path):
        try:
            await runtime.apply_config(new_config)
        except Exception:
            logging.getLogger("pitwall").exception("config rebuild failed")


async def serve(config_path: Path) -> int:
    config = load_config(config_path)
    register_builtins()

    runtime = Runtime()
    await runtime.start(config)
    logging.getLogger("pitwall").info("started with %d instance(s)", len(config.instances))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    watch_task = asyncio.create_task(_watch_and_apply(config_path, runtime))
    try:
        await stop.wait()
    finally:
        watch_task.cancel()
        await runtime.stop()
        logging.getLogger("pitwall").info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pitwall", description="PitWall — read-only Twitch chat reader"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help=f"config path (default: {default_config_path()})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        return asyncio.run(serve(args.config or default_config_path()))
    except (ConfigError, UnknownPluginError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
