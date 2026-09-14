"""Public roster cards, using unlocked skills and single-operator room formulas."""
from .model import prepare_operators, evaluate_team
from .state_model import BaseContext


def operator_cards(catalog):
    result = []
    for oid, op in catalog["operators"].items():
        stages = sorted({(0, 1), *((level["phase"], level["level"]) for slot in op["slots"] for level in slot)})
        previews = []
        for elite, level in stages:
            prepared = prepare_operators([{"id": oid, "elite": elite, "level": level}], catalog)
            skills = prepared[0]["skills"]
            previews.append({"elite": elite, "level": level, "skills": skills,
                "efficiency": {key: round(evaluate_team(prepared, key, catalog, BaseContext())['efficiency'], 2)
                               for key in ('gold', 'exp', 'shard', 'trade', 'orundum', 'power')}})
        result.append({**{key: op.get(key) for key in ('id','name','rarity','profession','branch','branch_name')},
                       "previews": previews})
    return sorted(result, key=lambda item: (-item['rarity'], item['name']))
