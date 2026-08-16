"""Build a room-centric, collection-aligned two-team RIIC schedule."""

from __future__ import annotations

import heapq
import math
import re


def _morale_rates(room: dict) -> dict[str, float]:
    operators = room.get("operators", [])
    details = room.get("details", [])
    count = len(operators)
    if room.get("key") in {"trade", "orundum", "gold", "exp", "shard"}:
        base = 1.0 - 0.05 * max(0, count - 1)
    elif room.get("key") == "control":
        base = 1.0 - 0.05 * count
    else:
        base = 1.0
    group_delta = 0.0
    for detail in details:
        for skill in detail.get("skills", []):
            text = str(skill.get("description") or "")
            if "内干员心情每小时消耗" not in text:
                continue
            for sign, value in re.findall(r"心情每小时消耗([+-])([0-9.]+)", text):
                group_delta += float(value) * (1 if sign == "+" else -1)
    rates = {}
    for operator_id, detail in zip(operators, details):
        delta = group_delta
        for skill in detail.get("skills", []):
            text = str(skill.get("description") or "")
            if "内干员心情每小时消耗" in text:
                continue
            for sign, value in re.findall(r"心情每小时消耗([+-])([0-9.]+)", text):
                delta += float(value) * (1 if sign == "+" else -1)
        rates[operator_id] = round(max(0.0, base + delta), 3)
    return rates


def _all_rooms(team: dict) -> list[dict]:
    return [*(team.get("support_rooms") or []), *(team.get("rooms") or [])]


def _team_duration(team: dict, collection_hours: float, morale_floor: float, max_work_hours: float) -> float:
    """Find the latest collection event before a worker reaches the floor."""
    rates = [rate for room in _all_rooms(team) for rate in _morale_rates(room).values() if rate > 0]
    fatigue_limit = min(((24.0 - morale_floor) / rate for rate in rates), default=max_work_hours)
    safe = min(max_work_hours, fatigue_limit)
    aligned = math.floor((safe + 1e-9) / collection_hours) * collection_hours
    return round(aligned if aligned > 0 else max(1.0, safe), 3)


def _average_metrics(a: dict, b: dict, a_hours: float = 1.0, b_hours: float = 1.0) -> dict:
    keys = {
        "lmd_per_day", "lmd_shard_cost_per_day", "lmd_net_after_shards_per_day",
        "exp_per_day", "orundum_per_day", "shards_made_per_day", "shards_used_per_day",
        "shards_net_per_day", "shard_material_used_per_day", "gold_made_per_day",
        "gold_used_per_day", "gold_production_net_per_day", "gold_external_per_day",
        "gold_net_per_day", "drones_per_day", "drone_hours_per_day", "power_bonus",
    }
    total = max(1e-9, a_hours + b_hours)
    result = dict(a)
    for key in keys:
        if isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float)):
            result[key] = round((float(a[key]) * a_hours + float(b[key]) * b_hours) / total, 2)
    result["drone_target"] = "A/B 两套排班按实际在岗时长加权"
    net = float(result.get("gold_net_per_day", 0))
    inventory = float(a.get("gold_inventory", 0))
    result["gold_inventory"] = inventory
    result["gold_inventory_days"] = None if net >= 0 else round(inventory / -net, 1)
    return result


