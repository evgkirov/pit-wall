from pathlib import Path

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
