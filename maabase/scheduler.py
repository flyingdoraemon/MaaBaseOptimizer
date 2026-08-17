"""Build a room-centric, collection-aligned two-team RIIC schedule."""

from __future__ import annotations

import math
import re

from .valuation import candidate_daily_value, metrics_daily_value, metrics_layout_score


BASE_RECOVERY_PER_HOUR = 4.0
DRONE_CAPACITY = 235.0


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


def _recovery_audit(
    team: dict, work_hours: float, rest_hours: float, dorm_helper: dict | None,
    fiammetta: dict | None = None,
) -> dict:
    """Audit one team's recovery with a persistent helper occupying one dorm bed.

    An all-dorm recovery skill affects the other four beds in that dorm.  The
    four workers with the largest recovery demand are assigned there; all other
    workers use ordinary max-level beds and may leave as soon as they are full.
    """
    instant_target = str((fiammetta or {}).get("target_operator_id") or "") if (fiammetta or {}).get("active") else ""
    rates = [
        rate for room in _all_rooms(team) for operator_id, rate in _morale_rates(room).items()
        if operator_id != instant_target
    ]
    spent = sorted((rate * work_hours for rate in rates), reverse=True)
    all_bonus = max(0.0, float((dorm_helper or {}).get("all", 0) or 0))
    boosted_slots = min(4, len(spent)) if dorm_helper and all_bonus > 0 else 0
    recovery_times = [
        value / (BASE_RECOVERY_PER_HOUR + (all_bonus if index < boosted_slots else 0.0))
        for index, value in enumerate(spent)
    ]
    reserved_beds = int(bool(dorm_helper)) + int(bool((fiammetta or {}).get("enabled")))
    beds = 20 - reserved_beds
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


def _operator_morale_rate(team: dict, operator_id: str) -> float:
    return next(
        (rates[operator_id] for room in _all_rooms(team) if operator_id in (rates := _morale_rates(room))),
        0.0,
    )


def _fiammetta_audit(
    team_a: dict, team_b: dict, durations: dict[str, float], fiammetta: dict | None,
) -> dict:
    if not (fiammetta or {}).get("active"):
        return {"active": False, "feasible": True}
    target_id = str(fiammetta["target_operator_id"])
    spent_a = _operator_morale_rate(team_a, target_id) * durations["A"]
    spent_b = _operator_morale_rate(team_b, target_id) * durations["B"]
    # Self-recovery is max-dorm 4/h plus Fiammetta's isolated +2/h.  After a
    # swap she inherits the target's ending morale, so her missing morale is
    # exactly what the target spent in the preceding shift.
    recovery_rate = 6.0
    recover_after_a = spent_a / recovery_rate
    recover_after_b = spent_b / recovery_rate
    feasible = recover_after_a <= durations["B"] + 1e-9 and recover_after_b <= durations["A"] + 1e-9
    return {
        "active": True,
        "target_operator_id": target_id,
        "target_operator_name": fiammetta.get("target_operator_name"),
        "self_recovery_per_hour": recovery_rate,
        "target_spent_in_a": round(spent_a, 3),
        "target_spent_in_b": round(spent_b, 3),
        "recover_during_b_hours": round(recover_after_a, 3),
        "recover_during_a_hours": round(recover_after_b, 3),
        "feasible": feasible,
    }


def _production_score(team: dict, objective_mode: str) -> float:
    """Value a complete shift in the same unit used by assignment search."""
    metrics = team.get("metrics") or {}
    return metrics_daily_value(metrics) if objective_mode == "sanity_value" else metrics_layout_score(metrics)


def _choose_durations(
    team_a: dict,
    team_b: dict,
    collection: float,
    floor: float,
    maximum: float,
    dorm_helper: dict | None,
    fiammetta: dict | None,
    objective_mode: str,
) -> tuple[dict[str, float], str]:
    """Choose a sustainable unequal cycle so the stronger team works longer."""
    options = {
        "A": _duration_options(team_a, collection, floor, maximum),
        "B": _duration_options(team_b, collection, floor, maximum),
    }
    scores = {
        "A": _production_score(team_a, objective_mode),
        "B": _production_score(team_b, objective_mode),
    }
    best: tuple[float, float, float, float] | None = None
    pairs = [(a_hours, b_hours) for a_hours in options["A"] for b_hours in options["B"]]
    daily_pairs = [(a_hours, b_hours) for a_hours, b_hours in pairs if abs(a_hours + b_hours - 24.0) < 1e-9]
    for a_hours, b_hours in (daily_pairs or pairs):
        trial_durations = {"A": a_hours, "B": b_hours}
        audit_a = _recovery_audit(team_a, a_hours, b_hours, dorm_helper, fiammetta)
        audit_b = _recovery_audit(team_b, b_hours, a_hours, dorm_helper, fiammetta)
        instant_audit = _fiammetta_audit(team_a, team_b, trial_durations, fiammetta)
        if not (audit_a["feasible"] and audit_b["feasible"] and instant_audit["feasible"]):
            continue
        cycle = a_hours + b_hours
        weighted = (scores["A"] * a_hours + scores["B"] * b_hours) / cycle
        # The daily pairs keep the 24h trace equal to the repeating-cycle
        # average; a non-daily fallback is used only when unavoidable.
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


