# -*- coding: utf-8 -*-
"""
Test local cu LOOP: microfon laptop -> STT -> brain (stare pastrata) -> TTS -> difuzor ESP.

Comportament aliniat cu fluxul ESP (run_voice_dialog.py):
  - metrics.start_session / end_session
  - auto-listen dupa intrebari (Act.6, Act.7, Stop/Go, story, etc.) — fara ENTER
  - la SELECTIE_JOC: ENTER manual ca sa alegi jocul
  - la BUILD_MODEL: asteapta buton DREAPTA + vision bridge (proceseaza vision/tags din MQTT)

Necesita in .env:
  - ROBOT_ESP_IP  = IP-ul ESP32 pe WiFi
  - TRISENSE_TTS_OVER_TCP=1  pentru audio pe difuzor prin TCP

Rulare:
  py testare/test_laptop_mic.py           # loop implicit
  py testare/test_laptop_mic.py --once    # o singura inregistrare

Oprire: Ctrl+C
"""

from __future__ import annotations

import io
import logging
import os
import queue
import sys
import time
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

_DEFAULT_MANUAL_SEC = float(os.environ.get("LAPTOP_MIC_RECORD_SEC", "5"))
_AUTO_MIN_SEC = 2.0
_AUTO_MAX_SEC = 30.0


def pcm16_mono_16k_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


def record_mic(seconds: float, samplerate: int = 16000) -> bytes:
    seconds = max(1.0, min(seconds, _AUTO_MAX_SEC))
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
    RobotState.START: "START",
    RobotState.SELECTIE_JOC: "liber — alege joc",
    RobotState.GUESS_EMOTION: "Act.6 — ghiceste emotia",
    RobotState.FOLLOW_PATTERN: "Act.7 — urmeaza pattern",
    RobotState.BUILD_MODEL: "Build Model — construieste + poza (buton dreapta)",
    RobotState.STOP_GO: "Stop/Go — raspunde la semnal",
    RobotState.CATEGORY_FLUENCY: "Category Fluency — numeste cuvinte",
    RobotState.TIME_ESTIMATE: "Time Estimate — spune stop",
    RobotState.DANCE_WITH_ME: "Dance with Me",
    RobotState.CO_CONSTRUCTED_STORY: "Poveste co-construita",
}


def _drain_vision_queue(brain: TriSenseBrain) -> int:
    """Proceseaza rezultate CAM/HuskyLens (ex. Build Model dupa buton dreapta)."""
    n = 0
    q = brain.mqtt.vision_queue
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        brain._handle_vision(item)
        n += 1
    return n


def _install_laptop_listen_hook(brain: TriSenseBrain) -> list[int]:
    """Inlocuieste MQTT listen catre ESP cu auto-record pe microfonul laptopului."""
    pending_ms = [0]

    def _laptop_publish_listen(*, duration_ms: int = 10000) -> bool:
        ms = int(duration_ms)
        ms = max(2000, min(ms, int(_AUTO_MAX_SEC * 1000)))
        pending_ms[0] = ms
        print(f"[AUTO-LISTEN] Microfon laptop pregatit (~{ms / 1000:.1f}s)")
        return True

    brain._publish_listen = _laptop_publish_listen  # type: ignore[method-assign]
    return pending_ms


def _fix_time_estimate_start(brain: TriSenseBrain) -> None:
    """La TIME_ESTIMATE, reseteaza _te_start dupa inregistrare (nu la publish_listen).
    Altfel elapsed include 15s inregistrare + STT + procesare, nu durata reala stop.
    """
    if brain.state == RobotState.TIME_ESTIMATE and hasattr(brain, "_te_start"):
        brain._te_start = time.time()


def _state_label(brain: TriSenseBrain) -> str:
    return _STATE_LABELS.get(brain.state, brain.state.name)


def _awaiting_camera(brain: TriSenseBrain) -> bool:
    return brain.state == RobotState.BUILD_MODEL and bool(getattr(brain, "_build_awaiting", False))


def _process_transcript(brain: TriSenseBrain, transcript: str, esp_ip: str) -> float:
    print(f"[STT] Am inteles: '{transcript}'")
    print("[BRAIN] Procesez... (poate dura 15-25s pentru unele jocuri)")
    t0 = time.time()
    brain.handle_voice_transcript(transcript, robot_only=True, esp_ip=esp_ip)
    dt = time.time() - t0
    print(f"[DONE] Procesare {dt:.1f}s. Stare noua: {_state_label(brain)}")
    print("=" * 60)
    return dt


