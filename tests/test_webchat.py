"""Integration tests for mirroring the MeshPulse web chat into Discord.

MeshPulse transmits messages composed in its own chat window without notifying
plugins, so the bridge watches `mapper.messages` instead of receiving a hook.
These tests cover that watcher: what it must pick up, what it must ignore, and
the two ways it could duplicate traffic.
"""
import asyncio
import importlib.util
import os
import sqlite3
import sys
import types

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

discord = types.ModuleType("discord")
discord.ChannelType = types.SimpleNamespace(public_thread="public_thread")
discord.Embed = lambda **kw: types.SimpleNamespace(
    set_author=lambda name: None, set_footer=lambda text: None
)
discord.utils = types.SimpleNamespace(
    escape_markdown=lambda s: s,
    get=lambda seq, **kw: None,
)
discord.Activity = lambda **kw: None
discord.ActivityType = types.SimpleNamespace(listening=1)
discord.Intents = types.SimpleNamespace(default=lambda: types.SimpleNamespace())
discord.Client = object
sys.modules["discord"] = discord

spec = importlib.util.spec_from_file_location("dbridge", PLUGIN_MAIN)
mod = importlib.util.module_from_spec(spec)
sys.modules["dbridge"] = mod
spec.loader.exec_module(mod)

LOCAL = "!base0000"


class FakeThread:
    def __init__(self, tid, name, parent):
        self.id = tid
        self.name = name
        self.parent_id = parent.id
        self.archived = False
        self.sent = []

    async def send(self, content=None, embed=None):
        self.sent.append(content)

    async def edit(self, **kw):
        self.archived = kw.get("archived", self.archived)


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
        self._next = 2000
        self.created = []

    async def send(self, content=None, embed=None):
        self.sent.append(content)

    async def create_thread(self, name, type=None, auto_archive_duration=None,
                            reason=None):
        self._next += 1
        t = FakeThread(self._next, name, self)
        self.guild.threads[t.id] = t
        self.created.append(name)
        return t


class FakeMapper:
    """Stands in for the MeshPulse mapper, newest-first and capped at 50."""

    def __init__(self, local_node_id=LOCAL):
        self.messages = {}
        self.local_node_id = local_node_id
        # A live radio connection, as the real mapper would have.
        self.connection_type = "serial"
        self.sent_over_radio = []
        self._serial_iface = _Serial(self.sent_over_radio)

    def add(self, text, *, from_id=LOCAL, to_id="^all", channel=0, ts=None,
            is_dm=False, from_name="You"):
        entry = {
            "from_id": from_id,
            "from_name": from_name,
            "to_id": to_id,
            "text": text,
            "timestamp": ts if ts is not None else int(mod.time.time()),
            "is_dm": is_dm,
            "channel_index": channel,
        }
        self.messages.setdefault(channel, []).insert(0, entry)
        if len(self.messages[channel]) > 50:
            self.messages[channel] = self.messages[channel][:50]
        return entry


class _Serial:
    def __init__(self, sink):
        self.sink = sink

    def sendText(self, text, channelIndex=0, destinationId="^all"):
        self.sink.append((text, destinationId))


class Bridge(mod.DiscordBridge):
    def __init__(self, config, db, mapper):
        self.plugin_id = "test/bridge"
        self.config = config
        self._test_db = db
        self._manager = None
        self._mapper = mapper
        self.logs = []
        self.sent_mesh = []

    def log(self, m):
        self.logs.append(m)

    def get_database(self):
        return self._test_db

    def register_ws_channel(self, n):
        pass

    def broadcast_ws(self, *a, **k):
        pass

    def get_tracker_info(self):
        return {"name": "base"}

    async def send_mesh_message(self, text, to_id=None, channel=0):
        # Mirrors the real manager: transmits without writing to
        # mapper.messages. The watcher must therefore never see this.
        self.sent_mesh.append((text, to_id))


