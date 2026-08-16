"""Mechanic-level rules shared by operators with the same RIIC effect.

The game data identifies skills by stable buff icons.  Rules belong here by
effect type; operator names must never be used as calculation switches.
"""

from __future__ import annotations

from dataclasses import dataclass


TRADE_RULES: dict[str, tuple[str, object]] = {
    # Order-quality warm-up changes the 2/3/4-gold steady-state distribution.
    "bskill_tra_wt&cost1": ("probabilities", (0.15, 0.30, 0.55)),
    "bskill_tra_wt&cost2": ("probabilities", (0.05, 0.10, 0.85)),
    # A breach converts an original 2/3-gold order.  The number is both the
    # extra gold paid and, at 500 LMD per bar, its extra LMD reward.
    "bskill_tra_against": ("breach_extra_gold", 1),
    "bskill_tra_against2": ("breach_extra_gold", 2),
    # Investment only affects an original normal 4-gold order.
    "bskill_tra_long1": ("normal_large_order_lmd", 250),
    "bskill_tra_long2": ("normal_large_order_lmd", 500),
    # Whisper replaces the other two workers' speed with 45% each.
    "bskill_tra_vodfox": ("replace_other_speed", 45),
    # Contract Law marks eligible orders as breach orders.  It has no numeric
    # parameter but is retained so coverage reporting knows it is understood.
    "bskill_tra_law": ("breach_marker", True),
}

TRADE_ECONOMIC_ICONS = frozenset(TRADE_RULES)


@dataclass(frozen=True)
class TradeMechanics:
    probabilities: tuple[float, float, float] = (0.30, 0.50, 0.20)
    breach_marker: bool = False
    breach_extra_gold: int = 0
    normal_large_order_lmd: int = 0
    replace_other_speed: int = 0


def resolve_trade_mechanics(icons) -> TradeMechanics:
    """Compile all active trade buff icons into one room-level state."""
    values: dict[str, object] = {}
    for icon in sorted(icons):
        rule = TRADE_RULES.get(icon)
        if not rule:
            continue
        effect, value = rule
        # A slot only exposes the highest unlocked version, but max() also
        # keeps this deterministic for imported or synthetic data.
        current = values.get(effect)
        if isinstance(value, (int, float)) and isinstance(current, (int, float)):
            values[effect] = max(value, current)
        else:
            values[effect] = value
    return TradeMechanics(**values)


def warmed_order_probabilities(icons, shift_hours: float | None) -> tuple[tuple[float, float, float], str]:
    """Return the shift-average 2/3/4-gold distribution.

    PRTS publishes the base/terminal distributions and the 3h/5h time to the
    alpha/beta peak, but not the complete internal curve.  We use a linear
    ramp and expose that assumption in the returned label.  Passing ``None``
    requests the terminal steady state (used by formula regression tests).
    """
    icon_list = list(icons)
    alpha = icon_list.count("bskill_tra_wt&cost1")
    beta = icon_list.count("bskill_tra_wt&cost2")
    base = (0.30, 0.50, 0.20)
    if beta:
        terminal, ramp = (0.05, 0.10, 0.85), 5.0
        label = "品质 β"
    elif alpha >= 2:
        terminal, ramp = (0.13, 0.22, 0.65), 3.0
        label = "双品质 α（实测终态）"
    elif alpha:
        terminal, ramp = (0.15, 0.30, 0.55), 3.0
        label = "品质 α"
    else:
        return base, "三级站常规（30% / 50% / 20%）"
    if shift_hours is None:
        return terminal, f"{label} 稳态"
    hours = max(0.0, float(shift_hours))
    # Average of min(t/ramp, 1) over [0, hours].
    blend = hours / (2.0 * ramp) if hours <= ramp else 1.0 - ramp / (2.0 * max(hours, 1e-9))
    result = tuple(a + blend * (b - a) for a, b in zip(base, terminal))
    return result, f"{label}：{hours:g} 小时班次线性暖机均值（{blend * 100:.1f}% 峰值权重）"


def order_quality_profile(icons, shift_hours: float | None) -> dict:
    icon_list = list(icons)
    alpha = icon_list.count("bskill_tra_wt&cost1")
    beta = icon_list.count("bskill_tra_wt&cost2")
    if beta:
        terminal, ramp, level = (0.05, 0.10, 0.85), 5.0, "beta"
    elif alpha >= 2:
        terminal, ramp, level = (0.13, 0.22, 0.65), 3.0, "double_alpha"
    elif alpha:
        terminal, ramp, level = (0.15, 0.30, 0.55), 3.0, "alpha"
    else:
        terminal, ramp, level = (0.30, 0.50, 0.20), 0.0, "normal"
    return {
        "level": level,
        "base": [0.30, 0.50, 0.20],
        "terminal": list(terminal),
        "ramp_hours": ramp,
        "shift_hours": float(shift_hours) if shift_hours is not None else None,
        "curve": "linear_until_peak" if ramp else "constant",
        "reset_on_reassignment": bool(ramp),
    }


def mechanic_is_partial(skill: dict) -> bool:
    """Flag a skill whose direct +X% is only one part of its real effect.

    This is intentionally conservative.  It prevents MAA's comparison score
    or the game's base numeric field from being presented as an exact resource
    rate when a cross-room counter, faction count, threshold or warm-up also
    changes the result.
    """
    if skill.get("icon") in TRADE_ECONOMIC_ICONS:
        return False
    text = str(skill.get("description") or "")
    markers = (
        "每有", "每个", "每间", "每1", "每2", "每5", "每10", "每20",
        "如果", "若", "当", "取决于", "转化为", "特殊加成", "额外提供",
        "工作时长影响", "上限时", "心情处于", "归零",
    )
    return any(marker in text for marker in markers)
