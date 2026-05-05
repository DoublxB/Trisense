# -*- coding: utf-8 -*-
"""
Demo PAS 3: salut stabil fara Gemini pe ESP (pyttsx3 pe PC → PCM TCP :8766).

NU foloseste MQTT; pentru varianta fisier PCM pe ESP vezi greeting.pcm si tri_play_greeting_pcm in main_robot.

Rulare:
  py testare\\demo_speak_tcp.py
  py testare\\demo_speak_tcp.py \"Hi I'm TriSense! Let's breathe and play!\"

Necesita in .env:
  PC_VOICE_IP = <IP ESP32 dupa WiFi>   (acelasi lucru ca pentru test_laptop_mic cu TTS over TCP)

ESP: main_robot.py pornit; in consola: \"Audio TCP server activ pe port 8766\".
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

from trisense.audio_push import send_pcm_to_esp
from trisense.config import ESP_AUDIO_TCP_PORT
from trisense.tts_engine import TTSEngine

logger = logging.getLogger(__name__)

_DEFAULT_TEXT = "Hi, I'm TriSense! Let's breathe and play!"


def main() -> None:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        text = _DEFAULT_TEXT

    host = (os.environ.get("PC_VOICE_IP") or "").strip()
    if not host:
        print(
            "[ERR] Lipseste PC_VOICE_IP in .env (IP-ul ESP32-ului pe aceeasi Wi‑Fi). "
            "Vezi README_FOR_MARIUS.md — Pasul 4."
        )
        sys.exit(1)

    print(f"[TCP TTS] Trimite la {host}:{ESP_AUDIO_TCP_PORT}: {text[:120]!r}")

    tts = TTSEngine()
    if not tts.available:
        print("[ERR] pyttsx3 indisponibil — pip install pyttsx3")
        sys.exit(1)

    pcm, sample_rate = tts.synthesize_pcm(text)
    if not pcm:
        print("[ERR] synthesize_pcm a returnat audio gol.")
        sys.exit(1)

    ok = send_pcm_to_esp(host, ESP_AUDIO_TCP_PORT, pcm, sample_rate)
    if ok:
        print("[OK] Audio TCP trimis catre difuzorul robotului.")
    else:
        print("[FAIL] Conexiune esuata sau timeout. Verifica IP ESP, Wi‑Fi, firewall, port 8766 pe ESP.")
        sys.exit(1)


if __name__ == "__main__":
    main()
