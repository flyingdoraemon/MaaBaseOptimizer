"""Seeded discrete-event replay of physical rooms on one virtual clock.

No wall-clock sleeps, daily-output multiplication, or averaging independent
A/B simulations. Work in progress belongs to the room and survives handovers.
"""
from __future__ import annotations

import math
import random
from statistics import fmean, pstdev

from .scheduler import _instant_multiplier
from .login_calendar import login_hours
from .morale_runtime import compile_morale

PRODUCTS = {"gold": (72.0, {"gold_made_per_day": 1.0}),
            "exp": (180.0, {"exp_per_day": 1000.0}),
            "shard": (60.0, {"shards_made_per_day": 1.0}),
            "orundum": (120.0, {"shards_used_per_day": 2.0, "orundum_per_day": 20.0})}
KEYS = ("lmd_per_day", "exp_per_day", "gold_made_per_day", "gold_used_per_day",
        "shards_made_per_day", "shards_used_per_day", "orundum_per_day")
EPS = 1e-8


def _number(value, label: str, minimum=0.0, maximum=math.inf) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须为有限数值") from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} 必须在 {minimum:g} 至 {maximum:g} 之间")
    return number


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)] if ordered else 0.0


def _warm_distribution(distribution: list[dict], profile: dict, work_minutes: float) -> list[dict]:
    ramp = float(profile.get("ramp_hours") or 0) * 60
    if ramp <= 0 or len(distribution) != 3:
        return distribution
    blend = min(1.0, max(0.0, work_minutes / ramp))
    base = profile.get("base") or [0.30, 0.50, 0.20]
    terminal = profile.get("terminal") or base
    return [{**order, "probability": a + blend * (b - a)}
            for order, a, b in zip(distribution, base, terminal)]


def _draw_order(rng: random.Random, distribution: list[dict]) -> dict:
    point = rng.random() * sum(float(order["probability"]) for order in distribution)
    for order in distribution:
        point -= float(order["probability"])
        if point <= 0:
            return order
    return distribution[-1]


def _schedules(payload: dict) -> tuple[list[dict], float]:
    rotation = payload.get("rotation") or {}
    # A common period of independent room cycles can exceed the displayed
    # week (e.g. 32h, 40h and 48h repeat together after 480h). The simulation
    # horizon is bounded separately; never cap or reject that repeat period.
    cycle = _number(rotation.get("natural_cycle_hours") or rotation.get("cycle_hours") or 24,
                    "轮班周期", 0.01) * 60
    schedules = []
    if rotation:
        sources = {(label, room["room"]): room for label, team in rotation.get("teams", {}).items()
                   for room in [*team.get("rooms", []), *team.get("support_rooms", [])]}
        for row in rotation.get("rooms", []):
            spans = []
            for event in row.get("events", []):
                source = sources.get((event["team"], row["room"]))
                if source is None:
                    if row.get("key") in {*PRODUCTS, "trade", "power"}:
                        raise ValueError(f"轮班缺少房间数据：{row['room']} / {event['team']}")
                    continue
                start, end = float(event["start"]) * 60, float(event["end"]) * 60
                if start < cycle and end > start:
                    spans.append((start, min(end, cycle), {**source, "_team": event["team"],
                                  "_elapsed_offset_hours": float(event.get("elapsed_offset_hours", 0))}))
            if spans:
                schedules.append({"name": row["room"], "spans": sorted(spans, key=lambda span: span[0])})
    else:
        for i, room in enumerate(payload.get("rooms") or []):
            fraction = _number(room.get("work_fraction", 1), "在岗比例", 0, 1)
            if fraction:
                schedules.append({"name": room.get("room") or f"room-{i}",
                                  "spans": [(0.0, cycle * fraction, room)]})
    names = [row["name"] for row in schedules]
    if len(set(names)) != len(names):
        raise ValueError("物理房间名称必须唯一；A/B 班请通过 rotation 时间线传入")
    for row in schedules:
        previous_end = 0.0
        products = set()
        for start, end, room in row["spans"]:
            if not 0 <= start < end <= cycle or start < previous_end - EPS:
                raise ValueError("房间轮班时间重叠或越界")
            previous_end = end
            key = room.get("key")
            products.add(key)
            _number(room.get("multiplier", 1), "生产倍率", 0, 1000)
            if room.get("output_capacity") is not None:
                _number(room["output_capacity"], "仓库容量", 1, 100000)
            if key == "trade":
                distribution = (room.get("trade") or {}).get("distribution") or []
                if not distribution:
                    raise ValueError("贸易房间必须提供订单分布")
                for order in distribution:
                    _number(order.get("minutes"), "订单时长", 0.001)
                    for field in ("probability", "lmd", "gold"):
                        _number(order.get(field), field)
                if sum(float(x["probability"]) for x in distribution) <= 0:
                    raise ValueError("订单概率总和必须大于零")
        if len(products) > 1:
            raise ValueError("同一物理房间跨班必须保持同一产品；请先完成产品切换建模")
    return schedules, cycle


