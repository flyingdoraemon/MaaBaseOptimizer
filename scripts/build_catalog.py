#!/usr/bin/env python3
"""Build a compact RIIC catalog from game data and MAA's numeric skill model."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return TAG_RE.sub("", text or "").replace("\\n", " ").strip()


def build(building_path: Path, character_path: Path, maa_path: Path) -> dict:
    building = json.loads(building_path.read_text(encoding="utf-8"))
    characters = json.loads(character_path.read_text(encoding="utf-8"))
    maa = json.loads(maa_path.read_text(encoding="utf-8"))

    buffs = {}
    for buff_id, raw in building["buffs"].items():
        buffs[buff_id] = {
            "id": buff_id,
            "name": raw.get("buffName", buff_id),
            "icon": raw.get("skillIcon", ""),
            "room": raw.get("roomType", ""),
            "description": clean(raw.get("description", "")),
            "efficiency": raw.get("efficiency", 0),
            "targets": raw.get("targets", []),
            "category": raw.get("buffCategory", ""),
        }

    operators = {}
    for char_id, raw in building.get("chars", {}).items():
        char = characters.get(char_id)
        if not char or not char.get("name"):
            continue
        slots = []
        for slot in raw.get("buffChar", []):
            levels = []
            for item in slot.get("buffData", []):
                buff_id = item.get("buffId")
                if buff_id not in buffs:
                    continue
                cond = item.get("cond", {})
                levels.append({
                    "phase": int(cond.get("phase", 0)),
                    "level": int(cond.get("level", 1)),
                    "buff": buff_id,
                })
            if levels:
                levels.sort(key=lambda x: (x["phase"], x["level"]))
                slots.append(levels)
        if slots:
            operators[char_id] = {
                "id": char_id,
                "name": char["name"],
                "rarity": int(char.get("rarity", 0)) + 1,
                "slots": slots,
            }

    maa_model = {}
    for room in ("Mfg", "Trade", "Power", "Control"):
        source = maa.get(room, {})
        skills = {}
        for icon, skill in source.get("skills", {}).items():
            skills[icon] = {
                "name": skill.get("name", [icon])[0],
                "description": (skill.get("desc") or [""])[0],
                "efficient": skill.get("efficient", {}),
                "max_num": skill.get("maxNum"),
            }
        groups = []
        for group in source.get("skillsGroup", []):
            groups.append({
                "description": group.get("desc", ""),
                "allow_external": bool(group.get("allowExternal", False)),
                "conditions": group.get("conditions", {}),
                "necessary": [compact_comb(x) for x in group.get("necessary", [])],
                "optional": [compact_comb(x) for x in group.get("optional", [])],
            })
        maa_model[room] = {"skills": skills, "groups": groups}

    return {
        "schema": 1,
        "sources": {
            "building_data": "yuanyan3060/ArknightsGameResource",
            "maa_model": "MaaAssistantArknights/resource/infrast.json",
            "notes": "PRTS is used to validate formulas and unsupported mechanics.",
        },
        "constants": {
            "gold_base_per_day": 20.0,
            "exp_base_per_day": 8000.0,
            "trade_lmd_base_per_day": 10265.486725663717,
            "trade_gold_base_per_day": 20.530973451327434,
            "drone_minutes": 3.0,
            "drone_recover_minutes": 6.0,
        },
        "operators": operators,
        "buffs": buffs,
        "maa": maa_model,
    }


def compact_comb(raw: dict) -> dict:
    return {
        "description": raw.get("desc", ""),
        "skills": raw.get("skills", []),
        "efficient": raw.get("efficient", {}),
        "filter": raw.get("filter", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--maa-infrast", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.building, args.characters, args.maa_infrast)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.output}: {len(result['operators'])} operators, {len(result['buffs'])} buffs")


if __name__ == "__main__":
    main()

