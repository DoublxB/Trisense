# -*- coding: utf-8 -*-
"""Setari centralizate pentru broker MQTT, topicuri si fisiere."""

import json
import os
from pathlib import Path
from typing import Optional

# Directorul proiectului (folderul parinte al pachetului trisense)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# MQTT (compatibil HiveMQ public)
MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.100.134")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USE_TLS = os.environ.get("MQTT_USE_TLS", "0") == "1"

# Text speak trimis la ESP (Gemini TTS) — sub ~120 caractere ca sa incapa in RAM JSON+PCM
ESP_SPEAK_MAX_CHARS = int(os.environ.get("ESP_SPEAK_MAX_CHARS", "120"))

# HuskyLens class ID → nume acțiune motrice pentru robot/control (trebuie să existe în firmware ESP).
# Exemplu: {"20":"breathe_in","21":"breathe_out","22":"dance"} — clasele 20–22 nu mai intră în ramura LEGO implicită.
VISION_ID_TO_ACTION_RAW = os.environ.get("VISION_ID_TO_ACTION", "{}")


def vision_id_to_action_map() -> dict[str, str]:
    """Parsare JSON din VISION_ID_TO_ACTION; chei string (ID HuskyLens) -> action string."""
    raw = (VISION_ID_TO_ACTION_RAW or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in obj.items():
        try:
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            out[str(k).strip()] = str(v).strip()
        except (TypeError, ValueError):
            continue
    return out


# Topicuri obligatorii (nu schimba fara a alinia ESP32). Payload vision/tags = {"id": N} clasa HuskyLens.
TOPIC_VISION_TAGS = "vision/tags"
TOPIC_ROBOT_CONTROL = "robot/control"
# Salut retained — ESP-ul care se conecteaza dupa PC primeste ultimul mesaj la subscribe
TOPIC_ROBOT_SPEAK = "robot/speak"

# ID client PC (trebuie diferit de ESP32)
MQTT_CLIENT_ID_PC = os.environ.get("MQTT_CLIENT_ID_PC", "TriSense_PC_Brain_3")

# Fisiere locale
MEMORY_FILE = PROJECT_ROOT / "memorie_copil.json"
METRICS_CSV = PROJECT_ROOT / "trisense_metrics.csv"


def default_google_credentials_path() -> Optional[Path]:
    """Fișier JSON service account pentru Vertex și Cloud API (fără a expune secretul în cod)."""
    for key in ("GOOGLE_APPLICATION_CREDENTIALS", "GCP_SERVICE_ACCOUNT_JSON", "TRISENSE_GOOGLE_KEY_JSON"):
        raw = (os.environ.get(key) or "").strip()
        if raw and Path(raw).is_file():
            return Path(raw)
    guess = PROJECT_ROOT / "cheie_google.json"
    if guess.is_file():
        return guess
    return None


def _project_id_from_service_account_json(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = data.get("project_id")
        return pid.strip() if isinstance(pid, str) else ""
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return ""


def resolved_gcp_project() -> str:
    p = (os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if p:
        return p
    cp = default_google_credentials_path()
    return _project_id_from_service_account_json(cp) if cp else ""


# Google Gemini — AI Studio API key SAU Vertex cu service account (cheie_google.json).
_gemini_vertex_env = os.environ.get("GEMINI_USE_VERTEX")
if (_gemini_vertex_env is None or str(_gemini_vertex_env).strip() == "") and default_google_credentials_path() is not None:
    # Cu JSON GCP în proiect, folosim implicit Vertex dacă nu e setat GEMINI_USE_VERTEX.
    GEMINI_USE_VERTEX = True
else:
    GEMINI_USE_VERTEX = str(_gemini_vertex_env or "0").strip().lower() in ("1", "true", "yes")

# Vertex (Gemini 3.x preview): recomandată regiunea `global`. Vezi .env dacă apare 404 pe modelul ales.
# Model ID-uri uzuale: gemini-3.1-flash-preview — dacă întoarce NOT_FOUND pentru proiectul tău, încearcă
# GEMINI_MODEL=gemini-3-flash-preview sau GEMINI_MODEL=gemini-3.1-flash-lite-preview (Vertex Model Garden).
_DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-preview"
GEMINI_MODEL = _DEFAULT_GEMINI_MODEL

GCP_PROJECT = resolved_gcp_project()
GCP_LOCATION = (os.environ.get("GCP_LOCATION") or "global").strip()


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
