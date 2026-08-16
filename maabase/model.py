"""Operator skill activation and room-team evaluation."""

from __future__ import annotations

from itertools import combinations
from typing import Iterable

from .mechanics import (
    TRADE_ECONOMIC_ICONS,
    mechanic_is_partial,
    order_quality_profile,
    resolve_trade_mechanics,
    warmed_order_probabilities,
)
from .state_model import BaseContext, CONTEXT_MODELED_ICONS, room_context_adjustment


ROOM_MAP = {"MANUFACTURE": "Mfg", "TRADING": "Trade", "POWER": "Power", "CONTROL": "Control"}
PRODUCT_KEYS = {"gold": "PureGold", "exp": "CombatRecord", "shard": "OriginStone",
                "trade": "Money", "orundum": "Money", "power": "Drone"}
TARGETS = {"gold": "F_GOLD", "exp": "F_EXP", "shard": "F_DIAMOND"}
def active_skills(operator: dict, catalog: dict) -> list[dict]:
    definition = catalog["operators"].get(operator["id"])
    if not definition:
        return []
    phase = int(operator.get("elite", operator.get("phase", 0)))
    level = int(operator.get("level", 1))
    result = []
    for slot in definition.get("slots", []):
        eligible = [x for x in slot if phase > x["phase"] or (phase == x["phase"] and level >= x["level"])]
        if eligible:
            choice = max(eligible, key=lambda x: (x["phase"], x["level"]))
            buff = dict(catalog["buffs"][choice["buff"]])
            buff["unlock"] = {"phase": choice["phase"], "level": choice["level"]}
            result.append(buff)
    return result


