"""Shared clock-time login calendar. No handovers or collections while asleep."""
from __future__ import annotations

import math


def login_hours(interval: float, horizon: float, *, quiet: bool = True) -> list[float]:
    if not quiet or interval >= 8:
        return [round(i * interval, 9) for i in range(1, math.floor(horizon / interval + 1e-9) + 1)]
    return [round(day * 24 + 6 + i * interval, 9)
            for day in range(math.floor(horizon / 24) + 1)
            for i in range(math.ceil(18 / interval))
            if day * 24 + 6 + i * interval <= horizon + 1e-9]


def apply_night_calendar(rotation: dict) -> dict:
    interval = rotation["collection_interval_hours"]
    quiet = interval < 8 and rotation.get("schedule_mode") != "fixed"
    rotation["login_calendar"] = {"quiet_hours": [0, 6] if quiet else None,
                                  "login_hours": login_hours(interval, 24, quiet=quiet),
                                  "clock_origin_hour": 0, "handover_policy": "login_only"}
    if not quiet:
        return rotation
    # Builders use a daily A/B cycle starting at zero. Shift its origin to
    # 06:00 and split only the display interval crossing midnight. The offset
    # explicitly preserves the incoming night's elapsed work and warm-up.
    rotation["cycle_hours"] = rotation["natural_cycle_hours"] = 24.0
    for row in rotation["rooms"]:
        events = []
        for event in row["events"]:
            start, end = event["start"] + 6, event["end"] + 6
            for left, right, offset in ((start, min(end, 24), 0), (max(start, 24), end, 24)):
                if right <= left:
                    continue
                extra = left - start
                phases = [{**profile, "phases": [
                    {**phase, "start": max(left, phase["start"] + 6) - offset,
                     "end": min(right, phase["end"] + 6) - offset}
                    for phase in profile.get("phases", [])
                    if min(right, phase["end"] + 6) > max(left, phase["start"] + 6)
                ]} for profile in event.get("time_profiles", [])]
                events.append({**event, "start": left - offset, "end": right - offset,
                               "elapsed_offset_hours": extra, "time_profiles": phases,
                               "continuation": extra > 0})
        row["events"] = sorted(events, key=lambda e: e["start"])
    changes = {}
    for row in rotation["rooms"]:
        for event in row["events"]:
            if event["start"] > 0:
                changes.setdefault(event["start"], []).append({"room": row["room"], "team": event["team"], "names": event["names"]})
    rotation["handover_events"] = [{"time": t, "changes": c} for t, c in sorted(changes.items())]
    rotation["shifts"] = []  # Room events are the authoritative clock timeline.
    rotation["duration_reason"] += "；时间轴使用实际钟点，00:00–06:00 不上线，06:00 允许换班。"
    rotation["morale"]["note"] += " 夜间不换班；心情耗尽后保留岗位到下次上线，技能失效计入模拟。"
    return rotation
