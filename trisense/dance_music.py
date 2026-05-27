# -*- coding: utf-8 -*-
"""Muzica de fundal sintetica pentru Dance with me (2.3) — PCM mono int16 LE."""

from __future__ import annotations

import logging
import math
import struct
from pathlib import Path
from typing import Optional

from trisense.audio_push import send_pcm_to_esp
from trisense.config import ESP_AUDIO_TCP_PORT, PROJECT_ROOT

logger = logging.getLogger(__name__)

DANCE_SAMPLE_RATE = 24000
DANCE_DURATION_S = 12.0

# Melodie simpla majora (Hz) + ritm
_MELODY = (
    (523, 0.35),
    (659, 0.35),
    (784, 0.35),
    (659, 0.35),
    (523, 0.35),
    (659, 0.35),
    (988, 0.50),
    (784, 0.50),
    (659, 0.35),
    (523, 0.35),
    (587, 0.35),
    (659, 0.35),
    (698, 0.35),
    (784, 0.50),
    (659, 0.50),
    (523, 0.60),
)

_ASSETS_PCM = PROJECT_ROOT / "assets" / "dance_loop.pcm"


def synthesize_dance_loop_pcm(duration_s: float = DANCE_DURATION_S, sample_rate: int = DANCE_SAMPLE_RATE) -> bytes:
    """Genereaza loop upbeat (~12s) fara numpy — sine + envelope."""
    n = max(1, int(sample_rate * duration_s))
    out = bytearray(n * 2)
    beat_len = sample_rate * 0.25
    t_note = 0.0
    note_i = 0
    freq, note_dur = _MELODY[0]
    note_samples = int(note_dur * sample_rate)
    note_elapsed = 0

    for i in range(n):
        if note_elapsed >= note_samples:
            note_i = (note_i + 1) % len(_MELODY)
            freq, note_dur = _MELODY[note_i]
            note_samples = max(1, int(note_dur * sample_rate))
            note_elapsed = 0

        t = i / sample_rate
        # bass pulse pe beat
        beat = 0.22 if (i % beat_len) < beat_len * 0.12 else 0.0
        # envelope scurt pe fiecare nota
        env = min(1.0, note_elapsed / (sample_rate * 0.04)) * max(
            0.0, 1.0 - (note_elapsed / max(1, note_samples)) * 0.35
        )
        s = math.sin(2 * math.pi * freq * t) * env * 0.55
        s += math.sin(2 * math.pi * freq * 2 * t) * env * 0.12
        s += math.sin(2 * math.pi * 110 * t) * beat
        v = int(max(-32767, min(32767, s * 28000)))
        struct.pack_into("<h", out, i * 2, v)
        note_elapsed += 1
        t_note += 1.0 / sample_rate

    return bytes(out)


def load_dance_pcm_bytes() -> tuple[bytes, int]:
    """Prefera assets/dance_loop.pcm daca exista, altfel sintetizeaza."""
    if _ASSETS_PCM.is_file():
        data = _ASSETS_PCM.read_bytes()
        if len(data) >= 4:
            return data, DANCE_SAMPLE_RATE
    return synthesize_dance_loop_pcm(), DANCE_SAMPLE_RATE


def send_dance_music_to_esp(host: str, port: int = ESP_AUDIO_TCP_PORT) -> bool:
    if not host:
        return False
    pcm, rate = load_dance_pcm_bytes()
    ok = send_pcm_to_esp(host, port, pcm, rate)
    if ok:
        logger.info(
            "Dance music TCP trimis la %s:%s (~%.1fs @ %d Hz)",
            host,
            port,
            len(pcm) / (2 * rate),
            rate,
        )
    return ok


def ensure_assets_pcm() -> Path:
    """Scrie assets/dance_loop.pcm daca lipseste (util pt flash ESP)."""
    _ASSETS_PCM.parent.mkdir(parents=True, exist_ok=True)
    if not _ASSETS_PCM.is_file():
        _ASSETS_PCM.write_bytes(synthesize_dance_loop_pcm())
    return _ASSETS_PCM
