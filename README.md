# TriSense - ghid simplu pentru echipa

TriSense este un robot prietenos care:
- vede cu camera (HuskyLens),
- vorbeste cu voce prietenoasa,
- recunoaste un copil si piese LEGO,
- raspunde printr-un "creier" care ruleaza pe laptop.

## Ce face proiectul, pe scurt

Imagineaza-ti TriSense ca un joc in 2 parti:
- **Robotul (ESP32)** = "corpul" (camera, sunet, conexiune cu hub-ul LEGO).
- **Laptopul (Python + trisense)** = "creierul" (gandeste raspunsul si decide ce zice robotul).

Cand camera vede ceva:
1. Robotul trimite un mesaj.
2. Creierul de pe laptop il intelege.
3. TriSense raspunde cu un mesaj scurt si pozitiv.

## Componente importante

| Componenta | Ce face (pe intelesul tuturor) |
|------------|---------------------------------|
| `main_robot.py` | Programul principal de pe robot (camera + audio + MQTT) |
| `run_trisense_brain.py` + `trisense/` | Programul de pe laptop care "gandeste" raspunsul |
| `run_voice_dialog.py` + `trisense/voice_tcp_server.py` | Varianta in care robotul trimite vocea la laptop (server TCP pentru audio) |
| `RECOVERY.md` | Ce faci daca upload-ul/repl nu merge |
| `HARDWARE_LMS_ESP32_ANTONS.md` | Note hardware utile pentru placa LMS-ESP32 |

## Hardware LMS-ESP32 (Anton's Mindstorms)

Documentatie oficiala:
- **Pinout:** <https://www.antonsmindstorms.com/docs/lms-esp32-v2-pinout/>
- **Getting started:** <https://www.antonsmindstorms.com/docs/getting-started-with-your-new-lms-esp32v2-board/>
- **Toate placile de expansiune:** <https://www.antonsmindstorms.com/doc-category/expansion-board-documentation/>

## Schema pini (TriSense)

Maparea folosita in codul curent (`main_robot.py`):

| Modul | Semnal | GPIO | Observatii |
|------|--------|------|------------|
| Hub LEGO (LPF2/PUPRemote) | UART catre hub | `7/8` | Linie dedicata LMS-ESP32 pentru legatura cu hub-ul LEGO |
| HuskyLens (I2C) | `SCL` | `22` | `SoftI2C(scl=Pin(22), sda=Pin(21))` |
| HuskyLens (I2C) | `SDA` | `21` | Implicit pentru camera in proiect |
| Difuzor I2S (MAX98357) | `BCLK` | `14` | Clock audio I2S (`SCK` pe microfon) |
| Difuzor I2S (MAX98357) | `LRC/WS` | `15` | Word select I2S |
| Difuzor I2S (MAX98357) | `DIN` | `26` | Date audio catre amplificator |
| Amplificator | `EN` | `32` | Activare amplificator |
| Microfon I2S (INMP441) | `SD` | `33` | Date microfon (RX), pe acelasi `SCK/BCLK` si `WS/LRC` |

Schema rapida:

```text
LMS-ESP32
├─ Hub LEGO (UART): GPIO 7/8
├─ HuskyLens I2C: SCL=22, SDA=21
└─ Audio
   ├─ MAX98357 (speaker): BCLK=14, LRC=15, DIN=26, EN=32
   └─ INMP441 (mic): SD=33 (share SCK/BCLK=14, WS/LRC=15)
```

Nota: evita schimbarea pinilor `7/8` daca legatura cu hub-ul functioneaza; sunt critici pentru handshake LPF2 pe LMS-ESP32.

## Screenshot cablaj simulator (de completat)

Adauga aici imaginea cu cablajul vizual din simulator:

```md
![Cablaj TriSense in simulator](./docs/simulator-cablaj.png)
```

Checklist rapid pentru poza:
- sa se vada clar placa LMS-ESP32;
- sa se vada legaturile pentru HuskyLens, microfon si difuzor;
- sa se vada etichetele pinilor (GPIO).

Poti crea folderul `docs/` si sa pui screenshot-ul acolo.

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

- Ruleaza firmware-ul din `main_robot.py` pe placa LMS-ESP32 (din folderul proiectului inlocuiesti COM7 dupa cum apare ESP-ul in Device Manager):

```bash
python -m mpremote connect COM7 run main_robot.py
```

- Creeaza `secrets.py` pe ESP (nu in repo) pentru chei/date locale (ex: `GEMINI_API_KEY`, `PC_VOICE_IP`).
- Verifica reteaua Wi-Fi si brokerul MQTT din configurarea ESP.

## Teste audio hardware (difuzor + microfon)

Inainte de test:
- conecteaza placa pe portul serial corect (ex. `COM7`);
- opreste orice rulare anterioara (`main_robot.py`) din acelasi port;
- foloseste aceleasi legaturi din schema de pini (`BCLK=14`, `LRC=15`, `DIN=26`, `MIC_SD=33`).

