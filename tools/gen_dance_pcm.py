#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genereaza assets/dance_loop.pcm pentru Dance with me (mono int16 LE, 24000 Hz).

Rulare: py tools/gen_dance_pcm.py
Pe ESP (optional): mpremote cp assets/dance_loop.pcm :dance_loop.pcm
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trisense.dance_music import DANCE_SAMPLE_RATE, ensure_assets_pcm, synthesize_dance_loop_pcm


def main() -> None:
    path = ensure_assets_pcm()
    pcm = synthesize_dance_loop_pcm()
    path.write_bytes(pcm)
    print(path, len(pcm), "B @", DANCE_SAMPLE_RATE, "Hz mono int16")


if __name__ == "__main__":
    main()
