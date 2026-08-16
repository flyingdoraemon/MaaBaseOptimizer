"""Validated local persistence for the user's operator roster."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def normalize_roster(value: Any, catalog: dict) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("干员列表必须是数组")
    result: list[dict] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        op_id = str(raw.get("id") or "")
        definition = catalog["operators"].get(op_id)
        if not definition or op_id in seen:
            continue
        seen.add(op_id)
        result.append({
            "id": op_id,
            "name": definition["name"],
            "elite": max(0, min(2, int(raw.get("elite", raw.get("phase", 0)) or 0))),
            "level": max(1, min(90, int(raw.get("level", 1) or 1))),
            "potential": max(1, min(6, int(raw.get("potential", 1) or 1))),
        })
    return result


def load_roster(path: Path, catalog: dict) -> list[dict]:
    if not path.is_file():
        return []
    try:
        return normalize_roster(json.loads(path.read_text(encoding="utf-8")), catalog)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def save_roster(path: Path, roster: Any, catalog: dict) -> list[dict]:
    normalized = normalize_roster(roster, catalog)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return normalized
