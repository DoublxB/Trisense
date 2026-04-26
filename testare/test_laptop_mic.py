# -*- coding: utf-8 -*-
"""
Test local: microfon laptop -> STT Gemini -> LLM -> TTS pe PC -> PCM TCP -> difuzor ESP.

Rulare:
  py testare/test_laptop_mic.py
"""

from __future__ import annotations

import io
import logging
import os
import sys
import wave
from pathlib import Path

import sounddevice as sd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

from trisense.brain import TriSenseBrain


def pcm16_mono_16k_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


def record_mic(seconds: float = 4.0, samplerate: int = 16000) -> bytes:
    print(f"[REC] Vorbeste acum ~{seconds:.1f}s...")
    data = sd.rec(
        int(seconds * samplerate),
        samplerate=samplerate,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    return data.tobytes()


def main() -> None:
    esp_ip = os.environ.get("PC_VOICE_IP", "").strip()
    print(f"[INIT] ESP IP: {esp_ip or '(negasit in .env)'}")
    print(f"[INIT] TTS over TCP: {os.environ.get('TRISENSE_TTS_OVER_TCP', '0')}")

    brain = TriSenseBrain()
    brain.mqtt.connect_background()

    print(f"[MQTT] Astept conexiune la {os.environ.get('MQTT_BROKER', '?')}...")
    connected = brain.mqtt.wait_connected(timeout=10.0)
    print("[MQTT] CONECTAT OK" if connected else "[MQTT] EROARE — broker offline!")

    pcm = record_mic(seconds=4.0, samplerate=16000)
    wav = pcm16_mono_16k_to_wav(pcm)

    print("[STT] Transcriu audio...")
    transcript = brain.ai.transcribe_wav(wav).strip()

    if transcript:
        print(f"[STT] Am inteles: '{transcript}'")
    else:
        print("[STT] EROARE — nu am inteles nimic. Vorbeste mai tare.")
        return

    print("[LLM+TTS] Generez raspuns si trimit audio la ESP prin TCP...")
    # robot_only=True: nu incearca pyttsx3 pe PC (nu vrem sunet pe laptop)
    # esp_ip: trimite PCM direct la difuzorul ESP pe portul 8766
    text = brain.ai.reply(
        f"The child said this through the microphone (transcript): {transcript}. "
        "Reply very briefly, friendly, in English, as TriSense.",
        brain.memory.get_child_name() or "friend",
    )
    text = (text or "").strip().strip("\"'")
    print(f"[LLM] Raspuns TriSense: '{text}'")
    delivered = brain._announce(text, robot_only=True, esp_ip=esp_ip)
    if delivered:
        print("[DONE] Raspuns livrat: TCP audio sau fallback MQTT speak.")
    else:
        print("[FAIL] Raspuns generat, dar nu a fost livrat catre robot.")


if __name__ == "__main__":
    main()
