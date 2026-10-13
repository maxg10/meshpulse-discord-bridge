# Przewodnik · Guide

Pełny przewodnik po mostku Meshtastic ↔ Discord — od zera do działającej
instalacji.

🇵🇱 **[Wersja polska](#wersja-polska)** — zaczyna się tutaj
🇬🇧 **[English version](#english-version)** — second half of this file

---

<a name="wersja-polska"></a>

# 🇵🇱 Wersja polska

## Spis treści

1. [Co to robi](#1-co-to-robi)
2. [Czego potrzebujesz](#2-czego-potrzebujesz)
3. [Serwer na Discordzie](#3-serwer-na-discordzie)
4. [Bot](#4-bot)
5. [Instalacja wtyczki](#5-instalacja-wtyczki)
6. [Sprawdzenie](#6-sprawdzenie)
7. [Codzienne użycie](#7-codzienne-użycie)
8. [Komendy](#8-komendy)
9. [Ustawienia](#9-ustawienia)
10. [Kiedy coś nie działa](#10-kiedy-coś-nie-działa)
11. [Ograniczenia](#11-ograniczenia)

---

## 1. Co to robi

Masz radio Meshtastic podłączone do komputera, na którym chodzi MeshPulse. Ta
wtyczka wrzuca na Discorda wszystko, co radio usłyszy, i nadaje w eter
wszystko, co napiszesz na kanale.

```
   ktoś z radiem                 Twój komputer                Discord
   w terenie                     + radio
      📻  ──────── LoRa ────────►  📡  ──── internet ────►  💬  Ty, z telefonu
      📻  ◄─────── LoRa ─────────  📡  ◄─── internet ─────  💬
```

Wychodzisz z domu, komputer zostaje włączony — i z telefonu widzisz, co dzieje
się na siatce, oraz możesz się odezwać. To jest cały sens.

Wszystko trafia do **jednego kanału**:

```
📡 Kuba !a1b2c3d4: schodzę ze szczytu
📡 Ola  !b2c3d4e5: jestem na miejscu
```

Nic nie jest niczyje wspólne — serwer jest Twój, bot jest Twój, mostek rozmawia
wyłącznie z Twoim radiem.

## 2. Czego potrzebujesz

- radio Meshtastic podłączone do komputera z **MeshPulse 2.3.0** lub nowszym
- ten komputer **włączony**, kiedy mostek ma działać — to on nadaje za Ciebie
- konto na Discordzie

## 3. Serwer na Discordzie

1. W Discordzie kliknij **+** na dole listy serwerów po lewej
2. **Stwórz własny** → **Dla mnie i znajomych** → nazwij jak chcesz
3. Zrób jeden kanał tekstowy, np. `#mesh`

Jeden kanał wystarczy. Wszystko, co radio usłyszy, ląduje tam, a wszystko, co
tam napiszesz, idzie w eter.

## 4. Bot

Wejdź na `discord.com/developers/applications`, zalogowany tym samym kontem.

### 4.1. Utworzenie

1. **New Application** → nazwa → **Create**
2. Menu z lewej → **Bot**
3. Zjedź do **Privileged Gateway Intents** i włącz **MESSAGE CONTENT INTENT**

   > Bez tego bot dostaje puste wiadomości i nie przekaże niczego.

4. **Save Changes**
5. Na górze **Reset Token** → **Copy**

> ⚠️ Token pokazuje się **raz**. To klucz do bota — kto go ma, może nim pisać,
> kasować i rozdawać role. Zgubisz albo wkleisz publicznie → zresetuj, stary
> natychmiast przestaje działać.

### 4.2. Wpuszczenie na serwer

1. **OAuth2** → **URL Generator**
2. W **Scopes** zaznacz `bot` — dopiero wtedy pojawi się lista uprawnień
3. W **Bot Permissions** zaznacz:

   | Uprawnienie | Po co |
   |---|---|
   | View Channels | widzieć kanał |
   | Send Messages | pisać |
   | Read Message History | odczytać kontekst przy starcie |
   | Add Reactions | znacznik 📡 potwierdzający nadanie |
   | Create Public Threads | tylko jeśli chcesz wątków |
   | Send Messages in Threads | jw. |
   | Manage Roles | tylko przy `paired_role_name` |

4. Skopiuj link z dołu strony, otwórz, wybierz serwer, **Autoryzuj**

> Przy `Manage Roles`: w ustawieniach serwera przesuń rolę bota **wyżej** niż
> tę, którą ma nadawać. Inaczej Discord odmówi.

### 4.3. Numer kanału

1. Discord → zębatka → **Zaawansowane** → włącz **Tryb dewelopera**
2. Prawy klik na kanale `#mesh` → **Kopiuj identyfikator kanału**

> ⚠️ Kliknij w **kanał**, nie w kategorię nad nim. Oba dają 19 cyfr, działa
> tylko jeden.

## 5. Instalacja wtyczki

Zbuduj paczkę albo pobierz gotową:

```bash
./build.sh          # tworzy discord-bridge-<wersja>.meshplugin
```

Potem w MeshPulse:

1. **Config → Plugins → Install Plugin** → wskaż plik `.meshplugin`
2. **Enable** — potrwa kilkanaście sekund, wtyczka dociąga `discord.py`
3. **F5** — odśwież stronę, inaczej zobaczysz stary zestaw ustawień
4. Rozwiń ⚙️ **Settings** → wklej **token** i **ID kanału**

Reszty nie ruszaj. Domyślne wartości są dobrane pod zwykłe użycie.

## 6. Sprawdzenie

| Zrób to | Powinno się stać |
|---|---|
| napisz cokolwiek na `#mesh` | bot dokleja reakcję 📡 |
| `!mesh status` | 🟢 online, liczniki |
| napisz w oknie czatu MeshPulse | pojawi się na `#mesh` ze znacznikiem 🖥️ |
| poczekaj na sąsiada z radiem | jego wiadomość wpada na `#mesh` |

Ostatni punkt wymaga kogoś innego na siatce. Mając jedno radio możesz go udać:
włącz `simulate_enabled` w ustawieniach i wpisz

```
!mesh simulate !abcd1234 czesc z terenu
```

**Wyłącz to potem.** Z włączonym każdy na kanale może podszyć się pod dowolny
węzeł.

## 7. Codzienne użycie

**Do wszystkich** — pisz na kanale. Leci rozgłoszeniowo, podpisane Twoją nazwą.

**Do jednej osoby** — jednorazowo:

```
!mesh dm !a1b2c3d4 jesteś na miejscu?
```

albo na stałe, zakładając jej wątek:

```
!mesh open !a1b2c3d4
```

Od tej chwili wszystko, co napiszesz w tym wątku, idzie tylko do tego węzła, a
jego odpowiedzi lądują tam zamiast w kanale głównym. **Wątki powstają tylko na
Twoje żądanie.** Chcesz automatycznie dla każdego węzła — włącz
`thread_per_node`; ma to sens, gdy na siatce jest kilka osób.

### Znaczniki

| Symbol | Znaczenie |
|---|---|
| 📡 | bot przyjął Twoją wiadomość i nadał ją |
| 🔒 | przychodząca była prywatna, nie rozgłoszeniowa |
| 🖥️ | napisana w oknie czatu MeshPulse |
| ✂️ | była za długa i poszła w kawałkach |

## 8. Komendy

Działają na kanale mostka i w każdym wątku pod nim.

| Komenda | Co robi |
|---|---|
| `!mesh status` | stan połączenia, liczniki, czas pracy |
| `!mesh diag` | dlaczego nic się nie przekazuje — trasa nadawcza, zgodność kanału, ostatni błąd |
| `!mesh nodes` | węzły, które radio aktualnie widzi |
| `!mesh threads` | otwarte rozmowy |
| `!mesh open !abcd1234` | zakłada wątek dla węzła |
| `!mesh dm !abcd1234 treść` | jednorazowa wiadomość prywatna |
| `!mesh pair` / `whoami` / `unpair` | powiązanie konta z radiem |
| `!mesh simulate [dm] !abcd1234 treść` | udawany pakiet, do testów |
| `!mesh here` | ID bieżącego kanału |

### Parowanie

Wiąże konto Discord z konkretnym radiem — **w sposób udowodniony**. Bot
przysyła na priv kod, Ty wysyłasz go ze swojego radia jako wiadomość prywatną.
Posiadanie sprzętu jest jedyną rzeczą, której nie da się podrobić z klawiatury.

Kod musi przyjść prywatnie: od firmware 2.5 takie wiadomości są szyfrowane
kluczem odbiorcy, więc nikt w zasięgu nie podsłucha kodu i nie przejmie konta.
Kod jest jednorazowy i wygasa po 15 minutach.

W pojedynczej instalacji parowanie nie jest do niczego potrzebne — przydaje się
dopiero, gdy wpuszczasz na serwer inne osoby.

## 9. Ustawienia

**Config → Plugins → Discord Bridge → ⚙️ Settings**

### Podstawa

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `discord_token` | — | token bota |
| `discord_channel_id` | — | ID kanału, same cyfry |
| `mesh_to_discord` | ✅ | przekazuj z radia na Discord |
| `discord_to_mesh` | ✅ | przekazuj z Discorda w eter |

### Siatka

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `mesh_channel_index` | `0` | na którym kanale Meshtastic nadawać |
| `mesh_channel_filter` | `all` | którego słuchać: `all` albo numer |
| `forward_dms` | ✅ | przekazuj wiadomości prywatne do Twojego węzła |
| `relay_web_chat` | ✅ | pokazuj na Discordzie to, co piszesz w oknie MeshPulse |
| `echo_to_meshpulse` | ✅ | pokazuj w oknie MeshPulse to, co wysłano z Discorda |
| `dm_target` | puste | numer węzła — wtedy kanał główny pisze prywatnie tylko do niego |
| `name_prefix` | ✅ | dopisuj `[Nazwa]` przed treścią |

### Wątki

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `thread_per_node` | ❌ | automatyczny wątek dla każdego węzła |
| `thread_scope` | `all` | `all` = każdy nadawca, `dm` = tylko prywatne |
| `thread_archive_hours` | `24` | po ilu godzinach ciszy Discord chowa wątek |
| `thread_name_template` | `{name} ({id})` | tytuł wątku |

### Parowanie

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `pairing_enabled` | ✅ | pozwalaj parować |
| `pair_code_ttl_minutes` | `15` | ważność kodu |
| `pair_require_dm` | ✅ | kod musi przyjść zaszyfrowany — **nie wyłączaj bez potrzeby** |
| `greet_new_members` | ✅ | kod dla nowych na serwerze *(wymaga SERVER MEMBERS INTENT)* |
| `paired_role_name` | puste | rola po sparowaniu *(wymaga Manage Roles)* |

### Zaawansowane

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `simulate_enabled` | ❌ | komenda `simulate` — **trzymaj wyłączone na co dzień** |
| `command_prefix` | `!mesh` | przedrostek komend |
| `use_embed` | ❌ | przychodzące jako embed zamiast tekstu |
| `allow_bots` | ❌ | przekazuj inne boty — **zdejmuje jedno zabezpieczenie pętli** |
| `max_payload` / `max_chunks` | `200` / `4` | limity rozmiaru nadania |
| `tx_interval` | `3` | odstęp między nadaniami w sekundach |
| `echo_ttl` | `180` | okno wykrywania własnego echa |
| `log_to_db` | ✅ | zapisuj przekazane wiadomości |

## 10. Kiedy coś nie działa

Zacznij od **`!mesh diag`** na kanale. Wypisuje trasę nadawczą, rozpoznany węzeł
własny, zgodność ID kanału, stan kierunków i ostatni błąd nadawania — czyli
wszystko, co zwykle wymaga zaglądania do logów.

Log na komputerze z MeshPulse:

```bash
sudo journalctl -u meshpulse --no-pager | grep -i "discord\|PLUGIN" | tail -20
```

| Objaw | Przyczyna |
|---|---|
| bot szary, nie wchodzi | brak `MESSAGE CONTENT INTENT` albo zły token |
| `Cannot resolve channel` | ID kategorii zamiast kanału, albo bot nie widzi kanału |
| bot online, nic nie przekazuje | sprawdź `discord_to_mesh` i `mesh_to_discord` |
| wiadomości w kanale zamiast w wątku | brak `Create Public Threads` |
| rola nie zostaje nadana | brak `Manage Roles` albo rola bota za nisko |
| brak linii `[PLUGIN:...]` | wtyczka nie jest włączona |
| nowych ustawień nie widać | stara zakładka — **F5** |

### Nadaje, ale nic nie dochodzi

Jeśli `diag` pokazuje rosnący licznik i brak błędów, a drugie radio milczy, to
problem jest radiowy, nie programowy. Po kolei:

1. **Czy wiadomość z okna czatu MeshPulse też nie dochodzi?** Jeśli nie — mostek
   jest niewinny, sprawdzaj radio
2. **Czy oba mają anteny?** Nadawanie bez anteny daje fatalny wynik i potrafi
   uszkodzić stopień mocy
3. **Czy nie leżą obok siebie?** Odbiornik LoRa jest zrobiony na sygnały rzędu
   −130 dBm. Nadajnik pół metra dalej przesterowuje mu wejście. Rozsuń na kilka
   metrów
4. **Czy zgadzają się: kanał, hasło (PSK), preset LoRa i region?** Wszystkie
   cztery, co do jednego. Inaczej pakiet dociera i znika bez śladu

## 11. Ograniczenia

To fizyka radia i kryptografia, nie niedoróbki.

**Siatka widzi jeden nadajnik, nie ludzi.** Wszyscy piszący na Discordzie
wychodzą w eter przez to jedno radio, rozróżniani tylko dopiskiem `[Nazwa]`.

**Nie ma potwierdzeń doręczenia.** Wiadomość do radia poza zasięgiem przepada
po cichu i nic Ci o tym nie powie.

**Twój komputer jest mostkiem.** Śpi albo jest offline → nic nie przechodzi w
żadną stronę, a Discord wygląda tak samo jak przy ciszy na siatce.

**Centralny mostek nie odczyta cudzych rozmów prywatnych.** Od firmware 2.5
wiadomości prywatne są szyfrowane kluczem odbiorcy.

**MeshPulse nie ma logowania** i zakłada zaufaną sieć lokalną. Nie wystawiaj go
na internet.

### Zapraszanie innych

Chcesz znajomych na kanale — po prostu zaproś ich na serwer. Czytają i piszą od
razu, bez radia i bez MeshPulse.

Dzielą jednak Twoje radio: wszystko wychodzi przez Twój węzeł i widzą każdą
rozmowę na kanale. Dobre wśród znajomych, złe wobec obcych.

---
---

<a name="english-version"></a>

# 🇬🇧 English version

## Contents

1. [What it does](#1-what-it-does)
2. [What you need](#2-what-you-need)
3. [A Discord server](#3-a-discord-server)
4. [The bot](#4-the-bot)
5. [Installing the plugin](#5-installing-the-plugin)
6. [Checking it works](#6-checking-it-works)
7. [Everyday use](#7-everyday-use)
8. [Commands](#8-commands)
9. [Configuration](#9-configuration)
10. [When something is wrong](#10-when-something-is-wrong)
11. [Limitations](#11-limitations)

---

## 1. What it does

You have a Meshtastic radio attached to a machine running MeshPulse. This
plugin posts everything the radio hears into Discord, and transmits everything
written in the channel over the air.

```
 someone in the field          your machine                  Discord
      📻  ──────── LoRa ────────►  📡  ──── internet ────►  💬  you, on a phone
      📻  ◄─────── LoRa ─────────  📡  ◄─── internet ─────  💬
```

Leave the house with the machine running, and from your phone you can see what
is happening on the mesh and say something back. That is the whole point.

Everything arrives in **one channel**:

```
📡 Kuba !a1b2c3d4: heading down now
📡 Ola  !b2c3d4e5: arrived
```

Nothing here is shared with anyone. The server is yours, the bot is yours, and
the bridge talks only to your radio.

## 2. What you need

- a Meshtastic radio attached to a machine running **MeshPulse 2.3.0** or newer
- that machine **online** whenever the bridge should work — it transmits on your
  behalf
- a Discord account

## 3. A Discord server

1. Click the **+** at the bottom of the server list on the left
2. **Create My Own** → **For me and my friends** → name it
3. Make one text channel, `#mesh` is a reasonable name

One channel is enough: everything the radio hears arrives there, and anything
you type there goes out over the air.

## 4. The bot

Go to `discord.com/developers/applications`, signed in with the same account.

### 4.1. Create it

1. **New Application** → name it → **Create**
2. **Bot** in the left-hand menu
3. Under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT**

   > Without it the bot receives empty messages and can relay nothing.

4. **Save Changes**
5. At the top, **Reset Token** → **Copy**

> ⚠️ The token is shown once. It is the key to the bot: anyone holding it can
> act as it. If you lose it or paste it publicly, reset it — the old one stops
> working immediately.

### 4.2. Invite it

1. **OAuth2** → **URL Generator**
2. Under **Scopes**, tick `bot`. The permission list appears only then
3. Under **Bot Permissions**:

   | Permission | Why |
   |---|---|
   | View Channels | see the bridge channel |
   | Send Messages | post what the radio hears |
   | Read Message History | read context on startup |
   | Add Reactions | mark messages it has transmitted |
   | Create Public Threads | only if you want threads |
   | Send Messages in Threads | same |
   | Manage Roles | only with `paired_role_name` |

4. Open the generated URL, pick your server, authorise

> With `Manage Roles`, position the bot's role above the role it grants.

### 4.3. The channel ID

1. Discord → **Settings** → **Advanced** → turn on **Developer Mode**
2. Right-click your `#mesh` channel → **Copy Channel ID**

> ⚠️ Right-click the **channel**, not the category heading above it. Both give
> a 19-digit number and only one works.

## 5. Installing the plugin

```bash
./build.sh          # produces discord-bridge-<version>.meshplugin
```

In MeshPulse:

1. **Config → Plugins → Install Plugin** → select the `.meshplugin` file
2. **Enable** — a few seconds, the mapper installs `discord.py`
3. **Refresh the page**, or you will see the previous settings
4. Open ⚙️ **Settings** → paste the **token** and the **channel ID**

Leave everything else alone. The defaults suit ordinary use.

## 6. Checking it works

| Do this | Expect |
|---|---|
| type anything in `#mesh` | the bot adds a 📡 reaction |
| `!mesh status` | 🟢 online, with counters |
| type in the MeshPulse chat window | it appears in `#mesh` marked 🖥️ |
| wait for a neighbour's radio | their message appears in `#mesh` |

The last needs somebody else on the mesh. With one radio you can fake one: turn
on `simulate_enabled` and run

```
!mesh simulate !abcd1234 hello from the field
```

**Turn it off afterwards.** While it is on, anyone in the channel can forge
traffic that appears to come from any node.

## 7. Everyday use

**To everyone** — type in the channel. It is broadcast, tagged with your name.

**To one node** — once:

```
!mesh dm !a1b2c3d4 are you there?
```

or permanently, by giving it a thread:

```
!mesh open !a1b2c3d4
```

Everything you write in that thread then goes to that node alone, and its
replies arrive there rather than in the main channel. **Threads are opened only
when you ask.** Set `thread_per_node` to open one for every node automatically —
worth it when several people share the mesh.

### Markers

| Symbol | Meaning |
|---|---|
| 📡 | the bot accepted and transmitted your message |
| 🔒 | the incoming message was direct, not broadcast |
| 🖥️ | composed in the MeshPulse chat window |
| ✂️ | too long, sent in several packets |

## 8. Commands

They work in the bridge channel and in any thread under it.

| Command | Effect |
|---|---|
| `!mesh status` | connection state, counters, uptime |
| `!mesh diag` | why nothing is relayed — transmit route, channel match, last error |
| `!mesh nodes` | nodes the radio can currently see |
| `!mesh threads` | open conversations |
| `!mesh open !abcd1234` | open a thread for a node |
| `!mesh dm !abcd1234 text` | one-off direct message |
| `!mesh pair` / `whoami` / `unpair` | manage the account-to-node binding |
| `!mesh simulate [dm] !abcd1234 text` | inject a synthetic packet |
| `!mesh here` | print the current channel ID |

### Pairing

Binds a Discord account to a specific radio, **by proof rather than by claim**.
The bot DMs a one-time code; you transmit it back from your radio as a direct
message. Possession of the hardware is the only credential that cannot be
forged from a keyboard.

The code must arrive as a direct message: firmware 2.5 and later encrypts those
to the recipient's key, so a bystander cannot lift the code off the air and
claim the account first. Codes are single-use and expire after 15 minutes.

On a single-operator install pairing is not needed at all. It earns its place
once other people join your server.

## 9. Configuration

**Config → Plugins → Discord Bridge → ⚙️ Settings**

| Key | Default | Purpose |
|---|---|---|
| `discord_token` | — | bot token |
| `discord_channel_id` | — | target channel ID, digits only |
| `mesh_to_discord` / `discord_to_mesh` | `true` | enable each direction |
| `mesh_channel_index` | `0` | Meshtastic channel used for transmissions |
| `mesh_channel_filter` | `all` | listen on `all` channels or one index |
| `forward_dms` | `true` | relay direct messages addressed to this node |
| `relay_web_chat` | `true` | mirror the MeshPulse chat window into Discord |
| `echo_to_meshpulse` | `true` | show Discord traffic in the MeshPulse chat window |
| `dm_target` | — | when set, channel messages become DMs to this node |
| `name_prefix` | `true` | prefix outbound text with `[name]` |
| `thread_per_node` | `false` | open a thread per node automatically |
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

## 10. When something is wrong

Start with **`!mesh diag`** in the channel. It reports the transmit route, the
resolved local node, whether the channel ID matches, the direction switches and
the last transmit error — everything that otherwise means reading logs.

On the machine running MeshPulse:

```bash
sudo journalctl -u meshpulse --no-pager | grep -i "discord\|PLUGIN" | tail -20
```

| Symptom | Cause |
|---|---|
| bot stays offline | `MESSAGE CONTENT INTENT` is off, or the token is wrong |
| `Cannot resolve channel` | a category ID, or the bot cannot see that channel |
| online but relays nothing | check `discord_to_mesh` and `mesh_to_discord` |
| messages in the channel, not a thread | `Create Public Threads` is missing |
| the role is never granted | `Manage Roles` missing, or the bot's role sits too low |
| no `[PLUGIN:...]` lines at all | the plugin is not enabled |
| settings look out of date | refresh the page |

### It transmits, but nothing arrives

If `diag` shows the counter rising with no errors and the other radio stays
silent, the fault is in the radio layer rather than the software:

1. **Does a message from the MeshPulse chat window also fail to arrive?** If so,
   the bridge is not involved at all
2. **Do both have antennas?** Transmitting without one performs terribly and can
   damage the power stage
3. **Are they sitting next to each other?** A LoRa receiver is built for signals
   around −130 dBm; a transmitter half a metre away overloads its front end.
   Move them several metres apart
4. **Do the channel, PSK, LoRa preset and region all match?** All four, exactly.
   Otherwise packets arrive and are discarded without a trace

## 11. Limitations

These follow from radio physics and cryptography, not from this code.

**The mesh sees one transmitter, not people.** Every Discord participant shares
the single attached radio, distinguished only by the name tag.

**No delivery receipts.** A message to a radio out of range is lost silently.

**Your machine is the bridge.** Asleep or offline, nothing is relayed either
way — and Discord looks the same whether the mesh is quiet or your machine is
unplugged.

**A central bridge cannot mirror other people's private conversations.**
Firmware 2.5+ encrypts direct messages to the recipient's key.

**MeshPulse has no authentication** and assumes a trusted LAN. Do not expose it
to the internet.

### Inviting other people

Invite friends to your server and they can read and write to the mesh
immediately — no radio, no MeshPulse of their own.

They share your radio, though: everything they send leaves through your node,
and they can see every conversation in the channel. Fine among friends, wrong
for strangers.
