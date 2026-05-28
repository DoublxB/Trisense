# test_mic_only.py — MicroPython ESP32
# Test DOAR microfon INMP441 (fara difuzor, fara MQTT, fara HuskyLens).
# Cablaj: VDD=3V3, GND=GND, SCK=14, WS=15, SD=33, L/R=GND
# Daca MAX98357 are SD/EN pe GPIO32, testul il tine oprit ca sa nu bazaie.

from machine import I2S, Pin
import time
import struct

SCK_PIN = 14
WS_PIN  = 15
SD_PIN  = 33
SPK_DIN_PIN = 26
AMP_ENABLE_PIN = 32
RATE    = 16000

print("=== TEST MICROFON INMP441 ===")
print("SCK=14  WS=15  SD=33  VDD=3V3  GND=GND  L/R=GND")
print("")

# Mic-ul si difuzorul impart BCLK/LRC. Cand porneste I2S RX, MAX98357 poate
# interpreta clock-urile ca audio si bazaie daca ramane activ sau DIN pluteste.
try:
    Pin(AMP_ENABLE_PIN, Pin.OUT).value(0)
    Pin(SPK_DIN_PIN, Pin.OUT).value(0)
    print("Difuzor/amplificator oprit pentru test (EN=GPIO32 LOW, DIN=GPIO26 LOW).")
except Exception as e:
    print("Nu pot opri difuzorul din software:", e)


try:
    import network
    network.WLAN(network.STA_IF).active(False)
    network.WLAN(network.AP_IF).active(False)
    print("WiFi oprit.")
except Exception:
    pass

time.sleep_ms(200)

mic = None
try:
    mic = I2S(
        0,
        sck=Pin(SCK_PIN),
        ws=Pin(WS_PIN),
        sd=Pin(SD_PIN),
        mode=I2S.RX,
        bits=16,
        format=I2S.MONO,
        rate=RATE,
        ibuf=8000,
    )
    print("I2S RX init OK (16-bit MONO).")
except Exception as e:
    print("EROARE I2S init:", e)
    raise SystemExit

buf = bytearray(2048)

# INMP441 are nevoie de ~200ms dupa ce porneste BCLK ca sa se sincronizeze.
# Fara delay, pe a doua rulare (dupa deinit anterior) da tot 0x00.
time.sleep_ms(300)

# Warm-up: citim si aruncam pana microfonul iese din starea tranzitorie.
for _ in range(20):
    mic.readinto(buf)
    time.sleep_ms(10)

# Print raw bytes pt debug
mic.readinto(buf)
print("Raw primii 32 bytes:", " ".join("%02x" % b for b in buf[:32]))
print("")
print("Vorbeste tare spre microfon (10 runde x ~130ms)...")
print("")

for runda in range(10):
    n = mic.readinto(buf)
    if not n:
        print("Runda %2d | EROARE: readinto=0" % (runda + 1))
        continue

    mx = 0
    n_samples = n // 2
    for i in range(n_samples):
        s = struct.unpack_from("<h", buf, i * 2)[0]
        v = abs(s)
        if v > mx:
            mx = v

    bari = min(mx * 30 // 32767, 30)
    bara = "#" * bari + "-" * (30 - bari)
    print("Runda %2d | max=%5d | [%s]" % (runda + 1, mx, bara))
    time.sleep_ms(130)

mic.deinit()
print("")
if mx > 500:
    print("MICROFON OK!")
else:
    print("Semnal mic/nul. Verifica:")
    print("  1. Firul SD -> GPIO 33 (contact slab?)")
    print("  2. VDD -> 3.3V (nu 5V!)")
    print("  3. GND comun cu ESP32")
    print("  4. Incearca L/R la 3.3V in loc de GND")
