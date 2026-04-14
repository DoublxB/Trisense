# -*- coding: utf-8 -*-
"""
Server TCP: ESP32 trimite PCM 16-bit mono 16 kHz (header TRIS + lungime + date).
PC construieste WAV, transcrie cu Gemini, apoi TriSenseBrain raspunde:
- preferat: TTS pe PC + push audio TCP catre ESP (difuzor robot)
- fallback: MQTT speak (TTS pe ESP)
"""

from __future__ import annotations

import io
import logging
import socket
import struct
import sys
import threading
import wave
from typing import TYPE_CHECKING, Any

from trisense.config import VOICE_TCP_BIND, VOICE_TCP_PORT

if TYPE_CHECKING:
    from trisense.brain import TriSenseBrain

logger = logging.getLogger(__name__)

MAGIC = b"TRIS"
_MAX_PCM = 4 * 1024 * 1024  # ~128 s la 16 kHz mono int16 — plafon de siguranta


def _flush_log_output() -> None:
    """Thread-ul TCP de voce: pe Windows mesajele pot ramane in buffer fara flush."""
    for h in logging.root.handlers:
        try:
            if hasattr(h, "flush"):
                h.flush()
        except Exception:
            pass
    try:
        sys.stderr.flush()
    except Exception:
        pass


def pcm16_mono_16k_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


def _handle_client(conn: socket.socket, addr: Any, brain: TriSenseBrain) -> None:
    try:
        logger.info("Voce TCP: conexiune noua de la %s", addr)
        _flush_log_output()
        conn.settimeout(120.0)
        header = b""
        while len(header) < 8:
            chunk = conn.recv(8 - len(header))
            if not chunk:
                logger.warning("Voce TCP: inchis inainte de header 8B de la %s", addr)
                _flush_log_output()
                return
            header += chunk
        if header[:4] != MAGIC:
            logger.warning("Voce TCP: magic invalid de la %s", addr)
            _flush_log_output()
            return
        (length,) = struct.unpack("<I", header[4:8])
        if length > _MAX_PCM or length < 200:
            logger.warning("Voce TCP: lungime invalida %s de la %s", length, addr)
            _flush_log_output()
            return
        logger.info("Voce TCP: primesc %s octeti PCM de la %s (asteapta ~10s inregistrare ESP)...", length, addr)
        _flush_log_output()
        data = bytearray()
        while len(data) < length:
            chunk = conn.recv(min(65536, length - len(data)))
            if not chunk:
                break
            data += chunk
        if len(data) < length:
            logger.warning("Voce TCP: date incomplete %s/%s", len(data), length)
            _flush_log_output()
            return
        logger.info("Voce TCP: PCM primit %s B -> STT Gemini...", len(data))
        _flush_log_output()
        wav = pcm16_mono_16k_to_wav(bytes(data))
        transcript = brain.ai.transcribe_wav(wav)
        logger.info("Voce TCP transcriere: %s", (transcript or "")[:300])
        _flush_log_output()
        esp_ip = addr[0] if isinstance(addr, tuple) and addr else None
        brain.handle_voice_transcript(transcript, robot_only=True, esp_ip=esp_ip)
        _flush_log_output()
    except Exception as e:
        logger.exception("Voce TCP: eroare client %s: %s", addr, e)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve_forever(
    brain: TriSenseBrain,
    bind: str | None = None,
    port: int | None = None,
) -> None:
    bind = bind or VOICE_TCP_BIND
    port = port or VOICE_TCP_PORT
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind, port))
    sock.listen(5)
    logger.info("Voce TCP: ascult pe %s:%s (ESP -> microfon -> STT -> speak)", bind, port)
    while True:
        conn, addr = sock.accept()
        logger.info("Voce TCP: accept() client %s (pornesc thread handler)", addr)
        _flush_log_output()
        t = threading.Thread(
            target=_handle_client,
            args=(conn, addr, brain),
            daemon=True,
        )
        t.start()


def start_voice_tcp_background(
    brain: TriSenseBrain,
    bind: str | None = None,
    port: int | None = None,
) -> threading.Thread:
    th = threading.Thread(
        target=serve_forever,
        args=(brain, bind, port),
        daemon=True,
    )
    th.start()
    return th
