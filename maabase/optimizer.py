"""Cross-room RIIC assignment optimizer and production accounting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import itertools
from typing import Any

from .model import active_skills, generate_candidates, prepare_operators
from .morale import analyze_morale, choose_dorm_helper
from .scheduler import DRONE_CAPACITY, build_rotation, build_staggered_production_curve
from .valuation import candidate_daily_value, metrics_daily_value, metrics_layout_score, public_valuation
from .state_model import (
    ABYSSAL_HUNTER_IDS,
    MONSTER_HUNTER_IDS,
    SUI_IDS,
    BaseContext,
    mechanism_coverage,
    platform_count,
    select_control_options,
)


@dataclass(frozen=True)
class GroupSpec:
    key: str
    count: int


def _utility(candidate: dict, product: str, objective_mode: str) -> float:
    if objective_mode == "sanity_value":
        return candidate_daily_value(candidate, product)
    # The layout itself expresses demand in the default mode: each requested
    # room contributes a normalized production score, so one EXP room remains
    # one EXP room and is not silently sacrificed to an external value ratio.
    multiplier = float(candidate.get("multiplier", 0) or 0)
    if product == "trade":
        return float((candidate.get("trade") or {}).get("lmd_per_day", 0) or 0) / 10_265.4867256637
    if product == "orundum":
        return float((candidate.get("orundum") or {}).get("orundum_per_day", 0) or 0) / 240.0
    if product in {"exp", "gold", "shard"}:
        return multiplier
    if product == "power":
        return 0.18 * multiplier
    return 0.0


def _deterministic_tie_break(candidate: dict, product: str) -> float:
    """Resolve exact objective ties reproducibly without changing real scores."""
    identity = product + ":" + ",".join(sorted(str(value) for value in candidate.get("operators") or []))
    rank = int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big") / float(2**64)
    return rank * 1e-7


def _candidate_score(candidate: dict, product: str, objective_mode: str) -> float:
    return _utility(candidate, product, objective_mode) + _deterministic_tie_break(candidate, product)


def _solve_pulp(
    candidates: dict[str, list[dict]], groups: list[GroupSpec], objective_mode: str,
    reusable_ids: set[str] | None = None,
) -> tuple[dict, str] | None:
    try:
        import pulp
    except ImportError:
        return None
    problem = pulp.LpProblem("maa_base_global", pulp.LpMaximize)
    variables: dict[tuple[str, int], Any] = {}
    for group in groups:
        for index in range(len(candidates[group.key])):
            variables[(group.key, index)] = pulp.LpVariable(f"x_{group.key}_{index}", cat="Binary")
        problem += pulp.lpSum(variables[(group.key, i)] for i in range(len(candidates[group.key]))) == group.count
    operator_ids = {op for values in candidates.values() for c in values for op in c["operators"]}
    for op_id in operator_ids:
        problem += pulp.lpSum(
            variables[(group.key, i)]
            for group in groups
            for i, candidate in enumerate(candidates[group.key])
            if op_id in candidate["operators"]
        ) <= 1
    if reusable_ids:
        # Fiammetta can refresh one configured target between non-overlapping
        # rotation states.  The second team may therefore claim at most one
        # operator already used by A, never an arbitrary number of overlaps.
        problem += pulp.lpSum(
            len(set(candidate["operators"]) & reusable_ids) * variables[(group.key, i)]
            for group in groups
            for i, candidate in enumerate(candidates[group.key])
        ) <= 1
    problem += pulp.lpSum(
        _candidate_score(candidate, group.key, objective_mode) * variables[(group.key, i)]
        for group in groups
        for i, candidate in enumerate(candidates[group.key])
    )
    status = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=12))
    if pulp.LpStatus[status] not in {"Optimal", "Not Solved"}:
        return None
    selected = {
        group.key: [candidates[group.key][i] for i in range(len(candidates[group.key])) if variables[(group.key, i)].value() and variables[(group.key, i)].value() > 0.5]
        for group in groups
    }
    if any(len(selected[g.key]) != g.count for g in groups):
        return None
    return selected, "CBC 候选集协调解"


def _solve_beam(
    candidates: dict[str, list[dict]], groups: list[GroupSpec], objective_mode: str,
    width: int = 4000, reusable_ids: set[str] | None = None,
) -> tuple[dict, str]:
    # score, used operators, selected by product
    states: list[tuple[float, frozenset[str], dict[str, list[dict]]]] = [(0.0, frozenset(), {})]
    for group in groups:
        for slot in range(group.count):
            heap = []
            counter = itertools.count()
            for score, used, selected in states:
                for candidate in candidates[group.key]:
                    op_set = frozenset(candidate["operators"])
                    if used & op_set:
                        continue
                    if reusable_ids and len((used | op_set) & reusable_ids) > 1:
                        continue
                    new_selected = {key: list(value) for key, value in selected.items()}
                    new_selected.setdefault(group.key, []).append(candidate)
                    item = (score + _candidate_score(candidate, group.key, objective_mode), next(counter), used | op_set, new_selected)
                    if len(heap) < width * 2:
                        heapq.heappush(heap, item)
                    elif item[0] > heap[0][0]:
                        heapq.heapreplace(heap, item)
            if not heap:
                raise ValueError(f"可用干员不足，无法为 {group.key} 安排第 {slot + 1} 个房间")
            expanded = sorted(heap, key=lambda x: x[0], reverse=True)
            # One state per used-set avoids retaining mere permutations.
            states = []
            seen = set()
            for score, _, used, selected in expanded:
                if used in seen:
                    continue
                seen.add(used)
                states.append((score, used, selected))
                if len(states) >= width:
                    break
    return states[0][2], f"候选集协调搜索（宽度 {width}）"


def _solve(
    candidates: dict[str, list[dict]], groups: list[GroupSpec], objective_mode: str,
    reusable_ids: set[str] | None = None,
) -> tuple[dict, str]:
    exact = _solve_pulp(candidates, groups, objective_mode, reusable_ids)
    if exact:
        return exact
    return _solve_beam(candidates, groups, objective_mode, reusable_ids=reusable_ids)


def _metrics(
    selected: dict[str, list[dict]], catalog: dict, drone_target: str,
    external_gold_per_day: float = 0.0, gold_inventory: float = 0.0,
    shard_recipe: str = "rock", shard_inventory: float = 0.0,
    collection_interval_hours: float = 8.0,
    gold_net_target_per_day: float = -20.0,
) -> dict:
    constants = catalog["constants"]
    trade = selected.get("trade", [])
    gold = selected.get("gold", [])
    exp = selected.get("exp", [])
    shard = selected.get("shard", [])
    orundum_trade = selected.get("orundum", [])
    power = selected.get("power", [])
    lmd = sum(float((c.get("trade") or {}).get("lmd_per_day", constants["trade_lmd_base_per_day"] * c["multiplier"])) for c in trade)
    gold_used = sum(float((c.get("trade") or {}).get("gold_per_day", constants["trade_gold_base_per_day"] * c["multiplier"])) for c in trade)
    gold_made = sum(constants["gold_base_per_day"] * c["multiplier"] for c in gold)
    experience = sum(constants["exp_base_per_day"] * c["multiplier"] for c in exp)
    shards_made = sum(24.0 * c["multiplier"] for c in shard)
    shards_used = sum(float((c.get("orundum") or {}).get("shards_per_day", 24.0 * c["multiplier"])) for c in orundum_trade)
    orundum = sum(float((c.get("orundum") or {}).get("orundum_per_day", 240.0 * c["multiplier"])) for c in orundum_trade)
    before_drones = {
        "lmd_per_day": lmd,
        "exp_per_day": experience,
        "gold_made_per_day": gold_made,
        "gold_used_per_day": gold_used,
        "shards_made_per_day": shards_made,
        "shards_used_per_day": shards_used,
        "orundum_per_day": orundum,
    }
    shard_lmd_cost = shards_made * (1600.0 if shard_recipe == "rock" else 1000.0)
    shard_material_used = shards_made * (2.0 if shard_recipe == "rock" else 1.0)
    power_bonus = sum(5.0 + c["efficiency"] for c in power)
    drone_recovery_potential = 1440.0 / constants["drone_recover_minutes"] * (1.0 + power_bonus / 100.0)
    # With a fixed collection cadence the inventory can be emptied at most
    # once per interval. Recovery pauses at the 235-drone cap.
    drones = min(drone_recovery_potential, DRONE_CAPACITY * 24.0 / collection_interval_hours)
    drone_hours = drones * constants["drone_minutes"] / 60.0
    # One drone removes three base minutes, so a full day of a target room is
    # 480 drones regardless of that room's speed.  Keep the per-drone ledger:
    # the scheduler can then spend the accumulated bank at actual collection
    # nodes instead of smearing acceleration continuously across the day.
    profiles: dict[str, dict] = {}
    if trade:
        target = max(trade, key=lambda x: float((x.get("trade") or {}).get("lmd_per_day", 0)))
        econ = target.get("trade") or {}
        profiles["trade"] = {
            "kind": "trade", "label": "贸易订单", "target": f"贸易站：{' / '.join(target['names'])}",
            "target_operators": list(target.get("operators") or []),
            "per_drone": {
                "lmd_per_day": float(econ.get("lmd_per_day", constants["trade_lmd_base_per_day"] * target["multiplier"])) / 480.0,
                "gold_used_per_day": float(econ.get("gold_per_day", constants["trade_gold_base_per_day"] * target["multiplier"])) / 480.0,
            },
        }
    if gold:
        target = max(gold, key=lambda x: x["multiplier"])
        profiles["gold"] = {
            "kind": "gold", "label": "赤金制造", "target": f"赤金制造：{' / '.join(target['names'])}",
            "target_operators": list(target.get("operators") or []),
            "per_drone": {"gold_made_per_day": constants["gold_base_per_day"] * target["multiplier"] / 480.0},
        }
    if exp:
        target = max(exp, key=lambda x: x["multiplier"])
        profiles["exp"] = {
            "kind": "exp", "label": "作战记录制造", "target": f"作战记录制造：{' / '.join(target['names'])}",
            "target_operators": list(target.get("operators") or []),
            "per_drone": {"exp_per_day": constants["exp_base_per_day"] * target["multiplier"] / 480.0},
        }
    if shard:
        target = max(shard, key=lambda x: x["multiplier"])
        profiles["shard"] = {
            "kind": "shard", "label": "源石碎片制造", "target": f"源石碎片制造：{' / '.join(target['names'])}",
            "target_operators": list(target.get("operators") or []),
            "per_drone": {"shards_made_per_day": 24.0 * target["multiplier"] / 480.0},
        }
    if orundum_trade:
        target = max(orundum_trade, key=lambda x: float((x.get("orundum") or {}).get("orundum_per_day", 0)))
        econ = target.get("orundum") or {}
        profiles["orundum"] = {
            "kind": "orundum", "label": "源石订单", "target": f"源石订单：{' / '.join(target['names'])}",
            "target_operators": list(target.get("operators") or []),
            "per_drone": {
                "orundum_per_day": float(econ.get("orundum_per_day", 240.0 * target["multiplier"])) / 480.0,
                "shards_used_per_day": float(econ.get("shards_per_day", 24.0 * target["multiplier"])) / 480.0,
            },
        }

    allocations: list[dict] = []
    base_gold_net = gold_made - gold_used + external_gold_per_day
    balance = None
    if drone_target in {"auto_balance", "auto_lmd"} and "trade" in profiles:
        trade_profile = profiles["trade"]
        trade_gold = float(trade_profile["per_drone"].get("gold_used_per_day", 0))
        gold_per_drone = float((profiles.get("gold") or {}).get("per_drone", {}).get("gold_made_per_day", 0))
        gold_drones = 0.0
        if gold_per_drone > 0:
            # Gold is an intermediate input. The user supplies the acceptable
            # daily inventory change (which can be negative because missions,
            # events, the credit shop, and existing stock subsidize the chain).
            # Use only enough drones on gold to reach that target; every
            # remaining drone goes to orders that realize LMD.
            gold_drones = max(0.0, min(drones, (gold_net_target_per_day - base_gold_net + drones * trade_gold) / (gold_per_drone + trade_gold)))
        projected = base_gold_net + gold_drones * gold_per_drone - (drones - gold_drones) * trade_gold
        all_trade_net = base_gold_net - drones * trade_gold
        all_gold_net = base_gold_net + drones * gold_per_drone
        binding = abs(projected - gold_net_target_per_day) < 1e-6
        regime = (
            "balanced" if binding else
            "trade_saturated" if gold_net_target_per_day < all_trade_net else
            "gold_saturated"
        )
        balance = {
            "policy": "supply_demand_balance", "base_gold_net_per_day": round(base_gold_net, 3),
            "target_gold_net_per_day": round(gold_net_target_per_day, 3),
            "projected_gold_net_per_day": round(projected, 3),
            "all_trade_gold_net_per_day": round(all_trade_net, 3),
            "all_gold_gold_net_per_day": round(all_gold_net, 3),
            "bottleneck": "gold" if gold_drones > 1e-9 else "trade",
            "balanced": binding,
            "binding": binding,
            "regime": regime,
            "reachable": projected >= gold_net_target_per_day - 1e-6,
        }
        if gold_drones > 1e-9 and "gold" in profiles:
            allocations.append({**profiles["gold"], "drones_per_day": gold_drones})
        if drones - gold_drones > 1e-9:
            allocations.append({**trade_profile, "drones_per_day": drones - gold_drones})
    elif drone_target in profiles:
        allocations.append({**profiles[drone_target], "drones_per_day": drones})

    delta = {key: 0.0 for key in before_drones}
    for allocation in allocations:
        amount = float(allocation["drones_per_day"])
        allocation["fraction"] = amount / drones if drones else 0.0
        allocation["equivalent_hours"] = amount * constants["drone_minutes"] / 60.0
        allocation["deltas"] = {
            key: float(value) * amount for key, value in allocation["per_drone"].items()
        }
        for key, value in allocation["deltas"].items():
            delta[key] += value
    lmd += delta["lmd_per_day"]
    experience += delta["exp_per_day"]
    gold_made += delta["gold_made_per_day"]
    gold_used += delta["gold_used_per_day"]
    shards_made += delta["shards_made_per_day"]
    shards_used += delta["shards_used_per_day"]
    orundum += delta["orundum_per_day"]
    shard_lmd_cost += delta["shards_made_per_day"] * (1600.0 if shard_recipe == "rock" else 1000.0)
    shard_material_used += delta["shards_made_per_day"] * (2.0 if shard_recipe == "rock" else 1.0)
    drone_note = " + ".join(
        f"{item['label']} {item['fraction'] * 100:.1f}%" for item in allocations
    ) or "未使用"
    production_net = gold_made - gold_used
    total_net = production_net + external_gold_per_day
    drone_effect = {
        "target_kind": drone_target,
        "target": drone_note,
        "equivalent_hours": round(drone_hours, 3),
        **{key: round(value, 3) for key, value in delta.items()},
        "gold_net_per_day": round(delta["gold_made_per_day"] - delta["gold_used_per_day"], 3),
        "allocations": allocations,
        "balance": balance,
    }
    return {
        "lmd_per_day": round(lmd),
        "lmd_shard_cost_per_day": round(shard_lmd_cost),
        "lmd_net_after_shards_per_day": round(lmd - shard_lmd_cost),
        "exp_per_day": round(experience),
        "orundum_per_day": round(orundum, 2),
        "shards_made_per_day": round(shards_made, 2),
        "shards_used_per_day": round(shards_used, 2),
        "shards_net_per_day": round(shards_made - shards_used, 2),
        "shard_recipe": shard_recipe,
        "shard_material_used_per_day": round(shard_material_used, 2),
        "gold_made_per_day": round(gold_made, 2),
        "gold_used_per_day": round(gold_used, 2),
        "gold_production_net_per_day": round(production_net, 2),
        "gold_external_per_day": round(external_gold_per_day, 2),
        "gold_net_per_day": round(total_net, 2),
        "gold_inventory": round(gold_inventory, 2),
        "gold_inventory_days": None if total_net >= 0 else round(gold_inventory / -total_net, 1),
        "shard_inventory": round(shard_inventory, 2),
        "collection_interval_hours": round(collection_interval_hours, 2),
        "inventory_policy": "working_stock",
        "drones_per_day": round(drones, 1),
        "drones_recovery_potential_per_day": round(drone_recovery_potential, 1),
        "drone_overflow_lost_per_day": round(max(0.0, drone_recovery_potential - drones), 1),
        "drone_capacity": DRONE_CAPACITY,
        "drone_hours_per_day": round(drone_hours, 2),
        "drone_target": drone_note,
        "drone_effect": drone_effect,
        "power_bonus": round(power_bonus, 2),
    }


def _warnings(selected: dict[str, list[dict]], metrics: dict) -> list[str]:
    warnings = []
    drone_balance = (metrics.get("drone_effect") or {}).get("balance")
    if drone_balance and not drone_balance.get("reachable"):
        warnings.append(
            f"即使把本班全部无人机投向赤金，预计赤金净流量仍为 {drone_balance['projected_gold_net_per_day']:+.1f}/日，"
            f"无法达到用户允许的 {drone_balance['target_gold_net_per_day']:+.1f}/日；本班已采用最接近目标的分配。"
        )
    net = metrics["gold_net_per_day"]
    production_net = metrics.get("gold_production_net_per_day", net)
    external = metrics.get("gold_external_per_day", 0)
    if production_net < -5 and external > 0:
        warnings.append(
            f"制造站与贸易站本身每天相差 {production_net:.1f} 根赤金；计入外部 +{external:.1f}/日后，"
            f"库存总变化为 {net:+.1f}/日。赤金是中间品，负的制造净流量不等于方案低效。"
        )
    elif net < -5:
        days = metrics.get("gold_inventory_days")
        suffix = f"；按当前库存可维持约 {days:.1f} 天" if days is not None and days > 0 else ""
        warnings.append(f"当前方案每天预计净消耗 {-net:.1f} 根赤金{suffix}。这是库存流量提示，不会被直接判为错误方案。")
    elif net > 8:
        warnings.append(f"计入外部来源后每天预计净增加 {net:.1f} 根赤金；这是库存流量提示，可按实际积压情况调整制造站配方。")
    unresolved = sorted({item for values in selected.values() for c in values for item in c.get("unresolved", [])})
    if unresolved:
        warnings.append("以下特殊技能暂按保守值处理：" + "、".join(unresolved[:8]) + ("……" if len(unresolved) > 8 else ""))
    if any(c.get("confidence") == "maa_combo" for values in selected.values() for c in values):
        warnings.append("MAA 等效分只用于候选组合排序；但书、龙舌兰和订单品质的资源流已按逐订单期望单独计算。跨房间体系仍需结合控制中枢、宿舍等全局状态复核。")
    if any("线性暖机" in note for c in selected.get("trade", []) for note in (c.get("trade") or {}).get("notes", [])):
        warnings.append("订单品质已按班次暖机计算；PRTS 公开了峰值分布和达到峰值所需时间，但未公开完整曲线，峰值前暂采用线性插值，并在快进模拟中保留这一假设。")
    return warnings


def _room_rows(selected: dict[str, list[dict]]) -> list[dict]:
    labels = {"trade": "龙门贸易站", "orundum": "源石订单贸易站", "gold": "赤金制造站",
              "exp": "作战记录制造站", "shard": "源石碎片制造站", "power": "发电站"}
    rows = []
    for key in ("trade", "orundum", "gold", "exp", "shard", "power"):
        for index, candidate in enumerate(selected.get(key, []), 1):
            rows.append({
                "key": key,
                "room": f"{labels[key]} {index}",
                **candidate,
            })
    return rows


def _room_weighted_selection(rotation: dict) -> dict[str, list[dict]]:
    """Blend A/B room outputs by each physical room's independent duty ratio."""
    teams = rotation.get("teams") or {}
    durations = rotation.get("room_work_hours") or {}
    buckets: dict[str, dict[str, list[dict]]] = {"A": {}, "B": {}}
    for label in ("A", "B"):
        for room in (teams.get(label) or {}).get("rooms", []):
            buckets[label].setdefault(str(room.get("key") or ""), []).append(room)
    selected: dict[str, list[dict]] = {}
    for key, rooms_a in buckets["A"].items():
        rooms_b = buckets["B"].get(key, [])
        for index, room_a in enumerate(rooms_a):
            if index >= len(rooms_b):
                continue
            room_b = rooms_b[index]
            room_name = str(room_a.get("room") or "")
            pair_hours = durations.get(room_name) or {"A": 1.0, "B": 1.0}
            total = max(1e-9, float(pair_hours["A"]) + float(pair_hours["B"]))
            wa, wb = float(pair_hours["A"]) / total, float(pair_hours["B"]) / total
            blended = {
                **room_a,
                "operators": [*room_a.get("operators", []), *room_b.get("operators", [])],
                "names": [f"A：{' / '.join(room_a.get('names', []))}", f"B：{' / '.join(room_b.get('names', []))}"],
                "efficiency": float(room_a.get("efficiency", 0) or 0) * wa + float(room_b.get("efficiency", 0) or 0) * wb,
                "multiplier": float(room_a.get("multiplier", 1) or 1) * wa + float(room_b.get("multiplier", 1) or 1) * wb,
                "time_profiles": [],
            }
            if key == "trade":
                trade_a, trade_b = room_a.get("trade") or {}, room_b.get("trade") or {}
                blended["trade"] = {
                    "lmd_per_day": float(trade_a.get("lmd_per_day", 0) or 0) * wa + float(trade_b.get("lmd_per_day", 0) or 0) * wb,
                    "gold_per_day": float(trade_a.get("gold_per_day", 0) or 0) * wa + float(trade_b.get("gold_per_day", 0) or 0) * wb,
                }
            elif key == "orundum":
                order_a, order_b = room_a.get("orundum") or {}, room_b.get("orundum") or {}
                blended["orundum"] = {
                    "orundum_per_day": float(order_a.get("orundum_per_day", 0) or 0) * wa + float(order_b.get("orundum_per_day", 0) or 0) * wb,
                    "shards_per_day": float(order_a.get("shards_per_day", 0) or 0) * wa + float(order_b.get("shards_per_day", 0) or 0) * wb,
                }
            selected.setdefault(key, []).append(blended)
    return selected