def _room_score(room: dict, objective_mode: str) -> float:
    """Score one room without importing the optimizer and creating a cycle."""
    key = str(room.get("key") or "")
    if objective_mode == "sanity_value":
        return candidate_daily_value(room, key)
    if key == "trade":
        return float((room.get("trade") or {}).get("lmd_per_day", 0) or 0) / 10_265.4867256637
    if key == "orundum":
        return float((room.get("orundum") or {}).get("orundum_per_day", 0) or 0) / 240.0
    if key in {"gold", "exp", "shard"}:
        return float(room.get("multiplier", 0) or 0)
    if key == "power":
        return 0.18 * float(room.get("multiplier", 1) or 1)
    return 0.0


def _room_team(room: dict) -> dict:
    return {"rooms": [room], "support_rooms": [], "metrics": {}}


def _choose_room_durations(
    room_a: dict,
    room_b: dict,
    collection: float,
    floor: float,
    maximum: float,
    objective_mode: str,
    fiammetta: dict | None,
) -> tuple[dict[str, float], dict]:
    """Choose independent A/B work lengths for one physical room.

    The login/collection interval defines every legal handover point.  A room
    with a stronger and slower-fatiguing team can therefore remain on duty
    after unrelated rooms have already changed shifts.
    """
    teams = {"A": _room_team(room_a), "B": _room_team(room_b)}
    options = {
        label: _duration_options(team, collection, floor, maximum)
        for label, team in teams.items()
    }
    scores = {"A": _room_score(room_a, objective_mode), "B": _room_score(room_b, objective_mode)}
    best: tuple[float, float, float, float, float] | None = None
    best_audits: tuple[dict, dict] | None = None
    pairs = [(a_hours, b_hours) for a_hours in options["A"] for b_hours in options["B"]]
    # A 24-hour room cycle makes the displayed 24h trace an exact repeating
    # steady-state day.  Only fall back to a non-daily cycle if the login grid
    # or recovery constraints make every daily split infeasible.
    daily_pairs = [(a_hours, b_hours) for a_hours, b_hours in pairs if abs(a_hours + b_hours - 24.0) < 1e-9]
    for a_hours, b_hours in (daily_pairs or pairs):
        # Use ordinary beds here.  A single locked helper cannot
        # simultaneously boost every independently rotating room.
        audit_a = _recovery_audit(teams["A"], a_hours, b_hours, None, fiammetta)
        audit_b = _recovery_audit(teams["B"], b_hours, a_hours, None, fiammetta)
        if not (audit_a["feasible"] and audit_b["feasible"]):
            continue
        cycle = a_hours + b_hours
        weighted = (scores["A"] * a_hours + scores["B"] * b_hours) / cycle
        # Real output dominates.  On the daily cycle, the stronger room
        # can take every additional login interval that remains recoverable.
        candidate = (
            weighted,
            -abs(cycle - 24.0) / 100_000.0,
            cycle / 10_000_000.0,
            -abs(a_hours - b_hours) / 100_000_000.0,
            a_hours,
        )
        if best is None or candidate > best:
            best = candidate
            best_audits = (audit_a, audit_b)
            durations = {"A": a_hours, "B": b_hours}
    if best is None:
        durations = {
            "A": _team_duration(teams["A"], collection, floor, maximum),
            "B": _team_duration(teams["B"], collection, floor, maximum),
        }
        best_audits = (
            _recovery_audit(teams["A"], durations["A"], durations["B"], None, fiammetta),
            _recovery_audit(teams["B"], durations["B"], durations["A"], None, fiammetta),
        )
    return durations, {
        "scores": {key: round(value, 6) for key, value in scores.items()},
        "options": options,
        "recovery": {"A": best_audits[0], "B": best_audits[1]},
        "daily_cycle": abs(durations["A"] + durations["B"] - 24.0) < 1e-9,
    }


def _paired_rooms(team_a: dict, team_b: dict) -> list[tuple[dict, dict]]:
    """Pair corresponding physical rooms while preserving facility order."""
    buckets: dict[str, list[dict]] = {}
    for room in _all_rooms(team_b):
        buckets.setdefault(str(room.get("key") or ""), []).append(room)
    positions: dict[str, int] = {}
    pairs = []
    for room_a in _all_rooms(team_a):
        key = str(room_a.get("key") or "")
        index = positions.get(key, 0)
        positions[key] = index + 1
        values = buckets.get(key, [])
        if index < len(values):
            pairs.append((room_a, values[index]))
    return pairs


