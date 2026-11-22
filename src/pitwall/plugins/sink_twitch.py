"""sink.twitch: read-only anonymous Twitch chat over IRC.

Connects as a random `justinfan` nick (no credentials), joins the configured
channel, and publishes every chat message. Twitch's IRC endpoint still accepts
anonymous reads; twitchio (EventSub-only, user-token-only) cannot.
Reconnection on drop is provided by the runtime supervisor restarting the
plugin after a connection error.
"""

import asyncio
import random
import ssl
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from pitwall.core.events import Message
from pitwall.core.plugin import Context

HOST = "irc.chat.twitch.tv"
PORT = 6697


class IrcConnection(Protocol):
    def send(self, line: str) -> None: ...

    async def readline(self) -> str: ...  # raises on EOF

    async def close(self) -> None: ...


class SocketConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    def send(self, line: str) -> None:
        self._writer.write((line + "\r\n").encode())

    async def readline(self) -> str:
        data = await self._reader.readline()
        if not data:
            msg = "connection closed by peer"
            raise ConnectionError(msg)
        return data.decode(errors="replace").rstrip("\r\n")

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except ConnectionError, OSError:
            pass


async def tls_connect(host: str, port: int) -> SocketConnection:
    reader, writer = await asyncio.open_connection(host, port, ssl=ssl.create_default_context())
    return SocketConnection(reader, writer)


def parse_privmsg(line: str) -> tuple[str, str] | None:
    """Extract (display user, text) from a Twitch IRC PRIVMSG line, else None."""
    tags: dict[str, str] = {}
    rest = line
    if rest.startswith("@"):
        tag_part, _, rest = rest.partition(" ")
        for pair in tag_part[1:].split(";"):
            key, _, value = pair.partition("=")
            tags[key] = value.replace("\\s", " ")
    if " PRIVMSG " not in rest:
        return None
    prefix, _, trailing = rest.partition(" ")
    nick = prefix.lstrip(":").split("!")[0]
    _, _, text = trailing.partition(" :")
    user = tags.get("display-name") or nick
    return user, text


def _anonymous_nick() -> str:
    return f"justinfan{random.randint(10_000, 99_999)}"


class TwitchSinkPlugin:
    name = "sink.twitch"

    def __init__(
        self,
        config: dict | None = None,
        connection_factory: Callable[[str, int], Awaitable[IrcConnection]] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._connect = connection_factory or tls_connect

    async def start(self, ctx: Context) -> None:
        channel = str(self._config.get("channel", "")).lstrip("#").strip()
        if not channel:
            msg = "sink.twitch: config key 'channel' is required"
            raise ValueError(msg)

        conn = await self._connect(HOST, PORT)
        nick = _anonymous_nick()
        conn.send("CAP REQ :twitch.tv/tags")
        conn.send(f"NICK {nick}")
        joined = False
        try:
            while not ctx.stopping.is_set():
                read_task = asyncio.ensure_future(conn.readline())
                stop_task = asyncio.ensure_future(ctx.stopping.wait())
                done, _ = await asyncio.wait(
                    {read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if stop_task in done:
                    read_task.cancel()
                    break
                stop_task.cancel()
                line = read_task.result()
                if not joined and " 001 " in line:
                    conn.send(f"JOIN #{channel}")
                    joined = True
                    ctx.logger.info("joined #%s as %s", channel, nick)
                    continue
                words = line.split()
                is_ping = bool(words) and (
                    words[0] == "PING" or (len(words) > 1 and words[1] == "PING")
                )
                if is_ping:
                    conn.send("PONG " + words[-1] if len(words) > 1 else "PONG")
                    continue
                parsed = parse_privmsg(line)
                if parsed is not None:
                    user, text = parsed
                    await ctx.messages.publish(
                        Message(
                            source="twitch",
                            user=user,
                            text=text,
                            ts=time.time(),
                            kind="chat",
                        )
                    )
        finally:
            await conn.close()

    async def stop(self, ctx: Context) -> None:
        pass  # connection closed in start()'s finally
