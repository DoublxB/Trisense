# -*- coding: utf-8 -*-
"""
Text-to-Speech pe PC (pyttsx3 sau fallback la print).
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self) -> None:
        self._engine = None
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            try:
                self._engine.setProperty("rate", 170)
            except Exception:
                pass
        except Exception as e:
            logger.warning("pyttsx3 indisponibil (%s) — folosesc doar print", e)
            self._engine = None

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"[TTS] {text}", flush=True)
        if self._engine is None:
            return
        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as e:
            logger.warning("TTS speak esuat: %s", e)
