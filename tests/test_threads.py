"""Integration tests for per-node conversation threads.

Runs against the REAL MeshPulse plugin base class (cloned repo on sys.path)
with a stubbed discord.py, so the routing logic is exercised end to end.
"""
import asyncio
import importlib.util
import sqlite3
import sys
import types

import os

# The tests run against the real MeshPulse plugin base class rather than a
# stub, so a checkout of MeshPulse must be reachable. Override with
# MESHPULSE_PATH=/path/to/meshpulse when it lives somewhere else.
MESHPULSE_PATH = os.environ.get("MESHPULSE_PATH", "../../meshpulse")
if not os.path.isdir(os.path.join(MESHPULSE_PATH, "mapper")):
    raise SystemExit(
        f"MeshPulse checkout not found at {MESHPULSE_PATH!r}.\n"
        f"Clone it next to this repository, or set MESHPULSE_PATH."
    )
sys.path.insert(0, MESHPULSE_PATH)

PLUGIN_MAIN = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "backend", "main.py"
)

# --- stub discord.py ------------------------------------------------------
discord = types.ModuleType("discord")


class _ChannelType:
    public_thread = "public_thread"


class _Embed:
    def __init__(self, **kw):
        self.kw = kw
        self.author = None
        self.footer = None

    def set_author(self, name):
        self.author = name

    def set_footer(self, text):
        self.footer = text


discord.ChannelType = _ChannelType
discord.Embed = _Embed
discord.utils = types.SimpleNamespace(escape_markdown=lambda s: s)
discord.Activity = lambda **kw: None
discord.ActivityType = types.SimpleNamespace(listening=1)
discord.Intents = types.SimpleNamespace(default=lambda: types.SimpleNamespace())
discord.Client = object
sys.modules["discord"] = discord

spec = importlib.util.spec_from_file_location(
    "dbridge", PLUGIN_MAIN
)
mod = importlib.util.module_from_spec(spec)
sys.modules["dbridge"] = mod  # dataclass(slots=True) resolves via sys.modules
spec.loader.exec_module(mod)


# --- doubles --------------------------------------------------------------
class FakeThread:
    def __init__(self, tid, name, parent):
        self.id = tid
        self.name = name
        self.parent_id = parent.id
        self.archived = False
        self.sent = []
        self.mention = f"<#{tid}>"

    async def send(self, content=None, embed=None):
        self.sent.append(content if content is not None else embed)

    async def edit(self, **kw):
        if "archived" in kw:
            self.archived = kw["archived"]


class FakeGuild:
    def __init__(self):
        self.threads = {}

    def get_thread(self, tid):
        return self.threads.get(tid)


class FakeChannel:
    def __init__(self, cid=999):
        self.id = cid
        self.guild = FakeGuild()
        self.sent = []
        self._next = 1000
        self.created = []

    async def send(self, content=None, embed=None):
        self.sent.append(content if content is not None else embed)

    async def create_thread(self, name, type=None, auto_archive_duration=None, reason=None):
        self._next += 1
        t = FakeThread(self._next, name, self)
        self.guild.threads[t.id] = t
        self.created.append((name, auto_archive_duration))
        return t


class FakeAuthor:
    def __init__(self, name="Ryszard", bot=False, aid=7):
        self.display_name = name
        self.bot = bot
        self.id = aid

    def __str__(self):
        return self.display_name


class FakeMessage:
    def __init__(self, channel, content="hello", author=None):
        self.channel = channel
        self.author = author or FakeAuthor()
        self.clean_content = content
        self.attachments = []
        self.stickers = []
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def reply(self, text):
        self.channel.sent.append(text)


class FakeClient:
    def __init__(self, channels):
        self.user = types.SimpleNamespace(id=1)
        self._channels = channels

    async def fetch_channel(self, cid):
        if cid in self._channels:
            return self._channels[cid]
        raise RuntimeError("unknown channel")


# --- harness --------------------------------------------------------------
class Bridge(mod.DiscordBridge):
    """Overrides only the mapper-provided plumbing."""

    def __init__(self, config, db):
        self.plugin_id = "test/discord-bridge"
        self.config = config
        self._mapper = None
        self._manager = None
        self._test_db = db
        self.logs = []
        self.sent_mesh = []

    def log(self, msg):
        self.logs.append(msg)

    def get_database(self):
        return self._test_db

    def register_ws_channel(self, name):
        pass

    def broadcast_ws(self, *a, **kw):
        pass

    def get_tracker_info(self):
        return {"name": "base"}

    async def send_mesh_message(self, text, to_id=None, channel=0):
        self.sent_mesh.append((text, to_id, channel))