### Test difuzor (MAX98357)

Script: `testare/test_i2s_beep.py`  
Rol: verifica strict lantul I2S TX + amplificator + difuzor (fara MQTT/HuskyLens).

Rulare:

```bash
python -m mpremote connect COM7 run testare/test_i2s_beep.py
```

Ce trebuie sa vezi/auzi:
- in serial: `I2S0 init OK 44100 STEREO`, apoi `write runda ...`;
- pe difuzor: ton de test (beep/sine) repetat.

Daca e liniste:
- verifica alimentarea modulului MAX98357 (`Vin`, `GND`);
- verifica `DIN/BCLK/LRC` si pinul de enable;
- testeaza cu alt difuzor sau leaga `SD/EN` modul direct la `3.3V` (cum mentioneaza scriptul).

### Test microfon + difuzor (INMP441 + MAX98357)

Script: `testare/test_mic_difuzor.py`  
Rol: ruleaza pe rand testul de difuzor si apoi citirea microfonului I2S (nivel pe serial).

Rulare:

```bash
python -m mpremote connect COM7 run testare/test_mic_difuzor.py
```

Ce trebuie sa vezi:
- `OK: I2S TX scris. Ar trebui sa auzi un ton.` (difuzor);
- `I2S RX OK. Incerc inregistrarea...` (microfon);
- valori nenule pentru `Varf L`, `Varf R`, `max` cand vorbesti spre microfon.

Interpretare rapida:
- `Semnal foarte mic` -> problema pe `SD` microfon / ceas / alimentare;
- `Semnal blocat/saturat` -> verificare `L/R`, `WS/SCK`, `GND comun`;
- `Microfon pare activ.` -> test trecut.

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
| `pupremote.py` | Biblioteca PUPRemote pentru legatura ESP32 <-> Hub LEGO |
| `pyhuskylens.py` | Driver/interfata pentru camera HuskyLens |
| `repl` | Marker local pentru mod de lucru REPL pe device |
| `requirements.txt` | Dependinte Python pentru partea PC |
| `run_esp32.ps1` | Script PowerShell pentru rulare `main_robot.py` prin mpremote |
| `run_trisense_brain.py` | Entrypoint pentru creierul PC in modul standard |
| `run_voice_dialog.py` | Entrypoint pentru creierul PC cu server TCP de voce |
| `secrets.example.py` | Exemplu de secrete pentru ESP32 |
| `testare/` | Folder cu scripturi de test (audio, MQTT, microfon laptop) |
| `testare/README.md` | Ghid rapid pentru rularea tuturor scripturilor de test |
| `testare/mqtt_speak_test.py` | Utilitar de test pentru comenzi MQTT de tip `speak` |
| `testare/mqtt_voice_listen_test.py` | Utilitar de test pentru comanda MQTT `listen` (voce) |
| `testare/test_i2s_beep.py` | Test audio I2S (difuzor) pe ESP32 |
| `testare/test_mic_difuzor.py` | Test combinat microfon + difuzor pe ESP32 |
| `testare/test_laptop_mic.py` | Test local microfon laptop -> STT -> raspuns TriSense |
| `trisense_metrics.csv` | Log de metrici pentru rularea creierului |

### Pachetul `trisense/` explicat simplu

Gandeste-te la `trisense/` ca la "camera de control" a robotului:

| Fisier | Explicatie simpla |
|--------|-------------------|
| `trisense/brain.py` | Este "seful" care coordoneaza tot: ce vede robotul, ce raspuns da, cand trece la urmatorul pas |
| `trisense/ai_client.py` | Vorbeste cu AI-ul (Gemini) ca sa genereze raspunsuri prietenoase |
| `trisense/config.py` | "Setarile proiectului": broker MQTT, porturi, nume topicuri, fisiere |
| `trisense/mqtt_layer.py` | Face legatura prin MQTT intre robot si laptop |
| `trisense/memory_store.py` | Tine minte informatii simple (de exemplu numele copilului) |
| `trisense/tts_engine.py` | Transforma textul in voce pe laptop (daca este activat) |
| `trisense/voice_tcp_server.py` | Primeste audio de la robot cand folosesti modul vocal |
| `trisense/audio_push.py` | Trimite audio de pe laptop catre robot |
| `trisense/metrics_logger.py` | Salveaza statistici (de ex. timpi de reactie) |
| `trisense/states.py` | Defineste starile jocului (START, SALUT, ACTIVITATE, FINAL) |
| `trisense/__init__.py` | Fisier tehnic de pachet Python |

Pe scurt: `brain.py` decide, `ai_client.py` genereaza textul, `mqtt_layer.py` trimite/comunica, iar restul modulelor ajuta cu memorie, voce si statistici.

## Observatii importante

- Nu publica chei/API keys sau parole Wi-Fi in repository.
- Daca apare desincronizare LPF2 sau probleme de upload, vezi `RECOVERY.md`.
- Pentru depanare hardware si pini, foloseste `HARDWARE_LMS_ESP32_ANTONS.md`.
