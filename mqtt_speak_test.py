# -*- coding: utf-8 -*-
"""
Trimite un mesaj pe topicul robot/control ca ESP32 sa vorbeasca pe difuzor.

De ce "merge uneori, alteori nu" (la fel pe broker public HiveMQ):
  - broker.hivemq.com e gratuit, fara SLA — uneori e aglomerat sau limiteaza conexiuni;
  - acelasi MQTT client_id cu o sesiune veche inca deschisa → noul client poate fi respins;
  - retea WiFi / DNS temporar;
  - pe robot: WiFi pierdut, ESP trebuie repornit sau reconectat MQTT.

Acest script: client_id unic la fiecare rulare, QoS 1, reincercari cu asteptare.
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
except ImportError:
    pass

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
USE_TLS = os.environ.get("MQTT_USE_TLS", "0") == "1"
TOPIC = "robot/control"

MAX_ATTEMPTS = 4
BACKOFF_SEC = 2.5


def _rc_ok(rc: object) -> bool:
    try:
        if hasattr(rc, "value"):
            return int(rc.value) == 0
        return int(rc) == 0
    except Exception:
        return rc == 0 or rc == mqtt.MQTT_ERR_SUCCESS


def _make_client() -> mqtt.Client:
    # ID unic la fiecare rulare — evita conflict cu sesiune MQTT veche (acelasi PID, alt socket)
    cid = f"TrS_spk_{os.getpid()}_{random.randint(0, 0x7FFFFFFF)}"
    kw = {"client_id": cid, "protocol": mqtt.MQTTv311}
    try:
        # paho-mqtt 2.x: VERSION1 e depreciat; VERSION2 e recomandat
        return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, **kw)
    except (TypeError, AttributeError):
        try:
            return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, **kw)
        except AttributeError:
            return mqtt.Client(**kw)


def _try_once(payload: bytes) -> bool:
    connected = threading.Event()

    def on_connect(_c: object, _u: object, _f: object, arg4: object, _props: object = None) -> None:
        # VERSION2: arg4 = ReasonCode; VERSION1: arg4 = rc (int)
        if isinstance(arg4, int):
            ok = arg4 == 0
        elif hasattr(arg4, "is_failure"):
            ok = not arg4.is_failure
        else:
            ok = int(getattr(arg4, "value", 1)) == 0
        if ok:
            connected.set()

    client = _make_client()
    client.on_connect = on_connect
    if USE_TLS:
        client.tls_set()

    try:
        rc_conn = client.connect(BROKER, PORT, keepalive=30)
    except OSError as e:
        print("  (retea)", e)
        return False
    except Exception as e:
        print("  (connect)", e)
        return False

    if not _rc_ok(rc_conn):
        print("  (connect rc)", rc_conn)
        return False

    client.loop_start()
    try:
        if not connected.wait(timeout=12.0):
            print("  (timeout CONNACK — broker lent sau blocat)")
            return False
        time.sleep(0.05)
        inf = client.publish(TOPIC, payload, qos=1)
        inf.wait_for_publish(timeout=20.0)
        rc_pub = getattr(inf, "rc", 0)
        return _rc_ok(rc_pub)
    finally:
        time.sleep(0.05)
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


def main() -> None:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        text = "Salut, sunt TriSense. Ma auzi pe difuzor?"
    if len(text) > 500:
        text = text[:497] + "..."
    payload = json.dumps({"speak": text}, ensure_ascii=False).encode("utf-8")

    print("Broker:", BROKER, "port:", PORT, "TLS:", USE_TLS, "topic:", TOPIC)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print(f"Reincercare {attempt}/{MAX_ATTEMPTS} peste {BACKOFF_SEC:.0f}s...")
            time.sleep(BACKOFF_SEC)
        ok = _try_once(payload)
        if ok:
            print("OK trimis pe", TOPIC, ":", text[:100] + ("..." if len(text) > 100 else ""))
            return

    print(
        "Esuat dupa", MAX_ATTEMPTS, "incercari.",
        "Incearca mai tarziu, alt WiFi sau verifica daca brokerul public e suprasolicitat.",
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
