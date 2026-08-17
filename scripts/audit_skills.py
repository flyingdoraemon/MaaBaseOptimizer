#!/usr/bin/env python3
"""Audit operator -> unlocked buff -> MAA mapping -> local formula coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maabase.mechanics import mechanic_is_partial
from maabase.model import prepare_operators
from maabase.state_model import mechanism_coverage


ROOM_MAP = {"MANUFACTURE": "Mfg", "TRADING": "Trade", "POWER": "Power", "CONTROL": "Control"}


def audit(catalog: dict) -> dict:
    term_path = ROOT / "data" / "riic_terms.json"
    terms = json.loads(term_path.read_text(encoding="utf-8"))["terms"]
    unknown_term_members = [
        {"term": term, "operator_id": operator_id}
        for term, members in terms.items() for operator_id in members
        if operator_id not in catalog["operators"]
    ]
    broken_slot_references: list[dict] = []
    for operator_id, operator in catalog["operators"].items():
        for slot in operator.get("slots", []):
            for unlock in slot:
                if unlock["buff"] not in catalog["buffs"]:
                    broken_slot_references.append({
                        "operator": operator["name"], "operator_id": operator_id, "buff": unlock["buff"],
                    })

    unsafe_missing_maa: list[dict] = []
    simple_game_data_fallback: list[dict] = []
    for buff in catalog["buffs"].values():
        room = ROOM_MAP.get(buff.get("room"))
        icon = buff.get("icon")
        if not room or not icon or icon in catalog["maa"][room]["skills"]:
            continue
        item = {"buff": buff["id"], "name": buff["name"], "icon": icon, "room": room}
        if buff.get("category") == "OUTPUT" and not mechanic_is_partial(buff):
            simple_game_data_fallback.append(item)
        else:
            unsafe_missing_maa.append(item)

    icon_descriptions: dict[tuple[str, str], set[str]] = defaultdict(set)
    icon_buffs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for buff in catalog["buffs"].values():
        room = ROOM_MAP.get(buff.get("room"))
        icon = buff.get("icon")
        if not room or not icon:
            continue
        key = (room, icon)
        icon_descriptions[key].add(buff.get("description", ""))
        icon_buffs[key].append(buff["id"])
    shared_icon_semantics = [
        {"room": room, "icon": icon, "buffs": sorted(icon_buffs[(room, icon)]),
         "description_variants": len(descriptions)}
        for (room, icon), descriptions in icon_descriptions.items() if len(descriptions) > 1
    ]

    roster = [{"id": operator_id, "elite": 2, "level": 90} for operator_id in catalog["operators"]]
    coverage = mechanism_coverage(prepare_operators(roster, catalog))
    return {
        "operators": len(catalog["operators"]),
        "buffs": len(catalog["buffs"]),
        "broken_slot_references": broken_slot_references,
        "unknown_term_members": unknown_term_members,
        "unsafe_missing_maa": unsafe_missing_maa,
        "simple_game_data_fallback": simple_game_data_fallback,
        "shared_icon_semantics": shared_icon_semantics,
        "mechanism_coverage": coverage,
        "safe": not broken_slot_references and not unknown_term_members and not unsafe_missing_maa,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="审计全干员后勤技能数据与公式覆盖")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.json")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = audit(json.loads(args.catalog.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    if not result["safe"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
