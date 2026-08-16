"""Cross-room RIIC state and exact/expected room-mechanic adjustments.

This module models game mechanics, not operator identities.  Operator/faction
membership is data used by a mechanism (the same way recipe or room type is),
while calculation switches are keyed by stable building-skill icons.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
import re

from .mechanics import TRADE_ECONOMIC_ICONS, mechanic_is_partial


MONSTER_HUNTER_IDS = frozenset({"char_1029_yato2", "char_1030_noirc2", "char_4077_palico"})
ABYSSAL_HUNTER_IDS = frozenset({"char_474_glady", "char_263_skadi", "char_143_ghost", "char_218_cuttle", "char_4145_ulpia"})
SUI_IDS = frozenset({
    "char_2014_nian", "char_2015_dusk", "char_2023_ling", "char_2024_chyue",
    "char_2025_shu", "char_2026_yu", "char_2027_wang",
})
PLATFORM_IDS = frozenset({
    "char_285_medic2", "char_286_cast3", "char_376_therex", "char_4000_jnight",
    "char_4093_frston", "char_4136_phonor", "char_4188_confes", "char_4227_gallus",
})


CONTEXT_MODELED_ICONS = frozenset({
    "bskill_tra_texas1", "bskill_tra_Lappland1", "bskill_tra_Lappland2",
    "bskill_tra_spd&formula1", "bskill_tra_flow_gs", "bskill_tra_spd&limit_felyne",
    "bskill_tra_spd_variable21", "bskill_tra_spd_variable22",
    "bskill_tra_limit_diff",
    "bskill_man_spd&limit_felyne", "bskill_man_token_spd1", "bskill_man_token_spd2",
    "bskill_man_spd_variable11", "bskill_man_spd_mechanist", "bskill_man_spd_reduce",
    "bskill_man_spd_add1", "bskill_man_spd_add2",
    "bskill_man_spd_manu1",
    "bskill_man_bd1", "bskill_man_constrLv", "bskill_man_spd_bd1", "bskill_man_spd_bd2",
    "bskill_man_spd_bd3", "bskill_man_spd_bd4", "bskill_man_spd_bd5", "bskill_man_spd_bd6",
    "bskill_man_spd_bd7", "bskill_man_spd_bd_dungeon", "bskill_man_spd_bd_n1",
    "bskill_tra_bd_n1", "bskill_tra_bd_n2", "bskill_tra_spd_bd1", "bskill_tra_spd_bd2",
    "bskill_tra_spd_bd_dungeon",
    "bskill_ctrl_t_spd", "bskill_ctrl_p_spd", "bskill_ctrl_cost_felyne",
    "bskill_ctrl_felyne", "bskill_ctrl_aegir", "bskill_ctrl_aegir2",
    "bskill_ctrl_cost_bd1", "bskill_ctrl_cost_bd1&bd2",
    "bskill_ctrl_cost_bd2", "bskill_ctrl_cost_bd3", "bskill_ctrl_p_oblvns",
    "bskill_ctrl_trade_mortis", "bskill_ctrl_dorm_uika1", "bskill_ctrl_hire_tmoris",
    "bskill_ctrl_meet_amoris1",
})


@dataclass
class BaseContext:
    shift_hours: float = 8.0
    collection_interval_hours: float = 8.0
    num_trade: int = 2
    num_factory: int = 4
    num_power: int = 3
    gold_lines: int = 3
    formula_types: int = 2
    dorm_people: int = 20
    dorm_level_sum: int = 20
    platform_power_count: int = 0
    catnip: int = 0
    human_fire: int = 0
    perception_information: int = 0
    thought_chain: int = 0
    witchcraft_crystal: int = 0
    engineering_robots: int = 0
    silent_resonance: int = 0
    monster_food: int = 0
    enthusiasm: int = 0
    control_trade_speed: float = 0.0
    control_factory_speed: float = 0.0
    abyssal_factory_percent_per_hunter: float = 0.0
    abyssal_factory_count: int = 0
    control_operator_ids: list[str] = field(default_factory=list)
    control_operator_names: list[str] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return asdict(self)


def _control_effect(team: tuple[dict, ...], context: BaseContext) -> tuple[float, BaseContext]:
    result = BaseContext(**{**asdict(context), "audit": list(context.audit)})
    icons = {icon for operator in team for icon in operator["icons"]}
    ids = {operator["id"] for operator in team}
    result.control_operator_ids = [operator["id"] for operator in team]
    result.control_operator_names = [operator["name"] for operator in team]
    if "bskill_ctrl_t_spd" in icons:
        result.control_trade_speed = max(result.control_trade_speed, 7.0)
        result.audit.append("控制中枢：全贸易站订单效率 +7%")
    if "bskill_ctrl_p_spd" in icons:
        result.control_factory_speed = max(result.control_factory_speed, 2.0)
        result.audit.append("控制中枢：全制造站生产力 +2%")
    if "bskill_ctrl_cost_felyne" in icons:
        result.catnip += 8
    if "bskill_ctrl_felyne" in icons:
        result.catnip += 2 * len(ids & MONSTER_HUNTER_IDS)
    if result.catnip:
        result.audit.append(f"控制中枢：木天蓼 {result.catnip}")
    if "bskill_ctrl_aegir2" in icons:
        result.abyssal_factory_percent_per_hunter = 10.0
    elif "bskill_ctrl_aegir" in icons:
        result.abyssal_factory_percent_per_hunter = 5.0
    if result.abyssal_factory_percent_per_hunter:
        result.audit.append(
            f"深海猎人制造站特殊加成：每名制造站深海猎人 {result.abyssal_factory_percent_per_hunter:g}%"
        )

    # State-variable producers use icon semantics.  Threshold-dependent Sui
    # skills are deliberately represented in the state even when not owned.
    midpoint_morale = 24.0 - 0.75 * result.shift_hours / 2.0
    if "bskill_ctrl_cost_bd1" in icons and midpoint_morale < 12.0:
        result.human_fire += 15
    if "bskill_ctrl_cost_bd1&bd2" in icons:
        if midpoint_morale > 12.0:
            result.human_fire += 15
        else:
            result.perception_information += 10
    if "bskill_ctrl_cost_bd2" in icons and midpoint_morale > 12.0:
        result.perception_information += 10
    if "bskill_ctrl_cost_bd3" in icons:
        result.human_fire += 5 * min(5, len(ids & SUI_IDS))
    if "bskill_ctrl_dorm_uika1" in icons:
        result.enthusiasm += result.dorm_people
    if "bskill_ctrl_hire_tmoris" in icons:
        result.enthusiasm += 10
    if "bskill_ctrl_meet_amoris1" in icons:
        result.enthusiasm += 10
    if "bskill_ctrl_trade_mortis" in icons:
        result.enthusiasm += 20
        result.control_trade_speed = max(result.control_trade_speed, float(result.enthusiasm // 8))
    if "bskill_ctrl_p_oblvns" in icons:
        result.control_factory_speed = max(result.control_factory_speed, 0.5 + 0.5 * (result.enthusiasm // 20))
    score = result.control_trade_speed * result.num_trade + result.control_factory_speed * result.num_factory
    # The roster-level caller adds a catnip ownership score; these terms keep
    # generally useful global mechanisms above morale-only fillers.
    score += result.catnip * 0.5 + result.abyssal_factory_percent_per_hunter * 0.25
    return score, result
def select_control_team(operators: list[dict], context: BaseContext) -> tuple[list[dict], BaseContext]:
    candidates = [op for op in operators if any(skill.get("room") == "CONTROL" for skill in op["skills"])]
    if not candidates:
        return [], context
    size = min(5, len(candidates))
    terra_owned = any(op["id"] == "char_4077_palico" for op in operators)
    abyssal_owned = sum(op["id"] in ABYSSAL_HUNTER_IDS for op in operators)
    best: tuple[float, tuple[dict, ...], BaseContext] | None = None
    for team in combinations(candidates, size):
        score, state = _control_effect(team, context)
        if terra_owned:
            score += state.catnip * 3.0
        if abyssal_owned > 1:
            score += state.abyssal_factory_percent_per_hunter * (abyssal_owned - 1)
        # Prefer more morale support only after production-related state.
        score += sum(
            0.01 for operator in team for skill in operator["skills"]
            if skill.get("room") == "CONTROL" and "心情" in str(skill.get("description") or "")
        )
        candidate = (score, team, state)
        if best is None or candidate[0] > best[0]:
            best = candidate
    assert best is not None
    return list(best[1]), best[2]


def select_control_options(
    operators: list[dict], context: BaseContext, limit: int = 4
) -> list[tuple[list[dict], BaseContext]]:
    """Return production-distinct control-center alternatives.

    A control team is not merely a morale filler: Amiya, Monster Hunter and
    Abyssal Hunter states can change the best production-room assignment.  We
    retain the strongest team for each distinct production state so the
    optimizer can compare their *actual* downstream output instead of choosing
    a control team from an isolated heuristic score.
    """
    candidates = [op for op in operators if any(skill.get("room") == "CONTROL" for skill in op["skills"])]
    if not candidates:
        return [([], context)]
    size = min(5, len(candidates))
    terra_owned = any(op["id"] == "char_4077_palico" for op in operators)
    abyssal_owned = sum(op["id"] in ABYSSAL_HUNTER_IDS for op in operators)
    by_state: dict[tuple, tuple[float, tuple[dict, ...], BaseContext]] = {}
    for team in combinations(candidates, size):
        score, state = _control_effect(team, context)
        if terra_owned:
            score += state.catnip * 3.0
        if abyssal_owned > 1:
            score += state.abyssal_factory_percent_per_hunter * (abyssal_owned - 1)
        score += sum(
            0.01 for operator in team for skill in operator["skills"]
            if skill.get("room") == "CONTROL" and "心情" in str(skill.get("description") or "")
        )
        signature = (
            state.control_trade_speed,
            state.control_factory_speed,
            state.catnip,
            state.human_fire,
            state.perception_information,
            state.enthusiasm,
            state.abyssal_factory_percent_per_hunter,
        )
        current = by_state.get(signature)
        if current is None or score > current[0]:
            by_state[signature] = (score, team, state)
    ranked = sorted(by_state.values(), key=lambda item: item[0], reverse=True)
    return [(list(team), state) for _, team, state in ranked[: max(1, limit)]]


def _target_matches(skill: dict, product: str) -> bool:
    target = {"gold": "F_GOLD", "exp": "F_EXP"}.get(product)
    return not target or not skill.get("targets") or target in skill.get("targets", [])


def _capacity_bonus(team: list[dict], product: str) -> float:
    total = 0.0
    for operator in team:
        for skill in operator["skills"]:
            if skill.get("room") != "MANUFACTURE" or not _target_matches(skill, product):
                continue
            total += sum(float(x) for x in re.findall(r"仓库容量上限\+([0-9.]+)", skill.get("description", "")))
    if any("bskill_man_spd_manu1" in operator["icons"] for operator in team):
        total += 5.0 * len(team)
    return total


def _morale_gap_average_penalty(hours: float, consumption: float = 0.75) -> float:
    """Average -5% per complete four points of morale gap over a shift."""
    if hours <= 0 or consumption <= 0:
        return 0.0
    weighted = 0.0
    start = 0.0
    step = 0
    while start < hours:
        end = min(hours, (step + 1) * 4.0 / consumption)
        weighted += max(0.0, end - start) * step * 5.0
        start = end
        step += 1
    return weighted / hours


def _hourly_ramp_profile(initial: float, step: float, cap: float, hours: float) -> tuple[float, list[dict]]:
    """Integrate a whole-hour stepped skill and retain its timeline phases."""
    cursor = 0.0
    weighted = 0.0
    phases: list[dict] = []
    while cursor < hours - 1e-9:
        end = min(hours, cursor + 1.0)
        value = min(cap, initial + step * int(cursor))
        weighted += value * (end - cursor)
        if phases and phases[-1]["value_percent"] == value:
            phases[-1]["end_hour"] = end
        else:
            phases.append({"start_hour": cursor, "end_hour": end, "value_percent": value})
        cursor = end
    return weighted / max(hours, 1e-9), phases


def _order_limit(team: list[dict]) -> int:
    total = 10
    names = {operator["name"] for operator in team}
    for operator in team:
        for skill in operator["skills"]:
            if skill.get("room") != "TRADING":
                continue
            if skill.get("icon") in {"bskill_tra_Lappland1", "bskill_tra_Lappland2"} and "德克萨斯" not in names:
                continue
            total += sum(int(float(x)) for x in re.findall(r"订单上限\+([0-9.]+)", skill.get("description", "")))
            total -= sum(int(float(x)) for x in re.findall(r"订单上限-([0-9.]+)", skill.get("description", "")))
    return max(1, total)


def _average_empty_order_slots(limit: int, speed_without_jaye: float, interval_hours: float,
                               mean_order_minutes: float = 203.4) -> float:
    """Deterministic steady-cycle expectation for Jaye's queue-gap skill.

    Orders are collected every ``interval_hours``.  Existing in-progress work
    is retained at collection; only the completed-order queue becomes empty.
    The workload of a normal L3 order is its published 203.4-minute mean.
    """
    interval = max(1.0, interval_hours * 60.0)
    remaining_work = mean_order_minutes
    weighted_gap = 0.0
    measured = 0.0
    # Warm ten collection cycles, then measure twenty.
    for cycle in range(30):
        elapsed = 0.0
        gap = limit
        while elapsed < interval:
            multiplier = 1.0 + (3.0 + speed_without_jaye + 4.0 * gap) / 100.0
            minutes_to_finish = remaining_work / multiplier
            segment = min(interval - elapsed, minutes_to_finish)
            if cycle >= 10:
                weighted_gap += gap * segment
                measured += segment
            elapsed += segment
            remaining_work -= segment * multiplier
            if remaining_work <= 1e-9:
                remaining_work = mean_order_minutes
                gap = max(0, gap - 1)
                if gap == 0:
                    # Full queue blocks until collection.
                    if cycle >= 10:
                        measured += interval - elapsed
                    elapsed = interval
        # Collection empties the completed queue but keeps current progress.
    return weighted_gap / max(measured, 1e-9)


def room_context_adjustment(team: list[dict], product: str, context: BaseContext, base_speed: float) -> dict:
    icons = {icon for operator in team for icon in operator["icons"]}
    ids = {operator["id"] for operator in team}
    names = {operator["name"] for operator in team}
    delta = 0.0
    notes: list[str] = []
    effects: list[dict] = []
    time_profiles: list[dict] = []
    modeled: set[str] = set()

    def use_state(state: str, label: str, available: float, contribution: float, detail: str) -> None:
        effects.append({
            "state": state,
            "label": label,
            "available": available,
            "contribution_percent": round(contribution, 3),
            "detail": detail,
        })

    if product in {"trade", "orundum"}:
        delta += context.control_trade_speed
        if context.control_trade_speed:
            notes.append(f"控制中枢全局 +{context.control_trade_speed:g}%")
            use_state("control_trade_speed", "全贸易站效率", context.control_trade_speed, context.control_trade_speed, "控制中枢全局增益")
        if "bskill_tra_texas1" in icons and "拉普兰德" in names:
            delta += 65.0
            modeled.add("bskill_tra_texas1")
            notes.append("德克萨斯—拉普兰德同站 +65%")
        if "bskill_tra_spd&formula1" in icons:
            value = 2.0 * context.formula_types
            delta += value
            modeled.add("bskill_tra_spd&formula1")
            notes.append(f"制造配方 {context.formula_types} 类 +{value:g}%")
            use_state("formula_types", "制造配方", context.formula_types, value, f"{context.formula_types:g} 类 × 2%")
        if "bskill_tra_flow_gs" in icons:
            value = 5.0 * context.gold_lines
            delta += value
            modeled.add("bskill_tra_flow_gs")
            notes.append(f"赤金生产线 {context.gold_lines} 条 +{value:g}%")
            use_state("gold_lines", "赤金生产线", context.gold_lines, value, f"{context.gold_lines:g} 条 × 5%")
        if "bskill_tra_spd&limit_felyne" in icons:
            value = 3.0 * context.catnip
            delta += value
            modeled.add("bskill_tra_spd&limit_felyne")
            notes.append(f"木天蓼 {context.catnip} × 3% = +{value:g}%")
            use_state("catnip", "木天蓼", context.catnip, value, f"{context.catnip:g} 个 × 3%")
        local_human_fire = context.human_fire + (context.dorm_people if "bskill_tra_bd_n2" in icons else 0)
        if "bskill_tra_bd_n2" in icons:
            delta += local_human_fire
            modeled.add("bskill_tra_bd_n2")
            notes.append(f"愿者上钩：人间烟火 {local_human_fire}，订单效率 +{local_human_fire}%")
            use_state("human_fire", "人间烟火", local_human_fire, local_human_fire, "愿者上钩转化")
        local_silent = context.silent_resonance + (context.dorm_people if "bskill_tra_bd_n1" in icons else 0)
        if "bskill_tra_bd_n1" in icons:
            modeled.add("bskill_tra_bd_n1")
            notes.append(f"乐感：感知信息/无声共鸣 +{context.dorm_people}")
        if "bskill_tra_spd_bd1" in icons:
            value = float(local_silent // 4)
            delta += value
            modeled.add("bskill_tra_spd_bd1")
            notes.append(f"无声共鸣 {local_silent} / 4 = +{value:g}%")
            use_state("silent_resonance", "无声共鸣", local_silent, value, "每 4 点转化 1%")
        if "bskill_tra_spd_bd2" in icons:
            value = float(local_silent // 2)
            delta += value
            modeled.add("bskill_tra_spd_bd2")
            notes.append(f"无声共鸣 {local_silent} / 2 = +{value:g}%")
            use_state("silent_resonance", "无声共鸣", local_silent, value, "每 2 点转化 1%")
        if "bskill_tra_spd_bd_dungeon" in icons:
            delta += context.monster_food
            modeled.add("bskill_tra_spd_bd_dungeon")
            notes.append(f"魔物料理 {context.monster_food} = +{context.monster_food}%")
            use_state("monster_food", "魔物料理", context.monster_food, context.monster_food, "每点转化 1%")
        snow_icons = icons & {"bskill_tra_spd_variable21", "bskill_tra_spd_variable22"}
        if snow_icons:
            cap = 25.0 if "bskill_tra_spd_variable21" in snow_icons else 35.0
            before = base_speed + delta
            value = min(cap, int(max(0.0, before) // 5.0) * 5.0)
            delta += value
            modeled.update(snow_icons)
            notes.append(f"效率分段追加 +{value:g}%（上限 {cap:g}%）")
        if "bskill_tra_limit_diff" in icons:
            limit = _order_limit(team)
            before = base_speed + delta
            average_gap = _average_empty_order_slots(
                limit, before, context.collection_interval_hours,
                120.0 if product == "orundum" else 203.4,
            )
            value = 4.0 * average_gap
            delta += value
            modeled.add("bskill_tra_limit_diff")
            notes.append(
                f"每 {context.collection_interval_hours:g} 小时收单：订单上限 {limit}，平均空位 {average_gap:.2f}，+{value:.2f}%"
            )

    elif product in {"gold", "exp", "shard"}:
        ramp_rules = {
            "bskill_man_spd_add1": (20.0, 1.0, 25.0, "急性子"),
            "bskill_man_spd_add2": (15.0, 2.0, 25.0, "慢性子"),
        }
        for operator in team:
            for icon, (initial, step, cap, label) in ramp_rules.items():
                if icon not in operator["icons"]:
                    continue
                average, phases = _hourly_ramp_profile(initial, step, cap, context.shift_hours)
                delta += average - initial
                modeled.add(icon)
                notes.append(f"{operator['name']} {label}班均 +{average:.2f}%")
                time_profiles.append({
                    "operator": operator["name"], "mechanic": "hourly_step", "label": label,
                    "average_percent": round(average, 3), "phases": phases,
                })
        if "bskill_man_spd_manu1" in icons:
            # Science Modification clears partners' own production bonuses.
            # Facility-count/global bonuses added below remain valid.
            delta -= base_speed
            modeled.add("bskill_man_spd_manu1")
            notes.append("科学改造：同站干员直接生产力归零，每人提供仓容 +5")
        delta += context.control_factory_speed
        if context.control_factory_speed:
            notes.append(f"控制中枢全局 +{context.control_factory_speed:g}%")
            use_state("control_factory_speed", "全制造站效率", context.control_factory_speed, context.control_factory_speed, "控制中枢全局增益")
        if "bskill_man_spd&limit_felyne" in icons:
            value = float(context.catnip)
            delta += value
            modeled.add("bskill_man_spd&limit_felyne")
            notes.append(f"木天蓼 {context.catnip} × 1% = +{value:g}%")
            use_state("catnip", "木天蓼", context.catnip, value, f"{context.catnip:g} 个 × 1%")
        platform_icons = icons & {"bskill_man_token_spd1", "bskill_man_token_spd2"}
        if platform_icons and product == "gold":
            per = 10.0 if "bskill_man_token_spd2" in platform_icons else 5.0
            value = per * context.platform_power_count
            delta += value
            modeled.update(platform_icons)
            notes.append(f"发电站作业平台 {context.platform_power_count} 台 +{value:g}%")
            use_state("platform_power_count", "作业平台", context.platform_power_count, value, f"{context.platform_power_count:g} 台 × {per:g}%")
        if "bskill_man_spd_variable11" in icons:
            value = 2.0 * _capacity_bonus(team, product)
            delta += value
            modeled.add("bskill_man_spd_variable11")
            notes.append(f"仓容转换 +{value:g}%")
        if "bskill_man_spd_mechanist" in icons:
            hours = context.shift_hours
            value = 10.0 * max(0.0, hours - 12.0) / max(hours, 1e-9)
            delta += value
            modeled.add("bskill_man_spd_mechanist")
            notes.append(f"12 小时后生效的班均贡献 +{value:.2f}%")
        if "bskill_man_spd_reduce" in icons:
            penalty = _morale_gap_average_penalty(context.shift_hours)
            delta -= penalty
            modeled.add("bskill_man_spd_reduce")
            notes.append(f"心情落差班均衰减 -{penalty:.2f}%")
        local_thought = context.thought_chain + (context.dorm_people if "bskill_man_spd_bd_n1" in icons else 0)
        if "bskill_man_spd_bd_n1" in icons:
            modeled.add("bskill_man_spd_bd_n1")
            notes.append(f"超感：感知信息/思维链环 +{context.dorm_people}")
        if "bskill_man_spd_bd1" in icons:
            value = float(local_thought // 2)
            delta += value
            modeled.add("bskill_man_spd_bd1")
            notes.append(f"思维链环 {local_thought} / 2 = +{value:g}%")
            use_state("thought_chain", "思维链环", local_thought, value, "每 2 点转化 1%")
        if "bskill_man_spd_bd2" in icons:
            value = float(local_thought)
            delta += value
            modeled.add("bskill_man_spd_bd2")
            notes.append(f"思维链环 {local_thought} = +{value:g}%")
            use_state("thought_chain", "思维链环", local_thought, value, "每点转化 1%")
        local_crystal = context.witchcraft_crystal
        if "bskill_man_bd1" in icons:
            local_crystal += context.human_fire // 5
            modeled.add("bskill_man_bd1")
            notes.append(f"人间烟火 {context.human_fire} / 5 → 巫术结晶 {local_crystal}")
        if "bskill_man_spd_bd5" in icons:
            delta += local_crystal
            modeled.add("bskill_man_spd_bd5")
            notes.append(f"巫术结晶 {local_crystal} = +{local_crystal}%")
            use_state("witchcraft_crystal", "巫术结晶", local_crystal, local_crystal, "每点转化 1%")
        if "bskill_man_spd_bd6" in icons:
            value = 2.0 * local_crystal
            delta += value
            modeled.add("bskill_man_spd_bd6")
            notes.append(f"巫术结晶 {local_crystal} × 2% = +{value:g}%")
            use_state("witchcraft_crystal", "巫术结晶", local_crystal, value, "每点转化 2%")
        if "bskill_man_spd_bd7" in icons:
            value = float(context.human_fire // 3)
            delta += value
            modeled.add("bskill_man_spd_bd7")
            notes.append(f"人间烟火 {context.human_fire} / 3 = +{value:g}%")
            use_state("human_fire", "人间烟火", context.human_fire, value, "每 3 点转化 1%")
        robots = context.engineering_robots
        if "bskill_man_constrLv" in icons:
            # 2-4-3 full right side: CC5 + 9 left rooms*3 + 4 dorms*5 +
            # reception3 + office3 + training3 = 61, below the cap of 64.
            robots = max(robots, 61)
            modeled.add("bskill_man_constrLv")
            notes.append("满级 2-4-3 设施等级合计按 61 个工程机器人")
        if "bskill_man_spd_bd3" in icons:
            value = float(robots // 16) * 5.0
            delta += value
            modeled.add("bskill_man_spd_bd3")
            notes.append(f"工程机器人 {robots} / 16 = +{value:g}%")
            use_state("engineering_robots", "工程机器人", robots, value, "每 16 台转化 5%")
        if "bskill_man_spd_bd4" in icons:
            value = float(robots // 8) * 5.0
            delta += value
            modeled.add("bskill_man_spd_bd4")
            notes.append(f"工程机器人 {robots} / 8 = +{value:g}%")
            use_state("engineering_robots", "工程机器人", robots, value, "每 8 台转化 5%")
        if "bskill_man_spd_bd_dungeon" in icons:
            delta += context.monster_food
            modeled.add("bskill_man_spd_bd_dungeon")
            notes.append(f"魔物料理 {context.monster_food} = +{context.monster_food}%")
            use_state("monster_food", "魔物料理", context.monster_food, context.monster_food, "每点转化 1%")

        # Gladiia's control-center effect applies to every factory containing
        # an Abyssal Hunter.  The full cross-factory count is refined after
        # selection; local count is an exact lower bound during candidate rank.
        local_abyssal = len(ids & ABYSSAL_HUNTER_IDS)
        if local_abyssal and context.abyssal_factory_percent_per_hunter:
            total_abyssal = context.abyssal_factory_count or local_abyssal
            value = min(90.0, context.abyssal_factory_percent_per_hunter * total_abyssal)
            delta += value
            notes.append(f"制造站深海猎人总数 {total_abyssal}：本房间特殊加成 +{value:g}%")
            use_state("abyssal_factory_count", "深海猎人协同", total_abyssal, value, f"{total_abyssal:g} 名 × {context.abyssal_factory_percent_per_hunter:g}%")

    return {"delta": delta, "notes": notes, "effects": effects,
            "time_profiles": time_profiles, "modeled_icons": modeled}


def platform_count(power_rooms: list[dict]) -> int:
    return sum(operator in PLATFORM_IDS for room in power_rooms for operator in room.get("operators", []))


def mechanism_coverage(operators: list[dict]) -> dict:
    """Audit active production-affecting skills without claiming false parity."""
    exact: list[dict] = []
    partial: list[dict] = []
    ignored: list[dict] = []
    production_words = ("生产力", "订单获取效率", "充能速度", "赤金", "龙门币", "特殊加成")
    for operator in operators:
        for skill in operator["skills"]:
            room = skill.get("room")
            if room not in {"MANUFACTURE", "TRADING", "POWER", "CONTROL"}:
                continue
            item = {
                "operator": operator["name"],
                "skill": skill.get("name", ""),
                "icon": skill.get("icon", ""),
                "room": room,
            }
            icon = skill.get("icon", "")
            text = str(skill.get("description") or "")
            if icon in TRADE_ECONOMIC_ICONS or icon in CONTEXT_MODELED_ICONS:
                exact.append(item)
            elif room == "CONTROL" and not any(word in text for word in production_words):
                ignored.append({**item, "reason": "仅影响心情/非生产设施，作为轮班约束而非产出目标"})
            elif skill.get("category") == "OUTPUT" and not mechanic_is_partial(skill):
                exact.append(item)
            elif any(word in text for word in production_words):
                partial.append({**item, "reason": "存在尚未解释为状态公式的条件效果"})
            else:
                ignored.append({**item, "reason": "不改变当前龙门币/经验/赤金/无人机目标"})
    return {
        "exact_count": len(exact),
        "partial_count": len(partial),
        "constraint_only_count": len(ignored),
        "total_relevant": len(exact) + len(partial),
        "exact_percent": round(100.0 * len(exact) / max(1, len(exact) + len(partial)), 1),
        "partial": partial,
    }
