# -*- coding: utf-8 -*-
"""
Jurnal metrici sesiune: CSV + JSONL + raport sumar pentru terapeut (3.10).
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from trisense.config import METRICS_CSV, METRICS_JSONL, SESSION_REPORTS_DIR

logger = logging.getLogger(__name__)

# Aliniat cu headerul deja folosit in trisense_metrics.csv (sesiuni mai vechi).
_CSV_HEADER = [
    "timestamp_iso",
    "session_id",
    "nume_copil",
    "activity",
    "id_vazut",
    "timp_reactie_ms",
    "stare",
    "extra_json",
]


class MetricsLogger:
    def __init__(
        self,
        csv_path: Optional[Path] = None,
        jsonl_path: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
    ) -> None:
        self.csv_path = csv_path or METRICS_CSV
        self.jsonl_path = jsonl_path or METRICS_JSONL
        self.reports_dir = reports_dir or SESSION_REPORTS_DIR
        self._session_id: str = ""
        self._session_start: float = 0.0
        self._child_name: str = ""
        self._session_events: list[dict[str, Any]] = []
        self._ensure_header()

    def _ensure_header(self) -> None:
        if self.csv_path.exists():
            return
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_CSV_HEADER)

    def start_session(self, child_name: str) -> str:
        self._session_id = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        self._session_start = time.time()
        self._child_name = (child_name or "friend").strip() or "friend"
        self._session_events = []
        logger.info("Metrics: session started id=%s child=%s", self._session_id, self._child_name)
        return self._session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def log(
        self,
        nume_copil: str,
        id_vazut: int,
        timp_reactie_ms: Optional[float],
        stare: str,
        extra: Optional[dict[str, Any]] = None,
        *,
        activity: str = "",
    ) -> None:
        extra = dict(extra or {})
        act = (activity or extra.get("activity") or stare or "").strip()
        if act and "activity" not in extra:
            extra["activity"] = act
        sid = self._session_id
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        record = {
            "timestamp_iso": ts,
            "session_id": sid,
            "nume_copil": nume_copil,
            "id_vazut": id_vazut,
            "timp_reactie_ms": timp_reactie_ms,
            "stare": stare,
            "activity": act,
            "extra": extra,
        }
        self._session_events.append(record)
        row = [
            ts,
            sid,
            nume_copil,
            act,
            id_vazut,
            "" if timp_reactie_ms is None else round(timp_reactie_ms, 2),
            stare,
            json.dumps(extra, ensure_ascii=False),
        ]
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        except OSError as e:
            logger.warning("Metrics CSV write failed: %s", e)
        self.append_jsonl(self.jsonl_path, record)

    def append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.warning("Metrics JSONL write failed: %s", e)

    @staticmethod
    def load_events_from_csv(
        csv_path: Path,
        *,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not csv_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = (row.get("session_id") or "").strip()
                if session_id and sid != session_id:
                    continue
                extra_raw = row.get("extra_json") or "{}"
                try:
                    extra = json.loads(extra_raw)
                except (json.JSONDecodeError, TypeError):
                    extra = {}
                react = row.get("timp_reactie_ms") or ""
                try:
                    react_ms = float(react) if str(react).strip() else None
                except ValueError:
                    react_ms = None
                events.append(
                    {
                        "timestamp_iso": row.get("timestamp_iso", ""),
                        "session_id": sid,
                        "nume_copil": row.get("nume_copil", ""),
                        "id_vazut": int(row.get("id_vazut") or 0),
                        "timp_reactie_ms": react_ms,
                        "stare": row.get("stare", ""),
                        "activity": (row.get("activity") or extra.get("activity") or "").strip(),
                        "extra": extra,
                    }
                )
        return events

    def build_session_summary(self, events: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        ev = events if events is not None else list(self._session_events)
        if not ev:
            return {}
        started = ev[0].get("timestamp_iso", "")
        ended = ev[-1].get("timestamp_iso", "")
        child = ev[0].get("nume_copil") or self._child_name or "friend"
        sid = (ev[0].get("session_id") or self._session_id or "").strip()
        duration_min = 0.0
        if self._session_start > 0:
            duration_min = round((time.time() - self._session_start) / 60.0, 1)

        activities: dict[str, dict[str, Any]] = {}
        reaction_samples: list[float] = []

        for e in ev:
            act = (e.get("activity") or e.get("stare") or "").strip() or "OTHER"
            bucket = activities.setdefault(
                act,
                {"events": 0, "trials": 0, "correct": 0, "incorrect": 0},
            )
            bucket["events"] += 1
            extra = e.get("extra") or {}
            if isinstance(extra, dict):
                if extra.get("trial") is not None or extra.get("step_ok") is not None:
                    bucket["trials"] += 1
                if extra.get("correct") is True or extra.get("step_ok") is True:
                    bucket["correct"] += 1
                elif extra.get("correct") is False or extra.get("step_ok") is False:
                    bucket["incorrect"] += 1
                if extra.get("false_alarm"):
                    bucket.setdefault("false_alarms", 0)
                    bucket["false_alarms"] += 1
                if extra.get("valid_count") is not None:
                    bucket["valid_words_total"] = bucket.get("valid_words_total", 0) + int(
                        extra.get("valid_count") or 0
                    )
            react = e.get("timp_reactie_ms")
            if isinstance(react, (int, float)):
                reaction_samples.append(float(react))

        for act, bucket in activities.items():
            trials = bucket.get("trials", 0)
            correct = bucket.get("correct", 0)
            if trials > 0:
                bucket["success_rate"] = round(correct / trials, 2)

        return {
            "session_id": sid,
            "child_name": child,
            "started_at_iso": started,
            "ended_at_iso": ended,
            "duration_minutes": duration_min,
            "total_events": len(ev),
            "activities": activities,
            "overall": {
                "avg_reaction_ms": (
                    round(sum(reaction_samples) / len(reaction_samples), 1)
                    if reaction_samples
                    else None
                ),
                "games_played": sorted(activities.keys()),
            },
        }

    def format_report_text(self, summary: dict[str, Any]) -> str:
        if not summary:
            return "No session data."
        lines = [
            "TriSense — Session Report (therapeutic support, not clinical diagnosis)",
            "=" * 60,
            f"Session ID:    {summary.get('session_id', '')}",
            f"Child:         {summary.get('child_name', '')}",
            f"Started:       {summary.get('started_at_iso', '')}",
            f"Ended:         {summary.get('ended_at_iso', '')}",
            f"Duration:      {summary.get('duration_minutes', 0)} min",
            f"Total events:  {summary.get('total_events', 0)}",
            "",
            f"Games / activities: {', '.join(summary.get('overall', {}).get('games_played', []))}",
            "",
            "Per activity:",
            "-" * 40,
        ]
        for act, bucket in (summary.get("activities") or {}).items():
            parts = [f"  {act}:"]
            if bucket.get("trials"):
                rate = bucket.get("success_rate")
                rate_txt = f"{int(rate * 100)}%" if isinstance(rate, (int, float)) else "n/a"
                parts.append(f" {bucket.get('correct', 0)}/{bucket.get('trials', 0)} correct ({rate_txt})")
            if bucket.get("valid_words_total") is not None:
                parts.append(f" valid_words={bucket['valid_words_total']}")
            if bucket.get("false_alarms"):
                parts.append(f" false_alarms={bucket['false_alarms']}")
            if len(parts) == 1:
                parts.append(f" events={bucket.get('events', 0)}")
            lines.append("".join(parts))
        lines.extend(
            [
                "",
                "Note: metrics support guided play sessions; not a validated clinical test.",
            ]
        )
        return "\n".join(lines)

    def write_session_report(self, summary: dict[str, Any]) -> Optional[Path]:
        if not summary:
            return None
        sid = (summary.get("session_id") or self._session_id or time.strftime("%Y%m%d-%H%M%S")).strip()
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        txt_path = self.reports_dir / f"report_{sid}.txt"
        json_path = self.reports_dir / f"report_{sid}.json"
        try:
            txt_path.write_text(self.format_report_text(summary), encoding="utf-8")
            json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Session report written: %s", txt_path)
            return txt_path
        except OSError as e:
            logger.warning("Session report write failed: %s", e)
            return None

    def end_session(self) -> Optional[Path]:
        if not self._session_events:
            logger.info("Metrics: end_session skipped (no events).")
            return None
        summary = self.build_session_summary()
        path = self.write_session_report(summary)
        self._session_id = ""
        self._session_start = 0.0
        self._session_events = []
        return path
