# -*- coding: utf-8 -*-
"""
Pas 4 — smoke MQTT pentru micari hub prin firmware ESP:

  1) Publica succesiune JSON pe robot/control ({\"action\":\"...\"} sau {\"cmd\":N}).
  2) Optional: publica {\"id\":K} pe vision/tags (simulate camera) pentru a testa creierul
     PC daca TriSenseBrain ruleaza si VISION_ID_TO_ACTION este setat pentru acelasi K.

Cerinte: broker pornit, ESP cu hub si (la test vision) eventual PC cu python -m triSense sau run_voice.

Ruleaza din radacina repo:
  py testare/test_motor_integration.py
  py testare/test_motor_integration.py --actions repose,wheels_stop --pause 3
  py testare/test_motor_integration.py --vision-id 22
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

import paho.mqtt.publish as mqtt_publish


def main() -> None:
    from trisense.config import MQTT_BROKER, MQTT_PORT, TOPIC_ROBOT_CONTROL, TOPIC_VISION_TAGS

    ap = argparse.ArgumentParser(description="Smoke test MQTT miscari TriSense.")
    ap.add_argument(
        "--broker",
        default=os.environ.get("MQTT_BROKER", MQTT_BROKER),
        help="MQTT broker host",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MQTT_PORT", str(MQTT_PORT))),
        help="MQTT port",
    )
    ap.add_argument(
        "--pause",
        type=float,
        default=2.5,
        help="Pauza intre publicari (secunde).",
    )
    ap.add_argument(
        "--actions",
        default="repose,breathe_in,breathe_out,dance,wheels_stop",
        help="Lista action denumiri separate prin virgula (mapate in main_robot.py).",
    )
    ap.add_argument(
        "--cmd",
        type=int,
        default=None,
        metavar="N",
        help="Daca e setat, trimite o singura data {\"cmd\":N} in loc de --actions.",
    )
    ap.add_argument(
        "--vision-id",
        type=int,
        default=None,
        metavar="ID",
        help="Dupa actiuni, publica {\"id\":ID} pe vision/tags (test creier PC).",
    )
    args = ap.parse_args()

    def pub(topic: str, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":"))
        print(f"[PUB] {topic} {body}")
        mqtt_publish.single(
            topic,
            body.encode("utf-8"),
            hostname=args.broker,
            port=args.port,
        )

    print(f"[INIT] broker={args.broker}:{args.port}")
    if args.cmd is not None:
        pub(TOPIC_ROBOT_CONTROL, {"cmd": int(args.cmd)})
        time.sleep(args.pause)
    else:
        for part in args.actions.split(","):
            name = part.strip()
            if not name:
                continue
            pub(TOPIC_ROBOT_CONTROL, {"action": name})
            time.sleep(args.pause)

    if args.vision_id is not None:
        pub(TOPIC_VISION_TAGS, {"id": int(args.vision_id)})
        print(
            "[NOTE] vision/tags: creierul PC traduce ID doar daca VISION_ID_TO_ACTION contine aceasta cheie.",
        )


if __name__ == "__main__":
    main()
