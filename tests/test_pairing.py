"""Integration tests for Discord account <-> mesh node pairing."""
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

discord = types.ModuleType("discord")


class _ChannelType:
    public_thread = "public_thread"


discord.ChannelType = _ChannelType
discord.Embed = lambda **kw: types.SimpleNamespace(
    set_author=lambda name: None, set_footer=lambda text: None
)
discord.utils = types.SimpleNamespace(
    escape_markdown=lambda s: s,
    get=lambda seq, **kw: next(
        (x for x in seq if all(getattr(x, k) == v for k, v in kw.items())), None
    ),
)
discord.Activity = lambda **kw: None
discord.ActivityType = types.SimpleNamespace(listening=1)
discord.Intents = types.SimpleNamespace(default=lambda: types.SimpleNamespace())
discord.Client = object
sys.modules["discord"] = discord

spec = importlib.util.spec_from_file_location(
    "dbridge", PLUGIN_MAIN
)
mod = importlib.util.module_from_spec(spec)
sys.modules["dbridge"] = mod
spec.loader.exec_module(mod)


class FakeUser:
    def __init__(self, uid, name):
        self.id = uid
        self.display_name = name
        self.bot = False
        self.dms = []
        self.roles_added = []
        self.dm_closed = False

    def __str__(self):
        return self.display_name

    async def send(self, text):
        if self.dm_closed:
            raise RuntimeError("Cannot send messages to this user")
        self.dms.append(text)

    async def add_roles(self, role, reason=None):
        self.roles_added.append(role.name)


class FakeRole:
    def __init__(self, name):
        self.name = name


class FakeGuild:
    def __init__(self):
        self.threads = {}
        self.roles = []
        self.members = {}
        self.created_roles = []

    def get_thread(self, tid):
        return self.threads.get(tid)

    def get_member(self, uid):
        return self.members.get(uid)

    async def fetch_member(self, uid):
        return self.members[uid]

    async def create_role(self, name, reason=None):
        r = FakeRole(name)
        self.roles.append(r)
        self.created_roles.append(name)
        return r


class FakeChannel:
    def __init__(self, cid=999):
        self.id = cid
        self.guild = FakeGuild()
        self.sent = []

    async def send(self, content=None, embed=None):
        self.sent.append(content)


class FakeMessage:
    def __init__(self, channel, content, author):
        self.channel = channel
        self.author = author
        self.clean_content = content
        self.attachments = []
        self.stickers = []
        self.replies = []

    async def add_reaction(self, e):
        pass

    async def reply(self, text, mention_author=None):
        self.replies.append(text)


class FakeClient:
    def __init__(self, users):
        self.user = types.SimpleNamespace(id=1)
        self._users = users

    def get_user(self, uid):
        return self._users.get(uid)

    async def fetch_user(self, uid):
        return self._users[uid]


class Bridge(mod.DiscordBridge):
    def __init__(self, config, db):
        self.plugin_id = "test/bridge"
        self.config = config
        self._test_db = db
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
        self.sent_mesh.append((text, to_id))


def make(config=None, db=None):
    cfg = {"discord_channel_id": "999", "pairing_enabled": True,
           "pair_require_dm": True, "pair_code_ttl_minutes": 15,
           "thread_per_node": True, "log_to_db": True}
    cfg.update(config or {})
    db = db or sqlite3.connect(":memory:")
    b = Bridge(cfg, db)
    b._stopping = False
    b._echo = {}
    b._echo_lock = mod.threading.Lock()
    b._local_node_id = "!base0000"
    b._status = "online"
    b._stats = mod.Stats()
    b._threads, b._thread_nodes = {}, {}
    b._pair_by_discord, b._pair_by_node = {}, {}
    b._db = None
    ch = FakeChannel()
    b._channel = ch
    b._tx_queue = asyncio.Queue(maxsize=200)
    b._open_db()
    return b, ch, db


R = []


def check(name, cond):
    R.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name)