def _source(schedule: dict, minute: float, cycle: float):
    phase = minute % cycle
    for start, end, room in schedule["spans"]:
        if start <= phase < end:
            return room, phase - start + float(room.get("_elapsed_offset_hours", 0)) * 60
    return None, 0.0


def _capacity(room: dict) -> int:
    # Generated candidates carry product-count capacity. Legacy payloads have
    # no warehouse data and deliberately keep their unbounded compatibility.
    return max(1, int(room.get("output_capacity") or 10**9))


def _new_job(room: dict, elapsed: float, rng: random.Random) -> tuple[float, dict]:
    key = room.get("key")
    if key == "trade":
        economy = room["trade"]
        order = _draw_order(rng, _warm_distribution(economy["distribution"],
                            economy.get("quality_warmup") or {}, elapsed))
        return float(order["minutes"]), {"lmd_per_day": float(order["lmd"]),
                                         "gold_used_per_day": float(order["gold"])}
    return PRODUCTS[key]


def _advance(state: dict, room: dict, start: float, elapsed: float, minutes: float,
             rng: random.Random, totals: dict, trace: list | None, instant=False) -> float:
    key = room.get("key")
    if key not in {*PRODUCTS, "trade"}:
        return minutes
    speed = 1.0 if instant else max(0.0, _instant_multiplier(room, elapsed / 60))
    remaining = minutes
    cursor = start
    while remaining > EPS and speed > EPS and len(state["queue"]) < _capacity(room):
        if state["job"] is None:
            duration, reward = _new_job(room, elapsed + (0 if instant else cursor - start), rng)
            state["job"] = dict(reward)
            state["remaining"] = duration
        used = min(remaining, state["remaining"] / speed)
        state["remaining"] -= used * speed
        remaining -= used
        if not instant:
            cursor += used
        if state["remaining"] <= EPS:
            reward = state["job"]
            state["queue"].append(reward)
            for name, value in reward.items():
                totals[name] += value
            if trace is not None and len(trace) < 2000:
                trace.append({"minute": round(cursor, 6), "type": "drone_completion" if instant else "completion",
                              "room": state["name"], "product": key, "output": reward})
            state["job"] = None
    return minutes - remaining


