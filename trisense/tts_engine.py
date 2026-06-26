# -*- coding: utf-8 -*-
"""
Text-to-Speech pe PC (pyttsx3).
- speak(text): redare prin difuzorul PC-ului (pentru testare)
- synthesize_pcm(text): genereaza PCM mono int16 -> trimitem prin TCP la ESP
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import struct
import sys
import tempfile
import threading
import wave

logger = logging.getLogger(__name__)

_RO_VOICE_HINTS = ("andrei", "romanian", "romana", "română", "ro-ro", "m1048")
_EDGE_TTS_DEFAULT_VOICE = "ro-RO-AlinaNeural"


def _pick_romanian_voice(engine) -> None:
    """Pe Windows/SAPI alege vocea română dacă există."""
    try:
        voices = engine.getProperty("voices") or []
    except Exception:
        return
    for v in voices:
        blob = " ".join(
            str(getattr(v, attr, "") or "")
            for attr in ("id", "name", "languages")
        ).lower()
        if any(h in blob for h in _RO_VOICE_HINTS):
            try:
                engine.setProperty("voice", v.id)
                logger.info("pyttsx3: voce romana selectata (%s)", getattr(v, "name", v.id))
            except Exception:
                pass
            return


class TTSEngine:
    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            try:
                self._engine.setProperty("rate", 170)
            except Exception:
                pass
            _pick_romanian_voice(self._engine)
        except Exception as e:
            logger.warning("pyttsx3 indisponibil (%s) — folosesc doar print", e)
            self._engine = None

    @property
    def available(self) -> bool:
        return self._engine is not None

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"[TTS] {text}", flush=True)
        if self._engine is None:
            return
        with self._lock:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as e:
                logger.warning("TTS speak esuat: %s", e)

    def synthesize_pcm(self, text: str) -> tuple[bytes, int]:
        """Genereaza PCM mono int16 (edge-tts -> fallback pyttsx3).

        Ordine fallback local:
        1) edge-tts (romana, online, calitate mai buna)
        2) pyttsx3 (offline/legacy)

        Pe Windows, pyttsx3+SAPI are bug cunoscut: la al 2-lea save_to_file
        in acelasi engine, runAndWait() blocheaza la infinit. Reinitializam
        engine-ul la fiecare apel ca sa evitam blocajul.
        """
        text = (text or "").strip()
        if not text:
            return b"", 16000
        pcm_edge, sr_edge = self._synthesize_pcm_edge_tts(text)
        if pcm_edge:
            return pcm_edge, sr_edge
        if self._engine is None:
            return b"", 16000
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with self._lock:
                try:
                    import pyttsx3

                    eng = pyttsx3.init()
                    try:
                        eng.setProperty("rate", 170)
                    except Exception:
                        pass
                    _pick_romanian_voice(eng)
                    eng.save_to_file(text, tmp_path)
                    eng.runAndWait()
                    try:
                        eng.stop()
                    except Exception:
                        pass
                    del eng
                except Exception as e:
                    logger.warning("pyttsx3 save_to_file esuat: %s", e)
                    return b"", 16000
            try:
                size = os.path.getsize(tmp_path)
            except OSError:
                size = 0
            if size < 100:
                logger.warning("pyttsx3: WAV prea mic (%d B) — TTS local nu a generat audio.", size)
                return b"", 16000
            with wave.open(tmp_path, "rb") as wf:
                ch = wf.getnchannels()
                sr = wf.getframerate() or 16000
                sw = wf.getsampwidth()
                frames = wf.readframes(wf.getnframes())
            if sw != 2:
                logger.warning("pyttsx3: WAV nu e PCM 16-bit (sampwidth=%d) — ignor.", sw)
                return b"", sr
            pcm = frames if ch == 1 else _stereo_to_mono(frames)
            if not pcm or len(pcm) < 200:
                return b"", sr
            return pcm, sr
        except Exception as e:
            logger.warning("pyttsx3 synthesize_pcm esuat: %s", e)
            return b"", 16000
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _synthesize_pcm_edge_tts(self, text: str) -> tuple[bytes, int]:
        voice = (os.environ.get("TRISENSE_EDGE_TTS_VOICE") or _EDGE_TTS_DEFAULT_VOICE).strip()
        rate = (os.environ.get("TRISENSE_EDGE_TTS_RATE") or "+0%").strip()
        volume = (os.environ.get("TRISENSE_EDGE_TTS_VOLUME") or "+0%").strip()
        pitch = (os.environ.get("TRISENSE_EDGE_TTS_PITCH") or "+0Hz").strip()
        tmp_path = ""
        removed_paths: list[str] = []
        try:
            # Repo root has `secrets.py`; edge-tts needs stdlib `secrets`.
            cwd = os.getcwd()
            for path in ("", cwd):
                while path in sys.path:
                    sys.path.remove(path)
                    removed_paths.append(path)
            loaded_secrets = sys.modules.get("secrets")
            loaded_secrets_file = str(getattr(loaded_secrets, "__file__", "") or "").lower()
            if loaded_secrets_file.endswith("\\secrets.py"):
                sys.modules.pop("secrets", None)
            secrets_mod = importlib.import_module("secrets")
            if not hasattr(secrets_mod, "token_hex"):
                raise RuntimeError("stdlib secrets/token_hex unavailable")
            edge_tts = importlib.import_module("edge_tts")
            sf = importlib.import_module("soundfile")
        except Exception as e:
            for p in reversed(removed_paths):
                sys.path.insert(0, p)
            logger.debug("edge-tts indisponibil (%s)", e)
            return b"", 24000
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            asyncio.run(
                edge_tts.Communicate(
                    text=text,
                    voice=voice,
                    rate=rate or "+0%",
                    volume=volume or "+0%",
                    pitch=pitch or "+0Hz",
                ).save(tmp_path)
            )
            data, sample_rate = sf.read(tmp_path, dtype="int16", always_2d=True)
            if data.size == 0:
                return b"", 24000
            if data.shape[1] > 1:
                mono = ((data[:, 0].astype("int32") + data[:, 1].astype("int32")) // 2).astype("int16")
            else:
                mono = data[:, 0]
            pcm = mono.tobytes()
            if len(pcm) < 200:
                return b"", int(sample_rate or 24000)
            logger.info(
                "TTS local edge-tts (%s): PCM %d B @ %d Hz (~%.2f s).",
                voice,
                len(pcm),
                int(sample_rate or 24000),
                len(pcm) / (2 * max(1, int(sample_rate or 24000))),
            )
            return pcm, int(sample_rate or 24000)
        except Exception as e:
            logger.warning("edge-tts synthesize esuat: %s", e)
            return b"", 24000
        finally:
            for p in reversed(removed_paths):
                sys.path.insert(0, p)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def _stereo_to_mono(pcm: bytes) -> bytes:
    if len(pcm) % 4 != 0:
        return pcm if len(pcm) % 2 == 0 else pcm[:-1]
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm), 4):
        l = struct.unpack_from("<h", pcm, i)[0]
        r = struct.unpack_from("<h", pcm, i + 2)[0]
        struct.pack_into("<h", out, i // 2, (l + r) // 2)
    return bytes(out)
