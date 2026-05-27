# -*- coding: utf-8 -*-
"""
Bridge ESP32-CAM (firmware TriSense HTTP) -> MQTT vision/tags.

Firmware-ul plăcii CAM (cel pe care îl ai) expune:
  http://<IP>/capture   — JPEG o singură dată (port 80)
  http://<IP>:81/stream — MJPEG (nu folosit aici)

Acest script (rulează pe PC, cu .env ca restul TriSense):
  1) GET /capture la interval
  2) trimite JPEG la Vertex/Gemini pe PC (reply_with_image_jpeg)
  3) parsează {\"id\": N} din răspuns
  4) publică pe topicul vision/tags ca HuskyLens -> brain.py reacționează la fel

Pornește MQTT broker + (opțional) main.py / creierul TriSense.

Exemplu:
  # .env: ESP32CAM_CAPTURE_URL=http://192.168.1.70/capture   (sau ESP32CAM_HOST=192.168.1.70)
  py testare/vision_esp32cam_bridge.py
  py testare/vision_esp32cam_bridge.py --once
  py testare/vision_esp32cam_bridge.py --interval 5 --dry-run
  # Trigger la cerere (ex. buton LEFT pe Hub -> MQTT vision/capture_req):
  py testare/vision_esp32cam_bridge.py --on-request

Aliniază ID-urile cu HuskyLens / VISION_ID_TO_ACTION: editează VISION_CAM_PROMPT în .env.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

import paho.mqtt.publish as mqtt_publish
import paho.mqtt.client as mqtt_client

from trisense.config import MQTT_BROKER, MQTT_PORT, TOPIC_VISION_TAGS, TOPIC_VISION_BUILD_CONTEXT
from trisense.cognitive_games import build_model_verify_prompt

# Prompt implicit: aliniază-te cu convenția brain (ex. id 1 = față / salut). Ajustează în .env.
_DEFAULT_VISION_PROMPT = """You classify one image for a child robot interaction.
Output ONLY valid JSON with one field: "id" (integer). No markdown, no explanation.

Rules:
- id=1 if a human face is clearly visible and is the main subject.
- id=2 if a ball, round toy, or similar spherical play object is dominant.
- id=3 if another clear play object or toy is dominant (not face, not ball).
- id=0 if the image is too dark, blurry, empty, or unclear.

