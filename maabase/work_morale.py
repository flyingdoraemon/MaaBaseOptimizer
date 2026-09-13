"""Morale rates shared by scheduling and continuous replay (points/hour).

Positive means consumption; negative means recovery while still on duty.
The control room is a real staffed room, never an assumed constant -0.25.
"""
from __future__ import annotations
import re
from .state_model import ABYSSAL_HUNTER_IDS, SUI_IDS

PRODUCTION = {"trade", "orundum", "gold", "exp", "shard"}


def morale_rates(room: dict, control: dict | None = None, active_ids: set | None = None) -> dict[str, float]:
    ids = room.get("operators") or []
    active = set(ids) if active_ids is None else set(ids) & active_ids
    control = control if control is not None else room.get("control_room") or {}
    controls = set(control.get("operators") or [])
    if active_ids is not None:
        controls &= active_ids
    if room.get("key") == "control":
        base = 1 - .05 * len(active)
    else:
        base = 1 - .05 * len(controls)
        if room.get("key") in PRODUCTION:
            base -= .05 * max(0, len(active) - 1)
    rates = dict.fromkeys(ids, base)
    details = room.get("details") or []
    names = {str(d.get("operator")) for i, d in enumerate(details) if i < len(ids) and ids[i] in active}
    profiles = room.get("operator_profiles") or []
    state = room.get("base_state") or {}
    enabled_icons = {skill.get("icon") for i, detail in enumerate(details)
                     if i < len(ids) and ids[i] in active for skill in detail.get("skills", [])}
    for index, detail in enumerate(details):
        if index >= len(ids) or ids[index] not in active:
            continue
        owner = ids[index]
        for skill in detail.get("skills", []):
            text = re.sub(r"<[^>]+>", "", skill.get("description") or "")
            icon = skill.get("icon", "")
            # Explicit partner conditions gate the morale clause, too.
            peer = re.search(r"当与(.+?)(?:在同一个|一起进驻|进驻控制中枢一起工作)", text)
            if peer and peer[1] not in names:
                if peer[1] != "萨尔贡干员" or not any(p.get("nation_id") == "sargon" and p.get("id") in active for p in profiles):
                    continue
            if "生产作战记录类配方时" in text and room.get("key") != "exp":
                continue
            if icon == "bskill_ctrl_cost_aegir":
                hunters_working = len((set(state.get("working_operator_ids") or []) | set(ids)) & ABYSSAL_HUNTER_IDS)
                dormant = state.get("dormitory_morale") or {}
                hunters_resting = [v for op, v in dormant.items() if op in ABYSSAL_HUNTER_IDS]
                rates[owner] += .5 * (hunters_working - len(hunters_resting) - sum(v >= 24 - 1e-7 for v in hunters_resting))
                continue
            if "所有宿舍" in text or "其他设施" in text or "部分设施" in text:
                continue  # Applied to the receiving facility below.
            if "每个" in text and "恢复" in text:
                factions = {"bskill_ctrl_lungmen": ("group_id", "lgd"),
                            "bskill_ctrl_ussg": ("team_id", "student"),
                            "bskill_ctrl_karlan": ("nation_id", "kjerag"),
                            "bskill_ctrl_r6": ("team_id", "rainbow"),
                            "bskill_ctrl_lda_add": ("group_id", "lee")}
                if icon in factions:
                    field, group = factions[icon]
                    factor = sum(p.get(field) == group and p.get("id") in active for p in profiles)
                elif icon == "bskill_ctrl_sp":
                    factor = sum(bool(p.get("is_alter")) and p.get("id") in active for p in profiles)
                else:
                    factor = 1
            else:
                factor = 1
            if icon == "bskill_man_gold&blacksteel":
                factor = min(3, (state.get("working_group_counts") or {}).get("blacksteel", 0))
            if icon == "bskill_ctrl_trade_mortis":
                factor = int(state.get("enthusiasm", 0)) // 8
            if icon == "bskill_ctrl_mp_oblvns" and state.get("enthusiasm", 0) < 40:
                continue
            targets = list(ids) if re.search(r"(?:内.*?(?:所有|其余|内干员)|全体)心情|内(?:所有)?干员(?:的)?心情", text) else [owner]
            if "自身和阿米娅" in text:
                targets = [owner] + [ids[i] for i, d in enumerate(details) if d.get("operator") == "阿米娅"]
            if "除自身" in text:
                targets = [value for value in ids if value != owner]
            if "丰川祥子心情" in text or "丰川祥子的心情" in text:
                targets = [ids[i] for i, d in enumerate(details) if d.get("operator") == "丰川祥子"]
            for action, sign, number in re.findall(r"心情每小时(消耗|恢复)([+-])([0-9.]+)", text):
                delta = float(number) * (1 if sign == "+" else -1) * (1 if action == "消耗" else -1) * factor
                for target in targets:
                    if targets == [owner] and owner in SUI_IDS and "bskill_ctrl_clear_sui" in enabled_icons:
                        continue
                    rates[target] += delta
    # Global recovery is compared with, rather than blindly added to, the
    # normal control reduction. Mlynar's distinct effect stacks with it.
    if room.get("key") != "control":
        alternative = 0.0
        extra = 0.0
        control_details = control.get("details") or []
        for i, detail in enumerate(control_details):
            if i >= len(control.get("operators", [])) or control["operators"][i] not in controls:
                continue
            for skill in detail.get("skills", []):
                icon = skill.get("icon")
                if icon == "bskill_ctrl_cost_bd4":
                    alternative = max(alternative, .05 * (1 + int(state.get("human_fire", 0)) // 20))
                elif icon == "bskill_ctrl_cost_expand":
                    alternative = max(alternative, .1 + .1 * ("魔王" in control.get("names", [])))
                elif icon == "bskill_ctrl_lonely":
                    extra = max(extra, (.1 if room.get("key") in {"power", "office", "reception"} else 0) + .05 * sum(s.get("icon") == "bskill_ctrl_cost" for d in control_details for s in d.get("skills", [])))
        reduction = max(0, alternative - .05 * len(controls)) + extra
        for operator in rates:
            rates[operator] -= reduction
    return {operator: round(value, 6) for operator, value in rates.items()}