def _average_metrics(a: dict, b: dict, a_hours: float = 1.0, b_hours: float = 1.0) -> dict:
    keys = {
        "lmd_per_day", "lmd_shard_cost_per_day", "lmd_net_after_shards_per_day",
        "exp_per_day", "orundum_per_day", "shards_made_per_day", "shards_used_per_day",
        "shards_net_per_day", "shard_material_used_per_day", "gold_made_per_day",
        "gold_used_per_day", "gold_production_net_per_day", "gold_external_per_day",
        "gold_net_per_day", "drones_per_day", "drones_recovery_potential_per_day",
        "drone_overflow_lost_per_day", "drone_hours_per_day", "power_bonus",
    }
    total = max(1e-9, a_hours + b_hours)
    result = dict(a)
    for key in keys:
        if isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float)):
            result[key] = round((float(a[key]) * a_hours + float(b[key]) * b_hours) / total, 2)
    result["drone_target"] = "A/B 两套排班按实际在岗时长加权"
    effects = [a.get("drone_effect") or {}, b.get("drone_effect") or {}]
    effect_keys = {
        "equivalent_hours", "lmd_per_day", "exp_per_day", "gold_made_per_day",
        "gold_used_per_day", "shards_made_per_day", "shards_used_per_day", "orundum_per_day",
    }
    result["drone_effect"] = {
        key: round(
            (float(effects[0].get(key, 0) or 0) * a_hours + float(effects[1].get(key, 0) or 0) * b_hours) / total,
            3,
        )
        for key in effect_keys
    }
    result["drone_effect"].update({
        "target_kind": "weighted_rotation",
        "target": "A/B 各自选择的目标房间，按实际在岗时长加权",
    })
    allocations = []
    for team, effect, weight in (("A", effects[0], a_hours), ("B", effects[1], b_hours)):
        for allocation in effect.get("allocations") or []:
            amount = float(allocation.get("drones_per_day", 0) or 0) * weight / total
            allocations.append({
                **allocation,
                "team": team,
                "drones_per_day": round(amount, 3),
                "fraction": round(amount / float(result.get("drones_per_day", 1) or 1), 6),
                "equivalent_hours": round(amount * 3.0 / 60.0, 3),
                "deltas": {key: round(float(value) * weight / total, 3)
                           for key, value in (allocation.get("deltas") or {}).items()},
            })
    result["drone_effect"]["allocations"] = allocations
    balances = [effect.get("balance") for effect in effects]
    if all(balances):
        result["drone_effect"]["balance"] = {
            "policy": "supply_demand_balance",
            "base_gold_net_per_day": round((float(balances[0]["base_gold_net_per_day"]) * a_hours + float(balances[1]["base_gold_net_per_day"]) * b_hours) / total, 3),
            "target_gold_net_per_day": round((float(balances[0]["target_gold_net_per_day"]) * a_hours + float(balances[1]["target_gold_net_per_day"]) * b_hours) / total, 3),
            "projected_gold_net_per_day": round((float(balances[0]["projected_gold_net_per_day"]) * a_hours + float(balances[1]["projected_gold_net_per_day"]) * b_hours) / total, 3),
            "all_trade_gold_net_per_day": round((float(balances[0]["all_trade_gold_net_per_day"]) * a_hours + float(balances[1]["all_trade_gold_net_per_day"]) * b_hours) / total, 3),
            "all_gold_gold_net_per_day": round((float(balances[0]["all_gold_gold_net_per_day"]) * a_hours + float(balances[1]["all_gold_gold_net_per_day"]) * b_hours) / total, 3),
            "reachable": bool(balances[0].get("reachable") and balances[1].get("reachable")),
            "balanced": bool(balances[0].get("balanced") and balances[1].get("balanced")),
            "binding": bool(balances[0].get("binding") and balances[1].get("binding")),
            "regime": (
                "balanced" if balances[0].get("binding") and balances[1].get("binding") else
                "trade_saturated" if all(item.get("regime") == "trade_saturated" for item in balances) else
                "mixed"
            ),
            "bottleneck": "gold" if any(item.get("kind") == "gold" for item in allocations) else "trade",
        }
        result["drone_effect"]["target"] = " + ".join(
            f"{item.get('team')}班 {item.get('label')} {float(item.get('fraction', 0)) * 100:.1f}%"
            for item in allocations
        )
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
    drone_effect = metrics.get("drone_effect") or {}
    base_metrics = dict(metrics)
    for key in (
        "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
        "orundum_per_day", "shards_made_per_day", "shards_used_per_day",
    ):
        base_metrics[key] = float(metrics.get(key, 0) or 0) - float(drone_effect.get(key, 0) or 0)
    base_metrics["gold_net_per_day"] = (
        float(metrics.get("gold_net_per_day", 0) or 0)
        - float(drone_effect.get("gold_net_per_day", 0) or 0)
    )
    base_metrics["shards_net_per_day"] = (
        float(base_metrics.get("shards_made_per_day", 0) or 0)
        - float(base_metrics.get("shards_used_per_day", 0) or 0)
    )
    rooms = team.get("rooms") or []
    rates = {
        key: float(base_metrics.get(key, 0) or 0) / 24.0
        for key in (
            "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
            "gold_net_per_day", "orundum_per_day", "shards_net_per_day", "drones_per_day",
        )
    }
    rates["drones_per_day"] = float(
        metrics.get("drones_recovery_potential_per_day", metrics.get("drones_per_day", 0)) or 0
    ) / 24.0
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
    shards_made = float(base_metrics.get("shards_made_per_day", 0) or 0) / 24.0
    shards_used = float(base_metrics.get("shards_used_per_day", 0) or 0) / 24.0
    shards_made *= _room_output_ratio(shard, elapsed_hours, lambda room: room.get("multiplier", 0))
    shards_used *= _room_output_ratio(
        orundum, elapsed_hours, lambda room: (room.get("orundum") or {}).get("shards_per_day", 0)
    )
    rates["shards_net_per_day"] = shards_made - shards_used
    external_gold = (
        float(base_metrics.get("gold_net_per_day", 0) or 0)
        - float(base_metrics.get("gold_made_per_day", 0) or 0)
        + float(base_metrics.get("gold_used_per_day", 0) or 0)
    ) / 24.0
    rates["gold_net_per_day"] = rates["gold_made_per_day"] - rates["gold_used_per_day"] + external_gold
    return rates