def build_rotation(
    team_a: dict,
    team_b: dict,
    shift_hours: float,
    *,
    schedule_mode: str = "fixed",
    collection_interval_hours: float | None = None,
    morale_floor: float = 1.0,
    max_work_hours: float | None = None,
    horizon_hours: float = 48.0,
) -> dict:
    """Build a two-team schedule and a room-centric event timeline.

    In morale-aware mode, each team works until the latest collection event
    before either its morale floor or continuous-work cap.
    """
    requested = max(1.0, min(24.0, float(shift_hours)))
    collection = max(1.0, min(24.0, float(collection_interval_hours or requested)))
    maximum = max(1.0, min(36.0, float(max_work_hours or requested)))
    floor = max(0.0, min(23.0, float(morale_floor)))
    horizon = max(24.0, min(168.0, float(horizon_hours)))
    teams = {"A": team_a, "B": team_b}
    if schedule_mode == "morale_aware":
        durations = {label: _team_duration(team, collection, floor, maximum) for label, team in teams.items()}
    else:
        if requested not in {8.0, 12.0}:
            raise ValueError("固定轮班目前支持 8 小时或 12 小时")
        durations = {"A": requested, "B": requested}

    shifts = []
    operator_rows: dict[str, dict] = {}
    room_rows: dict[str, dict] = {}
    worked_hours = {"A": 0.0, "B": 0.0}
    elapsed = 0.0
    index = 0
    while elapsed < horizon - 1e-9:
        label = "A" if index % 2 == 0 else "B"
        start = elapsed
        end = min(horizon, start + durations[label])
        worked_hours[label] += end - start
        shift_rooms = []
        for room in _all_rooms(teams[label]):
            rates = _morale_rates(room)
            phases = [{
                **profile,
                "phases": [{**phase, "start": start + phase["start_hour"], "end": min(end, start + phase["end_hour"])}
                           for phase in profile.get("phases", []) if start + phase["start_hour"] < end],
            } for profile in room.get("time_profiles", [])]
            min_end = min((24.0 - rates.get(op, 1.0) * (end - start) for op in room.get("operators", [])), default=24.0)
            event = {
                "type": "work", "team": label, "room": room["room"], "key": room.get("key"),
                "start": start, "end": end, "names": room.get("names", []),
                "operators": room.get("operators", []), "details": room.get("details", []),
                "efficiency": room.get("efficiency", 0), "time_profiles": phases,
                "morale_min_end": round(max(0.0, min_end), 2),
            }
            shift_rooms.append(event)
            room_rows.setdefault(room["room"], {"room": room["room"], "key": room.get("key"), "events": []})["events"].append(event)
            for operator_id, name in zip(room.get("operators", []), room.get("names", [])):
                operator_rows.setdefault(operator_id, {"id": operator_id, "name": name})
        shifts.append({"index": index + 1, "team": label, "start": start, "end": end, "rooms": shift_rooms})
        elapsed = end
        index += 1

    feasible = True
    recovery_audit = {}
    for label, other in (("A", "B"), ("B", "A")):
        rates = [rate for room in _all_rooms(teams[label]) for rate in _morale_rates(room).values()]
        recovery_hours = max((rate * durations[label] / 4.0 for rate in rates), default=0.0)
        load = sum(rate * durations[label] / 4.0 for rate in rates)
        available = 20.0 * durations[other]
        ok = recovery_hours <= durations[other] + 1e-9 and load <= available + 1e-9
        feasible = feasible and ok
        recovery_audit[label] = {"work_hours": durations[label], "rest_hours": durations[other],
                                 "slowest_recovery_hours": round(recovery_hours, 2),
                                 "bed_hours_required": round(load, 2), "bed_hours_available": round(available, 2),
                                 "feasible": ok}

    room_order = {"control": 0, "trade": 1, "orundum": 2, "gold": 3, "exp": 4,
                  "shard": 5, "power": 6, "reception": 7, "office": 8}
    rooms = sorted(room_rows.values(), key=lambda row: (room_order.get(row.get("key"), 99), row["room"]))
    return {
        "cycle_hours": horizon, "shift_hours": requested, "schedule_mode": schedule_mode,
        "collection_interval_hours": collection, "morale_floor": floor, "team_work_hours": durations,
        "pattern": [shift["team"] for shift in shifts], "shifts": shifts, "rooms": rooms,
        "operators": list(operator_rows.values()),
        "teams": {
            "A": {"rooms": team_a.get("rooms", []), "support_rooms": team_a.get("support_rooms", []), "metrics": team_a["metrics"]},
            "B": {"rooms": team_b.get("rooms", []), "support_rooms": team_b.get("support_rooms", []), "metrics": team_b["metrics"]},
        },
        "average_metrics": _average_metrics(team_a["metrics"], team_b["metrics"], worked_hours["A"], worked_hours["B"]),
        "morale": {
            "feasible": feasible, "beds": 20, "base_recovery_per_hour": 4.0, "teams": recovery_audit,
            "note": (f"换班仅落在每 {collection:g} 小时统一收取节点；每队尽量工作至心情 {floor:g} 前，"
                     f"且连续在岗不超过 {maximum:g} 小时。按满级满氛围宿舍基础恢复 4/小时审计，未把宿舍技能当作必需条件。"
                     if schedule_mode == "morale_aware" else
                     "固定时长轮班；按满级满氛围宿舍基础恢复 4/小时审计，未把宿舍技能当作必需条件。"),
        },
        "inventory_policy": {
            "mode": "working_stock", "collection_interval_hours": collection,
            "note": "制造站与贸易站在同一收取节点结算；产出期望默认已有足够周转库存，不从零库存强制串行启动。",
        },
    }
