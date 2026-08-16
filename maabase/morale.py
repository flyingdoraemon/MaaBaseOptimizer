"""Morale-cycle feasibility checks for a maxed 2-4-3 base."""

from __future__ import annotations

import re

from .model import active_skills


MAX_MORALE = 24.0
DORM_LEVEL = 5
DORM_AMBIENCE = 5000
DORM_COUNT = 4
DORM_SLOTS = 5
# 2-4-3 support facilities not selected by the production optimizer:
# 5 control-center seats, 2 reception-room seats and 1 office seat.
SUPPORT_ACTIVE_SLOTS = 8
# PRTS: 1.5 + 0.1 * level + 0.0004 * ambience.
BASE_RECOVERY_PER_HOUR = 1.5 + 0.1 * DORM_LEVEL + 0.0004 * DORM_AMBIENCE
CONTROL_BASE_REDUCTION = 0.05 * 5


def _numbers(description: str, patterns: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for pattern in patterns:
        values.extend(float(value) for value in re.findall(pattern, description))
    return values


def _dorm_skill(skill: dict, operator: str) -> dict | None:
    if skill.get("room") != "DORMITORY":
        return None
    text = re.sub(r"<[^>]+>", "", str(skill.get("description") or ""))
    all_values = _numbers(text, (r"所有干员(?:的)?心情每小时恢复(?:速度)?\+([0-9.]+)",))
    single_values = _numbers(text, (r"某个干员每小时恢复\+([0-9.]+)", r"某一名.*?心情每小时恢复(?:速度)?\+([0-9.]+)"))
    self_values = _numbers(text, (r"自身心情每小时恢复(?:速度)?\+([0-9.]+)",))
    if not (all_values or single_values or self_values):
        return None
    return {
        "operator": operator,
        "skill": skill.get("name", ""),
        "all": max(all_values, default=0.0),
        "single": max(single_values, default=0.0),
        "self": max(self_values, default=0.0),
        "description": text,
    }


def _work_rates(rooms: list[dict]) -> dict[str, float]:
    rates: dict[str, float] = {}
    for room in rooms:
        team_all_delta = 0.0
        for detail in room.get("details", []):
            for skill in detail.get("skills", []):
                text = str(skill.get("description") or "")
                if "全体心情每小时消耗" in text:
                    match = re.search(r"全体心情每小时消耗([+-])([0-9.]+)", text)
                    if match:
                        team_all_delta += float(match.group(2)) * (1 if match.group(1) == "+" else -1)
        for detail in room.get("details", []):
            rate = 1.0 - CONTROL_BASE_REDUCTION + team_all_delta
            for skill in detail.get("skills", []):
                text = str(skill.get("description") or "")
                if "全体心情每小时消耗" in text:
                    continue
                match = re.search(r"心情每小时消耗([+-])([0-9.]+)", text)
                if match:
                    rate += float(match.group(2)) * (1 if match.group(1) == "+" else -1)
            rates[str(detail.get("operator"))] = max(0.0, rate)
    return rates


def analyze_morale(rooms: list[dict], roster: list[dict], catalog: dict, shift_hours: float = 8.0) -> dict:
    shift_hours = max(1.0, min(24.0, float(shift_hours)))
    helpers = []
    for operator in roster:
        definition = catalog["operators"].get(operator.get("id"))
        if not definition:
            continue
        for skill in active_skills(operator, catalog):
            parsed = _dorm_skill(skill, definition["name"])
            if parsed:
                helpers.append(parsed)
    helpers.sort(key=lambda x: (x["all"], x["single"], x["self"]), reverse=True)
    rates = _work_rates(rooms)
    max_rate = max(rates.values(), default=0.75)
    max_spent = max_rate * shift_hours
    recovery_hours = max_spent / BASE_RECOVERY_PER_HOUR
    production_slots = sum(len(room.get("operators", [])) for room in rooms)
    active_slots = production_slots + SUPPORT_ACTIVE_SLOTS
    dorm_capacity = DORM_COUNT * DORM_SLOTS
    # Beds are a flow capacity, not a one-worker-per-shift reservation.  A
    # worker may leave as soon as full, so compare required and available
    # bed-hours over the whole rest shift.
    work_rates = list(rates.values())
    support_rate = max(0.0, 1.0 - CONTROL_BASE_REDUCTION)
    recovery_load = sum(rate * shift_hours / BASE_RECOVERY_PER_HOUR for rate in work_rates)
    recovery_load += SUPPORT_ACTIVE_SLOTS * support_rate * shift_hours / BASE_RECOVERY_PER_HOUR
    bed_hours_available = dorm_capacity * shift_hours
    two_team_feasible = recovery_hours <= shift_hours + 1e-9 and recovery_load <= bed_hours_available + 1e-9
    recommended_teams = 2 if two_team_feasible else 3
    required_roster = active_slots * recommended_teams
    one_rest_shift_enough = recovery_hours <= shift_hours + 1e-9
    return {
        "shift_hours": shift_hours,
        "base_recovery_per_hour": round(BASE_RECOVERY_PER_HOUR, 3),
        "control_base_reduction_per_hour": CONTROL_BASE_REDUCTION,
        "max_work_consumption_per_hour": round(max_rate, 3),
        "max_morale_spent_per_shift": round(max_spent, 3),
        "max_recovery_hours": round(recovery_hours, 3),
        "one_rest_shift_enough": one_rest_shift_enough,
        "production_slots": production_slots,
        "support_slots": SUPPORT_ACTIVE_SLOTS,
        "active_slots": active_slots,
        "dorm_capacity": dorm_capacity,
        "bed_hours_required": round(recovery_load, 3),
        "bed_hours_available": round(bed_hours_available, 3),
        "two_team_feasible": two_team_feasible,
        "recommended_rotation_teams": recommended_teams,
        "minimum_distinct_operators": required_roster,
        "owned_operators": len(roster),
        "roster_capacity_ok": len(roster) >= required_roster,
        "fiammetta_owned": any(operator.get("name") == "菲亚梅塔" for operator in roster),
        "dorm_helpers": helpers[:10],
        "note": (
            "满级满氛围宿舍的基础恢复与床位小时数都足以支撑休息一班；宿舍恢复干员不作为常规硬需求，"
            "但会保留给额外心情消耗、错峰不足或特殊体系。"
            if two_team_feasible else
            "仅靠基础恢复无法在一班内回满，需要分配宿舍恢复技能或延长休息。"
        ),
    }