def _summarize_drone_events(drone_events: list[dict]) -> dict:
    allocation_totals: dict[tuple[str, str, str], dict] = {}
    drone_deltas: dict[str, float] = {}
    for event in drone_events:
        for target in event.get("targets", []):
            key = (str(target.get("kind")), str(target.get("label")), str(target.get("target")))
            row = allocation_totals.setdefault(key, {
                "kind": target.get("kind"), "label": target.get("label"),
                "target": target.get("target"), "target_operators": target.get("target_operators") or [],
                "drones_per_day": 0.0, "deltas": {},
            })
            row["drones_per_day"] += float(target.get("drones", 0) or 0)
            for name, value in (target.get("deltas") or {}).items():
                row["deltas"][name] = row["deltas"].get(name, 0.0) + float(value or 0)
                drone_deltas[name] = drone_deltas.get(name, 0.0) + float(value or 0)
    spent_total = sum(float(event.get("drones_spent", 0) or 0) for event in drone_events)
    allocations = []
    for row in allocation_totals.values():
        amount = float(row["drones_per_day"])
        allocations.append({
            **row,
            "drones_per_day": round(amount, 3),
            "fraction": round(amount / spent_total, 6) if spent_total else 0.0,
            "equivalent_hours": round(amount * 3.0 / 60.0, 3),
            "deltas": {name: round(value, 3) for name, value in row["deltas"].items()},
        })
    return {
        "drones_spent": round(spent_total, 3),
        "equivalent_hours": round(spent_total * 3.0 / 60.0, 3),
        "allocations": allocations,
        "deltas": {name: round(value, 3) for name, value in drone_deltas.items()},
    }


def _production_curve(
    teams: dict[str, dict], durations: dict[str, float], collection_hours: float, minutes: int = 1440,
) -> dict:
    """Integrate base production and spend the drone bank at collection nodes."""
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
    drone_bank = 0.0
    drone_events = []
    step = 15
    collection_minutes = max(step, round(collection_hours * 60 / step) * step)
    label, elapsed_hours = active_team(0)
    rates = _instant_rates(teams[label], elapsed_hours)
    points.append({
        "minute": 0, "team": label,
        "rates_per_hour": {key: round(value, 6) for key, value in rates.items()},
        "cumulative": {key: 0.0 for key in metric_keys}, "drone_event": None,
    })
    for minute in range(step, minutes + 1, step):
        # Integrate the interval using the team that was active immediately
        # before its right edge. This also handles a handover/collection at the
        # same timestamp in the same order as an in-game pre-shift collection.
        outgoing, outgoing_elapsed = active_team(max(0.0, (minute - 1e-6) / 60.0))
        interval_rates = _instant_rates(teams[outgoing], outgoing_elapsed)
        for key, value in interval_rates.items():
            if key != "drones_per_day":
                cumulative[key] += value * step / 60.0
        drone_bank = min(
            DRONE_CAPACITY,
            drone_bank + interval_rates["drones_per_day"] * step / 60.0,
        )

        event = None
        if minute % collection_minutes == 0:
            effect = (teams[outgoing].get("metrics") or {}).get("drone_effect") or {}
            allocations = effect.get("allocations") or []
            event_deltas = {key: 0.0 for key in metric_keys}
            event_targets = []
            spent_total = 0.0
            for allocation in allocations:
                fraction = float(allocation.get("fraction", 0) or 0)
                spent = drone_bank * fraction
                spent_total += spent
                deltas = {key: spent * float(value)
                          for key, value in (allocation.get("per_drone") or {}).items()}
                for key, value in deltas.items():
                    if key in event_deltas:
                        event_deltas[key] += value
                event_targets.append({
                    "kind": allocation.get("kind"), "label": allocation.get("label"),
                    "target": allocation.get("target"), "drones": round(spent, 3),
                    "deltas": {key: round(value, 6) for key, value in deltas.items()},
                })
            event_deltas["gold_net_per_day"] = (
                event_deltas.get("gold_made_per_day", 0) - event_deltas.get("gold_used_per_day", 0)
            )
            # Drones are a generated-flow trace; spending them changes the bank
            # but does not erase the cumulative number recovered.
            for key, value in event_deltas.items():
                if key != "drones_per_day":
                    cumulative[key] += value
            event = {
                "minute": minute, "team": outgoing, "drones_spent": round(spent_total, 3),
                "drone_inventory_before": round(drone_bank, 3),
                "targets": event_targets,
                "deltas": {key: round(value, 6) for key, value in event_deltas.items() if abs(value) > 1e-12},
            }
            drone_events.append(event)
            drone_bank = max(0.0, drone_bank - spent_total)

        cumulative["drones_per_day"] = drone_bank

        label, elapsed_hours = active_team(minute / 60.0 if minute < minutes else max(0.0, (minute - 1e-6) / 60.0))
        rates = _instant_rates(teams[label], elapsed_hours)
        points.append({
            "minute": minute,
            "team": label,
            "rates_per_hour": {key: round(value, 6) for key, value in rates.items()},
            "cumulative": {key: round(value, 6) for key, value in cumulative.items()},
            "drone_event": event,
        })
    return {
        "hours": minutes / 60.0,
        "step_minutes": step,
        "points": points,
        "drone_events": drone_events,
        "drone_summary": _summarize_drone_events(drone_events),
        "metrics": list(metric_keys),
        "note": (f"基础产出按当前班组每 15 分钟积分；无人机库存按实时恢复速度增长、上限 {DRONE_CAPACITY:g} 架，"
                 f"并在每 {collection_hours:g} 小时收取节点按当班分配投入，所以无人机曲线是锯齿而非累计恢复量直线。"
                 "班次边界与阶段技能改变实时斜率。"),
    }


