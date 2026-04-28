# Testare TriSense

Acest folder contine scripturile de test pentru hardware si comunicare.

## Ce script rulezi

| Script | Scop |
|--------|------|
| `test_i2s_beep.py` | Test rapid difuzor I2S (MAX98357) |
| `test_mic_difuzor.py` | Test difuzor + microfon I2S (INMP441) |
| `mqtt_speak_test.py` | Trimite comanda MQTT `speak` catre robot |
| `demo_speak_tcp.py` | TTS pe PC (pyttsx3) → PCM TCP la difuzor ESP (fara MQTT / Gemini pe ESP) |
| `mqtt_voice_listen_test.py` | Trimite comanda MQTT `listen` pentru flux vocal TCP |
| `test_laptop_mic.py` | Test local microfon laptop -> STT -> LLM -> TTS -> ESP |

## Schema pini

### ESP32 -> MAX98357A (difuzor I2S)

| MAX98357A | ESP32 | Observatii |
|-----------|-------|------------|
| `VIN` | `3V3` sau `5V` | Depinde de modul; foloseste alimentarea recomandata pentru placa ta |
| `GND` | `GND` | Masa comuna cu ESP32 si restul modulelor |
| `BCLK` | `GPIO 14` | I2S bit clock |
| `LRC` / `LRCLK` | `GPIO 15` | I2S word select |
| `DIN` | `GPIO 26` | Date audio ESP32 -> amplificator |
| `SD` / `EN` | `GPIO 32` | Enable amplificator, daca modulul are pinul acesta |

### ESP32 -> INMP441 (microfon I2S)

| INMP441 | ESP32 | Observatii |
|---------|-------|------------|
| `VDD` | `3V3` | Nu alimenta microfonul la 5V |
| `GND` | `GND` | Masa comuna |
| `SCK` / `BCLK` | `GPIO 14` | Acelasi clock ca difuzorul |
| `WS` / `LRCL` | `GPIO 15` | Acelasi word select ca difuzorul |
| `SD` / `DOUT` | `GPIO 33` | Date audio microfon -> ESP32 |
| `L/R` | `GND` | Selectie canal; daca testul indica doar un canal, incearca si `3V3` |

### ESP32 -> HuskyLens (I2C)

| HuskyLens | ESP32 | Observatii |
|-----------|-------|------------|
| `VCC` | `5V` | Alimentare stabila pentru HuskyLens |
| `GND` | `GND` | Masa comuna |
| `SDA` | `GPIO 21` | I2C data |
| `SCL` | `GPIO 22` | I2C clock |

### ESP32 -> LEGO Hub / LPF2

| LPF2 / Hub | ESP32 | Observatii |
|------------|-------|------------|
| `TX/RX LPF2` | `GPIO 4` | Pin folosit de `PUPRemoteSensor` |
| `GND` | `GND` | Masa comuna |
| Alimentare | conform LEGO Hub | Verifica nivelurile si alimentarea inainte de conectare |

### Retea si porturi

| Componenta | Valoare |
|------------|---------|
| Wi-Fi SSID | `Orange-292q-2.4G` |
| MQTT broker PC | `192.168.100.134` |
| PC voice TCP | `8765` |
| ESP audio TCP | `8766` |

### Atentie la lipituri

- `SCK` si `WS` nu trebuie sa se atinga intre ele.
- Microfonul si difuzorul impart `GPIO 14` si `GPIO 15`, dar au pini separati de date.
- Microfonul foloseste `GPIO 33` pentru date.
- Difuzorul foloseste `GPIO 26` pentru date.
- Toate modulele trebuie sa aiba `GND` comun.

## Comenzi utile

### 1) Test difuzor pe ESP32

```bash
python -m mpremote connect COM7 run testare/test_i2s_beep.py
```

### 2) Test difuzor + microfon pe ESP32

```bash
python -m mpremote connect COM7 run testare/test_mic_difuzor.py
```

### 3) Test speak prin MQTT

```bash
py testare/mqtt_speak_test.py "Salut, sunt TriSense!"
```

### 4) Test listen prin MQTT

```bash
py testare/mqtt_voice_listen_test.py 192.168.1.50
```

### 5) Test microfon laptop (end-to-end)

```bash
py testare/test_laptop_mic.py
```

## Observatii

- Inainte de testele MQTT, asigura-te ca `MQTT_BROKER` si `MQTT_PORT` sunt corecte in `.env`.
- Pentru testele audio ESP, inchide orice alta sesiune care foloseste acelasi port serial.
- Daca folosesti alta placa/alt port, inlocuieste `COM7` in comenzi.
