"""Discrete fast-forward validation for an optimized one-shift schedule."""

from __future__ import annotations

import random
from statistics import fmean, pstdev


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def _draw_order(rng: random.Random, distribution: list[dict]) -> dict:
    point = rng.random()
    cumulative = 0.0
    for order in distribution:
        cumulative += float(order["probability"])
        if point <= cumulative:
            return order
    return distribution[-1]


def _warm_distribution(distribution: list[dict], profile: dict, work_minutes: float) -> list[dict]:
    ramp = float(profile.get("ramp_hours") or 0) * 60.0
    if ramp <= 0:
        return distribution
    blend = min(1.0, max(0.0, work_minutes / ramp))
    base = profile.get("base") or [0.30, 0.50, 0.20]
    terminal = profile.get("terminal") or base
    result = []
    for index, order in enumerate(distribution):
        item = dict(order)
        item["probability"] = float(base[index]) + blend * (float(terminal[index]) - float(base[index]))
        result.append(item)
    return result


def simulate(payload: dict) -> dict:
    rooms = payload.get("rooms") or []
    expected = payload.get("metrics") or {}
    days = max(1, min(365, int(payload.get("days", 30))))
    trials = max(100, min(5000, int(payload.get("trials", 1000))))
    raw_seed = payload.get("seed")
    seed = int(raw_seed) if raw_seed not in (None, "") else random.SystemRandom().randrange(1, 2**63)
    drone_hours = float(expected.get("drone_hours_per_day", 0) or 0)
    drone_note = str(expected.get("drone_target") or "")
    drone_allocations = (expected.get("drone_effect") or {}).get("allocations") or []
    drone_minutes_by_operators = {
        tuple(sorted(str(operator) for operator in allocation.get("target_operators") or [])):
            float(allocation.get("drones_per_day", 0) or 0) * 3.0
        for allocation in drone_allocations
    }
    external_gold = float(expected.get("gold_external_per_day", 0) or 0)

    lmd_samples: list[float] = []
    gold_used_samples: list[float] = []
    rng = random.Random(seed)
    trade_rooms = [room for room in rooms if room.get("key") == "trade" and room.get("trade")]
    for _ in range(trials):
        lmd = 0.0
        gold_used = 0.0
        for room in trade_rooms:
            names = " / ".join(room.get("names") or [])
            signature = tuple(sorted(str(operator) for operator in room.get("operators") or []))
            extra = drone_minutes_by_operators.get(signature, drone_hours * 60.0 if names and names in drone_note else 0.0)
            horizon = days * (1440.0 + extra)
            elapsed = 0.0
            multiplier = float(room.get("multiplier", 1.0))
            distribution = room["trade"]["distribution"]
            while True:
                # The analytical layer stores the already integrated
                # shift-average distribution.  Replay that same distribution
                # here; applying the warm-up curve a second, order-start-weighted
                # way creates a systematic 3–5% mismatch that more trials can
                # never remove.
                order = _draw_order(rng, distribution)
                elapsed += float(order["minutes"]) / multiplier
                if elapsed > horizon:
                    break
                lmd += float(order["lmd"])
                gold_used += float(order["gold"])
        lmd_samples.append(lmd / days)
        gold_used_samples.append(gold_used / days)

    gold_made = 0.0
    experience = 0.0
    shards_made = 0.0
    shards_used = 0.0
    orundum = 0.0
    for room in rooms:
        key = room.get("key")
        if key not in {"gold", "exp", "shard", "orundum"}:
            continue
        names = " / ".join(room.get("names") or [])
        signature = tuple(sorted(str(operator) for operator in room.get("operators") or []))
        extra = drone_minutes_by_operators.get(signature, drone_hours * 60.0 if names and names in drone_note else 0.0)
        horizon = days * (1440.0 + extra)
        multiplier = float(room.get("multiplier", 1.0))
        if key == "gold":
            gold_made += int(horizon * multiplier / 72.0) / days
        elif key == "exp":
            experience += int(horizon * multiplier / 180.0) * 1000.0 / days
        elif key == "shard":
            shards_made += int(horizon * multiplier / 60.0) / days
        else:
            orders = int(horizon * multiplier / 120.0) / days
            orundum += orders * 20.0
            shards_used += orders * 2.0

    lmd_mean = fmean(lmd_samples)
    gold_used_mean = fmean(gold_used_samples)
    simulated = {
        "lmd_per_day": round(lmd_mean, 2),
        "lmd_p05": round(_percentile(lmd_samples, 0.05), 2),
        "lmd_p95": round(_percentile(lmd_samples, 0.95), 2),
        "exp_per_day": round(experience, 2),
        "gold_made_per_day": round(gold_made, 3),
        "gold_used_per_day": round(gold_used_mean, 3),
        "gold_external_per_day": round(external_gold, 3),
        "gold_production_net_per_day": round(gold_made - gold_used_mean, 3),
        "gold_net_per_day": round(gold_made + external_gold - gold_used_mean, 3),
        "orundum_per_day": round(orundum, 3),
        "shards_made_per_day": round(shards_made, 3),
        "shards_used_per_day": round(shards_used, 3),
        "shards_net_per_day": round(shards_made - shards_used, 3),
    }
    sample_run = {
        "lmd_per_day": round(lmd_samples[0], 2),
        "gold_used_per_day": round(gold_used_samples[0], 3),
        "gold_net_per_day": round(gold_made + external_gold - gold_used_samples[0], 3),
    }

    # A transparent inventory ledger at the same collection events used by the
    # schedule. Production and orders are allowed to run from an existing
    # working stock; zero in the optional stock field means "unknown", not that
    # trade must wait for a newly manufactured first batch.
    collection_hours = max(1.0, min(24.0, float(expected.get("collection_interval_hours", 8) or 8)))
    gold_stock = float(expected.get("gold_inventory", 0) or 0)
    shard_stock = float(expected.get("shard_inventory", 0) or 0)
    collection_events = []
    for hour in range(int(collection_hours), 49, int(collection_hours)):
        fraction = collection_hours / 24.0
        gold_stock += (gold_made + external_gold - gold_used_mean) * fraction
        shard_stock += (shards_made - shards_used) * fraction
        collection_events.append({"hour": hour, "gold": round(gold_stock, 2), "shards": round(shard_stock, 2)})

    def delta(key: str) -> float | None:
        baseline = expected.get(key)
        if not isinstance(baseline, (int, float)) or abs(float(baseline)) < 1e-9:
            return None
        return round((simulated[key] - float(baseline)) / abs(float(baseline)) * 100.0, 3)

    assumptions = [
        "贸易站逐笔随机生成订单；制造站按完整产品离散结算。",
        f"制造站与贸易站按每 {collection_hours:g} 小时同一节点结算库存；排班期望假设开班已有足够周转库存，不做从零启动串行阻塞。",
        "心情耗尽与恢复由排班器审计；本随机层只重放在岗期间的产品和订单。",
        "订单品质先按班内线性暖机曲线积分成班均分布；快进与解析层重放同一分布，换班时重新开始暖机。",
        "无人机按收取节点分配给贸易站与制造站；随机层把各节点投入折算为对应房间的额外倒计时时间。",
    ]
    if any("平均空位" in note for room in rooms for note in room.get("mechanic_notes", [])):
        assumptions.append("孑的订单空位加成先由收单周期稳态队列折算为班均速度；随机层尚未逐格重放订单仓库。")
    return {
        "days": days,
        "trials": trials,
        "seed": seed,
        "simulated": simulated,
        "sample_run": sample_run,
        "standard_deviation": {"lmd_per_day": round(pstdev(lmd_samples), 3)},
        "expected": expected,
        "difference_percent": {
            key: delta(key) for key in ("lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
                                        "orundum_per_day", "shards_made_per_day", "shards_used_per_day")
        },
        "collection_events": collection_events,
        "assumptions": assumptions,
    }
