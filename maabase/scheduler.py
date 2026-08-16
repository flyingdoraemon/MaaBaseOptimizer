"""Build a room-centric, collection-aligned two-team RIIC schedule."""

from __future__ import annotations

import math
import re


BASE_RECOVERY_PER_HOUR = 4.0


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


def _duration_options(team: dict, collection_hours: float, morale_floor: float, max_work_hours: float) -> list[float]:
    """Return collection-aligned work durations that do not cross the morale floor."""
    limit = _team_duration(team, collection_hours, morale_floor, max_work_hours)
    options = [
        round(collection_hours * index, 3)
        for index in range(1, int(math.floor((limit + 1e-9) / collection_hours)) + 1)
    ]
    return options or [limit]


def _recovery_audit(team: dict, work_hours: float, rest_hours: float, dorm_helper: dict | None) -> dict:
    """Audit one team's recovery with a persistent helper occupying one dorm bed.

    An all-dorm recovery skill affects the other four beds in that dorm.  The
    four workers with the largest recovery demand are assigned there; all other
    workers use ordinary max-level beds and may leave as soon as they are full.
    """
    rates = [rate for room in _all_rooms(team) for rate in _morale_rates(room).values()]
    spent = sorted((rate * work_hours for rate in rates), reverse=True)
    all_bonus = max(0.0, float((dorm_helper or {}).get("all", 0) or 0))
    boosted_slots = min(4, len(spent)) if dorm_helper and all_bonus > 0 else 0
    recovery_times = [
        value / (BASE_RECOVERY_PER_HOUR + (all_bonus if index < boosted_slots else 0.0))
        for index, value in enumerate(spent)
    ]
    beds = 19 if dorm_helper else 20
    required = sum(recovery_times)
    slowest = max(recovery_times, default=0.0)
    available = beds * rest_hours
    return {
        "work_hours": round(work_hours, 3),
        "rest_hours": round(rest_hours, 3),
        "slowest_recovery_hours": round(slowest, 3),
        "bed_hours_required": round(required, 3),
        "bed_hours_available": round(available, 3),
        "ordinary_beds": beds - boosted_slots,
        "boosted_beds": boosted_slots,
        "boosted_recovery_per_hour": round(BASE_RECOVERY_PER_HOUR + all_bonus, 3),
        "feasible": slowest <= rest_hours + 1e-9 and required <= available + 1e-9,
    }


def _production_score(team: dict) -> float:
    """A transparent, scale-balanced score used only to allocate A/B work time."""
    metrics = team.get("metrics") or {}
    return (
        float(metrics.get("lmd_per_day", 0) or 0) / 10_000.0
        + float(metrics.get("exp_per_day", 0) or 0) / 10_000.0
        + float(metrics.get("orundum_per_day", 0) or 0) / 240.0
        + max(0.0, float(metrics.get("gold_made_per_day", 0) or 0)) / 40.0
    )


def _choose_durations(
    team_a: dict,
    team_b: dict,
    collection: float,
    floor: float,
    maximum: float,
    dorm_helper: dict | None,
) -> tuple[dict[str, float], str]:
    """Choose a sustainable unequal cycle so the stronger team works longer."""
    options = {
        "A": _duration_options(team_a, collection, floor, maximum),
        "B": _duration_options(team_b, collection, floor, maximum),
    }
    scores = {"A": _production_score(team_a), "B": _production_score(team_b)}
    best: tuple[float, float, float, float] | None = None
    for a_hours in options["A"]:
        for b_hours in options["B"]:
            audit_a = _recovery_audit(team_a, a_hours, b_hours, dorm_helper)
            audit_b = _recovery_audit(team_b, b_hours, a_hours, dorm_helper)
            if not (audit_a["feasible"] and audit_b["feasible"]):
                continue
            cycle = a_hours + b_hours
            weighted = (scores["A"] * a_hours + scores["B"] * b_hours) / cycle
            # Prefer a 24-hour operational cycle when its yield is effectively
            # tied, then prefer a longer cycle to reduce handover frequency.
            tie = -abs(cycle - 24.0) / 100_000.0 + cycle / 10_000_000.0
            candidate = (weighted + tie, cycle, a_hours, b_hours)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        fallback = {
            "A": _team_duration(team_a, collection, floor, maximum),
            "B": _team_duration(team_b, collection, floor, maximum),
        }
        return fallback, "没有找到可持续的不等长组合，退回各队心情上限"
    durations = {"A": best[2], "B": best[3]}
    return durations, (
        f"在收取节点上枚举 {len(options['A']) * len(options['B'])} 组班长，"
        f"按综合产出让较强班组承担更多工时"
    )


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


