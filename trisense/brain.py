# -*- coding: utf-8 -*-
"""
Orchestrator principal: memorie, stari, MQTT, AI, TTS, metrici.
"""

from __future__ import annotations

import logging
import os
import queue
import random
import time
import unicodedata
from typing import Any, Optional

from trisense.ai_client import TriSenseAI
from trisense.audio_push import send_pcm_to_esp
from trisense.cloud_tts import (
    GCP_TTS_SAMPLE_RATE_HZ,
    cloud_tts_ready,
    synthesize_linear16_pcm,
)
from trisense.config import (
    ESP_AUDIO_TCP_PORT,
    ESP_SPEAK_MAX_CHARS,
    TOPIC_ROBOT_CONTROL,
    TRISENSE_TTS_OVER_TCP,
    vision_id_to_action_map,
)
from trisense.memory_store import MemoryStore
from trisense.metrics_logger import MetricsLogger
from trisense.mqtt_layer import MqttBrainClient
from trisense.states import RobotState
from trisense.tts_engine import TTSEngine

logger = logging.getLogger(__name__)


def _voice_keyword_compact(raw: str) -> str:
    """Litera mica, fara diacritice, litere+digit concatenat (ex. 'foot' + 'ball' -> ...football...)."""
    if not raw:
        return ""
    n = unicodedata.normalize("NFD", raw.strip())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return "".join(ch.lower() for ch in n if ch.isalnum())

