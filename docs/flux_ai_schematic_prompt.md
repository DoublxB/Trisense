# TriSense — schematic Flux.ai (fără HuskyLens, cu ESP32-CAM)

**Arhitectura confirmată** (cod + montaj fizic):

```
[Hub SPIKE Prime]  baterie interna + incarcare la priza (cablu USB)
       |
       | cablu LEGO Anton (Port A <-> LPF2) — UART + alimentare LMS
       v
[LMS-ESP32 v2] ----WiFi----> [Router] ----> [PC: MQTT, voce, vision bridge]
       | 5V + GND (doar alimentare, fara GPIO date)
       v
[ESP32-CAM AI-Thinker] ----WiFi----> PC (HTTP /capture -> vision/tags)

Pe LMS (I2S): MAX98357 + INMP441
Pe Hub (Pybricks main.py): Port B,E brate; C,D roti
```

**HuskyLens eliminat.** Camera = **ESP32-CAM** (date pe **WiFi**; **5V + GND** de la **LMS-ESP32**).

**Hub ↔ LMS:** cablu LEGO dedicat Anton, **Port A**, UART intern **GPIO 7/8**. **LMS primește curent de la Hub** prin același cablu/conector (nu sursă separată la priză pentru LMS în montajul final).

Pinout LMS: https://www.antonsmindstorms.com/docs/lms-esp32-v2-pinout/

---

## PROMPT PRINCIPAL Flux Copilot (copiază tot)

```
Draw a complete TriSense robot electrical schematic. EXACT wiring below. NO HuskyLens.

MANDATORY BLOCKS:
1) LEGO SPIKE Prime Hub (internal rechargeable battery; charging port to wall USB charger — label "charge via USB when not running")
2) LMS-ESP32 v2 (Anton's Mindstorms)
3) Anton LEGO/LPF2 cable: Hub Port A <-> LMS built-in hub connector (single cable symbol)
4) MAX98357A + 4 ohm speaker
5) INMP441 microphone (REQUIRED separate symbol)
6) ESP32-CAM AI-Thinker module (separate board)
7) WiFi router + PC/laptop (dashed WiFi links)

=== POWER (confirmed physical setup) ===

LEGO Hub:
- Internal battery powers Hub motors and electronics
- Hub can be charged from wall outlet via USB charging cable (draw charger symbol when charging)
- Hub Port A supplies power to connected sensor port devices

LMS-ESP32:
- POWER FROM HUB through the LEGO/LPF2 cable (Port A on Hub -> LMS hub connector)
- Do NOT draw separate mains/USB power to LMS in normal operation — LMS is powered by Hub
- Common GND with Hub through the cable

ESP32-CAM:
- 5V wire from LMS-ESP32 5V rail -> ESP32-CAM 5V input
- GND wire from LMS-ESP32 GND -> ESP32-CAM GND
- NO other wires between ESP32-CAM and LMS (no UART, no I2C, no GPIO data lines)
- Camera module internal sensor pins stay on ESP32-CAM board only

Audio modules (MAX98357, INMP441): powered from LMS 3V3/5V and GND as per module (mic VDD = 3.3V only)

=== BLOCK A: Hub <-> LMS (data + power on Anton cable) ===

Physical: Hub Port A — Anton LEGO cable — LMS LPF2 connector

Electrical (annotate on cable / LMS connector):
- LMS GPIO 7 = UART TX to Hub
- LMS GPIO 8 = UART RX from Hub
- Power: Hub port -> LMS (5V/GND through LEGO port per Anton design)
- Protocol: LPF2 / PUPRemote, channels "cmd" and "obj"

Hub Pybricks (annotation): PUPRemoteHub on Port A; motors B,E arms; C,D wheels

DO NOT wire Hub to LMS GPIO 14,15,21,22,26,32,33 as Dupont jumpers.

=== BLOCK B: Audio on LMS (I2S) — with mini breadboard bus ===

A small breadboard (mini board) sits between LMS-ESP32 and the two audio modules. Draw it explicitly:

SHARED CLOCK BUS (mini breadboard rails):
- LMS GPIO 14 -> one wire to a breadboard rail (label "BCLK bus")
  - From that rail: one wire to MAX98357 BCLK pin
  - From that rail: one wire to INMP441 SCK/BCLK pin
- LMS GPIO 15 -> one wire to another breadboard rail (label "WS/LRC bus")
  - From that rail: one wire to MAX98357 LRC/WS pin
  - From that rail: one wire to INMP441 WS pin

SHARED GND BUS (breadboard rail):
- One GND rail on the mini breadboard connects ALL of these together:
  - INMP441 GND pin
  - INMP441 L/R pin (channel select tied to GND)
  - MAX98357 GND pin
  - One wire from this GND rail goes back to LMS-ESP32 GND pin (single wire to ESP)

SEPARATE DATA LINES (direct, not through bus):
- LMS GPIO 26 -> direct wire to MAX98357 DIN (audio data ESP to amp)
- LMS GPIO 33 <- direct wire from INMP441 SD/DOUT (mic data to ESP)
- LMS GPIO 32 -> direct wire to MAX98357 SD/EN (shutdown enable, HIGH=on)

POWER:
- MAX98357 VIN: from LMS 5V (or 3V3 per module rating)
- INMP441 VDD: from LMS 3.3V ONLY

Draw the mini breadboard as a small PCB/bus block with labeled rails: BCLK, WS/LRC, GND.
Show that GPIO 14 and 15 each go to ONE breadboard rail, then fan out to both modules from that rail.

=== BLOCK C: ESP32-CAM (vision — power from LMS, data via WiFi) ===

Power wires (solid lines):
- LMS-ESP32 5V -> ESP32-CAM 5V
- LMS-ESP32 GND -> ESP32-CAM GND

Data (dashed WiFi only):
- ESP32-CAM -> WiFi -> PC
- HTTP GET /capture (JPEG)
- PC publishes MQTT vision/tags {"id": N}
- NO GPIO data connection LMS <-> ESP32-CAM

=== BLOCK D: LMS <-> PC (WiFi only) ===

LMS WiFi: MQTT robot/control, robot/speak; TCP 8765 mic to PC; TCP 8766 audio from PC

=== DO NOT DRAW ===
- HuskyLens
- I2C on GPIO 21/22
- ESP32-CAM camera D0-D7 wired to LMS
- Separate wall power to LMS (LMS fed from Hub)
- USB power to ESP32-CAM (fed from LMS 5V/GND)

Legend with all GPIO numbers.
```

