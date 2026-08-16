"""Import MAA OperBox callback data and simple user roster formats."""

from __future__ import annotations

from typing import Any


def _find_own_opers(value: Any) -> list[dict] | None:
    if isinstance(value, dict):
        if isinstance(value.get("own_opers"), list):
            return value["own_opers"]
        for key in ("details", "data", "result", "payload"):
            found = _find_own_opers(value.get(key))
            if found is not None:
                return found
        for child in value.values():
            found = _find_own_opers(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        if value and all(isinstance(x, dict) and ("id" in x or "name" in x) for x in value):
            return value
        for child in value:
            found = _find_own_opers(child)
            if found is not None:
                return found
    return None


def parse_roster(payload: Any, catalog: dict) -> tuple[list[dict], list[str]]:
    source = _find_own_opers(payload)
    if source is None:
        raise ValueError("没有找到 MAA OperBox 的 own_opers 数组")
    by_name = {op["name"]: op_id for op_id, op in catalog["operators"].items()}
    roster: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for raw in source:
        if raw.get("own") is False:
            continue
        op_id = str(raw.get("id") or "")
        if op_id not in catalog["operators"]:
            op_id = by_name.get(str(raw.get("name") or ""), "")
        if not op_id or op_id in seen:
            if raw.get("name"):
                warnings.append(f"未在当前技能数据中匹配：{raw['name']}")
            continue
        seen.add(op_id)
        roster.append({
            "id": op_id,
            "name": catalog["operators"][op_id]["name"],
            "elite": max(0, min(2, int(raw.get("elite", raw.get("phase", 0)) or 0))),
            "level": max(1, int(raw.get("level", 1) or 1)),
            "potential": max(1, int(raw.get("potential", 1) or 1)),
        })
    return roster, warnings

