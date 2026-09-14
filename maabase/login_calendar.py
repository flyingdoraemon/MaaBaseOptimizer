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
    period = float(rotation.get("natural_cycle_hours") or rotation["cycle_hours"])
    horizon = float(rotation["cycle_hours"])
    rotation["login_calendar"]["login_hours"] = login_hours(interval, horizon)
    # Phase-shift the full common period to 06:00. Never wrap a 36-hour
    # assignment at midnight or repeat an incomplete display window.
    for row in rotation["rooms"]:
        source = [event for event in row["events"] if event["start"] < period]
        events = []
        for repeat in range(-1, math.ceil(horizon / period) + 1):
            for event in source:
                start = event["start"] + 6 + repeat * period
                end = min(event["end"], period) + 6 + repeat * period
                left, right = max(0., start), min(horizon, end)
                if right <= left:
                    continue
                extra = left - start
                phases = [{**profile, "phases": [
                    {**phase, "start": max(left, phase["start"] + 6 + repeat * period),
                     "end": min(right, phase["end"] + 6 + repeat * period)}
                    for phase in profile.get("phases", [])
                    if min(right, phase["end"] + 6 + repeat * period) > max(left, phase["start"] + 6 + repeat * period)
                ]} for profile in event.get("time_profiles", [])]
                events.append({**event, "start": left, "end": right,
                               "elapsed_offset_hours": extra, "time_profiles": phases,
                               "scheduled_work_hours": event.get("scheduled_work_hours", end - start),
                               "continuation": extra > 0})
        row["events"] = sorted(events, key=lambda event: event["start"])
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