def _value(efficient: dict, product: str, constants: dict | None = None) -> float | None:
    key = PRODUCT_KEYS[product]
    raw = efficient.get(key, efficient.get("all"))
    if raw is not None:
        return float(raw)
    expression = efficient.get(f"{key}_reg", efficient.get("all_reg"))
    if not expression:
        return None
    values = {"NumOfTrade": 2, "NumOfPower": 3}
    if constants:
        values.update(constants)
    text = str(expression)
    for name, number in values.items():
        text = text.replace(f"[{name}]", str(float(number)))
    # MAA's current formula set only uses numbers and basic arithmetic.
    if any(ch not in "0123456789.+-*/() " for ch in text):
        return None
    try:
        return float(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 - validated alphabet above
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None


def _skill_value(skill: dict, product: str, maa_room: dict) -> tuple[float, bool]:
    maa = maa_room.get("skills", {}).get(skill.get("icon", ""))
    if maa:
        value = _value(maa.get("efficient", {}), product)
        if value is not None:
            return value, True
    target = TARGETS.get(product)
    applicable = not target or not skill.get("targets") or target in skill.get("targets", [])
    if applicable and skill.get("category") == "OUTPUT":
        return float(skill.get("efficiency") or 0), True
    return 0.0, False


def _actual_speed_value(skill: dict, product: str, maa_room: dict) -> tuple[float, bool]:
    """Return clock speed without MAA's order-value equivalent scores."""
    if product in {"trade", "orundum"} and skill.get("icon") in TRADE_ECONOMIC_ICONS:
        return 0.0, True
    target = TARGETS.get(product)
    applicable = not target or not skill.get("targets") or target in skill.get("targets", [])
    if applicable and skill.get("category") == "OUTPUT":
        return float(skill.get("efficiency") or 0), True
    # MAA's values for capacity, morale and complex conditions are comparison
    # scores, not clock speed.  They must never leak into actual production.
    return 0.0, False


def _trade_economics(team: list[dict], speed_efficiency: float, context: BaseContext | None = None) -> dict:
    icon_list = [icon for operator in team for icon in operator["icons"]]
    mechanics = resolve_trade_mechanics(icon_list)
    probabilities, quality = warmed_order_probabilities(icon_list, context.shift_hours if context else None)
    breach_extra = mechanics.breach_extra_gold if mechanics.breach_marker else 0
    large_order_bonus = mechanics.normal_large_order_lmd
    base_orders = ((2.0, 1000.0, 144.0), (3.0, 1500.0, 210.0), (4.0, 2000.0, 276.0))
    distribution = []
    for (base_gold, base_lmd, minutes), probability in zip(base_orders, probabilities):
        breach = breach_extra > 0 and base_gold < 4
        gold = base_gold + breach_extra if breach else base_gold
        lmd = base_lmd + breach_extra * 500 if breach else base_lmd
        if large_order_bonus and base_gold > 3 and not breach:
            lmd += large_order_bonus
        distribution.append({"base_gold": base_gold, "gold": gold, "lmd": lmd,
                             "minutes": minutes, "probability": probability, "breach": breach})
    expected_minutes = sum(x["minutes"] * x["probability"] for x in distribution)
    expected_lmd = sum(x["lmd"] * x["probability"] for x in distribution)
    expected_gold = sum(x["gold"] * x["probability"] for x in distribution)
    multiplier = 1.0 + (len(team) + speed_efficiency) / 100.0
    notes = [quality]
    if breach_extra:
        notes.append(f"违约订单机制 +{breach_extra} 赤金 / +{breach_extra * 500} 龙门币")
    if large_order_bonus:
        notes.append(f"普通四赤金订单投资机制 +{large_order_bonus} 龙门币")
    return {
        "distribution": distribution,
        "quality_warmup": order_quality_profile(icon_list, context.shift_hours if context else None),
        "expected_minutes": round(expected_minutes, 6),
        "expected_lmd": round(expected_lmd, 6),
        "expected_gold": round(expected_gold, 6),
        "lmd_per_day": expected_lmd / expected_minutes * 1440.0 * multiplier,
        "gold_per_day": expected_gold / expected_minutes * 1440.0 * multiplier,
        "notes": notes,
        "breach_extra_gold": breach_extra,
        "normal_large_order_lmd": large_order_bonus,
    }


def _orundum_economics(team: list[dict], speed_efficiency: float) -> dict:
    multiplier = 1.0 + (len(team) + speed_efficiency) / 100.0
    return {
        "distribution": [{"shards": 2, "orundum": 20, "minutes": 120, "probability": 1.0}],
        "expected_minutes": 120.0,
        "expected_shards": 2.0,
        "expected_orundum": 20.0,
        "orundum_per_day": 240.0 * multiplier,
        "shards_per_day": 24.0 * multiplier,
        "notes": ["开采协力：每 2 个源石碎片兑换 20 合成玉，基础订单 2 小时"],
    }


def _comb_matches(comb: dict, operator: dict) -> bool:
    icons = operator["icons"]
    if not set(comb.get("skills", [])).issubset(icons):
        return False
    filters = comb.get("filter", [])
    return not filters or operator["name"] in filters


def _best_group_score(team: list[dict], product: str, maa_room: dict, direct_values: list[float],
                      context: BaseContext) -> tuple[float, str] | None:
    best: tuple[float, str] | None = None
    for group in maa_room.get("groups", []):
        conditions = group.get("conditions", {})
        actual = {"NumOfTrade": context.num_trade, "NumOfPower": context.num_power}
        if any(actual.get(k) not in (None, v) for k, v in conditions.items()):
            continue
        necessary = group.get("necessary", [])

        def place(index: int, used: set[int], score: float) -> None:
            nonlocal best
            if index < len(necessary):
                comb = necessary[index]
                value = _value(comb.get("efficient", {}), product)
                if value is None:
                    return
                for op_index, operator in enumerate(team):
                    if op_index not in used and _comb_matches(comb, operator):
                        place(index + 1, used | {op_index}, score + value)
                return

            total = score
            remaining = [i for i in range(len(team)) if i not in used]
            for op_index in remaining:
                values = [
                    _value(comb.get("efficient", {}), product)
                    for comb in group.get("optional", [])
                    if _comb_matches(comb, team[op_index])
                ]
                values = [x for x in values if x is not None]
                if values:
                    total += max(values)
                elif group.get("allow_external"):
                    total += direct_values[op_index]
                else:
                    return
            candidate = (total, group.get("description", "MAA 技能组"))
            if best is None or candidate[0] > best[0]:
                best = candidate

        place(0, set(), 0.0)
    return best


def evaluate_team(team: Iterable[dict], product: str, catalog: dict, context: BaseContext | None = None) -> dict:
    team = list(team)
    context = context or BaseContext()
    room = "Power" if product == "power" else ("Trade" if product in {"trade", "orundum"} else "Mfg")
    maa_room = catalog["maa"][room]
    direct_values: list[float] = []
    speed_values: list[float] = []
    unresolved: list[str] = []
    details: list[dict] = []
    icon_counts: dict[str, int] = {}
    for operator in team:
        value = 0.0
        speed_value = 0.0
        op_details = []
        for skill in operator["skills"]:
            if ROOM_MAP.get(skill.get("room")) != room:
                continue
            amount, modeled = _skill_value(skill, product, maa_room)
            speed_amount, speed_modeled = _actual_speed_value(skill, product, maa_room)
            icon = skill.get("icon", "")
            max_num = maa_room.get("skills", {}).get(icon, {}).get("max_num")
            icon_counts[icon] = icon_counts.get(icon, 0) + 1
            if max_num is not None and icon_counts[icon] > int(max_num):
                amount = 0.0
            value += amount
            speed_value += speed_amount
            op_details.append({"name": skill["name"], "description": skill["description"], "value": amount})
            description = skill.get("description", "")
            affects_output = any(word in description for word in ("生产力", "订单获取效率", "充能速度"))
            if mechanic_is_partial(skill) and icon not in CONTEXT_MODELED_ICONS:
                unresolved.append(f"{operator['name']}：{skill['name']}（仅计直接部分）")
            elif affects_output and not (modeled or speed_modeled):
                unresolved.append(f"{operator['name']}：{skill['name']}")
        direct_values.append(value)
        speed_values.append(speed_value)
        details.append({"operator": operator["name"], "skills": op_details, "value": value})

    direct = sum(direct_values)
    group = _best_group_score(team, product, maa_room, direct_values, context) if len(team) == 3 else None
    if group and group[0] > direct:
        rank_efficiency, group_name = group
        confidence = "maa_combo"
    else:
        rank_efficiency, group_name = direct, None
        confidence = "estimated" if unresolved else "direct"
    trade_mechanics = resolve_trade_mechanics([icon for operator in team for icon in operator["icons"]])
    if product in {"trade", "orundum"} and trade_mechanics.replace_other_speed:
        speed_efficiency = float(trade_mechanics.replace_other_speed) * (len(team) - 1)
    else:
        speed_efficiency = sum(speed_values)
    contextual = room_context_adjustment(team, product, context, speed_efficiency)
    speed_efficiency += float(contextual["delta"])
    rank_efficiency = max(rank_efficiency, speed_efficiency)
    multiplier = 1.0 + (len(team) + speed_efficiency) / 100.0
    return {
        "operators": [x["id"] for x in team],
        "names": [x["name"] for x in team],
        "product": product,
        "efficiency": round(speed_efficiency, 3),
        "equivalent_efficiency": round(rank_efficiency, 3),
        "multiplier": multiplier,
        "trade": _trade_economics(team, speed_efficiency, context) if product == "trade" else None,
        "orundum": _orundum_economics(team, speed_efficiency) if product == "orundum" else None,
        "mechanic_notes": contextual["notes"],
        "context_effects": contextual["effects"],
        "time_profiles": contextual["time_profiles"],
        "confidence": confidence,
        "group": group_name,
        "unresolved": sorted(set(unresolved)),
        "details": details,
    }


def prepare_operators(roster: list[dict], catalog: dict) -> list[dict]:
    result = []
    for raw in roster:
        definition = catalog["operators"].get(raw.get("id"))
        if not definition:
            continue
        skills = active_skills(raw, catalog)
        result.append({
            **raw,
            "name": definition["name"],
            "skills": skills,
            "icons": {x.get("icon", "") for x in skills},
        })
    return result


def generate_candidates(operators: list[dict], product: str, catalog: dict, keep: int = 180,
                        context: BaseContext | None = None) -> list[dict]:
    context = context or BaseContext()
    room = "Power" if product == "power" else ("Trade" if product in {"trade", "orundum"} else "Mfg")
    group_icons = {
        icon
        for group in catalog["maa"][room].get("groups", [])
        for comb in group.get("necessary", []) + group.get("optional", [])
        for icon in comb.get("skills", [])
    }
    ranked = []
    neutral = []
    for operator in operators:
        relevant = [s for s in operator["skills"] if ROOM_MAP.get(s.get("room")) == room]
        if relevant:
            direct = sum(_skill_value(s, product, catalog["maa"][room])[0] for s in relevant)
            combo = 50 if operator["icons"] & (group_icons | CONTEXT_MODELED_ICONS) else 0
            ranked.append((direct + combo, operator))
        else:
            neutral.append(operator)
    ranked.sort(key=lambda x: x[0], reverse=True)
    pool_limit = 42 if product != "power" else 32
    pool = [x[1] for x in ranked[:pool_limit]] + neutral[: min(6, max(0, pool_limit - len(ranked)))]
    size = 1 if product == "power" else 3
    if len(pool) < size:
        return []
    candidates = [evaluate_team(team, product, catalog, context) for team in combinations(pool, size)]
    candidates.sort(key=lambda x: (x.get("equivalent_efficiency", x["efficiency"]), x["confidence"] != "estimated"), reverse=True)
    if size == 1:
        return candidates[:keep]

    # Pure top-N truncation is unsafe for set packing: the first hundred teams may
    # all contain the same superstar. Preserve several greedily disjoint chains so
    # later rooms always have competitive alternatives.
    retained = list(candidates[: max(60, keep // 2)])
    # Keep the best representative containing every relevant pool operator.
    # This prevents a small set of superstars from erasing strong second-team
    # alternatives before the global set-packing solver can see them.
    for operator in pool:
        representative = next((candidate for candidate in candidates if operator["id"] in candidate["operators"]), None)
        if representative:
            retained.append(representative)
    for seed in candidates[: min(48, len(candidates))]:
        current = seed
        used: set[str] = set()
        for _ in range(5):
            retained.append(current)
            used.update(current["operators"])
            current = next((x for x in candidates if not used.intersection(x["operators"])), None)
            if current is None:
                break
    unique = {}
    for candidate in retained:
        unique[tuple(candidate["operators"])] = candidate
    diverse = list(unique.values())
    diverse.sort(key=lambda x: (x.get("equivalent_efficiency", x["efficiency"]), x["confidence"] != "estimated"), reverse=True)
    return diverse[: max(keep, min(len(diverse), keep + 120))]