def _build_staggered_rotation(
    team_a: dict,
    team_b: dict,
    requested: float,
    collection: float,
    maximum: float,
    floor: float,
    dorm_helper: dict | None,
    fiammetta: dict | None,
    objective_mode: str,
    horizon_hours: float | None,
) -> dict:
    """Build a 24-hour room-level schedule with independent handovers."""
    horizon = 24.0 if horizon_hours is None else max(1.0, min(168.0, float(horizon_hours)))
    pairs = _paired_rooms(team_a, team_b)
    room_rows = []
    room_work_hours: dict[str, dict] = {}
    room_audits: dict[str, dict] = {}
    operator_rows: dict[str, dict] = {}
    handovers: dict[float, list[dict]] = {}
    production_durations = []
    room_order = {"control": 0, "trade": 1, "orundum": 2, "gold": 3, "exp": 4,
                  "shard": 5, "power": 6, "reception": 7, "office": 8}

    plans = []
    for room_a, room_b in pairs:
        name = str(room_a.get("room") or room_b.get("room") or "设施")
        durations, audit = _choose_room_durations(
            room_a, room_b, collection, floor, maximum, objective_mode, fiammetta
        )
        plans.append({"name": name, "a": room_a, "b": room_b, "durations": durations, "audit": audit})

    # A candidate with context effects was evaluated under its own team's full
    # control/cross-room state.  Such rooms must change together with that
    # state; otherwise a mixed A/B interval would silently apply the wrong
    # control-center or material count.  Purely local rooms remain independent.
    context_durations, context_reason = _choose_durations(
        team_a, team_b, collection, floor, maximum, dorm_helper, fiammetta, objective_mode
    )
    for plan in plans:
        has_context_dependency = plan["a"].get("key") == "control" or any(
            room.get("context_effects") for room in (plan["a"], plan["b"])
        )
        if has_context_dependency:
            plan["durations"] = dict(context_durations)
            plan["audit"] = {
                **plan["audit"], "synchronized_context": True,
                "synchronization_reason": "依赖控制中枢或跨房间状态，必须与全局状态同时切换",
            }

    for plan in plans:
        name, room_a, room_b = plan["name"], plan["a"], plan["b"]
        durations, audit = plan["durations"], plan["audit"]
        room_work_hours[name] = durations
        room_audits[name] = audit
        if room_a.get("key") in {"trade", "orundum", "gold", "exp", "shard", "power"}:
            production_durations.append(durations)
        events = []
        elapsed = 0.0
        index = 0
        while elapsed < horizon - 1e-9:
            label = "A" if index % 2 == 0 else "B"
            source = room_a if label == "A" else room_b
            start = elapsed
            end = min(horizon, start + durations[label])
            rates = _morale_rates(source)
            intrinsic_limit = _team_duration(_room_team(source), collection, floor, 36.0)
            phases = [{
                **profile,
                "phases": [
                    {**phase, "start": start + phase["start_hour"], "end": min(end, start + phase["end_hour"])}
                    for phase in profile.get("phases", []) if start + phase["start_hour"] < end
                ],
            } for profile in source.get("time_profiles", [])]
            min_end = min(
                (24.0 - rates.get(operator_id, 1.0) * (end - start)
                 for operator_id in source.get("operators", [])),
                default=24.0,
            )
            event = {
                "type": "work", "team": label, "room": name, "key": source.get("key"),
                "start": round(start, 3), "end": round(end, 3),
                "names": source.get("names", []), "operators": source.get("operators", []),
                "details": source.get("details", []), "efficiency": source.get("efficiency", 0),
                "time_profiles": phases, "morale_min_end": round(max(0.0, min_end), 2),
                "morale_rates": rates, "safe_work_hours": intrinsic_limit,
                "scheduled_work_hours": round(end - start, 3),
            }
            events.append(event)
            if start > 0:
                handovers.setdefault(round(start, 3), []).append({
                    "room": name, "team": label, "names": source.get("names", []),
                })
            for operator_id, operator_name in zip(source.get("operators", []), source.get("names", [])):
                operator_rows.setdefault(operator_id, {"id": operator_id, "name": operator_name})
            elapsed = end
            index += 1
        room_rows.append({"room": name, "key": room_a.get("key"), "events": events})

    if production_durations:
        average_a = sum(item["A"] for item in production_durations) / len(production_durations)
        average_b = sum(item["B"] for item in production_durations) / len(production_durations)
    else:
        average_a = average_b = requested
    team_hours = {"A": round(average_a, 3), "B": round(average_b, 3)}
    change_events = [
        {"time": time, "changes": changes}
        for time, changes in sorted(handovers.items())
    ]
    feasible = all(
        audit["recovery"]["A"]["feasible"] and audit["recovery"]["B"]["feasible"]
        for audit in room_audits.values()
    )
    fiammetta_audit = _fiammetta_audit(team_a, team_b, team_hours, fiammetta)
    room_rows.sort(key=lambda row: (room_order.get(row.get("key"), 99), row["room"]))
    return {
        "cycle_hours": horizon,
        "natural_cycle_hours": None,
        "shift_hours": requested,
        "schedule_mode": "staggered",
        "objective_mode": objective_mode,
        "collection_interval_hours": collection,
        "morale_floor": floor,
        "team_work_hours": team_hours,
        "room_work_hours": room_work_hours,
        "room_duration_audit": room_audits,
        "duration_reason": (
            f"各房间独立枚举每 {collection:g} 小时上线节点；纯本地技能按本房间产出决定工时，"
            f"依赖跨房间状态的设施同步切换。{context_reason}"
        ),
        "pattern": [],
        "shifts": [],
        "handover_events": change_events,
        "rooms": room_rows,
        "operators": list(operator_rows.values()),
        "teams": {
            "A": {"rooms": team_a.get("rooms", []), "support_rooms": team_a.get("support_rooms", []), "metrics": team_a["metrics"]},
            "B": {"rooms": team_b.get("rooms", []), "support_rooms": team_b.get("support_rooms", []), "metrics": team_b["metrics"]},
        },
        # The optimizer replaces these two provisional full-team aggregates
        # with room-weighted metrics and a room-event production curve.
        "average_metrics": _average_metrics(team_a["metrics"], team_b["metrics"], average_a, average_b),
        "production_curve": None,
        "dormitory": {
            "locked_helper": dorm_helper,
            "fiammetta": fiammetta,
            "note": (f"固定 {dorm_helper['name']} 驻宿舍；房间级时长审计保守地不重复使用其增益。"
                     if dorm_helper else "仅使用满级宿舍基础恢复进行房间级审计。"),
        },
        "morale": {
            "feasible": feasible and fiammetta_audit["feasible"],
            "beds": 20 - int(bool(dorm_helper)) - int(bool((fiammetta or {}).get("enabled"))),
            "base_recovery_per_hour": BASE_RECOVERY_PER_HOUR,
            "teams": {},
            "rooms": room_audits,
            "fiammetta": fiammetta_audit,
            "note": f"房间独立换班；所有切换均落在每 {collection:g} 小时的可上线节点。",
        },
        "inventory_policy": {
            "mode": "working_stock", "collection_interval_hours": collection,
            "note": "产出与订单在上线节点统一收取；不同房间可在同一节点选择继续工作或换班。",
        },
    }


