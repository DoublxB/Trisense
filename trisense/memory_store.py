# -*- coding: utf-8 -*-
"""
Memorie persistenta pentru numele copilului (JSON).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from trisense.config import MEMORY_FILE


class MemoryStore:
    """Gestioneaza memorie_copil.json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or MEMORY_FILE

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_child_name(self) -> Optional[str]:
        data = self.load()
        name = data.get("nume_copil") or data.get("nume")
        if name and str(name).strip():
            return str(name).strip()
        return None

    def set_child_name(self, name: str) -> None:
        data = self.load()
        data["nume_copil"] = name.strip()
        self.save(data)
