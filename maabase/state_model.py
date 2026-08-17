"""Cross-room RIIC state and exact/expected room-mechanic adjustments.

This module models game mechanics, not operator identities.  Operator/faction
membership is data used by a mechanism (the same way recipe or room type is),
while calculation switches are keyed by stable building-skill icons.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
import json
from pathlib import Path
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
_TERM_DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "riic_terms.json").read_text(encoding="utf-8"))
RIIC_TERMS = {key: frozenset(value) for key, value in _TERM_DATA["terms"].items()}


CONTEXT_MODELED_ICONS = frozenset({
    "bskill_tra_texas1", "bskill_tra_Lappland1", "bskill_tra_Lappland2",
    "bskill_tra_spd&formula1", "bskill_tra_flow_gs", "bskill_tra_spd&limit_felyne",
    "bskill_tra_spd_variable21", "bskill_tra_spd_variable22",
    "bskill_tra_limit_diff",
    "bskill_man_spd&limit_felyne", "bskill_man_token_spd1", "bskill_man_token_spd2",
    "bskill_man_spd_variable11", "bskill_man_spd_variable31", "bskill_man_spd_variable21",
    "bskill_man_spd_mechanist", "bskill_man_spd_reduce",
    "bskill_man_spd_add1", "bskill_man_spd_add2", "bskill_man_spd_add3",
    "bskill_man_spd_manu1", "bskill_man_spd_manu2",
    "bskill_man_spd&power1", "bskill_man_spd&power2", "bskill_man_spd&power3",
    "bskill_man_spd&trade", "bskill_man_spd&trade1", "bskill_man_spd&dorm1",
    "bskill_man_skill_spd", "bskill_man_skill_spd2", "bskill_man_skill_spd3",
    "bskill_man_spd_veen", "bskill_man_spd_double", "bskill_man_spd_double2",
    "bskill_formula_spd_headb2",
    "bskill_man_gold&blacksteel", "bskill_man_gold&rhine",
    "bskill_formula_spd_sunbr", "bskill_man_fuze", "bskill_man_A1",
    "bskill_man_bd1", "bskill_man_constrLv", "bskill_man_spd_bd1", "bskill_man_spd_bd2",
    "bskill_man_spd_bd3", "bskill_man_spd_bd4", "bskill_man_spd_bd5", "bskill_man_spd_bd6",
    "bskill_man_spd_bd7", "bskill_man_spd_bd_dungeon", "bskill_man_spd_bd_n1",
    "bskill_tra_bd_n1", "bskill_tra_bd_n2", "bskill_tra_spd_bd1", "bskill_tra_spd_bd2",
    "bskill_tra_spd_bd_dungeon",
    "bskill_tra_limit_count", "bskill_tra_flow_gs2", "bskill_tra_flow_gc2",
    "bskill_tra_flow_durin",
    "bskill_tra_spd&meet1", "bskill_tra_spd&meet", "bskill_tra_par1",
    "trade_ord_spd&par2", "bskill_tra_laterano1", "bskill_tra_lemuen1",
    "bskill_trade_ord_spd_variable", "bskill_tra_limit2spd", "bskill_tra_spd&wt1",
    "bskill_tra_par&per2", "bskill_tra_ord_spd_ext1", "bskill_tra_ord_spd_ext3",
    "bskill_ord_spd&tag1", "bskill_ord_spd&tag2", "bskill_tra_orchd2",
    "bskill_pow_drone", "bskill_pow_spd_P", "bskill_power_rec_spd&dorm&lv", "bskill_power_rec_rhine",
    "bskill_power_rec_spd_ext&faction", "bskill_power_rec_spd_ext&tag",
    "bskill_ctrl_t_spd", "bskill_ctrl_p_spd", "bskill_ctrl_cost_felyne",
    "bskill_ctrl_felyne", "bskill_ctrl_aegir", "bskill_ctrl_aegir2",
    "bskill_ctrl_cost_bd1", "bskill_ctrl_cost_bd1&bd2",
    "bskill_ctrl_cost_bd2", "bskill_ctrl_cost_bd3", "bskill_ctrl_p_oblvns",
    "bskill_ctrl_trade_mortis", "bskill_ctrl_dorm_uika1", "bskill_ctrl_hire_tmoris",
    "bskill_ctrl_meet_amoris1",
    "bskill_ctrl_psk", "bskill_ctrl_token_p_spd", "bskill_ctrl_token_p_spd2",
    "bskill_ctrl_bd_spd", "bskill_token_prod_spd3_lungmenguard",
    "bskill_ctrl_t_limit&spd", "bskill_ctrl_g_limit&spd",
    "bskill_ctrl_t_limit&spd_tmoris", "bskill_ctrl_t_limit&spd3",
    "bskill_ctrl_tachanka", "bskill_ctrl_fraction_knight", "bskill_ctrl_tra&prod",
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
    ursus_drink: int = 0
    enthusiasm: int = 0
    control_trade_speed: float = 0.0
    control_factory_speed: float = 0.0
    control_gold_factory_speed: float = 0.0
    abyssal_factory_percent_per_hunter: float = 0.0
    abyssal_factory_count: int = 0
    control_operator_ids: list[str] = field(default_factory=list)
    control_operator_names: list[str] = field(default_factory=list)
    control_icons: list[str] = field(default_factory=list)
    control_group_counts: dict[str, int] = field(default_factory=dict)
    working_group_counts: dict[str, int] = field(default_factory=dict)
    working_nation_counts: dict[str, int] = field(default_factory=dict)
    power_nation_counts: dict[str, int] = field(default_factory=dict)
    working_operator_ids: list[str] = field(default_factory=list)
    trade_operator_ids: list[str] = field(default_factory=list)
    elite_staffed_facility_count: int = 0
    sui_staffed_facility_count: int = 0
    drone_capacity: int = 235
    audit: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return asdict(self)


CONTROL_PRODUCTION_ICONS = {
    "bskill_ctrl_t_spd", "bskill_ctrl_p_spd", "bskill_ctrl_cost_felyne", "bskill_ctrl_felyne",
    "bskill_ctrl_aegir2", "bskill_ctrl_aegir", "bskill_ctrl_cost_bd1", "bskill_ctrl_cost_bd1&bd2",
    "bskill_ctrl_cost_bd2", "bskill_ctrl_cost_bd3", "bskill_ctrl_dorm_uika1", "bskill_ctrl_hire_tmoris",
    "bskill_ctrl_meet_amoris1", "bskill_ctrl_trade_mortis", "bskill_ctrl_p_oblvns",
    "bskill_ctrl_psk", "bskill_ctrl_token_p_spd", "bskill_ctrl_t_limit&spd",
    "bskill_ctrl_token_p_spd2", "bskill_ctrl_bd_spd", "bskill_ctrl_g_limit&spd",
    "bskill_ctrl_fraction_knight", "bskill_token_prod_spd3_lungmenguard",
    "bskill_ctrl_t_limit&spd_tmoris", "bskill_ctrl_t_limit&spd3", "bskill_ctrl_tra&prod",
    "bskill_ctrl_tachanka",
}


def _control_candidates(operators: list[dict]) -> list[dict]:
    """Retain every modeled state producer plus a few morale-only fillers.

    A full catalog currently has dozens of control-room operators; blindly
    enumerating C(65, 5) teams spends minutes rediscovering equivalent
    morale-only states.  Production-state producers are never truncated.
    """
    candidates = [op for op in operators if any(skill.get("room") == "CONTROL" for skill in op["skills"])]
    producers = [op for op in candidates if op["icons"] & CONTROL_PRODUCTION_ICONS]
    producer_ids = {op["id"] for op in producers}
    fillers = [op for op in candidates if op["id"] not in producer_ids]
    fillers.sort(key=lambda op: sum(
        "心情" in str(skill.get("description") or "")
        for skill in op["skills"] if skill.get("room") == "CONTROL"
    ), reverse=True)
    return producers + fillers[: max(0, 20 - len(producers))]


def _control_effect(team: tuple[dict, ...], context: BaseContext) -> tuple[float, BaseContext]:
    result = BaseContext(**{**asdict(context), "audit": list(context.audit)})
    icons = {icon for operator in team for icon in operator["icons"]}
    ids = {operator["id"] for operator in team}
    result.control_operator_ids = [operator["id"] for operator in team]
    result.control_operator_names = [operator["name"] for operator in team]
    # Only production-affecting icons define a downstream optimization state;
    # morale/training icons must not manufacture dozens of equivalent plans.
    result.control_icons = sorted(icons & CONTROL_PRODUCTION_ICONS)
    result.control_group_counts = {}
    if "bskill_token_prod_spd3_lungmenguard" in icons:
        result.control_group_counts["lgd"] = sum(operator.get("group_id") == "lgd" for operator in team)
    if "bskill_ctrl_t_spd" in icons:
        result.control_trade_speed = max(result.control_trade_speed, 7.0)
        result.audit.append("控制中枢：全贸易站订单效率 +7%")
    if "bskill_ctrl_p_spd" in icons:
        result.control_factory_speed = max(result.control_factory_speed, 2.0)
        result.audit.append("控制中枢：全制造站生产力 +2%")
    if "bskill_ctrl_tra&prod" in icons:
        external = result.num_trade + result.num_power
        field = result.num_factory
        if external >= field:
            result.control_trade_speed = max(result.control_trade_speed, 7.0)
            result.audit.append(f"权变：外势 {external} ≥ 实地 {field}，全贸易站 +7%")
        else:
            result.control_factory_speed = max(result.control_factory_speed, 2.0)
            result.audit.append(f"权变：实地 {field} > 外势 {external}，全制造站 +2%")
    if "bskill_ctrl_cost_felyne" in icons:
        result.catnip += 8
    if "bskill_ctrl_felyne" in icons:
        result.catnip += 2 * len(ids & MONSTER_HUNTER_IDS)
    if result.catnip:
        result.audit.append(f"控制中枢：木天蓼 {result.catnip}")
    if "bskill_ctrl_tachanka" in icons:
        result.ursus_drink += sum(operator.get("team_id") == "student" for operator in team)
        result.audit.append(f"控制中枢：乌萨斯特饮 {result.ursus_drink}")
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
        # This icon is reused by two game-data buffs with different 0.5%/1%
        # coefficients.  The active buff id/description, not the icon alone,
        # is the source of truth.  It only affects precious-metal formulas.
        candidates = []
        for operator in team:
            for skill in operator["skills"]:
                if skill.get("icon") != "bskill_ctrl_p_oblvns":
                    continue
                values = [float(value) for value in re.findall(r"生产力\+([0-9.]+)%", skill.get("description", ""))]
                if values:
                    coefficient = max(values)
                    candidates.append(coefficient * (1.0 + result.enthusiasm // 20))
        if candidates:
            result.control_gold_factory_speed = max(result.control_gold_factory_speed, max(candidates))
    score = (
        result.control_trade_speed * result.num_trade
        + result.control_factory_speed * result.num_factory
        + result.control_gold_factory_speed * result.gold_lines
    )
    # The roster-level caller adds a catnip ownership score; these terms keep
    # generally useful global mechanisms above morale-only fillers.
    score += result.catnip * 0.5 + result.abyssal_factory_percent_per_hunter * 0.25
    return score, result
def select_control_team(operators: list[dict], context: BaseContext) -> tuple[list[dict], BaseContext]:
    candidates = _control_candidates(operators)
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
    candidates = _control_candidates(operators)
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
            state.control_gold_factory_speed,
            tuple(state.control_icons),
            tuple(sorted(state.control_group_counts.items())),
            state.catnip,
            state.human_fire,
            state.perception_information,
            state.enthusiasm,
            state.ursus_drink,
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


def _static_capacity_by_operator(team: list[dict], product: str, context: BaseContext) -> dict[str, float]:
    """Return unconditional, positive capacity supplied by each worker.

    Capacity embedded in a conditional clause (for example "每有 1 瓶……")
    must not be treated as permanently active.  Capacity reductions are not
    "提升的仓库容量" and therefore do not feed Red Cloud/Bubble converters.
    """
    result: dict[str, float] = {}
    for operator in team:
        total = 0.0
        for skill in operator["skills"]:
            if skill.get("room") != "MANUFACTURE" or not _target_matches(skill, product):
                continue
            for clause in re.split(r"[，；。]", skill.get("description", "")):
                if "仓库容量" not in clause or any(marker in clause for marker in ("每有", "每个", "每间", "如果", "若", "当")):
                    continue
                total += sum(float(x) for x in re.findall(r"仓库容量(?:上限)?\+([0-9.]+)", clause))
        if "bskill_man_fuze" in operator["icons"]:
            total += 2.0 * context.ursus_drink
        result[operator["id"]] = total
    return result


MANUFACTURE_RESET_ICONS = frozenset({
    "bskill_man_spd_manu1", "bskill_man_spd_manu2",
    "bskill_man_spd&power1", "bskill_man_spd&power2", "bskill_man_spd&power3",
})


def _facility_count_speed(team: list[dict], product: str, context: BaseContext) -> tuple[float, list[str], set[str]]:
    """Evaluate effects explicitly based on a facility/room population count.

    These are the only local effects preserved by Science Modification,
    Process Optimization and Automation.  Warehouse capacity is deliberately
    absent: it is not a facility count.
    """
    total = 0.0
    notes: list[str] = []
    modeled: set[str] = set()
    rules = {
        "bskill_man_spd&power1": (5.0 * context.num_power, f"发电站 {context.num_power} 间 × 5%"),
        "bskill_man_spd&power2": (10.0 * context.num_power, f"发电站 {context.num_power} 间 × 10%"),
        "bskill_man_spd&power3": (15.0 * context.num_power, f"发电站 {context.num_power} 间 × 15%"),
        "bskill_man_spd_manu2": (10.0 * len(team), f"本站干员 {len(team)} 名 × 10%"),
    }
    if product == "gold":
        rules.update({
            "bskill_man_spd&trade": (20.0 * context.num_trade, f"贸易站 {context.num_trade} 间 × 20%"),
            "bskill_man_spd&trade1": (3.0 * context.num_trade, f"贸易站 {context.num_trade} 间 × 3%"),
            "bskill_man_spd&dorm1": (float(context.dorm_level_sum), f"宿舍等级合计 {context.dorm_level_sum} × 1%"),
        })
    for operator in team:
        for skill in operator["skills"]:
            icon = skill.get("icon", "")
            if icon not in rules or not _target_matches(skill, product):
                continue
            value, detail = rules[icon]
            total += value
            modeled.add(icon)
            notes.append(f"{operator['name']} {skill['name']}：{detail} = +{value:g}%")
    return total, notes, modeled


def _other_direct_production(team: list[dict], owner_id: str, product: str) -> float:
    total = 0.0
    for operator in team:
        if operator["id"] == owner_id:
            continue
        for skill in operator["skills"]:
            if skill.get("room") != "MANUFACTURE" or not _target_matches(skill, product):
                continue
            if skill.get("icon") in MANUFACTURE_RESET_ICONS:
                continue
            if skill.get("category") == "OUTPUT":
                total += float(skill.get("efficiency") or 0.0)
    return total


def _effective_control_factory_speed(context: BaseContext) -> float:
    """Resolve mutually exclusive +2% all-factory control effects."""
    icons = set(context.control_icons)
    values = [context.control_factory_speed]
    if "bskill_ctrl_token_p_spd" in icons and context.platform_power_count >= 2:
        values.append(2.0)
    if "bskill_ctrl_token_p_spd2" in icons and set(context.control_operator_ids) & MONSTER_HUNTER_IDS:
        values.append(2.0)
    if "bskill_token_prod_spd3_lungmenguard" in icons:
        # The skill owner is LGD; it activates when another LGD operator is in
        # the same control center.
        lgd_count = context.control_group_counts.get("lgd", 0)
        if lgd_count >= 2:
            values.append(3.0)
    return max(values)


def _control_local_factory_speed(team: list[dict], product: str, context: BaseContext) -> tuple[float, list[str]]:
    icons = set(context.control_icons)
    value = 0.0
    notes: list[str] = []
    if "bskill_ctrl_psk" in icons:
        count = sum(operator.get("group_id") == "pinus" for operator in team)
        contribution = count * (10.0 if product == "exp" else (-10.0 if product == "gold" else 0.0))
        value += contribution
        notes.append(f"红松骑士：本站红松骑士团 {count} 名 → {contribution:+g}%")
    if "bskill_ctrl_bd_spd" in icons:
        count = sum(operator.get("group_id") == "blacksteel" for operator in team)
        contribution = 5.0 * count
        value += contribution
        notes.append(f"老友相聚：本站黑钢国际 {count} 名 × 5% = +{contribution:g}%")
    if "bskill_ctrl_fraction_knight" in icons:
        count = sum(operator["id"] in RIIC_TERMS["knight"] for operator in team)
        contribution = 7.0 * count
        value += contribution
        notes.append(f"烛骑士微光：本站骑士 {count} 名 × 7% = +{contribution:g}%")
    return value, notes


def _control_local_trade_effect(team: list[dict], context: BaseContext) -> tuple[float, int, list[str]]:
    icons = set(context.control_icons)
    value = 0.0
    order_limit = 0
    notes: list[str] = []
    kjerag = sum(operator.get("nation_id") == "kjerag" for operator in team)
    glasgow = sum(operator.get("group_id") == "glasgow" for operator in team)
    siracusa = sum(operator.get("nation_id") == "siracusa" for operator in team)
    if "bskill_ctrl_t_limit&spd" in icons:
        contribution = -15.0 * kjerag
        added_limit = 6 * kjerag
        value += contribution
        order_limit += added_limit
        notes.append(f"精密计算：谢拉格 {kjerag} 名 → {contribution:+g}% / 订单上限 +{added_limit}")
    if "bskill_ctrl_g_limit&spd" in icons:
        contribution = 10.0 * glasgow
        value += contribution
        notes.append(f"运筹好手：格拉斯哥帮 {glasgow} 名 × 10% = +{contribution:g}%")
    if "bskill_ctrl_t_limit&spd_tmoris" in icons:
        contribution = 5.0 * siracusa
        value += contribution
        notes.append(f"家族认可：叙拉古 {siracusa} 名 × 5% = +{contribution:g}%")
    if "bskill_ctrl_t_limit&spd3" in icons and kjerag == 3:
        value += 10.0
        notes.append("商业版图：本站 3 名谢拉格干员 → +10%")
    return value, order_limit, notes


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


def _positive_order_limit_bonus(team: list[dict]) -> int:
    """Order slots added by workers, excluding the room's built-in capacity."""
    return max(0, _order_limit(team) - 10)


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
        control_trade_delta, control_order_limit, control_trade_notes = _control_local_trade_effect(team, context)
        delta += control_trade_delta
        notes.extend(control_trade_notes)
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
        local_gold_lines = context.gold_lines
        if "bskill_tra_flow_durin" in icons:
            count = min(4, len(set(context.working_operator_ids) & RIIC_TERMS["durin"]))
            local_gold_lines += count
            modeled.add("bskill_tra_flow_durin")
            notes.append(f"际崖居民：基建工作的杜林族 {count} 名 → 结算赤金线 +{count}")
        if "bskill_tra_flow_gc2" in icons:
            extra_lines = 2 * (context.gold_lines // 2)
            local_gold_lines += extra_lines
            modeled.add("bskill_tra_flow_gc2")
            notes.append(f"订单流可视化：{context.gold_lines} 条实际赤金线 → {local_gold_lines} 条结算赤金线")
        if "bskill_tra_flow_gs" in icons:
            value = 5.0 * local_gold_lines
            delta += value
            modeled.add("bskill_tra_flow_gs")
            notes.append(f"赤金生产线 {local_gold_lines} 条 +{value:g}%")
            use_state("gold_lines", "赤金生产线", local_gold_lines, value, f"{local_gold_lines:g} 条 × 5%")
        if "bskill_tra_flow_gs2" in icons:
            value = 15.0 * (local_gold_lines // 2)
            delta += value
            modeled.add("bskill_tra_flow_gs2")
            notes.append(f"物流规划：{local_gold_lines} 条赤金线，每 2 条 +15% = +{value:g}%")
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
        glasgow_count = sum(operator.get("group_id") == "glasgow" for operator in team)
        if "bskill_tra_par1" in icons:
            value = 20.0 * glasgow_count + (35.0 if "char_112_siege" in ids else 0.0)
            delta += value
            modeled.add("bskill_tra_par1")
            notes.append(f"帮派指南针：格拉斯哥帮 {glasgow_count} 名"
                         f"{'，与推进之王同站' if 'char_112_siege' in ids else ''} → +{value:g}%")
        if "trade_ord_spd&par2" in icons:
            value = 10.0 if glasgow_count else 0.0
            delta += value
            modeled.add("trade_ord_spd&par2")
            notes.append(f"外贸决议：同站格拉斯哥帮 {glasgow_count} 名 → +{value:g}%")
        if "bskill_tra_laterano1" in icons:
            count = sum(operator.get("nation_id") == "laterano" for operator in team)
            value = 15.0 * count
            delta += value
            modeled.add("bskill_tra_laterano1")
            notes.append(f"同城加急单：同站拉特兰 {count} 名 × 15% = +{value:g}%")
        if "bskill_tra_lemuen1" in icons:
            value = 25.0 if "char_103_angel" in ids else 0.0
            delta += value
            modeled.add("bskill_tra_lemuen1")
            notes.append(f"相伴：{'与能天使同站' if value else '未与能天使同站'} → +{value:g}%")
        working_ids = set(context.working_operator_ids)
        if "bskill_tra_par&per2" in icons:
            count = sum(operator_id in working_ids for operator_id in ("char_4087_ines", "char_113_cqbw"))
            value = 5.0 * count
            delta += value
            modeled.add("bskill_tra_par&per2")
            notes.append(f"白手起家：伊内丝/W 工作人数 {count} × 5% = +{value:g}%")
        if "bskill_tra_ord_spd_ext1" in icons:
            value = 10.0 if "char_4145_ulpia" in working_ids else 0.0
            delta += value
            modeled.add("bskill_tra_ord_spd_ext1")
            notes.append(f"对陆接洽：{'乌尔比安在基建工作' if value else '乌尔比安未在基建工作'} → +{value:g}%")
        if "bskill_tra_ord_spd_ext3" in icons:
            value = 10.0 if "char_427_vigil" in working_ids else 0.0
            delta += value
            modeled.add("bskill_tra_ord_spd_ext3")
            notes.append(f"家族经营：{'伺夜在基建工作' if value else '伺夜未在基建工作'} → +{value:g}%")
        if "bskill_ord_spd&tag1" in icons:
            count = min(10, context.elite_staffed_facility_count)
            value = 2.0 * count
            delta += value
            modeled.add("bskill_ord_spd&tag1")
            notes.append(f"精英小队：进驻精英干员的设施 {count} 间 × 2% = +{value:g}%")
        if "bskill_ord_spd&tag2" in icons:
            count = min(5, context.sui_staffed_facility_count)
            value = 4.0 * count
            delta += value
            modeled.add("bskill_ord_spd&tag2")
            notes.append(f"孺子可教：进驻岁干员的设施 {count} 间 × 4% = +{value:g}%")
        if "bskill_tra_orchd2" in icons:
            count = len(ids & RIIC_TERMS["bubble_hunter"])
            value = 20.0 * count
            delta += value
            modeled.add("bskill_tra_orchd2")
            notes.append(f"队长的自觉：泡影国狩猎小队 {count} 名 × 20% = +{value:g}%")
        reception_rules = {
            "bskill_tra_spd&meet1": (5.0, 40.0, "新城贸易"),
            "bskill_tra_spd&meet": (5.0, 30.0, "天生的顾问"),
        }
        for icon, (per_level, cap, label) in reception_rules.items():
            if icon not in icons:
                continue
            owner = next(operator for operator in team if icon in operator["icons"])
            direct = _other_direct_production([owner], "", "trade")
            # The game-data direct efficiency is already in base_speed; only
            # add the reception-room component here.
            value = min(per_level * 3.0, max(0.0, cap - direct))
            delta += value
            modeled.add(icon)
            notes.append(f"{label}：三级会客室额外 +{value:g}%")
        order_bonus = _positive_order_limit_bonus(team)
        if "bskill_trade_ord_spd_variable" in icons:
            value = 4.0 * order_bonus
            delta += value
            modeled.add("bskill_trade_ord_spd_variable")
            notes.append(f"招商引资：干员增加订单上限 {order_bonus} × 4% = +{value:g}%")
        if "bskill_tra_limit2spd" in icons:
            value = min(100.0, float(order_bonus // 5) * 25.0)
            delta += value
            modeled.add("bskill_tra_limit2spd")
            notes.append(f"冠军风采：干员增加订单上限 {order_bonus} → +{value:g}%")
        if "bskill_tra_limit_count" in icons:
            other_speed = max(0.0, base_speed)
            reduced = int(other_speed // 10.0)
            notes.append(f"市井之道：其他订单效率折算使订单上限 -{reduced}")
            modeled.add("bskill_tra_limit_count")
        if "bskill_tra_spd&wt1" in icons:
            modeled.add("bskill_tra_spd&wt1")
            notes.append("天真的谈判者：订单固定为 2 赤金（产出分布已单独结算）")
        if "bskill_tra_limit_diff" in icons:
            limit = _order_limit(team) + control_order_limit
            if "bskill_tra_limit_count" in icons:
                limit = max(1, limit - int(max(0.0, base_speed) // 10.0))
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
        control_factory_speed = _effective_control_factory_speed(context)
        facility_speed, facility_notes, facility_icons = _facility_count_speed(team, product, context)
        control_local_speed, control_local_notes = _control_local_factory_speed(team, product, context)
        reset_icons = icons & MANUFACTURE_RESET_ICONS
        if reset_icons:
            # Reset skills erase every local production contribution except
            # effects explicitly based on a facility/population count.  Apply
            # this before any warehouse/ramp/token converter can be added.
            delta -= base_speed
            delta += facility_speed
            modeled.update(reset_icons | facility_icons)
            suppressed = [
                operator["name"] for operator in team
                if not (operator["icons"] & MANUFACTURE_RESET_ICONS)
                and any(skill.get("room") == "MANUFACTURE" for skill in operator["skills"])
            ]
            labels = "、".join(suppressed) or "无"
            notes.append(f"生产力清零规则：非设施数量加成不生效（被清除：{labels}）")
            notes.extend(facility_notes)
            delta += control_factory_speed
            delta += control_local_speed
            notes.extend(control_local_notes)
            if control_factory_speed:
                notes.append(f"控制中枢全制造站全局 +{control_factory_speed:g}%")
                use_state("control_factory_speed", "全制造站效率", control_factory_speed,
                          control_factory_speed, "控制中枢同类全局增益取最高，不属于同站干员加成")
            if product == "gold" and context.control_gold_factory_speed:
                delta += context.control_gold_factory_speed
                notes.append(f"控制中枢贵金属全局 +{context.control_gold_factory_speed:g}%")
                use_state("control_gold_factory_speed", "贵金属制造效率", context.control_gold_factory_speed,
                          context.control_gold_factory_speed, "控制中枢贵金属全局增益")
            local_abyssal = len(ids & ABYSSAL_HUNTER_IDS)
            if local_abyssal and context.abyssal_factory_percent_per_hunter:
                total_abyssal = context.abyssal_factory_count or local_abyssal
                value = min(90.0, context.abyssal_factory_percent_per_hunter * total_abyssal)
                delta += value
                notes.append(f"制造站深海猎人总数 {total_abyssal}：控制中枢特殊加成 +{value:g}%")
                use_state("abyssal_factory_count", "深海猎人协同", total_abyssal, value,
                          f"{total_abyssal:g} 名 × {context.abyssal_factory_percent_per_hunter:g}%")
            return {"delta": delta, "notes": notes, "effects": effects,
                    "time_profiles": time_profiles, "modeled_icons": modeled}

        delta += facility_speed
        modeled.update(facility_icons)
        notes.extend(facility_notes)
        ramp_rules = {
            "bskill_man_spd_add1": (20.0, 1.0, 25.0, "急性子"),
            "bskill_man_spd_add2": (15.0, 2.0, 25.0, "慢性子"),
            "bskill_man_spd_add3": (0.0, 2.0, 20.0, "例行清扫"),
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
        delta += control_factory_speed
        delta += control_local_speed
        notes.extend(control_local_notes)
        if control_factory_speed:
            notes.append(f"控制中枢全局 +{control_factory_speed:g}%")
            use_state("control_factory_speed", "全制造站效率", control_factory_speed, control_factory_speed,
                      "控制中枢同类全局增益取最高")
        if product == "gold" and context.control_gold_factory_speed:
            delta += context.control_gold_factory_speed
            notes.append(f"控制中枢贵金属全局 +{context.control_gold_factory_speed:g}%")
            use_state("control_gold_factory_speed", "贵金属制造效率", context.control_gold_factory_speed,
                      context.control_gold_factory_speed, "控制中枢贵金属全局增益")
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
        capacities = _static_capacity_by_operator(team, product, context)
        conditional_capacity_fraction = max(0.0, context.shift_hours - 16.0) / max(context.shift_hours, 1e-9)
        if "bskill_man_spd_add&cost" in icons:
            value = 10.0 * conditional_capacity_fraction
            delta += value
            modeled.add("bskill_man_spd_add&cost")
            notes.append(f"窗外雪啸：心情落差超过 12 的班次占比 {conditional_capacity_fraction * 100:.1f}% → +{value:g}%")
        if "bskill_man_spd_variable31" in icons:
            # Bubble explicitly has priority over Red Cloud and evaluates each
            # worker's own positive capacity separately.
            value = sum(capacity if capacity <= 16.0 else capacity * 3.0 for capacity in capacities.values())
            if "bskill_man_spd_add&cost" in icons:
                value += 6.0 * conditional_capacity_fraction
            delta += value
            modeled.add("bskill_man_spd_variable31")
            if "bskill_man_spd_variable11" in icons:
                modeled.add("bskill_man_spd_variable11")
            detail = "、".join(f"{operator['name']} {capacities[operator['id']]:g}格" for operator in team)
            notes.append(f"泡泡仓容转换（优先于红云）：{detail} → +{value:g}%")
        elif "bskill_man_spd_variable11" in icons:
            capacity = sum(capacities.values())
            value = 2.0 * capacity
            if "bskill_man_spd_add&cost" in icons:
                value += 12.0 * conditional_capacity_fraction
            delta += value
            modeled.add("bskill_man_spd_variable11")
            notes.append(f"红云仓容转换：静态正仓容 {capacity:g} × 2% = +{value:g}%")
        if "bskill_man_spd_variable21" in icons:
            owner = next(operator for operator in team if "bskill_man_spd_variable21" in operator["icons"])
            partner_speed = max(0.0, _other_direct_production(team, owner["id"], product))
            value = min(40.0, float(int(partner_speed // 5.0) * 5))
            delta += value
            modeled.add("bskill_man_spd_variable21")
            notes.append(f"配合意识：其他干员非设施数量生产力 {partner_speed:g}% → +{value:g}%")
        skill_tag_rules = {
            "bskill_man_skill_spd": (lambda operator: bool(operator["icons"] & {"bskill_man_spd1", "bskill_man_spd2"}), "标准化"),
            "bskill_man_skill_spd2": (lambda operator: operator.get("group_id") == "rhine" and bool(operator["icons"] & {"bskill_man_spd1", "bskill_man_spd2", "bskill_man_spd3"}), "莱茵科技"),
            "bskill_man_skill_spd3": (lambda operator: bool(operator["icons"] & {"bskill_man_gold1", "bskill_man_gold2"}), "金属工艺"),
        }
        for icon, (matches, label) in skill_tag_rules.items():
            if icon not in icons:
                continue
            count = sum(matches(operator) for operator in team)
            value = 5.0 * count
            delta += value
            modeled.add(icon)
            notes.append(f"{label}类技能 {count} 个 × 5% = +{value:g}%")
        if "bskill_man_gold&blacksteel" in icons and product == "gold":
            count = min(3, context.working_group_counts.get("blacksteel", 0))
            value = 2.0 * count
            delta += value
            modeled.add("bskill_man_gold&blacksteel")
            notes.append(f"挑大梁：基建工作中的黑钢国际 {count} 名 × 2% = +{value:g}%")
        if "bskill_man_gold&rhine" in icons and product == "gold":
            count = min(5, context.working_group_counts.get("rhine", 0))
            value = 3.0 * count
            delta += value
            modeled.add("bskill_man_gold&rhine")
            notes.append(f"造价高昂：基建工作中的莱茵生命 {count} 名 × 3% = +{value:g}%")
        if "bskill_formula_spd_sunbr" in icons and product == "exp":
            value = 35.0 if "char_196_sunbr" in context.trade_operator_ids else 0.0
            delta += value
            modeled.add("bskill_formula_spd_sunbr")
            notes.append(f"患难拍档：{'古米在贸易站' if value else '古米不在贸易站'} → +{value:g}%")
        if "bskill_man_A1" in icons:
            owner = next(operator for operator in team if "bskill_man_A1" in operator["icons"])
            count = sum(operator.get("team_id") == "reserve1" for operator in team)
            if owner.get("team_id") != "reserve1":
                count += 1
            value = 10.0 * count
            delta += value
            modeled.add("bskill_man_A1")
            notes.append(f"重聚时光：本站 A1 小队 {count} 名 × 10% = +{value:g}%")
        if "bskill_man_spd_veen" in icons:
            value = min(30.0, 10.0 * 3.0)
            delta += value
            modeled.add("bskill_man_spd_veen")
            notes.append(f"手艺人：三级训练室 +{value:g}%")
        named_partner_rules = {
            "bskill_man_spd_double": ("温米", "gold", 15.0),
            "bskill_man_spd_double2": ("酒神", "exp", 30.0),
        }
        for icon, (partner, required_product, value) in named_partner_rules.items():
            if icon not in icons or product != required_product:
                continue
            contribution = value if partner in names else 0.0
            delta += contribution
            modeled.add(icon)
            notes.append(f"同站协作：{'存在' if contribution else '不存在'}{partner} → +{contribution:g}%")
        if "bskill_formula_spd_headb2" in icons and product == "exp":
            owner = next(operator for operator in team if "bskill_formula_spd_headb2" in operator["icons"])
            teammate = any(operator["id"] != owner["id"] and operator.get("team_id") == "student" for operator in team)
            value = 10.0 if teammate else 0.0
            delta += value
            modeled.add("bskill_formula_spd_headb2")
            notes.append(f"情同手足：{'有' if teammate else '无'}乌萨斯学生自治团队友 → +{value:g}%")
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

    elif product == "power":
        if "bskill_pow_drone" in icons:
            value = min(25.0, float(context.drone_capacity // 10))
            delta += value
            modeled.add("bskill_pow_drone")
            notes.append(f"巡线框架：无人机上限 {context.drone_capacity} / 10 = +{value:g}%")
        if "bskill_pow_spd_P" in icons:
            value = 5.0 if "凯尔希" in context.control_operator_names else 0.0
            delta += value
            modeled.add("bskill_pow_spd_P")
            notes.append(f"愉快的对谈：{'凯尔希在中枢' if value else '凯尔希不在中枢'} → +{value:g}%")
        if "bskill_power_rec_spd&dorm&lv" in icons:
            value = 0.5 * context.dorm_level_sum
            delta += value
            modeled.add("bskill_power_rec_spd&dorm&lv")
            notes.append(f"灵河共鸣：宿舍等级合计 {context.dorm_level_sum} × 0.5% = +{value:g}%")
        if "bskill_power_rec_rhine" in icons:
            owner_is_rhine = any(
                "bskill_power_rec_rhine" in operator["icons"] and operator.get("group_id") == "rhine"
                for operator in team
            )
            count = max(0, context.working_group_counts.get("rhine", 0) - int(owner_is_rhine))
            count = min(5, count)
            value = 3.0 * count
            delta += value
            modeled.add("bskill_power_rec_rhine")
            notes.append(f"生态科主任：其他莱茵生命工作干员 {count} 名 × 3% = +{value:g}%")
        if "bskill_power_rec_spd_ext&faction" in icons:
            owner_count = sum(operator.get("nation_id") == "laterano" for operator in team)
            others = max(0, context.power_nation_counts.get("laterano", 0) - owner_count)
            value = 5.0 if others else 0.0
            delta += value
            modeled.add("bskill_power_rec_spd_ext&faction")
            notes.append(f"维护中：其他发电站拉特兰干员 {others} 名 → +{value:g}%")
        if "bskill_power_rec_spd_ext&tag" in icons:
            local_platforms = sum(operator["id"] in PLATFORM_IDS for operator in team)
            others = max(0, context.platform_power_count - local_platforms)
            value = 5.0 if others else 0.0
            delta += value
            modeled.add("bskill_power_rec_spd_ext&tag")
            notes.append(f"鸡励机制：其他发电站作业平台 {others} 台 → +{value:g}%")

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
