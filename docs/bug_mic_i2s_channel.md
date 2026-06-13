# Bug: Microfon INMP441 — semnal zero la voce (I2S canal greșit)

## Simptom

- `testare/test_mic_only.py` raporta `max=0` la toate rundele când se vorbea.
- La apăsarea degetului pe microfon → `max=32767` (funcționa).
- `run_voice_dialog.py` transcria `00:00` sau text gol după înregistrarea ESP.
- STT Gemini primea PCM de 320 KB dar fără conținut audio real.

## Cauza

Două probleme cumulate:

### 1. ID I2S greșit în scriptul de test (`test_mic_only.py`)
```python
# GREȘIT — I2S(0) e periferialul difuzorului (TX)
mic = I2S(0, ..., mode=I2S.RX, ...)

# CORECT — microfonul folosește I2S(1)
mic = I2S(1, ..., mode=I2S.RX, ...)
```

### 2. Canal I2S greșit — MONO vs STEREO (principal)

INMP441 cu `L/R = GND` transmite audio pe **canalul RIGHT** în protocolul Philips I2S
(WS=LOW corespunde RIGHT în acest caz).

`format=I2S.MONO` pe MicroPython ESP32 citea **canalul LEFT** (bytes 0-1 din fiecare
frame de 4 bytes) → zero pentru voce.

Presiunea degetului creează o variație de presiune atât de mare încât saturează
ambele canale simultan → de aceea `max=32767` la atingere chiar și cu codul greșit.

**Raw bytes confirmare** (STEREO mode):
```
00 00 75 fc  00 00 72 fc  ...
^--- LEFT=0  ^--- RIGHT=-903 (semnal real)
```

## Fix

### `testare/test_mic_only.py`
```python
# 1. I2S(1) în loc de I2S(0)
# 2. format=I2S.STEREO în loc de I2S.MONO
# 3. Extrage canalul RIGHT (bytes 2-3 din fiecare frame de 4B):
s = struct.unpack_from("<h", buf, i * 4 + 2)[0]  # RIGHT channel
```

### `main_robot.py` — `tri_record_send_tcp()`
```python
# format=I2S.STEREO, ibuf=32000
# Extrage RIGHT si trimite ca PCM mono catre PC:
mono_buf[i*2]   = stereo_buf[i*4 + 2]
mono_buf[i*2+1] = stereo_buf[i*4 + 3]
```

## Verificare

Dupa fix, `testare/test_mic_only.py` arata semnal real la voce:
```
Runda  7 | max= 7027 | [######------------------------]
Runda 10 | max= 7787 | [#######-----------------------]
MICROFON OK!
```

## Note

- Dacă `L/R = 3.3V` → audio pe canalul LEFT (bytes 0-1, offset `i*4`).
- Cablajul actual: `L/R = GND` → RIGHT (offset `i*4 + 2`).
- `test_mic_difuzor.py` era deja corect: folosea `I2S(1)` și `format=I2S.STEREO`.
