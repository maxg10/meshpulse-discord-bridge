# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The status panel registers through `api.panels` on MeshPulse 2.6.1 and
  newer, so it can be dragged and reordered like other plugin panels (2.8.0+)
  and moves into the Map Layers drawer on phones. Older cores still get the
  bottom-left Leaflet control.

## [1.0.0] — 2026-10-13

First release. Developed and verified against MeshPulse 2.5.1 through 2.9.0, on
a Raspberry Pi with a serial-attached radio.

### Added

- Bidirectional relay between a Meshtastic mesh and one Discord channel. Mesh
  traffic is posted to the channel; messages written there are transmitted over
  the air, tagged with the sender's name.
- Messages composed in the MeshPulse web chat are mirrored into Discord, and
  messages relayed from Discord appear in the MeshPulse chat window — so one
  conversation reads the same from a radio, from Discord, or from the mapper's
  own UI.
- Optional per-node threads. `open` gives a node a thread of its own: messages
  written there go to that node alone and its replies arrive there.
  `thread_per_node` opens one for every node automatically.
- Proof-of-possession pairing between Discord accounts and mesh nodes. The bot
  issues a short-lived single-use code; the node transmits it back. Codes must
  arrive as direct messages, which firmware 2.5+ encrypts to the recipient's
  key, so they cannot be lifted off the air.
- Commands: `status`, `diag`, `nodes`, `threads`, `open`, `dm`, `pair`,
  `whoami`, `unpair`, `simulate`, `here`.
- Status panel on the MeshPulse map.
- 107 integration tests against the real `MeshPlugin` base class.
- Setup and usage guide in Polish and English.

### Notable problems solved during development

Each of these was found by reading the MeshPulse source or by testing on
hardware, and each was invisible from the outside.

- **The Discord client was placed in a per-hook event loop.** MeshPulse
  dispatches hooks from the radio thread through `asyncio.run()`, so that loop
  dies after one event while a gateway client must live for hours. The plugin
  now owns a thread and a private loop, with packets handed across by
  `call_soon_threadsafe`.
- **Transmissions were counted as successful when they had failed.** The
  mapper's `send_mesh_message` catches every exception from the underlying
  send, prints it, and returns normally, so a plugin cannot distinguish a
  delivered packet from one that never left the device. The bridge now drives
  the interface directly and lets errors propagate.
- **The local node id was only ever set by `on_connect`,** which never fires
  for a plugin enabled while the radio is already connected. The field stayed
  empty, silently disabling both the web-chat mirror and the own-transmission
  echo guard. It is now resolved from the mapper.
- **A disabled `SERVER MEMBERS INTENT` took the whole bridge down,** because
  Discord refuses the login outright when a privileged intent is unavailable.
  The plugin now detects that rejection and reconnects without the intent.
- **A refused login ended the supervisor permanently.** Discord also refuses
  logins it considers too frequent, which made a condition that clears itself
  in minutes look like a dead plugin. Refusals now back off and retry.
- **A TCP host carrying a port was passed unsplit** by the mapper's plugin send
  path, unlike its own. The bridge splits it, IPv6 included.
- **Database handles were opened per message** and crossed thread boundaries;
  one connection is now opened on the bridge thread and reused.
- **The echo-guard dictionary was written by two threads** without a lock.
- **Defensive handling wrapped a library signature that turned out to be
  unambiguous,** and was removed — it could only have hidden real errors.
