# TriSense testing

This folder holds test scripts for hardware and communication.

## Which script do you run

| Script | What it does |
|--------|----------------|
| `test_i2s_beep.py` | Quick speaker I2S test (MAX98357) |
| `test_mic_difuzor.py` | Speaker + I2S mic test (INMP441) |
| `mqtt_speak_test.py` | Sends MQTT `speak` command to the robot |
| `demo_speak_tcp.py` | TTS on PC (pyttsx3) → PCM over TCP to ESP speaker (no MQTT / Gemini on ESP) |
| `mqtt_voice_listen_test.py` | Sends MQTT `listen` command for TCP voice flow |
| `test_laptop_mic.py` | Local laptop mic → STT → LLM → TTS → ESP |
| `test_motor_integration.py` | Smoke MQTT (`robot/control` + optional `vision/tags`) for hub motions |

## Pin map

### ESP32 -> MAX98357A (I2S speaker)

| MAX98357A | ESP32 | Notes |
|-----------|-------|-------|
| `VIN` | `3V3` or `5V` | Depends on module; use the power rating your board needs |
| `GND` | `GND` | Common ground with ESP32 and other modules |
| `BCLK` | `GPIO 14` | I2S bit clock |
| `LRC` / `LRCLK` | `GPIO 15` | I2S word select |
| `DIN` | `GPIO 26` | Audio data ESP32 → amplifier |
| `SD` / `EN` | `GPIO 32` | Amplifier enable (if your module has this pin) |

### ESP32 -> INMP441 (I2S microphone)

| INMP441 | ESP32 | Notes |
|---------|-------|-------|
| `VDD` | `3V3` | Do **not** power the mic from 5V |
| `GND` | `GND` | Common ground |
| `SCK` / `BCLK` | `GPIO 14` | Same clock as speaker |
| `WS` / `LRCL` | `GPIO 15` | Same word select as speaker |
| `SD` / `DOUT` | `GPIO 33` | Mic data → ESP32 |
| `L/R` | `GND` | Channel select; if test shows only one channel, try `3V3` too |

### ESP32 -> HuskyLens (I2C)

| HuskyLens | ESP32 | Notes |
|-----------|-------|-------|
| `VCC` | `5V` | Stable supply for HuskyLens |
| `GND` | `GND` | Common ground |
| `SDA` | `GPIO 21` | I2C data |
| `SCL` | `GPIO 22` | I2C clock |

### ESP32 -> LEGO Hub / LPF2

| LPF2 / Hub | ESP32 | Notes |
|------------|-------|-------|
| `TX/RX LPF2` | `GPIO 4` | Pin used by `PUPRemoteSensor` |
| `GND` | `GND` | Common ground |
| Power | per LEGO Hub | Check levels before wiring |

### Network and ports

| Thing | Value |
|-------|-------|
| Wi-Fi SSID | `Orange-292q-2.4G` |
| MQTT broker PC | `192.168.100.134` |
| PC voice TCP | `8765` |
| ESP audio TCP | `8766` |

### Watch the solder joints

- `SCK` and `WS` must not short together.
- Mic and speaker share `GPIO 14` and `GPIO 15` but have separate data pins.
- Mic uses `GPIO 33` for data.
- Speaker uses `GPIO 26` for data.
- All modules need a common `GND`.

## Useful commands

### 1) Speaker test on ESP32

```bash
python -m mpremote connect COM7 run testare/test_i2s_beep.py
```

### 2) Speaker + mic test on ESP32

```bash
python -m mpremote connect COM7 run testare/test_mic_difuzor.py
```

### 3) MQTT speak test

```bash
py testare/mqtt_speak_test.py "Hi, I'm TriSense!"
```

### 4) MQTT listen test

```bash
py testare/mqtt_voice_listen_test.py 192.168.1.50
```

### 5) Laptop mic (end-to-end)

```bash
py testare/test_laptop_mic.py
```

### 6) Motor smoke MQTT + fake vision

```bash
py testare/test_motor_integration.py
py testare/test_motor_integration.py --cmd 12 --pause 2
py testare/test_motor_integration.py --actions play_greeting
py testare/test_motor_integration.py --vision-id 21
```

The last line publishes `vision/tags` (camera simulation): run **TriSenseBrain** on the PC if you want the full vision→motor chain with `VISION_ID_TO_ACTION`.

### Contest demo — STEP 3 / 4 / 5

| STEP | Role | What you run |
|------|------|--------------|
| 3 | Stable hello without Gemini in the first minute | PCM `greeting.pcm` at boot + MQTT `action` = `play_greeting` (repeat); or **demo_speak_tcp** on `:8766` |
| 4 | Breathing show (~35 s) | Hub **cmd 12** with `action` = `breathing_show`; PC voice can run in parallel |
| 5 | Mini chat + gestures | **run_voice_dialog** + MQTT `listen`; e.g. word **football** → right hand (see `brain.py`) |

## Notes

- Before MQTT tests, make sure `MQTT_BROKER` and `MQTT_PORT` in `.env` are right.
- **STEP 5 (one sports word)**: In logs look for `Voce TCP transcriere:` after dictation — if transcription is empty or has no `football` / `soccer` / `fotbal` (however Gemini writes it in ASCII letters), the gesture won’t fire. Restart the brain after code changes; if you see `MQTT indisponibil`, the broker wasn’t ready before the gesture command.
- If you use another board/port, replace `COM7` in the commands.
