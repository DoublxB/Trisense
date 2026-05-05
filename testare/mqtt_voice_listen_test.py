# -*- coding: utf-8 -*-
"""
Trimite {"listen": true, "pc_host": "IP_PC"} pe robot/control — ESP inregistreaza ~10s (implicit)
si trimite audio la serverul TCP (run_voice_dialog.py pe acelasi PC).

Prenumite:
  - PC: py run_voice_dialog.py (firewall pentru VOICE_TCP_PORT, default 8765).
  - ESP: main_robot.py + secrets.py cu PC_VOICE_IP (optional daca treci IP-ul mai jos).

Exemplu:
  py testare/mqtt_voice_listen_test.py 192.168.1.50
  py testare/mqtt_voice_listen_test.py   # foloseste PC_VOICE_IP din .env
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "192.168.100.134")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
TOPIC = "robot/control"


def main() -> None:
    host = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not host:
        host = (os.environ.get("PC_VOICE_IP") or "").strip()
    if not host:
        print("Folosire: py testare/mqtt_voice_listen_test.py <IP_PC>")
        print("sau seteaza PC_VOICE_IP in .env")
        sys.exit(1)
    vport = int(os.environ.get("VOICE_TCP_PORT", "8765"))
    payload = json.dumps(
        {
            "listen": True,
            "pc_host": host,
            "voice_port": vport,
            "duration_ms": 10000,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="TriSense_voice_listen_pc",
            protocol=mqtt.MQTTv311,
        )
    except (TypeError, AttributeError):
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="TriSense_voice_listen_pc",
                protocol=mqtt.MQTTv311,
            )
        except AttributeError:
            client = mqtt.Client(
                client_id="TriSense_voice_listen_pc",
                protocol=mqtt.MQTTv311,
            )

    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()
    try:
        inf = client.publish(TOPIC, payload, qos=0)
        inf.wait_for_publish(timeout=10.0)
        print("OK listen trimis catre ESP, pc_host=", host, " port TCP=", vport)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