def _assignment_signature(selected: dict[str, list[dict]]) -> tuple:
    """Compare real room teams while ignoring interchangeable room numbers."""
    return tuple(
        (key, tuple(sorted(tuple(sorted(room.get("operators") or [])) for room in rooms)))
        for key, rooms in sorted(selected.items())
    )


def _result_assignment_signature(result: dict) -> tuple:
    teams = (result.get("rotation") or {}).get("teams") or {"A": result}
    return tuple(
        (team, _assignment_signature({
            key: [room for room in plan.get("rooms", []) if room.get("key") == key]
            for key in sorted({room.get("key") for room in plan.get("rooms", [])})
        }))
        for team, plan in sorted(teams.items())
    )


def _production_allocation_audit(result: dict, roster: list[dict], catalog: dict) -> dict:
    """Expose how operators eligible for several production facilities were resolved."""
    facility_names = {"TRADING": "贸易站", "MANUFACTURE": "制造站", "POWER": "发电站"}
    teams = (result.get("rotation") or {}).get("teams") or {
        "A": {"rooms": result.get("rooms", []), "support_rooms": result.get("support_rooms", [])}
    }
    assigned: dict[str, dict[str, list[str]]] = {}
    duplicates = []
    for label, plan in teams.items():
        counts: dict[str, list[str]] = {}
        for room in [*(plan.get("support_rooms") or []), *(plan.get("rooms") or [])]:
            for operator_id in room.get("operators", []):
                counts.setdefault(operator_id, []).append(room.get("room", "未知设施"))
        for operator_id, rooms in counts.items():
            assigned.setdefault(operator_id, {})[label] = rooms
            if len(rooms) > 1:
                duplicates.append({"team": label, "operator_id": operator_id, "rooms": rooms})
    rows = []
    for operator in roster:
        skills = active_skills(operator, catalog)
        facilities = sorted({skill.get("room") for skill in skills if skill.get("room") in facility_names})
        if len(facilities) < 2:
            continue
        definition = catalog["operators"].get(operator.get("id"), {})
        rows.append({
            "operator_id": operator.get("id"),
            "operator": definition.get("name", operator.get("name", operator.get("id"))),
            "eligible_facilities": [facility_names[item] for item in facilities],
            "assignments": assigned.get(operator.get("id"), {}),
            "skills": [
                {"name": skill.get("name"), "facility": facility_names.get(skill.get("room")), "icon": skill.get("icon")}
                for skill in skills if skill.get("room") in facility_names
            ],
        })
    return {
        "multi_facility_operators": rows,
        "simultaneous_duplicates": duplicates,
        "constraint": "同一班次内每名干员至多进入一个设施；贸易、制造和发电候选在同一个集合打包问题中竞争。",
        "rotation_scope": "A/B 两班目前顺序生成，跨班不是联合全局最优证明；两班时段不重叠，未启用菲亚梅塔时干员也不会跨班复用。",
    }