def _run(schedules: list[dict], cycle: float, horizon: float, interval: float,
         metrics: dict, rng: random.Random, capture: bool,
         rotation: dict, catalog: dict | None, initial: dict, effect_cache: dict) -> dict:
    states = [{**row, "queue": [], "job": None, "remaining": 0.0} for row in schedules]
    totals = dict.fromkeys(KEYS, 0.0)
    collected = dict.fromkeys(KEYS, 0.0)
    trace = [] if capture else None
    ledger = []
    drone_events = []
    gold = float(metrics.get("gold_inventory", 0) or 0)
    shards = float(metrics.get("shard_inventory", 0) or 0)
    external = float(metrics.get("gold_external_per_day", 0) or 0)
    drone_bank = float(metrics.get("drone_inventory", 0) or 0)
    drone_cap = float(metrics.get("drone_capacity", 235) or 235)
    allocations = (metrics.get("drone_effect") or {}).get("allocations") or []
    # Planned split is replayed at actual collection nodes, restricted to the
    # operators currently in each physical room. Fraction is renormalized
    # across active recipients; absolute daily minutes are never added.
    collection_nodes = {round(hour * 60, 6) for hour in login_hours(interval / 60, horizon / 60, quiet=rotation.get("schedule_mode") != "fixed")}
    previous_collection = 0.

    def advance_interval(start, end, rooms):
        nonlocal drone_bank, gold, shards, previous_collection
        dt = end - start
        active = [(state, room, elapsed) for state, (room, elapsed) in zip(states, rooms)]
        busy = {}
        powers = [room for _, room, _ in active if room and room.get("key") == "power"]
        recover_per_minute = (1 + sum((5 if room.get("active_operators", room.get("operators")) else 0) + float(room.get("efficiency", 0)) for room in powers) / 100) / 6
        if not powers:
            recover_per_minute = float(metrics.get("drones_recovery_potential_per_day", 240) or 0) / 1440
        drone_bank = min(drone_cap, drone_bank + dt * recover_per_minute)
        for state, room, elapsed in active:
            if room:
                used = _advance(state, room, start, elapsed, dt, rng, totals, trace)
                for op in room.get("operators", []):
                    busy[op] = used
        is_collection = round(end, 6) in collection_nodes
        if not is_collection:
            return busy
        gold += external * (end - previous_collection) / 1440
        previous_collection = end

        def collect() -> None:
            nonlocal gold, shards
            # Factories are collected before contracts are fulfilled, so
            # contemporaneous production is available to both trade chains.
            for trade_pass in (False, True):
                for state in states:
                    pending = []
                    for reward in state["queue"]:
                        trade = "gold_used_per_day" in reward or "shards_used_per_day" in reward
                        if trade != trade_pass:
                            pending.append(reward)
                            continue
                        need_gold = reward.get("gold_used_per_day", 0)
                        need_shards = reward.get("shards_used_per_day", 0)
                        gold += reward.get("gold_made_per_day", 0) - need_gold
                        shards += reward.get("shards_made_per_day", 0) - need_shards
                        for name, value in reward.items():
                            collected[name] += value
                    state["queue"] = pending

        collect()
        targets = []
        for state, room, elapsed in active:
            if not room or room.get("key") not in {*PRODUCTS, "trade"}:
                continue
            signature = sorted(room.get("operators") or [])
            weight = sum(float(a.get("drones_per_day", 0) or 0) for a in allocations
                         if sorted(a.get("target_operators") or []) == signature
                         and (not a.get("kind") or a["kind"] == room.get("key")))
            if weight > 0:
                targets.append((state, room, max(0, elapsed + dt - EPS), weight))
        total_weight = sum(x[3] for x in targets)
        # Drones are integral. Keep rounding remainders in the bank.
        available = math.floor(drone_bank + EPS) if targets else 0
        spent = 0
        for index, (state, room, elapsed, weight) in enumerate(targets):
            count = available - spent if index == len(targets) - 1 else math.floor(available * weight / total_weight)
            for _ in range(count):
                if len(state["queue"]) >= _capacity(room):
                    break
                _advance(state, room, end, elapsed, 3.0, rng, totals, trace, instant=True)
                spent += 1
                collect()  # Player is online: collect before accelerating again.
        drone_bank -= spent
        if capture:
            ledger.append({"hour": round(end / 60, 6), "gold": round(gold, 6), "shards": round(shards, 6),
                           "collected": {**collected,
                               "lmd_shard_cost_per_day": totals["shards_made_per_day"] * (1000 if metrics.get("shard_recipe") == "device" else 1600),
                               "lmd_net_after_shards_per_day": collected["lmd_per_day"] - totals["shards_made_per_day"] * (1000 if metrics.get("shard_recipe") == "device" else 1600)},
                           "drones": round(drone_bank, 6)})
            drone_events.append({"minute": round(end, 6), "drones_spent": spent,
                                 "drones_remaining": round(drone_bank, 6)})
        return busy

    _, morale_report = compile_morale(schedules, cycle, horizon, interval, rotation, catalog, initial,
                                      on_interval=advance_interval, effect_cache=effect_cache)
    days = horizon / 1440
    # Report delivered/collected goods; completed but uncollected items remain
    # explicitly in pending_output and are not silently sold at the horizon.
    daily = {key: value / days for key, value in collected.items()}
    daily.update(gold_external_per_day=external,
                 gold_production_net_per_day=daily["gold_made_per_day"] - daily["gold_used_per_day"],
                 gold_net_per_day=(gold - float(metrics.get("gold_inventory", 0) or 0)) / days,
                 shards_net_per_day=(shards - float(metrics.get("shard_inventory", 0) or 0)) / days)
    recipe = metrics.get("shard_recipe", "rock")
    daily["lmd_shard_cost_per_day"] = totals["shards_made_per_day"] / days * (1000 if recipe == "device" else 1600)
    daily["shard_material_used_per_day"] = totals["shards_made_per_day"] / days * (1 if recipe == "device" else 2)
    daily["lmd_net_after_shards_per_day"] = daily["lmd_per_day"] - daily["lmd_shard_cost_per_day"]
    pending = {key: totals[key] - collected[key] for key in KEYS}
    return {"daily": daily, "trace": trace, "morale": morale_report, "collection_events": ledger, "drone_events": drone_events,
            "pending_output": pending, "completed_output": totals,
            "work_in_progress": [{"room": s["name"], "remaining_base_minutes": round(s["remaining"], 6),
                                  "pending_items": len(s["queue"])} for s in states]}


