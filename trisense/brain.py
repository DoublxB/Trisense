# -*- coding: utf-8 -*-
"""
Orchestrator principal: memorie, stari, MQTT, AI, TTS, metrici.
"""

from __future__ import annotations

import logging
import os
import queue
import random
import threading
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
from trisense.cognitive_games import (
    CO_STORY_OPENINGS,
    CATEGORY_WORDS,
    analyze_co_story_turn,
    build_model_level,
    count_category_words,
    parse_seconds_estimate,
)
from trisense.config import (
    ESP_AUDIO_TCP_PORT,
    ESP_SPEAK_MAX_CHARS,
    TOPIC_ROBOT_CONTROL,
    TOPIC_VISION_BUILD_CONTEXT,
    TRISENSE_TTS_OVER_TCP,
    VOICE_TCP_PORT,
    vision_id_to_action_map,
)
from trisense.dance_music import DANCE_DURATION_S, send_dance_music_to_esp
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

    _EMOTION_LABEL_EN = {
        "happy": "happy",
        "sad": "sad",
        "surprised": "surprised",
        "angry": "angry",
        "meltdown": "meltdown",
    }

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
        # Build the Model (Turnul lui Hanoi)
        self._build_level: int = 1
        self._build_awaiting: bool = False
        self._build_start: Optional[float] = None
        self._build_attempts: int = 0
        self._build_lock = threading.Lock()
        self._build_timer: Optional[threading.Timer] = None
        # Secunde de constructie inainte de captura CAM (env override).
        self._build_window_s: float = float(
            (os.environ.get("BUILD_MODEL_WINDOW_SEC") or "30").strip() or "30"
        )
        # Scor minim pentru a accepta potrivirea daca modelul nu intoarce "match" explicit.
        # Default 0.4 — tolerant la variante de forma (nivel 3 robot da max ~0.4 cu prag strict).
        self._build_match_threshold: float = float(
            (os.environ.get("BUILD_MODEL_MATCH_THRESHOLD") or "0.4").strip() or "0.4"
        )
        self._current_activity: str = ""
        # Stop & Go
        self._sg_trials: list[str] = []
        self._sg_index: int = 0
        self._sg_correct: int = 0
        self._sg_false_alarms: int = 0
        # Category fluency
        self._cat_category: str = ""
        # Time estimate
        self._te_target_s: float = 5.0
        self._te_start: float = 0.0
        self._te_round: int = 0
        # Co-constructed story
        self._co_story_lines: list[str] = []
        self._co_story_turn: int = 0
        self._co_story_vocab: set[str] = set()
        self._co_story_max_turns: int = 4

    def _log_activity(
        self,
        stare: str,
        *,
        activity: str = "",
        id_vazut: int = 0,
        timp_reactie_ms: Optional[float] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        name = self._child_name or self.memory.get_child_name() or "friend"
        self.metrics.log(
            nume_copil=name,
            id_vazut=id_vazut,
            timp_reactie_ms=timp_reactie_ms,
            stare=stare,
            activity=activity or stare,
            extra=extra,
        )

    def _publish_listen(self, *, duration_ms: int = 10000) -> bool:
        """Cere robotului sa porneasca ascultarea microfonului fara script manual."""
        host = (os.environ.get("PC_VOICE_IP") or "").strip()
        if not host:
            logger.warning("Act.6 auto-listen: PC_VOICE_IP lipseste in .env; nu pot trimite listen automat.")
            return False
        payload = {
            "listen": True,
            "pc_host": host,
            "voice_port": int(VOICE_TCP_PORT),
            "duration_ms": int(duration_ms),
        }
        ok = self._publish(payload)
        if ok:
            logger.info("Act.6 auto-listen trimis: %s", payload)
        else:
            logger.warning("Act.6 auto-listen nu s-a putut publica (MQTT offline?): %s", payload)
        return ok

    def _synthesize_tcp_pcm(self, msg: str) -> tuple[bytes, int]:
        """PCM mono pentru TCP către ESP: fallback Cloud/Gemini după sursa principală."""
        raw = (os.environ.get("TRISENSE_TTS_PCM_SOURCE") or "edge_tts").strip().lower()
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

        TRISENSE_TTS_PCM_SOURCE=edge_tts: principal local (edge-tts), apoi fallback Cloud/Gemini.
        TRISENSE_TTS_PCM_SOURCE=google_cloud: principal Cloud Neural2 (Vertex / GCP), apoi fallback local/Gemini.
        TRISENSE_TTS_PCM_ALLOW_GEMINI_FALLBACK=1: dacă Cloud/Gemini eșuează, păstrează rezervă.

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
                            "TTS local (edge-tts/pyttsx3 fallback): PCM %d B @ %d Hz (~%.2f s).",
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
        cq = _voice_keyword_compact(transcript)

        if "dance with me" in bl or "danseaza cu mine" in bl_ascii or "dans cu mine" in bl_ascii:
            return "dance_with_me"
        if cq and ("dancewithme" in cq or "danseazacumine" in cq):
            return "dance_with_me"
        if {"dance", "danseaza", "danseaz", "danseze", "dancing"} & words and "with" not in words:
            return "dance"

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

        # Comanda directa emotie (fara joc): "meltdown"
        if any(kw in bl_ascii for kw in ("meltdown", "breakdown", "criza", "panic", "panicat")):
            return "emotion_meltdown"

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

        # Build the Model (Turnul lui Hanoi)
        if "hanoi" in bl_ascii:
            return "build_model"
        if "build" in words and (
            "model" in words or "tower" in words or "shape" in words or "build" in words
        ) and ("model" in words or "tower" in words or "shape" in words):
            return "build_model"
        if ("construieste" in bl_ascii or "construim" in bl_ascii or "constructie" in bl_ascii) and (
            "model" in bl_ascii or "turn" in bl_ascii
        ):
            return "build_model"
        if cq and ("buildthemodel" in cq or "buildmodel" in cq or "buildthetower" in cq or "towergame" in cq):
            return "build_model"

        if cq and ("stopandgo" in cq or "stopgo" in cq or "stopsigo" in cq):
            return "stop_go"
        if "stop and go" in bl or "stop go" in bl or "stopgo" in bl_ascii:
            return "stop_go"

        if "category game" in bl or "name animals" in bl or "name colors" in bl or "name fruits" in bl:
            return "category_fluency"
        if cq and ("categorygame" in cq or "nameanimals" in cq or "namecolors" in cq):
            return "category_fluency"
        if "categorie" in bl_ascii and ("joc" in bl_ascii or "game" in bl):
            return "category_fluency"

        if (
            "time game" in bl
            or "time estimation" in bl
            or "time estimate" in bl
            or "play time estimate" in bl
            or "estimate time" in bl
            or ("time" in words and "estimate" in words)
        ):
            return "time_estimate"
        if cq and (
            "timegame" in cq
            or "timeestimation" in cq
            or "timeestimate" in cq
            or "playtimeestimate" in cq
            or "estimatetimp" in cq
        ):
            return "time_estimate"
        if "estimeaza timpul" in bl_ascii or "estimeaza timp" in bl_ascii:
            return "time_estimate"

        if (
            "tell a story" in bl
            or "make a story" in bl
            or "co story" in bl
            or "let's tell a story" in bl
            or "lets tell a story" in bl
        ):
            return "co_story"
        if cq and ("tellastory" in cq or "makeastory" in cq or "costory" in cq or "poveste" in cq):
            return "co_story"
        if "poveste" in bl_ascii and ("spune" in bl_ascii or "facem" in bl_ascii or "hai" in bl_ascii):
            return "co_story"

        if "session report" in bl or "end session" in bl or "end the session" in bl:
            return "session_report"
        if cq and ("sessionreport" in cq or "endsession" in cq):
            return "session_report"

        # Demo juriu: salut fix + braț, pivot dreapta, braț, pivot stânga
        if "hello to the judges" in bl or "salut juriu" in bl_ascii or "salut juriului" in bl_ascii:
            return "judges_demo"
        if ("judges" in words or "judge" in words) and (
            "hello" in words or "hi" in words or "everyone" in words or "demo" in words
        ):
            return "judges_demo"
        if cq and (
            "hellotothejudges" in cq
            or "hellojudges" in cq
            or "judgeshello" in cq
            or "judgesdemo" in cq
            or "demojudges" in cq
            or "demopentrujuriu" in cq
        ):
            return "judges_demo"

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

        if self.state == RobotState.STOP_GO:
            self._validate_stop_go_response(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        if self.state == RobotState.CATEGORY_FLUENCY:
            self._validate_category_fluency(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        if self.state == RobotState.TIME_ESTIMATE:
            self._validate_time_estimate(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        if self.state == RobotState.CO_CONSTRUCTED_STORY:
            self._validate_co_story_turn(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        if self.state == RobotState.DANCE_WITH_ME:
            self._validate_dance_with_me(t, name, robot_only=robot_only, esp_ip=esp_ip)
            return

        # Build the Model: ignora vocea in timp ce copilul construieste (nu LLM, nu confuzie).
        if self.state == RobotState.BUILD_MODEL:
            logger.info("Build the Model: transcript ignorat in timp ce asteptam butonul dreapta: %s", t[:80])
            self._say(
                f"Keep building, {name}! Press the right button when you're ready!",
                robot_only=robot_only,
                esp_ip=esp_ip,
            )
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
                "breathing_show": f"Watch my arms, lights and sounds — two breaths, {name}.",
                "forward": f"Moving forward, {name}!",
                "backward": f"Moving back.",
                "turn_left": f"Turning left.",
                "turn_right": f"Turning right.",
                "guess_emotion": f"Let's play Guess the Emotion, {name}!",
                "follow_pattern": f"Let's play Follow the Pattern, {name}!",
                "build_model": f"Let's play Build the Model, {name}!",
                "emotion_meltdown": f"Okay, {name}, the meltdown emotion!",
                "stop_go": f"Let's play Stop and Go, {name}!",
                "category_fluency": f"Let's play the category game, {name}!",
                "time_estimate": f"Let's play the time game, {name}!",
                "co_story": f"Let's make a story together, {name}!",
                "dance_with_me": f"Let's dance together, {name}!",
                "session_report": f"Okay {name}, I'll prepare your session report.",
            }.get(action, f"Okay, {name}!")
            # Act. 6 — Guess the Emotion
            if action == "guess_emotion":
                self._start_guess_emotion(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            # Act. 7 — Follow the Pattern
            if action == "follow_pattern":
                self._start_follow_pattern(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            # Build the Model (Turnul lui Hanoi)
            if action == "build_model":
                self._start_build_model(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "judges_demo":
                self._run_judges_demo(robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "stop_go":
                self._start_stop_go(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "category_fluency":
                self._start_category_fluency(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "time_estimate":
                self._start_time_estimate(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "co_story":
                self._start_co_story(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "dance_with_me":
                self._start_dance_with_me(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "session_report":
                self._run_session_report(name, robot_only=robot_only, esp_ip=esp_ip)
                return
            if action == "breathing_show":
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
                    logger.warning("Breathing show: Audio TCP esuat, incerc MQTT speak ca fallback.")
                    self._publish({"speak": vtrim})
                    time.sleep(3.0)
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
    # Demo juriu — voce fixă + brațe / rotiri scurte (Hello to the Judges)
    # ------------------------------------------------------------------

    def _run_judges_demo(self, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """
        Secvență pentru prezentare: mesaj introductor, braț drept sus, rotire dreapta,
        braț stâng sus, rotire stânga; apoi repaus brațe.
        Declanșare vocală: „Hello to the judges”, „hello judges”, „judges demo”, etc.
        """
        intro = "Hello everyone! I'm TriSense, the first LEGO robotic therapist."
        logger.info("Judges demo: intro + gesturi (numele copilului rămâne în memorie pentru dialog).")
        vtrim = intro.strip()
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
                "Judges demo: intro nu a ajuns pe difuzor (TCP/MQTT sau IP lipsă); continuă gesturile."
            )
        time.sleep(0.35)
        self._publish({"action": "right_arm"})
        time.sleep(2.5)
        self._publish({"action": "turn_right"})
        time.sleep(1.2)
        self._publish({"action": "left_arm"})
        time.sleep(2.5)
        self._publish({"action": "turn_left"})
        time.sleep(1.2)
        self._publish({"action": "wheels_stop"})
        time.sleep(0.15)
        self._publish({"action": "repose"})
        logger.info("Judges demo terminat.")

    # ------------------------------------------------------------------
    # Act. 6 — Guess the Emotion
    # ------------------------------------------------------------------

    def _start_guess_emotion(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """Robot alege o emotie random, o arata cu gesturi, cere copilului sa ghiceasca."""
        emotions = ["happy", "sad", "surprised", "angry", "meltdown"]
        self._current_emotion = random.choice(emotions)
        emotion_action = {
            "happy":     "emotion_happy",
            "sad":       "emotion_sad",
            "surprised": "emotion_surprised",
            "angry":     "emotion_angry",
            "meltdown":  "emotion_meltdown",
        }[self._current_emotion]
        logger.info("Act.6 [1/4]: emotie aleasa = %s", self._current_emotion)
        self._current_activity = "GUESS_EMOTION"

        intro = f"Watch carefully, {name}!"
        logger.info("Act.6 [2/4]: redau intro pe robot...")
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.6)

        logger.info("Act.6 [3/4]: trimit cmd %s la Hub si astept rutina...", emotion_action)
        self._publish({"action": emotion_action})
        emotion_dur = {
            "emotion_happy": 22.0,
            "emotion_sad": 9.5,
            "emotion_surprised": 8.5,
            "emotion_angry": 24.0,
            "emotion_meltdown": 28.0,
        }
        time.sleep(emotion_dur.get(emotion_action, 12.0))
        time.sleep(0.8)

        question = (
            f"What emotion was I showing, {name}? "
            "Happy, sad, surprised, angry, or meltdown?"
        )
        logger.info("Act.6 [4/4]: redau intrebarea pe robot...")
        self._say(question, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        # Porneste automat ascultarea microfonului, ca sa nu mai fie nevoie de script manual.
        self._publish_listen(duration_ms=10000)
        logger.info("Act.6: gata, astept raspunsul copilului (listen auto trimis).")
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
        elif any(kw in bl for kw in ("angry", "furie", "furios", "furioasa", "nervos", "enervat")):
            detected = "angry"
        elif any(kw in bl for kw in ("meltdown", "criza", "panic", "panicat", "breakdown")):
            detected = "meltdown"

        expected = self._current_emotion or "happy"
        exp_en = self._EMOTION_LABEL_EN.get(expected, expected)
        if detected == expected:
            response = f"Amazing, {name}! Correct — I was {exp_en}!"
            self._say(response, robot_only=robot_only, esp_ip=esp_ip)
            time.sleep(0.5)
            self._publish({"action": "dance"})
            self.state = RobotState.SELECTIE_JOC
            self._current_emotion = None
            logger.info("Act.6 terminat corect; emotie=%s", expected)
            return
        elif detected:
            det_en = self._EMOTION_LABEL_EN.get(detected, detected)
            response = (
                f"Not quite, {name}. I was actually {exp_en}. "
                f"But great try — you said {det_en}!"
            )
        else:
            response = f"I didn't quite hear you. I was {exp_en}! Try again next time!"

        self._say(response, robot_only=robot_only, esp_ip=esp_ip)
        self.state = RobotState.SELECTIE_JOC
        self._current_emotion = None
        logger.info("Act.6 terminat; detectat=%s, expected=%s", detected, expected)

    # ------------------------------------------------------------------
    # Act. 7 — Follow the Pattern
    # ------------------------------------------------------------------

    def _start_follow_pattern(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """Robot arata secventa de 3 miscari, cere copilului sa o repete pas cu pas."""
        # Randomizeaza combinatia la fiecare runda (permutare pe cei 3 pasi demo).
        steps = random.sample(self._PATTERN_STEPS, k=len(self._PATTERN_STEPS))
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
        # Auto-listen la inceputul secventei (pasul 1), fara trigger manual.
        self._publish_listen(duration_ms=10000)
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
                response = f"Perfect, {name}! Wonderful!"
                self._say(response, robot_only=robot_only, esp_ip=esp_ip)
                time.sleep(0.5)
                self._publish({"action": "dance"})
                self.state = RobotState.SELECTIE_JOC
                self._pattern_sequence = []
                self._pattern_step = 0
            else:
                next_action = self._pattern_sequence[self._pattern_step]
                step_label = next(
                    (s[1] for s in self._PATTERN_STEPS if s[0] == next_action),
                    next_action.replace("_", " "),
                )
                response = f"Correct! Step {self._pattern_step + 1}: {step_label}?"
                self._say(response, robot_only=robot_only, esp_ip=esp_ip)
                # Auto-listen dupa intrebarea pentru pasul urmator.
                self._publish_listen(duration_ms=10000)
        else:
            if expected:
                exp_label = next(
                    (s[1] for s in self._PATTERN_STEPS if s[0] == expected), expected.replace("_", " ")
                )
                if action:
                    response = f"Not quite! Step {self._pattern_step + 1} is {exp_label}. Try again!"
                else:
                    response = f"I didn't understand. Step {self._pattern_step + 1} is {exp_label}?"
            else:
                response = f"Something went wrong. Let's start over!"
                self.state = RobotState.SELECTIE_JOC
                self._pattern_step = 0
                self._pattern_sequence = []
            self._say(response, robot_only=robot_only, esp_ip=esp_ip)
            # Daca secventa continua (nu am resetat la SELECTIE_JOC), repornim auto-listen.
            if self.state == RobotState.FOLLOW_PATTERN:
                self._publish_listen(duration_ms=10000)
        logger.info("Act.7 pas=%d/%d; detectat=%s, expected=%s", self._pattern_step, total, action, expected)

    # ------------------------------------------------------------------
    # Build the Model (Turnul lui Hanoi) — model pe matrice Hub + verificare ESP32-CAM
    # ------------------------------------------------------------------

    _BUILD_INSTRUCTIONS = {
        "tower": (
            "Stack four orange bricks on top of each other to make a tall tower!"
        ),
        "pyramid": (
            "Build a blue pyramid! Put two bricks side by side at the bottom, "
            "one brick in the middle, and one small brick on top!"
        ),
        "robot": (
            "Build the black robot! Two bricks stacked for the base, "
            "a small brick on top, then a long brick for the arms, "
            "and a small brick as the head!"
        ),
    }

    def _clear_build_context(self) -> None:
        """Sterge contextul build de pe bridge (retained gol)."""
        try:
            self.mqtt.publish(TOPIC_VISION_BUILD_CONTEXT, {}, retain=True)
        except Exception as e:
            logger.debug("Build: nu pot curata build_context: %s", e)

    def _start_build_model(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        """
        Build the Model (inspirat Turnul lui Hanoi):
        1) afiseaza modelul tinta pe matricea Hub,
        2) anunta copilul ce sa construiasca,
        3) asteapta poza declansata de butonul DREAPTA de pe Hub (fara timer),
        4) verificarea CAM se face in _handle_vision.
        """
        # Anuleaza eventual watchdog ramas dintr-o runda anterioara.
        self._cancel_build_timer()

        level_def = build_model_level(self._build_level)
        level = int(level_def.get("level", self._build_level))
        action = str(level_def.get("action", "build_model_1"))
        shape = str(level_def.get("name", "tower"))
        description = str(level_def.get("description", "a LEGO build"))
        self._build_attempts += 1
        self._current_activity = "BUILD_MODEL"

        logger.info(
            "Build the Model [start]: level=%d shape=%s action=%s attempt=%d",
            level, shape, action, self._build_attempts,
        )

        # 1) Trimite contextul tintei la bridge (retained: il prinde si daca porneste mai tarziu).
        self.mqtt.publish(
            TOPIC_VISION_BUILD_CONTEXT,
            {
                "build_model": True,
                "level": level,
                "pattern": shape,
                "description": description,
            },
            retain=True,
        )

        # 2) Afiseaza modelul pe matricea Hub.
        self._publish({"action": action})
        time.sleep(0.4)

        # 3) Anunta sarcina: copilul construieste, apoi apasa butonul DREAPTA cand e gata.
        instruction = self._BUILD_INSTRUCTIONS.get(shape, "Copy the model on my screen with LEGO bricks!")
        intro = f"Look at my screen, {name}! {instruction}"
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.3)
        self._say(
            "When you finish, press the right button on me and I'll check it!",
            robot_only=robot_only,
            esp_ip=esp_ip,
            wait=True,
        )

        # 4) Asteptam poza (declansata de butonul DREAPTA -> ESP -> vision/capture_req -> bridge).
        self.state = RobotState.BUILD_MODEL
        self._build_start = time.time()
        self._build_awaiting = True
        logger.info("Build the Model: astept butonul DREAPTA pentru captura (fara timer).")

        # Watchdog lung: daca nu vine niciun rezultat, nu ramanem blocati in BUILD_MODEL.
        self._arm_build_timer(name, esp_ip=esp_ip)

    def _arm_build_timer(self, name: str, *, esp_ip: Optional[str]) -> None:
        timeout = float((os.environ.get("BUILD_MODEL_RESULT_TIMEOUT_SEC") or "90").strip() or "90")

        def _fire() -> None:
            self._build_timeout(name, esp_ip=esp_ip)

        t = threading.Timer(max(5.0, timeout), _fire)
        t.daemon = True
        self._build_timer = t
        t.start()

    def _cancel_build_timer(self) -> None:
        t = self._build_timer
        self._build_timer = None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def _build_timeout(self, name: str, *, esp_ip: Optional[str]) -> None:
        """Nu a venit rezultat de la ESP32-CAM in timp util."""
        with self._build_lock:
            if not self._build_awaiting or self.state != RobotState.BUILD_MODEL:
                return
            self._build_awaiting = False
            self.state = RobotState.SELECTIE_JOC
        logger.warning("Build the Model: timeout asteptand butonul/rezultatul CAM.")
        self._clear_build_context()
        self._say(
            f"No worries, {name}! Tell me when you want to build again!",
            robot_only=True,
            esp_ip=esp_ip,
        )

    def _validate_build_model(self, data: dict[str, Any]) -> None:
        """Proceseaza rezultatul ESP32-CAM (match / match_score) pentru runda curenta."""
        with self._build_lock:
            if not self._build_awaiting:
                logger.info("Build the Model: rezultat CAM ignorat (nu astept inca o captura).")
                return
            self._build_awaiting = False
            self._cancel_build_timer()

        name = self._child_name or self.memory.get_child_name() or "friend"
        raw = data.get("raw", "")
        match = data.get("match")
        score = data.get("match_score")
        # Daca match nu vine explicit, decidem pe baza scorului.
        if match is None and isinstance(score, (int, float)):
            match = float(score) >= self._build_match_threshold
        success = bool(match)

        duration = None
        if self._build_start is not None:
            duration = round(time.time() - self._build_start, 1)

        score_txt = f"{float(score):.2f}" if isinstance(score, (int, float)) else "n/a"
        logger.info(
            "Build the Model [result]: match=%s score=%s level=%d durata=%ss raw=%s",
            success, score_txt, self._build_level, duration, (raw[:120] if isinstance(raw, str) else raw),
        )

        self.metrics.log(
            nume_copil=name,
            id_vazut=int(data.get("id", 0)),
            timp_reactie_ms=(duration * 1000.0 if duration is not None else None),
            stare="BUILD_MODEL",
            extra={
                "activity": "build_model",
                "level": self._build_level,
                "attempts": self._build_attempts,
                "match": success,
                "match_score": (float(score) if isinstance(score, (int, float)) else None),
                "build_duration_s": duration,
            },
        )

        self._clear_build_context()

        if success:
            self._say(f"Yes! Great building, {name}! High five!", robot_only=True, esp_ip=self._last_esp_ip)
            time.sleep(0.4)
            self._publish({"action": "right_arm"})
            time.sleep(2.0)
            self._publish({"action": "dance"})
            # Avanseaza la nivelul urmator (pana la ultimul disponibil).
            self._build_level += 1
            self._build_attempts = 0
        else:
            self._say(
                f"Almost, {name}! That was tricky. We can try the same model again!",
                robot_only=True,
                esp_ip=self._last_esp_ip,
            )

        self.state = RobotState.SELECTIE_JOC
        self._build_start = None

    # ------------------------------------------------------------------
    # Act. 3.1 — Stop & Go
    # ------------------------------------------------------------------

    _SG_NUM_TRIALS = 6
    _SG_LISTEN_MS = 4500
    _SG_FREEZE_TIMEOUT = 5.5

    def _start_stop_go(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        go_n = self._SG_NUM_TRIALS // 2
        trials = ["go"] * go_n + ["freeze"] * (self._SG_NUM_TRIALS - go_n)
        random.shuffle(trials)
        self._sg_trials = trials
        self._sg_index = 0
        self._sg_correct = 0
        self._sg_false_alarms = 0
        self._current_activity = "STOP_GO"
        self.state = RobotState.STOP_GO

        rules = (
            f"Listen, {name}! When you see 1, say dance! "
            f"When you see 0, stay frozen and say nothing!"
        )
        self._say(rules, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.4)
        self._sg_run_trial(name, robot_only=robot_only, esp_ip=esp_ip)

    def _sg_run_trial(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        if self._sg_index >= len(self._sg_trials):
            self._sg_finish(name, robot_only=robot_only, esp_ip=esp_ip)
            return
        trial = self._sg_trials[self._sg_index]
        if trial == "go":
            self._publish({"action": "stop_go_go"})
            time.sleep(3.8)
            self._say("Go! Dance!", robot_only=robot_only, esp_ip=esp_ip, wait=True)
            self._publish_listen(duration_ms=self._SG_LISTEN_MS)
        else:
            self._publish({"action": "stop_go_freeze"})
            time.sleep(3.8)
            self._say("Freeze! Stay still!", robot_only=robot_only, esp_ip=esp_ip, wait=True)
            self._publish_listen(duration_ms=int(self._SG_FREEZE_TIMEOUT * 1000))

    def _validate_stop_go_response(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        if self._sg_index >= len(self._sg_trials):
            return
        trial = self._sg_trials[self._sg_index]
        bl = transcript.lower()
        said_dance = any(k in bl for k in ("dance", "danseaza", "danseaz", "move", "go"))
        said_freeze = any(k in bl for k in ("freeze", "stop", "still", "wait", "gata"))

        correct = False
        false_alarm = False
        if trial == "go":
            correct = said_dance and not said_freeze
        else:
            if said_dance:
                false_alarm = True
                correct = False
            else:
                correct = True

        if correct:
            self._sg_correct += 1
        if false_alarm:
            self._sg_false_alarms += 1

        self._log_activity(
            "STOP_GO",
            activity="STOP_GO",
            extra={
                "trial": self._sg_index + 1,
                "trial_type": trial,
                "correct": correct,
                "false_alarm": false_alarm,
                "transcript": transcript[:80],
            },
        )

        if correct:
            self._say("Great!", robot_only=robot_only, esp_ip=esp_ip, wait=True)
        elif false_alarm:
            self._say("Oops, that was freeze time!", robot_only=robot_only, esp_ip=esp_ip, wait=True)
        else:
            self._say("Almost! Keep trying!", robot_only=robot_only, esp_ip=esp_ip, wait=True)

        self._sg_index += 1
        time.sleep(0.3)
        if self._sg_index < len(self._sg_trials):
            self._sg_run_trial(name, robot_only=robot_only, esp_ip=esp_ip)
        else:
            self._sg_finish(name, robot_only=robot_only, esp_ip=esp_ip)

    def _sg_finish(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        self._publish({"action": "stop_go_end"})
        total = len(self._sg_trials)
        msg = f"Stop and Go done, {name}! You got {self._sg_correct} out of {total}!"
        self._say(msg, robot_only=robot_only, esp_ip=esp_ip)
        if self._sg_correct >= total // 2:
            time.sleep(0.4)
            self._publish({"action": "dance"})
        self._sg_trials = []
        self._sg_index = 0
        self._current_activity = ""
        self.state = RobotState.SELECTIE_JOC

    # ------------------------------------------------------------------
    # Act. 3.12 — Category fluency
    # ------------------------------------------------------------------

    def _start_category_fluency(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        cats = list(CATEGORY_WORDS.keys())
        self._cat_category = random.choice(cats) if cats else "animals"
        self._current_activity = "CATEGORY_FLUENCY"
        self.state = RobotState.CATEGORY_FLUENCY
        prompt = (
            f"Name as many {self._cat_category} as you can, {name}! "
            f"You have thirty seconds. Go!"
        )
        self._say(prompt, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        self._publish_listen(duration_ms=30000)

    def _validate_category_fluency(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        stats = count_category_words(transcript, self._cat_category)
        valid = int(stats.get("valid_count") or 0)
        words = stats.get("valid_words") or []
        self._log_activity(
            "CATEGORY_FLUENCY",
            activity="CATEGORY_FLUENCY",
            extra={
                "category": self._cat_category,
                "valid_count": valid,
                "valid_words": words[:12],
                "repetition_count": stats.get("repetition_count", 0),
            },
        )
        if valid >= 3:
            msg = f"Wonderful, {name}! I heard {valid} {self._cat_category}: {', '.join(words[:5])}!"
            self._publish({"action": "dance"})
        elif valid >= 1:
            msg = f"Good job, {name}! You named {valid}: {', '.join(words)}. Can you think of more next time?"
        else:
            msg = f"Nice try, {name}! Let's practice {self._cat_category} again later."
        self._say(msg, robot_only=robot_only, esp_ip=esp_ip)
        self._cat_category = ""
        self._current_activity = ""
        self.state = RobotState.SELECTIE_JOC

    # ------------------------------------------------------------------
    # Act. 3.16 — Time estimation
    # ------------------------------------------------------------------

    _TE_NUM_ROUNDS = 2

    def _start_time_estimate(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        self._te_round = 0
        self._current_activity = "TIME_ESTIMATE"
        self.state = RobotState.TIME_ESTIMATE
        intro = f"Time game, {name}! I'll be quiet. You say stop when you think enough seconds passed."
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.3)
        self._te_next_round(name, robot_only=robot_only, esp_ip=esp_ip)

    def _te_next_round(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        if self._te_round >= self._TE_NUM_ROUNDS:
            self._te_finish(name, robot_only=robot_only, esp_ip=esp_ip)
            return
        self._te_target_s = float(random.randint(4, 8))
        self._te_round += 1
        prompt = (
            f"Round {self._te_round}. Close your eyes. Say stop when you think "
            f"about {int(self._te_target_s)} seconds passed!"
        )
        self._say(prompt, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.4)
        self._te_start = time.time()
        self._publish_listen(duration_ms=15000)

    def _validate_time_estimate(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        elapsed = max(0.1, time.time() - self._te_start)
        spoken_guess = parse_seconds_estimate(transcript)
        # Copilul spune „stop” cand simte ca a trecut timpul — masuram elapsed.
        estimated = spoken_guess if spoken_guess is not None else elapsed
        error = abs(estimated - self._te_target_s)
        correct = error <= 2.0
        self._log_activity(
            "TIME_ESTIMATE",
            activity="TIME_ESTIMATE",
            timp_reactie_ms=elapsed * 1000.0,
            extra={
                "trial": self._te_round,
                "target_s": self._te_target_s,
                "guessed_s": round(estimated, 1),
                "elapsed_s": round(elapsed, 1),
                "error_s": round(error, 1),
                "correct": correct,
            },
        )
        if correct:
            msg = (
                f"Nice timing, {name}! You stopped at about {int(round(estimated))} seconds — "
                f"very close to {int(self._te_target_s)}!"
            )
        else:
            msg = (
                f"Good try! You stopped at about {int(round(estimated))} seconds. "
                f"We were aiming for about {int(self._te_target_s)} seconds."
            )
        self._say(msg, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.4)
        self._te_next_round(name, robot_only=robot_only, esp_ip=esp_ip)

    def _te_finish(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        self._say(f"Time game finished, {name}! Great focus!", robot_only=robot_only, esp_ip=esp_ip)
        self._current_activity = ""
        self.state = RobotState.SELECTIE_JOC

    # ------------------------------------------------------------------
    # Act. 2.3 — Dance with me
    # ------------------------------------------------------------------

    def _start_dance_with_me(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        self._current_activity = "DANCE_WITH_ME"
        self.state = RobotState.DANCE_WITH_ME
        intro = f"Watch me dance, {name}! Then it's your turn!"
        self._say(intro, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        time.sleep(0.3)
        # Dans Hub intai; muzica PCM dupa (acelasi port TCP 8766 — fara suprapunere cu TTS).
        self._publish({"action": "dance_with_me"})
        time.sleep(10.5)
        host = (esp_ip or self._last_esp_ip or os.environ.get("ROBOT_ESP_IP") or "").strip()
        if host:
            send_dance_music_to_esp(host)
            time.sleep(DANCE_DURATION_S + 0.5)
        time.sleep(1.2)
        self._say(
            f"Your turn, {name}! Stand up and dance like me!",
            robot_only=robot_only,
            esp_ip=esp_ip,
            wait=True,
        )
        self._publish_listen(duration_ms=12000)

    def _validate_dance_with_me(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        bl = transcript.lower()
        danced = any(
            k in bl
            for k in ("dance", "danseaza", "danseaz", "moving", "jump", "wiggle", "yes", "done", "finished")
        )
        self._log_activity(
            "DANCE_WITH_ME",
            activity="DANCE_WITH_ME",
            extra={"engagement": danced, "transcript": transcript[:80]},
        )
        if danced:
            msg = f"Awesome dancing, {name}! You moved with me!"
            self._say(msg, robot_only=robot_only, esp_ip=esp_ip)
            time.sleep(0.4)
            self._publish({"action": "dance"})
        else:
            self._say(
                f"That's okay, {name}! Next time we can dance together louder!",
                robot_only=robot_only,
                esp_ip=esp_ip,
            )
        self._current_activity = ""
        self.state = RobotState.SELECTIE_JOC

    # ------------------------------------------------------------------
    # Poveste co-construită
    # ------------------------------------------------------------------

    def _start_co_story(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        self._co_story_lines = []
        self._co_story_turn = 0
        self._co_story_vocab = set()
        self._current_activity = "CO_CONSTRUCTED_STORY"
        self.state = RobotState.CO_CONSTRUCTED_STORY
        opening = random.choice(CO_STORY_OPENINGS).format(name=name)
        if self.ai.available:
            try:
                opening = self.ai.reply(
                    f"Start a very short co-created story for child {name}. "
                    f"One sentence only, end with a question for the child. English.",
                    name,
                ).strip() or opening
            except Exception:
                pass
        self._co_story_lines.append(f"TriSense: {opening}")
        self._say(opening, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        self._publish_listen(duration_ms=15000)

    def _validate_co_story_turn(
        self, transcript: str, name: str, *, robot_only: bool, esp_ip: Optional[str]
    ) -> None:
        child_line = (transcript or "").strip()
        if len(child_line) < 2:
            self._say(
                f"What happens next, {name}?",
                robot_only=robot_only,
                esp_ip=esp_ip,
                wait=True,
            )
            self._publish_listen(duration_ms=12000)
            return

        prev = ""
        for line in reversed(self._co_story_lines):
            if line.startswith(f"{name}:"):
                prev = line
                break

        metrics = analyze_co_story_turn(
            child_line,
            story_vocab=self._co_story_vocab,
            prev_child=prev,
        )
        self._co_story_vocab.update(metrics.get("new_ideas") or [])
        self._co_story_turn += 1
        self._co_story_lines.append(f"{name}: {child_line}")
        self._log_activity(
            "CO_CONSTRUCTED_STORY",
            activity="CO_CONSTRUCTED_STORY",
            extra={
                "turn": self._co_story_turn,
                "word_count": metrics.get("word_count", 0),
                "emotion_count": metrics.get("emotion_count", 0),
                "initiation": metrics.get("initiation", False),
                "topic_maintained": metrics.get("topic_maintained", True),
            },
        )

        if self._co_story_turn >= self._co_story_max_turns:
            ending = (
                f"What a wonderful story, {name}! "
                f"You helped me imagine something special today!"
            )
            self._say(ending, robot_only=robot_only, esp_ip=esp_ip)
            time.sleep(0.4)
            self._publish({"action": "dance"})
            self._co_story_lines = []
            self._co_story_turn = 0
            self._co_story_vocab = set()
            self._current_activity = ""
            self.state = RobotState.SELECTIE_JOC
            return

        if self.ai.available:
            context = "\n".join(self._co_story_lines[-6:])
            prompt = (
                f"Co-create a children's story with {name}. Story so far:\n{context}\n"
                f"Child just said: {child_line}\n"
                "Reply with ONE short encouraging sentence that continues the story, "
                "then ask ONE short question. English only."
            )
            try:
                next_line = self.ai.reply(prompt, name).strip()
            except Exception:
                next_line = f"Wow, {name}! What happens next?"
        else:
            next_line = f"Wow, {name}! What happens next in our story?"

        self._co_story_lines.append(f"TriSense: {next_line}")
        self._say(next_line, robot_only=robot_only, esp_ip=esp_ip, wait=True)
        self._publish_listen(duration_ms=15000)

    # ------------------------------------------------------------------
    # Act. 3.10 — Raport sesiune terapeut
    # ------------------------------------------------------------------

    def _run_session_report(self, name: str, *, robot_only: bool, esp_ip: Optional[str]) -> None:
        summary = self.metrics.build_session_summary()
        path = self.metrics.write_session_report(summary)
        if path:
            msg = (
                f"Session report ready for {name}. "
                f"I saved it for your therapist. Great work today!"
            )
            logger.info("Session report: %s", path)
        else:
            msg = f"No session data yet, {name}. Play a game first, then ask again!"
        self._say(msg, robot_only=robot_only, esp_ip=esp_ip)

    def _run_primul_salut(self) -> None:
        """No name in memory: ask child name and save JSON."""
        msg = (
            "First meeting with TriSense. Tell the child you are happy to meet them. "
            "Ask their name briefly in one friendly sentence, in English."
        )
        if self.ai.available:
            text = self.ai.reply(msg, "friend")
        else:
            text = "Hi! I'm TriSense. What's your name?"
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
            f"The child {name} was just recognized (greeting/face signal). "
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
            f"The child {name} showed a LEGO piece or build recognized by the camera (class ID {object_class_id}). "
            "Praise them in one short sentence and suggest a small play activity, in English."
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
                f"The round is over. Encourage {name} for taking part, very briefly, in English.",
                name,
            )
            if self.ai.available
            else f"Great job, {name}! See you next play round!"
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

        # Build the Model: rezultatul verificarii CAM are prioritate cat suntem in joc.
        if self.state == RobotState.BUILD_MODEL and self._build_awaiting:
            self._validate_build_model(data)
            return

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
        greet_name = self._child_name or name or ""
        self.metrics.start_session(greet_name or "friend")
        greet = (
            f"Hi! I'm TriSense. Great to see you, {greet_name}!"
            if greet_name
            else "Hi! I'm TriSense."
        )
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
                report = self.metrics.end_session()
                if report:
                    logger.info("Session report on exit: %s", report)
                self.mqtt.stop()
                break
            except Exception as e:
                logger.exception("Main loop error: %s", e)
                time.sleep(1.0)