def _result_room_differences(current: dict, alternate: dict) -> list[dict]:
    current_teams = (current.get("rotation") or {}).get("teams") or {"A": current}
    alternate_teams = (alternate.get("rotation") or {}).get("teams") or {"A": alternate}
    labels = {"trade": "龙门贸易站", "orundum": "源石贸易站", "gold": "赤金制造站",
              "exp": "作战记录制造站", "shard": "源石碎片制造站", "power": "发电站"}
    rows = []
    for team in sorted(set(current_teams) | set(alternate_teams)):
        current_rooms = current_teams.get(team, {}).get("rooms", [])
        alternate_rooms = alternate_teams.get(team, {}).get("rooms", [])
        for key in sorted({room.get("key") for room in current_rooms + alternate_rooms}):
            current_groups = sorted(tuple(sorted(room.get("names") or [])) for room in current_rooms if room.get("key") == key)
            alternate_groups = sorted(tuple(sorted(room.get("names") or [])) for room in alternate_rooms if room.get("key") == key)
            if current_groups != alternate_groups:
                rows.append({
                    "team": team, "key": key, "room_type": labels.get(key, key),
                    "current": [list(group) for group in current_groups],
                    "alternate": [list(group) for group in alternate_groups],
                })
    return rows


def _control_row(team: list[dict], context: BaseContext) -> dict | None:
    if not team:
        return None
    return {
        "key": "control",
        "room": "控制中枢",
        "operators": [operator["id"] for operator in team],
        "names": [operator["name"] for operator in team],
        "efficiency": context.control_trade_speed + context.control_factory_speed,
        "equivalent_efficiency": context.control_trade_speed + context.control_factory_speed,
        "confidence": "state_model",
        "group": None,
        "unresolved": [],
        "mechanic_notes": list(context.audit),
        "details": [
            {
                "operator": operator["name"],
                "skills": [
                    {"name": skill["name"], "description": skill["description"], "value": 0,
                     "icon": skill.get("icon", "")}
                    for skill in operator["skills"] if skill.get("room") == "CONTROL"
                ],
                "value": 0,
            }
            for operator in team
        ],
    }


