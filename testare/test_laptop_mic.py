# -*- coding: utf-8 -*-
"""
Test local cu LOOP: microfon laptop -> STT -> brain (stare pastrata) -> TTS -> difuzor ESP.

Acelasi brain ruleaza continuu intre ture, deci Act. 6 (Guess the Emotion) si
Act. 7 (Follow the Pattern) functioneaza corect pe mai multe schimburi de replici.

Necesita in .env:
  - ROBOT_ESP_IP  = IP-ul ESP32 pe WiFi
  - TRISENSE_TTS_OVER_TCP=1  pentru audio pe difuzor prin TCP

Rulare:
  py testare/test_laptop_mic.py           # loop implicit
  py testare/test_laptop_mic.py --once    # o singura inregistrare (comportament vechi)

Oprire: Ctrl+C sau Enter fara sa vorbesti (transcript gol).
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
from trisense.states import RobotState


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


def _robot_esp_ip() -> str:
    for key in ("ROBOT_ESP_IP", "ESP32_IP", "TRISENSE_ROBOT_IP"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


_STATE_LABELS = {
    RobotState.SELECTIE_JOC: "liber",
    RobotState.GUESS_EMOTION: "Act.6 — asteapta ghicire emotie",
    RobotState.FOLLOW_PATTERN: "Act.7 — asteapta pas pattern",
}


def main() -> None:
    loop_mode = "--once" not in sys.argv

    esp_ip = _robot_esp_ip()
    print(f"[INIT] Robot ESP IP: {esp_ip or '(lipseste — pune ROBOT_ESP_IP in .env)'}")
    print(f"[INIT] TTS over TCP: {os.environ.get('TRISENSE_TTS_OVER_TCP', '0')}")
    print(f"[INIT] Mod: {'LOOP (Ctrl+C pentru oprire)' if loop_mode else 'O singura inregistrare'}")
    if not esp_ip:
        print("[ERR] Lipseste ROBOT_ESP_IP in .env")
        raise SystemExit(1)

    brain = TriSenseBrain()
    brain.mqtt.connect_background()
    print(f"[MQTT] Astept conexiune la {os.environ.get('MQTT_BROKER', '?')}...")
    connected = brain.mqtt.wait_connected(timeout=10.0)
    print("[MQTT] CONECTAT OK" if connected else "[MQTT] EROARE — broker offline!")

    turn = 0
    while True:
        turn += 1
        state_label = _STATE_LABELS.get(brain.state, brain.state.name)
        print(f"\n[TURA {turn}] Stare brain: {state_label}")
        print("[APASA ENTER ca sa incepi inregistrarea, sau Ctrl+C pt oprire]")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            print("\n[STOP] Iesire.")
            break

        pcm = record_mic(seconds=5.0, samplerate=16000)
        wav = pcm16_mono_16k_to_wav(pcm)

        print("[STT] Transcriu audio...")
        try:
            transcript = brain.ai.transcribe_wav(wav).strip()
        except Exception as e:
            print(f"[STT] Eroare: {e}")
            if not loop_mode:
                break
            continue

        if not transcript:
            print("[STT] Nu am inteles nimic. Vorbeste mai tare.")
            if not loop_mode:
                break
            continue

        print(f"[STT] Am inteles: '{transcript}'")
        print("[BRAIN] Procesez... (poate dura 15-25s pentru Act.6/Act.7)")
        import time as _t
        t0 = _t.time()
        brain.handle_voice_transcript(transcript, robot_only=True, esp_ip=esp_ip)
        dt = _t.time() - t0
        print(f"[DONE] Procesare {dt:.1f}s. Stare noua brain: {_STATE_LABELS.get(brain.state, brain.state.name)}")
        print("=" * 60)

        if not loop_mode:
            break


if __name__ == "__main__":
    main()
