# TriSense - simple guide for the team

TriSense is a friendly robot that:

- sees with the camera (HuskyLens),
- speaks in a friendly voice,
- recognizes a child and LEGO pieces,
- responds through a "brain" running on the laptop.

## What the project does, in a nutshell

Imagine TriSense as a two-part game:

- The robot (ESP32) = the "body" (camera, sound, connection to the LEGO hub).
- The laptop (Python + trisense) = the "brain" (thinks of the answer and decides what the robot says).

When the camera sees something:

- The robot sends a message.
- The brain on the laptop understands it.
- TriSense responds with a short and positive message.

## Important components

| compound | What does he do (in everyone's understanding) |
|----------|-----------------------------------------------|
| `main_robot.py` | The main program on the robot (camera + audio + MQTT) |
| `run_trisense_brain.py` + `trisense/` | The laptop program that "thinks" the answer |
| `run_voice_dialog.py` + `trisense/voice_tcp_server.py` | The variant in which the robot sends the voice to the laptop (TCP server for audio) |
| `RECOVERY.md` | What to do if the upload/repl doesn't work |
| `HARDWARE_LMS_ESP32_ANTONS.md` | Useful hardware notes for the LMS-ESP32 board |

## Hardware LMS-ESP32 (Anton's Mindstorms)

Official documentation:

- Pinout: <https://www.antonsmindstorms.com/docs/lms-esp32-v2-pinout/>
- Getting started: <https://www.antonsmindstorms.com/docs/getting-started-with-your-new-lms-esp32v2-board/>
- All expansion cards: <https://www.antonsmindstorms.com/doc-category/expansion-board-documentation/>

## Pin diagram (TriSense)

Mapping used in the current code (`main_robot.py`):

| Module | Signal | GPIO | Observations |
|--------|--------|------|---------------|
| LEGO Hub (LPF2/PUPRemote) | UART to hub | 7/8 | Dedicated LMS-ESP32 line for connection to the LEGO hub |
| HuskyLens (I2C) | SCL | 22 | SoftI2C(scl=Pin(22), sda=Pin(21)) |
| HuskyLens (I2C) | SDA | 21 | Default for the room in the project |
| I2S speaker (MAX98357) | BCLK | 14 | I2S audio clock (SCK on microphone) |
| I2S speaker (MAX98357) | LRC/WS | 15 | Word select I2S |
| I2S speaker (MAX98357) | FROM | 26 | Audio data to amplifier |
| Amplifier | EN | 32 | Amplifier activation |
| I2S Microphone (INMP441) | SD | 33 | Microphone data (RX), on the same SCK/BCLK and WS/LRC |

Quick diagram:

```
LMS-ESP32
├ ─ LEGO Hub (UART): GPIO 7/8
├ ─ HuskyLens I2C: SCL=22, SDA=21
└─ Audio
   ├ ─ MAX98357 (speaker): BCLK=14, LRC=15, DIN=26, EN=32
   └─ INMP441 (small): SD=33 (share SCK/BCLK=14, WS/LRC=15)
```

Note: avoid changing pins 7/8 if the connection to the hub works; they are critical for the LPF2 handshake on the LMS-ESP32.

## Simulator wiring screenshot (to be completed)

Add here the image with the visual wiring from the simulator:

```markdown
![TriSense wiring in simulator](./docs/simulator-wiring.png)
```

Quick checklist for the picture:

- to clearly see the LMS-ESP32 board;
- to see the connections for HuskyLens, microphone and speaker;
- to see the pin labels (GPIO).

You can create the docs/ folder and put the screenshot there.

## MQTT (ESP32 <-> PC)

| Topical | Direction | Content |
|---------|-----------|---------|
| `vision/tags` | ESP32 -> broker -> PC | JSON {"id": N} (class HuskyLens: 1 = face, 2+ = LEGO objects) |
| `robot/control` | PC -> broker -> ESP32 | JSON commands (speak, listen, pc_host, voice_port, duration_ms) |
| `robot/speak` | PC -> broker -> ESP32 | Retained greeting message/short message for TTS on the robot |

Note: in main_robot.py, MQTT is non-blocking (check_msg()), and the LPF2 loop remains active (pr.process() / process_async).

## Software requirements (PC)

- Python 3.10+ recommended
- Dependencies: requirements.txt
- Gemini API key in .env (GEMINI_API_KEY)

Quick installation:

```bash
pip install -r requirements.txt
copy .env.example .env
```

Then fill in .env:

- GEMINI_API_KEY=...
- optional: MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID_PC
- optional voice: VOICE_TCP_PORT, TRISENSE_TTS_PC, TRISENSE_TTS_OVER_TCP

## Running on PC

### 1) Standard mode (brain + MQTT)

```bash
py run_trisense_brain.py
```

Used for the main interaction flow via MQTT.

### 2) Voice dialog mode (small ESP -> PC STT/TTS)

```bash
py run_voice_dialog.py
```

This mode also starts the TCP voice server (default port 8765), which receives audio from the ESP.

## ESP32 configuration

Run the firmware from main_robot.py on the LMS-ESP32 board (from the project folder, replace COM7 as the ESP appears in Device Manager):

```bash
python -m mpremote connect COM7 run main_robot.py
```

Create secrets.py on ESP (not in repo) for local keys/data (ex: GEMINI_API_KEY, PC_VOICE_IP).

Check the Wi-Fi network and MQTT broker in the ESP configuration.

## Hardware audio tests (speaker + microphone)

Before the test:

- connect the board to the correct serial port (e.g. COM7);
- stops any previous running (main_robot.py) from the same port;
- uses the same connections from the pinout (BCLK=14, LRC=15, DIN=26, MIC_SD=33).

### Speaker test (MAX98357)

Script: test/test_i2s_beep.py Role: strictly checks the I2S TX + amplifier + speaker chain (without MQTT/HuskyLens).

Running:

```bash
python -m mpremote connect COM7 run testare/test_i2s_beep.py
```

What you need to see/hear:

- in serial: I2S0 init OK 44100 STEREO, then write round ...;
- on speaker: repeated test tone (beep/sine).

If it is quiet:

- check the power supply of the MAX98357 module (Vin, GND);
- check DIN/BCLK/LRC and enable pin;
- test with another speaker or connect the SD/EN module directly to 3.3V (as the script mentions).

### Microphone + speaker test (INMP441 + MAX98357)

Script: test/test_mic_difuzor.py Role: runs the speaker test and then the I2S microphone reading (serial level) in turn.

Running:

```bash
python -m mpremote connect COM7 run testare/test_mic_difuzor.py
```

What you need to see:

- OK: I2S TX written. You should hear a tone. (speaker);
- I2S RX OK. Trying to record... (microphone);
- non-zero values for Peak L, Peak R, max when speaking into the microphone.

Quick interpretation:

- Very low signal -> problem on SD microphone / clock / power supply;
- Blocked/saturated signal -> check L/R, WS/SCK, common GND;
- Microphone seems active. -> test passed.

## What each file does

### The root of the project

| File | Role |
|------|------|
| `.env.example` | Example of environment variables for the PC side |
| `.gitignore` | Files/folders excluded from git (ex: .env, secrets.py, .venv) |
| `.micropico` | Configuration for uploading/running MicroPython (tooling) |
| `.vscode/extensions.json` | Recommended extensions for VS Code/Cursor |
| `.vscode/settings.json` | Editor local settings for the project |
| `CONTEXT.md` | Placeholder file (currently empty) |
| `HARDWARE_LMS_ESP32_ANTONS.md` | LMS-ESP32 hardware notes used in the paper |
| `Project Report 2.0 3 Ways of Garbage (2).pdf` | PDF project documentation |
| `README.md` | Main project documentation |
| `RECOVERY.md` | Recovery steps for REPL/mpremote |
| `boot.py` | Boot script on ESP32 |
| `lpf2.py` | LPF2 implementation/protocol used in LEGO communication |
| `main.py` | Main script for LEGO Hub (Pybricks) |
| `main_robot.py` | Main firmware on ESP32 (camera, MQTT, audio, hub connection) |
| `child_memory.json` | Local storage for conversation memory |
| `pupremote.py` | PUPRemote library for connecting ESP32 <-> LEGO Hub |
| `pyhuskylens.py` | Driver/interface for HuskyLens camera |
| `rep` | Local marker for REPL mode on device |
| `requirements.txt` | Python dependencies for the PC side |
| `run_esp32.ps1` | PowerShell script to run main_robot.py via mpremote |
| `run_trisense_brain.py` | Entrypoint for the PC brain in standard mode |
| `run_voice_dialog.py` | Entrypoint for PC brain with TCP voice server |
| `secrets.example.py` | Example of secrets for ESP32 |
| `testing/` | Folder with test scripts (audio, MQTT, laptop microphone) |
| `testing/README.md` | Quick guide to running all test scripts |
| `test/mqtt_speak_test.py` | Test utility for MQTT speak commands |
| `test/mqtt_voice_listen_test.py` | Test utility for MQTT listen command (voice) |
| `test/test_i2s_beep.py` | I2S audio test (speaker) on ESP32 |
| `test/test_mic_difuzor.py` | Combined microphone + speaker test on ESP32 |
| `test/test_laptop_mic.py` | Local laptop microphone test -> STT -> TriSense response |
| `trisense_metrics.csv` | Brain Running Metrics Log |

### The trisense package/ simply explained

Think of `trisense/` as the robot's "control room":

| File | Simple explanation |
|------|---------------------|
| `trisense/brain.py` | It is the "boss" who coordinates everything: what the robot sees, what response it gives, when it moves on to the next step. |
| `trisense/ai_client.py` | Talk to the AI (Gemini) to generate friendly responses |
| `trisense/config.py` | "Project settings": MQTT broker, ports, topic names, files |
| `trisense/mqtt_layer.py` | Connects via MQTT between robot and laptop |
| `trisense/memory_store.py` | Remember simple information (e.g. child's name) |
| `trisense/tts_engine.py` | Turn text into speech on your laptop (if enabled) |
| `trisense/voice_tcp_server.py` | Receive audio from the robot when using voice mode |
| `trisense/audio_push.py` | Send audio from laptop to robot |
| `trisense/metrics_logger.py` | Save statistics (e.g. reaction times) |
| `trisense/states.py` | Defines the game states (START, GREETINGS, ACTIVITY, END) |
| `trisense/__init__.py` | Python package technical file |

In short: brain.py decides, ai_client.py generates the text, mqtt_layer.py sends/communicates, and the rest of the modules help with memory, voice, and statistics.

## Important notes

- Do not publish API keys or Wi-Fi passwords in the repository.
- If LPF2 desynchronization or upload problems occur, see RECOVERY.md.
- For hardware and pin debugging, use HARDWARE_LMS_ESP32_ANTONS.md.