def _support_rows(
    operators: list[dict], used: set[str], shift_hours: float, excluded_ids: set[str] | None = None,
) -> list[dict]:
    """Choose reception/office workers without reusing production operators."""
    excluded_ids = excluded_ids or set()
    available = [operator for operator in operators if operator["id"] not in used and operator["id"] not in excluded_ids]

    def skill_score(operator: dict, room: str) -> float:
        skills = [skill for skill in operator["skills"] if skill.get("room") == room]
        if not skills:
            return -1000.0
        score = sum(float(skill.get("efficiency") or 0) for skill in skills)
        # Avoid a worker who reaches zero morale exactly at an 8h handover or
        # earlier in a 12h shift when a nearly equal sustainable option exists.
        if any("心情每小时消耗+2" in str(skill.get("description") or "") for skill in skills):
            score -= 20.0 if shift_hours <= 8 else 100.0
        return score

    meeting = sorted(available, key=lambda operator: skill_score(operator, "MEETING"), reverse=True)[:2]
    meeting_ids = {operator["id"] for operator in meeting}
    office_pool = [operator for operator in available if operator["id"] not in meeting_ids]
    office = sorted(office_pool, key=lambda operator: skill_score(operator, "HIRE"), reverse=True)[:1]

    def row(key: str, room_name: str, team: list[dict], skill_room: str) -> dict | None:
        if not team:
            return None
        return {
            "key": key, "room": room_name,
            "operators": [operator["id"] for operator in team],
            "names": [operator["name"] for operator in team],
            "efficiency": round(sum(max(0.0, skill_score(operator, skill_room)) for operator in team), 3),
            "equivalent_efficiency": 0, "confidence": "direct", "group": None,
            "unresolved": [], "mechanic_notes": [], "time_profiles": [], "context_effects": [],
            "details": [{
                "operator": operator["name"],
                "skills": [{"name": skill["name"], "description": skill["description"],
                            "value": skill.get("efficiency", 0), "icon": skill.get("icon", "")}
                           for skill in operator["skills"] if skill.get("room") == skill_room],
                "value": max(0.0, skill_score(operator, skill_room)),
            } for operator in team],
        }

    return [item for item in (
        row("reception", "会客室", meeting, "MEETING"),
        row("office", "人力办公室", office, "HIRE"),
    ) if item]


