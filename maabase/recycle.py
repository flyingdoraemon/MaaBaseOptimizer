"""Recycler conversion throughput, separate from randomized material value.

Constants are copied from the pinned client building_data table. The optional
boost represents a continuously supplied level-3 room, not free acceleration.
"""
from math import isfinite


def settings(payload, catalog):
    raw = payload.get('recycle_level', 3 if catalog.get('recycle', {}).get('data') else 0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError('回收站等级须为 0、1、2 或 3') from None
    if not isfinite(value) or value not in (0, 1, 2, 3):
        raise ValueError('回收站等级须为 0、1、2 或 3')
    level = int(value)
    if not level:
        return None
    data = catalog['recycle']
    constants = data['constants']
    phase = data['data']['phases'][level - 1]
    boost = bool(payload.get('recycle_boost', False))
    if boost and level < constants['recycleSpeedUpUnlockLevel']:
        raise ValueError('回收站达到 3 级后才能投料加速')
    return {'level': level,
            'slots': data['room']['phases'][level - 1]['maxStationedNum'],
            'capacity': constants['recycleBaseCapacity'] + phase['recycleCapacity'],
            'base_minutes': constants['recycleTimeRequirement'] / 60,
            'base_multiplier': phase['recycleSpeed'],
            'staff_bonus': data['data']['basicSpeedBuff'],
            'boost_multiplier': constants['recycleBoostSpeed'] if boost else 0,
            'continuous_boost': boost}


def evaluate_recycle(team, config):
    team = list(team)
    efficiency = sum(float(s.get('efficiency') or 0) for op in team
                     for s in op['skills'] if s.get('room') == 'RECYCLE')
    multiplier = config['base_multiplier'] + config['boost_multiplier'] + len(team) * config['staff_bonus'] + efficiency / 100
    return {
        'key': 'recycle', 'product': 'recycle', 'room': '回收站', 'recycle': dict(config),
        'operators': [op['id'] for op in team], 'names': [op['name'] for op in team],
        'operator_profiles': [{**{k: op.get(k) for k in ('id', 'name', 'nation_id', 'group_id', 'team_id')},
                               'elite': int(op.get('elite', op.get('phase', 0))), 'level': int(op.get('level', 1))} for op in team],
        'efficiency': efficiency, 'equivalent_efficiency': efficiency,
        'multiplier': multiplier, 'output_capacity': config['capacity'],
        'recycle_cycles_per_day': 1440 / config['base_minutes'] * multiplier,
        'confidence': 'direct', 'group': None, 'unresolved': [], 'time_profiles': [], 'context_effects': [],
        'mechanic_notes': [f"{config['level']} 级 · {config['slots']} 个进驻位 · {config['capacity']} 格储存",
                           f"每次转化基础 {config['base_minutes'] / 60:g} 小时，跨换班保留进度",
                           '持续投料 +50%' if config['continuous_boost'] else '自然转化，无需投料'],
        'details': [{'operator': op['name'],
                    'skills': [{**s, 'value': s.get('efficiency', 0)} for s in op['skills'] if s.get('room') == 'RECYCLE']}
                   for op in team],
    }