def main() -> None:
    loop_mode = "--once" not in sys.argv

    esp_ip = _robot_esp_ip()
    print(f"[INIT] Robot ESP IP: {esp_ip or '(lipseste — pune ROBOT_ESP_IP in .env)'}")
    print(f"[INIT] TTS over TCP: {os.environ.get('TRISENSE_TTS_OVER_TCP', '0')}")
    print(
        f"[INIT] Mod: {'LOOP (auto-listen la jocuri, Ctrl+C oprire)' if loop_mode else 'O singura inregistrare'}"
    )
    if not esp_ip:
        print("[ERR] Lipseste ROBOT_ESP_IP in .env")
        raise SystemExit(1)

    brain = TriSenseBrain()
    pending_listen_ms = _install_laptop_listen_hook(brain)

    brain.mqtt.connect_background()
    print(f"[MQTT] Astept conexiune la {os.environ.get('MQTT_BROKER', '?')}...")
    connected = brain.mqtt.wait_connected(timeout=10.0)
    print("[MQTT] CONECTAT OK" if connected else "[MQTT] EROARE — broker offline!")

    child = brain.memory.get_child_name() or "friend"
    brain._child_name = child
    brain.state = RobotState.SELECTIE_JOC
    brain.metrics.start_session(child)
    print(f"[SESSION] Pornit pentru {child} (id={brain.metrics._session_id})")
    print("[HINT] La 'liber': ENTER + vorbeste. La jocuri active: ascultare automata dupa intrebarea robotului.")
    print("[HINT] Build Model: buton DREAPTA pe Hub + vision_esp32cam_bridge.py --on-request")

    turn = 0
    try:
        while True:
            turn += 1
            _drain_vision_queue(brain)

            if _awaiting_camera(brain):
                print(f"\n[TURA {turn}] Stare: {_state_label(brain)}")
                print("[CAM] Construieste modelul, apoi apasa BUTON DREAPTA pe Hub pentru poza.")
                print("      (tine pornit: py testare/vision_esp32cam_bridge.py --on-request)")
                print("[CAM] Apasa ENTER dupa poza ca sa verific rezultatul CAM, sau Ctrl+C.")
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    print("\n[STOP] Iesire.")
                    break
                n = _drain_vision_queue(brain)
                if n:
                    print(f"[CAM] Procesat {n} eveniment(e) vision.")
                else:
                    print("[CAM] Inca nu am primit vision/tags — verifica bridge-ul si IP camerei.")
                if not loop_mode:
                    break
                continue

            auto_ms = pending_listen_ms[0]
            if auto_ms > 0:
                pending_listen_ms[0] = 0
                seconds = auto_ms / 1000.0
                print(f"\n[TURA {turn}] Stare: {_state_label(brain)}")
                print(f"[AUTO] Robotul te asculta — vorbeste (~{seconds:.1f}s), fara ENTER...")
                pcm = record_mic(seconds=seconds)
                # TIME_ESTIMATE: elapsed se masoara din momentul in care copilul a terminat
                # de vorbit, nu de cand a inceput inregistrarea (altfel STT+procesare = +17s).
                _fix_time_estimate_start(brain)
            else:
                print(f"\n[TURA {turn}] Stare: {_state_label(brain)}")
                print("[ENTER] Apasa ENTER ca sa incepi inregistrarea, sau Ctrl+C pt oprire")
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    print("\n[STOP] Iesire.")
                    break
                pcm = record_mic(seconds=_DEFAULT_MANUAL_SEC)
                _fix_time_estimate_start(brain)

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
                if brain.state in (
                    RobotState.GUESS_EMOTION,
                    RobotState.FOLLOW_PATTERN,
                    RobotState.CO_CONSTRUCTED_STORY,
                    RobotState.STOP_GO,
                    RobotState.CATEGORY_FLUENCY,
                    RobotState.TIME_ESTIMATE,
                    RobotState.DANCE_WITH_ME,
                ):
                    pending_listen_ms[0] = int(_DEFAULT_MANUAL_SEC * 1000)
                    print("[AUTO] Reincerc ascultare automata...")
                if not loop_mode:
                    break
                continue

            _process_transcript(brain, transcript, esp_ip)
            _drain_vision_queue(brain)

            if not loop_mode:
                break
    finally:
        report = brain.metrics.end_session()
        if report:
            print(f"[SESSION] Raport salvat: {report}")
        brain.mqtt.stop()


if __name__ == "__main__":
    main()