Example output: {"id":1}
"""


def _capture_url_from_env() -> str:
    raw = (os.environ.get("ESP32CAM_CAPTURE_URL") or "").strip()
    if raw:
        return raw.rstrip("/")
    host = (os.environ.get("ESP32CAM_HOST") or "").strip().rstrip("/")
    if not host:
        return ""
    if not host.lower().startswith("http"):
        host = "http://" + host
    return host + "/capture"


def fetch_jpeg(url: str, timeout_sec: float = 8.0) -> Optional[bytes]:
    req = Request(url, headers={"Accept": "image/jpeg"})
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read()
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        print("[CAM] fetch failed:", e)
        return None
    if not data or len(data) < 800:
        print("[CAM] JPEG prea scurt sau gol:", len(data or b""))
        return None
    if not data.startswith(b"\xff\xd8"):
        print("[CAM] nu pare JPEG (lipsește marker SOI)")
        return None
    return data


_ID_RE = re.compile(r'"id"\s*:\s*(\d+)', re.I)
_MATCH_RE = re.compile(r'"match"\s*:\s*(true|false)', re.I)
_SCORE_RE = re.compile(r'"match_score"\s*:\s*([0-9.]+)', re.I)
_DEFAULT_TRIGGER_TOPIC = "vision/capture_req"


def parse_model_id(text: str) -> Optional[int]:
    t = (text or "").strip()
    if not t:
        return None
    m = _ID_RE.search(t)
    if m:
        return int(m.group(1))
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            if isinstance(obj, dict) and "id" in obj:
                return int(obj["id"])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


def parse_model_verification(text: str) -> dict[str, object]:
    """Extrage id, match si match_score din raspunsul Gemini."""
    t = (text or "").strip()
    out: dict[str, object] = {}
    if not t:
        return out
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            if isinstance(obj, dict):
                if "id" in obj:
                    out["id"] = int(obj["id"])
                if "match" in obj:
                    out["match"] = bool(obj["match"])
                if "match_score" in obj:
                    out["match_score"] = float(obj["match_score"])
                return out
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    m = _ID_RE.search(t)
    if m:
        out["id"] = int(m.group(1))
    m = _MATCH_RE.search(t)
    if m:
        out["match"] = m.group(1).lower() == "true"
    m = _SCORE_RE.search(t)
    if m:
        try:
            out["match_score"] = float(m.group(1))
        except ValueError:
            pass
    return out


def _make_mqtt_client(client_id: str) -> mqtt_client.Client:
    try:
        return mqtt_client.Client(
            callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt_client.MQTTv311,
        )
    except (TypeError, AttributeError):
        try:
            return mqtt_client.Client(
                mqtt_client.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                protocol=mqtt_client.MQTTv311,
            )
        except AttributeError:
            return mqtt_client.Client(client_id=client_id, protocol=mqtt_client.MQTTv311)


def main() -> None:
    parser = argparse.ArgumentParser(description="ESP32-CAM JPEG -> Vertex vision -> MQTT vision/tags")
    parser.add_argument(
        "--interval",
        type=float,
        default=float((os.environ.get("VISION_CAM_INTERVAL_SEC") or "3.0").strip() or "3.0"),
        help="Secunde între capturi (implicit din VISION_CAM_INTERVAL_SEC sau 3).",
    )
    parser.add_argument("--once", action="store_true", help="O singură captură și ieșire.")
    parser.add_argument("--dry-run", action="store_true", help="Nu publică MQTT, doar afișează id-ul.")
    parser.add_argument(
        "--broker",
        default=os.environ.get("MQTT_BROKER", MQTT_BROKER),
        help="MQTT broker",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MQTT_PORT", MQTT_PORT)),
    )
    parser.add_argument(
        "--on-request",
        action="store_true",
        help="Captureaza doar la trigger MQTT (ex. buton LEFT pe Hub).",
    )
    parser.add_argument(
        "--trigger-topic",
        default=(os.environ.get("VISION_CAM_TRIGGER_TOPIC") or _DEFAULT_TRIGGER_TOPIC).strip(),
        help=f"Topic trigger captura (implicit {_DEFAULT_TRIGGER_TOPIC}).",
    )
    args = parser.parse_args()

    url = _capture_url_from_env()
    if not url:
        print(
            "[FATAL] Setează ESP32CAM_CAPTURE_URL (ex. http://192.168.1.70/capture) "
            "sau ESP32CAM_HOST=192.168.1.70 în .env",
        )
        sys.exit(2)

    publish_mode = (os.environ.get("VISION_CAM_PUBLISH_MODE") or "change_only").strip().lower()
    child = (os.environ.get("VISION_CAM_CHILD_NAME") or "").strip()
    prompt = (os.environ.get("VISION_CAM_PROMPT") or _DEFAULT_VISION_PROMPT).strip()
    client_id = (os.environ.get("ESP32CAM_MQTT_CLIENT_ID") or "TriSense_ESP32CAM_Bridge").strip()
    http_timeout = float((os.environ.get("ESP32CAM_HTTP_TIMEOUT_SEC") or "8").strip() or "8")

    from trisense.ai_client import TriSenseAI

    ai = TriSenseAI()
    if not ai.available:
        print("[FATAL] TriSenseAI indisponibil — verifică Vertex/cheie_google.json în .env.")
        sys.exit(3)

    print("[INIT] capture:", url)
    print("[INIT] MQTT:", args.broker, args.port, "topic", TOPIC_VISION_TAGS)
    print("[INIT] publish_mode:", publish_mode)
    if args.on_request:
        print("[INIT] trigger mode: on-request topic", args.trigger_topic)

    last_id: Optional[int] = None
    build_context: dict[str, object] = {}

    def loop_once(*, force_publish: bool = False) -> None:
        nonlocal last_id
        ctx = build_context if isinstance(build_context, dict) else {}
        use_build = bool(ctx.get("build_model"))
        active_prompt = prompt
        if use_build:
            desc = str(ctx.get("description") or ctx.get("pattern") or "LEGO build")
            active_prompt = build_model_verify_prompt(desc)
            print("[AI] build_model context level=", ctx.get("level"), "pattern=", ctx.get("pattern"))
        jpeg = fetch_jpeg(url, timeout_sec=http_timeout)
        if not jpeg:
            return
        reply = ai.reply_with_image_jpeg(jpeg, active_prompt, child, max_tokens=128)
        parsed = parse_model_verification(reply)
        vid = parsed.get("id")
        if vid is None:
            vid = parse_model_id(reply)
        print("[AI] raw:", (reply[:200] + "...") if len(reply) > 200 else reply)
        if vid is None:
            print("[AI] nu pot extrage id din răspuns")
            return
        vid_int = int(vid)
        if (
            not force_publish
            and publish_mode == "change_only"
            and not use_build
            and vid_int == last_id
        ):
            print("[MQTT] skip (același id=", vid_int, ")")
            return
        last_id = vid_int
        payload_obj: dict[str, object] = {"id": vid_int}
        if "match" in parsed:
            payload_obj["match"] = parsed["match"]
        if "match_score" in parsed:
            payload_obj["match_score"] = parsed["match_score"]
        if use_build:
            payload_obj["build_model"] = True
            if ctx.get("level") is not None:
                payload_obj["level"] = ctx.get("level")
            if ctx.get("pattern"):
                payload_obj["pattern"] = ctx.get("pattern")
        payload = json.dumps(payload_obj, separators=(",", ":"))
        if args.dry_run:
            print("[DRY] ar publica:", TOPIC_VISION_TAGS, payload)
            return
        mqtt_publish.single(
            TOPIC_VISION_TAGS,
            payload.encode("utf-8"),
            hostname=args.broker,
            port=args.port,
            client_id=client_id,
        )
        print("[MQTT]", TOPIC_VISION_TAGS, payload)

    def run_on_request_loop() -> None:
        trig = threading.Event()
        c = _make_mqtt_client(client_id + "_req")

        def _on_connect(client, userdata, flags, reason_code, properties=None):
            try:
                client.subscribe(args.trigger_topic, qos=0)
                client.subscribe(TOPIC_VISION_BUILD_CONTEXT, qos=0)
                print("[TRIGGER] subscribed:", args.trigger_topic, "+", TOPIC_VISION_BUILD_CONTEXT)
            except Exception as e:
                print("[TRIGGER] subscribe err:", e)

        def _on_message(client, userdata, msg):
            nonlocal build_context
            topic = msg.topic if isinstance(msg.topic, str) else msg.topic.decode("utf-8", errors="replace")
            if topic == TOPIC_VISION_BUILD_CONTEXT:
                try:
                    raw = msg.payload.decode("utf-8", errors="replace").strip()
                    if not raw or raw in ("{}", "null"):
                        build_context = {}
                        print("[CONTEXT] build_model cleared")
                        return
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and obj.get("build_model"):
                        build_context = obj
                        print("[CONTEXT] build_model level=", obj.get("level"), "pattern=", obj.get("pattern"))
                    else:
                        build_context = {}
                except Exception as e:
                    print("[CONTEXT] parse err:", e)
                return
            try:
                raw = msg.payload.decode("utf-8", errors="replace").strip()
                if not raw:
                    return
                obj = json.loads(raw)
                if isinstance(obj, dict) and (
                    obj.get("capture") is True
                    or str(obj.get("capture")).lower() in ("1", "true", "yes")
                ):
                    print("[TRIGGER] capture request:", raw[:180])
                    trig.set()
            except Exception:
                # Fallback: orice payload non-empty declanseaza captura.
                if msg.payload:
                    print("[TRIGGER] capture request (raw payload)")
                    trig.set()

        c.on_connect = _on_connect
        c.on_message = _on_message
        c.connect(args.broker, args.port, keepalive=30)
        c.loop_start()
        print("[TRIGGER] waiting... (Ctrl+C stop)")
        try:
            while True:
                trig.wait()
                trig.clear()
                loop_once(force_publish=True)
        finally:
            c.loop_stop()
            c.disconnect()

    try:
        if args.on_request:
            run_on_request_loop()
        else:
            while True:
                loop_once()
                if args.once:
                    break
                time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        print("\n[STOP]")


if __name__ == "__main__":
    main()
