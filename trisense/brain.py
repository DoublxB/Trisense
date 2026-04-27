# -*- coding: utf-8 -*-
"""
Orchestrator principal: memorie, stari, MQTT, AI, TTS, metrici.
"""

from __future__ import annotations

import logging
import os
import queue
import time
from typing import Any, Optional

from trisense.ai_client import TriSenseAI
from trisense.audio_push import send_pcm_to_esp
from trisense.config import ESP_AUDIO_TCP_PORT, ESP_SPEAK_MAX_CHARS, TOPIC_ROBOT_CONTROL, TRISENSE_TTS_OVER_TCP
from trisense.memory_store import MemoryStore
from trisense.metrics_logger import MetricsLogger
from trisense.mqtt_layer import MqttBrainClient
from trisense.states import RobotState
from trisense.tts_engine import TTSEngine

logger = logging.getLogger(__name__)


class TriSenseBrain:
    """
    Creier TriSense 3.0:
    - Memorie JSON (nume copil)
    - Stari: START -> SALUT (ID1) -> SELECTIE_JOC -> ACTIVITATE (ID2+) -> FINAL
    - MQTT: asculta vision/tags, comenzi pe robot/control (nume topic neschimbat)
    - ESP32: HuskyLens in Object Classification — ID-uri invatate pe camera (fara stickere).
      ID 1 = fata; ID 2+ = piese / constructii LEGO invatate.
    """

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
    ) -> bool:
        """TTS pe PC + acelasi text pe MQTT pentru difuzor ESP (Gemini TTS pe robot).
        robot_only=True: doar MQTT (folosit din thread-ul serverului TCP voce; evita pyttsx3 din background).
        TRISENSE_TTS_PC=1 in .env pentru voce si pe laptop; implicit / lipsa = doar MQTT (difuzor robot).
        Citire la fiecare apel (nu la import), ca sa respecte load_dotenv(override=True).
        Returneaza True daca textul a fost livrat (TCP TTS sau MQTT speak); False daca nu s-a putut trimite.
        """
        v = (os.environ.get("TRISENSE_TTS_PC") or "0").strip().lower()
        tts_pc = v in ("1", "true", "yes")
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
                prefer_gemini = (
                    (os.environ.get("TRISENSE_TTS_PREFER_GEMINI") or "0").strip().lower()
                    in ("1", "true", "yes")
                )
                pcm: bytes = b""
                sample_rate: int = 24000
                if not prefer_gemini and self.tts.available:
                    pcm, sample_rate = self.tts.synthesize_pcm(msg)
                    if pcm:
                        logger.info(
                            "TTS local pyttsx3: PCM %d B @ %d Hz (~%.2f s).",
                            len(pcm),
                            sample_rate,
                            len(pcm) / (2 * max(1, sample_rate)),
                        )
                    else:
                        logger.info("TTS local pyttsx3 indisponibil sau gol; trec pe Gemini TTS.")
                if not pcm:
                    pcm, sample_rate = self.ai.synthesize_tts_pcm(msg)
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
                        if dur_ms >= min_ms:
                            return True
                        logger.warning(
                            "PCM TTS sub pragul %d ms — pe difuzor e aproape inaudibil; "
                            "trimit acelasi text si pe MQTT speak (TTS pe ESP).",
                            min_ms,
                        )
                    else:
                        logger.warning("Audio TCP esuat; incerc MQTT speak.")
            else:
                logger.info("Audio TCP preferred, but robot IP is not known yet; skipping local ESP TTS fallback.")
                return False
        if msg:
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
                and not tts_pc
                and not self._pc_tts_hint_logged
            ):
                self._pc_tts_hint_logged = True
                logger.info(
                    "Pe laptop nu se aude (TRISENSE_TTS_PC=0); vocea e pe difuzor ESP. "
                    "Pune TRISENSE_TTS_PC=1 in .env daca vrei si audio pe PC."
                )
            return ok
        return True

    def _detect_motor_action(self, transcript: str) -> Optional[str]:
        """Mapeaza cuvinte cheie din transcript la o actiune motrice ce ajunge la hub LEGO.

        Returneaza un identificator scurt ("dance", ...) sau None daca nu s-a recunoscut nimic.
        Cautam cuvinte intregi ca sa nu confundam "dance" cu "advance".
        """
        if not transcript:
            return None
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in transcript)
        words = set(normalized.split())
        if {"dance", "danseaza", "danseaz\u0103", "danseaz", "danseze"} & words:
            return "dance"
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

        action = self._detect_motor_action(t)
        if action == "dance":
            sent = self._publish({"action": "dance"})
            logger.info("Motor action 'dance' -> MQTT robot/control trimis=%s", sent)
            text = f"Let's dance, {name}!"
            self._announce(text, robot_only=robot_only, esp_ip=esp_ip)
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
        """ID din JSON MQTT = clasa HuskyLens (1=fata, 2+=LEGO invatat)."""
        vision_id = int(data["id"])
        recv = data.get("_received_at", time.time())

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