def _cross_room_flows(
    selected: dict[str, list[dict]], control_team: list[dict], context: BaseContext, catalog: dict
) -> list[dict]:
    """Build a presentation-safe graph from the exact effects used in scoring."""
    labels = {"trade": "龙门贸易站", "orundum": "源石订单贸易站", "gold": "赤金制造站",
              "exp": "作战记录制造站", "shard": "源石碎片制造站", "power": "发电站"}
    grouped: dict[str, dict] = {}
    for key in ("trade", "orundum", "gold", "exp", "shard", "power"):
        for index, room in enumerate(selected.get(key, []), 1):
            for effect in room.get("context_effects", []):
                state = effect["state"]
                flow = grouped.setdefault(state, {
                    "id": state,
                    "label": effect["label"],
                    "value": effect["available"],
                    "unit": {"catnip": "个", "formula_types": "类", "gold_lines": "条",
                             "platform_power_count": "台", "abyssal_factory_count": "名",
                             "control_trade_speed": "%", "control_factory_speed": "%"}.get(state, "点"),
                    "sources": [], "consumers": [],
                })
                flow["value"] = max(float(flow["value"]), float(effect["available"]))
                contribution = float(effect["contribution_percent"])
                if key == "trade":
                    base_output = float((room.get("trade") or {}).get("lmd_per_day", 0)) / max(float(room.get("multiplier", 1)), 1e-9)
                    output_delta, output_unit = base_output * contribution / 100.0, "龙门币/日"
                elif key == "orundum":
                    output_delta, output_unit = 240.0 * contribution / 100.0, "合成玉/日"
                elif key == "gold":
                    output_delta, output_unit = catalog["constants"]["gold_base_per_day"] * contribution / 100.0, "赤金/日"
                elif key == "exp":
                    output_delta, output_unit = catalog["constants"]["exp_base_per_day"] * contribution / 100.0, "经验/日"
                elif key == "shard":
                    output_delta, output_unit = 24.0 * contribution / 100.0, "碎片/日"
                else:
                    output_delta, output_unit = 0.0, ""
                flow["consumers"].append({
                    "room": f"{labels[key]} {index}",
                    "operators": room.get("names", []),
                    "contribution_percent": contribution,
                    "output_delta_per_day": round(output_delta, 2),
                    "output_unit": output_unit,
                    "detail": effect["detail"],
                })

    control_icons = {operator["id"]: operator["icons"] for operator in control_team}
    control_names = {operator["id"]: operator["name"] for operator in control_team}
    mh_count = len(set(control_icons) & MONSTER_HUNTER_IDS)
    source_rules = {
        "control_trade_speed": [("bskill_ctrl_t_spd", lambda _: "全贸易站 +7%")],
        "control_factory_speed": [("bskill_ctrl_p_spd", lambda _: "全制造站效率")],
        "catnip": [
            ("bskill_ctrl_cost_felyne", lambda _: "+8 木天蓼"),
            ("bskill_ctrl_felyne", lambda _: f"怪物猎人小队 {mh_count} 名 × 2 = +{mh_count * 2}"),
        ],
        "abyssal_factory_count": [
            ("bskill_ctrl_aegir2", lambda _: "启用每名 +10% 的深海猎人协同"),
            ("bskill_ctrl_aegir", lambda _: "启用每名 +5% 的深海猎人协同"),
        ],
    }
    if context.abyssal_factory_percent_per_hunter and "abyssal_factory_count" not in grouped:
        grouped["abyssal_factory_count"] = {
            "id": "abyssal_factory_count", "label": "深海猎人协同", "value": 0,
            "unit": "名", "sources": [], "consumers": [],
        }
    for state, flow in grouped.items():
        for icon, describe in source_rules.get(state, []):
            for operator_id, icons in control_icons.items():
                if icon in icons:
                    flow["sources"].append({"name": control_names[operator_id], "detail": describe(operator_id)})
        if state == "formula_types":
            flow["sources"].append({"name": "制造站布局", "detail": f"当前生产 {context.formula_types:g} 类配方"})
        elif state == "gold_lines":
            flow["sources"].append({"name": "制造站布局", "detail": f"{context.gold_lines:g} 条赤金生产线"})
        elif state == "platform_power_count":
            names = [name for room in selected.get("power", []) for op, name in zip(room["operators"], room["names"]) if op in {
                "char_285_medic2", "char_286_cast3", "char_376_therex", "char_4000_jnight",
                "char_4093_frston", "char_4136_phonor", "char_4188_confes", "char_4227_gallus",
            }]
            flow["sources"].extend({"name": name, "detail": "发电站内提供 1 台作业平台"} for name in names)
        elif state == "abyssal_factory_count":
            names = [name for room in selected.get("gold", []) + selected.get("exp", [])
                     for op, name in zip(room["operators"], room["names"]) if op in ABYSSAL_HUNTER_IDS]
            flow["sources"].append({"name": "制造站中的深海猎人", "detail": "、".join(names) or "无"})
        if not flow["sources"]:
            flow["sources"].append({"name": "基建全局状态", "detail": f"当前可用 {flow['value']:g}{flow['unit']}"})
        flow["total_contribution_percent"] = round(sum(x["contribution_percent"] for x in flow["consumers"]), 3)
        flow["active"] = bool(flow["consumers"] and flow["total_contribution_percent"])
    return sorted(grouped.values(), key=lambda x: (-x["total_contribution_percent"], x["label"]))


