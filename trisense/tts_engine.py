# -*- coding: utf-8 -*-
"""
Text-to-Speech pe PC (pyttsx3).
- speak(text): redare prin difuzorul PC-ului (pentru testare)
- synthesize_pcm(text): genereaza PCM mono int16 -> trimitem prin TCP la ESP
"""

from __future__ import annotations

import logging
import os
import struct
import tempfile
import threading
import wave

logger = logging.getLogger(__name__)


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
        """Genereaza PCM mono int16 din text (pyttsx3 -> WAV temp -> bytes).
        Returneaza (pcm_bytes, sample_rate). Pe Windows, SAPI scoate de obicei 22050 Hz.
        """
        text = (text or "").strip()
        if not text or self._engine is None:
            return b"", 16000
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with self._lock:
                try:
                    self._engine.save_to_file(text, tmp_path)
                    self._engine.runAndWait()
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


def _stereo_to_mono(pcm: bytes) -> bytes:
    if len(pcm) % 4 != 0:
        return pcm if len(pcm) % 2 == 0 else pcm[:-1]
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm), 4):
        l = struct.unpack_from("<h", pcm, i)[0]
        r = struct.unpack_from("<h", pcm, i + 2)[0]
        struct.pack_into("<h", out, i // 2, (l + r) // 2)
    return bytes(out)
