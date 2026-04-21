# test_i2s_beep.py - MicroPython ESP32 (LMS-ESP32 / TriSense)
# DOAR ASCII in print().
#
# WS = LRC (acelasi semnal). sd= in I2S = linia DATE spre amplificator (DIN).
# Pini: BCLK=14, LRC=15, DIN=26. Enable modul pe GPIO 32 (daca exista).
# Daca tot liniste: deconecteaza microfonul de pe bus (test doar difuzor).

from machine import I2S, Pin
import time
import struct
import math

BCLK_PIN = 14
WS_PIN = 15
DIN_PIN = 26
AMP_ENABLE_PIN = 33

# Opreste WiFi — pe ESP32 poate interfera cu I2S/DMA
def wifi_off():
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
        print("WiFi oprit pentru test I2S.")
    except Exception as e:
        print("WiFi skip:", e)


def buf_sine_stereo(rate_hz, freq_hz, duration_s, amp=30000):
    n = int(rate_hz * duration_s)
    buf = bytearray(n * 4)
    for i in range(n):
        t = i / rate_hz
        v = int(amp * math.sin(2 * math.pi * freq_hz * t))
        struct.pack_into("<hh", buf, i * 4, v, v)
    return buf


def run_beep(enable_high, label):
    print("===", label, "GPIO", AMP_ENABLE_PIN, "=", "HIGH" if enable_high else "LOW", "===")
    en = None
    try:
        en = Pin(AMP_ENABLE_PIN, Pin.OUT)
        en.value(1 if enable_high else 0)
    except Exception as e:
        print("Enable pin eroare:", e)

    time.sleep_ms(80)

    bclk = Pin(BCLK_PIN)
    ws = Pin(WS_PIN)
    din = Pin(DIN_PIN)

    # Buffer ~0.4s ton 440Hz stereo @ 44100
    buf = buf_sine_stereo(44100, 440, 0.4, amp=31000)
    print("Buffer sine bytes:", len(buf))

    audio = None
    try:
        audio = I2S(
            0,
            sck=bclk,
            ws=ws,
            sd=din,
            mode=I2S.TX,
            bits=16,
            format=I2S.STEREO,
            rate=44100,
            ibuf=40000,
        )
        print("I2S0 init OK 44100 STEREO")
    except Exception as e:
        print("I2S init esuat:", e)
        return

    try:
        for k in range(6):
            n = audio.write(buf)
            print("write runda", k + 1, "ret:", n)
            time.sleep_ms(200)
    except Exception as e:
        print("write esuat:", e)
    finally:
        try:
            audio.deinit()
        except Exception:
            pass

    print("--- Sfarsit", label, "---\n")


print("TriSense I2S debug extins")
print("BCLK", BCLK_PIN, "LRC", WS_PIN, "DIN", DIN_PIN)
wifi_off()
time.sleep_ms(100)

print("Verifica hardware MAX98357:")
print("- Vin + GND modul")
print("- Difuzor intre + si -")
print("- SD/EN: unele moduluri trebuie legate la Vin (3.3V) permanent, nu la GPIO")
print("- Daca EN e pe GPIO 32, incercam HIGH apoi LOW\n")

run_beep(True, "Test A enable")
time.sleep_ms(500)
run_beep(False, "Test B enable")

print("Gata. Daca liniste:")
print("1) Leaga SD pin modul la 3.3V (nu GPIO) si ruleaza din nou")
print("2) Schimba BCLK/LRC/DIN cu fire incrucisate (BCLK<->LRC)")
print("3) Incearca alt difuzor / masoara cu multimetru pe Vin modul")
