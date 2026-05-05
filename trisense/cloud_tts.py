# -*- coding: utf-8 -*-
"""Google Cloud Text-to-Speech — PCM LINEAR16 (aceleași credentials ca Vertex)."""

from __future__ import annotations

import logging
import os
from typing import Optional

from trisense.config import GCP_PROJECT, default_google_credentials_path

logger = logging.getLogger(__name__)

_client: Optional[object] = None

GCP_TTS_VOICE = os.environ.get("GCP_TTS_VOICE", "en-US-Neural2-F").strip() or "en-US-Neural2-F"
GCP_TTS_LANGUAGE = os.environ.get("GCP_TTS_LANGUAGE", "en-US").strip() or "en-US"
GCP_TTS_SAMPLE_RATE_HZ = int(os.environ.get("GCP_TTS_SAMPLE_RATE_HZ", "24000"))


def _get_client():  # type: ignore[no-untyped-def]
    global _client
    if _client is not None:
        return _client
    cp = default_google_credentials_path()
    if cp:
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(cp))
    try:
        from google.cloud import texttospeech_v1 as texttospeech
    except ImportError:
        logger.warning("google-cloud-texttospeech lipsă — pip install google-cloud-texttospeech")
        return None
    kwargs = {}
    if GCP_PROJECT:
        kwargs["client_options"] = {"quota_project_id": GCP_PROJECT}
    try:
        _client = texttospeech.TextToSpeechClient(**kwargs)
    except Exception as e:
        logger.warning("Cloud TTS client init esuat: %s", e)
        _client = None
        return None
    return _client


def synthesize_linear16_pcm(text: str, *, voice_name: Optional[str] = None) -> tuple[bytes, int]:
    """Returnează mono int16 LE brut (fără header WAV) și sample rate Hz."""
    t = (text or "").strip()
    if not t:
        return b"", GCP_TTS_SAMPLE_RATE_HZ
    client = _get_client()
    if client is None:
        return b"", GCP_TTS_SAMPLE_RATE_HZ
    voice = (voice_name or GCP_TTS_VOICE or "en-US-Neural2-F").strip()
    lang = GCP_TTS_LANGUAGE
    sr = GCP_TTS_SAMPLE_RATE_HZ
    if sr not in (8000, 12000, 16000, 22050, 24000):
        sr = 24000
    try:
        from google.cloud import texttospeech_v1 as texttospeech
    except ImportError:
        return b"", sr

    try:
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=t),
            voice=texttospeech.VoiceSelectionParams(
                language_code=lang,
                name=voice,
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=sr,
            ),
        )
    except Exception as e:
        logger.warning("Cloud TTS synthesize_speech esuat: %s", e)
        return b"", sr
    raw = getattr(response, "audio_content", None) or b""
    if not raw or len(raw) < 100:
        logger.warning("Cloud TTS: PCM gol sau foarte scurt.")
        return b"", sr
    logger.info(
        "Cloud TTS: PCM %d B @ %d Hz (~%.2f s)",
        len(raw),
        sr,
        len(raw) / (2 * max(1, sr)),
    )
    return raw if len(raw) % 2 == 0 else raw[:-1], sr


def cloud_tts_ready() -> bool:
    """True dacă avem biblioteca și un fișier de credentials JSON configurat."""
    try:
        from google.cloud import texttospeech_v1  # noqa: F401
    except ImportError:
        return False
    return default_google_credentials_path() is not None
