# -*- coding: utf-8 -*-
"""
Genereaza raport sesiune terapeut din trisense_metrics.csv (3.10).

Rulare:
  py testare/session_report.py
  py testare/session_report.py --session 20260526-013045
  py testare/session_report.py --latest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trisense.config import METRICS_CSV, SESSION_REPORTS_DIR
from trisense.metrics_logger import MetricsLogger


def _latest_session_id(csv_path: Path) -> str:
    events = MetricsLogger.load_events_from_csv(csv_path)
    for e in reversed(events):
        sid = (e.get("session_id") or "").strip()
        if sid:
            return sid
    return ""


def main() -> None:
    p = argparse.ArgumentParser(description="TriSense session report for therapist")
    p.add_argument("--session", "-s", help="session_id (ex. 20260526-013045)")
    p.add_argument("--latest", "-l", action="store_true", help="ultima sesiune din CSV")
    p.add_argument("--csv", default=str(METRICS_CSV), help="cale CSV metrici")
    args = p.parse_args()

    csv_path = Path(args.csv)
    sid = (args.session or "").strip()
    if args.latest or not sid:
        sid = _latest_session_id(csv_path)
    if not sid:
        print("[ERR] Niciun session_id in CSV. Ruleaza intai py run_voice_dialog.py si joaca.")
        sys.exit(1)

    events = MetricsLogger.load_events_from_csv(csv_path, session_id=sid)
    if not events:
        print(f"[ERR] Zero evenimente pentru session_id={sid}")
        sys.exit(1)

    ml = MetricsLogger(reports_dir=SESSION_REPORTS_DIR)
    ml._session_id = sid
    ml._child_name = events[0].get("nume_copil") or "friend"
    ml._session_events = events
    summary = ml.build_session_summary(events)
    path = ml.write_session_report(summary)
    if not path:
        print("[ERR] Nu am putut scrie raportul.")
        sys.exit(1)

    print(ml.format_report_text(summary))
    print()
    print(f"[OK] Raport salvat: {path}")
    print(f"     JSON: {path.with_suffix('.json')}")


if __name__ == "__main__":
    main()
