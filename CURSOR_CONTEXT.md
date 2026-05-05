# TriSense 3.0 — Context complet pentru Cursor AI

## Ce este proiectul

TriSense este un **robot terapeut interactiv** pentru copii, construit din LEGO SPIKE Prime, controlat prin LMS-ESP32 (AntonsMindstorms) și orchestrat de un PC (Python). Proiect de licență.

Robotul vorbește (TTS pe difuzor), ascultă (microfon I2S), mișcă brațele/rotile, afișează pe matricea LED 5x5 și recunoaște obiecte (HuskyLens).

## Arhitectură (3 dispozitive)

```
┌─────────────────────────────────────────────────────────────┐
│  PC (Windows) — "creierul"                                  │
│  Python 3.13 + paho-mqtt + google-genai + pyttsx3           │
│                                                             │
│  trisense/brain.py  — orchestrator, state machine           │
│  trisense/ai_client.py — Gemini via Vertex AI (STT + LLM)  │
│  trisense/cloud_tts.py — Google Cloud TTS Neural2           │
│  trisense/audio_push.py — trimite PCM stereo la ESP via TCP │
│  trisense/mqtt_layer.py — MQTT publish/subscribe            │
│  trisense/voice_tcp_server.py — primește audio de la ESP    │
├─────────────────────────────────────────────────────────────┤
│  ESP32 (LMS-ESP32 v2) — "corpul"                           │
│  MicroPython firmware AntonsMindstorms                      │
│                                                             │
│  main_robot.py → copiat ca main.py pe ESP                   │
│  - LPF2 UART ↔ Hub LEGO (PUPRemoteSensor)                  │
│  - MQTT subscriber (robot/control, robot/speak)             │
│  - I2S audio output (difuzor 4Ω/2W prin MAX98357A)         │
│  - I2S audio input (microfon INMP441)                       │
│  - HuskyLens I2C (recunoaștere obiecte)                     │
│  - Audio TCP server port 8766 (primește PCM de la PC)       │
│  - _thread pe Core 2 pt LPF2 heartbeat în timpul I2S       │
├─────────────────────────────────────────────────────────────┤
│  Hub LEGO SPIKE Prime — "mușchii"                           │
│  Pybricks MicroPython                                       │
│                                                             │
│  main.py → uploadat prin Pybricks IDE (Bluetooth)           │
│  - Motor brațe: Port B (stâng), Port E (drept)              │
│  - Motor roți: Port C (stâng), Port D (drept)               │
│  - Matrice LED 5x5 (afișează emoții, animații respirație)   │
│  - PUPRemoteHub pe Port A ↔ ESP32                           │
└─────────────────────────────────────────────────────────────┘
```

## Protocol comunicare

### LPF2 (ESP ↔ Hub LEGO, cablu UART)
- **Canal `obj`** (uint8): ID obiect detectat de HuskyLens
- **Canal `cmd`** (uint8): comandă de la PC→ESP→Hub
- Heartbeat obligatoriu: `pr.process()` la minim 15 Hz (max 66ms interval)
- Timeout heartbeat: ~1 secundă → `line is dead`
- **CRITIC**: I2S audio blochează Core 0 → folosim `_thread` pe Core 2 pentru heartbeat

### MQTT (PC ↔ ESP, WiFi)
- Broker: Mosquitto pe PC (portul 1883)
- **`robot/control`**: PC publică JSON `{"action": "dance"}`, `{"action": "emotion_happy"}` etc.
- **`robot/speak`**: PC publică text pentru TTS pe ESP (fallback dacă Audio TCP eșuează)
- **`vision/tags`**: ESP publică `{"id": N}` când HuskyLens detectează obiect

### Audio TCP (PC → ESP, port 8766)
- Header: `TPCM` (4B magic) + sample_rate u32 + length u32
- Payload: PCM16 stereo LE
- Preferabil: fără resampling (trimite la rata originală, ex. 24000 Hz)

### Voice TCP (ESP → PC, port 8765)
- ESP înregistrează audio microfon → trimite la PC pentru STT Gemini

