# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.0]

### Added

- Messages composed in the MeshPulse web chat are mirrored into Discord. They
  previously reached no hook at all — MeshPulse transmits them itself, and its
  send path notifies no plugin — so the bridge now watches `mapper.messages`,
  where that path leaves each message in the same shape a received one has.
  Direct messages are routed to the recipient's thread, broadcasts to the
  parent channel.
- `relay_web_chat`, `web_chat_poll_seconds` and `web_chat_label`.

### Notes

- Mirrored messages bypass the transmit queue: MeshPulse has already put them
  on the air, and relaying them again would duplicate them for every radio in
  range.
- The watcher cannot pick up the bridge's own Discord-to-mesh traffic, because
  `send_mesh_message` does not write to the store it watches.
- Everything present at startup is fingerprinted before the first poll, so a
  restart does not replay the backlog MeshPulse retains.

### Removed

- The corresponding entry from the README's limitations section.

## [1.2.2]

### Changed

- Login and channel-resolution failures now name the likely cause. The previous
  wording ("check the ID and permissions") gave the operator nothing to act on;
  the messages now distinguish a category ID from a channel ID, a missing
  invite, and each privileged intent by name.

## [1.2.1]

### Fixed

- A disabled `SERVER MEMBERS INTENT` no longer takes the whole bridge down.
  Requesting a privileged intent that is switched off in the developer portal
  makes Discord refuse the login outright, which disabled every feature rather
  than only the join greeting. The plugin now detects that specific rejection,
  reconnects without the intent, and logs what to enable.

### Added

- `simulate` command and its `simulate_enabled` guard: injects a synthetic
  packet at the point the radio reader normally delivers one, so threads,
  pairing and filtering can be exercised on a bench with a single node. Off by
  default, since it lets anyone in the channel forge traffic.

## [1.2.0]

### Added

- Proof-of-possession pairing between Discord accounts and mesh nodes. The bot
  issues a short-lived code; the node transmits it back. Codes are single-use,
  expire, and by default must arrive as a direct message so they cannot be
  lifted off the air — see `pair_require_dm`.
- Commands `pair`, `whoami` and `unpair`; optional role granted on success via
  `paired_role_name`; optional join greeting via `greet_new_members`.
- Bindings persist in SQLite and are restored on startup. One account maps to
  one node, and claiming either side releases the previous relation.

### Notes

- Pairing codes are consumed before relaying, so they never appear in a channel
  where somebody else could reuse them.

## [1.1.0]

### Added

- Per-node conversation threads: each mesh node is given its own Discord
  thread, so several people hold separate, continuous one-to-one conversations
  instead of sharing a single channel. Controlled by `thread_per_node`.
- `thread_scope` selects whether every sender gets a thread or only direct
  messages do; broadcasts can be left in the parent channel.
- `thread_archive_hours` and `thread_name_template` for thread presentation.
- Thread mappings are persisted in SQLite and restored on restart, so a
  conversation keeps its thread across reboots and plugin reloads.
- Archived threads are reopened automatically when the conversation resumes.
- Commands `threads` (list open conversations) and `open !nodeid` (start one).

### Changed

- Messages written inside a node's thread are transmitted as direct messages to
  that node; the parent channel keeps its previous broadcast behaviour.
- The plugin database is now opened regardless of `log_to_db`, which only gates
  message logging. Thread mappings must survive with logging switched off.
- Status report and help text reflect the active conversation model.

### Notes

- The bot needs two additional Discord permissions: **Create Public Threads**
  and **Send Messages in Threads**. Without them the plugin logs a explicit
  hint and falls back to posting in the parent channel.

## [1.0.0]

### Added

- Bidirectional text bridge between a Meshtastic mesh and a Discord channel.
- Three-layer loop prevention: Discord identity filtering, local-node packet
  rejection, and a fingerprint-based echo guard with a configurable window.
- Byte-accurate UTF-8 payload splitting with a configurable packet budget and
  split ceiling.
- Transmit pacing via `tx_interval` to protect the duty cycle.
- In-channel commands: `status`, `nodes`, `dm`, `here`.
- Optional SQLite log of bridged traffic.
- Map status panel driven by a plugin WebSocket channel.
- Automatic reconnection with capped exponential backoff; terminal failures
  (invalid token, missing intent, unresolvable channel) stop retrying and
  surface in the UI.
