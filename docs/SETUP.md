# Setting up your own bridge

This walks you from nothing to a working bridge: your own Discord server, your
own bot, and the plugin running on your MeshPulse instance. Allow about twenty
minutes.

Nothing here is shared with anyone else. The server is yours, the bot is yours,
and the bridge talks only to your radio. If you later want other people in,
invite them to your server — but you do not need anyone's permission or
infrastructure to start.

**What you need first**

- A Meshtastic radio, connected to a machine running MeshPulse 2.3.0 or newer
- That machine online whenever you want the bridge to work. It transmits on
  your behalf; if it sleeps, the bridge sleeps
- A Discord account

---

## 1. Create a server

In Discord, click the **+** at the bottom of the server list on the left →
**Create My Own** → **For me and my friends**. Name it whatever you like.

Delete or ignore the channels Discord creates for you, and make one text
channel for the bridge — `#mesh` is a reasonable name. One channel is enough:
everything your radio hears arrives there, and anything you type there goes out
over the air.

## 2. Create a bot

Go to <https://discord.com/developers/applications>, signed in with the same
account.

1. **New Application** → give it a name → **Create**
2. Open **Bot** in the left-hand menu
3. Scroll to **Privileged Gateway Intents** and enable **MESSAGE CONTENT
   INTENT**. Without it the bot receives empty messages and can relay nothing
4. **Save Changes**
5. Back at the top, **Reset Token**, then **Copy**

Keep that token somewhere safe for the next few minutes. It is shown once, and
it is the key to the bot: anyone holding it can act as your bot. If you lose it
or paste it somewhere public, reset it — the old one stops working immediately.

## 3. Invite the bot to your server

Still in the developer portal:

1. **OAuth2** → **URL Generator**
2. Under **Scopes**, tick `bot`. The permissions list appears only after you do
3. Under **Bot Permissions**, tick:

   | Permission | Why |
   |---|---|
   | View Channels | see the bridge channel |
   | Send Messages | post what the radio hears |
   | Read Message History | read context on startup |
   | Add Reactions | mark messages it has transmitted |
   | Create Public Threads | only if you want per-node threads |
   | Send Messages in Threads | same |
   | Manage Roles | only if you use `paired_role_name` |

4. Copy the URL at the bottom, open it, pick your server, authorise

The bot appears in your member list, offline for now.

## 4. Find your channel ID

1. Discord → **Settings** (the gear) → **Advanced** → turn on **Developer Mode**
2. Right-click your `#mesh` channel in the channel list → **Copy Channel ID**

Right-click the **channel**, not the category heading above it. Both give you a
19-digit number and only one of them works.

## 5. Install the plugin

1. Build the package, or download it from the repository's releases:

   ```bash
   ./build.sh          # produces discord-bridge-<version>.meshplugin
   ```

2. Open MeshPulse in your browser → **Config → Plugins → Install Plugin**
3. Select the `.meshplugin` file
4. Press **Enable**. It takes a few seconds — the mapper installs `discord.py`
5. Refresh the page, then open the plugin's **Settings**
6. Paste the **token** and the **channel ID**. Leave everything else alone

## 6. Check it works

| Do this | Expect |
|---|---|
| Type anything in `#mesh` | the bot adds a 📡 reaction |
| Type `!mesh status` | 🟢 online, with counters |
| Type in the MeshPulse chat window | it appears in `#mesh` marked 🖥️ |
| Wait for a neighbour's radio | their message appears in `#mesh` |

The last one needs somebody else on the mesh. With a single radio you can fake
one instead: turn on `simulate_enabled` in the settings and run

```
!mesh simulate !abcd1234 hello from the field
```

Turn it off again afterwards — while it is on, anyone in the channel can forge
traffic that appears to come from any node.

---

## Everyday use

Everything the radio hears lands in your one channel, like this:

```
📡 Kuba !a1b2c3d4: heading down now
```

Anything you type there is transmitted to the whole mesh, tagged with your
name. From your phone, away from the house, that is the whole point: you can
see what is happening on the mesh and say something back, as long as the
machine at home is running.

**Talking to one node privately.** Either send one message:

```
!mesh dm !a1b2c3d4 are you there?
```

or give that node a thread of its own:

```
!mesh open !a1b2c3d4
```

From then on everything you write in that thread goes to that node alone, and
its replies arrive there rather than in the main channel. Threads are opened
only when you ask. If you would rather every node be given one automatically,
turn on `thread_per_node` — useful when several people are on the mesh, noisy
when it is mostly you.

**Useful commands**

```
!mesh status    connection state and counters
!mesh nodes     nodes your radio can currently see
!mesh threads   conversations you have opened
!mesh here      the current channel's ID
!mesh           everything else
```

---

## If something does not work

Read the log on the machine running MeshPulse:

```bash
sudo journalctl -u meshpulse --no-pager | grep -i "discord\|PLUGIN" | tail -20
```

The messages say what is wrong in plain words. The usual causes:

| What you see | What it means |
|---|---|
| Bot stays offline | `MESSAGE CONTENT INTENT` is off, or the token is wrong |
| `Cannot resolve channel` | you copied a category ID, or the bot cannot see that channel |
| Bot online, relays nothing | check `discord_to_mesh` and `mesh_to_discord` are on |
| No `[PLUGIN:...]` lines at all | the plugin is not enabled |
| Settings look out of date | refresh the browser page |

## Two things worth knowing before you rely on it

**Your machine is the bridge.** If it is asleep or offline, nothing is relayed
in either direction — Discord will look calm whether the mesh is quiet or your
Raspberry Pi is unplugged.

**There are no delivery receipts.** Meshtastic transmits and moves on. A
message to a radio that is out of range is lost silently, and nothing in
Discord will tell you so.

## Inviting other people

If you want friends in your bridge channel, just invite them to your server.
They can read the mesh and write to it immediately — they do not need a radio,
a bot or MeshPulse of their own.

They share your radio, though. Everything they send leaves through your node,
distinguished only by the name tag, and they can see every conversation in the
channel. That is fine among friends and wrong for strangers.