def _instant_multiplier(room: dict, elapsed_hours: float) -> float:
    profiles = room.get("time_profiles") or []
    if not profiles:
        return float(room.get("multiplier", 1.0) or 1.0)
    efficiency = float(room.get("efficiency", 0) or 0)
    for profile in profiles:
        efficiency -= float(profile.get("average_percent", 0) or 0)
        phases = profile.get("phases") or []
        phase = next((item for item in phases if float(item["start_hour"]) <= elapsed_hours < float(item["end_hour"])), None)
        if phase is None and phases and elapsed_hours >= float(phases[-1]["end_hour"]):
            phase = phases[-1]
        efficiency += float((phase or {}).get("value_percent", 0) or 0)
    return 1.0 + (len(room.get("operators") or []) + efficiency) / 100.0


def _room_output_ratio(rooms: list[dict], elapsed_hours: float, value) -> float:
    average = 0.0
    current = 0.0
    for room in rooms:
        output = float(value(room) or 0)
        if output == 0:
            continue
        multiplier = max(1e-9, float(room.get("multiplier", 1.0) or 1.0))
        average += output
        current += output / multiplier * _instant_multiplier(room, elapsed_hours)
    return current / average if abs(average) > 1e-9 else 1.0


def _instant_rates(team: dict, elapsed_hours: float) -> dict[str, float]:
    metrics = team.get("metrics") or {}
    rooms = team.get("rooms") or []
    rates = {
        key: float(metrics.get(key, 0) or 0) / 24.0
        for key in (
            "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
            "gold_net_per_day", "orundum_per_day", "shards_net_per_day", "drones_per_day",
        )
    }
    trade = [room for room in rooms if room.get("key") == "trade"]
    gold = [room for room in rooms if room.get("key") == "gold"]
    exp = [room for room in rooms if room.get("key") == "exp"]
    shard = [room for room in rooms if room.get("key") == "shard"]
    orundum = [room for room in rooms if room.get("key") == "orundum"]
    rates["lmd_per_day"] *= _room_output_ratio(
        trade, elapsed_hours, lambda room: (room.get("trade") or {}).get("lmd_per_day", 0)
    )
    rates["gold_used_per_day"] *= _room_output_ratio(
        trade, elapsed_hours, lambda room: (room.get("trade") or {}).get("gold_per_day", 0)
    )
    rates["gold_made_per_day"] *= _room_output_ratio(
        gold, elapsed_hours, lambda room: room.get("multiplier", 0)
    )
    rates["exp_per_day"] *= _room_output_ratio(
        exp, elapsed_hours, lambda room: room.get("multiplier", 0)
    )
    rates["orundum_per_day"] *= _room_output_ratio(
        orundum, elapsed_hours, lambda room: (room.get("orundum") or {}).get("orundum_per_day", 0)
    )
    shards_made = float(metrics.get("shards_made_per_day", 0) or 0) / 24.0
    shards_used = float(metrics.get("shards_used_per_day", 0) or 0) / 24.0
    shards_made *= _room_output_ratio(shard, elapsed_hours, lambda room: room.get("multiplier", 0))
    shards_used *= _room_output_ratio(
        orundum, elapsed_hours, lambda room: (room.get("orundum") or {}).get("shards_per_day", 0)
    )
    rates["shards_net_per_day"] = shards_made - shards_used
    external_gold = (
        float(metrics.get("gold_net_per_day", 0) or 0)
        - float(metrics.get("gold_made_per_day", 0) or 0)
        + float(metrics.get("gold_used_per_day", 0) or 0)
    ) / 24.0
    rates["gold_net_per_day"] = rates["gold_made_per_day"] - rates["gold_used_per_day"] + external_gold
    return rates


def _production_curve(teams: dict[str, dict], durations: dict[str, float], minutes: int = 1440) -> dict:
    """Create a 24-hour expected-rate and cumulative-yield curve."""
    metric_keys = (
        "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
        "gold_net_per_day", "orundum_per_day", "shards_net_per_day", "drones_per_day",
    )
    cycle = durations["A"] + durations["B"]

    def active_team(hour: float) -> tuple[str, float]:
        within = hour % cycle
        return ("A", within) if within < durations["A"] - 1e-9 else ("B", within - durations["A"])

    cumulative = {key: 0.0 for key in metric_keys}
    points = []
    step = 15
    for minute in range(0, minutes + 1, step):
        label, elapsed_hours = active_team(
            minute / 60.0 if minute < minutes else max(0.0, (minute - 1e-6) / 60.0)
        )
        rates = _instant_rates(teams[label], elapsed_hours)
        points.append({
            "minute": minute,
            "team": label,
            "rates_per_hour": {key: round(value, 6) for key, value in rates.items()},
            "cumulative": {key: round(value, 6) for key, value in cumulative.items()},
        })
        if minute < minutes:
            for key, value in rates.items():
                cumulative[key] += value * step / 60.0
    return {
        "hours": minutes / 60.0,
        "step_minutes": step,
        "points": points,
        "metrics": list(metric_keys),
        "note": "曲线按当前班组每 15 分钟积分；班次边界切换速率，芬/克洛丝等整点阶段技能也按当时档位改变斜率。",
    }


