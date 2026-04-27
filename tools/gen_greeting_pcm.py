#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genereaza assets/greeting.pcm pentru ESP32 (mono int16 LE, 24000 Hz).

Necesita: pyttsx3, numpy. Rulare: py tools/gen_greeting_pcm.py
Copiere pe placuta: mpremote cp assets/greeting.pcm :greeting.pcm
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parent.parent
TEXT = "Hi! I'm TrySense! Let's play!"


def main() -> None:
    import pyttsx3

    wav_path = SCRIPT / "_greeting_tmp.wav"
    pcm_path = SCRIPT / "assets" / "greeting.pcm"

    pcm_path.parent.mkdir(parents=True, exist_ok=True)

    e = pyttsx3.init()
    e.save_to_file(TEXT, str(wav_path))
    e.runAndWait()

    if not wav_path.is_file():
        raise SystemExit("pyttsx3 nu a produs WAV")

    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        nch = w.getnchannels()
        nf = w.getnframes()
        raw = w.readframes(nf)

    x = np.frombuffer(raw, dtype=np.int16)
    if nch == 2:
        x = x.reshape(-1, 2).mean(axis=1).astype(np.int16)

    target_sr = 24000
    new_len = max(1, int(len(x) * target_sr / sr))
    xi = np.linspace(0, len(x) - 1, new_len)
    y = np.interp(xi, np.arange(len(x)), x.astype(np.float64)).astype(np.int16)

    pcm_bytes = y.tobytes()
    pcm_path.write_bytes(pcm_bytes)
    print(pcm_path, len(pcm_bytes), "bytes,", target_sr, "Hz mono.")

    wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