async def main():
    # --- happy path -------------------------------------------------------
    b, ch, db = make({"paired_role_name": "mesh"})
    alice = FakeUser(111, "Alice")
    b._client = FakeClient({111: alice})
    ch.guild.members[111] = alice

    code = b._issue_code(111, "Alice")
    check("code has the expected shape", mod.PAIR_CODE_RE.fullmatch(code) is not None)
    check("code avoids confusable glyphs",
          not set("01OIL") & set(code.split("-")[1]))

    consumed = await b._try_pair(
        {"from_id": "!aaaa1111", "from_name": "Kuba", "text": code, "is_dm": True}
    )
    check("pairing packet is consumed, not relayed", consumed is True)
    check("binding stored in memory", b._pair_by_discord[111] == "!aaaa1111")
    check("reverse binding stored", b._pair_by_node["!aaaa1111"] == 111)
    check("radio gets a confirmation", any("Paired" in t for t, _ in b.sent_mesh))
    check("discord user gets a DM", any("Paired" in d for d in alice.dms))
    check("role created and granted", alice.roles_added == ["mesh"])

    # --- single use -------------------------------------------------------
    b.sent_mesh.clear()
    await b._try_pair(
        {"from_id": "!cccc3333", "from_name": "Thief", "text": code, "is_dm": True}
    )
    check("code cannot be redeemed twice",
          b._pair_by_node.get("!cccc3333") is None)
    check("replay gets an explicit rejection",
          any("invalid or expired" in t for t, _ in b.sent_mesh))

    # --- broadcast codes are refused -------------------------------------
    b2, _, _ = make()
    b2._client = FakeClient({222: FakeUser(222, "Bob")})
    code2 = b2._issue_code(222, "Bob")
    b2.sent_mesh.clear()
    consumed = await b2._try_pair(
        {"from_id": "!bbbb2222", "from_name": "Bob", "text": code2, "is_dm": False}
    )
    check("code sent in the clear is consumed but refused", consumed is True)
    check("no binding from a broadcast code", b2._pair_by_discord == {})
    check("sender is told to use a DM",
          any("direct message" in t for t, _ in b2.sent_mesh))
    check("refusal is logged", any("in the clear" in m for m in b2.logs))
    check("code survives for a proper retry",
          (await b2._try_pair({"from_id": "!bbbb2222", "from_name": "Bob",
                               "text": code2, "is_dm": True})) is True
          and b2._pair_by_discord.get(222) == "!bbbb2222")

    # --- expiry -----------------------------------------------------------
    b3, _, _ = make({"pair_code_ttl_minutes": 1})
    b3._client = FakeClient({333: FakeUser(333, "Carol")})
    code3 = b3._issue_code(333, "Carol")
    b3._db.execute("UPDATE pair_codes SET expires = ? WHERE code = ?",
                   (int(mod.time.time()) - 5, code3))
    b3._db.commit()
    b3.sent_mesh.clear()
    await b3._try_pair({"from_id": "!dddd4444", "text": code3, "is_dm": True})
    check("expired code is rejected", b3._pair_by_discord == {})

    # --- rebinding --------------------------------------------------------
    b4, ch4, _ = make()
    dave = FakeUser(444, "Dave")
    b4._client = FakeClient({444: dave})
    await b4._try_pair({"from_id": "!1111aaaa", "text": b4._issue_code(444, "Dave"),
                        "is_dm": True})
    await b4._try_pair({"from_id": "!2222bbbb", "text": b4._issue_code(444, "Dave"),
                        "is_dm": True})
    check("new radio replaces the old one", b4._pair_by_discord[444] == "!2222bbbb")
    check("old node released", "!1111aaaa" not in b4._pair_by_node)
    check("exactly one binding per account", len(b4._pair_by_discord) == 1)
    rows = b4._db.execute("SELECT COUNT(*) FROM pairings").fetchone()[0]
    check("database holds one row too", rows == 1)

    # --- a node can only belong to one account ----------------------------
    b5, _, _ = make()
    b5._client = FakeClient({551: FakeUser(551, "E"), 552: FakeUser(552, "F")})
    await b5._try_pair({"from_id": "!5555cccc", "text": b5._issue_code(551, "E"),
                        "is_dm": True})
    await b5._try_pair({"from_id": "!5555cccc", "text": b5._issue_code(552, "F"),
                        "is_dm": True})
    check("node transfers to the newest claimant", b5._pair_by_node["!5555cccc"] == 552)
    check("previous owner loses the node", 551 not in b5._pair_by_discord)

    # --- persistence ------------------------------------------------------
    b6, _, _ = make(db=db)
    check("pairings restored after restart", b6._pair_by_discord == b._pair_by_discord)

    # --- ordinary traffic is untouched ------------------------------------
    b7, _, _ = make()
    check("plain text is not treated as a code",
          (await b7._try_pair({"from_id": "!x", "text": "hej co tam", "is_dm": True})) is False)
    check("code-like word without prefix ignored",
          (await b7._try_pair({"from_id": "!x", "text": "7K2M", "is_dm": True})) is False)

    # --- commands ---------------------------------------------------------
    b8, ch8, _ = make()
    gina = FakeUser(888, "Gina")
    b8._client = FakeClient({888: gina})
    msg = FakeMessage(ch8, "!mesh pair", gina)
    await b8._handle_command(msg, "pair")
    check("pair command DMs a code", any("PAIR-" in d for d in gina.dms))
    check("pair command confirms in channel", any("DMs" in r for r in msg.replies))

    msg = FakeMessage(ch8, "!mesh whoami", gina)
    await b8._handle_command(msg, "whoami")
    check("whoami reports unpaired", any("not paired" in r for r in msg.replies))

    sent = [d for d in gina.dms if "PAIR-" in d][0]
    real_code = mod.PAIR_CODE_RE.search(sent).group(0)
    await b8._try_pair({"from_id": "!8888eeee", "text": real_code, "is_dm": True})
    msg = FakeMessage(ch8, "!mesh whoami", gina)
    await b8._handle_command(msg, "whoami")
    check("whoami reports the node after pairing",
          any("!8888eeee" in r for r in msg.replies))

    msg = FakeMessage(ch8, "!mesh unpair", gina)
    await b8._handle_command(msg, "unpair")
    check("unpair clears the binding", b8._pair_by_discord == {})
    rows = b8._db.execute("SELECT COUNT(*) FROM pairings").fetchone()[0]
    check("unpair clears the database row", rows == 0)

    # --- closed DMs are handled -------------------------------------------
    b9, ch9, _ = make()
    hank = FakeUser(999, "Hank")
    hank.dm_closed = True
    b9._client = FakeClient({999: hank})
    msg = FakeMessage(ch9, "!mesh pair", hank)
    await b9._handle_command(msg, "pair")
    check("closed DMs produce a helpful reply",
          any("privacy settings" in r for r in msg.replies))

    # --- pairing switched off ---------------------------------------------
    b10, _, _ = make({"pairing_enabled": False})
    check("disabled pairing relays the packet normally",
          (await b10._try_pair({"from_id": "!x", "text": "PAIR-7K2M", "is_dm": True})) is False)

    print()
    failed = [n for n, ok in R if not ok]
    print(f"{len(R) - len(failed)}/{len(R)} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        sys.exit(1)


asyncio.run(main())
