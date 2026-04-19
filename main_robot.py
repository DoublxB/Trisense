from machine import Pin, SoftI2C, I2S
from pupremote import PUPRemoteSensor
from pyhuskylens import HuskyLens, ALGORITHM_OBJECT_CLASSIFICATION
import asyncio
import time
import json
import struct
import network
from umqtt.simple import MQTTClient

print("=== TriSense ESP32 START ===")

# ==========================================
# 0. AUDIO I2S (MAX98357) — scurt feedback, NU lasa I2S deschis in bucla
#     (nu strica LPF2: apeluri scurte intre pr.process). Pini ca la test_i2s_beep.
# ==========================================
AUDIO_ENABLED = True
I2S_BCLK, I2S_LRC, I2S_DIN = 14, 15, 26
AMP_ENABLE_PIN = 32
# Microfon I2S (INMP441): SD pe GPIO 33 — acelasi BCLK/LRC ca difuzorul (vezi test_mic_difuzor.py).
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

pending_speak = None
pending_voice_tcp = None  # {"host","port","duration_ms"} dupa MQTT {"listen": true}
_last_mqtt_speak_ts = 0
_last_mqtt_speak_txt = ""
_last_mqtt_speak_topic = ""  # dedupe doar acelasi text pe *acelasi* topic (<2s)
_audio_play_srv = None
_audio_play_srv_ok = False


# Mono 2048 B ≈ 43 ms @ 24 kHz — LPF2 (hub) tolera ~40 ms intre pr.process()
_TTS_STREAM_CHUNK_BYTES = 2048
_TTS_STEREO_WORK = bytearray(2048 * 4)
# Sub ~0.85 * full scale: mai putin clip / „bazait” de distorsiune; creste daca e prea incet
_TTS_GAIN_Q15 = 23000
# Voci Gemini TTS: Sulafat=Warm, Achird=Friendly, Vindemiatrix=Gentle (calm, copii cu autism)
_GEMINI_TTS_VOICE = "Vindemiatrix"
# Limita stricta pe ESP: pana la ~80 caractere = ~5s audio (incape in RAM/HTTP body).
_GEMINI_TTS_MAX_CHARS = 80
# Din MQTT acceptam putin mai mult, dar tot limitat pentru stabilitate.
_GEMINI_TTS_TOTAL_MAX_CHARS = 140
# Cerere initiala (~5s audio); fallback un pic mai scurt daca request cade pe memorie
_GEMINI_TTS_MAX_TOKENS = 320
_GEMINI_TTS_FALLBACK_CHARS = 56
_GEMINI_TTS_FALLBACK_TOKENS = 192
# Daca API raspunde cu body foarte mare, retry automat cu target mai scurt.
_GEMINI_TTS_MAX_HTTP_BODY = 280000
# JSON mare: json.loads + dict Python dubleaza RAM (~600KB+) -> OOM pe ESP32
_JSON_STREAM_THRESHOLD = 180000
# Primul pas base64 mic = mai putin PCM de decodat inainte de primul sunet (mai mic lag)
_TTS_B64_FIRST_BYTES = 4096
_TTS_B64_STEP_BYTES = 12288


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


def _play_mono_pcm_bytes(pcm, pr_sensor, audio):
    """Reda mono PCM16 LE; chunk-uri cu buffer stereo reutilizat."""
    if len(pcm) < 2:
        return
    total_in = len(pcm)
    off = 0
    while off < total_in:
        end = min(off + _TTS_STREAM_CHUNK_BYTES, total_in)
        if (end - off) < 2:
            break
        if (end - off) % 2:
            end -= 1
        seg = pcm[off:end]
        off = end
        nb = _mono16_to_stereo_buf_gain_into(seg, _TTS_GAIN_Q15, _TTS_STEREO_WORK)
        if nb is None:
            stereo = _mono16_to_stereo_buf_gain(seg, _TTS_GAIN_Q15)
            audio.write(stereo)
        else:
            audio.write(memoryview(_TTS_STEREO_WORK)[:nb])
        if pr_sensor is not None:
            pr_sensor.process()


