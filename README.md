# TriSense (licenta) - robot terapeutic LEGO + LMS-ESP32

Proiect de licenta cu arhitectura hibrida:
- **ESP32 (MicroPython)**: integrare LEGO Hub (PUPRemote), HuskyLens, Wi-Fi, MQTT, audio I2S.
- **PC (Python)**: "creier" conversational cu Gemini, memorie JSON, TTS si flux optional de dialog vocal prin TCP.

## Arhitectura pe scurt

| Componenta | Rol |
|------------|-----|
| `main_robot.py` | Runtime ESP32: LPF2/PUPRemote, HuskyLens, MQTT, TTS pe robot, audio TCP |
| `run_trisense_brain.py` + `trisense/` | Creier PC standard (MQTT + AI + logica de raspuns) |
| `run_voice_dialog.py` + `trisense/voice_tcp_server.py` | Creier PC cu server TCP pentru vocea captata de ESP |
| `RECOVERY.md` | Proceduri REPL / `mpremote` |
| `HARDWARE_LMS_ESP32_ANTONS.md` | Rezumat hardware LMS-ESP32 pentru proiect |

## Hardware LMS-ESP32 (Anton's Mindstorms)

Documentatie oficiala:
- **Pinout:** <https://www.antonsmindstorms.com/docs/lms-esp32-v2-pinout/>
- **Getting started:** <https://www.antonsmindstorms.com/docs/getting-started-with-your-new-lms-esp32v2-board/>
- **Toate placile de expansiune:** <https://www.antonsmindstorms.com/doc-category/expansion-board-documentation/>

## MQTT (ESP32 <-> PC)

| Topic | Directie | Continut |
|-------|----------|----------|
| `vision/tags` | ESP32 -> broker -> PC | JSON `{"id": N}` (clasa HuskyLens: `1` = fata, `2+` = obiecte LEGO) |
| `robot/control` | PC -> broker -> ESP32 | JSON comenzi (`speak`, `listen`, `pc_host`, `voice_port`, `duration_ms`) |
| `robot/speak` | PC -> broker -> ESP32 | Mesaj retained de salut/mesaj scurt pentru TTS pe robot |

Nota: in `main_robot.py`, MQTT este non-blocking (`check_msg()`), iar bucla LPF2 ramane activa (`pr.process()` / `process_async`).

## Cerinte software (PC)

- Python 3.10+ recomandat
- Dependinte: `requirements.txt`
- API key Gemini in `.env` (`GEMINI_API_KEY`)

Instalare rapida:

```bash
pip install -r requirements.txt
copy .env.example .env
```

Apoi completeaza in `.env`:
- `GEMINI_API_KEY=...`
- optional: `MQTT_BROKER`, `MQTT_PORT`, `MQTT_CLIENT_ID_PC`
- optional voce: `VOICE_TCP_PORT`, `TRISENSE_TTS_PC`, `TRISENSE_TTS_OVER_TCP`

## Rulare pe PC

### 1) Mod standard (creier + MQTT)

```bash
py run_trisense_brain.py
```

Folosit pentru fluxul principal de interactiune prin MQTT.

### 2) Mod dialog vocal (ESP mic -> PC STT/TTS)

```bash
py run_voice_dialog.py
```

Acest mod porneste si serverul TCP de voce (implicit port `8765`), care primeste audio de la ESP.

## Configurare ESP32

- Ruleaza firmware-ul din `main_robot.py` pe placa LMS-ESP32.
- Creeaza `secrets.py` pe ESP (nu in repo) pentru chei/date locale (ex: `GEMINI_API_KEY`, `PC_VOICE_IP`).
- Verifica reteaua Wi-Fi si brokerul MQTT din configurarea ESP.

## Observatii importante

- Nu publica chei/API keys sau parole Wi-Fi in repository.
- Daca apare desincronizare LPF2 sau probleme de upload, vezi `RECOVERY.md`.
- Pentru depanare hardware si pini, foloseste `HARDWARE_LMS_ESP32_ANTONS.md`.
