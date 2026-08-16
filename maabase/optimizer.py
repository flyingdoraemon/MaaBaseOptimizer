"""Cross-room RIIC assignment optimizer and production accounting."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import itertools
from typing import Any

from .model import generate_candidates, prepare_operators
from .morale import analyze_morale, choose_dorm_helper
from .scheduler import build_rotation
from .state_model import (
    ABYSSAL_HUNTER_IDS,
    MONSTER_HUNTER_IDS,
    BaseContext,
    mechanism_coverage,
    platform_count,
    select_control_options,
)


@dataclass(frozen=True)
class GroupSpec:
    key: str
    count: int


def _utility(candidate: dict, product: str, lmd_weight: float, gold_safety: float) -> float:
    multiplier = candidate["multiplier"]
    if product == "trade":
        trade = candidate.get("trade") or {}
        return float(trade.get("lmd_per_day", 0)) / 10000.0
    if product == "orundum":
        return float((candidate.get("orundum") or {}).get("orundum_per_day", 0)) / 240.0
    if product in {"exp", "gold", "shard"}:
        return multiplier
    if product == "power":
        return 0.18 * multiplier
    return 0.0


def _solve_pulp(
    candidates: dict[str, list[dict]], groups: list[GroupSpec], lmd_weight: float, gold_safety: float,
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
        _utility(candidate, group.key, lmd_weight, gold_safety) * variables[(group.key, i)]
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
    candidates: dict[str, list[dict]], groups: list[GroupSpec], lmd_weight: float, gold_safety: float,
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
                    item = (score + _utility(candidate, group.key, lmd_weight, gold_safety), next(counter), used | op_set, new_selected)
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
    candidates: dict[str, list[dict]], groups: list[GroupSpec], lmd_weight: float, gold_safety: float,
    reusable_ids: set[str] | None = None,
) -> tuple[dict, str]:
    exact = _solve_pulp(candidates, groups, lmd_weight, gold_safety, reusable_ids)
    if exact:
        return exact
    return _solve_beam(candidates, groups, lmd_weight, gold_safety, reusable_ids=reusable_ids)


def _metrics(
    selected: dict[str, list[dict]], catalog: dict, drone_target: str,
    external_gold_per_day: float = 0.0, gold_inventory: float = 0.0,
    shard_recipe: str = "rock", shard_inventory: float = 0.0,
    collection_interval_hours: float = 8.0,
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
    shard_lmd_cost = shards_made * (1600.0 if shard_recipe == "rock" else 1000.0)
    shard_material_used = shards_made * (2.0 if shard_recipe == "rock" else 1.0)
    power_bonus = sum(5.0 + c["efficiency"] for c in power)
    drones = 1440.0 / constants["drone_recover_minutes"] * (1.0 + power_bonus / 100.0)
    drone_hours = drones * constants["drone_minutes"] / 60.0
    drone_note = "未使用"
    if drone_target == "trade" and trade:
        target = max(trade, key=lambda x: float((x.get("trade") or {}).get("lmd_per_day", 0)))
        target_trade = target.get("trade") or {}
        lmd += float(target_trade.get("lmd_per_day", constants["trade_lmd_base_per_day"] * target["multiplier"])) / 24.0 * drone_hours
        gold_used += float(target_trade.get("gold_per_day", constants["trade_gold_base_per_day"] * target["multiplier"])) / 24.0 * drone_hours
        drone_note = f"贸易站：{' / '.join(target['names'])}"
    elif drone_target == "gold" and gold:
        target = max(gold, key=lambda x: x["multiplier"])
        gold_made += constants["gold_base_per_day"] / 24.0 * target["multiplier"] * drone_hours
        drone_note = f"赤金制造：{' / '.join(target['names'])}"
    elif drone_target == "exp" and exp:
        target = max(exp, key=lambda x: x["multiplier"])
        experience += constants["exp_base_per_day"] / 24.0 * target["multiplier"] * drone_hours
        drone_note = f"作战记录制造：{' / '.join(target['names'])}"
    elif drone_target == "shard" and shard:
        target = max(shard, key=lambda x: x["multiplier"])
        extra = 1.0 / 24.0 * target["multiplier"] * drone_hours
        shards_made += extra
        shard_lmd_cost += extra * (1600.0 if shard_recipe == "rock" else 1000.0)
        shard_material_used += extra * (2.0 if shard_recipe == "rock" else 1.0)
        drone_note = f"源石碎片制造：{' / '.join(target['names'])}"
    elif drone_target == "orundum" and orundum_trade:
        target = max(orundum_trade, key=lambda x: x["multiplier"])
        econ = target.get("orundum") or {}
        orundum += float(econ.get("orundum_per_day", 240.0 * target["multiplier"])) / 24.0 * drone_hours
        shards_used += float(econ.get("shards_per_day", 24.0 * target["multiplier"])) / 24.0 * drone_hours
        drone_note = f"源石订单：{' / '.join(target['names'])}"
    production_net = gold_made - gold_used
    total_net = production_net + external_gold_per_day
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
        "drone_hours_per_day": round(drone_hours, 2),
        "drone_target": drone_note,
        "power_bonus": round(power_bonus, 2),
    }


def _warnings(selected: dict[str, list[dict]], metrics: dict) -> list[str]:
    warnings = []
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
                    {"name": skill["name"], "description": skill["description"], "value": 0}
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
                            "value": skill.get("efficiency", 0)}
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
    lmd_weight = 0.5
    gold_safety = 0.0
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
    control_options = select_control_options(control_pool, base_context, 4 if len(operators) <= 180 else 1)
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
                candidates_option, groups, lmd_weight, gold_safety, reusable_ids
            )
            count = platform_count(selected_option.get("power", []))
            factory_rooms = selected_option.get("gold", []) + selected_option.get("exp", []) + selected_option.get("shard", [])
            abyssal_count = sum(
                operator in ABYSSAL_HUNTER_IDS
                for room in factory_rooms for operator in room.get("operators", [])
            )
            if count == context_option.platform_power_count and abyssal_count == context_option.abyssal_factory_count:
                break
            if attempt == 4:
                context_option.audit.append("离散跨房间状态在 5 次迭代内未收敛；当前结果按最后一次状态估算")
                break
            context_option.platform_power_count = count
            context_option.audit = [line for line in context_option.audit if not line.startswith("发电站：作业平台")]
            if count:
                context_option.audit.append(f"发电站：作业平台 {count} 台")
            context_option.abyssal_factory_count = abyssal_count
            context_option.audit = [line for line in context_option.audit if not line.startswith("制造站：深海猎人")]
            if abyssal_count:
                context_option.audit.append(f"制造站：深海猎人 {abyssal_count} 名")
        score = sum(
            _utility(candidate, group.key, lmd_weight, gold_safety)
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
        shard_inventory, base_context.collection_interval_hours,
    )
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
        "metrics": metrics,
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
            )
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
    return result
