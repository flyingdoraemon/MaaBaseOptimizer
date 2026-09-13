"""Advance coupled morale and production on a shared virtual clock.

Assignments only change at login; zero morale is a rate-change event, never a
handover. Beds stay occupied until login even if their worker becomes full.
"""
from __future__ import annotations
from dataclasses import fields
import math
import re

from .login_calendar import login_hours
from .model import evaluate_team, prepare_operators
from .state_model import BaseContext, _control_effect, ABYSSAL_HUNTER_IDS
from .work_morale import morale_rates

EPS = 1e-7


def compile_morale(schedules: list[dict], cycle: float, horizon: float, interval: float,
                   rotation: dict, catalog: dict | None = None, initial: dict | None = None, on_interval=None, effect_cache=None) -> tuple[list[dict], dict]:
    from .simulator import _source
    profiles = {}
    originals = {}
    for row in schedules:
        for _, _, room in row['spans']:
            for profile in room.get('operator_profiles') or []:
                profiles[profile['id']] = profile
            for operator in room.get('operators') or []:
                originals[operator] = room
                profiles.setdefault(operator, {'id': operator})
    prepared = {op['id']: op for op in prepare_operators(list(profiles.values()), catalog)} if catalog else {}
    morale = {operator: max(0., min(24., float((initial or {}).get(operator, 24)))) for operator in profiles}
    helper = (rotation.get('dormitory') or {}).get('locked_helper') or {}
    fiam = (rotation.get('dormitory') or {}).get('fiammetta') or {}
    beds = [None] * 20
    if helper:
        beds[0] = helper.get('id', '__helper')
    if fiam.get('enabled'):
        beds[5] = fiam.get('id', '__fiammetta')
    fiam_morale = 24.0
    nodes = {round(hour * 60, 6) for hour in login_hours(interval / 60, horizon / 60, quiet=rotation.get("schedule_mode") != "fixed")}
    boundaries = {0., horizon, *nodes}
    for iteration in range(math.ceil(horizon / cycle)):
        for row in schedules:
            for start, end, room in row['spans']:
                for profile in room.get("time_profiles") or []:
                    for phase in profile.get("phases") or []:
                        value = start + (phase["end_hour"] - float(room.get("_elapsed_offset_hours", 0))) * 60
                        if start < value < end and iteration * cycle + value < horizon:
                            boundaries.add(iteration * cycle + value)
                boundaries.update(v for v in (iteration * cycle + start, iteration * cycle + end) if 0 <= v <= horizon)
    boundaries = sorted(boundaries)
    out = [{'name': row['name'], 'spans': []} for row in schedules]
    events, fatigue = [], {operator: 0. for operator in morale}
    cache = effect_cache if effect_cache is not None else {}
    rate_cache = cache.setdefault("morale_rates", {})
    own_recovery = {op: max([0.] + [float(n) for skill in value.get('skills', [])
                    if skill.get('room') == 'DORMITORY'
                    for n in re.findall(r'自身心情每小时恢复\+([0-9.]+)', skill.get('description', ''))])
                    for op, value in prepared.items()}
    previous = None
    pointer = 1
    now = 0.
    min_morale = dict(morale)
    overflow_seen = set()

    def effective(room, active, all_rooms):
        ids = room.get('operators') or []
        relevant = set(ids) & active
        if not catalog or not set(ids) <= prepared.keys():
            if relevant == set(ids):
                return room
            # Legacy synthetic inputs have no reconstructable skills. Only
            # fully exhausted rooms can be evaluated exactly from that input.
            if relevant:
                raise ValueError('部分干员心情耗尽时需提供可识别的 operator_profiles 才能重算组合技能')
            copy = {**room, 'multiplier': 1., 'efficiency': 0., 'time_profiles': [],
                    'active_operators': [], 'output_capacity': {'gold': 27, 'exp': 10, 'shard': 18}.get(room.get('key'), 10)}
            if room.get('key') == 'trade':
                copy['trade'] = {'distribution': [
                    {'minutes': 144, 'gold': 2, 'lmd': 1000, 'probability': .3},
                    {'minutes': 210, 'gold': 3, 'lmd': 1500, 'probability': .5},
                    {'minutes': 276, 'gold': 4, 'lmd': 2000, 'probability': .2}]}
            return copy
        if room.get('key') not in {'trade', 'orundum', 'gold', 'exp', 'shard', 'power'}:
            return room
        # Cached subsets include the complete current cross-facility state.
        signature = (id(room), tuple(sorted(active)), tuple((r.get('room'), tuple(r.get('operators') or [])) for r in all_rooms),
                     tuple(sorted(op for op in active if morale.get(op, 24) <= 12)))
        if signature in cache:
            return cache[signature]
        state = room.get('base_state') or {}
        context = BaseContext(**{f.name: state[f.name] for f in fields(BaseContext) if f.name in state})
        controls = next((r for r in all_rooms if r.get('key') == 'control'), {})
        # Remove the outgoing control contribution, then apply the current
        # active control skills once (including a tired support operator).
        neutral = BaseContext(**{f.name: getattr(context, f.name) for f in fields(BaseContext)
                                 if f.name not in {'control_trade_speed', 'control_factory_speed',
                                     'control_gold_factory_speed', 'control_operator_ids', 'control_operator_names',
                                     'control_icons', 'control_group_counts', 'catnip', 'human_fire',
                                     'perception_information', 'enthusiasm', 'abyssal_factory_percent_per_hunter'}})
        control_team = [prepared[x] for x in controls.get('operators', []) if x in active and x in prepared]
        _, context = _control_effect(tuple(control_team), neutral)
        context.working_operator_ids = sorted(active)
        for key, kinds in [('trade_operator_ids', {'trade', 'orundum'}), ('factory_operator_ids', {'gold', 'exp', 'shard'})]:
            setattr(context, key, [x for r in all_rooms if r.get('key') in kinds for x in r.get('operators', []) if x in active])
        for attr, field in [('working_group_counts', 'group_id'), ('working_nation_counts', 'nation_id')]:
            counts = {}
            for x in active:
                value = prepared.get(x, {}).get(field)
                if value:
                    counts[value] = counts.get(value, 0) + 1
            setattr(context, attr, counts)
        # Control threshold producers use actual morale rather than the
        # scheduling model's midpoint estimate.
        for op in control_team:
            icons = op['icons']
            midpoint = 24 - .75 * context.shift_hours / 2
            low = morale[op['id']] <= 12
            if 'bskill_ctrl_cost_bd1' in icons:
                context.human_fire += 15 * (int(low) - int(midpoint < 12))
            if 'bskill_ctrl_cost_bd2' in icons:
                context.perception_information += 10 * (int(not low) - int(midpoint > 12))
            if 'bskill_ctrl_cost_bd1&bd2' in icons:
                context.human_fire += 15 * (int(not low) - int(midpoint > 12))
                context.perception_information += 10 * (int(low) - int(midpoint <= 12))
        evaluated = evaluate_team([prepared[x] for x in ids if x in active], room['key'], catalog, context)
        # Preserve physical assignment signatures for drone routing. The
        # number of active operators is a separate efficiency input.
        copy = {**room, **evaluated, 'operators': ids, 'active_operators': evaluated['operators']}
        cache[signature] = copy
        return copy

    while now < horizon - EPS:
        current = [_source(row, now + EPS, cycle) for row in schedules]
        current = [(room, max(0., elapsed - EPS)) for room, elapsed in current]
        rooms = [room for room, _ in current if room]
        working = {op for room in rooms for op in room.get('operators', [])}
        assignment = tuple((r['name'], tuple((room or {}).get('operators') or []), (room or {}).get('_team'))
                           for r, (room, _) in zip(schedules, current))
        active = {op for op in working if morale[op] > EPS}
        control = next((r for r in rooms if r.get('key') == 'control'), {})
        # Initial wrapped night is a continuation of the previous shift.
        if now == 0:
            for room, elapsed in current:
                if not room or elapsed < EPS:
                    continue
                for op, rate in morale_rates(room, control, active).items():
                    if op not in (initial or {}):
                        morale[op] = max(0., min(24., 24 - rate * elapsed / 60))
            active = {op for op in working if morale[op] > EPS}
        if now == 0 or round(now, 6) in nodes:
            if fiam.get('active') and previous is not None and assignment != previous:
                target = fiam.get('target_operator_id')
                if target in working and fiam_morale >= 24 - EPS:
                    morale[target], fiam_morale = fiam_morale, morale[target]
                    events.append({'minute': round(now, 6), 'type': 'morale_swap', 'operator': target})
            waiting = sorted((op for op in morale if op not in working and morale[op] < 24 - EPS),
                             key=lambda op: (morale[op], op))
            available = [i for i in range(20) if not (helper and i == 0) and not (fiam.get('enabled') and i == 5)]
            for i in available:
                beds[i] = waiting.pop(0) if waiting else None
            overflow_seen.update(waiting)
        previous = assignment
        active = {op for op in working if morale[op] > EPS}
        runtime_state = {"working_operator_ids": sorted(working),
                         "dormitory_morale": {op: morale[op] for op in beds if op in morale}}
        rates = {}
        # Rate changes depend on assignments, active skills, and whether a
        # resting hunter is full, rather than the exact floating-point mood.
        rate_state = (tuple(sorted(active)), tuple(sorted(working)),
                      tuple(sorted((op, value >= 24 - EPS) for op, value in runtime_state["dormitory_morale"].items()
                                   if op in ABYSSAL_HUNTER_IDS)))
        for room in rooms:
            rate_key = (id(room), id(control), rate_state)
            if rate_key not in rate_cache:
                rate_cache[rate_key] = morale_rates(
                    {**room, "base_state": {**(room.get("base_state") or {}), **runtime_state}}, control, active)
            rates.update(rate_cache[rate_key])
        recovery = {}
        for i, op in enumerate(beds):
            if op not in morale or op in working:
                continue
            own = own_recovery.get(op, 0.)
            recovery[op] = 4. + own + (float(helper.get('all', 0)) if i < 5 and i != 0 else 0)
        deltas = {op: (-rates.get(op, 0) if op in working else recovery.get(op, 0)) for op in morale}
        while pointer < len(boundaries) and boundaries[pointer] <= now + EPS:
            pointer += 1
        end = boundaries[pointer] if pointer < len(boundaries) else horizon
        for op, delta in deltas.items():
            value = morale[op]
            targets = [0, 12] if delta < 0 else [12, 24]
            for target in targets:
                dt = (target - value) / delta * 60 if abs(delta) > EPS else -1
                if dt > EPS:
                    end = min(end, now + dt)
        dt = end - now
        effective_rooms = []
        for dest, (room, elapsed) in zip(out, current):
            if not room:
                effective_rooms.append((None, elapsed))
                continue
            value = effective(room, active, rooms)
            effective_rooms.append((value, elapsed))
            # One span can cover adjacent morale checkpoints when no output
            # parameter changed; this keeps long Monte Carlo runs compact.
            spans = dest['spans']
            if spans and spans[-1][2].get('_variant') == id(value) and abs(spans[-1][1] - now) < EPS and abs(
                spans[-1][2]['_elapsed_offset_hours'] * 60 + now - spans[-1][0] - elapsed) < 1e-5:
                start, _, old = spans[-1]
                spans[-1] = (start, end, old)
            else:
                spans.append((now, end, {**value, '_variant': id(value), '_elapsed_offset_hours': elapsed / 60}))
        busy = on_interval(now, end, effective_rooms) if on_interval else {}
        for op, delta in deltas.items():
            old = morale[op]
            if op in working and old <= EPS:
                fatigue[op] += dt / 60
            morale[op] = max(0., min(24., old + delta * (busy.get(op, dt) if op in working else dt) / 60))
            min_morale[op] = min(min_morale[op], morale[op])
            if old > EPS and morale[op] <= EPS:
                events.append({'minute': round(end, 6), 'type': 'exhausted', 'operator': op,
                               'handover': False})
        fiam_morale = min(24., fiam_morale + dt / 60 * 2)
        now = end
    report = {'model': 'continuous_login_only', 'initial_morale': initial or 'full_except_overnight_continuation',
              'final_morale': {op: round(value, 6) for op, value in morale.items()},
              'warehouse_pauses_consumption': bool(on_interval),
              'minimum_morale': {op: round(value, 6) for op, value in min_morale.items()},
              'exhausted_work_hours': {op: round(value, 6) for op, value in fatigue.items() if value > EPS},
              'events': events[:2000], 'event_count': len(events), 'dorm_overflow_operators': sorted(overflow_seen),
              'fiammetta_recovery_per_hour': 2., 'beds_reassigned_only_at_login': True}
    return out, report