def build_rotation(
    team_a: dict,
    team_b: dict,
    shift_hours: float,
    *,
    schedule_mode: str = "fixed",
    collection_interval_hours: float | None = None,
    morale_floor: float = 1.0,
    max_work_hours: float | None = None,
    horizon_hours: float | None = None,
    dorm_helper: dict | None = None,
) -> dict:
    """Build a two-team schedule and a room-centric event timeline.

    In morale-aware mode, each team works until the latest collection event
    before either its morale floor or continuous-work cap.
    """
    requested = max(1.0, min(24.0, float(shift_hours)))
    collection = max(1.0, min(24.0, float(collection_interval_hours or requested)))
    maximum = max(1.0, min(36.0, float(max_work_hours or requested)))
    floor = max(0.0, min(23.0, float(morale_floor)))
    teams = {"A": team_a, "B": team_b}
    if schedule_mode == "morale_aware":
        durations, duration_reason = _choose_durations(team_a, team_b, collection, floor, maximum, dorm_helper)
    else:
        if requested not in {8.0, 12.0}:
            raise ValueError("固定轮班目前支持 8 小时或 12 小时")
        durations = {"A": requested, "B": requested}
        duration_reason = "固定等长对照班次"

    # Show one unique A→B cycle.  A 12h / B 12h therefore appears once each,
    # instead of repeating the same assignment merely to fill a 48h canvas.
    natural_cycle = durations["A"] + durations["B"]
    horizon = natural_cycle if horizon_hours is None else max(1.0, min(168.0, float(horizon_hours)))

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

    recovery_audit = {
        "A": _recovery_audit(team_a, durations["A"], durations["B"], dorm_helper),
        "B": _recovery_audit(team_b, durations["B"], durations["A"], dorm_helper),
    }
    feasible = all(audit["feasible"] for audit in recovery_audit.values())

    room_order = {"control": 0, "trade": 1, "orundum": 2, "gold": 3, "exp": 4,
                  "shard": 5, "power": 6, "reception": 7, "office": 8}
    rooms = sorted(room_rows.values(), key=lambda row: (room_order.get(row.get("key"), 99), row["room"]))
    return {
        "cycle_hours": horizon, "natural_cycle_hours": natural_cycle, "shift_hours": requested, "schedule_mode": schedule_mode,
        "collection_interval_hours": collection, "morale_floor": floor, "team_work_hours": durations,
        "duration_reason": duration_reason,
        "pattern": [shift["team"] for shift in shifts], "shifts": shifts, "rooms": rooms,
        "operators": list(operator_rows.values()),
        "teams": {
            "A": {"rooms": team_a.get("rooms", []), "support_rooms": team_a.get("support_rooms", []), "metrics": team_a["metrics"]},
            "B": {"rooms": team_b.get("rooms", []), "support_rooms": team_b.get("support_rooms", []), "metrics": team_b["metrics"]},
        },
        "average_metrics": _average_metrics(team_a["metrics"], team_b["metrics"], worked_hours["A"], worked_hours["B"]),
        "production_curve": _production_curve(teams, durations),
        "dormitory": {
            "locked_helper": dorm_helper,
            "note": (f"固定 {dorm_helper['name']} 驻一间宿舍；占用 1 个床位，并使同宿舍其余 4 个床位恢复 +{dorm_helper.get('all', 0):g}/小时。"
                     if dorm_helper else "未锁定宿舍恢复干员。"),
        },
        "morale": {
            "feasible": feasible, "beds": 19 if dorm_helper else 20,
            "base_recovery_per_hour": BASE_RECOVERY_PER_HOUR, "teams": recovery_audit,
            "note": (f"换班仅落在每 {collection:g} 小时统一收取节点；每队尽量工作至心情 {floor:g} 前，"
                     f"且连续在岗不超过 {maximum:g} 小时。{duration_reason}。{(dorm_helper or {}).get('name', '未锁定干员')}"
                     f"{' 驻宿舍并计入恢复' if dorm_helper else '；仅使用基础恢复'}。"
                     if schedule_mode == "morale_aware" else
                     "固定时长轮班；按满级满氛围宿舍恢复能力审计。"),
        },
        "inventory_policy": {
            "mode": "working_stock", "collection_interval_hours": collection,
            "note": "制造站与贸易站在同一收取节点结算；产出期望默认已有足够周转库存，不从零库存强制串行启动。",
        },
    }
