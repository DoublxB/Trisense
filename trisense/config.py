# -*- coding: utf-8 -*-
"""Setari centralizate pentru broker MQTT, topicuri si fisiere."""

import os
from pathlib import Path

# Directorul proiectului (folderul parinte al pachetului trisense)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# MQTT (compatibil HiveMQ public)
MQTT_BROKER = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USE_TLS = os.environ.get("MQTT_USE_TLS", "0") == "1"

# Text speak trimis la ESP (Gemini TTS) — sub ~120 caractere ca sa incapa in RAM JSON+PCM
ESP_SPEAK_MAX_CHARS = int(os.environ.get("ESP_SPEAK_MAX_CHARS", "120"))

# Topicuri obligatorii (nu schimba fara a alinia ESP32). "vision/tags" e numele canalului MQTT;
# payload-ul este tot {"id": N} = clasa HuskyLens (Object Classification), nu stickere.
TOPIC_VISION_TAGS = "vision/tags"
TOPIC_ROBOT_CONTROL = "robot/control"
# Salut retained — ESP-ul care se conecteaza dupa PC primeste ultimul mesaj la subscribe
TOPIC_ROBOT_SPEAK = "robot/speak"

# ID client PC (trebuie diferit de ESP32)
MQTT_CLIENT_ID_PC = os.environ.get("MQTT_CLIENT_ID_PC", "TriSense_PC_Brain_3")

# Fisiere locale
MEMORY_FILE = PROJECT_ROOT / "memorie_copil.json"
METRICS_CSV = PROJECT_ROOT / "trisense_metrics.csv"

# Google Gemini — vezi modele in quickstart: https://ai.google.dev/gemini-api/docs/quickstart
# Exemple: gemini-2.5-flash, gemini-3-flash-preview (exemplu din documentatie)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Server TCP: ESP trimite PCM de la microfon I2S -> PC (STT Gemini + dialog)
VOICE_TCP_BIND = os.environ.get("VOICE_TCP_BIND", "0.0.0.0")
VOICE_TCP_PORT = int(os.environ.get("VOICE_TCP_PORT", "8765"))
# Server audio pe ESP: PC trimite PCM TTS catre difuzorul robotului
ESP_AUDIO_TCP_PORT = int(os.environ.get("ESP_AUDIO_TCP_PORT", "8766"))
# Mod stabil implicit: trimite text prin MQTT, iar ESP vorbeste local (fara audio TCP din PC).
TRISENSE_TTS_OVER_TCP = os.environ.get("TRISENSE_TTS_OVER_TCP", "0") == "1"
TRISENSE_TTS_VOICE = os.environ.get("TRISENSE_TTS_VOICE", "Vindemiatrix")
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")

# TTS pe PC (pyttsx3). Implicit oprit: doar MQTT speak -> difuzor ESP. Pune TRISENSE_TTS_PC=1 pentru voce si pe laptop.
TRISENSE_TTS_PC = os.environ.get("TRISENSE_TTS_PC", "0") == "1"
