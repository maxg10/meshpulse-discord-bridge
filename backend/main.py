"""Bidirectional text bridge between a Meshtastic mesh and a Discord channel.

Runs entirely on the public plugin API (``mapper.plugin_api.MeshPlugin``):

    RX: on_message() hook  -> queue -> Discord channel
    TX: discord.on_message -> queue -> await self.send_mesh_message(...)

Threading model
---------------
MeshPulse delivers hooks from the radio reader thread (pubsub
``meshtastic.receive``), and ``PluginManager.dispatch_hook_sync()`` wraps them
in ``asyncio.run()`` — a throwaway event loop that dies when the hook returns.
A long-lived Discord gateway connection cannot survive there, so this plugin
owns a dedicated thread with a private loop and accepts inbound data only via
``loop.call_soon_threadsafe()``.

Consequences worth knowing before editing this file:

* ``send_mesh_message()`` internally does ``get_running_loop()`` +
  ``run_in_executor()``, so it is safe to await from any loop.
* ``broadcast_ws()`` delegates to ``websockets.broadcast()``, which never
  awaits, so it is safe to call off the WebSocket server's loop.
* ``get_database()`` returns a *new* connection on every call, and sqlite
  connections are thread-bound (no ``check_same_thread=False``). We open one
  connection inside the bridge thread and reuse it there.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from mapper.plugin_api import MeshPlugin

try:
    import discord
except ImportError as exc:  # dependency is installed by the mapper on enable
    discord = None
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
WHITESPACE_RE = re.compile(r"\s+")

RECONNECT_BACKOFF: tuple[int, ...] = (5, 15, 30, 60, 120)
THREAD_JOIN_TIMEOUT = 15.0
STARTUP_TIMEOUT = 5.0

STATUS_LABELS = {
    "online": "🟢 online",
    "offline": "🔴 offline",
    "reconnecting": "🟡 reconnecting",
    "starting": "🟡 starting",
    "unconfigured": "⚙️ not configured",
    "bad_token": "🔴 invalid token",
    "no_intent": "🔴 message content intent missing",
    "bad_channel": "🔴 channel unavailable",
    "disabled": "⚫ disabled",
}

# Pairing codes travel over the air, where every byte costs time and every
# character costs a human squinting at a small screen. The alphabet drops the
# glyph pairs people confuse (0/O, 1/I/L) so a code read aloud or retyped from
# a radio display survives the trip.
PAIR_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
PAIR_CODE_RE = re.compile(r"\bPAIR-([" + PAIR_ALPHABET + r"]{4})\b", re.IGNORECASE)


def make_pair_code() -> str:
    return "PAIR-" + "".join(secrets.choice(PAIR_ALPHABET) for _ in range(4))


def fingerprint(text: str) -> str:
    """Content hash used for echo suppression, insensitive to case and spacing."""
    normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def split_utf8(text: str, max_bytes: int) -> list[str]:
    """Split on word boundaries into chunks of at most ``max_bytes`` encoded bytes.

    The limit has to be measured in bytes, not characters: TEXT_MESSAGE_APP caps
    the payload at roughly 200 bytes and non-ASCII characters cost two or more,
    so a character-based split silently truncates mid-codepoint on the firmware.
    """
    text = text.strip()
    if not text:
        return []
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        # A single word longer than the budget has to be hard-cut.
        while len(word.encode("utf-8")) > max_bytes:
            cut = word
            while len(cut.encode("utf-8")) > max_bytes:
                cut = cut[:-1]
            chunks.append(cut)
            word = word[len(cut):]
        current = word
    if current:
        chunks.append(current)
    return chunks


@dataclass(slots=True)
class Outbound:
    text: str
    to_id: str | None = None
    author: str = ""


@dataclass
class Stats:
    started_at: float = field(default_factory=time.time)
    mesh_to_discord: int = 0
    discord_to_mesh: int = 0
    dropped_echo: int = 0
    dropped_filter: int = 0
    errors: int = 0


class DiscordBridge(MeshPlugin):
    """Mesh <-> Discord text bridge.

    ``MeshPlugin`` declares no ``__init__``: PluginManager instantiates the class
    with no arguments and injects ``plugin_id``, ``plugin_dir``, ``config``,
    ``_mapper`` and ``_manager`` afterwards. All state is therefore set up in
    ``on_enable()``.
    """

    # --- lifecycle ---------------------------------------------------------

    def on_enable(self) -> None:
        if discord is None:
            self.log(f"discord.py is unavailable ({_IMPORT_ERROR}); check that "
                     f"requirements.txt was installed.")
            return

        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._main_task: asyncio.Task | None = None
        self._ready = threading.Event()

        self._client: Any = None
        self._channel: Any = None
        self._db: sqlite3.Connection | None = None
        self._rx_queue: asyncio.Queue | None = None
        self._tx_queue: asyncio.Queue | None = None

        self._echo: dict[str, float] = {}
        self._echo_lock = threading.Lock()  # shared by the hook and bridge threads
        self._local_node_id: str | None = None
        self._status = "starting"
        self._stats = Stats()

        # Per-node conversation threads. Both maps are read and written only on
        # the bridge thread (every Discord call lives there), so no lock is
        # needed - unlike _echo, which the radio hook also touches.
        self._threads: dict[str, int] = {}       # node id  -> discord thread id
        self._thread_nodes: dict[int, str] = {}  # thread id -> node id

        # Proven Discord account <-> mesh node bindings, mirrored from SQLite so
        # the hot path never touches the database.
        self._pair_by_discord: dict[int, str] = {}
        self._pair_by_node: dict[str, int] = {}

        # Messages composed in the MeshPulse web chat, which reach no hook and
        # have to be watched for instead. Touched only on the bridge thread.
        self._web_seen: set[str] = set()
        self._web_primed = False

        self.register_ws_channel("status")

        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"discord-bridge[{self.plugin_id}]",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=STARTUP_TIMEOUT)
        self.log("Bridge thread started.")

    def on_disable(self) -> None:
        self._stopping = True

        loop = getattr(self, "_loop", None)
        task = getattr(self, "_main_task", None)
        if loop is not None and not loop.is_closed() and task is not None:
            loop.call_soon_threadsafe(task.cancel)

        thread = getattr(self, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=THREAD_JOIN_TIMEOUT)
            if thread.is_alive():
                self.log("Bridge thread did not terminate within the timeout.")

        self._thread = None
        self._loop = None
        self._main_task = None
        self._client = None
        self._channel = None
        self._status = "disabled"
        self.log("Plugin disabled.")

    def on_config_update(self, new_config: dict) -> None:
        previous_token = (self.config.get("discord_token") or "").strip()
        previous_channel = self._as_int(self.config.get("discord_channel_id"))

        # Overriding this hook bypasses the base implementation, which is the
        # only thing that swaps self.config. Do it explicitly.
        self.config = new_config

        token = (new_config.get("discord_token") or "").strip()
        channel_id = self._as_int(new_config.get("discord_channel_id"))

        # Everything else is read per-use, so only credentials force a restart.
        if token != previous_token or channel_id != previous_channel:
            self.log("Credentials changed; restarting the Discord client.")
            self.on_disable()
            self.on_enable()
        else:
            self.log("Configuration updated in place.")

    # --- bridge thread -----------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            task = loop.create_task(self._main())
            self._main_task = task
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.log(f"Bridge thread terminated: {type(exc).__name__}: {exc}")
        finally:
            self._drain(loop)
            loop.close()
            self._loop = None
            self._ready.clear()

    @staticmethod
    def _drain(loop: asyncio.AbstractEventLoop) -> None:
        """Cancel and await stragglers so the loop closes without warnings."""
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass

    async def _main(self) -> None:
        self._rx_queue = asyncio.Queue(maxsize=500)
        self._tx_queue = asyncio.Queue(maxsize=200)
        self._open_db()
        self._ready.set()

        workers = [
            asyncio.create_task(self._rx_worker()),
            asyncio.create_task(self._tx_worker()),
            asyncio.create_task(self._web_chat_worker()),
        ]
        try:
            await self._supervise()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            client = self._client
            if client is not None and not client.is_closed():
                try:
                    await client.close()
                except Exception:
                    pass
            self._close_db()

    async def _supervise(self) -> None:
        """Keep the gateway connection up, backing off on transient failures."""
        attempt = 0
        while not self._stopping:
            token = (self.config.get("discord_token") or "").strip()
            channel_id = self._as_int(self.config.get("discord_channel_id"))

            if not token or not channel_id:
                await self._fail("unconfigured",
                                 "Token or channel ID missing; set them in "
                                 "Config -> Plugins -> Settings.")
                return

            try:
                await self._run_client(token)
                if self._stopping:
                    return
                attempt = 0
            except asyncio.CancelledError:
                raise
            except discord.LoginFailure:
                await self._fail("bad_token", "Discord rejected the token.")
                return
            except discord.PrivilegedIntentsRequired:
                await self._fail("no_intent",
                                 "Discord refused the login: a privileged intent is "
                                 "disabled. Enable MESSAGE CONTENT INTENT (and SERVER "
                                 "MEMBERS INTENT if greet_new_members is on) under "
                                 "Bot -> Privileged Gateway Intents in the Developer "
                                 "Portal, then save.")
                return
            except Exception as exc:
                self._stats.errors += 1
                self.log(f"Gateway connection lost: {type(exc).__name__}: {exc}")

            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self._status = "reconnecting"
            await self._push_status()
            self.log(f"Retrying in {delay}s.")
            await asyncio.sleep(delay)

    async def _fail(self, status: str, message: str) -> None:
        """Terminal failure: no amount of retrying fixes it without user action."""
        self._status = status
        self.log(message)
        await self._push_status()

    async def _run_client(self, token: str) -> None:
        # The members intent is privileged: if the portal toggle is off, Discord
        # refuses the login outright and the whole bridge is dead, including the
        # parts that never needed it. Losing the join greeting is a far smaller
        # failure than losing the bridge, so we drop the intent and carry on.
        want_members = bool(self.config.get("greet_new_members", True))
        try:
            await self._connect(token, want_members)
        except Exception as exc:
            if want_members and self._is_intent_error(exc):
                self.log(
                    "Discord refused the login because SERVER MEMBERS INTENT is "
                    "off in the developer portal. Reconnecting without it - the "
                    "bridge works, but newcomers will not be greeted "
                    "automatically and must run the pair command themselves. "
                    "Enable the toggle, or set greet_new_members to false to "
                    "silence this."
                )
                await self._connect(token, False)
            else:
                raise

    @staticmethod
    def _is_intent_error(exc: Exception) -> bool:
        required = getattr(discord, "PrivilegedIntentsRequired", None)
        if required is not None and isinstance(exc, required):
            return True
        return "privileged" in str(exc).lower() and "intent" in str(exc).lower()

    async def _connect(self, token: str, with_members: bool) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # requires the portal toggle
        intents.guilds = True
        intents.messages = True
        intents.members = with_members

        client = discord.Client(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        @client.event
        async def on_ready() -> None:
            await self._on_ready(client)

        @client.event
        async def on_message(message: Any) -> None:
            await self._on_discord_message(client, message)

        @client.event
        async def on_member_join(member: Any) -> None:
            if self.config.get("greet_new_members", True):
                await self._greet(member)

        self._client = client
        try:
            await client.start(token)
        finally:
            self._status = "offline"
            self._channel = None
            if not client.is_closed():
                await client.close()

    async def _on_ready(self, client: Any) -> None:
        channel_id = self._as_int(self.config.get("discord_channel_id"))
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except Exception as exc:
                await self._fail("bad_channel",
                                 f"Cannot resolve channel {channel_id}: {exc}. "
                                 f"Most often this is a category or server ID "
                                 f"rather than a text channel, or the bot has not "
                                 f"been invited to that server, or it cannot see "
                                 f"the channel. Right-click the text channel "
                                 f"itself and copy its ID.")
                return

        self._channel = channel
        self._status = "online"
        self.log(f"Connected as {client.user}; bridging #{getattr(channel, 'name', channel_id)}")
        await self._push_status()

        try:
            await client.change_presence(
                activity=discord.Activity(type=discord.ActivityType.listening, name="the mesh")
            )
        except Exception:
            pass

    # --- mesh -> discord ---------------------------------------------------
    # Hooks below execute on the radio reader thread inside a throwaway loop.
    # Never create tasks or await anything long-lived here; _submit_rx() is the
    # only sanctioned path into the bridge.

    async def on_connect(self, connection_info: dict) -> None:
        self._local_node_id = connection_info.get("local_node_id")
        self.log(f"Radio connected; local node {self._local_node_id}")

    async def on_disconnect(self, reason: dict) -> None:
        self.log(f"Radio disconnected: {reason}")

    async def on_message(self, message: dict) -> None:
        if not self.config.get("mesh_to_discord", True):
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        from_id = message.get("from_id")

        # Packets originating from our own node are our own transmissions.
        if from_id and self._local_node_id and str(from_id) == str(self._local_node_id):
            self._stats.dropped_echo += 1
            return

        if message.get("is_dm") and not self.config.get("forward_dms", True):
            self._stats.dropped_filter += 1
            return

        wanted = str(self.config.get("mesh_channel_filter", "all")).strip().lower()
        if wanted not in ("", "all", "*") and str(message.get("channel_index", 0)) != wanted:
            self._stats.dropped_filter += 1
            return

        if self._echo_hit(fingerprint(text)):
            self._stats.dropped_echo += 1
            return

        self._submit_rx(message)

    def _submit_rx(self, message: dict) -> None:
        """Cross-thread handoff from the radio thread into the bridge loop."""
        loop = self._loop
        if loop is None or loop.is_closed() or not self._ready.is_set():
            return
        try:
            loop.call_soon_threadsafe(self._enqueue_rx, message)
        except RuntimeError:  # loop shut down between the check and the call
            pass

    def _enqueue_rx(self, message: dict) -> None:
        try:
            self._rx_queue.put_nowait(message)
        except asyncio.QueueFull:
            self.log("RX queue full; dropping message.")

    async def _rx_worker(self) -> None:
        while True:
            try:
                message = await self._rx_queue.get()
                # A pairing code is credentials, not conversation: consume it
                # here so it never lands in a channel for others to reuse.
                if await self._try_pair(message):
                    continue
                await self._publish_to_discord(message)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._stats.errors += 1
                self.log(f"Failed to publish to Discord: {exc}")

    # --- messages composed in the MeshPulse web chat ------------------------
    # MeshPulse transmits those itself and never notifies plugins, so there is
    # no hook to subscribe to: `on_message` fires only for packets arriving
    # from the radio, and `on_ws_message` only for a plugin's own WS channels.
    # What the send path does leave behind is an entry in `mapper.messages`,
    # shaped exactly like a received message. Watching that list is the only
    # way to see those messages, and it is safe to watch: `send_mesh_message`,
    # which is how this bridge transmits, does not write there — so the
    # bridge's own Discord-to-mesh traffic can never come back through here.

    async def _web_chat_worker(self) -> None:
        interval = max(1.0, float(self._as_int(
            self.config.get("web_chat_poll_seconds", 2)) or 2))
        # Everything already in the list at startup is history, not news.
        # Without this the first poll would replay up to 50 past messages
        # into Discord on every restart.
        self._web_seen = self._web_fingerprints()
        self._web_primed = True

        while True:
            try:
                await asyncio.sleep(interval)
                if not self.config.get("relay_web_chat", True):
                    continue
                await self._drain_web_chat()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._stats.errors += 1
                self.log(f"Web chat watcher failed: {exc}")

    def _local_messages(self) -> list[dict]:
        """Snapshot of locally-composed messages, oldest first.

        The list is mutated from other threads, so each channel is copied
        before being read. MeshPulse caps each channel at 50 entries and
        inserts newest-first.
        """
        mapper = getattr(self, "_mapper", None)
        store = getattr(mapper, "messages", None)
        if not isinstance(store, dict):
            return []

        local = str(self._local_node_id or "")
        found: list[dict] = []
        for entries in list(store.values()):
            for item in list(entries):
                if not isinstance(item, dict):
                    continue
                if local and str(item.get("from_id") or "") == local:
                    found.append(item)
        found.reverse()
        return found

    @staticmethod
    def _web_key(message: dict) -> str:
        return "|".join(str(message.get(field, "")) for field in
                        ("timestamp", "channel_index", "to_id", "text"))

    def _web_fingerprints(self) -> set[str]:
        return {self._web_key(m) for m in self._local_messages()}

    async def _drain_web_chat(self) -> None:
        if not self._web_primed:
            return

        current = self._local_messages()
        fresh = [m for m in current if self._web_key(m) not in self._web_seen]
        if not fresh:
            return

        # Rebuild rather than accumulate: entries MeshPulse has evicted past
        # its 50-item cap can never reappear, so remembering them forever
        # would grow without bound.
        self._web_seen = {self._web_key(m) for m in current}

        label = str(self.config.get("web_chat_label", "MeshPulse") or "MeshPulse")
        for message in fresh:
            await self._publish_web_message(message, label)

    async def _publish_web_message(self, message: dict, label: str) -> None:
        """Mirror one locally-composed message into Discord.

        Deliberately bypasses the transmit queue: MeshPulse already put this
        on the air. Relaying it again would duplicate it for every radio in
        range.
        """
        channel = self._channel
        if channel is None:
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        to_id = str(message.get("to_id") or "")
        is_dm = bool(message.get("is_dm")) or (to_id and not to_id.startswith("^"))

        destination = channel
        if is_dm and to_id and self.config.get("thread_per_node", True):
            destination = await self._thread_for(to_id, to_id) or channel

        target = f" → `{to_id}`" if is_dm and to_id else ""
        body = discord.utils.escape_markdown(text)
        try:
            await destination.send(f"🖥️ **{label}**{target}: {body}")
        except Exception as exc:
            self._stats.errors += 1
            self.log(f"Could not mirror a web chat message: {exc}")
            return

        self._stats.mesh_to_discord += 1
        self._store("web->discord", to_id, label, text)
        await self._push_status()

    async def _publish_to_discord(self, message: dict) -> None:
        channel = self._channel
        if channel is None:
            return

        text = (message.get("text") or "").strip()
        author = message.get("from_name") or message.get("from_id") or "unknown"
        node_id = message.get("from_id") or ""
        marker = " 🔒" if message.get("is_dm") else ""

        # One node = one thread. Falls back to the parent channel whenever the
        # thread cannot be resolved, so a Discord-side failure never silently
        # swallows mesh traffic.
        if node_id and self._threading_wanted(message):
            channel = await self._thread_for(str(node_id), str(author)) or channel

        if self.config.get("use_embed", False):
            embed = discord.Embed(description=text, colour=0x2ECC71)
            embed.set_author(name=f"{author}{marker}")
            footer = [f"ch {message.get('channel_index', 0)}"]
            if node_id:
                footer.append(str(node_id))
            embed.set_footer(text=" | ".join(footer))
            await channel.send(embed=embed)
        else:
            body = discord.utils.escape_markdown(text)
            tag = f" `{node_id}`" if node_id else ""
            await channel.send(f"📡 **{author}**{tag}{marker}: {body}")

        self._stats.mesh_to_discord += 1
        self._store("mesh->discord", str(node_id), str(author), text)
        await self._push_status()

    # --- per-node threads --------------------------------------------------

    def _threading_wanted(self, message: dict) -> bool:
        if not self.config.get("thread_per_node", True):
            return False
        scope = str(self.config.get("thread_scope", "all")).strip().lower()
        if scope == "dm":
            return bool(message.get("is_dm"))
        return True

    async def _thread_for(self, node_id: str, author: str) -> Any:
        """Return the Discord thread dedicated to ``node_id``, creating it once.

        Threads archive themselves after a period of silence; an archived thread
        still accepts messages but Discord hides it, so we un-archive on use to
        keep a long-running conversation in one place.
        """
        parent = self._channel
        if parent is None:
            return None

        thread_id = self._threads.get(node_id)
        if thread_id:
            thread = parent.guild.get_thread(thread_id) if parent.guild else None
            if thread is None:
                try:
                    thread = await self._client.fetch_channel(thread_id)
                except Exception:
                    thread = None
                    self._forget_thread(node_id, thread_id)
            if thread is not None:
                if getattr(thread, "archived", False):
                    try:
                        await thread.edit(archived=False)
                    except Exception as exc:
                        self.log(f"Could not reopen thread for {node_id}: {exc}")
                return thread

        template = str(self.config.get("thread_name_template", "{name} ({id})"))
        try:
            name = template.format(name=author, id=node_id)[:100]
        except Exception:
            name = f"{author} ({node_id})"[:100]

        minutes = self._archive_minutes()
        try:
            thread = await parent.create_thread(
                name=name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=minutes,
                reason=f"Mesh bridge conversation with {node_id}",
            )
        except Exception as exc:
            self.log(f"Could not create a thread for {node_id}: {exc}. "
                     f"Grant the bot 'Create Public Threads' and 'Send Messages "
                     f"in Threads', or set thread_per_node to false.")
            return None

        self._remember_thread(node_id, thread.id, name)
        try:
            await thread.send(
                f"Private line to **{author}** `{node_id}`.\n"
                f"Everything written here is sent to that node only."
            )
        except Exception:
            pass
        self.log(f"Opened thread '{name}' for {node_id}")
        return thread

    def _archive_minutes(self) -> int:
        hours = self._as_int(self.config.get("thread_archive_hours", 24)) or 24
        allowed = (1, 24, 72, 168)  # Discord accepts 60/1440/4320/10080 minutes
        closest = min(allowed, key=lambda h: abs(h - hours))
        return closest * 60

    def _remember_thread(self, node_id: str, thread_id: int, name: str) -> None:
        self._threads[node_id] = thread_id
        self._thread_nodes[thread_id] = node_id
        if self._db is None:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO bridge_threads (node_id, thread_id, name, created)"
                " VALUES (?, ?, ?, ?)",
                (node_id, int(thread_id), name, int(time.time())),
            )
            self._db.commit()
        except Exception as exc:
            self.log(f"Could not persist the thread mapping: {exc}")

    def _forget_thread(self, node_id: str, thread_id: int) -> None:
        self._threads.pop(node_id, None)
        self._thread_nodes.pop(thread_id, None)
        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM bridge_threads WHERE node_id = ?", (node_id,))
            self._db.commit()
        except Exception:
            pass

    def _load_threads(self) -> None:
        """Restore the node<->thread mapping so a restart keeps the same threads."""
        if self._db is None:
            return
        try:
            rows = self._db.execute(
                "SELECT node_id, thread_id FROM bridge_threads"
            ).fetchall()
        except Exception as exc:
            self.log(f"Could not load thread mappings: {exc}")
            return
        for node_id, thread_id in rows:
            self._threads[str(node_id)] = int(thread_id)
            self._thread_nodes[int(thread_id)] = str(node_id)
        if rows:
            self.log(f"Restored {len(rows)} conversation thread(s).")

    # --- pairing -----------------------------------------------------------
    # A Discord account claims a mesh node by proving it can transmit from it.
    # The bot issues a short-lived code over Discord; the node sends that code
    # back over the air. Possession of the radio is the credential, which is
    # the only thing that cannot be faked from a keyboard.

    def _load_pairings(self) -> None:
        if self._db is None:
            return
        try:
            rows = self._db.execute(
                "SELECT discord_id, node_id FROM pairings"
            ).fetchall()
        except Exception as exc:
            self.log(f"Could not load pairings: {exc}")
            return
        for discord_id, node_id in rows:
            self._pair_by_discord[int(discord_id)] = str(node_id)
            self._pair_by_node[str(node_id)] = int(discord_id)
        if rows:
            self.log(f"Restored {len(rows)} pairing(s).")

    def _issue_code(self, discord_id: int, discord_name: str) -> str:
        """Mint a fresh code, replacing any outstanding one for this account."""
        ttl = max(60, self._as_int(self.config.get("pair_code_ttl_minutes", 15)) * 60)
        now = int(time.time())
        code = make_pair_code()
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM pair_codes WHERE discord_id = ? OR expires < ?",
                                 (int(discord_id), now))
                self._db.execute(
                    "INSERT INTO pair_codes (code, discord_id, discord_name, created, expires)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (code, int(discord_id), discord_name, now, now + ttl),
                )
                self._db.commit()
            except Exception as exc:
                self.log(f"Could not store the pairing code: {exc}")
        return code

    def _claim_code(self, code: str) -> tuple[int, str] | None:
        """Redeem a code exactly once. Returns (discord_id, name) or None."""
        if self._db is None:
            return None
        now = int(time.time())
        try:
            row = self._db.execute(
                "SELECT discord_id, discord_name FROM pair_codes"
                " WHERE code = ? AND expires >= ?",
                (code.upper(), now),
            ).fetchone()
            if row is None:
                return None
            self._db.execute("DELETE FROM pair_codes WHERE code = ?", (code.upper(),))
            self._db.commit()
            return int(row[0]), str(row[1] or "")
        except Exception as exc:
            self.log(f"Could not redeem the pairing code: {exc}")
            return None

    async def _try_pair(self, message: dict) -> bool:
        """Return True when the packet was a pairing code and was consumed."""
        if not self.config.get("pairing_enabled", True):
            return False

        text = (message.get("text") or "").strip()
        match = PAIR_CODE_RE.search(text)
        if not match:
            return False

        node_id = str(message.get("from_id") or "")
        if not node_id:
            return True  # malformed but still a code; do not relay it

        # By default the code must arrive as a direct message. On firmware 2.5+
        # that is encrypted to this node's public key, so nobody else on the
        # mesh can lift the code out of the air and claim the account first.
        if self.config.get("pair_require_dm", True) and not message.get("is_dm"):
            await self.send_mesh_message(
                "Send that code as a direct message, not to the channel.",
                to_id=node_id,
            )
            self.log(f"Pairing attempt from {node_id} rejected: sent in the clear.")
            return True

        claimed = self._claim_code("PAIR-" + match.group(1).upper())
        if claimed is None:
            await self.send_mesh_message("Code invalid or expired.", to_id=node_id)
            return True

        discord_id, discord_name = claimed
        node_name = str(message.get("from_name") or node_id)
        self._bind(discord_id, discord_name, node_id, node_name)

        await self.send_mesh_message(
            f"Paired with Discord user {discord_name}.", to_id=node_id
        )
        await self._notify_paired(discord_id, node_id, node_name)
        self.log(f"Paired Discord {discord_id} ({discord_name}) with node {node_id}")
        await self._push_status()
        return True

    def _bind(self, discord_id: int, discord_name: str, node_id: str, node_name: str) -> None:
        """Bind an account to a node, evicting any prior claim on either side."""
        old_node = self._pair_by_discord.pop(discord_id, None)
        if old_node:
            self._pair_by_node.pop(old_node, None)
        old_discord = self._pair_by_node.pop(node_id, None)
        if old_discord is not None:
            self._pair_by_discord.pop(old_discord, None)

        self._pair_by_discord[discord_id] = node_id
        self._pair_by_node[node_id] = discord_id

        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM pairings WHERE discord_id = ? OR node_id = ?",
                             (int(discord_id), node_id))
            self._db.execute(
                "INSERT INTO pairings (discord_id, discord_name, node_id, node_name, paired_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (int(discord_id), discord_name, node_id, node_name, int(time.time())),
            )
            self._db.commit()
        except Exception as exc:
            self.log(f"Could not persist the pairing: {exc}")

    def _unbind(self, discord_id: int) -> str | None:
        node_id = self._pair_by_discord.pop(discord_id, None)
        if node_id:
            self._pair_by_node.pop(node_id, None)
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM pairings WHERE discord_id = ?", (int(discord_id),))
                self._db.commit()
            except Exception:
                pass
        return node_id

    async def _notify_paired(self, discord_id: int, node_id: str, node_name: str) -> None:
        client = self._client
        if client is None:
            return
        try:
            user = client.get_user(discord_id) or await client.fetch_user(discord_id)
            await user.send(f"✅ Paired with node **{node_name}** `{node_id}`.")
        except Exception:
            pass
        await self._grant_paired_role(discord_id)

    async def _grant_paired_role(self, discord_id: int) -> None:
        name = str(self.config.get("paired_role_name", "") or "").strip()
        channel = self._channel
        if not name or channel is None or channel.guild is None:
            return
        guild = channel.guild
        try:
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(name=name, reason="Mesh bridge: paired node")
            member = guild.get_member(discord_id) or await guild.fetch_member(discord_id)
            await member.add_roles(role, reason="Paired a Meshtastic node")
        except Exception as exc:
            self.log(f"Could not assign the '{name}' role: {exc}. "
                     f"The bot needs 'Manage Roles' and a position above that role.")

    async def _greet(self, member: Any) -> None:
        if not self.config.get("pairing_enabled", True):
            return
        if member.id in self._pair_by_discord:
            return
        code = self._issue_code(member.id, member.display_name)
        try:
            await member.send(
                "**Welcome to the mesh bridge.**\n"
                "To link your Discord account to your Meshtastic node, send this "
                f"code from your radio as a **direct message** to the bridge node:\n"
                f"```\n{code}\n```"
                f"It expires in {self._as_int(self.config.get('pair_code_ttl_minutes', 15))} "
                f"minutes. Need a new one? Type `{self.config.get('command_prefix', '!mesh')} pair`."
            )
        except Exception:
            self.log(f"Could not DM {member} a pairing code; their DMs are probably closed.")



    async def _on_discord_message(self, client: Any, message: Any) -> None:
        if client.user and message.author.id == client.user.id:
            return
        if message.author.bot and not self.config.get("allow_bots", False):
            return
        bridge_id = self._as_int(self.config.get("discord_channel_id"))
        channel = message.channel
        target = self._default_target()

        if channel.id == bridge_id:
            pass  # the parent channel keeps its broadcast behaviour
        elif getattr(channel, "parent_id", None) == bridge_id:
            # A thread under the bridge channel is a private line to one node.
            node_id = self._thread_nodes.get(channel.id)
            if node_id is None:
                return  # a thread we did not open; not ours to relay
            target = node_id
        else:
            return

        content = self._normalize(message)
        prefix = str(self.config.get("command_prefix", "!mesh")).strip()

        if prefix and content.startswith(prefix):
            await self._handle_command(message, content[len(prefix):].strip())
            return

        if not self.config.get("discord_to_mesh", True) or not content:
            return

        await self._queue_outbound(message, content, to_id=target)

    def _normalize(self, message: Any) -> str:
        """Flatten Discord markup into something worth spending airtime on."""
        text = message.clean_content or ""
        text = CUSTOM_EMOJI_RE.sub(r":\1:", text)
        text = WHITESPACE_RE.sub(" ", text).strip()

        if message.attachments:
            names = ", ".join(a.filename for a in message.attachments[:2])
            text = f"{text} [file: {names}]".strip()
        if getattr(message, "stickers", None) and not text:
            text = f"[sticker: {message.stickers[0].name}]"
        return text

    def _default_target(self) -> str | None:
        target = (self.config.get("dm_target") or "").strip()
        return target or None

    async def _queue_outbound(self, message: Any, text: str, *, to_id: str | None) -> None:
        prefix = ""
        if self.config.get("name_prefix", True):
            prefix = f"[{message.author.display_name[:12]}] "

        max_payload = int(self.config.get("max_payload", 200) or 200)
        budget = max(32, max_payload - len(prefix.encode("utf-8")))
        chunks = split_utf8(text, budget)
        if not chunks:
            return

        limit = int(self.config.get("max_chunks", 4) or 4)
        truncated = len(chunks) > limit
        chunks = chunks[:limit]

        for chunk in chunks:
            payload = f"{prefix}{chunk}" if prefix else chunk
            # Record the fingerprint before transmitting: the packet can be
            # re-heard and dispatched back to us faster than the await returns.
            self._echo_add(fingerprint(payload))
            try:
                self._tx_queue.put_nowait(
                    Outbound(text=payload, to_id=to_id, author=str(message.author))
                )
            except asyncio.QueueFull:
                await self._reply(message, "⚠️ Transmit queue is full; try again shortly.")
                return

        if truncated:
            await self._reply(message, f"⚠️ Message truncated to {limit} packets.")
        try:
            await message.add_reaction("📡")
        except Exception:
            pass

    async def _tx_worker(self) -> None:
        """Serialise transmissions and space them out to protect duty cycle."""
        while True:
            try:
                item: Outbound = await self._tx_queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._send_to_mesh(item)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._stats.errors += 1
                self.log(f"Mesh transmit failed: {exc}")

            interval = float(self.config.get("tx_interval", 3) or 0)
            if interval > 0:
                try:
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    return

    async def _send_to_mesh(self, item: Outbound) -> None:
        channel_index = int(self.config.get("mesh_channel_index", 0) or 0)
        # to_id=None is translated to '^all' by the manager.
        await self.send_mesh_message(item.text, to_id=item.to_id, channel=channel_index)

        self._stats.discord_to_mesh += 1
        self._store("discord->mesh", item.to_id or "broadcast", item.author, item.text)
        self.log(f"TX -> {item.to_id or '^all'} (ch {channel_index}): {item.text}")
        await self._push_status()

    # --- commands ----------------------------------------------------------

    async def _handle_command(self, message: Any, rest: str) -> None:
        parts = rest.split(maxsplit=1)
        command = parts[0].lower() if parts else "help"
        args = parts[1] if len(parts) > 1 else ""
        prefix = self.config.get("command_prefix", "!mesh")

        if command == "status":
            await self._reply(message, self._status_report())
        elif command == "nodes":
            await self._reply(message, self._node_report())
        elif command == "dm":
            target, _, body = args.partition(" ")
            if not target or not body.strip():
                await self._reply(message, f"Usage: `{prefix} dm !abcd1234 your message`")
                return
            await self._queue_outbound(message, body.strip(), to_id=target.strip())
        elif command == "here":
            await self._reply(message, f"Channel ID: `{message.channel.id}`")
        elif command == "threads":
            await self._reply(message, self._thread_report())
        elif command == "pair":
            if not self.config.get("pairing_enabled", True):
                await self._reply(message, "Pairing is switched off on this bridge.")
                return
            existing = self._pair_by_discord.get(message.author.id)
            if existing:
                await self._reply(
                    message,
                    f"You are already paired with `{existing}`. "
                    f"Use `{prefix} unpair` first to change radios.",
                )
                return
            code = self._issue_code(message.author.id, message.author.display_name)
            minutes = self._as_int(self.config.get("pair_code_ttl_minutes", 15))
            try:
                await message.author.send(
                    "Send this code from your radio as a **direct message** to "
                    f"the bridge node:\n```\n{code}\n```Valid for {minutes} minutes."
                )
                await self._reply(message, "📬 Code sent to your DMs.")
            except Exception:
                await self._reply(
                    message,
                    "I could not DM you — open your privacy settings for this "
                    "server and try again.",
                )
        elif command == "simulate":
            # Injects a synthetic packet at the same point the radio reader
            # does, so threads, pairing and filtering can all be exercised on a
            # bench with a single node. Off by default: it lets anyone in the
            # channel forge traffic that appears to come from a given node.
            if not self.config.get("simulate_enabled", False):
                await self._reply(
                    message,
                    "Simulation is off. Enable `simulate_enabled` in the plugin "
                    "settings to test without a second radio.",
                )
                return
            parts = args.split()
            is_dm = bool(parts and parts[0].lower() == "dm")
            if is_dm:
                parts = parts[1:]
            if len(parts) < 2 or not parts[0].startswith("!"):
                await self._reply(
                    message,
                    f"Usage: `{prefix} simulate [dm] !abcd1234 your text`",
                )
                return
            node_id, text = parts[0], " ".join(parts[1:])
            await self._rx_queue.put({
                "from_id": node_id,
                "from_name": f"sim-{node_id[-4:]}",
                "to_id": self._local_node_id if is_dm else "^all",
                "text": text,
                "timestamp": int(time.time()),
                "is_dm": is_dm,
                "channel_index": self._as_int(self.config.get("mesh_channel_index", 0)),
            })
            await self._reply(
                message,
                f"Injected {'a direct message' if is_dm else 'a broadcast'} "
                f"from `{node_id}`.",
            )
        elif command == "whoami":
            node = self._pair_by_discord.get(message.author.id)
            await self._reply(
                message,
                f"You are paired with node `{node}`." if node
                else f"You are not paired yet. Run `{prefix} pair`.",
            )
        elif command == "unpair":
            node = self._unbind(message.author.id)
            await self._reply(
                message,
                f"Unpaired from `{node}`." if node else "You were not paired.",
            )
        elif command == "open":
            target = args.strip()
            if not target.startswith("!"):
                await self._reply(message, f"Usage: `{prefix} open !abcd1234`")
                return
            thread = await self._thread_for(target, target)
            await self._reply(
                message,
                f"Opened {thread.mention}" if thread else "Could not open that thread.",
            )
        else:
            threaded = self.config.get("thread_per_node", True)
            await self._reply(
                message,
                "**Mesh ↔ Discord bridge**\n"
                + ("Each node gets its own thread; write in a thread to reply to "
                   "that person only. Messages here go to the whole mesh.\n"
                   if threaded else
                   "Any ordinary message in this channel is transmitted to the mesh.\n")
                + f"`{prefix} status` — connection state and counters\n"
                f"`{prefix} nodes` — nodes currently visible\n"
                f"`{prefix} threads` — open conversations\n"
                f"`{prefix} pair` — link your Discord account to your radio\n"
                f"`{prefix} whoami` — show which node you are paired with\n"
                f"`{prefix} unpair` — drop that link\n"
                f"`{prefix} open !abcd1234` — start a conversation with a node\n"
                f"`{prefix} dm !abcd1234 text` — one-off direct message\n"
                f"`{prefix} here` — print this channel's ID",
            )

    def _thread_report(self) -> str:
        if not self._threads:
            return "No conversation threads yet. One opens as soon as a node speaks."
        lines = [f"**Conversations ({len(self._threads)})**"]
        for node_id, thread_id in list(self._threads.items())[:25]:
            lines.append(f"`{node_id}` → <#{thread_id}>")
        return "\n".join(lines)

    def _status_report(self) -> str:
        uptime = int(time.time() - self._stats.started_at)
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)

        tracker = self._safe(self.get_tracker_info) or {}
        radio = tracker.get("name") or tracker.get("id") or self._local_node_id or "none"

        return (
            "**Bridge status**\n"
            f"Discord: {STATUS_LABELS.get(self._status, self._status)}\n"
            f"Radio: `{radio}`\n"
            f"TX channel: `{self.config.get('mesh_channel_index', 0)}` | "
            f"RX filter: `{self.config.get('mesh_channel_filter', 'all')}`\n"
            f"Mesh→Discord: **{self._stats.mesh_to_discord}** | "
            f"Discord→Mesh: **{self._stats.discord_to_mesh}**\n"
            f"Dropped — echo: {self._stats.dropped_echo}, "
            f"filtered: {self._stats.dropped_filter}, errors: {self._stats.errors}\n"
            f"Conversations: **{len(self._threads)}** "
            f"({'threaded' if self.config.get('thread_per_node', True) else 'single channel'})\n"
            f"Paired accounts: **{len(self._pair_by_discord)}**\n"
            f"Uptime: {hours}h {minutes}m {seconds}s"
        )

    def _node_report(self) -> str:
        nodes = self._snapshot(self.get_nodes) + self._snapshot(self.get_nodes_no_position)
        if not nodes:
            return "No nodes visible yet."

        lines = [
            f"{'📍' if node.get('lat') not in (None, 0) else '  '} "
            f"`{node.get('id', '?')}` {node.get('name') or ''}"
            for node in nodes[:30]
        ]
        overflow = f"\n… and {len(nodes) - 30} more" if len(nodes) > 30 else ""
        return f"**Visible nodes ({len(nodes)}):**\n" + "\n".join(lines) + overflow

    @staticmethod
    def _snapshot(getter) -> list[dict]:
        """Copy node structures; the mapper mutates them from another thread."""
        try:
            data = getter()
            if isinstance(data, dict):
                result = []
                for key, value in list(data.items()):
                    if isinstance(value, dict):
                        entry = dict(value)
                        entry.setdefault("id", key)
                        result.append(entry)
                return result
            if isinstance(data, list):
                return [dict(item) for item in list(data) if isinstance(item, dict)]
        except Exception:
            return []
        return []

    async def _reply(self, message: Any, text: str) -> None:
        try:
            await message.reply(text, mention_author=False)
        except Exception:
            try:
                await message.channel.send(text)
            except Exception:
                pass

    # --- echo suppression --------------------------------------------------

    def _echo_add(self, key: str) -> None:
        ttl = float(self.config.get("echo_ttl", 180) or 180)
        now = time.monotonic()
        with self._echo_lock:
            self._echo = {k: v for k, v in self._echo.items() if v > now}
            self._echo[key] = now + ttl

    def _echo_hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._echo_lock:
            expiry = self._echo.pop(key, None)
        # The fingerprint is consumed on a hit so that a genuine repetition of
        # the same phrase later on still reaches Discord.
        return bool(expiry and expiry > now)

    # --- websocket and storage --------------------------------------------

    async def _push_status(self) -> None:
        try:
            await self.broadcast_ws(
                {
                    "type": "bridge_status",
                    "status": self._status,
                    "mesh_to_discord": self._stats.mesh_to_discord,
                    "discord_to_mesh": self._stats.discord_to_mesh,
                    "dropped_echo": self._stats.dropped_echo,
                    "errors": self._stats.errors,
                },
                channel="status",
            )
        except Exception:
            pass

    def _open_db(self) -> None:
        # Opened unconditionally: even with message logging switched off we must
        # persist the node<->thread mapping, or a restart would orphan every
        # conversation and open duplicates.
        try:
            self._db = self.get_database()
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS bridge_threads ("
                " node_id TEXT PRIMARY KEY,"
                " thread_id INTEGER NOT NULL,"
                " name TEXT,"
                " created INTEGER NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS pairings ("
                " discord_id INTEGER PRIMARY KEY,"
                " discord_name TEXT,"
                " node_id TEXT NOT NULL UNIQUE,"
                " node_name TEXT,"
                " paired_at INTEGER NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS pair_codes ("
                " code TEXT PRIMARY KEY,"
                " discord_id INTEGER NOT NULL,"
                " discord_name TEXT,"
                " created INTEGER NOT NULL,"
                " expires INTEGER NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS bridge_log ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " ts INTEGER NOT NULL,"
                " direction TEXT NOT NULL,"
                " peer TEXT,"
                " author TEXT,"
                " text TEXT)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bridge_log_ts ON bridge_log (ts)"
            )
            self._db.commit()
        except Exception as exc:
            self._db = None
            self.log(f"Could not initialise the plugin database: {exc}")
            return
        self._load_threads()
        self._load_pairings()

    def _close_db(self) -> None:
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    def _store(self, direction: str, peer: str, author: str, text: str) -> None:
        if self._db is None or not self.config.get("log_to_db", True):
            return
        try:
            self._db.execute(
                "INSERT INTO bridge_log (ts, direction, peer, author, text) VALUES (?, ?, ?, ?, ?)",
                (int(time.time()), direction, peer, author, text),
            )
            self._db.commit()
        except Exception as exc:
            self.log(f"Database write failed: {exc}")

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe(getter):
        try:
            return getter()
        except Exception:
            return None
