# -*- coding: utf-8 -*-
"""
Trimite {"listen": true, "pc_host": "IP_PC"} pe robot/control — ESP inregistreaza ~10s (implicit)
si trimite audio la serverul TCP (run_voice_dialog.py pe acelasi PC).

Prenumite:
  - PC: py run_voice_dialog.py (firewall pentru VOICE_TCP_PORT, default 8765).
  - ESP: main_robot.py + secrets.py cu PC_VOICE_IP (optional daca treci IP-ul mai jos).

Rulare:
  py testare/mqtt_voice_listen_test.py              # loop: Enter = listen
  py testare/mqtt_voice_listen_test.py --once       # o singura comanda (comportament vechi)
  py testare/mqtt_voice_listen_test.py 192.168.1.50
  py testare/mqtt_voice_listen_test.py 192.168.1.50 --once

Oprire loop: Ctrl+C
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


def _cli_args() -> tuple[list[str], bool]:
    args = [a for a in sys.argv[1:] if a != "--once"]
    once = "--once" in sys.argv[1:]
    return args, once


def _pc_host(positional: list[str]) -> str:
    if positional:
        return positional[0].strip()
    for key in ("PC_VOICE_IP", "MQTT_BROKER"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


def _make_client() -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="TriSense_voice_listen_pc",
            protocol=mqtt.MQTTv311,
        )
    except (TypeError, AttributeError):
        try:
            return mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="TriSense_voice_listen_pc",
                protocol=mqtt.MQTTv311,
            )
        except AttributeError:
            return mqtt.Client(
                client_id="TriSense_voice_listen_pc",
                protocol=mqtt.MQTTv311,
            )


def _publish_listen(client: mqtt.Client, host: str, vport: int, duration_ms: int) -> None:
    payload = json.dumps(
        {
            "listen": True,
            "pc_host": host,
            "voice_port": vport,
            "duration_ms": duration_ms,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    inf = client.publish(TOPIC, payload, qos=0)
    inf.wait_for_publish(timeout=10.0)
    print(
        f"[OK] listen trimis — pc_host={host} port TCP={vport} "
        f"durata={duration_ms}ms (~{duration_ms / 1000:.0f}s inregistrare ESP)"
    )


def main() -> None:
    positional, once = _cli_args()
    host = _pc_host(positional)
    if not host:
        print("Folosire: py testare/mqtt_voice_listen_test.py [IP_PC] [--once]")
        print("sau seteaza PC_VOICE_IP / MQTT_BROKER in .env")
        sys.exit(1)

    vport = int(os.environ.get("VOICE_TCP_PORT", "8765"))
    duration_ms = int(os.environ.get("VOICE_RECORD_MS", "10000"))
    loop_mode = not once

    print(f"[INIT] MQTT broker: {BROKER}:{PORT}")
    print(f"[INIT] pc_host (server TCP pe PC): {host}")
    print(f"[INIT] Mod: {'LOOP (Enter = listen, Ctrl+C = oprire)' if loop_mode else 'O singura comanda'}")
    print("[INIT] Porneste in alt terminal: py run_voice_dialog.py")

    client = _make_client()
    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()

    turn = 0
    try:
        while True:
            turn += 1
            if loop_mode:
                print(f"\n[TURA {turn}] Apasa ENTER ca ESP sa asculte ~{duration_ms / 1000:.0f}s (Ctrl+C = oprire)")
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    print("\n[STOP] Iesire.")
                    break

            try:
                _publish_listen(client, host, vport, duration_ms)
            except Exception as e:
                print(f"[ERR] Publish esuat: {e}")
                if once:
                    raise SystemExit(1) from e
                continue

            if once:
                break
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
