# Discord Bridge for MeshPulse

A [MeshPulse](https://github.com/maxg10/meshpulse) plugin that bridges text
between a Meshtastic LoRa mesh and Discord, in both directions, so a person on
a radio in the field and a person on Discord can hold an ordinary conversation
without either of them learning the other's tool.

```
 mesh node                 Raspberry Pi                   Discord
    📻  ────── LoRa ──────►  📡 MeshPulse ──── plugin ────►  💬
    📻  ◄───── LoRa ───────  📡  + radio  ◄─── plugin ─────  💬
```

The plugin drives the radio through MeshPulse itself. There is no MQTT broker,
no firmware-side JSON support and no downlink channel to configure — which also
means it works on nRF52 hardware, where the MQTT/JSON path is unavailable.

---

## What it does

**Bidirectional relay.** Mesh traffic appears in Discord; Discord messages are
transmitted over the air, tagged with the sender's name.

**One thread per node.** The first time a node transmits, the plugin opens a
Discord thread named after it. Every later message from that node lands in the
same thread, and anything written inside the thread is transmitted as a direct
message to that node alone. The parent channel stays broadcast.

**Proof-of-possession pairing.** A Discord account claims a mesh node by
transmitting a one-time code from it. The bot issues the code over Discord; the
radio sends it back over the air. Possession of the hardware is the credential —
the only thing that cannot be forged from a keyboard.

**Operational commands.** Status, node list, open conversations, ad-hoc direct
messages, pairing, and a packet injector for testing without a second radio.

---

## Design notes

These are the decisions that were not obvious, and why they went the way they
did. Each is a constraint discovered in MeshPulse or Meshtastic rather than a
preference.

### The plugin owns a thread and an event loop

MeshPulse dispatches hooks from the radio reader thread via `asyncio.run()`, so
each hook body executes in a throwaway event loop that dies immediately after.
A Discord gateway client has to live for hours. The plugin therefore starts its
own thread with a private loop, keeps the client there, and hands packets
across with `loop.call_soon_threadsafe()`.

### Three independent loop guards

Without them a message would be transmitted, re-heard by the local radio,
relayed back to Discord and transmitted again, until the duty cycle is
saturated.

1. **Discord side** — the bot ignores its own messages, other bots, and any
   channel outside the configured one.
2. **Mesh side** — packets whose sender is the local node are discarded.
3. **Content fingerprint** — a normalised SHA-1 of the payload is recorded
   *before* transmitting. The same content returning within `echo_ttl` is
   dropped and the fingerprint consumed, so a genuine later repeat of the same
   phrase still passes.

### Splitting on bytes, not characters

`TEXT_MESSAGE_APP` carries roughly 200 bytes. Polish diacritics are two bytes
each in UTF-8, so a character-based split truncates mid-codepoint and produces
mojibake on the receiving radio. The splitter measures encoded length and
breaks on word boundaries.

### Pairing codes must arrive as direct messages

Meshtastic firmware 2.5 and later encrypts direct messages to the recipient's
public key, so a code sent as a DM cannot be lifted off the air by a bystander
and redeemed first. Codes broadcast in the clear are refused with an
explanatory reply rather than silently accepted. The code alphabet omits
`0 O 1 I L`, because codes get retyped from small radio displays.

### Configuration is swapped in place

`on_config_update` replaces `self.config` and restarts the bridge thread only
when credentials actually change, so editing an unrelated setting does not
drop the Discord connection.

### Graceful degradation over hard failure

The `SERVER MEMBERS INTENT` is privileged; if it is disabled in the developer
portal Discord refuses the login outright and the entire bridge dies, including
the parts that never needed it. The plugin catches that specific rejection,
reconnects without the intent, and logs what to enable. Losing the join
greeting is a far smaller failure than losing the bridge.

---

## Installation

Requires MeshPulse 2.3.0+ (developed against 2.5.1, verified against 2.6.0) and
Python 3.9+. `discord.py>=2.4` is installed by the mapper on enable.

### 1. Discord application

At <https://discord.com/developers/applications>:

- **New Application** → **Bot** → enable `MESSAGE CONTENT INTENT`
  (and `SERVER MEMBERS INTENT` if you want new members greeted) → **Save**
- **Reset Token** → copy it
- **OAuth2 → URL Generator** → scope `bot`, then these permissions:

  `View Channels` · `Send Messages` · `Read Message History` ·
  `Add Reactions` · `Create Public Threads` · `Send Messages in Threads` ·
  `Manage Roles` *(only if using `paired_role_name`)*

- Open the generated URL and authorise the bot on your server

If you use `Manage Roles`, position the bot's role above the role it grants.

### 2. Build and install

```bash
./build.sh                      # produces discord-bridge-<version>.meshplugin
```

In MeshPulse: **Config → Plugins → Install Plugin**, select the package,
**Enable**, then open **Settings** and provide the bot token and the channel ID.

---

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `discord_token` | — | bot token |
| `discord_channel_id` | — | target channel ID, digits only (stored as a string: snowflakes exceed `Number.MAX_SAFE_INTEGER`) |
| `mesh_to_discord` / `discord_to_mesh` | `true` | enable each direction |
| `mesh_channel_index` | `0` | Meshtastic channel used for transmissions |
| `mesh_channel_filter` | `all` | listen on `all` channels or one index |
| `forward_dms` | `true` | relay direct messages addressed to this node |
| `dm_target` | — | when set, parent-channel messages become DMs to this node |
| `name_prefix` | `true` | prefix outbound text with `[name]` |
| `thread_per_node` | `true` | one Discord thread per mesh node |
| `thread_scope` | `all` | `all` senders, or `dm` only |
| `thread_archive_hours` | `24` | silence before Discord archives a thread |
| `thread_name_template` | `{name} ({id})` | thread title |
| `pairing_enabled` | `true` | allow accounts to claim nodes |
| `pair_code_ttl_minutes` | `15` | code lifetime |
| `pair_require_dm` | `true` | require the code to arrive encrypted |
| `greet_new_members` | `true` | DM a code on join (needs the members intent) |
| `paired_role_name` | — | role granted on successful pairing |
| `simulate_enabled` | `false` | enable the packet injector |
| `command_prefix` | `!mesh` | command prefix |
| `use_embed` | `false` | render inbound messages as embeds |
| `allow_bots` | `false` | relay other bots (removes one loop guard) |
| `max_payload` / `max_chunks` | `200` / `4` | transmission size limits |
| `tx_interval` | `3` | seconds between transmissions (duty cycle) |
| `echo_ttl` | `180` | echo-detection window in seconds |
| `log_to_db` | `true` | persist relayed messages |

---

## Commands

| Command | Effect |
|---|---|
| `!mesh status` | connection state, counters, uptime, conversations, paired accounts |
| `!mesh nodes` | nodes currently visible to the radio |
| `!mesh threads` | open conversations and links to their threads |
| `!mesh open !abcd1234` | open a thread for a node that has not spoken yet |
| `!mesh dm !abcd1234 text` | one-off direct message |
| `!mesh pair` / `whoami` / `unpair` | manage the account-to-node binding |
| `!mesh simulate [dm] !abcd1234 text` | inject a synthetic packet |
| `!mesh here` | print the current channel ID |

---

## Tests

55 integration tests run against the **real** `MeshPlugin` base class, not a
stub, with `discord.py` replaced by test doubles. Radio-thread hook dispatch is
reproduced faithfully, including the throwaway-event-loop behaviour.

```bash
git clone https://github.com/maxg10/meshpulse ../meshpulse
python3 tests/test_threads.py     # 22 tests — thread routing
python3 tests/test_pairing.py     # 33 tests — pairing and its failure modes
```

Set `MESHPULSE_PATH` if the checkout lives elsewhere.

Coverage includes bridge-thread lifecycle, cross-thread hand-off, echo
suppression with genuine-repeat pass-through, local-node rejection, byte-exact
UTF-8 splitting, thread creation and reuse, archived-thread reopening,
persistence across restart, permission-denied fallback, single-use and expiring
codes, rebinding on both sides of the relation, refusal of codes sent in the
clear, and clean shutdown with no orphaned threads.

---

## Limitations

These follow from radio physics and cryptography, not from this code.

- **The mesh sees one transmitter, not people.** Every Discord participant
  shares the single attached radio and is distinguished only by the name tag.
- **No delivery receipts.** A message to a node that is out of range is lost
  silently.
- **A central bridge cannot mirror other people's private conversations.**
  Firmware 2.5+ encrypts direct messages to the recipient's key; this node
  relays such packets without being able to read them.
- **Messages composed in the MeshPulse web chat do not reach Discord.**
  MeshPulse's send path does not notify plugins, so the bridge never sees them.
  The reverse direction is unaffected.
- **MeshPulse has no authentication** and assumes a trusted LAN. Do not expose
  it to the internet.

---

## Repository layout

```
backend/main.py       plugin implementation
frontend/             status panel rendered on the MeshPulse map
plugin.json           manifest, configuration schema, compatibility range
tests/                integration suites
docs/INSTRUKCJA.md    end-user manual (Polish)
build.sh              packages the .meshplugin archive
```

## License

GPL-3.0, matching MeshPulse.
