#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genereaza assets/inspire.pcm si assets/expire.pcm (mono int16 LE, 24000 Hz).

Sunet sintetic („aer”), nu voce — pentru PAS 4 pe ESP (difuzor I2S).

Rulare: py tools/gen_breathe_pcm.py
Pe ESP dupa WiFi-ready: mpremote cp assets/inspire.pcm :inspire.pcm
                         mpremote cp assets/expire.pcm :expire.pcm

Necesita: numpy (py -m pip install numpy).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parent.parent
SR = 24000
RNG = np.random.default_rng(seed=73)


def _smooth(r: np.ndarray, win: int) -> np.ndarray:
    win = max(3, win)
    k = np.ones(win, dtype=np.float64) / float(win)
    return np.convolve(r, k, mode="same")


def make_inspire() -> bytes:
    """~1.35 s crestere + usoara coborare."""
    dur = 1.35
    n = int(SR * dur)
    x = RNG.standard_normal(n).astype(np.float64)
    x = _smooth(x, int(SR * 0.012))
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    # ramp in/out pe zgomot filtrat
    env = (np.sin(np.pi * t) ** 0.55) * (0.15 + 0.85 * (t**0.4))
    sig = x * env * 26000.0
    pk = np.max(np.abs(sig)) + 1e-12
    sig = sig * min(32600.0 / pk, 1.85)
    return np.clip(sig, -32767, 32767).astype("<i2").tobytes()


def make_expire() -> bytes:
    """~1.25 s coborare („suflat”)."""
    dur = 1.25
    n = int(SR * dur)
    x = RNG.standard_normal(n).astype(np.float64)
    x = _smooth(x, int(SR * 0.018))
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    env = (1.0 - t) ** 0.85 * np.sin(np.pi * (1.0 - t) * 0.65)
    sig = x * env * 24000.0
    pk = np.max(np.abs(sig)) + 1e-12
    sig = sig * min(32600.0 / pk, 2.05)
    return np.clip(sig, -32767, 32767).astype("<i2").tobytes()


def main() -> None:
    root = SCRIPT / "assets"
    root.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("inspire.pcm", make_inspire()),
        ("expire.pcm", make_expire()),
    ):
        path = root / name
        path.write_bytes(data)
        print(path, len(data), "B @", SR, "Hz mono int16")


if __name__ == "__main__":
    main()