## Comenzi Hub (canal `cmd` uint8)

| cmd | Acțiune | Funcție Hub |
|-----|---------|-------------|
| 0 | idle | - |
| 1 | dans + roți față/spate | `dance_arms_and_wheels()` |
| 2 | repose (brațe home) | `repose_pose()` |
| 3 | braț stâng sus | `left_arm_up_pose()` |
| 4 | braț drept sus | `right_arm_up_pose()` |
| 5 | inspiră (brațe deschise) | `breathe_in_pose()` |
| 6 | expiră (brațe strânse) | `breathe_out_pose()` |
| 7-11 | roți (înainte/înapoi/pivot/stop) | `wheels_*()` |
| 12 | show respirație (~10s, 2 cicluri) | `breathing_show_routine()` |
| 13 | emoție tristă (lacrimi animate) | `emotion_sad_routine()` |
| 14 | emoție uimită (flash alternant) | `emotion_surprised_routine()` |
| 15 | emoție fericită (dans + roți) | `emotion_happy_routine()` |

## Activități implementate

### Act. 4 — Breathing Show
- PC trimite `{"action": "breathing_show"}` → Hub face animație respirație pe matrice + brațe
- PC redă vocal instrucțiunea **înainte** de Hub ("Follow my arms...")
- Audio PCM inspiră/expiră **NU** se mai redă în PAS4 (eliminat)

### Act. 6 — Guess the Emotion
- PC alege random: happy/sad/surprised
- Robot zice "Watch carefully!" → trimite emoția la Hub → Hub execută rutina (cmd 13/14/15)
- Robot întreabă "What emotion was I showing?"
- Copilul răspunde → validare cuvinte cheie (happy/sad/surprised)
- Corect → felicitare + dans | Greșit → retry

### Act. 7 — Follow the Pattern
- Secvență hardcodată: left_arm → right_arm → breathe_in (3 pași)
- Robot demonstrează fiecare pas cu voce + mișcare
- Copilul trebuie să repete pas cu pas
- Validare: cuvinte cheie detectate de `_detect_motor_action()`

## Mașina de stări (brain.py)

```
START → SALUT (recunoaștere față) → SELECTIE_JOC → ACTIVITATE
                                                  → GUESS_EMOTION (Act. 6)
                                                  → FOLLOW_PATTERN (Act. 7)
                                                  → FINAL
```

## Fișiere cheie

| Fișier | Rulează pe | Rol |
|--------|-----------|-----|
| `main.py` | Hub LEGO (Pybricks) | Control motoare + matrice LED |
| `main_robot.py` | ESP32 (ca `main.py`) | LPF2 + MQTT + I2S audio + HuskyLens |
| `trisense/brain.py` | PC | Orchestrator, state machine, LLM |
| `trisense/ai_client.py` | PC | Gemini API (Vertex) |
| `trisense/cloud_tts.py` | PC | Google Cloud TTS Neural2 |
| `trisense/audio_push.py` | PC | Trimite PCM stereo la ESP TCP |
| `trisense/config.py` | PC | Configurare centralizată din .env |
| `trisense/mqtt_layer.py` | PC | Client MQTT paho |
| `trisense/tts_engine.py` | PC | pyttsx3 local (fallback) |
| `trisense/voice_tcp_server.py` | PC | Server TCP pentru microfon ESP |
| `run_trisense_brain.py` | PC | Entry point cu microfon ESP |
| `run_voice_dialog.py` | PC | Entry point cu Voice TCP server |
| `testare/test_laptop_mic.py` | PC | Test Act.6/7 cu microfon laptop |
| `secrets.example.py` | ESP32 | Template pentru secrets.py |

## Instrucțiuni pentru Cursor AI

**Ești responsabil să faci totul singur.** Când utilizatorul îți cere ceva, fă-l direct — scrie cod, uploadează pe ESP, modifică configurări, fără să aștepți confirmare la fiecare pas.