---

## PROMPT CORECTARE

```
Fix TriSense schematic:

POWER:
- Hub has internal battery + USB charge to wall
- LMS-ESP32 powered FROM Hub via Port A / LPF2 cable (not separate mains to LMS)
- ESP32-CAM: only 5V and GND wires from LMS-ESP32; WiFi dashed to PC for data

REMOVE: HuskyLens, I2C camera on 21/22

ADD: INMP441 on 14,15,33; Hub-LMS Anton cable Port A with UART 7/8 note

MAX98357: 14,15,26,32. ESP32-CAM AI-Thinker on LMS 5V/GND only.
```

---

## Diagramă fizică (montaj confirmat)

```
     [Priza USB] ----incarcare----> [Hub SPIKE Prime]
     (baterie interna)                    |
                                          | cablu LEGO Anton (Port A)
                                          |  + alimentare LMS
                                          |  + UART LPF2 (GP7/8)
                                          v
                              ┌─────────────────────┐
                              │    LMS-ESP32 v2     │
                              │  GPIO 14 ───────────┼──> [mini breadboard BCLK rail]──┬─ MAX98357 BCLK
                              │  GPIO 15 ───────────┼──> [mini breadboard WS rail]──┐ └─ INMP441 SCK
                              │                     │                               ├─ MAX98357 LRC
                              │                     │                               └─ INMP441 WS
                              │  GPIO 26 ───────────┼── direct ──> MAX98357 DIN
                              │  GPIO 32 ───────────┼── direct ──> MAX98357 SD/EN
                              │  GPIO 33 ◄──────────┼── direct ──  INMP441 DOUT
                              │  GND ───────────────┼──> [mini breadboard GND rail]──┬─ MAX98357 GND
                              │                     │                                ├─ INMP441 GND
                              │                     │                                └─ INMP441 L/R
                              │  3V3 ───────────────┼──> INMP441 VDD
                              │  5V ────────────────┼──> ESP32-CAM 5V  +  MAX98357 VIN
                              │  GND ───────────────┼──> ESP32-CAM GND
                              │  WiFi ··············┼···· PC
                              └─────────────────────┘
                                        ^
                    ESP32-CAM ···········┘ WiFi (date cameră, fără fire GPIO)
```

---

## Tabel conexiuni

| Componentă | Legătură |
|------------|----------|
| **Hub** | Baterie internă; încărcare USB la priză |
| **Hub ↔ LMS** | Cablu Anton **Port A**; UART **7/8**; **LMS alimentat de la Hub** |
| **LMS ↔ ESP32-CAM** | **5V + GND** (doar alimentare, fără date) |
| **ESP32-CAM ↔ PC** | **WiFi** — `/capture`, fără fire date către LMS |
| **Mini breadboard** | Șină **BCLK** (GP14 → amp + mic); Șină **WS** (GP15 → amp + mic); Șină **GND** (amp GND + mic GND + mic L/R → un fir la ESP GND) |
| **MAX98357** | BCLK via bus 14, LRC via bus 15, DIN direct 26, SD direct 32, VIN 5V |
| **INMP441** | SCK via bus 14, WS via bus 15, DOUT direct 33, VDD 3V3, GND+L/R via bus GND |
| **HuskyLens** | **Eliminat** |

---

## Confirmat de utilizator

| Detaliu | Valoare |
|---------|---------|
| Hub | SPIKE Prime, baterie internă, încărcare la priză |
| Port LMS | **Port A** |
| Cablu | Anton LEGO / LPF2 |
| Alimentare LMS | **De la Hub** (prin cablu) |
| ESP32-CAM | **AI-Thinker**; **5V + GND de la LMS**; date **WiFi** |
| Rest | Da la toate |

---

## ESP32-CAM (firmware proiect)

- `esp32cam_firmware/esp32cam_firmware.ino`
- `http://<IP>/capture` → PC `testare/vision_esp32cam_bridge.py` → MQTT `vision/tags`
