# -*- coding: utf-8 -*-
"""
Integrare Google Gemini (SDK oficial google-genai, vezi quickstart):
https://ai.google.dev/gemini-api/docs/quickstart
Interfata publica (reply) ramane compatibila cu brain.py si TTS.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import struct
import wave
from typing import Optional

from trisense.config import GEMINI_MODEL, GEMINI_TTS_MODEL, TRISENSE_TTS_VOICE

logger = logging.getLogger(__name__)


def _project_id_from_credentials_json(path_str: str) -> str:
    try:
        with open(path_str, encoding="utf-8") as f:
            obj = json.load(f)
        pid = obj.get("project_id")
        return pid.strip() if isinstance(pid, str) else ""
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return ""

SYSTEM_PROMPT_TRISENSE = """You are TriSense, a friendly and patient robot companion for children.
You are a calm and encouraging tutor, adapted for autistic children: short sentences, clarity, no sarcasm,
no pressure. Always use the child's name when provided. Do not provide medical advice;
focus on play activities, encouragement, and simple routines. Language: English."""


class TriSenseAI:
    """
    Google Gen AI SDK (`google-genai`): fie GEMINI_API_KEY (AI Studio), fie Vertex AI cu service account JSON.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self._api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self._model_name = model or GEMINI_MODEL
        self._client = None

        try:
            from trisense.config import (
                GEMINI_USE_VERTEX,
                GCP_LOCATION,
                GCP_PROJECT,
                default_google_credentials_path,
            )

            cred_path = default_google_credentials_path()
            if cred_path is not None:
                os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(cred_path))

            project = (GCP_PROJECT or "").strip()
            location = GCP_LOCATION.strip() if GCP_LOCATION else "global"
            use_vertex = GEMINI_USE_VERTEX

            from google import genai

            if use_vertex:
                cred_file = ""
                if cred_path is not None:
                    cred_file = str(cred_path)
                    if not project:
                        project = _project_id_from_credentials_json(cred_file).strip()
                if cred_file and project:
                    self._client = genai.Client(vertexai=True, project=project, location=location)
                    logger.info("Gemini via Vertex AI (project=%s, location=%s, model=%s)", project, location, self._model_name)
                    return
                logger.warning(
                    "GEMINI_USE_VERTEX=1 dar lipsesc credentials (cheie_google.json sau GOOGLE_APPLICATION_CREDENTIALS) "
                    "sau project_id în JSON / GCP_PROJECT."
                )

            if self._api_key:
                self._client = genai.Client(api_key=self._api_key)
        except Exception as e:
            logger.warning("Google GenAI (google-genai) nu e disponibil: %s", e)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def reply(
        self,
        user_message: str,
        child_name: str,
        max_tokens: int = 400,
    ) -> str:
        """Generate a TriSense reply (same contract used by brain.py)."""
        if not self._client:
            return f"[TriSense] {user_message} (seteaza GEMINI_API_KEY sau GEMINI_USE_VERTEX=1 cu cheie_google.json / GCP)"

        name = child_name.strip() if child_name else "friend"
        user_turn = (
            f"The child name is: {name}. Address them by name sometimes.\n\n"
            f"Task:\n{user_message}"
        )

        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self._model_name,
                contents=user_turn,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TRISENSE,
                    temperature=0.7,
                    max_output_tokens=max_tokens,
                ),
            )
            text = _extract_response_text(response)
            return (text or "").strip()
        except Exception as e:
            logger.exception("Gemini error: %s", e)
            return f"TriSense: I had a technical issue. Please try again. ({name}, I am here.)"

    def reply_with_image_jpeg(
        self,
        jpeg_bytes: bytes,
        prompt: str,
        child_name: str,
        max_tokens: int = 400,
    ) -> str:
        """
        Răspuns multimodal cu o captură de cameră (JPEG).
        Folosește același model ca `reply` (ex. gemini-1.5-flash pe Vertex).
        """
        if not self._client or not jpeg_bytes or len(jpeg_bytes) < 100:
            return self.reply((prompt or "").strip(), child_name, max_tokens=max_tokens)
        name = child_name.strip() if child_name else "friend"
        task = (
            f"The child name is: {name}. Address them by name sometimes.\n\n"
            f"Task:\n{(prompt or '').strip()}"
        )
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self._model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=task),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TRISENSE,
                    temperature=0.7,
                    max_output_tokens=max_tokens,
                ),
            )
            return (_extract_response_text(response) or "").strip()
        except Exception as e:
            logger.exception("Gemini vision error: %s", e)
            return f"TriSense: I could not see well enough. ({name}, try again?)"

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe WAV (PCM 16-bit mono, e.g. 16 kHz) to text via Gemini multimodal."""
        if not self._client or not wav_bytes:
            return ""
        # Default: same model as reply; override with GEMINI_TRANSCRIBE_MODEL in .env.
        model = (os.getenv("GEMINI_TRANSCRIBE_MODEL") or "").strip() or GEMINI_MODEL
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(
                                data=wav_bytes,
                                mime_type="audio/wav",
                            ),
                            types.Part.from_text(
                                text=(
                                    "Transcribe exactly what you hear in English. "
                                    "Return only spoken text, no quotes, no explanations. "
                                    "If the speaker says a single word, return that word only."
                                )
                            ),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=1024,
                ),
            )
            text = _extract_response_text(response).strip()
            if not text:
                _log_empty_transcribe_response(response)
            return text
        except Exception as e:
            code = getattr(e, "status_code", None)
            err_s = str(e)
            is_429 = code == 429 or "RESOURCE_EXHAUSTED" in err_s
            # 503: uneori code lipseste sau e alt tip — prindem din mesaj
            is_503 = (
                code == 503
                or str(code) == "503"
                or (
                    "503" in err_s
                    and (
                        "UNAVAILABLE" in err_s
                        or "high demand" in err_s.lower()
                        or "Service Unavailable" in err_s
                    )
                )
            )
            if is_429:
                logger.warning(
                    "Gemini transcribe: quota / prea multe cereri (429). Asteapta 1–2 minute intre teste; "
                    "audio consuma multi tokeni. Verifica limitele: https://ai.google.dev/gemini-api/docs/rate-limits "
                    "(AI Studio → Usage). Optional: GEMINI_TRANSCRIBE_MODEL=alt model."
                )
            elif is_503:
                logger.warning(
                    "Gemini transcribe: server ocupat (503). Cerere mare pe model — incearca peste 1–2 minute "
                    "sau pune in .env GEMINI_TRANSCRIBE_MODEL=gemini-2.0-flash (sau alt model disponibil)."
                )
            else:
                logger.exception("Gemini transcribe error: %s", e)
            return ""

    def synthesize_tts_pcm(self, text: str, voice: Optional[str] = None) -> tuple[bytes, int]:
        """Generate TTS on PC and return mono int16 PCM + sample rate."""
        if not self._client or not text.strip():
            return b"", 24000
        model = (os.getenv("GEMINI_TTS_MODEL") or GEMINI_TTS_MODEL).strip() or GEMINI_TTS_MODEL
        voice_name = (voice or os.getenv("TRISENSE_TTS_VOICE") or TRISENSE_TTS_VOICE).strip() or "Vindemiatrix"
        base_text = (text or "").strip()
        max_tokens_cfg = max(
            512,
            min(
                32768,
                int((os.getenv("GEMINI_TTS_MAX_OUTPUT_TOKENS") or "8192").strip() or "8192"),
            ),
        )
        try:
            from google.genai import types

            def _request_tts(prompt_text: str, temp: float, out_tok: int):
                return self._client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])],
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_name,
                                )
                            )
                        ),
                        temperature=temp,
                        max_output_tokens=out_tok,
                    ),
                )

            prompt = base_text
            response = _request_tts(prompt, 0.25, max_tokens_cfg)
            pcm, sr = _extract_tts_pcm_from_response(response)
            fr = _tts_finish_reason(response)
            if pcm:
                dur_s = len(pcm) / (2 * max(1, sr))
                logger.info(
                    "Gemini TTS: PCM %d B mono @ %d Hz (~%.2f s), finish_reason=%s",
                    len(pcm),
                    sr,
                    dur_s,
                    fr,
                )
                if dur_s < 0.18:
                    logger.warning(
                        "Gemini TTS: audio foarte scurt (sub ~180 ms). Pe difuzor pare „mut” chiar daca "
                        "TCP reușește. Cauze uzuale: truncare API, MAX_TOKENS audio, sau model ocupat — "
                        "verifica finish_reason si GEMINI_TTS_MAX_OUTPUT_TOKENS."
                    )
            else:
                logger.warning("Gemini TTS: niciun PCM in raspuns (finish_reason=%s).", fr)
            return pcm, sr
        except Exception as e:
            logger.warning("Gemini TTS error: %s", e)
            return b"", 24000


def _extract_response_text(response: object) -> str:
    """Extrage textul din GenerateContentResponse (inclusiv multimodal: candidates[].content.parts)."""
    try:
        t = getattr(response, "text", None)
        if t:
            return str(t)
    except Exception:
        pass
    try:
        cands = getattr(response, "candidates", None) or []
        if cands:
            c0 = cands[0]
            content = getattr(c0, "content", None)
            if content is not None:
                parts = getattr(content, "parts", None) or []
                chunks = []
                for p in parts:
                    pt = getattr(p, "text", None)
                    if pt:
                        chunks.append(str(pt))
                if chunks:
                    return "".join(chunks)
    except Exception:
        pass
    parts = getattr(response, "parts", None) or []
    if parts:
        chunks = []
        for p in parts:
            if hasattr(p, "text") and p.text:
                chunks.append(p.text)
        return "".join(chunks)
    return ""


def _log_empty_transcribe_response(response: object) -> None:
    """Ajuta la diagnostic cand STT returneaza gol dar HTTP e 200."""
    try:
        cands = getattr(response, "candidates", None) or []
        if cands:
            fr = getattr(cands[0], "finish_reason", None)
            if fr is not None:
                logger.warning(
                    "Gemini transcribe: text gol (finish_reason=%s). "
                    "Audio prea silent / microfon I2S pe ESP sau incearca GEMINI_TRANSCRIBE_MODEL=gemini-2.0-flash.",
                    fr,
                )
                return
    except Exception:
        pass
    logger.warning(
        "Gemini transcribe: text gol — probabil audio silent sau fara vorbire clara (nu e legat de difuzor MQTT)."
    )


def _tts_finish_reason(response: object) -> str:
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return "no_candidates"
        fr = getattr(cands[0], "finish_reason", None)
        return str(fr) if fr is not None else "unknown"
    except Exception:
        return "?"


def _extract_tts_pcm_from_response(response: object) -> tuple[bytes, int]:
    cands = getattr(response, "candidates", None) or []
    if not cands:
        return b"", 24000
    content = getattr(cands[0], "content", None)
    if content is None:
        return b"", 24000
    parts = getattr(content, "parts", None) or []
    for p in parts:
        inline = getattr(p, "inline_data", None) or getattr(p, "inlineData", None)
        if not inline:
            continue
        data = getattr(inline, "data", None)
        if not data:
            continue
        mime = str(getattr(inline, "mime_type", None) or getattr(inline, "mimeType", "") or "")
        raw = b""
        if isinstance(data, (bytes, bytearray, memoryview)):
            raw = bytes(data)
        elif isinstance(data, str):
            try:
                raw = base64.b64decode(data)
            except Exception:
                raw = b""
        if not raw or len(raw) < 200:
            continue
        if raw[:4] != b"RIFF":
            try:
                head = raw[:64].decode("ascii")
                if all(c.isalnum() or c in "+/=\n\r" for c in head):
                    decoded = base64.b64decode(raw)
                    if decoded and len(decoded) > 200:
                        raw = decoded
            except Exception:
                pass
        if raw[:4] == b"RIFF":
            pcm, sr = _extract_wav_pcm_mono(raw)
            if pcm:
                return pcm, sr
        sr = _sample_rate_from_mime(mime)
        return raw if len(raw) % 2 == 0 else raw[:-1], sr
    return b"", 24000


def _sample_rate_from_mime(mime: str) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    if not m:
        return 24000
    try:
        sr = int(m.group(1))
        if 8000 <= sr <= 48000:
            return sr
    except Exception:
        pass
    return 24000


def _extract_wav_pcm_mono(wav_bytes: bytes) -> tuple[bytes, int]:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            ch = wf.getnchannels()
            sr = wf.getframerate()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if sw != 2:
            return b"", 24000
        pcm = _stereo_to_mono(frames) if ch == 2 else frames
        if sr < 8000 or sr > 48000:
            sr = 24000
        return pcm, sr
    except Exception:
        return b"", 24000


def _stereo_to_mono(pcm: bytes) -> bytes:
    if len(pcm) % 4 != 0:
        return pcm if len(pcm) % 2 == 0 else pcm[:-1]
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm), 4):
        l = struct.unpack_from("<h", pcm, i)[0]
        r = struct.unpack_from("<h", pcm, i + 2)[0]
        struct.pack_into("<h", out, i // 2, (l + r) // 2)
    return bytes(out)