def tri_speak_gemini(text, pr_sensor=None):
    """
    Apel REST Gemini 2.5 Flash TTS; redare I2S. Blocheaza cateva secunde.
    Daca pr_sensor e dat, cheama process() intre chunk-uri ca sa nu cada LPF2.
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

        # Prompt strict + indicatii de stil (Gemini TTS suporta directii naturale).
        # Stil: calm, lent, prietenos — potrivit pentru copii cu autism.
        prompt = (
            "Say this in English in a calm, gentle, soft voice. "
            "Speak slowly and clearly, with a warm and reassuring tone, "
            "as if talking kindly to a young child. "
            "Do not add, explain, shorten or continue. Text: " + speak_text
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
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
                    _play_mono_pcm_bytes(pcm_chunk, pr_sensor, audio)
                    del pcm_chunk
                    # NU gc.collect() aici — opreste I2S si face sacadat
            finally:
                audio.deinit()
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
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(45.0)
        sock.connect((pc_host, int(port)))
        sock.send(b"TRIS" + struct.pack("<I", total_bytes))
        audio_in = I2S(
            1,
            sck=Pin(I2S_BCLK),
            ws=Pin(I2S_LRC),
            sd=Pin(MIC_I2S_SD),
            mode=I2S.RX,
            bits=16,
            format=I2S.MONO,
            rate=MIC_RATE,
            ibuf=16000,
        )
        buf = bytearray(2048)
        sent = 0
        while sent < total_bytes:
            chunk = min(len(buf), total_bytes - sent)
            n = audio_in.readinto(memoryview(buf)[:chunk])
            if not n:
                time.sleep_ms(5)
                if pr_sensor is not None:
                    pr_sensor.process()
                continue
            mv = memoryview(buf)[:n]
            sock.send(mv)
            sent += n
            if pr_sensor is not None:
                pr_sensor.process()
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
        # RX pe acelasi BCLK/LRC ca TX: lasa perifericul sa se elibereze inainte de urmatoarea redare difuzor.
        time.sleep_ms(40)


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
    data = bytearray()
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
        except Exception:
            chunk = None
        if not chunk:
            return None
        data.extend(chunk)
        if pr_sensor is not None:
            try:
                pr_sensor.process()
            except Exception:
                pass
    return bytes(data)


def _play_pcm_stream_from_conn(conn, sample_rate, total_len, pr_sensor=None):
    """Citeste PCM stereo din socket si reda incremental (fara conversie grea pe ESP)."""
    if sample_rate < 8000 or sample_rate > 48000:
        sample_rate = 24000
    if total_len < 4 or total_len > 2000000:
        return False
    en = Pin(AMP_ENABLE_PIN, Pin.OUT)
    en.value(1)
    time.sleep_ms(2)
    audio = None
    try:
        # Mic prebuffer to absorb Wi-Fi jitter before first write.
        pre_target = min(16384, total_len)
        pre = bytearray()
        while len(pre) < pre_target:
            try:
                chunk0 = conn.recv(min(4096, pre_target - len(pre)))
            except Exception:
                chunk0 = None
            if not chunk0:
                break
            pre.extend(chunk0)
            if pr_sensor is not None:
                try:
                    pr_sensor.process()
                except Exception:
                    pass
        audio = I2S(
            0,
            sck=Pin(I2S_BCLK),
            ws=Pin(I2S_LRC),
            sd=Pin(I2S_DIN),
            mode=I2S.TX,
            bits=16,
            format=I2S.STEREO,
            rate=sample_rate,
            ibuf=65520,
        )
        got = 0
        carry = b""
        chunk_count = 0
        if pre:
            got = len(pre)
            rem = len(pre) % 4
            if rem:
                carry = bytes(pre[-rem:])
                pre = pre[:-rem]
            if pre:
                audio.write(pre)
        while got < total_len:
            need = min(4096, total_len - got)
            try:
                chunk = conn.recv(need)
            except Exception:
                chunk = None
            if not chunk:
                break
            got += len(chunk)
            if carry:
                chunk = carry + chunk
                carry = b""
            # Stereo PCM16: multiplu de 4 bytes.
            rem = len(chunk) % 4
            if rem:
                carry = chunk[-rem:]
                chunk = chunk[:-rem]
            if chunk:
                audio.write(chunk)
            chunk_count += 1
            if pr_sensor is not None and (chunk_count & 3) == 0:
                try:
                    pr_sensor.process()
                except Exception:
                    pass
        if carry:
            # ignora ultimul byte incomplet, evita zgomot
            carry = b""
        return got >= max(2, total_len - 2)
    finally:
        try:
            if audio:
                audio.deinit()
        except Exception:
            pass


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
        try:
            conn.settimeout(12.0)
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
# Config retea
# ==========================================
WIFI_SSID = "Orange-292q-2.4G"
WIFI_PASS = "Y8kCA4vx"
MQTT_BROKER = "broker.hivemq.com"
CLIENT_ID = "TriSense_Licenta_Robot"
TOPIC_VISION_TAGS = b"vision/tags"
TOPIC_ROBOT_CONTROL = b"robot/control"
TOPIC_ROBOT_SPEAK = b"robot/speak"  # salut retained de la PC (aceeasi incarcare JSON ca robot/control)


def _spin_hub(pr_sensor, count=40):
    """Cateva process() ca LPF2 sa nu moara in timpul init retea / MQTT / I2C."""
    for _ in range(count):
        pr_sensor.process()
        time.sleep_ms(2)


# ==========================================
# 1. LEGO imediat (inainte de WiFi)
# ==========================================
pr = PUPRemoteSensor(power=True)
pr.add_channel("obj", to_hub_fmt="b")
print("Comunicare LPF2 activata. Astept Hub-ul...")

# ==========================================
# 2. Camera + timere bucla
# ==========================================
i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
hl = None
huskylens_pornit = False
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
time.sleep_ms(300)
mqtt = None

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
    try:
        mqtt = MQTTClient(CLIENT_ID, MQTT_BROKER)
        mqtt.connect()
        _spin_hub(pr, 50)

        def _mqtt_control_cb(topic, msg):
            global pending_speak, pending_voice_tcp, _last_mqtt_speak_ts, _last_mqtt_speak_txt
            global _last_mqtt_speak_topic
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
                        pending_speak = t
                        print(">>> speak MQTT coada:", t[:72] + ("..." if len(t) > 72 else ""))
                # PC trimite JSON true; unele JSON-uri pot da int 1 sau string
                listen = o.get("listen")
                listen_on = listen is True or listen == 1 or listen == "true"
                if listen_on:
                    host = (o.get("pc_host") or o.get("pc_ip") or "").strip()
                    if not host:
                        try:
                            from secrets import PC_VOICE_IP as _pv

                            host = (_pv or "").strip() if isinstance(_pv, str) else ""
                        except ImportError:
                            host = ""
                    try:
                        vport = int(o.get("voice_port") or VOICE_TCP_PORT_DEFAULT)
                    except (TypeError, ValueError):
                        vport = VOICE_TCP_PORT_DEFAULT
                    try:
                        dur = int(o.get("duration_ms") or VOICE_RECORD_MS_DEFAULT)
                    except (TypeError, ValueError):
                        dur = VOICE_RECORD_MS_DEFAULT
                    if host and 200 <= dur <= 12000:
                        pending_voice_tcp = {
                            "host": host,
                            "port": vport,
                            "duration_ms": dur,
                        }
                    elif listen_on:
                        print("Voce: lipseste pc_host/pc_ip sau PC_VOICE_IP in secrets.py")
            except Exception as e:
                print("MQTT control err:", e)

        mqtt.set_callback(_mqtt_control_cb)
        mqtt.subscribe(TOPIC_ROBOT_CONTROL)
        mqtt.subscribe(TOPIC_ROBOT_SPEAK)
        print(
            ">>> MQTT CONECTAT la HiveMQ! (publish vision/tags; subscribe robot/control + robot/speak)"
        )
    except Exception as e:
        print("Eroare MQTT:", e)
        mqtt = None
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


def _robot_loop_body(connected, tts_pr_sensor, end_delay_ms):
    """O iteratie: MQTT, voce, hub debug, HuskyLens, update canal. tts_pr_sensor=None daca heartbeat e async."""
    global pending_speak, pending_voice_tcp, last_hub_connected, hub_fail_cycles, t_last_hub_print
    global timp_start, huskylens_pornit, hl, ultimul_timp_mqtt

    if mqtt:
        try:
            mqtt.check_msg()
        except Exception:
            pass

    if wlan.isconnected():
        tri_accept_play_tcp_once(tts_pr_sensor)

    if pending_speak:
        _txt = pending_speak
        pending_speak = None
        tri_speak_gemini(_txt, tts_pr_sensor)

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

    if not huskylens_pornit and time.ticks_diff(time.ticks_ms(), timp_start) > 2000:
        print("Incerc conectarea camerei HuskyLens...")
        try:
            if tts_pr_sensor is not None:
                _spin_hub(pr, 30)
            hl = HuskyLens(i2c)
            if tts_pr_sensor is not None:
                _spin_hub(pr, 30)
            hl.set_alg(ALGORITHM_OBJECT_CLASSIFICATION)
            if tts_pr_sensor is not None:
                _spin_hub(pr, 30)
            print(">>> HuskyLens OK! <<<")
            huskylens_pornit = True
        except Exception as e:
            print(">>> HuskyLens init esuat:", e)
            timp_start = time.ticks_ms()

    if huskylens_pornit and hl:
        obj = 0
        try:
            blocks = hl.get_blocks()
            if blocks:
                obj = blocks[0].ID
                print(">>> DEBUG LOCAL: Clasificare obiect ID:", obj)

                timp_curent = time.ticks_ms()
                if mqtt and time.ticks_diff(timp_curent, ultimul_timp_mqtt) > 2000:
                    payload = json.dumps({"id": obj})
                    try:
                        mqtt.publish(TOPIC_VISION_TAGS, payload.encode())
                        print("-> vision/tags:", payload)
                        tri_beep_stereo_ms(70)
                    except Exception:
                        pass
                    ultimul_timp_mqtt = timp_curent

        except OSError as e:
            print(">>> EROARE CABLURI CAMERA:", e)
            time.sleep_ms(500)

        pr.update_channel("obj", obj)

    time.sleep_ms(end_delay_ms)


async def _robot_main_async():
    asyncio.create_task(pr.process_async(40))
    await asyncio.sleep_ms(80)
    while True:
        connected = pr.lpup.connected
        _robot_loop_body(connected, None, 0)
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
    _robot_main_sync