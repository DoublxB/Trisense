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

## Ce face fiecare fisier

### Radacina proiectului

| Fisier | Rol |
|--------|-----|
| `.env.example` | Exemplu de variabile de mediu pentru partea PC |
| `.gitignore` | Fisiere/foldere excluse din git (ex: `.env`, `secrets.py`, `.venv`) |
| `.micropico` | Configurare pentru upload/rulare MicroPython (tooling) |
| `.vscode/extensions.json` | Extensii recomandate pentru VS Code/Cursor |
| `.vscode/settings.json` | Setari locale editor pentru proiect |
| `CONTEXT.md` | Fisier placeholder (momentan gol) |
| `HARDWARE_LMS_ESP32_ANTONS.md` | Note hardware LMS-ESP32 folosite in lucrare |
| `Project Report 2.0 3 Ways of Garbage (2).pdf` | Documentatie PDF de proiect |
| `README.md` | Documentatia principala a proiectului |
| `RECOVERY.md` | Pasi de recovery pentru REPL/mpremote |
| `boot.py` | Script de boot pe ESP32 |
| `lpf2.py` | Implementare/protocol LPF2 folosit in comunicarea LEGO |
| `main.py` | Script principal pentru Hub LEGO (Pybricks) |
| `main_robot.py` | Firmware principal pe ESP32 (camera, MQTT, audio, legatura hub) |
| `memorie_copil.json` | Stocare locala pentru memoria conversatiilor |
| `mqtt_speak_test.py` | Utilitar de test pentru comenzi MQTT de tip `speak` |
| `mqtt_voice_listen_test.py` | Utilitar de test pentru comanda MQTT `listen` (voce) |
| `pupremote.py` | Biblioteca PUPRemote pentru legatura ESP32 <-> Hub LEGO |
| `pyhuskylens.py` | Driver/interfata pentru camera HuskyLens |
| `repl` | Marker local pentru mod de lucru REPL pe device |
| `requirements.txt` | Dependinte Python pentru partea PC |
| `run_esp32.ps1` | Script PowerShell pentru rulare `main_robot.py` prin mpremote |
| `run_trisense_brain.py` | Entrypoint pentru creierul PC in modul standard |
| `run_voice_dialog.py` | Entrypoint pentru creierul PC cu server TCP de voce |
| `secrets.example.py` | Exemplu de secrete pentru ESP32 |
| `test_i2s_beep.py` | Test audio I2S (difuzor) pe ESP32 |
| `test_mic_difuzor.py` | Test combinat microfon + difuzor pe ESP32 |
| `trisense_metrics.csv` | Log de metrici pentru rularea creierului |

### Pachetul `trisense/`

| Fisier | Rol |
|--------|-----|
| `trisense/__init__.py` | Marker de pachet Python |
| `trisense/ai_client.py` | Client AI (Gemini) pentru raspunsuri/text |
| `trisense/audio_push.py` | Trimite audio de pe PC catre ESP (audio TCP) |
| `trisense/brain.py` | Orchestratorul principal al logicii pe PC |
| `trisense/config.py` | Configurari centralizate (env, topicuri, porturi, fisiere) |
| `trisense/memory_store.py` | Citire/scriere memorie conversationala JSON |
| `trisense/metrics_logger.py` | Logare metrici in CSV |
| `trisense/mqtt_layer.py` | Conexiune MQTT si publish/subscribe |
| `trisense/states.py` | Stari si tipuri auxiliare pentru fluxul conversational |
| `trisense/tts_engine.py` | Sinteza vocala pe PC (pyttsx3 / fallback logic) |
| `trisense/voice_tcp_server.py` | Server TCP pentru audio primit de la ESP32 |

## Observatii importante

- Nu publica chei/API keys sau parole Wi-Fi in repository.
- Daca apare desincronizare LPF2 sau probleme de upload, vezi `RECOVERY.md`.
- Pentru depanare hardware si pini, foloseste `HARDWARE_LMS_ESP32_ANTONS.md`.
