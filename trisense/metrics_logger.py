# -*- coding: utf-8 -*-
"""
Jurnal metrici: timestamp, nume copil, id vazut, timp reactie (ms).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Optional

from trisense.config import METRICS_CSV


class MetricsLogger:
    def __init__(self, csv_path: Optional[Path] = None) -> None:
        self.csv_path = csv_path or METRICS_CSV
        self._ensure_header()

    def _ensure_header(self) -> None:
        if self.csv_path.exists():
            return
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                ["timestamp_iso", "nume_copil", "id_vazut", "timp_reactie_ms", "stare", "extra_json"]
            )

    def log(
        self,
        nume_copil: str,
        id_vazut: int,
        timp_reactie_ms: Optional[float],
        stare: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        row = [
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            nume_copil,
            id_vazut,
            "" if timp_reactie_ms is None else round(timp_reactie_ms, 2),
            stare,
            json.dumps(extra or {}, ensure_ascii=False),
        ]
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        except OSError:
            pass

    def append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        """Alternativa: o linie JSON per eveniment."""
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