def simulate(payload: dict, catalog: dict | None = None) -> dict:
    rotation = payload.get("rotation") or {}
    expected = rotation.get("average_metrics") or payload.get("metrics") or {}
    days = int(_number(payload.get("days", 30), "天数", 1, 365))
    trials = int(_number(payload.get("trials", 1000), "试验次数", 1, 5000))
    raw_seed = payload.get("seed")
    seed = int(raw_seed) if raw_seed not in (None, "") else random.SystemRandom().randrange(1, 2**53)
    public_seed = seed if abs(seed) < 2**53 else str(seed)
    schedules, cycle = _schedules(payload)
    interval = _number(expected.get("collection_interval_hours", rotation.get("collection_interval_hours", 8)),
                       "收取间隔", 0.01, 24) * 60
    policy = payload.get("inventory_policy", "working_stock")
    if policy not in {"working_stock", "strict"}:
        raise ValueError("库存策略须为 working_stock 或 strict")
    for key in ("gold_inventory", "shard_inventory", "drone_inventory", "gold_external_per_day"):
        _number(expected.get(key, 0), key, 0)
    # Raw materials have external supply. Keep accepting old saved UI values
    # but never stall production/settlement on an inventory balance.
    initial = payload.get("initial_morale") or {}
    for value in initial.values():
        _number(value, "初始心情", 0, 24)
    effect_cache = {}
    rng = random.Random(seed)
    first = _run(schedules, cycle, days * 1440, interval, expected, rng, True, rotation, catalog, initial, effect_cache)
    first["trace"].sort(key=lambda event: (event["minute"], event["room"]))
    samples = [first["daily"]]
    # Deterministic manufacturing-only schedules need just one replay.
    stochastic = any(room.get("key") == "trade" and len(room["trade"]["distribution"]) > 1
                     for row in schedules for _, _, room in row["spans"])
    for _ in range(trials - 1):
        samples.append(_run(schedules, cycle, days * 1440, interval, expected, rng, False, rotation, catalog, initial, effect_cache)["daily"]
                       if stochastic else first["daily"])
    simulated = {key: round(fmean(sample[key] for sample in samples), 6) for key in first["daily"]}
    lmd_samples = [sample["lmd_per_day"] for sample in samples]
    net_samples = [sample["lmd_net_after_shards_per_day"] for sample in samples]
    simulated.update(lmd_net_p05=round(_percentile(net_samples, .05), 3),
                     lmd_net_p95=round(_percentile(net_samples, .95), 3))
    simulated.update(lmd_p05=round(_percentile(lmd_samples, .05), 3), lmd_p95=round(_percentile(lmd_samples, .95), 3))
    differences = {key: (round((simulated[key] - expected[key]) / abs(expected[key]) * 100, 3)
                        if isinstance(expected.get(key), (int, float)) and abs(expected[key]) > EPS else None)
                   for key in (*KEYS, "lmd_shard_cost_per_day", "lmd_net_after_shards_per_day")}
    assumptions = [
        "离散事件快进：同一虚拟时钟逐件/逐单完成，跨班保留物理房间进度；无真实时间等待。",
        "按实际换班时间切换倍率；整点技能分段，品质按订单开始时的在岗时间线性暖机，换班重新暖机。",
        "品质暖机曲线仍为线性近似；孑等队列联动速度仍使用候选模型。心情连续消耗/恢复，归零后重算有效技能，不自动换班。",
        "仓库容量来自候选；旧版未携带容量的输入按无限仓库兼容。收取前不计入可用库存，终点不额外强制收菜。",
        "无人机逐架在上线节点投入，按当时在岗目标分流，跨节点保留无人机库存。",
        "碎片原料和龙门币供应视为充足，实际消耗单独记账；尚未模拟材料耗尽停产。",
        "材料视为有外部补给，赤金/碎片允许负库存并单独记账；旧 strict 设置也不会因材料缺口停产或拒绝交单。",
        "复杂宿舍条件群回/单体恢复、部分中枢特殊叠加仍为受限模型，不代表全游戏机制精确仿真。",
        "心情在试验内跨日延续，制造/贸易满仓停止工作时暂停心情消耗；宿舍床位只在上线时分配。",
    ]
    if not rotation and any(room.get("work_fraction", 1) != 1 for room in payload.get("rooms") or []):
        assumptions.append("旧版实际在岗比例输入按每日开头连续在岗处理；完整 A/B 重放须提供 rotation。")
    return {"engine": "discrete_event", "days": days, "trials": trials, "seed": public_seed,
            "virtual_minutes": days * 1440, "morale": first["morale"], "inventory_policy": "working_stock", "simulated": simulated, "sample_run": first["daily"],
            "standard_deviation": {"lmd_per_day": round(pstdev(lmd_samples), 3),
                                   "lmd_net_after_shards_per_day": round(pstdev(net_samples), 3)},
            "expected": expected, "difference_percent": differences, "assumptions": assumptions,
            **{key: first[key] for key in ("trace", "collection_events", "drone_events", "pending_output",
                                          "completed_output", "work_in_progress")},
            "trace_limit": 2000, "trace_is_first_trial": True}
