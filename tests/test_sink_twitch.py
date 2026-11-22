import asyncio
import logging

import pytest

from pitwall.core.channels import Channel
from pitwall.core.plugin import Context
from pitwall.plugins.sink_twitch import TwitchSinkPlugin, parse_privmsg


def test_parse_privmsg_with_display_name_tag():
    line = (
        "@display-name=Alice\\sK;user-login=alice_k :alice_k!alice_k@alice_k.tmi.twitch.tv "
        "PRIVMSG #shroud :nice run"
    )
    assert parse_privmsg(line) == ("Alice K", "nice run")


def test_parse_privmsg_without_tags_falls_back_to_nick():
    line = ":bob!bob@bob.tmi.twitch.tv PRIVMSG #shroud :hello"
    assert parse_privmsg(line) == ("bob", "hello")


def test_parse_privmsg_non_privmsg_returns_none():
    assert parse_privmsg(":tmi.twitch.tv PING :tmi.twitch.tv") is None
    assert parse_privmsg(":tmi.twitch.tv RECONNECT") is None


def test_parse_privmsg_preserves_unicode_and_colons():
    line = ":bob!bob@bob.tmi.twitch.tv PRIVMSG #shroud :😀 hi: there"
    assert parse_privmsg(line)[1] == "😀 hi: there"


class FakeConnection:
    """Replays lines; records sent lines; raises ConnectionError at end."""

    def __init__(self, lines: list[str]):
        self._lines = list(lines)
        self.sent: list[str] = []

    def send(self, line: str) -> None:
        self.sent.append(line)

    async def readline(self) -> str:
        if not self._lines:
            raise ConnectionError("EOF")
        return self._lines.pop(0)

    async def close(self) -> None:
        self._lines.clear()


WELCOME = [":tmi.twitch.tv CAP * ACK :twitch.tv/tags", ":tmi.twitch.tv 001 justinfan1 :welcome"]


def make_ctx(config: dict) -> Context:
    return Context(
        instance="twitch",
        config=config,
        logger=logging.getLogger("pitwall.twitch"),
        messages=Channel("messages"),
        speak=Channel("speak"),
        audio=Channel("audio"),
        stopping=asyncio.Event(),
    )


async def run_sink(config, connection, publish_wait=0.05):
    ctx = make_ctx(config)
    messages_q = ctx.messages.subscribe("reader")
    plugin = TwitchSinkPlugin(config, connection_factory=lambda host, port: _ok(connection))
    task = asyncio.create_task(plugin.start(ctx))
    await asyncio.sleep(publish_wait)
    ctx.stopping.set()
    try:
        await asyncio.wait_for(task, timeout=1)
    except ConnectionError:
        pass  # EOF before stop is acceptable; supervisor would reconnect
    await plugin.stop(ctx)
    return ctx, messages_q, connection


async def _ok(connection):
    return connection


async def test_message_published_to_messages_channel():
    conn = FakeConnection(WELCOME + [":alice!alice@alice.tmi.twitch.tv PRIVMSG #shroud :hello"])
    ctx, q, conn = await run_sink({"channel": "shroud"}, conn)
    event = q.get_nowait()
    assert (event.source, event.user, event.text, event.kind) == (
        "twitch",
        "alice",
        "hello",
        "chat",
    )


async def test_join_uses_hashed_channel_and_anonymous_nick():
    conn = FakeConnection(WELCOME)
    await run_sink({"channel": "shroud"}, conn)
    nick_line = next(line for line in conn.sent if line.startswith("NICK"))
    assert nick_line.split()[1].startswith("justinfan")
    assert any(line.startswith("JOIN #shroud") for line in conn.sent)
    assert any(line == "CAP REQ :twitch.tv/tags" for line in conn.sent)


async def test_leading_hash_stripped_from_config():
    conn = FakeConnection(WELCOME)
    await run_sink({"channel": "#shroud"}, conn)
    assert any(line == "JOIN #shroud" for line in conn.sent)


async def test_ping_answered_with_pong():
    conn = FakeConnection(WELCOME + [":tmi.twitch.tv PING :tmi.twitch.tv"])
    await run_sink({"channel": "shroud"}, conn)
    assert "PONG :tmi.twitch.tv" in conn.sent


async def test_ping_word_in_chat_text_is_not_a_ping():
    conn = FakeConnection(
        WELCOME + [":bob!bob@bob.tmi.twitch.tv PRIVMSG #shroud :can someone PING me pls"]
    )
    ctx, q, conn = await run_sink({"channel": "shroud"}, conn)
    assert q.get_nowait().text == "can someone PING me pls"
    assert not any(line.startswith("PONG") for line in conn.sent)


async def test_channel_required():
    plugin = TwitchSinkPlugin({})
    with pytest.raises(ValueError, match="channel"):
        await plugin.start(make_ctx({}))
