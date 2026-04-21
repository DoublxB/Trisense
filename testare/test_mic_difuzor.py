# test_mic_difuzor.py — MicroPython ESP32 (LMS-ESP32 / TriSense)
# Test difuzor + amplificator (beep), apoi microfon I2S (nivel pe serial).
# Fara HuskyLens, fara MQTT. DOAR ASCII in print().
#
# Cablaj tipic (aliniat la main_robot + INMP441):
#   MAX98357: Vin GND, BCLK=14, LRC=15, DIN=26, EN=32 (sau SD modul la 3.3V)
#   INMP441:  VDD=3V3, GND, L/R=GND, WS=15, SCK=14, SD(date mic)=33
# Daca microfonul e pe acelasi BCLK/LRC: testele sunt pe rand (TX apoi RX).

from machine import I2S, Pin
import time
import struct
import math


def _p(msg):
    """Print + flush: pe serial uneori ramane in buffer; evita caractere non-ASCII in mesaje."""
    print(msg)
    try:
        import sys

        sys.stdout.flush()
    except Exception:
        pass

# --- Difuzor (MAX98357) — aceiasi pini ca main_robot.py ---
SPK_BCLK = 14
SPK_LRC = 15
SPK_DIN = 26
AMP_EN = 32

# --- Microfon (INMP441 / compatibil I2S) — iesire date pe GPIO 33 ---
MIC_SD = 33
MIC_RATE = 16000
MIC_BITS = 16


def wifi_off():
    try:
        import network

        network.WLAN(network.STA_IF).active(False)
        network.WLAN(network.AP_IF).active(False)
        print("WiFi oprit (recomandat pentru test I2S).")
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


def test_difuzor():
    """Ton scurt pe difuzor — verifica amplificator + conexiuni."""
    print("=== DIFUZOR + amplificator (beep ~0.4s) ===")
    try:
        en = Pin(AMP_EN, Pin.OUT)
        en.value(1)
    except Exception as e:
        print("AMP enable err:", e)
    time.sleep_ms(80)

    buf = buf_sine_stereo(44100, 440, 0.4, amp=30000)
    audio = None
    try:
        audio = I2S(
            0,
            sck=Pin(SPK_BCLK),
            ws=Pin(SPK_LRC),
            sd=Pin(SPK_DIN),
            mode=I2S.TX,
            bits=16,
            format=I2S.STEREO,
            rate=44100,
            ibuf=40000,
        )
        audio.write(buf)
        print("OK: I2S TX scris. Ar trebui sa auzi un ton.")
    except Exception as e:
        print("I2S TX esuat:", e)
    finally:
        try:
            if audio:
                audio.deinit()
        except Exception:
            pass
    time.sleep_ms(100)
    print("")


def _samp_i16_le(buf, off):
    s = buf[off] | (buf[off + 1] << 8)
    if s >= 32768:
        s -= 65536
    return s


def test_microfon():
    """Citeste esantioane I2S RX; tipareste nivel maxim (vorbeste spre microfon)."""
    _p("=== MICROFON (I2S RX) ===")
    _p("RX: STEREO 16-bit L+R (MONO driver poate da 0 pe un slot).")
    _p("Nu misca firele in timpul testului.")
    _p("Pe breadboard contact slab => uneori R mare, apoi tot 0.")
    _p("Vorbeste spre microfon dupa 'Incep inregistrarea'.")
    time.sleep_ms(300)

    audio_in = None
    try:
        audio_in = I2S(
            1,
            sck=Pin(SPK_BCLK),
            ws=Pin(SPK_LRC),
            sd=Pin(MIC_SD),
            mode=I2S.RX,
            bits=MIC_BITS,
            format=I2S.STEREO,
            rate=MIC_RATE,
            ibuf=16000,
        )
        _p("I2S RX OK. Incerc inregistrarea ~2.5s (nu apasa Ctrl+C).")
    except Exception as e:
        _p("I2S RX init esuat: " + str(e))
        _p(
            "Verifica SD mic GPIO "
            + str(MIC_SD)
            + " WS/BCLK "
            + str(SPK_LRC)
            + "/"
            + str(SPK_BCLK)
        )
        return

    buf = bytearray(2048)
    mx = 0
    mx_l = 0
    mx_r = 0
    sample_cnt = 0
    sat_neg = 0
    sat_pos = 0
    avg_abs = 0
    rounds = 40
    total_read = 0
    zero_reads = 0
    first_nonzero_dump = None
    try:
        _p("Incep inregistrarea.")
        # Warm-up (uneori primele bucati sunt goale)
        for _ in range(4):
            audio_in.readinto(buf)
            time.sleep_ms(20)

        for ri in range(rounds):
            n = audio_in.readinto(buf)
            if not n:
                zero_reads += 1
                time.sleep_ms(50)
                continue
            total_read += n
            if ri % 10 == 0:
                _p("... citire " + str(ri) + "/" + str(rounds))
            # stereo: 4 octeti / cadru (L int16, R int16)
            n_frames = n // 4
            for f in range(n_frames):
                off = f * 4
                sl = _samp_i16_le(buf, off)
                sr = _samp_i16_le(buf, off + 2)
                if abs(sl) > mx_l:
                    mx_l = abs(sl)
                if abs(sr) > mx_r:
                    mx_r = abs(sr)
                for s in (sl, sr):
                    if s <= -32760:
                        sat_neg += 1
                    elif s >= 32760:
                        sat_pos += 1
                    a = s if s >= 0 else -s
                    if a > 32767:
                        a = 32767
                    if a > mx:
                        mx = a
                    avg_abs += a
                    sample_cnt += 1
            if first_nonzero_dump is None and n >= 16:
                first_nonzero_dump = bytes(buf[:16])
            time.sleep_ms(50)
        _p("Octeti cititi (total): " + str(total_read) + " | citiri goale: " + str(zero_reads))
        _p(
            "Varf L: "
            + str(mx_l)
            + " | R: "
            + str(mx_r)
            + " | max: "
            + str(mx)
            + " / 32767"
        )
        if sample_cnt > 0:
            avg_abs = avg_abs // sample_cnt
            sat_pct = ((sat_neg + sat_pos) * 100) // sample_cnt
            _p("Mediu abs: " + str(avg_abs) + " | saturatie %: " + str(sat_pct))
        else:
            sat_pct = 0

        if total_read == 0:
            _p("readinto=0 mereu: port/rate sau RX esuat.")
        elif mx < 200 and first_nonzero_dump:
            hx = "".join("%02x " % b for b in first_nonzero_dump)
            _p("Primele 16 B: " + hx)

        if mx < 200:
            _p("Semnal foarte mic: fir SD/ceas/VDD mic sau contact breadboard.")
            _p("Daca doar L sau doar R mare: muta L/R INMP441 intre GND si 3V3.")
        elif sat_pct > 85:
            _p("Semnal blocat/saturat: verifica L/R, SD, WS/SCK, GND comun.")
        else:
            _p("Microfon pare activ.")
    except Exception as e:
        _p("Citire mic esuata: " + str(e))
    finally:
        try:
            audio_in.deinit()
        except Exception:
            pass
    print("")


print("TriSense test audio: difuzor apoi microfon (fara camera).")
wifi_off()
time.sleep_ms(150)

test_difuzor()
test_microfon()

print("Gata. Pentru voce Gemini pe difuzor: main_robot.py + secrets.py + creier PC.")
print("Daca RX esueaza: opreste microfonul de pe bus si retest doar difuzor cu test_i2s_beep.py")
