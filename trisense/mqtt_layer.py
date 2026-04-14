# -*- coding: utf-8 -*-
"""
Client MQTT pentru PC: asculta vision/tags, publica pe robot/control.
Reconectare cu backoff usoara; erorile nu opresc procesul principal.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from trisense.config import (
    ESP_SPEAK_MAX_CHARS,
    MQTT_BROKER,
    MQTT_CLIENT_ID_PC,
    MQTT_PORT,
    MQTT_USE_TLS,
    TOPIC_ROBOT_CONTROL,
    TOPIC_ROBOT_SPEAK,
    TOPIC_VISION_TAGS,
)

logger = logging.getLogger(__name__)

# Format vechi de pe ESP (fallback)
_LEGACY_ID_RE = re.compile(r"ID:\s*(\d+)", re.IGNORECASE)


def parse_vision_payload(raw: str) -> Optional[dict[str, Any]]:
    """
    Accepta JSON {"id": N} sau text vechi 'Robotul a detectat obiectul ID: N'.
    Returneaza dict cu cheie 'id' sau None.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "id" in obj:
            return {"id": int(obj["id"]), "raw": raw}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = _LEGACY_ID_RE.search(raw)
    if m:
        return {"id": int(m.group(1)), "raw": raw}
    return None


class MqttBrainClient:
    """Broker MQTT cu coada thread-safe pentru mesaje vision."""

    def __init__(
        self,
        on_vision: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self._on_vision = on_vision
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def vision_queue(self) -> queue.Queue[dict[str, Any]]:
        return self._queue

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            logger.info("MQTT conectat la %s", MQTT_BROKER)
            self._connected.set()
            try:
                client.subscribe(TOPIC_VISION_TAGS, qos=0)
                logger.info("Abonat la %s", TOPIC_VISION_TAGS)
            except Exception as e:
                logger.warning("Subscribe esuat: %s", e)
        else:
            logger.error("MQTT connect rc=%s", rc)
            self._connected.clear()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._connected.clear()
        logger.warning("MQTT deconectat (rc=%s)", rc)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8", errors="replace")
            if topic == TOPIC_VISION_TAGS:
                parsed = parse_vision_payload(payload)
                if parsed:
                    parsed["_received_at"] = time.time()
                    self._queue.put(parsed)
                    if self._on_vision:
                        self._on_vision(parsed)
        except Exception as e:
            logger.exception("Eroare la procesare mesaj MQTT: %s", e)

    def connect_background(self) -> None:
        """Porneste loop MQTT intr-un thread daemon."""

        def run() -> None:
            backoff = 1.0
            while not self._stop.is_set():
                try:
                    try:
                        self._client = mqtt.Client(
                            mqtt.CallbackAPIVersion.VERSION1,
                            client_id=MQTT_CLIENT_ID_PC,
                            protocol=mqtt.MQTTv311,
                        )
                    except AttributeError:
                        self._client = mqtt.Client(
                            client_id=MQTT_CLIENT_ID_PC,
                            protocol=mqtt.MQTTv311,
                        )
                    self._client.on_connect = self._on_connect
                    self._client.on_disconnect = self._on_disconnect
                    self._client.on_message = self._on_message
                    if MQTT_USE_TLS:
                        self._client.tls_set()
                    self._client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                    backoff = 1.0
                    self._client.loop_forever(retry_first_connection=True)
                except Exception as e:
                    logger.warning("MQTT loop eroare: %s — retry in %.1fs", e, backoff)
                    self._connected.clear()
                    time.sleep(min(backoff, 60.0))
                    backoff = min(backoff * 2, 60.0)

        self._thread = threading.Thread(target=run, daemon=True, name="mqtt-loop")
        self._thread.start()

    def wait_connected(self, timeout: float = 15.0) -> bool:
        return self._connected.wait(timeout=timeout)

    def publish_control(self, command: dict[str, Any]) -> bool:
        """Trimite comanda JSON pe robot/control."""
        if not self._client or not self._connected.is_set():
            logger.debug("MQTT indisponibil; comanda nu trimisa: %s", command)
            return False
        try:
            payload = json.dumps(command, ensure_ascii=False)
            self._client.publish(TOPIC_ROBOT_CONTROL, payload, qos=0)
            return True
        except Exception as e:
            logger.warning("publish_control esuat: %s", e)
            return False

    def publish_speak_retained(self, speak_text: str) -> bool:
        """
        Acelasi JSON {"speak": "..."} pe topic dedicat, cu retain=1.
        Brokerul il livreaza imediat abonatilor si il pastreaza pentru ESP conectat dupa PC.
        """
        if not self._client or not self._connected.is_set():
            return False
        try:
            msg = (speak_text or "").strip()
            if len(msg) > ESP_SPEAK_MAX_CHARS:
                msg = msg[: max(0, ESP_SPEAK_MAX_CHARS - 3)] + "..."
            if not msg:
                return False
            payload = json.dumps({"speak": msg}, ensure_ascii=False)
            self._client.publish(TOPIC_ROBOT_SPEAK, payload, qos=0, retain=True)
            logger.info(
                "MQTT retained pe %s (primeste si robotul pornit dupa acest mesaj)",
                TOPIC_ROBOT_SPEAK,
            )
            return True
        except Exception as e:
            logger.warning("publish_speak_retained esuat: %s", e)
            return False

    def stop(self) -> None:
        self._stop.set()
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