### Schimbat rețeaua WiFi (Inventika vs Acasă)
Când utilizatorul spune că e într-o locație nouă (ex. "sunt la inventika", "sunt acasă"):
1. Întreabă-l **SSID**, **parola** și **IP-ul PC-ului** (`ipconfig` în terminal)
2. Actualizează **toate** fișierele simultan:
   - `.env` → `MQTT_BROKER`, `PC_VOICE_IP`, `ROBOT_ESP_IP`
   - `main_robot.py` → default-urile `WIFI_SSID`, `WIFI_PASS`, `MQTT_BROKER`
   - `secrets.py` pe ESP → creează local, uploadează cu `py -m mpremote cp secrets.py :secrets.py`, apoi șterge local
3. `ROBOT_ESP_IP` nu-l știi dinainte — pune un placeholder, apoi după ce ESP-ul bootează verifică IP-ul real:
   ```powershell
   py -m mpremote exec "import network; w=network.WLAN(network.STA_IF); print(w.ifconfig())"
   ```
4. Upload ESP: **`main_robot.py` se copiază ca `:main.py`** (NU ca `:main_robot.py`!)
   ```powershell
   py -m mpremote cp main_robot.py :main.py; py -m mpremote reset
   ```

### Rețele cunoscute

| Locație | SSID | Parola | IP PC (exemplu) |
|---------|------|--------|-----------------|
| Acasă | Orange-292q-2.4G | Y8kCA4vx | 192.168.100.134 |
| Inventika | inventika | !#inventika2025 | 192.168.80.106 |

### Upload pe ESP — reguli stricte
- **`main_robot.py`** local → se urcă pe ESP ca **`:main.py`** (MicroPython boot file)
- **NU** urcă ca `:main_robot.py` — ESP-ul nu-l va rula
- Dacă serialul e deschis în alt terminal (`mpremote connect`), `mpremote cp` va da `no device found` — utilizatorul trebuie să închidă serialul
- PowerShell nu suportă `&&` — folosește `;` între comenzi

### Upload pe Hub LEGO — reguli stricte
- **`main.py`** local → se uploadează prin **Pybricks IDE** (code.pybricks.com, Bluetooth)
- NU se poate uploada prin mpremote — Hub-ul rulează Pybricks, nu MicroPython standard
- După upload, trebuie apăsat **butonul verde** pe Hub sau dat **Run** din Pybricks IDE
- Prima linie din `main.py` **NU trebuie să aibă spații înainte** (IndentationError pe Pybricks)

## Cum se rulează

### Pregătire
1. `pip install -r requirements.txt`
2. Copiază `.env.example` → `.env` și completează:
   - `MQTT_BROKER` = IP-ul PC-ului pe rețeaua WiFi
   - `PC_VOICE_IP` = același IP
   - `ROBOT_ESP_IP` = IP-ul ESP32 (vezi serial după conectare WiFi)
   - `GOOGLE_APPLICATION_CREDENTIALS` = cale la `cheie_google.json`
3. Copiază `secrets.example.py` → `secrets.py` pe ESP32:
   - `WIFI_SSID`, `WIFI_PASS` = rețeaua WiFi 2.4GHz
   - `MQTT_BROKER` = IP-ul PC-ului
   - `PC_VOICE_IP` = IP-ul PC-ului
4. Instalează Mosquitto MQTT broker pe PC (port 1883)
5. Uploadează `main.py` pe Hub prin **Pybricks IDE** (Bluetooth, code.pybricks.com)
6. Uploadează `main_robot.py` pe ESP ca `main.py`:
   ```powershell
   py -m mpremote cp main_robot.py :main.py
   py -m mpremote cp secrets.py :secrets.py
   py -m mpremote reset
   ```

### Pornire (ordine recomandată)
1. Pornește Mosquitto: `mosquitto -v`
2. Pornește ESP32 (USB sau alimentare externă) — se conectează automat la WiFi + MQTT
3. Pornește Hub LEGO și rulează `main.py` din Pybricks IDE (sau buton verde dacă e deja uploadat)
4. **Cu microfon ESP**: `py run_voice_dialog.py`
5. **Cu microfon laptop** (test): `py testare/test_laptop_mic.py`