def build_staggered_production_curve(
    rotation: dict,
    constants: dict,
    *,
    drone_target: str,
    external_gold_per_day: float,
    gold_net_target_per_day: float,
    minutes: int = 1440,
) -> dict:
    """Integrate a room-staggered schedule and spend drones at login nodes."""
    metric_keys = (
        "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
        "gold_net_per_day", "orundum_per_day", "shards_net_per_day", "drones_per_day",
    )
    candidates: dict[tuple[str, str], dict] = {}
    for label, plan in (rotation.get("teams") or {}).items():
        for room in [*(plan.get("support_rooms") or []), *(plan.get("rooms") or [])]:
            candidates[(label, str(room.get("room") or ""))] = room
    events_by_room = {row["room"]: row.get("events", []) for row in rotation.get("rooms", [])}

    def active(hour: float) -> list[tuple[str, dict, float]]:
        result = []
        for room_name, events in events_by_room.items():
            event = next(
                (item for item in events if float(item["start"]) <= hour < float(item["end"]) - 1e-9),
                events[-1] if events and hour >= float(events[-1]["end"]) - 1e-9 else None,
            )
            if not event:
                continue
            candidate = candidates.get((event["team"], room_name))
            if candidate:
                result.append((event["team"], candidate, max(0.0, hour - float(event["start"]))))
        return result

    def room_rates(room: dict, elapsed: float) -> dict[str, float]:
        key = room.get("key")
        average_multiplier = max(1e-9, float(room.get("multiplier", 1.0) or 1.0))
        ratio = _instant_multiplier(room, elapsed) / average_multiplier
        rates = {name: 0.0 for name in metric_keys}
        if key == "trade":
            rates["lmd_per_day"] = float((room.get("trade") or {}).get("lmd_per_day", 0) or 0) * ratio / 24.0
            rates["gold_used_per_day"] = float((room.get("trade") or {}).get("gold_per_day", 0) or 0) * ratio / 24.0
        elif key == "gold":
            rates["gold_made_per_day"] = float(constants["gold_base_per_day"]) * _instant_multiplier(room, elapsed) / 24.0
        elif key == "exp":
            rates["exp_per_day"] = float(constants["exp_base_per_day"]) * _instant_multiplier(room, elapsed) / 24.0
        elif key == "shard":
            rates["shards_net_per_day"] = 24.0 * _instant_multiplier(room, elapsed) / 24.0
        elif key == "orundum":
            economy = room.get("orundum") or {}
            rates["orundum_per_day"] = float(economy.get("orundum_per_day", 0) or 0) * ratio / 24.0
            rates["shards_net_per_day"] = -float(economy.get("shards_per_day", 0) or 0) * ratio / 24.0
        elif key == "power":
            rates["drones_per_day"] = 10.0 * (5.0 + float(room.get("efficiency", 0) or 0)) / 100.0
        return rates

    def snapshot(hour: float) -> tuple[dict[str, float], list[tuple[str, dict, float]]]:
        active_rooms = active(hour)
        rates = {key: 0.0 for key in metric_keys}
        rates["drones_per_day"] = 10.0
        for _, room, elapsed in active_rooms:
            for key, value in room_rates(room, elapsed).items():
                rates[key] += value
        rates["gold_net_per_day"] = (
            rates["gold_made_per_day"] - rates["gold_used_per_day"]
            + external_gold_per_day / 24.0
        )
        return rates, active_rooms

    def drone_profiles(active_rooms: list[tuple[str, dict, float]]) -> dict[str, dict]:
        profiles = {}
        for label, room, elapsed in active_rooms:
            key = room.get("key")
            ratio = _instant_multiplier(room, elapsed) / max(1e-9, float(room.get("multiplier", 1) or 1))
            if key == "trade":
                economy = room.get("trade") or {}
                candidate = {
                    "kind": "trade", "label": "贸易订单", "team": label,
                    "target": f"{room.get('room')}：{' / '.join(room.get('names') or [])}",
                    "target_operators": room.get("operators") or [],
                    "per_drone": {
                        "lmd_per_day": float(economy.get("lmd_per_day", 0) or 0) * ratio / 480.0,
                        "gold_used_per_day": float(economy.get("gold_per_day", 0) or 0) * ratio / 480.0,
                    },
                }
                if candidate["per_drone"]["lmd_per_day"] > float((profiles.get("trade") or {}).get("per_drone", {}).get("lmd_per_day", -1)):
                    profiles["trade"] = candidate
            elif key in {"gold", "exp", "shard"}:
                output_key = {"gold": "gold_made_per_day", "exp": "exp_per_day", "shard": "shards_made_per_day"}[key]
                base = {"gold": constants["gold_base_per_day"], "exp": constants["exp_base_per_day"], "shard": 24.0}[key]
                candidate = {
                    "kind": key, "label": {"gold": "赤金制造", "exp": "作战记录制造", "shard": "源石碎片制造"}[key],
                    "team": label, "target": f"{room.get('room')}：{' / '.join(room.get('names') or [])}",
                    "target_operators": room.get("operators") or [],
                    "per_drone": {output_key: float(base) * _instant_multiplier(room, elapsed) / 480.0},
                }
                if candidate["per_drone"][output_key] > float((profiles.get(key) or {}).get("per_drone", {}).get(output_key, -1)):
                    profiles[key] = candidate
            elif key == "orundum":
                economy = room.get("orundum") or {}
                profiles["orundum"] = {
                    "kind": "orundum", "label": "源石订单", "team": label,
                    "target": f"{room.get('room')}：{' / '.join(room.get('names') or [])}",
                    "target_operators": room.get("operators") or [],
                    "per_drone": {
                        "orundum_per_day": float(economy.get("orundum_per_day", 0) or 0) * ratio / 480.0,
                        "shards_used_per_day": float(economy.get("shards_per_day", 0) or 0) * ratio / 480.0,
                    },
                }
        return profiles

    cumulative = {key: 0.0 for key in metric_keys}
    points = []
    drone_bank = 0.0
    recovered = 0.0
    overflow = 0.0
    drone_events = []
    step = 15
    collection_minutes = max(step, round(float(rotation["collection_interval_hours"]) * 60 / step) * step)
    rates, active_rooms = snapshot(0.0)
    points.append({"minute": 0, "team": "A", "rates_per_hour": rates,
                   "cumulative": dict(cumulative), "drone_event": None})
    for minute in range(step, minutes + 1, step):
        hour = max(0.0, (minute - 1e-6) / 60.0)
        rates, active_rooms = snapshot(hour)
        for key, value in rates.items():
            if key != "drones_per_day":
                cumulative[key] += value * step / 60.0
        generated = rates["drones_per_day"] * step / 60.0
        recovered += generated
        new_bank = min(DRONE_CAPACITY, drone_bank + generated)
        overflow += max(0.0, drone_bank + generated - DRONE_CAPACITY)
        drone_bank = new_bank
        event = None
        if minute % collection_minutes == 0:
            profiles = drone_profiles(active_rooms)
            allocations = []
            if drone_target in {"auto_balance", "auto_lmd"} and "trade" in profiles:
                trade_gold = float(profiles["trade"]["per_drone"].get("gold_used_per_day", 0))
                gold_per_drone = float((profiles.get("gold") or {}).get("per_drone", {}).get("gold_made_per_day", 0))
                base_net = 24.0 * (rates["gold_made_per_day"] - rates["gold_used_per_day"]) + external_gold_per_day
                gold_drones = 0.0 if gold_per_drone <= 0 else max(
                    0.0, min(drone_bank, (gold_net_target_per_day - base_net + drone_bank * trade_gold) / (gold_per_drone + trade_gold))
                )
                if gold_drones > 1e-9 and "gold" in profiles:
                    allocations.append((profiles["gold"], gold_drones))
                if drone_bank - gold_drones > 1e-9:
                    allocations.append((profiles["trade"], drone_bank - gold_drones))
            elif drone_target in profiles:
                allocations.append((profiles[drone_target], drone_bank))
            targets = []
            event_deltas = {key: 0.0 for key in metric_keys}
            spent = 0.0
            for profile, amount in allocations:
                spent += amount
                deltas = {key: amount * float(value) for key, value in profile["per_drone"].items()}
                event_deltas["lmd_per_day"] += deltas.get("lmd_per_day", 0.0)
                event_deltas["exp_per_day"] += deltas.get("exp_per_day", 0.0)
                event_deltas["gold_made_per_day"] += deltas.get("gold_made_per_day", 0.0)
                event_deltas["gold_used_per_day"] += deltas.get("gold_used_per_day", 0.0)
                event_deltas["orundum_per_day"] += deltas.get("orundum_per_day", 0.0)
                event_deltas["shards_net_per_day"] += deltas.get("shards_made_per_day", 0.0) - deltas.get("shards_used_per_day", 0.0)
                targets.append({**profile, "drones": round(amount, 3), "deltas": deltas})
            event_deltas["gold_net_per_day"] = event_deltas["gold_made_per_day"] - event_deltas["gold_used_per_day"]
            for key, value in event_deltas.items():
                if key != "drones_per_day":
                    cumulative[key] += value
            labels = {label for label, _, _ in active_rooms}
            event = {"minute": minute, "team": labels.pop() if len(labels) == 1 else "混合",
                     "drones_spent": round(spent, 3), "drone_inventory_before": round(drone_bank, 3),
                     "targets": targets, "deltas": event_deltas}
            drone_events.append(event)
            drone_bank = max(0.0, drone_bank - spent)
        cumulative["drones_per_day"] = drone_bank
        labels = {label for label, _, _ in active_rooms}
        points.append({
            "minute": minute, "team": labels.pop() if len(labels) == 1 else "混合",
            "rates_per_hour": {key: round(value, 6) for key, value in rates.items()},
            "cumulative": {key: round(value, 6) for key, value in cumulative.items()},
            "drone_event": event,
        })
    return {
        "hours": minutes / 60.0, "step_minutes": step, "points": points,
        "drone_events": drone_events, "metrics": list(metric_keys),
        "drone_recovered": round(recovered, 3), "drone_overflow": round(overflow, 3),
        "drone_summary": _summarize_drone_events(drone_events),
        "note": (f"按每个房间的独立班次每 15 分钟积分；每 {rotation['collection_interval_hours']:g} 小时上线时统一收取并投入无人机。"
                 "悬停可查看混合 A/B 状态下的实时速率。"),
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
    fiammetta: dict | None = None,
    objective_mode: str = "layout_output",
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
    if schedule_mode == "staggered":
        return _build_staggered_rotation(
            team_a, team_b, requested, collection, maximum, floor,
            dorm_helper, fiammetta, objective_mode, horizon_hours,
        )
    if schedule_mode == "morale_aware":
        durations, duration_reason = _choose_durations(
            team_a, team_b, collection, floor, maximum, dorm_helper, fiammetta, objective_mode
        )
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
            intrinsic_limit = _team_duration(
                {"rooms": [room], "support_rooms": []}, collection, floor, 36.0
            )
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
                "morale_rates": rates,
                "safe_work_hours": intrinsic_limit,
                "scheduled_work_hours": round(end - start, 3),
            }
            shift_rooms.append(event)
            room_rows.setdefault(room["room"], {"room": room["room"], "key": room.get("key"), "events": []})["events"].append(event)
            for operator_id, name in zip(room.get("operators", []), room.get("names", [])):
                operator_rows.setdefault(operator_id, {"id": operator_id, "name": name})
        shifts.append({"index": index + 1, "team": label, "start": start, "end": end, "rooms": shift_rooms})
        elapsed = end
        index += 1

    recovery_audit = {
        "A": _recovery_audit(team_a, durations["A"], durations["B"], dorm_helper, fiammetta),
        "B": _recovery_audit(team_b, durations["B"], durations["A"], dorm_helper, fiammetta),
    }
    fiammetta_audit = _fiammetta_audit(team_a, team_b, durations, fiammetta)
    feasible = all(audit["feasible"] for audit in recovery_audit.values()) and fiammetta_audit["feasible"]

    room_order = {"control": 0, "trade": 1, "orundum": 2, "gold": 3, "exp": 4,
                  "shard": 5, "power": 6, "reception": 7, "office": 8}
    rooms = sorted(room_rows.values(), key=lambda row: (room_order.get(row.get("key"), 99), row["room"]))
    return {
        "cycle_hours": horizon, "natural_cycle_hours": natural_cycle, "shift_hours": requested, "schedule_mode": schedule_mode,
        "objective_mode": objective_mode,
        "collection_interval_hours": collection, "morale_floor": floor, "team_work_hours": durations,
        "duration_reason": duration_reason,
        "pattern": [shift["team"] for shift in shifts], "shifts": shifts, "rooms": rooms,
        "operators": list(operator_rows.values()),
        "teams": {
            "A": {"rooms": team_a.get("rooms", []), "support_rooms": team_a.get("support_rooms", []), "metrics": team_a["metrics"]},
            "B": {"rooms": team_b.get("rooms", []), "support_rooms": team_b.get("support_rooms", []), "metrics": team_b["metrics"]},
        },
        "average_metrics": _average_metrics(team_a["metrics"], team_b["metrics"], worked_hours["A"], worked_hours["B"]),
        "production_curve": _production_curve(teams, durations, collection),
        "dormitory": {
            "locked_helper": dorm_helper,
            "fiammetta": fiammetta,
            "note": (f"固定 {dorm_helper['name']} 驻一间宿舍；占用 1 个床位，并使同宿舍其余 4 个床位恢复 +{dorm_helper.get('all', 0):g}/小时。"
                     if dorm_helper else "未锁定宿舍恢复干员。"),
        },
        "morale": {
            "feasible": feasible,
            "beds": 20 - int(bool(dorm_helper)) - int(bool((fiammetta or {}).get("enabled"))),
            "base_recovery_per_hour": BASE_RECOVERY_PER_HOUR, "teams": recovery_audit,
            "fiammetta": fiammetta_audit,
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
