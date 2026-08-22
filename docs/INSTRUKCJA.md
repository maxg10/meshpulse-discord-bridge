# Mostek Meshtastic ↔ Discord

Wtyczka do MeshPulse. Łączy siatkę radiową Meshtastic z kanałem na Discordzie tak,
żeby dwie osoby mogły rozmawiać normalnie — jedna przez radio, druga przez
przeglądarkę — i żadna nie musiała uczyć się narzędzia tej drugiej.

Wersja 1.2.2 · wymaga MeshPulse 2.3.0 lub nowszego

---

## Spis treści

1. [Co to właściwie robi](#1-co-to-właściwie-robi)
2. [Jak to działa w środku](#2-jak-to-działa-w-środku)
3. [Instalacja od zera](#3-instalacja-od-zera)
4. [Codzienne użycie](#4-codzienne-użycie)
5. [Parowanie kont z radiami](#5-parowanie-kont-z-radiami)
6. [Komendy](#6-komendy)
7. [Wszystkie ustawienia](#7-wszystkie-ustawienia)
8. [Gotowe przepisy](#8-gotowe-przepisy)
9. [Testowanie z jednym radiem](#9-testowanie-z-jednym-radiem)
10. [Kiedy coś nie działa](#10-kiedy-coś-nie-działa)
11. [Ograniczenia, których nie da się obejść](#11-ograniczenia-których-nie-da-się-obejść)
12. [Czego jeszcze nie ma](#12-czego-jeszcze-nie-ma)

---

## 1. Co to właściwie robi

Masz radio Meshtastic podłączone do Raspberry Pi, na którym chodzi MeshPulse.
Ta wtyczka bierze wszystko, co to radio usłyszy, i wrzuca na Discorda — a
wszystko, co ktoś napisze na Discordzie, nadaje w eter.

```
   ktoś z radiem                  Twoje Pi                    Discord
   w terenie                      + radio
      📻  ──────── LoRa ────────►  📡  ──── internet ────►  💬  Ty i znajomi
      📻  ◄─────── LoRa ─────────  📡  ◄─── internet ─────  💬
```

Osoba przy radiu widzi na ekranie:

> `[Ryszard] Jesteś jeszcze na szczycie?`

Ty na Discordzie widzisz:

> 📡 **Mobilny** `!bbbb2222`: Schodzę, będę za godzinę

Nikt niczego nie przełącza. Piszesz jak do znajomego, on odpowiada z krótkofalówki.

### Osobna rozmowa dla każdej osoby

Domyślnie kanał na Discordzie działa jak poczekalnia, a **każde radio dostaje
własny wątek**:

```
#mesh-bridge              ← tu piszesz do całej siatki
 ├─ 🧵 Kuba (!aaaa1111)      ← prywatna rozmowa z Kubą
 ├─ 🧵 Ola (!bbbb2222)       ← prywatna rozmowa z Olą
 └─ 🧵 Marek (!cccc3333)
```

Ktoś odezwie się pierwszy raz — bot sam zakłada wątek z jego nazwą. Każda
kolejna wiadomość od niego trafia w to samo miejsce. Zawsze.

**To, co napiszesz w wątku, idzie prywatnie tylko do tego jednego radia.**
To, co napiszesz w głównym kanale, słyszy cała siatka.

---

## 2. Jak to działa w środku

Nie musisz tego wiedzieć, żeby używać. Ale jak coś zgrzytnie, ta wiedza pomaga.

**Wtyczka ma własny wątek systemowy i własną pętlę.** Powód: MeshPulse dostarcza
pakiety z radia w jednorazowej pętli, która ginie zaraz po obsłużeniu jednego
zdarzenia. Klient Discorda musi żyć godzinami, więc mieszka osobno, a pakiety z
radia są mu przekazywane bezpiecznie między wątkami.

**Trzy niezależne zabezpieczenia przed pętlą.** Bez nich Twoja wiadomość poleciałaby
w eter, radio usłyszałoby ją z powrotem, wtyczka wrzuciłaby ją znowu na Discord —
i tak w kółko aż do zapchania pasma.

1. Discord: bot ignoruje własne wiadomości, inne boty i obce kanały
2. Radio: pakiety nadane przez Twój własny węzeł są odrzucane
3. Odcisk palca: skrót treści zapisywany **przed** nadaniem; ta sama treść
   wracająca w ciągu 3 minut jest wyrzucana, a odcisk zużywany — więc szczere
   powtórzenie tego samego zdania później przejdzie normalnie

**Dzielenie długich wiadomości.** Radio przepuszcza około 200 bajtów. Polskie
`ą ę ł ń ó ś ź ż` zajmują po dwa bajty, więc liczenie znaków by nie wystarczyło —
wtyczka liczy bajty i tnie po granicach słów, maksymalnie na 4 kawałki.

**Odstęp między nadaniami.** Domyślnie 3 sekundy. Prawo ogranicza, ile czasu wolno
zajmować pasmo.

---

## 3. Instalacja od zera

### 3.1. Bot na Discordzie

Wejdź na `discord.com/developers/applications` i zaloguj się zwykłym kontem.

1. **New Application** → nazwa, np. `MeshBridge` → **Create**
2. Menu z lewej → **Bot**
3. Zjedź do **Privileged Gateway Intents** i włącz:
   - ☑ `MESSAGE CONTENT INTENT` — **wymagane**, bez tego bot nie czyta treści
   - ☑ `SERVER MEMBERS INTENT` — opcjonalne, tylko do automatycznego witania nowych
4. **Save Changes**
5. Góra strony → **Reset Token** → **Copy** → wklej do notatnika

> ⚠️ Token pokazuje się **raz**. Zgubisz — resetujesz i bierzesz nowy.
> Traktuj go jak hasło: kto go ma, ten steruje botem.

### 3.2. Wpuszczenie bota na serwer

1. Menu z lewej → **OAuth2** → **URL Generator**
2. W sekcji **Scopes** zaznacz `bot`
   *(dopiero teraz pod spodem pojawi się lista uprawnień)*
3. W **Bot Permissions** zaznacz:

   | Uprawnienie | Do czego |
   |---|---|
   | View Channels | widzieć kanał |
   | Send Messages | pisać |
   | Read Message History | odczytywać kontekst |
   | Add Reactions | znacznik 📡 potwierdzający nadanie |
   | Create Public Threads | zakładać wątki dla węzłów |
   | Send Messages in Threads | pisać w tych wątkach |
   | Manage Roles | tylko jeśli używasz `paired_role_name` |

4. Skopiuj link z dołu strony → otwórz w przeglądarce → wybierz serwer → **Autoryzuj**

> Przy `Manage Roles`: w ustawieniach serwera przesuń rolę bota **wyżej** niż
> rolę, którą ma nadawać. Discord inaczej odmówi.

### 3.3. Numer kanału

1. Discord → zębatka → **Zaawansowane** → włącz **Tryb dewelopera**
2. Prawy klik na **kanale tekstowym** → **Kopiuj identyfikator kanału**

> ⚠️ Kliknij w kanał, nie w kategorię nad nim. Numer wygląda identycznie
> (19 cyfr), ale bot go nie znajdzie.

### 3.4. Wtyczka

1. Otwórz MeshPulse w przeglądarce, np. `http://192.168.1.115/meshpulse/`
   *(ukośnik na końcu ma znaczenie)*
2. **Config → Plugins → Install Plugin** → wskaż plik `.meshplugin`
3. Przy wtyczce naciśnij **Enable** — potrwa kilkanaście sekund, bo dociąga
   bibliotekę `discord.py`
4. Rozwiń ⚙️ **Settings** → wklej **token** i **ID kanału**

> Po każdej instalacji odśwież stronę (**F5**). Lista ustawień przychodzi
> WebSocketem przy ładowaniu, więc stara zakładka pokazuje stary zestaw pól.

### 3.5. Sprawdzenie

| Krok | Czego się spodziewać |
|---|---|
| Napisz cokolwiek na kanale | bot dokleja reakcję 📡 |
| `!mesh status` | 🟢 online, liczniki, czas pracy |
| Ktoś nadaje z radia | powstaje wątek z jego nazwą |

---

## 4. Codzienne użycie

### Wysyłanie w eter

**Do wszystkich** — pisz w głównym kanale. Wiadomość leci rozgłoszeniowo na
kanał Meshtastic i słyszy ją każdy w zasięgu.

**Do jednej osoby** — wejdź w jej wątek i pisz tam. Wiadomość idzie jako
prywatna, tylko do tego węzła.

**Jednorazowo, bez wchodzenia w wątek:**
```
!mesh dm !aaaa1111 Jesteś na miejscu?
```

Każda wiadomość wychodzi podpisana Twoją nazwą z Discorda: `[Ryszard] treść`.
Można to wyłączyć ustawieniem `name_prefix`.

### Odbieranie

Wiadomości z radia trafiają do wątku nadawcy. Format:

> 📡 **Kuba** `!aaaa1111`: schodzę ze szczytu

Kłódka 🔒 przy nazwie oznacza, że to była wiadomość prywatna do Twojego węzła,
a nie rozgłoszenie na kanał.

### Znaczniki

| Symbol | Znaczenie |
|---|---|
| 📡 | bot przyjął Twoją wiadomość i nadał ją |
| 🔒 | przychodząca wiadomość była prywatna |
| ✂️ | wiadomość była za długa i poszła w kawałkach |

---

## 5. Parowanie kont z radiami

Parowanie wiąże konto Discord z konkretnym radiem — **w sposób udowodniony**,
nie zadeklarowany. Dzięki temu bot wie, kto siedzi za którym węzłem.

### Jak to przebiega

1. Osoba wpisuje na kanale `!mesh pair`
   *(albo, przy włączonym `greet_new_members`, dostaje kod automatycznie zaraz
   po wejściu na serwer)*
2. Bot przysyła jej na priv kod, np. `PAIR-7K2M`
3. Osoba wysyła ten kod **ze swojego radia, jako wiadomość prywatną** do węzła
   z mostkiem
4. Bot potwierdza: ✅ *Sparowano z węzłem Kuba `!aaaa1111`* i ewentualnie
   nadaje rolę

### Dlaczego akurat tak

Posiadanie radia jest jedyną rzeczą, której nie da się podrobić z klawiatury.
Kto potrafi nadać z danego węzła, ten nim dysponuje — i to wystarczy za dowód.

**Kod musi przyjść jako wiadomość prywatna.** Od firmware 2.5 prywatne wiadomości
są szyfrowane kluczem publicznym odbiorcy, więc nikt inny w zasięgu nie
podsłucha kodu i nie przejmie cudzego konta. Kod wysłany otwarcie na kanał jest
odrzucany, a nadawca dostaje podpowiedź, żeby spróbować prywatnie.

### Zasady

- kod ważny domyślnie **15 minut**
- kod jest **jednorazowy** — druga próba użycia zostaje odrzucona
- jedno konto = jedno radio; sparowanie nowego zwalnia stare, po obu stronach
- kod nigdy nie trafia na kanał jako zwykła wiadomość
- alfabet kodów nie zawiera `0 O 1 I L`, bo ludzie przepisują je z małych ekranów

---

## 6. Komendy

Wpisywane na kanale mostka albo w dowolnym wątku pod nim.
Przedrostek `!mesh` można zmienić ustawieniem `command_prefix`.

| Komenda | Co robi |
|---|---|
| `!mesh` | ściąga listy komend |
| `!mesh status` | stan połączenia, liczniki, czas pracy, liczba rozmów i sparowanych kont |
| `!mesh nodes` | węzły, które Twoje radio aktualnie widzi |
| `!mesh threads` | otwarte rozmowy i odnośniki do ich wątków |
| `!mesh open !aaaa1111` | zakłada wątek dla węzła, który się jeszcze nie odezwał |
| `!mesh dm !aaaa1111 treść` | jednorazowa wiadomość prywatna |
| `!mesh pair` | prośba o kod parujący |
| `!mesh whoami` | pokazuje, z którym węzłem jesteś sparowany |
| `!mesh unpair` | zrywa to powiązanie |
| `!mesh here` | wypisuje ID bieżącego kanału |
| `!mesh simulate [dm] !aaaa1111 treść` | wstrzykuje udawany pakiet (do testów) |

---

## 7. Wszystkie ustawienia

**Config → Plugins → Discord Bridge → ⚙️ Settings**

### Podstawa

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `discord_token` | — | token bota z portalu Discorda |
| `discord_channel_id` | — | ID kanału tekstowego, same cyfry |
| `mesh_to_discord` | ✅ | przekazuj z radia na Discord |
| `discord_to_mesh` | ✅ | przekazuj z Discorda w eter |

### Siatka radiowa

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `mesh_channel_index` | `0` | na którym kanale Meshtastic nadawać |
| `mesh_channel_filter` | `all` | którego kanału słuchać: `all` albo numer |
| `forward_dms` | ✅ | przekazuj też wiadomości prywatne do Twojego węzła |
| `dm_target` | puste | numer węzła — wtedy **główny kanał** też pisze prywatnie tylko do niego |
| `name_prefix` | ✅ | dopisuj `[Nazwa]` przed treścią |

### Wątki

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `thread_per_node` | ✅ | osobny wątek dla każdego węzła |
| `thread_scope` | `all` | `all` = każdy nadawca, `dm` = tylko prywatne (rozgłoszenia zostają w kanale) |
| `thread_archive_hours` | `24` | po ilu godzinach ciszy Discord chowa wątek (odkopywany sam) |
| `thread_name_template` | `{name} ({id})` | tytuł wątku |

### Parowanie

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `pairing_enabled` | ✅ | w ogóle pozwalaj parować |
| `pair_code_ttl_minutes` | `15` | jak długo kod jest ważny |
| `pair_require_dm` | ✅ | kod musi przyjść prywatnie — **nie wyłączaj bez potrzeby** |
| `greet_new_members` | ✅ | wysyłaj kod nowym na serwerze *(wymaga SERVER MEMBERS INTENT)* |
| `paired_role_name` | puste | rola nadawana po sparowaniu *(wymaga Manage Roles)* |

### Zaawansowane

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `simulate_enabled` | ❌ | włącza `!mesh simulate` — **trzymaj wyłączone na co dzień** |
| `command_prefix` | `!mesh` | przedrostek komend |
| `use_embed` | ❌ | pokazuj przychodzące jako embed zamiast tekstu |
| `allow_bots` | ❌ | przekazuj wiadomości innych botów — **zdejmuje jedno zabezpieczenie pętli** |
| `max_payload` | `200` | maksymalny rozmiar pakietu w bajtach |
| `max_chunks` | `4` | na ile kawałków wolno pociąć długą wiadomość |
| `tx_interval` | `3` | odstęp między nadaniami w sekundach |
| `echo_ttl` | `180` | okno wykrywania własnego echa w sekundach |
| `log_to_db` | ✅ | zapisuj przekazane wiadomości do bazy wtyczki |

---

## 8. Gotowe przepisy

### Rozmowa publiczna z całą siatką

Ustawienia domyślne. `dm_target` puste, `thread_per_node` włączone.
Piszesz w głównym kanale — słyszą wszyscy. Odpowiedzi lądują w wątkach nadawców.

### Prywatna rozmowa z jedną osobą

Wejdź w jej wątek i pisz. Tyle. Nic nie trzeba przestawiać.

Jeśli wolisz, żeby **cały** kanał rozmawiał tylko z jednym radiem:
ustaw `dm_target` na jego numer, np. `!aaaa1111`. Wyczyszczenie pola cofa zmianę.

### Szczelny kanał tylko dla dwóch osób

Najczystsze rozwiązanie, gdy rozmowa ma być stała i niewidoczna dla reszty siatki:

1. W aplikacji Meshtastic **na obu radiach** dodaj nowy kanał z własnym hasłem
   (PSK), np. `mostek`. Zapamiętaj jego numer na liście — załóżmy **1**
2. W ustawieniach wtyczki:
   - `mesh_channel_index` → `1`
   - `mesh_channel_filter` → `1`
   - `dm_target` → **puste**

Efekt: kanał Discord ↔ kanał `mostek`, w obie strony, zaszyfrowany hasłem,
którego nie ma nikt inny. Ruch z Primary przestaje się pojawiać.

### Powrót do ustawień wyjściowych

`dm_target` puste, `mesh_channel_index` na `0`, `mesh_channel_filter` na `all`.

---

## 9. Testowanie z jednym radiem

Mając jedno radio nie przetestujesz niczego naturalnie — Twój węzeł **jest**
mostkiem i nie wyśle wiadomości prywatnej sam do siebie. Od tego jest symulacja.

Włącz `simulate_enabled` i po kolei:

```
!mesh simulate !aaaa1111 czesc z terenu
```
→ powstaje wątek `sim-1111 (!aaaa1111)` z tą wiadomością

```
(napisz coś w tym wątku)
```
→ licznik `Discord→mesh` w `!mesh status` rośnie o 1; to była prawdziwa transmisja

```
!mesh pair
!mesh simulate dm !aaaa1111 PAIR-7K2M
```
→ konto zostaje sparowane, `!mesh whoami` zwraca `!aaaa1111`

```
!mesh simulate !bbbb2222 PAIR-XXXX
```
→ **nic się nie dzieje** — kod puszczony otwarcie jest odrzucany, tak ma być

Na koniec `!mesh unpair` i **wyłącz `simulate_enabled`**. Z włączonym każdy na
kanale może podszyć się pod dowolny węzeł.

> Symulacja wstrzykuje pakiet dokładnie tam, gdzie normalnie ląduje odczyt z
> radia — sprawdza więc całą drogę powyżej. Nie sprawdza jednego: czy prawdziwy
> pakiet z anteny dociera do wtyczki. Tego nie udowodni nic poza drugim radiem.

---

## 10. Kiedy coś nie działa

Podgląd logu na Raspberry Pi:

```
sudo journalctl -u meshpulse --no-pager | grep -i "discord\|PLUGIN" | tail -20
```

Na żywo, podczas testów:

```
sudo journalctl -u meshpulse -f | grep PLUGIN
```

| Objaw | Najczęstsza przyczyna | Co zrobić |
|---|---|---|
| Bot szary, w ogóle go nie ma | brak `MESSAGE CONTENT INTENT` albo zły token | włącz przełącznik w portalu, zapisz; ewentualnie zresetuj token |
| `Cannot resolve channel …` | skopiowane ID kategorii zamiast kanału, albo bot nie widzi kanału | prawy klik na sam kanał tekstowy; sprawdź uprawnienia kanału |
| Bot online, ale nic nie przekazuje | patrzysz w główny kanał, a wiadomości idą do wątków | rozwiń listę wątków przy kanale |
| Wiadomości lądują w kanale zamiast w wątkach | brak `Create Public Threads` | popraw uprawnienia w linku OAuth2 i autoryzuj ponownie |
| Rola po sparowaniu nie zostaje nadana | brak `Manage Roles` albo rola bota jest za nisko | przesuń rolę bota nad tę, którą ma nadawać |
| `!mesh pair` odpowiada, że nie może napisać na priv | zamknięte wiadomości prywatne | ustawienia prywatności serwera → zezwól na priv od członków |
| Kod parujący odrzucany | wysłany otwarcie na kanał zamiast prywatnie | wyślij jako wiadomość prywatną do węzła z mostkiem |
| Brak jakichkolwiek linii `[PLUGIN:...]` | wtyczka nie jest włączona | Config → Plugins → **Enable** |
| Nowe ustawienia nie widać | stara zakładka w przeglądarce | **F5** |

Komunikaty wtyczki w logu są pisane po ludzku i same mówią, czego brakuje.

---

## 11. Ograniczenia, których nie da się obejść

To nie są niedoróbki wtyczki. To fizyka radia i kryptografia.

**Siatka widzi jeden nadajnik, nie ludzi.**
Wszystkie osoby piszące na Discordzie wychodzą w eter przez to jedno radio.
Rozróżnia je wyłącznie dopisek `[Nazwa]`. Żeby ktoś był prawdziwym uczestnikiem
siatki, musi mieć własne radio.

**Nie ma potwierdzeń doręczenia.**
Radio nadaje i tyle. Jeśli odbiorca jest poza zasięgiem albo ma wyłączone
urządzenie, wiadomość przepada po cichu. Nie zobaczysz „niedostarczono".

**Tempo jak przy krótkofalówce, nie komunikatorze.**
Krótka wiadomość — kilka sekund. Długa, pocięta na cztery kawałki — kilkanaście.

**Centralny mostek nie odczyta cudzych rozmów prywatnych.**
Od firmware 2.5 wiadomości prywatne są szyfrowane kluczem odbiorcy. Twoje Pi
przekaże dalej rozmowę Kuby z Olą, ale jej nie przeczyta. Żeby lustrzanić czyjąś
prywatną rozmowę, wtyczka musi chodzić u tej osoby.

**MeshPulse nie ma logowania.**
Nie ma kont ani haseł — kto jest w Twojej sieci lokalnej i wpisze adres Pi, ten
steruje Twoim radiem. Nie wystawiaj tego na internet.

---

## 12. Czego jeszcze nie ma

**Czat z okna MeshPulse nie wychodzi na Discord.**
Kiedy piszesz w zakładce Messages na stronie MeshPulse, wtyczka tego nie widzi —
ścieżka wysyłki w MeshPulse nie powiadamia wtyczek. Wiadomość poleci w eter
normalnie, ale na Discordzie się nie pojawi. W drugą stronę wszystko działa.

**Kanały dla par osób.**
Zamysł: dwie sparowane osoby dostają rolę i prywatny kanał widoczny tylko dla
nich. Zaprojektowane, jeszcze nie zbudowane. Parowanie z tej wersji jest
fundamentem, na którym to stanie.

---

## Licencja

GPL-3.0. Kod jest w `backend/main.py`, komentarze wyjaśniają **dlaczego**
poszczególne rzeczy wyglądają tak, a nie inaczej — zwłaszcza własny wątek,
cięcie po bajtach i odcisk palca zapisywany przed nadaniem.
