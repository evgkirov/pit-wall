from pathlib import Path

import pytest

from pitwall.core.config import ConfigError, load_config
from pitwall.core.registry import factory_for
from pitwall.plugins import register_builtins


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_alias_defaults_to_plugin_suffix(tmp_path):
    cfg = load_config(write(tmp_path, '[[sink.twitch]]\nchannel = "shroud"\n'))
    assert cfg.instances[0].name == "twitch"
    assert cfg.instances[0].config == {"channel": "shroud"}


def test_explicit_alias_and_multiple_instances(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            """
[[tts.say]]
alias = "daniel"
voice = "Daniel"

[[tts.say]]
alias = "backup"
enabled = false
""",
        )
    )
    assert [s.name for s in cfg.instances] == ["daniel", "backup"]
    assert cfg.instances[1].enabled is False
    assert cfg.instances[1].config == {}


def test_derived_alias_collision_raises(tmp_path):
    with pytest.raises(ConfigError, match="say"):
        load_config(write(tmp_path, '[[tts.say]]\nvoice = "A"\n\n[[tts.say]]\nvoice = "B"\n'))


def test_target_must_name_enabled_alias(tmp_path):
    with pytest.raises(ConfigError, match="target"):
        load_config(
            write(tmp_path, '[[tts.say]]\nalias = "a"\n\n[[handler.tts]]\ntarget = "ghost"\n')
        )


def test_target_must_not_name_disabled_alias(tmp_path):
    with pytest.raises(ConfigError, match="target"):
        load_config(
            write(
                tmp_path,
                '[[tts.say]]\nalias = "a"\nenabled = false\n\n[[handler.tts]]\ntarget = "a"\n',
            )
        )


def test_targets_values_must_name_enabled_alias(tmp_path):
    with pytest.raises(ConfigError, match="ghost"):
        load_config(
            write(
                tmp_path,
                '[[tts.say]]\nalias = "a"\n\n[[handler.tts]]\ntargets = { text = "ghost" }\n',
            )
        )


def test_not_an_array_of_tables_raises(tmp_path):
    with pytest.raises(ConfigError, match="sink.twitch"):
        load_config(write(tmp_path, '[sink.twitch]\nchannel = "x"\n'))


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[broken"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="config"):
        load_config(tmp_path / "nope.toml")


def test_example_config_loads_and_names_known_plugins():
    register_builtins()
    example = Path(__file__).parents[1] / "config.toml.example"
    config = load_config(example)
    assert config.instances
    for spec in config.instances:
        factory_for(spec.plugin)
