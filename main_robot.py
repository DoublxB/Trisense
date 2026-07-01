from machine import Pin, I2S
from pupremote import PUPRemoteSensor
import asyncio
import time
import json
import struct
import network
from umqtt.simple import MQTTClient

try:
    import _thread
    _HAS_THREAD = True
except ImportError:
    _HAS_THREAD = False

try:
    import errno as _errno

    _SOC_ETIMEDOUT = getattr(_errno, "ETIMEDOUT", 116)
    _SOC_EAGAIN = getattr(_errno, "EAGAIN", 11)
except ImportError:
    _SOC_ETIMEDOUT = 116
    _SOC_EAGAIN = 11


def _sock_recv_err_is_timeout(exc):
    """lwIP/MicroPython ESP32 au coduri diferite pentru socket timeout/EAGAIN."""
    if not isinstance(exc, OSError) or not getattr(exc, "args", None):
        return False
    c = exc.args[0]
    return c in (_SOC_ETIMEDOUT, _SOC_EAGAIN, 110, 116, 118, 119)

print("=== TriSense ESP32 START ===")

# ==========================================
# 0. AUDIO I2S (MAX98357) — scurt feedback, NU lasa I2S deschis in bucla
#     (nu strica LPF2: apeluri scurte intre pr.process). Pini ca la test_i2s_beep.
# ==========================================
AUDIO_ENABLED = True
I2S_BCLK, I2S_LRC, I2S_DIN = 14, 15, 26
AMP_ENABLE_PIN = 32
# Microfon I2S (INMP441): SD pe GPIO 33 — acelasi BCLK/LRC ca difuzorul (vezi testare/test_mic_difuzor.py).
MIC_I2S_SD = 33
MIC_RATE = 16000
VOICE_TCP_PORT_DEFAULT = 8765
VOICE_RECORD_MS_DEFAULT = 10000  # implicit ~10s inregistrare voce TCP
AUDIO_TCP_PLAY_PORT = 8766  # PC -> ESP: redare PCM pe difuzorul robotului