def make(config=None):
    cfg = {"discord_channel_id": "999", "relay_web_chat": True,
           "thread_per_node": True, "log_to_db": True,
           "web_chat_label": "MeshPulse"}
    cfg.update(config or {})
    mapper = FakeMapper()
    b = Bridge(cfg, sqlite3.connect(":memory:"), mapper)
    b._stopping = False
    b._echo = {}
    b._echo_lock = mod.threading.Lock()
    b._local_node_id = LOCAL
    b._status = "online"
    b._stats = mod.Stats()
    b._threads, b._thread_nodes = {}, {}
    b._pair_by_discord, b._pair_by_node = {}, {}
    b._web_seen, b._web_primed = set(), False
    b._db = None
    ch = FakeChannel()
    b._channel = ch
    b._client = None
    b._tx_queue = asyncio.Queue(maxsize=200)
    b._open_db()
    return b, ch, mapper


def prime(b):
    """Reproduces what the worker does once before its first poll."""
    b._web_seen = b._web_fingerprints()
    b._web_primed = True


R = []


def check(name, cond):
    R.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name)


async def main():
    # 1. history present at startup must not be replayed
    b, ch, mapper = make()
    mapper.add("stara wiadomosc", ts=1000)
    mapper.add("jeszcze starsza", ts=900)
    prime(b)
    await b._drain_web_chat()
    check("startup history is not replayed", ch.sent == [])

    # 2. a newly composed message is mirrored
    mapper.add("czesc z przegladarki", ts=2000)
    await b._drain_web_chat()
    check("new web chat message is mirrored", len(ch.sent) == 1)
    check("mirrored text is carried", "czesc z przegladarki" in ch.sent[0])
    check("label distinguishes it from radio traffic", "MeshPulse" in ch.sent[0])

    # 3. polling again must not repeat it
    await b._drain_web_chat()
    await b._drain_web_chat()
    check("repeated polls do not duplicate", len(ch.sent) == 1)

    # 4. traffic received from other nodes belongs to the hook, not here
    b2, ch2, mapper2 = make()
    prime(b2)
    mapper2.add("z radia", from_id="!aaaa1111", from_name="Kuba", ts=3000)
    await b2._drain_web_chat()
    check("messages from other nodes are ignored", ch2.sent == [])

    # 5. the bridge's own Discord-to-mesh traffic cannot loop back
    b3, ch3, mapper3 = make()
    prime(b3)
    await b3._send_to_mesh(mod.Outbound(text="z discorda", to_id=None, author="R"))
    await b3._drain_web_chat()
    check("bridge transmissions never reach the watcher", ch3.sent == [])
    check("the transmission did happen", len(b3._mapper.sent_over_radio) == 1)

    # 6. a broadcast goes to the parent channel
    b4, ch4, mapper4 = make()
    prime(b4)
    mapper4.add("do wszystkich", to_id="^all", ts=4000)
    await b4._drain_web_chat()
    check("broadcast lands in the parent channel", len(ch4.sent) == 1)
    check("no thread opened for a broadcast", ch4.created == [])

    # 7. a direct message goes to that node's thread
    b5, ch5, mapper5 = make()
    prime(b5)
    mapper5.add("tylko do ciebie", to_id="!aaaa1111", is_dm=True, ts=5000)
    await b5._drain_web_chat()
    check("direct message opens the node's thread", len(ch5.created) == 1)
    check("parent channel stays quiet", ch5.sent == [])
    tid = b5._threads.get("!aaaa1111")
    thread = ch5.guild.threads[tid]
    body = [m for m in thread.sent if "tylko do ciebie" in str(m)]
    check("the thread carries the message", len(body) == 1)
    check("recipient is shown", "!aaaa1111" in body[0])

    # 8. the same DM thread is reused, not recreated
    mapper5.add("druga", to_id="!aaaa1111", is_dm=True, ts=5001)
    await b5._drain_web_chat()
    check("DM thread is reused", len(ch5.created) == 1)

    # 9. eviction past the 50-item cap must not resurrect anything
    b6, ch6, mapper6 = make()
    prime(b6)
    for i in range(60):
        mapper6.add(f"wiadomosc {i}", ts=6000 + i)
    await b6._drain_web_chat()
    first = len(ch6.sent)
    check("capped backlog mirrors at most the cap", 0 < first <= 50)
    await b6._drain_web_chat()
    check("evicted entries do not reappear", len(ch6.sent) == first)
    check("seen set stays bounded", len(b6._web_seen) <= 50)

    # 10. switched off
    b7, ch7, mapper7 = make({"relay_web_chat": False})
    prime(b7)
    mapper7.add("nie powinno przejsc", ts=7000)
    if b7.config.get("relay_web_chat", True):
        await b7._drain_web_chat()
    check("relay_web_chat=false mirrors nothing", ch7.sent == [])

    # 11. empty payloads are skipped
    b8, ch8, mapper8 = make()
    prime(b8)
    mapper8.add("   ", ts=8000)
    await b8._drain_web_chat()
    check("blank message is skipped", ch8.sent == [])

    # 12. counters and the log
    b9, ch9, mapper9 = make()
    prime(b9)
    mapper9.add("liczona", ts=9000)
    await b9._drain_web_chat()
    check("counter advances", b9._stats.mesh_to_discord == 1)
    rows = b9._db.execute(
        "SELECT direction FROM bridge_log WHERE direction = 'web->discord'"
    ).fetchall()
    check("logged with its own direction", len(rows) == 1)

    # 13. a Discord failure must not kill the watcher
    b10, ch10, mapper10 = make()
    prime(b10)

    async def boom(content=None, embed=None):
        raise RuntimeError("Missing Access")

    ch10.send = boom
    mapper10.add("nie wyjdzie", ts=10000)
    await b10._drain_web_chat()
    check("send failure is contained", b10._stats.errors == 1)
    check("failure is logged", any("mirror" in m for m in b10.logs))

    # 14. a mapper replaced on reconnect must not replay its contents
    b11, ch11, mapper11 = make()
    mapper11.add("przed restartem", ts=11000)
    prime(b11)
    b11._mapper = FakeMapper()
    await b11._drain_web_chat()
    check("replaced mapper replays nothing", ch11.sent == [])

    # 15. the node id is resolved without on_connect ever firing
    b13, ch13, mapper13 = make()
    b13._local_node_id = None          # on_connect never fired
    prime(b13)
    mapper13.add("po wlaczeniu wtyczki", ts=13000)
    await b13._drain_web_chat()
    check("node id resolved from the mapper, not from on_connect",
          len(ch13.sent) == 1)
    check("resolved id is cached", b13._local_node_id == LOCAL)

    # 16. with no id available anywhere, nothing is mirrored and nothing raises
    b14, ch14, mapper14 = make()
    b14._local_node_id = None
    b14._mapper = FakeMapper(local_node_id=None)
    b14.get_tracker_info = lambda: {}
    prime(b14)
    b14._mapper.add("osierocona", ts=14000)
    await b14._drain_web_chat()
    check("unknown node id mirrors nothing, without raising", ch14.sent == [])

    # 16b. a Discord transmission appears in the MeshPulse chat too
    b15, ch15, mapper15 = make()
    prime(b15)
    b15._channel = ch15
    await b15._send_to_mesh(mod.Outbound(text="[R] z discorda", to_id=None, author="R"))
    rows = mapper15.messages.get(0, [])
    check("transmission is recorded in the MeshPulse store", len(rows) == 1)
    check("it is attributed to Discord", rows[0]["from_name"] == "Discord")
    check("it carries this node's id", rows[0]["from_id"] == LOCAL)

    # ...and must not come straight back through the watcher
    await b15._drain_web_chat()
    check("recorded transmission does not loop back to Discord", ch15.sent == [])

    # a DM keeps its recipient
    await b15._send_to_mesh(mod.Outbound(text="[R] priv", to_id="!aaaa1111", author="R"))
    rows = mapper15.messages.get(0, [])
    check("DM records its recipient", rows[0]["to_id"] == "!aaaa1111" and rows[0]["is_dm"])
    await b15._drain_web_chat()
    check("DM does not loop back either", ch15.sent == [])

    # switched off
    b16, ch16, mapper16 = make({"echo_to_meshpulse": False})
    prime(b16)
    await b16._send_to_mesh(mod.Outbound(text="cicho", to_id=None, author="R"))
    check("echo_to_meshpulse=false records nothing", mapper16.messages == {})

    # 17. missing or malformed stores are tolerated
    b12, ch12, _ = make()
    prime(b12)
    b12._mapper = types.SimpleNamespace()
    await b12._drain_web_chat()
    b12._mapper = types.SimpleNamespace(messages={0: ["not a dict", None]})
    await b12._drain_web_chat()
    check("malformed store does not raise", ch12.sent == [])

    print()
    failed = [n for n, ok in R if not ok]
    print(f"{len(R) - len(failed)}/{len(R)} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        sys.exit(1)


asyncio.run(main())
