# -*- coding: utf-8 -*-
"""
Creier TriSense + server TCP pentru dialog prin microfonul ESP32.

1. Pe PC: seteaza in .env GEMINI_USE_VERTEX=1 și cheie `cheie_google.json` SAU GEMINI_API_KEY (AI Studio).
2. Porneste firewall pentru portul TCP pe LAN (Windows: regula inbound TCP).
3. In secrets.py pe ESP: PC_VOICE_IP = "IP-ul-PC-ului" (aceeasi retea WiFi ca robotul).
4. Ruleaza: py run_voice_dialog.py
5. Demo PAS 5 (Let's talk): trimite MQTT `{"listen": true}` pe robot/control (~10 s inregistrare).
   Gesturi dupa transcript fara LLM sport: fotbal / football / soccer → brat dreapta; rugby / basketball / handball → brat stanga.
   PAS 4 show respiratie pe hub (~10 s): „guided breathing”, „breathing exercise” sau respiratie ghidata.

Flux ulterior microfon ESP: TCP -> Gemini STT -> raspuns Gemini -> Audio TCP sau MQTT speak.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    # override=True: .env bate variabilele deja setate in Windows (altfel ramane TTS_PC pornit din greseala)
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from trisense.brain import TriSenseBrain
from trisense.voice_tcp_server import start_voice_tcp_background


def main() -> None:
    brain = TriSenseBrain()
    start_voice_tcp_background(brain)
    brain.run()


if __name__ == "__main__":
    main()