def tri_beep_stereo_ms(duration_ms=100):
    """Ton scurt stereo 44100 Hz, apoi opreste I2S. Esueaza silent daca hardware lipseste."""
    if not AUDIO_ENABLED:
        return
    try:
        rate = 44100
        n = max(100, int(rate * duration_ms / 1000))
        buf = bytearray(n * 4)
        half = 22
        for i in range(n):
            v = 26000 if (i // half) % 2 else -26000
            struct.pack_into("<hh", buf, i * 4, v, v)
        en = Pin(AMP_ENABLE_PIN, Pin.OUT)
        en.value(1)
        time.sleep_ms(5)
        audio = I2S(
            0,
            sck=Pin(I2S_BCLK),
            ws=Pin(I2S_LRC),
            sd=Pin(I2S_DIN),
            mode=I2S.TX,
            bits=16,
            format=I2S.STEREO,
            rate=rate,
            ibuf=20000,
        )
        audio.write(buf)
        audio.deinit()
    except Exception:
        pass


# ==========================================
# 0b. GEMINI TTS pe difuzor (MQTT {"speak": "text"} de la PC)
#     Cheie API: fisier secrets.py pe ESP (GEMINI_API_KEY = "AIza..."), nu in repo.
#     Model: PCM 16-bit mono (24 kHz din API) -> L=R stereo la ACEEASI rata I2S + volum redus.
#     NU resampla 24->44.1 kHz pe I2S: pe multe ESP32 suna "intins" (salllluuut). Beep-ul ramane la 44.1 kHz.
# ==========================================
try:
    from secrets import GEMINI_API_KEY

    GEMINI_API_KEY = GEMINI_API_KEY.strip() if isinstance(GEMINI_API_KEY, str) else ""
except ImportError:
    GEMINI_API_KEY = ""

try:
    import secrets as scr  # fisier ESP secrets.py
except ImportError:
    scr = None


def scr_get(attr, default):  # type: ignore[misc]
    if scr is None:
        return default
    try:
        v = getattr(scr, attr, default)
        return default if v is None else v
    except Exception:
        return default


pending_speak = None
speak_queue = []  # FIFO TTS Gemini: MQTT „speak” + BV (PAS 12)
pending_voice_tcp = None  # {"host","port","duration_ms"} dupa MQTT {"listen": true}
pending_play_greeting = False  # MQTT: redare greeting.pcm (fara Gemini)
# Butoane Hub -> ESP prin LPF2 (canal "btn"): 1=stanga (listen), 2=dreapta (captura CAM).
pending_button_listen = False
pending_capture_req = False
BUTTON_LISTEN_MS = 5000  # buton stanga: ~5s inregistrare voce
_last_mqtt_speak_ts = 0
_last_mqtt_speak_txt = ""
_last_mqtt_speak_topic = ""  # dedupe doar acelasi text pe *acelasi* topic (<2s)
_audio_play_srv = None
_audio_play_srv_ok = False


# Mono 2048 B ≈ 43 ms @ 24 kHz — LPF2 (hub) tolera ~40 ms intre pr.process()
_TTS_STREAM_CHUNK_BYTES = 2048
_TTS_STEREO_WORK = bytearray(2048 * 4)
# ~58% full scale: reduce clipping si crackling fara a pierde claritatea vocii
_TTS_GAIN_Q15 = int(32767 * 0.75)  # ~75% nivel digital (Unity = 32767)
# PAS 4: gain digital maxim recomandat (32767 ~= Q15 unity per esantion).
_BREATHE_PCM_GAIN_Q15 = 32767
# Mono PAS4 mic; stereo în felii foarte mici + multe pr.process() (după Audio TCP lung + I2S).
_BREATHE_PCM_CHUNK_BYTES = 256
_BREATHE_I2S_STEREO_CHUNK = 256
# După redare TCP: spin-uri cu sleep (40x12ms=~480ms respiro UART post-I2S).
_TCP_POST_PLAY_HUB_SPINS = 40
_TCP_POST_PLAY_SPIN_SLEEP_MS = 12
# Înainte de PAS4 flash PCM: spin-uri cu sleep ca LPF2 sa primeasca NACK-uri curate.
_BREATHE_PRE_PLAY_HUB_SPINS = 20
_BREATHE_PRE_PLAY_SPIN_SLEEP_MS = 5
# Delay minim obligatoriu inainte de primul inspir/expir PAS4 (de la scheduling MQTT).
# Dupa TCP de 5+ s, LPF2 are nevoie de ~2 s fara I2S ca sa nu cada la urmatorul I2S.
_BREATHE_MIN_DEFER_MS = 2000
# Voci Gemini TTS: Sulafat=Warm (natural), Achird=Friendly, Vindemiatrix=Gentle
_GEMINI_TTS_VOICE = "Sulafat"
# Limita stricta pe ESP: raspunsuri foarte scurte ca sa ramana stabil in RAM.
_GEMINI_TTS_MAX_CHARS = 32
# Din MQTT acceptam putin mai mult, dar tot limitat pentru stabilitate.
_GEMINI_TTS_TOTAL_MAX_CHARS = 120
# Cerere initiala (~5s audio); fallback un pic mai scurt daca request cade pe memorie
_GEMINI_TTS_MAX_TOKENS = 140
_GEMINI_TTS_FALLBACK_CHARS = 32
_GEMINI_TTS_FALLBACK_TOKENS = 120
# Daca API raspunde cu body foarte mare, retry automat cu target mai scurt.
_GEMINI_TTS_MAX_HTTP_BODY = 120000
# JSON mare: json.loads + dict Python dubleaza RAM (~600KB+) -> OOM pe ESP32
_JSON_STREAM_THRESHOLD = 180000
# Primul pas base64 mic = mai putin PCM de decodat inainte de primul sunet (mai mic lag)
_TTS_B64_FIRST_BYTES = 4096
_TTS_B64_STEP_BYTES = 12288

# Aliniere voce BV la main.py Hub: 2 × (inh + exh) = 10 s + miscări braț (main.py).
_BV_BREATHING_CYCLES = 2
_BV_INH_MS = 2500
_BV_EXH_MS = 2500
_bv_events = []  # liste (ticks_deadline, text_micro)
# PCM scurt synth pe PC → mpremote cp :inspire.pcm :expire.pcm (mono s16le 24 kHz)
_BREATHE_PCM_INSPIRE = "inspire.pcm"
_BREATHE_PCM_EXPIRE = "expire.pcm"
_pcm_breathing_events = []  # (ticks_deadline, filename)
pcm_breathing_queue = []  # o redare/scurtă în bucla robot
# În timpul PAS4: nu accepta Audio TCP mare (336kB) → ENOMEM + hub mort.
_BREATHE_GUARD_UNTIL_MS = 0
# Același MQTT cu „speak”: întârzie PCM doar dacă TTS Gemini chiar va rula (există GEMINI_API_KEY).
_PAS4_PCM_AFTER_SPOKEN_MS = 5500
# Actualizat la fiecare iterație; PAS4 PCM nu consume eveniment/coadă fără link LPF2.
_PAS4_HUB_LINK_OK = False


def _speak_trim(t):
    t = (t or "").strip()
    return t[:_GEMINI_TTS_TOTAL_MAX_CHARS] if t else ""


def _speak_queue_append(txt):
    global speak_queue
    s = _speak_trim(txt)
    if s:
        speak_queue.append(s)


def _schedule_breathing_voice(defer_pcm_ms=0):
    """PAS 4: doar PCM inspir/expir; defer_pcm_ms dacă același MQTT a avut „speak”."""
    global _bv_events, _pcm_breathing_events, _BREATHE_GUARD_UNTIL_MS
    _bv_events = []
    t0 = time.ticks_ms()
    inh = _BV_INH_MS
    exh = _BV_EXH_MS
    cy = inh + exh
    n_cycles = _BV_BREATHING_CYCLES
    d = max(_BREATHE_MIN_DEFER_MS, int(defer_pcm_ms))
    se = []
    for k in range(n_cycles):
        base = k * cy
        se.append((time.ticks_add(t0, d + base), _BREATHE_PCM_INSPIRE))
        se.append((time.ticks_add(t0, d + base + inh), _BREATHE_PCM_EXPIRE))
    _pcm_breathing_events = se
    guard_ms = d + n_cycles * cy + 10000
    _BREATHE_GUARD_UNTIL_MS = time.ticks_add(t0, guard_ms)


def _breathing_pcm_fire_due():
    """Pune în coadă toate clipurile PAS4 cu deadline scurs (după Gemini sau I2S, pot fi mai multe odată)."""
    global _pcm_breathing_events, pcm_breathing_queue
    if not _PAS4_HUB_LINK_OK:
        return
    now = time.ticks_ms()
    while _pcm_breathing_events:
        deadline, fn = _pcm_breathing_events[0]
        if time.ticks_diff(now, deadline) < 0:
            break
        _pcm_breathing_events.pop(0)
        if fn and isinstance(fn, str):
            pcm_breathing_queue.append(fn)
            print(">>> BV PCM queue:", fn)


def _breathing_voice_fire_due():
    """Trage maxim o frază programată per iterație (evită bombardament Gemini după TTS blocant)."""
    global _bv_events
    now = time.ticks_ms()
    if not _bv_events:
        return
    deadline, txt = _bv_events[0]
    if time.ticks_diff(now, deadline) < 0:
        return
    _bv_events.pop(0)
    if isinstance(txt, str) and txt.strip():
        _speak_queue_append(txt)
        print(">>> BV enqueue:", txt[:40])


def _fire_pattern_seq_due():
    """Act. 7: trimite urmatorul cmd din secventa pattern cand deadline-ul a trecut."""
    global _pattern_seq_events, _pending_cmd, _pending_cmd_until_ms
    if not _pattern_seq_events:
        return
    now = time.ticks_ms()
    deadline, cmd_code = _pattern_seq_events[0]
    if time.ticks_diff(now, deadline) < 0:
        return
    _pattern_seq_events.pop(0)
    _pending_cmd = int(cmd_code)
    _pending_cmd_until_ms = time.ticks_add(now, _CMD_HOLD_MS_PATTERN_STEP_MS)
    print(">>> Pattern step -> cmd=", cmd_code)


def _parse_wav_or_raw_pcm(pcm):
    """
    Dupa base64: fie WAV (RIFF) cu fmt+data, fie PCM brut mono 24 kHz.
    Returneaza (raw_pcm_s16le, sample_rate_hz, channels).
    """
    if len(pcm) < 12 or pcm[0:4] != b"RIFF" or pcm[8:12] != b"WAVE":
        return pcm, 24000, 1
    i = 12
    sr = 24000
    ch = 1
    bits = 16
    data_start = None
    data_len = 0
    try:
        while i + 8 <= len(pcm):
            cid = pcm[i : i + 4]
            sz = struct.unpack_from("<I", pcm, i + 4)[0]
            if sz < 0 or i + 8 + sz > len(pcm):
                break
            c0 = i + 8
            if cid == b"fmt " and sz >= 16:
                ch = struct.unpack_from("<H", pcm, c0 + 2)[0]
                sr = struct.unpack_from("<I", pcm, c0 + 4)[0]
                bits = struct.unpack_from("<H", pcm, c0 + 14)[0] if sz >= 16 else 16
            elif cid == b"data":
                data_start = c0
                data_len = sz
                break
            i += 8 + sz
    except Exception:
        return pcm, 24000, 1
    if data_start is None or bits != 16:
        return pcm, 24000, 1
    raw = pcm[data_start : data_start + data_len]
    if ch < 1 or ch > 2:
        ch = 1
    if sr < 8000 or sr > 48000:
        sr = 24000
    return raw, sr, ch


def _mono16_to_stereo_buf_gain(mono_seg, gain_q15):
    """Mono int16 LE -> stereo L=R cu castig fix (Q15). Alocare noua (ultimul chunk mare)."""
    n = len(mono_seg) // 2
    out = bytearray(n * 4)
    for i in range(n):
        lo = mono_seg[i * 2]
        hi = mono_seg[i * 2 + 1]
        s = (hi << 8) | lo
        if s >= 32768:
            s -= 65536
        s = (s * gain_q15) >> 15
        if s > 32767:
            s = 32767
        if s < -32768:
            s = -32768
        struct.pack_into("<hh", out, i * 4, s, s)
    return out


def _mono16_to_stereo_buf_gain_into(mono_seg, gain_q15, out_buf):
    """
    Scrie stereo in out_buf; returneaza numar octeti sau None daca nu incape (foloseste fallback).
    """
    n = len(mono_seg) // 2
    nb = n * 4
    if nb > len(out_buf):
        return None
    for i in range(n):
        lo = mono_seg[i * 2]
        hi = mono_seg[i * 2 + 1]
        s = (hi << 8) | lo
        if s >= 32768:
            s -= 65536
        s = (s * gain_q15) >> 15
        if s > 32767:
            s = 32767
        if s < -32768:
            s = -32768
        struct.pack_into("<hh", out_buf, i * 4, s, s)
    return nb


def _extract_longest_b64_data_field(raw_bytes):
    """Gaseste cel mai lung camp \"data\" din JSON fara json.loads (RAM)."""
    if not isinstance(raw_bytes, (bytes, bytearray)):
        return None
    marker = b'"data"'
    best = (0, 0)
    best_len = 0
    i = 0
    n = len(raw_bytes)
    while True:
        j = raw_bytes.find(marker, i)
        if j < 0:
            break
        colon = raw_bytes.find(b":", j, min(j + 40, n))
        if colon < 0:
            i = j + 1
            continue
        q1 = raw_bytes.find(b'"', colon, min(colon + 24, n))
        if q1 < 0:
            i = j + 1
            continue
        q1 += 1
        q2 = raw_bytes.find(b'"', q1)
        if q2 < 0:
            break
        seg_len = q2 - q1
        if seg_len > best_len and seg_len > 64:
            best = (q1, q2)
            best_len = seg_len
        i = j + 1
    if best_len == 0:
        return None
    return memoryview(raw_bytes)[best[0] : best[1]]


def _guess_sample_rate_from_bytes(raw_bytes):
    """
    Gemini TTS e aproape mereu 24 kHz. Nu verifica 48000 inainte de 24000:
    un '48000' random in JSON putea forta I2S gresit -> sunet straniu / bazait.
    """
    head = raw_bytes[:24000] if len(raw_bytes) > 24000 else raw_bytes
    if b"rate=24000" in head:
        return 24000
    if b"rate=48000" in head:
        return 48000
    if b"rate=44100" in head:
        return 44100
    if b"24000" in head:
        return 24000
    if b"48000" in head:
        return 48000
    if b"44100" in head:
        return 44100
    return 24000


def _snippet_json_error(raw_bytes):
    if b'"error"' not in raw_bytes[:2500]:
        return None
    try:
        return raw_bytes[:500].decode("utf-8", "replace")
    except Exception:
        return None


def _play_mono_pcm_bytes(pcm, pr_sensor, audio, gain_q15=None, mono_chunk_bytes=None, ticker_running=False):
    """Reda mono PCM16 LE cu I2S non-blocking. pr.process() e apelat intre chunk-uri."""
    g = _TTS_GAIN_Q15 if gain_q15 is None else gain_q15
    ckb = _TTS_STREAM_CHUNK_BYTES if mono_chunk_bytes is not None else 512
    ckb = max(192, (ckb // 2) * 2)
    if len(pcm) < 2:
        return
    hub = pr_sensor if pr_sensor is not None else pr
    audio.irq(_i2s_irq_cb)
    total_in = len(pcm)
    off = 0
    while off < total_in:
        end = min(off + ckb, total_in)
        if (end - off) < 2:
            break
        if (end - off) % 2:
            end -= 1
        seg = pcm[off:end]
        off = end
        nb = _mono16_to_stereo_buf_gain_into(seg, g, _TTS_STEREO_WORK)
        if nb is None:
            stereo = _mono16_to_stereo_buf_gain(seg, g)
            _i2s_write_nb(audio, stereo, hub)
        else:
            _i2s_write_nb(audio, memoryview(_TTS_STEREO_WORK)[:nb], hub)


def tri_play_greeting_pcm(pr_sensor=None, path="greeting.pcm", log_tag="Salut PCM"):
    """
    PCM/WAV mono 16-bit din flash (salut sau clipuri PAS 4).

    Salut: py tools/gen_greeting_pcm.py -> mpremote cp assets/greeting.pcm :greeting.pcm
    Respiratie: py tools/gen_breathe_pcm.py -> inspire.pcm, expire.pcm
    """
    if not AUDIO_ENABLED:
        return

    def _tick_hub():
        tgt = pr_sensor if pr_sensor is not None else pr
        try:
            tgt.process()
        except Exception:
            pass

    try:
        f = open(path, "rb")
    except OSError as e:
        print(
            ">>>",
            log_tag,
            "lipseste",
            path,
            "(" + str(e) + ") — tools/gen_greeting_pcm.py sau gen_breathe_pcm.py",
        )
        return

    try:
        head = f.read(12)
        f.seek(0)
        if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WAVE":
            data = f.read(300000)
            f.close()
            pcm, rate, ch = _parse_wav_or_raw_pcm(data)
            del data
        else:
            data = f.read(300000)
            f.close()
            pcm = data
            rate, ch = 24000, 1
            del data
    except Exception as e:
        try:
            f.close()
        except Exception:
            pass
        print(">>>", log_tag, "citire esuata:", e)
        return

    try:
        import gc

        gc.collect()
    except Exception:
        pass

    if len(pcm) < 4:
        print(">>>", log_tag, "fisier prea scurt")
        return
    if ch == 2:
        if len(pcm) % 4:
            pcm = pcm[: (len(pcm) // 4) * 4]
        n = len(pcm) // 4
        mono = bytearray(n * 2)
        for i in range(n):
            L = struct.unpack_from("<h", pcm, i * 4)[0]
            R = struct.unpack_from("<h", pcm, i * 4 + 2)[0]
            struct.pack_into("<h", mono, i * 2, (L + R) // 2)
        pcm = mono
        ch = 1
    elif len(pcm) % 2:
        print(">>>", log_tag, "lungime impara (ignor ultimul octet)")
        pcm = pcm[:-1]

    print(
        ">>>",
        log_tag,
        ": redare",
        len(pcm),
        "B @",
        rate,
        "Hz mono",
    )
    is_breathe_clip = path == _BREATHE_PCM_INSPIRE or path == _BREATHE_PCM_EXPIRE
    play_gain = _BREATHE_PCM_GAIN_Q15 if is_breathe_clip else _TTS_GAIN_Q15
    pcm_chunk = _BREATHE_PCM_CHUNK_BYTES if is_breathe_clip else None
    audio = None
    hub = pr_sensor if pr_sensor is not None else pr
    try:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        en = Pin(AMP_ENABLE_PIN, Pin.OUT)
        en.value(1)
        time.sleep_ms(2)
        if is_breathe_clip:
            for _ in range(_BREATHE_PRE_PLAY_HUB_SPINS):
                try:
                    hub.process()
                except Exception:
                    pass
                time.sleep_ms(_BREATHE_PRE_PLAY_SPIN_SLEEP_MS)
        last_i2s_err = None
        for ibuf_try in (16384, 8192, 32768, 4096):
            try:
                audio = I2S(
                    0,
                    sck=Pin(I2S_BCLK),
                    ws=Pin(I2S_LRC),
                    sd=Pin(I2S_DIN),
                    mode=I2S.TX,
                    bits=16,
                    format=I2S.STEREO,
                    rate=rate,
                    ibuf=ibuf_try,
                )
                break
            except Exception as e:
                last_i2s_err = e
                try:
                    if audio is not None:
                        audio.deinit()
                except Exception:
                    pass
                audio = None
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass
        if audio is None:
            print(">>>", log_tag, "I2S init esuat RAM (incerca ibuf mic):", last_i2s_err)
            return
        _play_mono_pcm_bytes(pcm, pr_sensor, audio, play_gain, pcm_chunk)
        print(">>>", log_tag, "terminat.")
    except Exception as e:
        print(">>>", log_tag, "I2S err:", e)
    finally:
        try:
            if audio is not None:
                audio.deinit()
        except Exception:
            pass
        try:
            import gc

            gc.collect()
        except Exception:
            pass


def tri_speak_gemini(text, pr_sensor=None):
    """
    Apel REST Gemini 2.5 Flash TTS; redare I2S. Blocheaza cateva secunde.
    urequests nu apasa LPF2 in timpul HTTP; link-ul LEGO poate pic la raspunsuri foarte lungi.
    Cu pr_sensor dat, tick inter chunk la redarea audio.
    """
    if not AUDIO_ENABLED or not text:
        return
    if not GEMINI_API_KEY.strip():
        print("TTS: lipseste GEMINI_API_KEY in secrets.py pe ESP (copiaza aceeasi cheie ca pe PC).")
        return
    try:
        import ubinascii
        import urequests
    except ImportError:
        print("TTS: lipseste urequests sau ubinascii")
        return

    print(">>> TTS Gemini: generating audio...")
    if pr_sensor is not None:
        for _ in range(5):
            try:
                pr_sensor.process()
            except Exception:
                break
    raw_t = (text or "").strip()
    if len(raw_t) > _GEMINI_TTS_MAX_CHARS:
        raw_t = raw_t[: _GEMINI_TTS_MAX_CHARS - 3] + "..."
        print("TTS: text truncated to", _GEMINI_TTS_MAX_CHARS, "chars (mode stabil)")
    safe = raw_t
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-preview-tts:generateContent"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY.strip(),
    }
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    raw = None
    sc = 0
    # Primul request normal, apoi fallback mai scurt daca primim MemoryError la urequests.post.
    for attempt_idx in range(2):
        if attempt_idx == 0:
            speak_text = safe
            tok = _GEMINI_TTS_MAX_TOKENS
        else:
            speak_text = safe
            if len(speak_text) > _GEMINI_TTS_FALLBACK_CHARS:
                speak_text = speak_text[: _GEMINI_TTS_FALLBACK_CHARS - 3] + "..."
            tok = _GEMINI_TTS_FALLBACK_TOKENS
            print("TTS: retry with shorter response target.")

        # Nu concatena speak_text în același șir: json.dumps în MicroPython + diacritice
        # au provocat corp JSON trunchiat (API 400: Unexpected end of string).
        inst = (
            "Citește cu voce tare doar fraza din partea următoare o singură dată. "
            "Doar în română. Ton cald, liniștit, prietenos, potrivit copiilor. "
            "Nu adăuga, explica, repeta, scurta sau schimba niciun cuvânt."
        )
        body = {
            "contents": [{"parts": [{"text": inst}, {"text": speak_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": _GEMINI_TTS_VOICE},
                    }
                },
                "temperature": 0.55,
                "maxOutputTokens": tok,
            },
        }
        try:
            try:
                r = urequests.post(
                    url,
                    data=json.dumps(body),
                    headers=headers,
                    timeout=60,
                )
            except TypeError:
                r = urequests.post(url, data=json.dumps(body), headers=headers)
            sc = getattr(r, "status_code", 200)
            raw = r.content if hasattr(r, "content") else r.text.encode()
            try:
                print("TTS: HTTP", sc, "body", len(raw), "B")
            except Exception:
                pass
            r.close()
            if (
                attempt_idx == 0
                and sc == 200
                and isinstance(raw, (bytes, bytearray))
                and len(raw) > _GEMINI_TTS_MAX_HTTP_BODY
            ):
                print(
                    "TTS: raspuns prea mare (",
                    len(raw),
                    "B ) -> retry compact.",
                )
                try:
                    del raw
                except Exception:
                    pass
                raw = None
                try:
                    import gc

                    gc.collect()
                except Exception:
                    pass
                continue
            break
        except MemoryError:
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            if attempt_idx == 0:
                continue
            print("TTS request err: out of memory during HTTP response")
            return
        except Exception as e:
            print("TTS request err:", e)
            return

    if raw is None:
        print("TTS request err: empty HTTP body")
        return
    if not isinstance(raw, (bytes, bytearray)):
        try:
            raw = str(raw).encode("utf-8")
        except Exception:
            print("TTS request err: invalid HTTP body type")
            return

    if sc != 200:
        try:
            err_snip = raw[:200].decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)[:200]
        except Exception:
            err_snip = "?"
        print("TTS HTTP", sc, err_snip)
        return

    try:
        import gc

        gc.collect()
        use_stream = len(raw) > _JSON_STREAM_THRESHOLD

        if use_stream:
            mv_b64 = _extract_longest_b64_data_field(raw)
            if mv_b64 is None:
                snip = _snippet_json_error(raw)
                if snip:
                    print("TTS API error:", snip[:200])
                else:
                    print("TTS: nu gasesc data base64 in JSON mare.")
                del raw
                return
            rate_hint = _guess_sample_rate_from_bytes(raw)
            try:
                print(
                    "TTS: JSON mare",
                    len(raw),
                    "B — stream b64 (fara json.loads),",
                    rate_hint,
                    "Hz",
                )
            except Exception:
                pass
            en = Pin(AMP_ENABLE_PIN, Pin.OUT)
            en.value(1)
            time.sleep_ms(2)
            tt_g = pr_sensor if pr_sensor is not None else pr
            ticker_tts = lpf2_ticker_start(tt_g)
            if ticker_tts:
                print("TTS Gemini: LPF2 ticker pornit pe core 2.")
            audio = I2S(
                0,
                sck=Pin(I2S_BCLK),
                ws=Pin(I2S_LRC),
                sd=Pin(I2S_DIN),
                mode=I2S.TX,
                bits=16,
                format=I2S.STEREO,
                rate=rate_hint,
                ibuf=65520,
            )
            b64_off = 0
            total_b64 = len(mv_b64)
            first_pcm = True
            first_b64_chunk = True
            stream_ok = True
            try:
                while b64_off < total_b64:
                    step = _TTS_B64_FIRST_BYTES if first_b64_chunk else _TTS_B64_STEP_BYTES
                    first_b64_chunk = False
                    end = min(b64_off + step, total_b64)
                    piece = bytes(mv_b64[b64_off:end])
                    b64_off = end
                    pad = (4 - (len(piece) % 4)) % 4
                    if pad:
                        piece = piece + (b"=" * pad)
                    pcm_chunk = ubinascii.a2b_base64(piece)
                    del piece
                    if first_pcm and len(pcm_chunk) >= 4 and pcm_chunk[:4] == b"RIFF":
                        print(
                            "TTS: WAV mare (nu pot stream); scurteaza textul sau limiteaza tokens."
                        )
                        stream_ok = False
                        break
                    first_pcm = False
                    _play_mono_pcm_bytes(pcm_chunk, pr_sensor, audio, ticker_running=ticker_tts)
                    del pcm_chunk
            finally:
                audio.deinit()
                if ticker_tts:
                    time.sleep_ms(150)
                    lpf2_ticker_stop()
                    print("TTS Gemini: LPF2 ticker oprit.")
                try:
                    gc.collect()
                except Exception:
                    pass
            del raw
            try:
                gc.collect()
            except Exception:
                pass
            if stream_ok:
                print(">>> TTS: redare terminata.")
            return

        try:
            resp = json.loads(raw.decode("utf-8"))
        except Exception:
            resp = json.loads(str(raw))
        del raw
        gc.collect()
        err_top = resp.get("error")
        if err_top:
            print("TTS API error:", err_top.get("message", err_top)[:200])
            return
        cands = resp.get("candidates") or []
        if not cands:
            print("TTS: fara candidates", str(resp.get("promptFeedback", ""))[:160])
            return
        c0 = cands[0]
        content = c0.get("content")
        if not content:
            fr = c0.get("finishReason") or c0.get("finish_reason")
            print("TTS: fara content (finishReason=", fr, ")")
            return
        parts = content.get("parts") or []
        b64 = None
        mime_hint = ""
        for p in parts:
            idata = p.get("inlineData") or p.get("inline_data")
            if idata:
                d = idata.get("data")
                if d:
                    b64 = d
                    mime_hint = (idata.get("mimeType") or idata.get("mime_type") or "")[:96]
                    break
        if not b64:
            print("TTS: fara audio in parts (parts=", len(parts), ")")
            if parts:
                try:
                    print("TTS: part0=", str(parts[0])[:160])
                except Exception:
                    pass
            return
        if isinstance(b64, str):
            b64 = b64.strip().encode()
        pad = (4 - (len(b64) % 4)) % 4
        if pad:
            b64 = b64 + (b"=" * pad)
        gc.collect()
        pcm = ubinascii.a2b_base64(b64)
        del b64
        try:
            del resp
        except Exception:
            pass
        gc.collect()
        try:
            print("TTS: PCM decodat", len(pcm), "B")
        except Exception:
            pass
    except Exception as e:
        print("TTS parse err:", e)
        return

    if mime_hint:
        print("TTS mime:", mime_hint)

    pcm, rate, ch = _parse_wav_or_raw_pcm(pcm)
    if len(pcm) < 4:
        print("TTS: PCM prea scurt")
        return
    if ch == 2:
        if len(pcm) % 4:
            pcm = pcm[: (len(pcm) // 4) * 4]
        n = len(pcm) // 4
        mono = bytearray(n * 2)
        for i in range(n):
            L = struct.unpack_from("<h", pcm, i * 4)[0]
            R = struct.unpack_from("<h", pcm, i * 4 + 2)[0]
            struct.pack_into("<h", mono, i * 2, (L + R) // 2)
        pcm = mono
        ch = 1
    elif len(pcm) % 2:
        print("TTS: PCM invalid (lungime", len(pcm), ")")
        return

    try:
        import gc

        gc.collect()
    except Exception:
        pass

    total_in = len(pcm)
    print(
        "TTS: redare @",
        rate,
        "Hz I2S (mono->stereo + volum),",
        total_in,
        "octeti PCM",
    )
    try:
        en = Pin(AMP_ENABLE_PIN, Pin.OUT)
        en.value(1)
        time.sleep_ms(2)
        audio = I2S(
            0,
            sck=Pin(I2S_BCLK),
            ws=Pin(I2S_LRC),
            sd=Pin(I2S_DIN),
            mode=I2S.TX,
            bits=16,
            format=I2S.STEREO,
            rate=rate,
            ibuf=65520,
        )
        _play_mono_pcm_bytes(pcm, pr_sensor, audio)
        audio.deinit()
        try:
            gc.collect()
        except Exception:
            pass
        print(">>> TTS: redare terminata.")
    except Exception as e:
        print("TTS I2S err:", e)


def tri_record_send_tcp(pc_host, port, duration_ms, pr_sensor=None):
    """
    Inregistreaza PCM 16-bit mono MIC_RATE Hz de la I2S RX, trimite la PC: TRIS + lungime + PCM.
    Serverul PC (run_voice_dialog.py) transcrie si raspunde prin MQTT speak.
    """
    if not pc_host or not AUDIO_ENABLED:
        return
    try:
        total_bytes = int(MIC_RATE * 2 * (duration_ms / 1000.0))
        if total_bytes < 400:
            return
    except Exception:
        return
    sock = None
    audio_in = None
    hub = pr_sensor if pr_sensor is not None else pr
    ticker_on = lpf2_ticker_start(hub)
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Connect-ul poate bloca lung daca serverul PC nu e pornit; tinem timeout scurt.
        sock.settimeout(3.0)
        sock.connect((pc_host, int(port)))
        sock.send(b"TRIS" + struct.pack("<I", total_bytes))
        # Dupa handshake, permitem transfer de durata.
        sock.settimeout(45.0)
        # INMP441 L/R=GND -> audio pe canalul RIGHT (bytes 2-3 din fiecare frame stereo).
        # format=I2S.MONO citea doar LEFT (bytes 0-1) -> semnal zero pentru voce.
        # Fix: citim STEREO si trimitem catre PC doar canalul RIGHT ca PCM mono.
        audio_in = I2S(
            1,
            sck=Pin(I2S_BCLK),
            ws=Pin(I2S_LRC),
            sd=Pin(MIC_I2S_SD),
            mode=I2S.RX,
            bits=16,
            format=I2S.STEREO,
            rate=MIC_RATE,
            ibuf=32000,
        )
        audio_in.irq(_i2s_irq_cb)
        stereo_buf = bytearray(4096)
        mono_buf   = bytearray(2048)
        sent = 0
        while sent < total_bytes:
            n_stereo = _i2s_readinto_nb(audio_in, stereo_buf, hub)
            if not n_stereo:
                continue
            n_frames = n_stereo // 4
            for i in range(n_frames):
                mono_buf[i * 2]     = stereo_buf[i * 4 + 2]
                mono_buf[i * 2 + 1] = stereo_buf[i * 4 + 3]
            chunk = min(n_frames * 2, total_bytes - sent)
            mv = memoryview(mono_buf)[:chunk]
            off = 0
            while off < chunk:
                end = min(off + 1024, chunk)
                sock.send(mv[off:end])
                off = end
                try:
                    hub.process()
                except Exception:
                    pass
            sent += chunk
        print("Voce TCP: trimis", sent, "octeti catre", pc_host, ":", int(port))
    except Exception as e:
        print("Voce TCP trimite esuat:", e)
    finally:
        try:
            if audio_in:
                audio_in.deinit()
        except Exception:
            pass
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        if ticker_on:
            lpf2_ticker_stop()
        # RX pe acelasi BCLK/LRC ca TX: lasa I2S sa se elibereze + stabilizeaza LPF2.
        _lpf2_spin(hub, 50)
        _lpf2_spin(hub, 40)


def _audio_play_server_init():
    """Server TCP local (PC -> ESP) pentru redare PCM pe difuzor."""
    global _audio_play_srv, _audio_play_srv_ok
    if _audio_play_srv_ok:
        return
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        s.bind(("0.0.0.0", AUDIO_TCP_PLAY_PORT))
        s.listen(1)
        s.settimeout(0)
        _audio_play_srv = s
        _audio_play_srv_ok = True
        print("Audio TCP server activ pe port", AUDIO_TCP_PLAY_PORT)
    except Exception as e:
        if not _audio_play_srv_ok:
            print("Audio TCP server init esuat:", e)
        _audio_play_srv_ok = False
        _audio_play_srv = None


def _recv_exact(conn, n, pr_sensor=None):
    """Citeste fix n octeti; mentine LPF2 viu inclusiv cand pr_sensor=None (async)."""
    hub = pr_sensor if pr_sensor is not None else pr
    data = bytearray()
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
        except OSError as e:
            if _sock_recv_err_is_timeout(e):
                try:
                    hub.process()
                except Exception:
                    pass
                continue
            return None
        except Exception:
            chunk = None
        if chunk is None or len(chunk) == 0:
            return None
        data.extend(chunk)
        try:
            hub.process()
        except Exception:
            pass
    return bytes(data)


# ---------------------------------------------------------------------------
# I2S non-blocking helpers — mentine LPF2 heartbeat in timpul audio I/O.
#
# MicroPython I2S: audio.irq(handler) face audio.write()/readinto() non-blocking.
# Callback-ul e chemat cand DMA-ul termina transferul. Intre transferuri
# main thread-ul e liber sa apeleze pr.process() si sa mentina LPF2 viu.
# ---------------------------------------------------------------------------
_I2S_NB_READY = True


def _i2s_irq_cb(arg):
    global _I2S_NB_READY
    _I2S_NB_READY = True


def _lpf2_spin(hub, count=40):
    """Cateva process() ca legatura LPF2 sa se stabilizeze dupa I2S RX/TX."""
    if hub is None:
        return
    for _ in range(count):
        try:
            hub.process()
        except Exception:
            pass
        time.sleep_ms(3)


def _i2s_write_nb(audio_dev, data, pr_sensor, chunk_size=2048):
    """Scrie data pe I2S in mod non-blocking, apeland pr.process() intre chunk-uri."""
    global _I2S_NB_READY
    mv = memoryview(data)
    off = 0
    total = len(data)
    while off < total:
        end = min(off + chunk_size, total)
        chunk = mv[off:end]
        _I2S_NB_READY = False
        audio_dev.write(chunk)
        while not _I2S_NB_READY:
            if pr_sensor is not None:
                try:
                    pr_sensor.process()
                except Exception:
                    pass
            time.sleep_ms(2)
        off = end


def _i2s_readinto_nb(audio_dev, buf, pr_sensor):
    """Citeste din I2S in mod non-blocking, apeland pr.process() cat asteapta.
    audio_dev trebuie sa aiba deja irq setat cu _i2s_irq_cb."""
    global _I2S_NB_READY
    _I2S_NB_READY = False
    n = audio_dev.readinto(buf)
    while not _I2S_NB_READY:
        if pr_sensor is not None:
            try:
                pr_sensor.process()
            except Exception:
                pass
        time.sleep_ms(2)
    return n


# LPF2 heartbeat ticker pe core 2 — backup suplimentar pt cazuri in care
# main thread-ul e blocat scurt (socket recv, gc.collect, etc).
_LPF2_TICKER_RUN = False
_LPF2_TICKER_PR = None


def _lpf2_ticker_loop():
    """Bucla pe al doilea thread: pr.process() la fiecare ~15ms cat timp e activa."""
    while _LPF2_TICKER_RUN:
        if _LPF2_TICKER_PR is not None:
            try:
                _LPF2_TICKER_PR.process()
            except Exception:
                pass
        time.sleep_ms(15)


def lpf2_ticker_start(pr_sensor):
    """Porneste ticker LPF2 pe core 2 ca backup. Cu I2S non-blocking, GIL-ul e cedat
    frecvent, deci ticker-ul poate rula in paralel fara sa fie starveit."""
    global _LPF2_TICKER_RUN, _LPF2_TICKER_PR
    if not _HAS_THREAD:
        return False
    if _LPF2_TICKER_RUN:
        _LPF2_TICKER_PR = pr_sensor
        return True
    _LPF2_TICKER_PR = pr_sensor
    _LPF2_TICKER_RUN = True
    try:
        _thread.start_new_thread(_lpf2_ticker_loop, ())
        return True
    except Exception as e:
        print("LPF2 ticker thread err:", e)
        _LPF2_TICKER_RUN = False
        return False


def lpf2_ticker_stop():
    """Opreste ticker LPF2. Apel dupa ce I2S a terminat."""
    global _LPF2_TICKER_RUN, _LPF2_TICKER_PR
    _LPF2_TICKER_RUN = False
    time.sleep_ms(30)
    _LPF2_TICKER_PR = None


def _play_pcm_stream_from_conn(conn, sample_rate, total_len, pr_sensor=None):
    """Citeste PCM stereo din socket si reda cu I2S non-blocking (streaming).
    pr.process() intre chunk-uri; drain scurt inainte de deinit."""
    if sample_rate < 8000 or sample_rate > 48000:
        sample_rate = 24000
    if total_len < 4 or total_len > 2000000:
        return False

    hub = pr_sensor if pr_sensor is not None else pr
    stereo_written = 0
    ticker_on = lpf2_ticker_start(hub)

    def _tick():
        try:
            hub.process()
        except Exception:
            pass

    _lpf2_spin(hub, 35)

    try:
        conn.settimeout(0.15)
    except Exception:
        pass

    en = Pin(AMP_ENABLE_PIN, Pin.OUT)
    en.value(1)
    time.sleep_ms(2)
    audio = None
    try:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        # Pre-buffer mai mare (~340 ms la 24 kHz stereo) ca sa absoarba jitter WiFi
        # si pauzele LPF2 → evita underrun-ul DMA care se aude "sacadat".
        pre_target = min(32768, total_len)
        pre = bytearray()
        while len(pre) < pre_target:
            try:
                chunk0 = conn.recv(min(2048, pre_target - len(pre)))
            except OSError as e:
                if _sock_recv_err_is_timeout(e):
                    _tick()
                    continue
                chunk0 = None
            except Exception:
                chunk0 = None
            if chunk0 is None or len(chunk0) == 0:
                break
            pre.extend(chunk0)
            _tick()
        last_err = None
        for ibuf_try in (32768, 16384, 8192, 4096):
            try:
                audio = I2S(
                    0,
                    sck=Pin(I2S_BCLK),
                    ws=Pin(I2S_LRC),
                    sd=Pin(I2S_DIN),
                    mode=I2S.TX,
                    bits=16,
                    format=I2S.STEREO,
                    rate=sample_rate,
                    ibuf=ibuf_try,
                )
                _tick()
                break
            except Exception as e:
                last_err = e
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass
            _tick()
        if audio is None:
            print("Audio TCP: I2S init esuat (RAM):", last_err)
            return False
        audio.irq(_i2s_irq_cb)
        got = 0
        carry = b""
        I2S_WR = 2048

        if pre:
            got = len(pre)
            rem = len(pre) % 4
            if rem:
                carry = bytes(pre[-rem:])
                pre = pre[:-rem]
            if pre:
                _i2s_write_nb(audio, pre, hub, I2S_WR)
                stereo_written += len(pre)
        while got < total_len:
            _tick()
            try:
                chunk = conn.recv(min(4096, total_len - got))
            except OSError as e:
                if _sock_recv_err_is_timeout(e):
                    _tick()
                    continue
                chunk = None
            except Exception:
                chunk = None
            if chunk is None or len(chunk) == 0:
                break
            got += len(chunk)
            if carry:
                chunk = carry + chunk
                carry = b""
            rem = len(chunk) % 4
            if rem:
                carry = chunk[-rem:]
                chunk = chunk[:-rem]
            if chunk:
                _i2s_write_nb(audio, chunk, hub, I2S_WR)
                stereo_written += len(chunk)
            else:
                _tick()
        return got >= max(2, total_len - 2)
    finally:
        if ticker_on:
            lpf2_ticker_stop()
        try:
            if audio:
                if stereo_written >= 4:
                    play_ms = (stereo_written // 4) * 1000 // sample_rate
                    tail_ms = min(max(300, play_ms // 5), 700)
                    end_ms = time.ticks_add(time.ticks_ms(), tail_ms)
                    while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
                        _tick()
                        time.sleep_ms(6)
                audio.deinit()
        except Exception:
            pass
        for _ in range(_TCP_POST_PLAY_HUB_SPINS):
            _tick()
            time.sleep_ms(_TCP_POST_PLAY_SPIN_SLEEP_MS)

def tri_accept_play_tcp_once(pr_sensor=None):
    """Verifica rapid daca PC a trimis audio; daca da, reda si revine."""
    if _audio_play_srv is None:
        return
    conn = None
    addr = None
    try:
        conn, addr = _audio_play_srv.accept()
    except Exception:
        return
    try:
        # Timeout scurt: recv() fara excepție poate bloca secunde — LPF2 moare dupa ~1s fara heartbeat.
        try:
            conn.settimeout(0.35)
        except Exception:
            pass
        hdr = _recv_exact(conn, 12, pr_sensor)
        if not hdr or hdr[:4] != b"TPCM":
            return
        rate = struct.unpack_from("<I", hdr, 4)[0]
        total = struct.unpack_from("<I", hdr, 8)[0]
        print("Audio TCP: primire", total, "B @", rate, "Hz de la", addr)
        ok = _play_pcm_stream_from_conn(conn, rate, total, pr_sensor)
        if ok:
            print("Audio TCP: redare terminata.")
        else:
            print("Audio TCP: flux incomplet.")
    except Exception as e:
        print("Audio TCP play err:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ==========================================
# Config retea (Inventika / MQTT pe PC — valorile sunt in secrets.py pe ESP sau default mai jos)
# ==========================================
WIFI_SSID = scr_get("WIFI_SSID", "Orange-292q-2.4G")
WIFI_PASS = scr_get("WIFI_PASS", "Y8kCA4vx")
MQTT_BROKER = scr_get("MQTT_BROKER", "192.168.100.134")
CLIENT_ID = "TriSense_Licenta_Robot"
TOPIC_VISION_TAGS = b"vision/tags"
TOPIC_ROBOT_CONTROL = b"robot/control"
TOPIC_ROBOT_SPEAK = b"robot/speak"  # salut retained de la PC (aceeasi incarcare JSON ca robot/control)


def _spin_hub(pr_sensor, count=40):
    """Cateva process() ca LPF2 sa nu moara in timpul init retea / MQTT / I2C."""
    for _ in range(count):
        pr_sensor.process()
        time.sleep_ms(2)


def btn(code):
    """Callback LPF2 buton Hub -> ESP. 1=stanga (listen), 2=dreapta (captura CAM).

    Doar seteaza flag-uri (handle-uite in bucla principala) ca sa nu facem I/O retea
    in timpul tranzactiei LPF2 (altfel risc „line dead”).
    """
    global pending_button_listen, pending_capture_req
    try:
        c = int(code)
    except Exception:
        return None
    if c == 1:
        pending_button_listen = True
    elif c == 2:
        pending_capture_req = True
    return None


def _voice_host_fallback():
    """IP-ul PC-ului pentru voce TCP: PC_VOICE_IP din secrets.py, altfel MQTT_BROKER (acelasi PC)."""
    try:
        from secrets import PC_VOICE_IP as _pv

        h = (_pv or "").strip() if isinstance(_pv, str) else ""
        if h:
            return h
    except ImportError:
        pass
    return (MQTT_BROKER or "").strip()


# ==========================================
# 1. LEGO imediat (inainte de WiFi)
# ==========================================
pr = PUPRemoteSensor(power=True)
pr.add_channel("obj", to_hub_fmt="b")
# Canal comandă hub LEGO (UINT8): 1 dance, 2–6 brate/respiri, 7–11 roți C+D (înainte/înapoi/pivot/stop).
# Tabelul trebuie să coincidă cu docstring din main.py (Pybricks).
pr.add_channel("cmd", to_hub_fmt="b")
# Canal buton Hub -> ESP (from_hub UINT8): trebuie adaugat IDENTIC si pe Hub (main.py), in aceeasi ordine.
pr.add_command("btn", from_hub_fmt="b")
print("Comunicare LPF2 activata. Astept Hub-ul...")
# Fereastra critica de boot: daca nu apelam process() in primele sute de ms,
# Hub-ul raporteaza ENODEV si intra in retry loop.
_spin_hub(pr, 300)

# Comanda activa spre hub (resetata la 0 dupa _CMD_HOLD_MS pentru ca hub-ul sa vada o tranzitie).
_pending_cmd = 0
_pending_cmd_until_ms = 0
_CMD_HOLD_MS = 1800
_CMD_HOLD_MS_LONG = 10000         # dans simplu pe hub (~8s rutina + buffer)
_CMD_HOLD_MS_DANCE_WITH_ME = 12000  # Act. 2.3: dans + muzica fundal
_CMD_HOLD_MS_STOP_GO_MS = 4000    # Stop&Go: afisare 1/0 + lumina
_CMD_HOLD_MS_BREATHING_SHOW_MS = 20000  # PAS 4: rutina Hub ~10 s + braț + margine
_CMD_HOLD_MS_EMOTION_MS = 32000   # Act. 6: rutine Hub amplificate (max ~28s meltdown) + margine
_CMD_HOLD_MS_PATTERN_STEP_MS = 2800  # Act. 7: durata per pas pattern
_CMD_HOLD_MS_BUILD_MODEL_MS = 40000  # Build the Model: tinta ramane afisata cat construieste copilul

# Act. 7 Follow the Pattern — secventa de (ticks_deadline, cmd_code) programata de PC via MQTT.
_pattern_seq_events = []

# String action (MQTT) -> cod uint8 spre hub (main.py)
_MQTT_ACTION_TO_CMD = {
    "dance": 1,
    "repose": 2,
    "home": 2,
    "reset": 2,
    "left_arm": 3,
    "right_arm": 4,
    "breathe_in": 5,
    "breathein": 5,
    "inspire": 5,
    "breathe_out": 6,
    "breatheout": 6,
    "expire": 6,
    "gesture7_breathing_in": 5,
    "gesture7_breathing_out": 6,
    # Roti Port C+D (durate scurte — vezi main.py hub)
    "forward": 7,
    "drive_forward": 7,
    "backward": 8,
    "back": 8,
    "drive_back": 8,
    "turn_left": 9,
    "turn_right": 10,
    "wheels_stop": 11,
    "drive_stop": 11,
    "breathing_show": 12,
    "breathing_demo": 12,
    "respiratie_show": 12,
    # Act. 6 — Guess the Emotion
    "emotion_happy": 15,    # dans brate + roti fata/spate + lumina plina
    "emotion_sad": 13,      # brate jos lent + puls slab
    "emotion_surprised": 14,  # brate sus rapid + flash
    "emotion_angry": 16,    # brate rigide + flash agresiv
    "emotion_meltdown": 17,  # agitatie intensa: brate + pivot + fata/spate
    # Build the Model (Turnul lui Hanoi) — afiseaza modelul tinta pe matricea Hub
    "build_model_1": 18,    # turn vertical
    "build_model_2": 19,    # linie orizontala
    "build_model_3": 20,    # forma L
    # Stop & Go (cmd 21-23; 18-20 rezervate pentru Build the Model)
    "stop_go_go": 21,
    "stop_go_freeze": 22,
    "stop_go_end": 23,
    "dance_with_me": 1,
}

_PCM_GREETING_ACTIONS = (
    "play_greeting",
    "replay_greeting_pcm",
    "stable_greeting",
)

# ==========================================
# 2. Timere bucla
# ==========================================
timp_start = time.ticks_ms()
ultimul_timp_mqtt = time.ticks_ms()
last_hub_connected = None
hub_fail_cycles = 0
t_last_hub_print = time.ticks_ms()

# ==========================================
# 3. WiFi + MQTT (pr.process in asteptare)
# ==========================================
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
# Trezirea radio poate bloca; mentinem heartbeat LPF2 in paralel.
_spin_hub(pr, 150)
mqtt = None
MQTT_RETRY_MS = 5000
_last_mqtt_retry_ms = time.ticks_ms()


def _mqtt_control_cb(topic, msg):
    global pending_speak, speak_queue, pending_voice_tcp, _last_mqtt_speak_ts, _last_mqtt_speak_txt
    global _last_mqtt_speak_topic, _bv_events, _pcm_breathing_events, pcm_breathing_queue
    global _BREATHE_GUARD_UNTIL_MS, _pattern_seq_events
    try:
        tnm = topic.decode() if isinstance(topic, (bytes, bytearray)) else str(topic)
        print(">>> MQTT", tnm + ":", msg.decode())
    except Exception:
        print(">>> MQTT topic raw:", topic, msg)
    try:
        if isinstance(msg, (bytes, bytearray)):
            msg = msg.decode("utf-8")
        msg = msg.strip()
        if not msg:
            return
        try:
            o = json.loads(msg)
        except ValueError:
            # Text simplu (ex. "HI" din MQTT Explorer) — nu e JSON
            print("MQTT robot/control: ignorat (nu e JSON valid)")
            return
        if not isinstance(o, dict):
            print("MQTT control err: JSON valid dar nu e obiect (tip", type(o), ")")
            return
        speak_enqueued_now = False
        sp = o.get("speak")
        if sp and isinstance(sp, str) and sp.strip():
            t = sp.strip()[:_GEMINI_TTS_TOTAL_MAX_CHARS]
            now = time.ticks_ms()
            # Acelasi text pe *alt* topic (ex. retained robot/speak + robot/control) nu e duplicat.
            if (
                t == _last_mqtt_speak_txt
                and tnm == _last_mqtt_speak_topic
                and time.ticks_diff(now, _last_mqtt_speak_ts) < 2000
            ):
                print(">>> speak MQTT: ignor (acelasi topic + text <2s)")
            else:
                _last_mqtt_speak_txt = t
                _last_mqtt_speak_ts = now
                _last_mqtt_speak_topic = tnm
                _speak_queue_append(t)
                speak_enqueued_now = True
                print(">>> speak MQTT coada:", t[:72] + ("..." if len(t) > 72 else ""))
        # PC trimite JSON true; unele JSON-uri pot da int 1 sau string
        listen = o.get("listen")
        listen_on = listen is True or listen in (1, "true", "True", "1")
        if listen_on:
            raw_host = o.get("pc_host") or o.get("pc_ip") or ""
            if isinstance(raw_host, str):
                host = raw_host.strip()
            elif raw_host:
                host = str(raw_host).strip()
            else:
                host = ""
            if not host:
                host = _voice_host_fallback()
            try:
                vport = int(o.get("voice_port") or VOICE_TCP_PORT_DEFAULT)
            except (TypeError, ValueError):
                vport = VOICE_TCP_PORT_DEFAULT
            try:
                dur = int(o.get("duration_ms") or VOICE_RECORD_MS_DEFAULT)
            except (TypeError, ValueError):
                dur = VOICE_RECORD_MS_DEFAULT
            if host and 200 <= dur <= 30000:
                pending_voice_tcp = {
                    "host": host,
                    "port": vport,
                    "duration_ms": dur,
                }
                print(">>> MQTT listen:", dur, "ms ->", host)
            elif listen_on:
                if not host:
                    print("Voce: lipseste pc_host/pc_ip si PC_VOICE_IP/MQTT_BROKER in secrets.py")
                else:
                    print("Voce: duration_ms invalid:", dur, "(acceptat 200-30000)")
        # Hub LEGO + salut PCM stabil (PAS 3)
        global _pending_cmd, _pending_cmd_until_ms, pending_play_greeting

        playback = o.get("playback")
        if isinstance(playback, str):
            pv = playback.strip().lower()
            if pv in ("greeting_pcm", "greeting", "boot_pcm"):
                pending_play_greeting = True
                print(">>> MQTT playback -> coada salut PCM")

        action_raw = o.get("action")
        cmd_key = o.get("cmd")
        if isinstance(cmd_key, bool):
            cmd_key = None

        resolved = None
        if isinstance(cmd_key, int):
            resolved = cmd_key if 0 <= cmd_key <= 255 else None
        elif isinstance(cmd_key, str):
            s = cmd_key.strip().lower()
            if s.isdigit():
                try:
                    v = int(s)
                    resolved = v if 0 <= v <= 255 else None
                except ValueError:
                    resolved = None
            elif s in ("stop", "idle", "none"):
                resolved = -1
            elif s:
                resolved = _MQTT_ACTION_TO_CMD.get(s)

        if resolved is None and isinstance(action_raw, str):
            act = action_raw.strip().lower()
            if act in ("stop", "idle", "none"):
                resolved = -1  # marca clear
            elif act in _PCM_GREETING_ACTIONS:
                pending_play_greeting = True
                print(">>> MQTT action -> coada salut PCM")
            elif act == "follow_pattern":
                # Act. 7: secventa de cmds hub programata de PC.
                # Payload: {"action":"follow_pattern","pattern":[3,4,5],"step_ms":3000}
                try:
                    pattern = o.get("pattern") or [3, 4, 5]
                    step_ms = int(o.get("step_ms") or 3000)
                    step_ms = max(1500, min(step_ms, 8000))
                    _pattern_seq_events[:] = []
                    t0 = time.ticks_ms()
                    for i, cmd_code in enumerate(pattern):
                        deadline = time.ticks_add(t0, i * step_ms)
                        _pattern_seq_events.append((deadline, int(cmd_code)))
                    print(">>> Follow Pattern: secventa", pattern, "step_ms=", step_ms)
                except Exception as _pe:
                    print("Follow Pattern parse err:", _pe)
            else:
                resolved = _MQTT_ACTION_TO_CMD.get(act)

        if resolved == -1:
            _pending_cmd = 0
            _pending_cmd_until_ms = 0
            _bv_events = []
            _pcm_breathing_events[:] = []
            pcm_breathing_queue[:] = []
            _pattern_seq_events[:] = []
            _BREATHE_GUARD_UNTIL_MS = 0
            print(">>> ACTION stop -> cmd=0 catre hub LEGO")
        elif isinstance(resolved, int) and resolved == 0:
            _pending_cmd = 0
            _pending_cmd_until_ms = 0
            print(">>> cmd=0 -> hub LEGO idle")
        elif isinstance(resolved, int) and resolved > 0:
            if resolved == 12:
                ms = _CMD_HOLD_MS_BREATHING_SHOW_MS
            elif resolved in (13, 14, 15, 16, 17):
                ms = _CMD_HOLD_MS_EMOTION_MS
            elif resolved in (18, 19, 20):
                ms = _CMD_HOLD_MS_BUILD_MODEL_MS
            elif resolved in (21, 22):
                ms = _CMD_HOLD_MS_STOP_GO_MS
            elif (
                isinstance(action_raw, str)
                and action_raw.strip().lower() == "dance_with_me"
                and resolved == 1
            ):
                ms = _CMD_HOLD_MS_DANCE_WITH_ME
            elif resolved == 1:
                ms = _CMD_HOLD_MS_LONG
            else:
                ms = _CMD_HOLD_MS
            _pending_cmd = resolved
            _pending_cmd_until_ms = time.ticks_add(time.ticks_ms(), ms)
            print(">>> ACTION -> cmd=", resolved, "catre hub LEGO (hold_ms=", ms, ")")
            # PAS4: breathing PCM pe ESP eliminat — sunetul vine din intro TCP de pe PC.
    except Exception as e:
        print("MQTT control err:", e)


def _mqtt_connect(pr_sensor):
    global mqtt, _last_mqtt_retry_ms
    _last_mqtt_retry_ms = time.ticks_ms()
    ticker_on = False
    try:
        if pr_sensor is not None:
            # MQTT connect/subscribe poate bloca >1s; mentinem LPF2 heartbeat in paralel.
            ticker_on = lpf2_ticker_start(pr_sensor)
        mqtt = MQTTClient(CLIENT_ID, MQTT_BROKER)
        mqtt.connect()
        if pr_sensor is not None:
            _spin_hub(pr_sensor, 50)
        mqtt.set_callback(_mqtt_control_cb)
        mqtt.subscribe(TOPIC_ROBOT_CONTROL)
        mqtt.subscribe(TOPIC_ROBOT_SPEAK)
        if pr_sensor is not None:
            _spin_hub(pr_sensor, 30)
        print(">>> MQTT CONECTAT la broker", MQTT_BROKER, "(vision/tags + robot/control + robot/speak)")
        return True
    except Exception as e:
        print("Eroare MQTT:", e)
        mqtt = None
        return False
    finally:
        if ticker_on:
            time.sleep_ms(80)
            lpf2_ticker_stop()

if not wlan.isconnected():
    print("Se conecteaza la WiFi: " + WIFI_SSID + " ...")
    try:
        wlan.disconnect()
    except Exception:
        pass
    wlan.connect(WIFI_SSID, WIFI_PASS)
    timeout = 25
    while not wlan.isconnected() and timeout > 0:
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1000:
            pr.process()
            if wlan.isconnected():
                break
            time.sleep_ms(5)
        timeout -= 1
        print(".")

if wlan.isconnected():
    print(">>> WiFi CONECTAT! IP:", wlan.ifconfig()[0])
    _audio_play_server_init()
    if not GEMINI_API_KEY:
        print(">>> Voce robot: seteaza GEMINI_API_KEY in secrets.py pe ESP (aceeasi cheie ca pe PC).")
    _spin_hub(pr, 50)
    _mqtt_connect(pr)
    # Salut PCM la boot DEZACTIVAT: I2S audio citeste 170KB din flash si blocheaza
    # pr.process() suficient cat LPF2 sa moara. PC-ul trimite salutul via Audio TCP.
    print(">>> Salut PCM la boot skip (LPF2 stabil). PC trimite salut via Audio TCP.")
else:
    try:
        st = wlan.status()
    except Exception:
        st = "?"
    print(">>> EROARE WIFI! wlan.status() =", st, "(vezi doc firmware pentru coduri)")
    mqtt = None

# ==========================================
# 4. Bucla principala
#    - Daca pupremote are process_async (fisier nou din repo): asyncio + heartbeat paralel (Anton).
#    - Firmware vechi LMS-ESP32: fara process_async -> bucla sincrona cu pr.process().
#      Poti copia pupremote.py din acest proiect pe ESP: mpremote cp pupremote.py :pupremote.py
# ==========================================


def _expire_and_push_hub_cmd():
    """Trimite `_pending_cmd` pe LPF2; expira pulsul MQTT doar cand Hub e conectat.
    Daca Hub e offline (TCP audio a distrus LPF2), prelungim deadline-ul
    ca Hub-ul sa vada comanda dupa reconectare."""
    global _pending_cmd, _pending_cmd_until_ms
    if _pending_cmd != 0:
        now = time.ticks_ms()
        if _PAS4_HUB_LINK_OK:
            if time.ticks_diff(now, _pending_cmd_until_ms) >= 0:
                _pending_cmd = 0
                _pending_cmd_until_ms = 0
        else:
            # Hub deconectat: prelungim deadline-ul cu 1s ca sa nu expire in gol
            if time.ticks_diff(now, _pending_cmd_until_ms) >= 0:
                _pending_cmd_until_ms = time.ticks_add(now, 1000)
    # HuskyLens a fost eliminat; mentinem explicit canalul "obj" la 0 ca Hub-ul
    # sa poata citi stabil pr.call("obj") fara payload vechi/incomplet.
    pr.update_channel("obj", 0)
    pr.update_channel("cmd", _pending_cmd)


def _robot_loop_body(connected, tts_pr_sensor, end_delay_ms):
    """O iteratie: MQTT, voce, hub debug, update canal. tts_pr_sensor=None daca heartbeat e async."""
    global mqtt, pending_speak, speak_queue, pcm_breathing_queue, pending_voice_tcp, pending_play_greeting, last_hub_connected, hub_fail_cycles, t_last_hub_print
    global pending_button_listen, pending_capture_req
    global ultimul_timp_mqtt, _last_mqtt_retry_ms
    global _PAS4_HUB_LINK_OK, _BREATHE_GUARD_UNTIL_MS, _pattern_seq_events

    _PAS4_HUB_LINK_OK = bool(connected)

    if mqtt:
        try:
            mqtt.check_msg()
        except Exception as e:
            print("MQTT check err:", e)
            try:
                mqtt.disconnect()
            except Exception:
                pass
            mqtt = None
    elif wlan.isconnected() and time.ticks_diff(time.ticks_ms(), _last_mqtt_retry_ms) > MQTT_RETRY_MS:
        print("MQTT reconnect attempt...")
        _mqtt_connect(tts_pr_sensor)

    _breathing_pcm_fire_due()
    _breathing_voice_fire_due()
    _fire_pattern_seq_due()

    _expire_and_push_hub_cmd()

    if not pending_speak and speak_queue:
        pending_speak = speak_queue.pop(0)

    if pending_speak:
        _txt = pending_speak
        pending_speak = None
        tri_speak_gemini(_txt, tts_pr_sensor)

    if pcm_breathing_queue and _PAS4_HUB_LINK_OK:
        pr_b = tts_pr_sensor if tts_pr_sensor is not None else pr
        _pf = pcm_breathing_queue.pop(0)
        try:
            tri_play_greeting_pcm(pr_b, _pf, log_tag="Resp PCM")
        except Exception as _e_pcm:
            print(">>> Resp PCM err:", _e_pcm)

    if wlan.isconnected():
        tri_accept_play_tcp_once(tts_pr_sensor)

    if pending_play_greeting:
        pending_play_greeting = False
        pr_audio = tts_pr_sensor if tts_pr_sensor is not None else pr
        try:
            print(">>> Replay salut PCM (PAS 3, stabil).")
            tri_play_greeting_pcm(pr_audio, "greeting.pcm")
        except Exception as e:
            print(">>> Replay salut PCM err:", e)

    # Buton STANGA pe Hub -> listen ~5s (acelasi mecanism ca MQTT {"listen":true}).
    if pending_button_listen:
        pending_button_listen = False
        _host = _voice_host_fallback()
        if _host:
            pending_voice_tcp = {
                "host": _host,
                "port": VOICE_TCP_PORT_DEFAULT,
                "duration_ms": BUTTON_LISTEN_MS,
            }
            print(">>> Buton STANGA: listen", BUTTON_LISTEN_MS, "ms ->", _host)
        else:
            print(">>> Buton STANGA: nu stiu IP-ul PC (PC_VOICE_IP/MQTT_BROKER lipsesc).")

    # Buton DREAPTA pe Hub -> cere o captura ESP32-CAM (bridge asculta vision/capture_req).
    if pending_capture_req:
        pending_capture_req = False
        if mqtt:
            try:
                mqtt.publish(b"vision/capture_req", b'{"capture":true}')
                print(">>> Buton DREAPTA: cerere captura CAM publicata (vision/capture_req).")
            except Exception as _ce:
                print(">>> Buton DREAPTA publish err:", _ce)
        else:
            print(">>> Buton DREAPTA: MQTT offline, nu pot cere captura.")

    if pending_voice_tcp and wlan.isconnected():
        _vc = pending_voice_tcp
        pending_voice_tcp = None
        tri_record_send_tcp(
            _vc["host"],
            _vc["port"],
            _vc["duration_ms"],
            tts_pr_sensor,
        )

    if connected != last_hub_connected:
        if connected:
            print(
                ">>> HUB LEGO CONECTAT (handshake OK) dupa",
                hub_fail_cycles,
                "cicluri fara link inainte",
            )
            # După reconectare lungă, evenimentele PAS4 vechi (deja expirate) ar trage 3-4 PCM consecutive
            # peste I2S → din nou „line dead”. Le aruncăm dacă deadline-ul e în trecut > prag.
            now_rec = time.ticks_ms()
            kept = []
            dropped = 0
            for ev in _pcm_breathing_events:
                try:
                    if time.ticks_diff(now_rec, ev[0]) > 1500:
                        dropped += 1
                        continue
                except Exception:
                    pass
                kept.append(ev)
            if dropped:
                _pcm_breathing_events[:] = kept
                pcm_breathing_queue[:] = []
                _BREATHE_GUARD_UNTIL_MS = 0
                print(
                    ">>> PAS4: am aruncat",
                    dropped,
                    "clipuri respiratie expirate dupa reconectare (evita I2S pe LPF2 fragil).",
                )
        else:
            print(">>> HUB: fara link / handshake in curs...")
        last_hub_connected = connected

    if not connected:
        hub_fail_cycles += 1
        if time.ticks_diff(time.ticks_ms(), t_last_hub_print) > 500:
            print(
                ">>> Hub LPF2 incerc:",
                hub_fail_cycles,
                "apel(uri) - inca fara conexiune",
            )
            t_last_hub_print = time.ticks_ms()
    else:
        hub_fail_cycles = 0

    _expire_and_push_hub_cmd()

    time.sleep_ms(end_delay_ms)


async def _robot_main_async():
    asyncio.create_task(pr.process_async(40))
    await asyncio.sleep_ms(80)
    while True:
        connected = pr.lpup.connected
        # `pr`: LPF2 trebuie apelat și în timpul PCM / TTS (altfel „line dead” după 1–2 clipuri).
        _robot_loop_body(connected, pr, 0)
        await asyncio.sleep_ms(2)


def _robot_main_sync():
    print(
        ">>> PUPRemote fara process_async (firmware vechi). "
        "Optional: uploadeaza pupremote.py din proiect pe ESP pentru heartbeat async."
    )
    while True:
        connected = pr.process()
        # Cand hub-ul nu e conectat, pr.process() poate bloca pe handshake/retry si sacadeaza TTS.
        tts_pr = pr if connected else None
        _robot_loop_body(connected, tts_pr, 2)


if hasattr(pr, "process_async"):
    try:
        asyncio.run(_robot_main_async())
    except AttributeError:
        asyncio.get_event_loop().run_until_complete(_robot_main_async())
else:
    _robot_main_sync()