def optimize(payload: dict, catalog: dict, include_frontier: bool = True) -> dict:
    roster = payload.get("operators") or []
    operators = prepare_operators(roster, catalog)
    reusable_ids = {str(operator_id) for operator_id in payload.get("_reusable_operator_ids", []) if operator_id}
    fiammetta = next((operator for operator in operators if operator["id"] == "char_300_phenxi"), None)
    fiammetta_enabled = bool(payload.get("enable_fiammetta", True)) and fiammetta is not None
    if fiammetta_enabled:
        operators = [operator for operator in operators if operator["id"] != fiammetta["id"]]
    lock_dorm_helper = bool(payload.get("lock_dorm_helper", True)) and not bool(payload.get("_rotation_internal"))
    dorm_helper = choose_dorm_helper(operators, str(payload.get("dorm_helper_id") or "")) if lock_dorm_helper else None
    if dorm_helper:
        operators = [operator for operator in operators if operator["id"] != dorm_helper["id"]]
    if len(operators) < 21:
        raise ValueError("预留宿舍恢复位后，左侧产出设施的一班需要 21 个不同干员；当前有效干员数量不足")
    layouts = {"243": (2, 4, 3), "153": (1, 5, 3), "333": (3, 3, 3)}
    layout_key = str(payload.get("base_layout", "243"))
    if layout_key not in layouts:
        raise ValueError("基建布局必须是 2-4-3、1-5-3 或 3-3-3")
    trade_count, factory_count, power_count = layouts[layout_key]
    shard_count = max(0, min(factory_count, int(payload.get("shard_factories", 0))))
    exp_count = max(0, min(factory_count - shard_count, int(payload.get("exp_factories", 1))))
    gold_count = factory_count - shard_count - exp_count
    orundum_count = max(0, min(trade_count, int(payload.get("orundum_trades", 0))))
    lmd_trade_count = trade_count - orundum_count
    drone_target = payload.get("drone_target", "trade")
    gold_net_target_per_day = max(-10000.0, min(10000.0, float(payload.get("gold_net_target_per_day", -20))))
    objective_mode = str(payload.get("objective_mode", "layout_output"))
    if objective_mode not in {"layout_output", "sanity_value"}:
        raise ValueError("排班目标必须是按布局产出或等效理智价值")
    shard_recipe = "device" if payload.get("shard_recipe") == "device" else "rock"
    keep = max(120, min(600, int(payload.get("candidate_limit", 320))))
    groups = [GroupSpec("trade", lmd_trade_count), GroupSpec("orundum", orundum_count),
              GroupSpec("gold", gold_count), GroupSpec("exp", exp_count), GroupSpec("shard", shard_count),
              GroupSpec("power", power_count)]
    groups = [g for g in groups if g.count]
    model_shift_hours = max(1.0, min(24.0, float(payload.get("model_shift_hours", payload.get("shift_hours", 8)))))
    model_shift_hours_b = max(1.0, min(24.0, float(payload.get("_model_shift_hours_b", model_shift_hours))))
    base_context = BaseContext(
        shift_hours=model_shift_hours,
        collection_interval_hours=max(1.0, min(24.0, float(payload.get("collection_interval_hours", payload.get("shift_hours", 8))))),
        gold_lines=gold_count,
        formula_types=sum(bool(x) for x in (gold_count, exp_count, shard_count)),
        num_trade=trade_count,
        num_factory=factory_count,
        num_power=power_count,
    )
    external_gold_per_day = max(0.0, min(10000.0, float(payload.get("external_gold_per_day", 0))))
    gold_inventory = max(0.0, min(10000000.0, float(payload.get("gold_inventory", 0))))
    shard_inventory = max(0.0, min(10000000.0, float(payload.get("shard_inventory", 0))))
    coverage = mechanism_coverage(operators)
    catalog_operators = prepare_operators(
        [{"id": op_id, "elite": 2, "level": 90} for op_id in catalog["operators"]],
        catalog,
    )
    catalog_coverage = mechanism_coverage(catalog_operators)
    # Compare production-distinct control-center states against the actual
    # downstream room solution.  On very large synthetic catalogs, retain the
    # former single-state path to keep regression runs laptop-friendly.
    control_pool = [operator for operator in operators if operator["id"] not in reusable_ids]
    control_options = select_control_options(control_pool, base_context, 12 if len(operators) <= 180 else 2)
    best_plan: tuple[float, list[dict], BaseContext, dict, str, dict] | None = None
    for control_team_option, context_option in control_options:
        control_ids = {operator["id"] for operator in control_team_option}
        production_operators = [operator for operator in operators if operator["id"] not in control_ids]
        power_seed = generate_candidates(production_operators, "power", catalog, keep, context_option)[:3]
        context_option.platform_power_count = platform_count(power_seed)
        if context_option.platform_power_count:
            context_option.audit.append(f"发电站：作业平台 {context_option.platform_power_count} 台")
        selected_option: dict[str, list[dict]] = {}
        candidates_option: dict[str, list[dict]] = {}
        solver_option = ""
        production_by_id = {operator["id"]: operator for operator in production_operators}
        for attempt in range(5):
            candidates_option = {}
            for group in groups:
                values = generate_candidates(production_operators, group.key, catalog, keep, context_option)
                if reusable_ids:
                    # Preserve a complete no-reuse backbone.  Otherwise the
                    # top candidate slice may be saturated by A-team stars and
                    # become infeasible once the one-target constraint is added.
                    no_reuse_pool = [operator for operator in production_operators if operator["id"] not in reusable_ids]
                    values.extend(generate_candidates(no_reuse_pool, group.key, catalog, keep, context_option))
                    unique = {tuple(candidate["operators"]): candidate for candidate in values}
                    values = sorted(
                        unique.values(),
                        key=lambda candidate: (
                            candidate.get("equivalent_efficiency", candidate["efficiency"]),
                            candidate["confidence"] != "estimated",
                        ),
                        reverse=True,
                    )[: keep * 2]
                candidates_option[group.key] = values
            for group in groups:
                if len(candidates_option[group.key]) < group.count:
                    raise ValueError(f"{group.key} 的候选组合不足")
            selected_option, solver_option = _solve(
                candidates_option, groups, objective_mode, reusable_ids
            )
            count = platform_count(selected_option.get("power", []))
            factory_rooms = selected_option.get("gold", []) + selected_option.get("exp", []) + selected_option.get("shard", [])
            abyssal_count = sum(
                operator in ABYSSAL_HUNTER_IDS
                for room in factory_rooms for operator in room.get("operators", [])
            )
            assigned_ids = {
                operator_id
                for rooms in selected_option.values() for room in rooms
                for operator_id in room.get("operators", [])
            } | control_ids
            assigned_operators = [
                operator for operator in operators if operator["id"] in assigned_ids
            ]
            group_counts: dict[str, int] = {}
            nation_counts: dict[str, int] = {}
            for operator in assigned_operators:
                if operator.get("group_id"):
                    group_counts[operator["group_id"]] = group_counts.get(operator["group_id"], 0) + 1
                if operator.get("nation_id"):
                    nation_counts[operator["nation_id"]] = nation_counts.get(operator["nation_id"], 0) + 1
            power_nation_counts: dict[str, int] = {}
            for room in selected_option.get("power", []):
                for operator_id in room.get("operators", []):
                    operator = production_by_id.get(operator_id)
                    if operator and operator.get("nation_id"):
                        nation = operator["nation_id"]
                        power_nation_counts[nation] = power_nation_counts.get(nation, 0) + 1
            trade_operator_ids = sorted({
                operator_id
                for key in ("trade", "orundum") for room in selected_option.get(key, [])
                for operator_id in room.get("operators", [])
            })
            all_selected_rooms = [room for rooms in selected_option.values() for room in rooms]
            elite_facilities = sum(
                any(int((production_by_id.get(operator_id) or {}).get("elite", 0)) >= 1
                    for operator_id in room.get("operators", []))
                for room in all_selected_rooms
            ) + int(any(int(operator.get("elite", 0)) >= 1 for operator in control_team_option))
            sui_facilities = sum(
                any(operator_id in SUI_IDS for operator_id in room.get("operators", []))
                for room in all_selected_rooms
            ) + int(any(operator["id"] in SUI_IDS for operator in control_team_option))
            state_stable = (
                count == context_option.platform_power_count
                and abyssal_count == context_option.abyssal_factory_count
                and group_counts == context_option.working_group_counts
                and nation_counts == context_option.working_nation_counts
                and power_nation_counts == context_option.power_nation_counts
                and sorted(assigned_ids) == context_option.working_operator_ids
                and trade_operator_ids == context_option.trade_operator_ids
                and elite_facilities == context_option.elite_staffed_facility_count
                and sui_facilities == context_option.sui_staffed_facility_count
            )
            if state_stable:
                break
            if attempt == 4:
                context_option.audit.append("离散跨房间状态在 5 次迭代内未收敛；当前结果按最后一次状态估算")
                break
            context_option.platform_power_count = count
            context_option.audit = [line for line in context_option.audit if not line.startswith("发电站：作业平台")]
            if count:
                context_option.audit.append(f"发电站：作业平台 {count} 台")
            context_option.abyssal_factory_count = abyssal_count
            context_option.working_group_counts = group_counts
            context_option.working_nation_counts = nation_counts
            context_option.power_nation_counts = power_nation_counts
            context_option.working_operator_ids = sorted(assigned_ids)
            context_option.trade_operator_ids = trade_operator_ids
            context_option.elite_staffed_facility_count = elite_facilities
            context_option.sui_staffed_facility_count = sui_facilities
            context_option.audit = [line for line in context_option.audit if not line.startswith("制造站：深海猎人")]
            if abyssal_count:
                context_option.audit.append(f"制造站：深海猎人 {abyssal_count} 名")
        score = sum(
            _utility(candidate, group.key, objective_mode)
            for group in groups for candidate in selected_option.get(group.key, [])
        )
        plan = (score, control_team_option, context_option, selected_option, solver_option, candidates_option)
        if best_plan is None or score > best_plan[0]:
            best_plan = plan
    assert best_plan is not None
    _, control_team, context, selected, solver, candidates = best_plan
    if len(control_options) > 1:
        solver += f" · 比较 {len(control_options)} 种控制中枢状态"
    metrics = _metrics(
        selected, catalog, drone_target, external_gold_per_day, gold_inventory, shard_recipe,
        shard_inventory, base_context.collection_interval_hours, gold_net_target_per_day,
    )
    alternate_mode = "layout_output" if objective_mode == "sanity_value" else "sanity_value"
    alternate_selected, alternate_solver = _solve(candidates, groups, alternate_mode, reusable_ids)
    alternate_metrics = _metrics(
        alternate_selected, catalog, drone_target, external_gold_per_day, gold_inventory, shard_recipe,
        shard_inventory, base_context.collection_interval_hours, gold_net_target_per_day,
    )
    same_assignment = _assignment_signature(selected) == _assignment_signature(alternate_selected)
    control_row = _control_row(control_team, context)
    occupied = {operator for values in selected.values() for room in values for operator in room.get("operators", [])}
    occupied.update(operator["id"] for operator in control_team)
    auxiliary_rows = _support_rows(operators, occupied, base_context.shift_hours, reusable_ids)
    result = {
        "solver": solver,
        "search_audit": {
            "claim": "候选集内协调解，不是全组合全周期全局最优证明",
            "candidate_operator_pool": "每类产出设施保留最多 42 名相关干员（发电站 32 名），并为每名高价值干员保留代表组合与多条互斥候选链",
            "candidate_retain_target_per_room_type": keep,
            "candidate_counts": {key: len(value) for key, value in candidates.items()},
            "control_states_compared": len(control_options),
            "modeled_shift_hours": model_shift_hours,
            "modeled_shift_hours_b": model_shift_hours_b,
            "duration_refinements": int(payload.get("_duration_refinement_count", 0)),
            "rotation_strategy": "A/B 班组仍分两阶段生成；候选范围已扩大，随后在所有收取节点组合上优化两队工时占比",
        },
        "layout": {"name": layout_key, "trade": trade_count, "lmd_trade": lmd_trade_count,
                   "orundum_trade": orundum_count, "factory": factory_count, "gold": gold_count,
                   "exp": exp_count, "shard": shard_count, "power": power_count},
        "objective": {
            "mode": objective_mode,
            "label": "固定产品布局：一图流等效理智最大化" if objective_mode == "sanity_value" else "固定产品布局：总产能等权最大化",
            "hard_constraints": f"{lmd_trade_count} 龙门贸易站 / {orundum_count} 源石贸易站 / {gold_count} 赤金站 / {exp_count} 经验站 / {shard_count} 碎片站",
            "comparison": {
                "alternate_mode": alternate_mode,
                "alternate_label": "固定产品布局：一图流等效理智最大化" if alternate_mode == "sanity_value" else "固定产品布局：总产能等权最大化",
                "same_semantic_assignment": same_assignment,
                "scope": "同一控制中枢状态与同一候选集",
                "solver": alternate_solver,
                "current_scores": {
                    "layout_output": round(sum(_utility(room, key, "layout_output") for key, rooms in selected.items() for room in rooms), 6),
                    "sanity_value": round(sum(_utility(room, key, "sanity_value") for key, rooms in selected.items() for room in rooms), 6),
                },
                "alternate_scores": {
                    "layout_output": round(sum(_utility(room, key, "layout_output") for key, rooms in alternate_selected.items() for room in rooms), 6),
                    "sanity_value": round(sum(_utility(room, key, "sanity_value") for key, rooms in alternate_selected.items() for room in rooms), 6),
                },
                "alternate_metrics": {key: alternate_metrics.get(key) for key in (
                    "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day", "gold_net_per_day", "orundum_per_day"
                )},
            },
        },
        "metrics": metrics,
        "valuation": public_valuation(),
        "rooms": _room_rows(selected),
        "support_rooms": ([control_row] if control_row else []) + auxiliary_rows,
        "base_state": context.public(),
        "cross_room_flows": _cross_room_flows(selected, control_team, context, catalog),
        "mechanism_coverage": coverage,
        "catalog_mechanism_coverage": catalog_coverage,
        "warnings": _warnings(selected, metrics),
        "morale": analyze_morale(_room_rows(selected), roster, catalog, payload.get("shift_hours", 8)),
        "dorm_helper": dorm_helper,
        "fiammetta": {
            "supported": True,
            "owned": fiammetta is not None,
            "enabled": fiammetta_enabled,
            "active": False,
            "operator_id": "char_300_phenxi",
            "operator_name": "菲亚梅塔",
            "target_operator_id": None,
            "target_operator_name": None,
            "note": (
                "已预留菲亚梅塔宿舍位；生成 B 班时允许恰好一名 A 班生产干员作为换班点心情交换目标。"
                if fiammetta_enabled else
                "机制已支持；当前 Box 未拥有或用户已关闭，因此本次不激活。"
            ),
        },
        "frontier": [],
    }
    if coverage["partial_count"]:
        names = "、".join(f"{item['operator']}：{item['skill']}" for item in coverage["partial"][:6])
        result["warnings"].append(
            f"当前 Box 的产出相关主动技能机制覆盖率 {coverage['exact_percent']}%（{coverage['exact_count']}/{coverage['total_relevant']}）；"
            f"仍需补公式：{names}{'……' if coverage['partial_count'] > 6 else ''}。"
        )
    if catalog_coverage["partial_count"]:
        result["warnings"].append(
            f"当前 Box 已解锁技能覆盖 {coverage['exact_count']}/{coverage['total_relevant']}；"
            f"全干员满练目录覆盖 {catalog_coverage['exact_count']}/{catalog_coverage['total_relevant']} "
            f"（{catalog_coverage['exact_percent']}%）。目录剩余机制会继续显示为未覆盖，不能外推为全游戏 100%。"
        )
    if payload.get("include_rotation") and not payload.get("_rotation_internal"):
        assigned_a = {
            operator_id
            for room in [*result.get("support_rooms", []), *result.get("rooms", [])]
            for operator_id in room.get("operators", [])
        }
        if dorm_helper:
            assigned_a.add(dorm_helper["id"])
        if fiammetta_enabled:
            assigned_a.add(fiammetta["id"])
        production_a_ids = {
            operator_id for room in result.get("rooms", []) for operator_id in room.get("operators", [])
        }
        reusable_a_ids = production_a_ids if fiammetta_enabled else set()
        remaining = [operator for operator in roster if operator.get("id") not in assigned_a]
        if reusable_a_ids:
            remaining.extend(operator for operator in roster if operator.get("id") in reusable_a_ids)
        if len(remaining) >= 21:
            second_payload = {
                **payload, "operators": remaining, "include_rotation": False,
                "_rotation_internal": True, "lock_dorm_helper": False,
                "model_shift_hours": model_shift_hours_b,
                "enable_fiammetta": False,
                "_reusable_operator_ids": sorted(reusable_a_ids),
            }
            team_b = optimize(second_payload, catalog, include_frontier=False)
            assigned_b = {
                operator_id
                for room in [*team_b.get("support_rooms", []), *team_b.get("rooms", [])]
                for operator_id in room.get("operators", [])
            }
            reused = sorted(reusable_a_ids & assigned_b)
            target_id = reused[0] if reused else None
            target_name = next((operator.get("name") for operator in roster if operator.get("id") == target_id), None)
            result["fiammetta"].update({
                "active": bool(target_id),
                "target_operator_id": target_id,
                "target_operator_name": target_name,
                "note": (
                    f"菲亚梅塔固定恢复 {target_name}；该干员可出现在不重叠的 A/B 时间状态，交换后按菲亚梅塔 6 心情/小时重新充满。"
                    if target_id else
                    "已预留菲亚梅塔，但扩大候选搜索后没有任何 A 班目标进入紧接着的 B 班能提高方案，本循环不执行心情交换。"
                ),
            })
            result["rotation"] = build_rotation(
                result, team_b, float(payload.get("max_work_hours", payload.get("shift_hours", 8))),
                schedule_mode=str(payload.get("schedule_mode", "morale_aware")),
                collection_interval_hours=base_context.collection_interval_hours,
                morale_floor=float(payload.get("morale_floor", 1)),
                max_work_hours=float(payload.get("max_work_hours", payload.get("shift_hours", 24))),
                dorm_helper=dorm_helper,
                fiammetta=result["fiammetta"],
                objective_mode=objective_mode,
            )
            if result["rotation"].get("schedule_mode") == "staggered":
                weighted_selected = _room_weighted_selection(result["rotation"])
                weighted_metrics = _metrics(
                    weighted_selected, catalog, drone_target, external_gold_per_day,
                    gold_inventory, shard_recipe, shard_inventory,
                    base_context.collection_interval_hours, gold_net_target_per_day,
                )
                curve = build_staggered_production_curve(
                    result["rotation"], catalog["constants"], drone_target=drone_target,
                    external_gold_per_day=external_gold_per_day,
                    gold_net_target_per_day=gold_net_target_per_day,
                )
                final_curve = (curve.get("points") or [{}])[-1].get("cumulative") or {}
                for key in (
                    "lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
                    "gold_net_per_day", "orundum_per_day", "shards_net_per_day",
                ):
                    if key in final_curve:
                        weighted_metrics[key] = round(float(final_curve[key]), 2)
                weighted_metrics["gold_production_net_per_day"] = round(
                    float(weighted_metrics.get("gold_made_per_day", 0))
                    - float(weighted_metrics.get("gold_used_per_day", 0)), 2,
                )
                weighted_metrics["gold_inventory_days"] = (
                    None if float(weighted_metrics.get("gold_net_per_day", 0)) >= 0 else
                    round(gold_inventory / -float(weighted_metrics["gold_net_per_day"]), 1)
                )
                weighted_metrics["lmd_net_after_shards_per_day"] = round(
                    float(weighted_metrics.get("lmd_per_day", 0))
                    - float(weighted_metrics.get("lmd_shard_cost_per_day", 0)), 2,
                )
                drone_summary = curve.get("drone_summary") or {}
                dynamic_allocations = drone_summary.get("allocations") or []
                dynamic_deltas = drone_summary.get("deltas") or {}
                allocation_kinds: dict[str, dict] = {}
                for item in dynamic_allocations:
                    kind = str(item.get("kind") or "unknown")
                    bucket = allocation_kinds.setdefault(kind, {"label": item.get("label") or kind, "fraction": 0.0})
                    bucket["fraction"] += float(item.get("fraction", 0) or 0)
                target_label = " + ".join(
                    f"{item['label']} {item['fraction'] * 100:.1f}%"
                    for item in allocation_kinds.values()
                ) or "未投入"
                weighted_metrics["drone_hours_per_day"] = float(drone_summary.get("equivalent_hours", 0) or 0)
                weighted_metrics["drone_target"] = target_label
                weighted_metrics["drone_effect"] = {
                    **(weighted_metrics.get("drone_effect") or {}),
                    "target_kind": drone_target, "target": target_label,
                    "equivalent_hours": weighted_metrics["drone_hours_per_day"],
                    "allocations": dynamic_allocations,
                    "lmd_per_day": round(float(dynamic_deltas.get("lmd_per_day", 0)), 3),
                    "exp_per_day": round(float(dynamic_deltas.get("exp_per_day", 0)), 3),
                    "gold_made_per_day": round(float(dynamic_deltas.get("gold_made_per_day", 0)), 3),
                    "gold_used_per_day": round(float(dynamic_deltas.get("gold_used_per_day", 0)), 3),
                    "orundum_per_day": round(float(dynamic_deltas.get("orundum_per_day", 0)), 3),
                    "gold_net_per_day": round(
                        float(dynamic_deltas.get("gold_made_per_day", 0))
                        - float(dynamic_deltas.get("gold_used_per_day", 0)), 3,
                    ),
                }
                balance = weighted_metrics["drone_effect"].get("balance") or {}
                if balance:
                    projected = float(weighted_metrics.get("gold_net_per_day", 0) or 0)
                    target = float(gold_net_target_per_day)
                    only_trade = bool(dynamic_allocations) and all(item.get("kind") == "trade" for item in dynamic_allocations)
                    weighted_metrics["drone_effect"]["balance"] = {
                        **balance,
                        "base_gold_net_per_day": round(
                            projected - float(weighted_metrics["drone_effect"]["gold_net_per_day"]), 3
                        ),
                        "target_gold_net_per_day": target,
                        "projected_gold_net_per_day": round(projected, 3),
                        "all_trade_gold_net_per_day": round(projected, 3) if only_trade else balance.get("all_trade_gold_net_per_day"),
                        "binding": abs(projected - target) <= 0.05,
                        "balanced": abs(projected - target) <= 0.05,
                        "regime": "trade_saturated" if only_trade else ("balanced" if abs(projected - target) <= 0.05 else "mixed"),
                    }
                result["rotation"]["average_metrics"] = weighted_metrics
                result["rotation"]["production_curve"] = curve
            # Time-dependent skills were ranked using a provisional duration.
            # Re-run the whole A/B construction at the duration produced by the
            # morale scheduler until it stabilizes (bounded to two refinements).
            durations = result["rotation"].get("team_work_hours") or {}
            actual_model_hours_a = float(durations.get("A", model_shift_hours))
            actual_model_hours_b = float(durations.get("B", model_shift_hours_b))
            refinement_count = int(payload.get("_duration_refinement_count", 0))
            durations_changed = (
                abs(actual_model_hours_a - model_shift_hours) > 1e-6
                or abs(actual_model_hours_b - model_shift_hours_b) > 1e-6
            )
            if durations_changed and refinement_count < 3:
                refined_payload = {
                    **payload,
                    "model_shift_hours": actual_model_hours_a,
                    "_model_shift_hours_b": actual_model_hours_b,
                    "_duration_refinement_count": refinement_count + 1,
                }
                return optimize(refined_payload, catalog, include_frontier=include_frontier)
            result["solver"] += " · 顺序生成 A/B 班组"
        else:
            result["warnings"].append(
                f"A 队排定后只剩 {len(remaining)} 名可用干员，无法生成完全互斥的 B 队；请补充 Box 或放宽辅助设施范围。"
            )
    if (
        payload.get("include_rotation") and result.get("rotation")
        and not payload.get("_rotation_internal") and not payload.get("_objective_audit_internal")
    ):
        alternate_result = optimize(
            {**payload, "objective_mode": alternate_mode, "_objective_audit_internal": True},
            catalog, include_frontier=False,
        )
        primary_result = result
        primary_metrics = primary_result["rotation"]["average_metrics"]
        alternate_metrics = alternate_result["rotation"]["average_metrics"]

        def full_score(metrics: dict, mode: str) -> float:
            return metrics_daily_value(metrics) if mode == "sanity_value" else metrics_layout_score(metrics)

        # A/B states are generated sequentially, so the plan seeded by the
        # other scalar objective can occasionally dominate after full-cycle
        # duration and drone accounting. Re-rank both completed plans under
        # the requested objective instead of returning the inferior seed.
        alternate_wins = full_score(alternate_metrics, objective_mode) > full_score(primary_metrics, objective_mode) + 1e-9
        if alternate_wins:
            result, rejected_result = alternate_result, primary_result
            selected_origin = alternate_mode
            result["solver"] += f" · 完整周期按 {objective_mode} 复排后采用交叉候选"
        else:
            result, rejected_result = primary_result, alternate_result
            selected_origin = objective_mode
        current_metrics = result["rotation"]["average_metrics"]
        rejected_metrics = rejected_result["rotation"]["average_metrics"]
        requested_label = "固定产品布局：一图流等效理智最大化" if objective_mode == "sanity_value" else "固定产品布局：总产能等权最大化"
        alternate_label = "固定产品布局：一图流等效理智最大化" if alternate_mode == "sanity_value" else "固定产品布局：总产能等权最大化"
        result["objective"].update({
            "mode": objective_mode,
            "label": requested_label,
        })
        result["rotation"]["objective_mode"] = objective_mode
        comparison = {
            "alternate_mode": alternate_mode,
            "alternate_label": alternate_label,
            "scope": "完整 A/B 排班、工时与控制中枢搜索",
            "same_semantic_assignment": _result_assignment_signature(result) == _result_assignment_signature(rejected_result),
            "same_work_durations": (
                (result["rotation"].get("team_work_hours") or {})
                == ((rejected_result.get("rotation") or {}).get("team_work_hours") or {})
            ),
            "alternate_metrics": {
                key: rejected_metrics.get(key)
                for key in ("lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day", "gold_net_per_day", "orundum_per_day")
            },
            "alternate_work_durations": (rejected_result.get("rotation") or {}).get("team_work_hours"),
            "room_differences": _result_room_differences(result, rejected_result),
            "selected_candidate_origin": selected_origin,
            "cross_candidate_reranked": alternate_wins,
            "selected_dominates_alternate": (
                metrics_layout_score(current_metrics) >= metrics_layout_score(rejected_metrics) - 1e-9
                and metrics_daily_value(current_metrics) >= metrics_daily_value(rejected_metrics) - 1e-9
            ),
            "full_schedule_scores": {
              "current": {
                "layout_output": round(metrics_layout_score(current_metrics), 6),
                "sanity_value": round(metrics_daily_value(current_metrics), 6),
              },
              "alternate": {
                "layout_output": round(metrics_layout_score(rejected_metrics), 6),
                "sanity_value": round(metrics_daily_value(rejected_metrics), 6),
              },
            },
            "metric_deltas_alternate_minus_current": {
                key: round(float(rejected_metrics.get(key, 0) or 0) - float(current_metrics.get(key, 0) or 0), 3)
                for key in ("lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day", "gold_net_per_day", "orundum_per_day")
            },
        }
        result["objective"]["comparison"] = comparison
    result["allocation_audit"] = _production_allocation_audit(result, roster, catalog)
    return result
