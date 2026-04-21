# Testare TriSense

Acest folder contine scripturile de test pentru hardware si comunicare.

## Ce script rulezi

| Script | Scop |
|--------|------|
| `test_i2s_beep.py` | Test rapid difuzor I2S (MAX98357) |
| `test_mic_difuzor.py` | Test difuzor + microfon I2S (INMP441) |
| `mqtt_speak_test.py` | Trimite comanda MQTT `speak` catre robot |
| `mqtt_voice_listen_test.py` | Trimite comanda MQTT `listen` pentru flux vocal TCP |
| `test_laptop_mic.py` | Test local microfon laptop -> STT -> LLM -> TTS -> ESP |

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
