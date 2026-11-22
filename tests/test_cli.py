import asyncio
from pathlib import Path

import pytest

from pitwall.cli import default_config_path, main


def test_default_config_path_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "pitwall" / "config.toml"


def test_default_config_path_fallback(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert default_config_path() == Path.home() / ".config" / "pitwall" / "config.toml"


def test_missing_config_exits_cleanly(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "nope.toml")]) == 1
    err = capsys.readouterr().err
    assert "nope.toml" in err
    assert "Traceback" not in err


def test_malformed_config_exits_cleanly(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text("[broken")
    assert main(["--config", str(config)]) == 1
    err = capsys.readouterr().err
    assert "config" in err
    assert "Traceback" not in err


def test_unknown_plugin_exits_cleanly(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[[tts.sayy]]\nvoice = "Alex"\n')
    assert main(["--config", str(config)]) == 1
    err = capsys.readouterr().err
    assert "tts.sayy" in err
    assert "Traceback" not in err


def test_bad_plugin_config_exits_cleanly(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(
        "[[handler.tts]]\nfilters = { nope = {} }\n\n[[tts.say]]\n\n[[output.local]]\n"
    )
    assert main(["--config", str(config)]) == 1
    err = capsys.readouterr().err
    assert "nope" in err
    assert "Traceback" not in err


async def test_watch_loop_survives_apply_failure(tmp_path):
    from pitwall import cli

    class BoomRuntime:
        def __init__(self):
            self.applied = 0

        async def apply_config(self, config):
            self.applied += 1
            raise ValueError("boom")

    path = tmp_path / "config.toml"
    path.write_text('[[sink.twitch]]\nchannel = "a"\n')
    runtime = BoomRuntime()
    task = asyncio.create_task(cli._watch_and_apply(path, runtime))
    await asyncio.sleep(0.3)
    path.write_text('[[sink.twitch]]\nchannel = "b"\n')
    await asyncio.sleep(0.5)
    assert not task.done()  # the watch survived the raising apply
    assert runtime.applied >= 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
