"""Shared RIIC resource valuation used by assignment and time allocation.

The default LMD/EXP ratio follows Arknights Yituliu's item-value model.  It
uses drones as the common unit: 60 drones produce 1000 EXP, while a normal
level-3 trading chain needs 229/145 as much base work for the same nominal
amount of LMD.  Values are expressed in sanity-equivalent units.
"""

from __future__ import annotations

import math


LMD_VALUE = 36.0 / 10_000.0
EXP_VALUE = LMD_VALUE * 145.0 / 229.0
DRONE_VALUE = EXP_VALUE * (180.0 / 10_800.0 * 1000.0)
GOLD_VALUE = DRONE_VALUE / (180.0 / 4320.0)
ORUNDUM_VALUE = 135.0 / 180.0


def resource_values(settings: dict | None = None) -> dict:
    """Yituliu pricing with explicit material opportunity costs (sanity/item)."""
    settings = settings or {}
    values = {"lmd": LMD_VALUE, "exp": EXP_VALUE, "drone": DRONE_VALUE, "gold": GOLD_VALUE,
              "orundum": ORUNDUM_VALUE, "rock": 0.0, "device": 0.0}
    for key in ("orundum", "rock", "device"):
        value = float(settings.get(key, values[key]))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} 的理智价值必须为有限非负数")
        values[key] = value
    strategy = settings.get("orundum_pricing", "custom")
    if strategy not in {"custom", "rock", "device"}:
        raise ValueError("合成玉定价须为 custom、rock 或 device")
    if strategy in {"rock", "device"}:
        if strategy not in settings:
            raise ValueError("按搓玉配方定价时必须提供对应材料的理智价值")
        count, lmd = (2, 1600) if strategy == "rock" else (1, 1000)
        values["orundum"] = (values[strategy] * count + lmd * LMD_VALUE + 40 * DRONE_VALUE) / 10
    # One shard can be exchanged for ten orundum using twenty drones of
    # baseline trading work. Value remaining shards and spent shards equally.
    values["shard"] = 10 * values["orundum"] - 20 * DRONE_VALUE
    values["unpriced_materials"] = [key for key in ("rock", "device") if key not in settings]
    return values


def candidate_daily_value(candidate: dict, product: str) -> float:
    """Return one room candidate's comparable daily resource value."""
    values = resource_values(candidate.get("valuation"))
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
        economy = candidate.get("orundum") or {}
        return (float(economy.get("orundum_per_day", 0) or 0) * values["orundum"]
                - float(economy.get("shards_per_day", 0) or 0) * values["shard"])
    if product == "shard":
        recipe = candidate.get("shard_recipe", "rock")
        count, lmd = (1, 1000) if recipe == "device" else (2, 1600)
        return 24 * float(candidate.get("multiplier", 0) or 0) * (
            values["shard"] - lmd * LMD_VALUE - count * values[recipe])
    return 0.0


def metrics_daily_value(metrics: dict) -> float:
    """Value a complete resource ledger without double-counting drones."""
    values = resource_values(metrics.get("valuation"))
    return (
        (float(metrics.get("lmd_per_day", 0) or 0) - float(metrics.get("lmd_shard_cost_per_day", 0) or 0)) * LMD_VALUE
        + float(metrics.get("exp_per_day", 0) or 0) * EXP_VALUE
        + float(metrics.get("gold_net_per_day", 0) or 0) * GOLD_VALUE
        + float(metrics.get("orundum_per_day", 0) or 0) * values["orundum"]
        + float(metrics.get("shards_net_per_day", 0) or 0) * values["shard"]
        - float(metrics.get("shard_material_used_per_day", 0) or 0) * values[metrics.get("shard_recipe", "rock")]
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
