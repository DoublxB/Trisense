# -*- coding: utf-8 -*-
"""
Punct de intrare: Creier TriSense 3.0 (PC).

Ruleaza din folderul proiectului:
  py run_trisense_brain.py

Setări: copiază .env.example în .env.
- API key: GEMINI_API_KEY (Google AI Studio), sau
- Vertex + credit GCP: GEMINI_USE_VERTEX=1 și `cheie_google.json` (vezi .env.example).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Asigura import din acelasi folder cu proiectul
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from trisense.brain import TriSenseBrain


def main() -> None:
    TriSenseBrain().run()


if __name__ == "__main__":
    main()