class TriSenseBrain:
    """
    Creier TriSense 3.0:
    - Memorie JSON (nume copil)
    - Stari: START -> SALUT (ID1) -> SELECTIE_JOC -> ACTIVITATE (ID2+) -> FINAL
    - MQTT: asculta vision/tags, comenzi pe robot/control (nume topic neschimbat)
    - HuskyLens ID 1=fata (salut flow); optional VISION_ID_TO_ACTION mapeaza alte clase la miscare hub fara LEGO;
      ID-uri ne-mapate dar >= 2 comportament LEGO clasic ramane.
    """

    # Act. 7 — pasii hardcodati pentru demo (action, voce anunt, cmd_hub)
    _PATTERN_STEPS: list[tuple[str, str, int]] = [
        ("left_arm",  "Left arm up!",  3),
        ("right_arm", "Right arm up!", 4),
        ("breathe_in", "Breathe in!",  5),
    ]

    def __init__(self) -> None:
        self.memory = MemoryStore()
        self.ai = TriSenseAI()
        self.tts = TTSEngine()
        self.metrics = MetricsLogger()
        self.mqtt = MqttBrainClient()
        self.state = RobotState.START
        self._child_name: str = ""
        self._challenge_start: Optional[float] = None
        self._expecting_lego: bool = False
        self._pc_tts_hint_logged: bool = False
        self._last_esp_ip: Optional[str] = None
        self._vision_id_to_motion = vision_id_to_action_map()
        # Act. 6
        self._current_emotion: Optional[str] = None
        # Act. 7
        self._pattern_sequence: list[str] = []
        self._pattern_step: int = 0

    def _synthesize_tcp_pcm(self, msg: str) -> tuple[bytes, int]:
        """PCM mono pentru TCP către ESP: după env TRISENSE_TTS_PCM_SOURCE (Cloud vs Gemini)."""
        raw = (os.environ.get("TRISENSE_TTS_PCM_SOURCE") or "gemini").strip().lower()
        google_modes = ("google_cloud", "cloud_tts", "cloud", "gcp")
        allow_gem = (os.environ.get("TRISENSE_TTS_PCM_ALLOW_GEMINI_FALLBACK") or "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        pcm: bytes = b""
        sample_rate = 24000

        if raw in google_modes:
            if cloud_tts_ready():
                pcm, sample_rate = synthesize_linear16_pcm(msg)
                if pcm:
                    return pcm, sample_rate
                logger.warning("Cloud Text-to-Speech: PCM gol sau eroare.")
            else:
                logger.warning(
                    "TRISENSE_TTS_PCM_SOURCE=%s dar Cloud TTS indisponibil (bibliotecă sau cheie_google.json).",
                    raw,
                )
            if not allow_gem:
                logger.warning(
                    "Fallback Gemini TTS dezactivat (implicit cu google_cloud). "
                    "Pune TRISENSE_TTS_PCM_ALLOW_GEMINI_FALLBACK=1 ca rezervă."
                )
                return b"", GCP_TTS_SAMPLE_RATE_HZ

        if self.ai.available:
            return self.ai.synthesize_tts_pcm(msg)
        return b"", sample_rate

    def _publish(self, cmd: dict[str, Any]) -> bool:
        ok = self.mqtt.publish_control(cmd)
        if not ok:
            logger.debug("Comanda nu a putut fi trimisa (MQTT offline): %s", cmd)
        return ok

    def _announce(
        self,
        text: str,
        *,
        robot_only: bool = False,
        retain_speak_topic: bool = False,
        esp_ip: Optional[str] = None,
        laptop_speaker: Optional[bool] = None,
        mqtt_speak_publish: bool = True,
        wait_for_playback: bool = False,
    ) -> bool:
        """TTS pe PC + PCM către ESP (TCP) sau fallback MQTT „speak”.

        robot_only=True: apel din thread-ul serverului TCP voce; evită pyttsx3 pe laptop.

        laptop_speaker=None: respectă TRISENSE_TTS_PC din .env; False=nu prinde difuzorul laptopului.

        mqtt_speak_publish=False: nu publică `{"speak":...}` (ex. PAS4 fără Gemini pe ESP).

        TRISENSE_TTS_PC=1: voce și pe laptop (dacă laptop_speaker nu e False).

        TRISENSE_TTS_PCM_SOURCE=google_cloud: Neural2 (Vertex / GCP, același proiect ca trial).
        TRISENSE_TTS_PCM_ALLOW_GEMINI_FALLBACK=1: dacă Cloud TTS eșuează, folosește și Gemini TTS.

        Citire env la fiecare apel (load_dotenv).
        """
        v = (os.environ.get("TRISENSE_TTS_PC") or "0").strip().lower()
        tts_pc_env = v in ("1", "true", "yes")
        if laptop_speaker is None:
            tts_pc = tts_pc_env
        else:
            tts_pc = bool(laptop_speaker)
        if not robot_only and tts_pc:
            self.tts.speak(text)
        msg = (text or "").strip()
        if len(msg) > ESP_SPEAK_MAX_CHARS:
            msg = msg[: max(0, ESP_SPEAK_MAX_CHARS - 3)] + "..."
        tcp_attempted = False
        if msg and TRISENSE_TTS_OVER_TCP:
            target_ip = (esp_ip or self._last_esp_ip or "").strip()
            if target_ip:
                tcp_attempted = True
                pcm_source = (os.environ.get("TRISENSE_TTS_PCM_SOURCE") or "").strip().lower()
                cloud_first = pcm_source in ("google_cloud", "cloud_tts", "cloud", "gcp")
                pcm: bytes = b""
                sample_rate: int = 24000
                if cloud_first:
                    pcm, sample_rate = self._synthesize_tcp_pcm(msg)
                    if pcm:
                        logger.info(
                            "Cloud TTS: PCM %d B @ %d Hz (~%.2f s).",
                            len(pcm),
                            sample_rate,
                            len(pcm) / (2 * max(1, sample_rate)),
                        )
                if not pcm and self.tts.available:
                    pcm, sample_rate = self.tts.synthesize_pcm(msg)
                    if pcm:
                        logger.info(
                            "TTS local pyttsx3 (fallback): PCM %d B @ %d Hz (~%.2f s).",
                            len(pcm),
                            sample_rate,
                            len(pcm) / (2 * max(1, sample_rate)),
                        )
                if not pcm and not cloud_first:
                    pcm, sample_rate = self._synthesize_tcp_pcm(msg)
                if pcm:
                    dur_ms = int(1000 * len(pcm) / (2 * max(1, sample_rate)))
                    ok_audio = send_pcm_to_esp(target_ip, ESP_AUDIO_TCP_PORT, pcm, sample_rate)
                    if ok_audio:
                        min_ms = int((os.environ.get("TTS_PCM_MIN_MS") or "180").strip() or "180")
                        logger.info(
                            "Audio TCP TTS trimis la %s:%s (~%d ms PCM mono @ %d Hz).",
                            target_ip,
                            ESP_AUDIO_TCP_PORT,
                            dur_ms,
                            sample_rate,
                        )
                        if wait_for_playback and dur_ms > 0:
                            wait_s = dur_ms / 1000.0 + 0.6
                            logger.info("Astept %.1fs ca ESP sa termine redarea PCM.", wait_s)
                            time.sleep(wait_s)
                        if dur_ms >= min_ms:
                            return True
                        logger.warning(
                            "PCM TTS sub pragul %d ms — pe difuzor e aproape inaudibil; "
                            "trimit acelasi text si pe MQTT speak (TTS pe ESP).",
                            min_ms,
                        )
                        if not mqtt_speak_publish:
                            return False
                    else:
                        logger.warning("Audio TCP esuat; incerc MQTT speak.")
                        if not mqtt_speak_publish:
                            return False
            else:
                logger.info("Audio TCP preferred, but robot IP is not known yet; skipping local ESP TTS fallback.")
                return False
        if msg and mqtt_speak_publish:
            if tcp_attempted:
                logger.info("Fallback MQTT speak dupa esec/PCM scurt pe Audio TCP.")
            ok = self._publish({"speak": msg})
            if not ok:
                time.sleep(1.5)
                ok = self._publish({"speak": msg})
            if ok:
                preview = msg if len(msg) <= 100 else msg[:97] + "..."
                logger.info("MQTT speak trimis spre robot: %s", preview)
            else:
                logger.warning(
                    "MQTT indisponibil — textul nu a ajuns la robot. Reporne dupa ce brokerul e online."
                )
            if retain_speak_topic and msg:
                self.mqtt.publish_speak_retained(msg)
            if (
                not robot_only
                and mqtt_speak_publish
                and not tts_pc
                and not self._pc_tts_hint_logged
            ):
                self._pc_tts_hint_logged = True
                logger.info(
                    "Pe laptop nu se aude (TRISENSE_TTS_PC=0); vocea e pe difuzor ESP. "
                    "Pune TRISENSE_TTS_PC=1 in .env daca vrei si audio pe PC."
                )
            return ok
        if msg and not mqtt_speak_publish:
            return False
        return True

    def _detect_motor_action(self, transcript: str) -> Optional[str]:
        """Mapeaza cuvinte din transcript la actiuni trimise MQTT (ESP -> hub LEGO)."""
        if not transcript:
            return None
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in transcript)
        words = set(normalized.split())

        if {"dance", "danseaza", "danseaz\u0103", "danseaz", "danseze", "dancing"} & words:
            return "dance"

        repose_kw = {"repose", "home", "reset", "reposition"}
        ro_repose = {"reposter", "reposeste"}
        if repose_kw & words or ro_repose & words:
            return "repose"

        bl = normalized.replace("_", " ")
        bl_ascii = (
            bl.replace("â", "a")
            .replace("ă", "a")
            .replace("î", "i")
            .replace("ș", "s")
            .replace("ț", "t")
        )
        if (
            "left arm" in bl
            or "left hand" in bl
            or "mana stanga" in bl_ascii
            or "mina stanga" in bl_ascii
        ):
            return "left_arm"
        if (
            "right arm" in bl
            or "right hand" in bl
            or "mana dreapta" in bl_ascii
            or "mina dreapta" in bl_ascii
        ):
            return "right_arm"

        if (
            "breathing exercise" in bl
            or "guided breathing" in bl
            or ("respiratie" in bl_ascii and "ghidata" in bl_ascii)
            or ("exercitiu" in bl_ascii and "respiratie" in bl_ascii)

        ):
            return "breathing_show"

        if "breathe" in words or "breathing" in words:
            if "in" in words:
                return "breathe_in"
            if "out" in words:
                return "breathe_out"

        ro_in = {"inspira", "inspir\u0103", "inspire", "inhalation"}
        ro_out = {"expira", "expir\u0103", "exhalation"}
        if ro_in & words:
            return "breathe_in"
        if ro_out & words:
            return "breathe_out"

        tl = (transcript or "").strip().lower()
        ro_bl = bl_ascii

        if (
            ("turn left" in bl or "rotate left" in bl or "pivot left" in bl)
            and "left arm" not in bl
        ):
            return "turn_left"
        if (
            ("turn right" in bl or "rotate right" in bl or "pivot right" in bl)
            and "right arm" not in bl
        ):
            return "turn_right"
        if (
            ("roteste" in tl or "intoarce" in tl)
            and ("stanga" in ro_bl)
            and ("mana stanga" not in ro_bl and "mina stanga" not in ro_bl)
        ):
            return "turn_left"
        if (
            ("roteste" in tl or "intoarce" in tl)
            and ("dreapta" in ro_bl)
            and ("mana dreapta" not in ro_bl)
        ):
            return "turn_right"

        if (
            "go forward" in bl
            or "drive forward" in bl
            or "move forward" in bl
            or "merge inainte" in ro_bl
            or "mergi inainte" in ro_bl
            or ({"forward"} & words and ({"go", "drive", "move", "step", "merge", "mergi"} & words))
        ):
            return "forward"
        if (
            "go back" in bl
            or "drive back" in bl
            or "move back" in bl
            or "merge inapoi" in ro_bl
            or "mergi inapoi" in ro_bl
            or (
                {"backward", "backwards"} & words
                and ({"go", "drive", "move", "step", "merge", "mergi"} & words)
            )
        ):
            return "backward"

        cq = _voice_keyword_compact(transcript)
        if cq and any(
            tag in cq
            for tag in (
                "football",
                "futbol",
                "soccer",
                "fussball",
                "fotbal",
                "futbal",
            )
        ):
            return "right_arm"
        if cq and any(
            tag in cq
            for tag in (
                "basketball",
                "handball",
                "rugby",
                "rugbi",
                "handbal",
                "baschet",
            )
        ):
            return "left_arm"

        # Act. 6 — Guess the Emotion
        if "guess" in words and (
            "emotion" in words or "emotia" in bl_ascii or "emotie" in bl_ascii or "feeling" in words
        ):
            return "guess_emotion"
        if cq and ("guessemotion" in cq or "emotionguess" in cq or "ghicesteemotia" in cq):
            return "guess_emotion"

        # Act. 7 — Follow the Pattern
        if ("follow" in words and "pattern" in words) or (
            "urmeaza" in bl_ascii and ("tiparul" in bl_ascii or "modelul" in bl_ascii or "pattern" in bl_ascii)
        ):
            return "follow_pattern"
        if cq and ("followpattern" in cq or "urmeazatiparul" in cq or "urmeazamodelul" in cq):
            return "follow_pattern"

        return None

    def handle_voice_transcript(
        self,
        transcript: str,
        *,
        robot_only: bool = True,
        esp_ip: Optional[str] = None,
    ) -> None:
        """Reply to text obtained from ESP microphone (STT on PC)."""
        t = (transcript or "").strip()
        if not t:
            return
        if len(t) < 2:
            logger.info("Voice: ignored transcript (too short).")
            return
        if esp_ip:
            self._last_esp_ip = esp_ip
        name = self._child_name or self.memory.get_child_name() or "friend"

        # Raspuns activ: Act. 6 asteapta ghicire emotie
        if self.state == RobotState.GUESS_EMOTION:
            self._validate_emotion_guess(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        # Raspuns activ: Act. 7 asteapta pas curent din pattern
        if self.state == RobotState.FOLLOW_PATTERN:
            self._validate_pattern_step(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        action = self._detect_motor_action(t)
        if action:
            if not self.mqtt.wait_connected(timeout=5.0):
                logger.warning(
                    "MQTT neconectat (timeout 5s) — gestul %r ar putea să nu ajungă la ESP.",
                    action,
                )
            voice = {
                "dance": f"Let's dance, {name}!",
                "repose": f"Relaxing pose, {name}.",
                "left_arm": f"Left arm up, {name}!",
                "right_arm": f"Right arm up, {name}!",
                "breathe_in": f"Breathe in, {name}.",
                "breathe_out": f"Breathe out, {name}.",
                "breathing_show": f"Follow my arms, lights and breathing sounds — two breaths, {name}.",
                "forward": f"Driving forward, {name}!",
                "backward": f"Backing up.",
                "turn_left": f"Turning left.",
                "turn_right": f"Turning right.",
                "guess_emotion": f"Let's play Guess the Emotion, {name}!",
                "follow_pattern": f"Let's play Follow the Pattern, {name}!",
            }.get(action, f"Okay, {name}!")
            # Act. 6 — Guess the Emotion
            if action == "guess_emotion":
                self._start_guess_emotion(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            # Act. 7 — Follow the Pattern
            if action == "follow_pattern":
                self._start_follow_pattern(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "breathing_show":
                # PAS4: ghid vocal prin Audio TCP din PC (pyttsx3/Vertex → PCM), fără laptop,
                #       fără {"speak"} pe MQTT → ESP nu cheamă Gemini (fără cheie în secrets.py).
                vtrim = (voice or "").strip()
                if len(vtrim) > ESP_SPEAK_MAX_CHARS:
                    vtrim = vtrim[: max(0, ESP_SPEAK_MAX_CHARS - 3)] + "..."
                intro_ok = self._announce(
                    vtrim,
                    robot_only=robot_only,
                    esp_ip=esp_ip,
                    laptop_speaker=False,
                    mqtt_speak_publish=False,
                    wait_for_playback=True,
                )
                if not intro_ok:
                    logger.warning(
                        "PAS4: fraza ghidată nu ajunge la difuzor (TRISENSE_TTS_OVER_TCP=1, pyttsx3 PCM, "
                        "IP ESP din flux vizual/server). Încerca din nou după reconectare."
                    )
                sent = self._publish({"action": "breathing_show"})
                if not sent:
                    logger.warning(
                        "Motor action %r nu s-a putut publica pe %s (broker offline?).",
                        action,
                        TOPIC_ROBOT_CONTROL,
                    )
                else:
                    logger.info(
                        "breathing_show -> MQTT action-only=%s după Audio TCP intro=%s",
                        sent,
                        intro_ok,
                    )
                return
            sent = self._publish({"action": action})
            if not sent:
                logger.warning(
                    "Motor action %r nu s-a putut publica pe %s (broker offline?).",
                    action,
                    TOPIC_ROBOT_CONTROL,
                )
            else:
                logger.info(
                    "Motor action %r -> MQTT %s trimis=%s",
                    action,
                    TOPIC_ROBOT_CONTROL,
                    sent,
                )
            self._announce(voice, robot_only=robot_only, esp_ip=esp_ip)
            return

        prompt = (
            f"The child said this through the microphone (transcript): {t}. "
            "Reply very briefly, friendly, in English, as TriSense."
        )
        text = self.ai.reply(prompt, name) if self.ai.available else f"I heard: {t}"
        text = (text or "").strip().strip("\"'")
        if text.count("\"") % 2 == 1:
            text = text.replace("\"", "")
        if len(text) < 8:
            text = f"I heard you, {name}."
        logger.info("Voce TCP raspuns TriSense: %s", (text or "")[:500])
        delivered = self._announce(text, robot_only=robot_only, esp_ip=esp_ip)
        if delivered:
            logger.info(
                "Voce TCP: lant PC complet (transcriere -> LLM -> TTS livrat: TCP si/sau MQTT speak). "
                "Daca PCM TTS pe PC a fost foarte scurt, s-a trimis automat si MQTT pentru TTS pe ESP."
            )
        else:
            logger.warning(
                "Voce TCP: raspunsul LLM exista, dar livrarea audio/MQTT catre robot a esuat "
                "(IP lipsa, TCP/MQTT offline sau PCM lipsa)."
            )

    def _say(self, text: str, *, robot_only: bool, esp_ip: Optional[str], wait: bool = True) -> None:
        """Shorthand: PCM via TCP catre difuzor robot, fara laptop, fara MQTT speak."""
        self._announce(
            text,
            robot_only=robot_only,
            esp_ip=esp_ip,
            laptop_speaker=False,
            mqtt_speak_publish=False,
            wait_for_playback=wait,
        )

    # ------------------------------------------------------------------
    # Act. 6 — Guess the Emotion
    # ------------------------------------------------------------------

    def _start_guess_emotion(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """Robot alege o emotie random, o arata cu gesturi, cere copilului sa ghiceasca."""
        emotions = ["happy", "sad", "surprised"]
        self._current_emotion = random.choice(emotions)
        emotion_action = {
            "happy":     "emotion_happy",
            "sad":       "emotion_sad",
            "surprised": "emotion_surprised",
        }[self._current_emotion]
        logger.info("Act.6 [1/4]: emotie aleasa = %s", self._current_emotion)

        intro = f"Watch carefully, {name}!"
        logger.info("Act.6 [2/4]: redau intro pe robot...")
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip)
        time.sleep(0.5)

        logger.info("Act.6 [3/4]: trimit cmd %s la Hub si astept rutina...", emotion_action)
        self._publish({"action": emotion_action})
        emotion_dur = {"emotion_happy": 14.0, "emotion_sad": 8.0, "emotion_surprised": 7.0}
        time.sleep(emotion_dur.get(emotion_action, 10.0))

        question = f"What emotion was I showing, {name}? Happy, sad, or surprised?"
        logger.info("Act.6 [4/4]: redau intrebarea pe robot...")
        self._say(question, robot_only=robot_only, esp_ip=esp_ip)
        logger.info("Act.6: gata, astept raspunsul copilului in proxima tura.")
        self.state = RobotState.GUESS_EMOTION
        logger.info("Act.6 GUESS_EMOTION pornit; emotie aleasa: %s", self._current_emotion)

    def _validate_emotion_guess(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        """Valideaza raspunsul copilului pentru Act. 6."""
        bl = transcript.lower()
        detected: Optional[str] = None
        if any(kw in bl for kw in ("happy", "fericit", "bucuros", "vesel", "fericita")):
            detected = "happy"
        elif any(kw in bl for kw in ("sad", "trist", "suparat", "tristete", "tristă")):
            detected = "sad"
        elif any(kw in bl for kw in ("surprised", "uimit", "uimita", "mirat", "surprins")):
            detected = "surprised"

        expected = self._current_emotion or "happy"
        if detected == expected:
            response = f"Amazing, {name}! Correct — I was {expected}!"
            self._say(response, robot_only=robot_only, esp_ip=esp_ip)
            time.sleep(0.5)
            self._publish({"action": "dance"})
            self.state = RobotState.SELECTIE_JOC
            self._current_emotion = None
            logger.info("Act.6 terminat corect; emotie=%s", expected)
            return
        elif detected:
            response = (
                f"Not quite, {name}. I was actually feeling {expected}. "
                f"But great try — you said {detected}!"
            )
        else:
            response = f"I wasn't sure I heard you. I was feeling {expected}! Try again next time!"

        self._say(response, robot_only=robot_only, esp_ip=esp_ip)
        self.state = RobotState.SELECTIE_JOC
        self._current_emotion = None
        logger.info("Act.6 terminat; detectat=%s, expected=%s", detected, expected)

    # ------------------------------------------------------------------
    # Act. 7 — Follow the Pattern
    # ------------------------------------------------------------------

    def _start_follow_pattern(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """Robot arata secventa de 3 miscari, cere copilului sa o repete pas cu pas."""
        steps = self._PATTERN_STEPS
        self._pattern_sequence = [s[0] for s in steps]
        self._pattern_step = 0

        intro = f"Watch my pattern, {name}! Three moves!"
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip)
        time.sleep(0.5)

        for i, (action, label, _cmd) in enumerate(steps):
            phrase = f"Step {i + 1}: {label}"
            self._say(phrase, robot_only=robot_only, esp_ip=esp_ip)
            time.sleep(0.5)
            self._publish({"action": action})
            time.sleep(3.5)

        ask = f"Your turn! Step 1?"
        self._say(ask, robot_only=robot_only, esp_ip=esp_ip)
        self.state = RobotState.FOLLOW_PATTERN
        logger.info("Act.7 FOLLOW_PATTERN pornit; secventa=%s", self._pattern_sequence)

    def _validate_pattern_step(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        """Valideaza un pas din secventa Act. 7."""
        action = self._detect_motor_action(transcript)
        total = len(self._pattern_sequence)
        expected = self._pattern_sequence[self._pattern_step] if self._pattern_step < total else None

        if action and action == expected:
            self._publish({"action": action})
            time.sleep(2.5)
            self._pattern_step += 1
            if self._pattern_step >= total:
                response = f"Perfect, {name}! Amazing!"
                self._say(response, robot_only=robot_only, esp_ip=esp_ip)
                time.sleep(0.5)
                self._publish({"action": "dance"})
                self.state = RobotState.SELECTIE_JOC
                self._pattern_sequence = []
                self._pattern_step = 0
            else:
                step_label = self._PATTERN_STEPS[self._pattern_step][1]
                response = f"Correct! Step {self._pattern_step + 1}: {step_label}?"
                self._say(response, robot_only=robot_only, esp_ip=esp_ip)
        else:
            if expected:
                exp_label = next(
                    (s[1] for s in self._PATTERN_STEPS if s[0] == expected), expected.replace("_", " ")
                )
                if action:
                    response = f"Not quite! Step {self._pattern_step + 1} is {exp_label}. Try again!"
                else:
                    response = f"I didn't catch that. Step {self._pattern_step + 1} is {exp_label}?"
            else:
                response = f"Something went wrong. Let's start over!"
                self.state = RobotState.SELECTIE_JOC
                self._pattern_step = 0
                self._pattern_sequence = []
            self._say(response, robot_only=robot_only, esp_ip=esp_ip)
        logger.info("Act.7 pas=%d/%d; detectat=%s, expected=%s", self._pattern_step, total, action, expected)

    def _run_primul_salut(self) -> None:
        """No name in memory: ask child name and save JSON."""
        msg = (
            "This is your first meeting with TriSense. Tell the child you are happy to meet them. "
            "Ask for their name briefly in one friendly sentence."
        )
        if self.ai.available:
            text = self.ai.reply(msg, "friend")
        else:
            text = "Hi! I am TriSense. What is your name?"
        self._announce(text)
        try:
            raw = input("Enter child name (then Enter): ").strip()
        except EOFError:
            raw = "Child"
        if not raw:
            raw = "Child"
        self.memory.set_child_name(raw)
        self._child_name = raw
        logger.info("Name saved in memorie_copil.json: %s", raw)
        self._publish({"event": "child_registered", "nume": raw})

    def _greet_salut_id1(self) -> None:
        """ID 1 interpreted as face / greeting."""
        name = self._child_name or "friend"
        prompt = (
            f"Child {name} has just been recognized (face/greeting ID signal). "
            "Reply very briefly, encouraging, in English."
        )
        text = self.ai.reply(prompt, name) if self.ai.available else f"Hi, {name}! Great to see you!"
        self._announce(text)
        self.metrics.log(
            nume_copil=name,
            id_vazut=1,
            timp_reactie_ms=None,
            stare="SALUT",
            extra={"tip": "fata"},
        )

    def _on_lego_id(self, object_class_id: int, reaction_ms: Optional[float]) -> None:
        """ID 2+ = LEGO object class learned in HuskyLens Object Classification mode."""
        name = self._child_name or "friend"
        prompt = (
            f"Child {name} showed a LEGO piece/build recognized by camera (class ID {object_class_id}). "
            "Praise them in one short sentence and propose a tiny play task."
        )
        text = self.ai.reply(prompt, name) if self.ai.available else f"Great, {name}, I recognized your build!"
        self._announce(text)
        self.metrics.log(
            nume_copil=name,
            id_vazut=object_class_id,
            timp_reactie_ms=reaction_ms,
            stare="ACTIVITATE",
            extra={"tip": "lego_class", "id": object_class_id},
        )
        self._publish({"event": "lego_seen", "id": object_class_id})
        self.state = RobotState.FINAL

    def _final_recompensa(self) -> None:
        name = self._child_name or "friend"
        text = (
            self.ai.reply(
                f"The round ended. Encourage {name} for participating, very briefly.",
                name,
            )
            if self.ai.available
            else f"Great job, {name}! See you in the next play round!"
        )
        self._announce(text)
        self.metrics.log(
            nume_copil=name,
            id_vazut=0,
            timp_reactie_ms=None,
            stare="FINAL",
            extra={},
        )
        self.state = RobotState.SELECTIE_JOC
        self._expecting_lego = False
        self._challenge_start = None

    def _handle_vision(self, data: dict[str, Any]) -> None:
        """ID din JSON MQTT = clasa HuskyLens (Object Classification). Optional: VISION_ID_TO_ACTION."""
        vision_id = int(data["id"])
        recv = data.get("_received_at", time.time())

        act = self._vision_id_to_motion.get(str(vision_id))
        if act:
            logger.info(
                "Vision: ID=%s mapped la miscare hub %r (robot/control)",
                vision_id,
                act,
            )
            self._publish({"action": act})
            return

        if self.state == RobotState.START:
            self.state = RobotState.SELECTIE_JOC

        if vision_id == 1:
            self.state = RobotState.SALUT
            self._greet_salut_id1()
            self._publish({"cmd": "state", "value": "SALUT", "id": 1})
            self.state = RobotState.SELECTIE_JOC
            self._expecting_lego = True
            self._challenge_start = time.time()
            self._publish({"cmd": "expect", "target": "lego_object", "min_id": 2})
            return

        if vision_id >= 2:
            reaction_ms = None
            if self._challenge_start is not None:
                reaction_ms = (recv - self._challenge_start) * 1000.0
            self.state = RobotState.ACTIVITATE
            self._on_lego_id(vision_id, reaction_ms)
            self._publish({"cmd": "state", "value": "ACTIVITATE", "id": vision_id})
            time.sleep(0.5)
            self._final_recompensa()

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        logger.info("Starting TriSense Brain 3.0 — MQTT %s / %s", "vision/tags", TOPIC_ROBOT_CONTROL)

        self.mqtt.connect_background()
        if not self.mqtt.wait_connected(timeout=20.0):
            logger.warning("MQTT not connected yet; continuing anyway (background reconnect).")

        name = self.memory.get_child_name()
        if not name:
            self._run_primul_salut()
        else:
            self._child_name = name
            logger.info("Memory: child = %s", name)

        self.state = RobotState.SELECTIE_JOC
        greet = "Hi! I am TriSense."
        self._announce(greet, retain_speak_topic=False)

        q = self.mqtt.vision_queue
        while True:
            try:
                item = q.get(timeout=0.5)
                self._handle_vision(item)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                logger.info("User stop.")
                self.mqtt.stop()
                break
            except Exception as e:
                logger.exception("Main loop error: %s", e)
                time.sleep(1.0)