### Test rapid Act.6 (Guess the Emotion)
```powershell
py testare/test_laptop_mic.py
# Spune: "Let's play guess the emotion"
# Robotul alege o emoție, o demonstrează, și te întreabă ce a fost
# Răspunde: "happy" / "sad" / "surprised"
```

### Test rapid comenzi MQTT
```powershell
python -c "import json, paho.mqtt.publish as p; p.single('robot/control', json.dumps({'action':'emotion_happy'}), hostname='BROKER_IP')"
python -c "import json, paho.mqtt.publish as p; p.single('robot/control', json.dumps({'action':'dance'}), hostname='BROKER_IP')"
```

## Probleme cunoscute și soluții

### LPF2 "line is dead" în timpul audio
- **Cauză**: I2S `audio.write()` blochează Core 0, heartbeat-ul LPF2 nu mai ajunge
- **Soluție**: `_thread` pe Core 2 care cheamă `pr.process()` continuu + `time.sleep_ms(1)` după fiecare `audio.write()` pentru yield GIL
- **ibuf I2S**: 16384 bytes când ticker e activ (DMA buffer suficient pentru 1ms pauze)
- **Write chunk**: 2048 bytes (nu 128!) când ticker e activ

### Audio sacadat (choppy TTS)
- **Cauză**: nearest-neighbor resampling de la 24000→16000 Hz distrugea calitatea
- **Soluție**: eliminat resampling-ul, trimite PCM la rata originală (24000 Hz Cloud TTS)

### pyttsx3 se blochează la al doilea apel
- **Cauză**: bug Windows cu `runAndWait()` repetat
- **Soluție**: re-inițializare engine la fiecare apel (`trisense/tts_engine.py`)

### Hub crăpă după handshake
- **Cauză**: `main.py` de pe Hub are eroare de sintaxă sau nu e uploadat
- **Soluție**: re-uploadează din Pybricks IDE, verifică prima linie (nu trebuie spații înainte de docstring)

## Hardware

- **Hub**: LEGO SPIKE Prime (Pybricks firmware)
- **ESP32**: LMS-ESP32 v2 (AntonsMindstorms MicroPython firmware)
- **Amplificator**: MAX98357A (I2S → difuzor)
- **Difuzor**: 4Ω / 2W
- **Microfon**: INMP441 (I2S)
- **Cameră**: HuskyLens (I2C, object classification)
- **Conexiune Hub↔ESP**: cablu LEGO (port A hub → conector LMS-ESP32)

### Pinout ESP32
| Funcție | Pin |
|---------|-----|
| I2S BCLK (amp) | 14 |
| I2S LRC (amp) | 15 |
| I2S DIN (amp) | 26 |
| AMP Enable | 32 |
| MIC I2S SD | 33 |
| HuskyLens SDA | 25 |
| HuskyLens SCL | 27 |

## Structura .env (PC)

```env
GEMINI_USE_VERTEX=1
GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/cheie_google.json
GCP_LOCATION=global
GEMINI_MODEL=gemini-3-flash-preview
TRISENSE_TTS_PCM_SOURCE=google_cloud
GCP_TTS_VOICE=en-US-Neural2-F
GCP_TTS_LANGUAGE=en-US
GCP_TTS_SAMPLE_RATE_HZ=24000
MQTT_BROKER=<IP_PC>
MQTT_PORT=1883
PC_VOICE_IP=<IP_PC>
ROBOT_ESP_IP=<IP_ESP>
TRISENSE_TTS_OVER_TCP=1
ESP_AUDIO_TCP_PORT=8766
```

## Structura secrets.py (ESP32)

```python
GEMINI_API_KEY = ""           # nu mai e necesar dacă TTS vine de pe PC
PC_VOICE_IP = "<IP_PC>"
WIFI_SSID = "<numele rețelei>"
WIFI_PASS = "<parola>"
MQTT_BROKER = "<IP_PC>"
```