def make(config=None, db=None):
    cfg = {
        "discord_channel_id": "999",
        "thread_per_node": True,
        "thread_scope": "all",
        "thread_archive_hours": 24,
        "log_to_db": True,
    }
    cfg.update(config or {})
    db = db or sqlite3.connect(":memory:")
    b = Bridge(cfg, db)
    b._stopping = False
    b._echo = {}
    b._echo_lock = mod.threading.Lock()
    b._local_node_id = "!base0000"
    b._status = "online"
    b._stats = mod.Stats()
    b._threads = {}
    b._thread_nodes = {}
    b._db = None
    ch = FakeChannel()
    b._channel = ch
    b._client = FakeClient({ch.id: ch})
    b._tx_queue = asyncio.Queue(maxsize=200)
    b._open_db()
    return b, ch, db


RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name)


async def main():
    # 1. first message from a node opens a thread
    b, ch, db = make()
    await b._publish_to_discord(
        {"from_id": "!aaaa1111", "from_name": "Kuba", "text": "czesc", "channel_index": 0}
    )
    check("thread opened on first contact", len(ch.created) == 1)
    check("thread named after the node", "Kuba (!aaaa1111)" == ch.created[0][0])
    check("archive window is 24h", ch.created[0][1] == 1440)
    check("message landed in the thread, not the channel", ch.sent == [])
    tid = b._threads["!aaaa1111"]
    check("thread carries the message", any("czesc" in str(s) for s in ch.guild.threads[tid].sent))

    # 2. second message reuses it
    await b._publish_to_discord(
        {"from_id": "!aaaa1111", "from_name": "Kuba", "text": "jestem", "channel_index": 0}
    )
    check("same node reuses one thread", len(ch.created) == 1)

    # 3. a different node gets its own
    await b._publish_to_discord(
        {"from_id": "!bbbb2222", "from_name": "Ola", "text": "hej", "channel_index": 0}
    )
    check("second node gets a separate thread", len(ch.created) == 2)
    check("two conversations tracked", len(b._threads) == 2)

    # 4. writing in a thread addresses that node only
    thread_a = ch.guild.threads[b._threads["!aaaa1111"]]
    await b._on_discord_message(b._client, FakeMessage(thread_a, "gdzie jestes?"))
    item = b._tx_queue.get_nowait()
    check("thread reply is addressed to that node", item.to_id == "!aaaa1111")
    check("author tag preserved", item.text.startswith("[Ryszard]"))

    # 5. parent channel still broadcasts
    await b._on_discord_message(b._client, FakeMessage(ch, "wszyscy tam?"))
    item = b._tx_queue.get_nowait()
    check("parent channel still broadcasts", item.to_id is None)

    # 6. unrelated thread is ignored
    stray = FakeThread(555, "random", FakeChannel(cid=4242))
    before = b._tx_queue.qsize()
    await b._on_discord_message(b._client, FakeMessage(stray, "nie moje"))
    check("foreign thread ignored", b._tx_queue.qsize() == before)

    # 7. archived thread is reopened
    thread_a.archived = True
    await b._publish_to_discord(
        {"from_id": "!aaaa1111", "from_name": "Kuba", "text": "wracam", "channel_index": 0}
    )
    check("archived thread reopened", thread_a.archived is False)
    check("no duplicate thread created", len(ch.created) == 2)

    # 8. mapping survives a restart
    b2, ch2, _ = make(db=db)
    check("threads restored from the database", b2._threads == b._threads)
    check("reverse map restored", b2._thread_nodes == b._thread_nodes)

    # 9. threading can be switched off
    b3, ch3, _ = make({"thread_per_node": False})
    await b3._publish_to_discord(
        {"from_id": "!cccc3333", "from_name": "Ktos", "text": "hej", "channel_index": 0}
    )
    check("thread_per_node=false keeps one channel", ch3.created == [] and len(ch3.sent) == 1)

    # 10. scope=dm leaves broadcasts in the channel
    b4, ch4, _ = make({"thread_scope": "dm"})
    await b4._publish_to_discord(
        {"from_id": "!dddd4444", "from_name": "Bc", "text": "public", "channel_index": 0}
    )
    check("scope=dm: broadcast stays in channel", ch4.created == [])
    await b4._publish_to_discord(
        {"from_id": "!dddd4444", "from_name": "Bc", "text": "priv", "is_dm": True, "channel_index": 0}
    )
    check("scope=dm: direct message opens a thread", len(ch4.created) == 1)

    # 11. thread creation failure falls back to the channel
    b5, ch5, _ = make()

    async def boom(*a, **kw):
        raise RuntimeError("Missing Permissions")

    ch5.create_thread = boom
    await b5._publish_to_discord(
        {"from_id": "!eeee5555", "from_name": "X", "text": "fallback", "channel_index": 0}
    )
    check("falls back to the channel when threads are denied", len(ch5.sent) == 1)
    check("failure is logged with a fix hint",
          any("Create Public Threads" in m for m in b5.logs))

    # 12. transmit really addresses the node
    b6, ch6, _ = make()
    await b6._send_to_mesh(mod.Outbound(text="hi", to_id="!aaaa1111", author="R"))
    check("send_mesh_message receives the node id", b6.sent_mesh[0][1] == "!aaaa1111")

    print()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        sys.exit(1)


asyncio.run(main())
