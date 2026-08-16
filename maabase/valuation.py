"""Shared RIIC resource valuation used by assignment and time allocation.

The default LMD/EXP ratio follows Arknights Yituliu's item-value model.  It
uses drones as the common unit: 60 drones produce 1000 EXP, while a normal
level-3 trading chain needs 229/145 as much base work for the same nominal
amount of LMD.  Values are expressed in sanity-equivalent units.
"""

from __future__ import annotations


LMD_VALUE = 36.0 / 10_000.0
EXP_VALUE = LMD_VALUE * 145.0 / 229.0
DRONE_VALUE = EXP_VALUE * (180.0 / 10_800.0 * 1000.0)
GOLD_VALUE = DRONE_VALUE / (180.0 / 4320.0)
ORUNDUM_VALUE = 135.0 / 180.0


def candidate_daily_value(candidate: dict, product: str) -> float:
    """Return one room candidate's comparable daily resource value."""
    if product == "trade":
        trade = candidate.get("trade") or {}
        return (
            float(trade.get("lmd_per_day", 0) or 0) * LMD_VALUE
            - float(trade.get("gold_per_day", 0) or 0) * GOLD_VALUE
        )
    if product == "exp":
        return 8000.0 * float(candidate.get("multiplier", 0) or 0) * EXP_VALUE
    if product == "gold":
        return 20.0 * float(candidate.get("multiplier", 0) or 0) * GOLD_VALUE
    if product == "power":
        extra_drones = 240.0 * (5.0 + float(candidate.get("efficiency", 0) or 0)) / 100.0
        return extra_drones * DRONE_VALUE
    if product == "orundum":
        return float((candidate.get("orundum") or {}).get("orundum_per_day", 0) or 0) * ORUNDUM_VALUE
    if product == "shard":
        # Rock/device opportunity cost is user-specific.  Use production speed
        # to rank shard rooms, while the result ledger exposes the real input
        # quantities instead of pretending this is a universal sanity value.
        return 20.0 * float(candidate.get("multiplier", 0) or 0) * GOLD_VALUE
    return 0.0


def metrics_daily_value(metrics: dict) -> float:
    """Value a complete resource ledger without double-counting drones."""
    return (
        float(metrics.get("lmd_per_day", 0) or 0) * LMD_VALUE
        + float(metrics.get("exp_per_day", 0) or 0) * EXP_VALUE
        + float(metrics.get("gold_net_per_day", 0) or 0) * GOLD_VALUE
        + float(metrics.get("orundum_per_day", 0) or 0) * ORUNDUM_VALUE
    )


def metrics_layout_score(metrics: dict) -> float:
    """Score a full shift by the output categories fixed by its layout."""
    score = (
        float(metrics.get("lmd_per_day", 0) or 0) / 10_265.4867256637
        + float(metrics.get("exp_per_day", 0) or 0) / 8000.0
        + float(metrics.get("gold_made_per_day", 0) or 0) / 20.0
        + float(metrics.get("orundum_per_day", 0) or 0) / 240.0
        + float(metrics.get("shards_made_per_day", 0) or 0) / 24.0
    )
    # Power stations matter through the drones already routed into the output
    # metrics, so drones are not added as a separate resource here.
    return score


def public_valuation() -> dict:
    return {
        "unit": "sanity_equivalent_per_day",
        "lmd": round(LMD_VALUE, 9),
        "exp": round(EXP_VALUE, 9),
        "drone": round(DRONE_VALUE, 9),
        "gold": round(GOLD_VALUE, 9),
        "orundum": round(ORUNDUM_VALUE, 9),
        "lmd_to_exp_ratio": round(LMD_VALUE / EXP_VALUE, 9),
        "note": "默认钱书价值比 229/145；无人机按 60 架加速 1000 EXP，赤金按 24 架无人机/根折算。",
    }
