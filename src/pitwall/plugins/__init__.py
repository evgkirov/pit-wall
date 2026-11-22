"""Built-in plugins for PitWall."""

from pitwall.core.registry import register
from pitwall.plugins.handler_tts import TtsHandlerPlugin
from pitwall.plugins.output_local import LocalOutputPlugin
from pitwall.plugins.sink_twitch import TwitchSinkPlugin
from pitwall.plugins.tts_mlx import MlxTtsPlugin
from pitwall.plugins.tts_say import SayTtsPlugin


def register_builtins() -> None:
    register("sink.twitch", TwitchSinkPlugin)
    register("handler.tts", TtsHandlerPlugin)
    register("tts.say", SayTtsPlugin)
    register("tts.mlx", MlxTtsPlugin)
    register("output.local", LocalOutputPlugin)
