import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Dict, List, Optional, Tuple


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


MONTH_ABBR = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}


def fmt_ts_local(dt: datetime) -> str:
    # DD-MON-YYYY HH24:MI:SS with uppercase month
    return f"{dt.day:02d}-{MONTH_ABBR[dt.month]}-{dt.year:04d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def daterange(start: date, days: int) -> List[date]:
    return [start + timedelta(days=i) for i in range(days)]


def dow_key(d: date) -> str:
    # mon..sun
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][d.weekday()]


def time_iter(d: date, start_hhmm: str, end_hhmm: str, bucket_minutes: int) -> List[datetime]:
    sh, sm = map(int, start_hhmm.split(":"))
    eh, em = map(int, end_hhmm.split(":"))
    cur = datetime(d.year, d.month, d.day, sh, sm, 0)
    end = datetime(d.year, d.month, d.day, eh, em, 0)
    out: List[datetime] = []
    while cur < end:
        out.append(cur)
        cur += timedelta(minutes=bucket_minutes)
    return out


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def weekday_profile(idx: int, start_h: int, end_h: int, peak_h: int, base: float, peak: float) -> float:
    """
    Smooth-ish profile over the day bucket index, returning demand between base and peak.
    idx corresponds to time bucket position from 00:00.
    """
    # Map idx to hour (0..23.5)
    hour = idx / 2.0
    if hour < start_h or hour >= end_h:
        return 0.0
    # Triangular peak at peak_h
    if hour <= peak_h:
        w = (hour - start_h) / max(1e-9, (peak_h - start_h))
    else:
        w = (end_h - hour) / max(1e-9, (end_h - peak_h))
    w = clamp(w, 0.0, 1.0)
    return base + (peak - base) * w


@dataclass(frozen=True)
class SkillGroup:
    id: str
    name: str
    direction: str
    channel: str


def build_templates() -> List[dict]:
    """
    Simple v1 template set:
    - 8h: starts 09:00..13:00 hourly (to cover inbound and late outbound overlap)
    - 4h: starts 09:00..17:00 hourly (to cover evening outbound)
    """
    templates: List[dict] = []
    # 8h
    for hh in range(9, 14):  # 09..13
        start = f"{hh:02d}:00"
        templates.append(
            {
                "id": f"S_{start.replace(':', '')}_8H",
                "name": f"{start} 8h",
                "start_time_local": start,
                "duration_minutes": 480,
            }
        )
    # 4h
    for hh in range(9, 18):  # 09..17
        start = f"{hh:02d}:00"
        templates.append(
            {
                "id": f"S_{start.replace(':', '')}_4H",
                "name": f"{start} 4h",
                "start_time_local": start,
                "duration_minutes": 240,
            }
        )
    return templates


def build_operating_hours() -> List[dict]:
    return [
        # Mon-Fri inbound operations 09:00-18:00 (voice/chat/email)
        {
            "name": "MonFri_inbound_voice",
            "direction": "inbound",
            "channel": "voice",
            "start_time_local": "09:00",
            "end_time_local": "18:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
        },
        {
            "name": "MonFri_inbound_chat",
            "direction": "inbound",
            "channel": "chat",
            "start_time_local": "09:00",
            "end_time_local": "18:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
        },
        {
            "name": "MonFri_inbound_email",
            "direction": "inbound",
            "channel": "email",
            "start_time_local": "09:00",
            "end_time_local": "18:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
        },
        # Mon-Fri outbound operations 16:00-21:00 (voice)
        {
            "name": "MonFri_outbound_voice",
            "direction": "outbound",
            "channel": "voice",
            "start_time_local": "16:00",
            "end_time_local": "21:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
        },
        # Sat inbound operations 10:00-18:00 (voice/chat/email)
        {
            "name": "Sat_inbound_voice",
            "direction": "inbound",
            "channel": "voice",
            "start_time_local": "10:00",
            "end_time_local": "18:00",
            "applies_to_days": ["sat"],
        },
        {
            "name": "Sat_inbound_chat",
            "direction": "inbound",
            "channel": "chat",
            "start_time_local": "10:00",
            "end_time_local": "18:00",
            "applies_to_days": ["sat"],
        },
        {
            "name": "Sat_inbound_email",
            "direction": "inbound",
            "channel": "email",
            "start_time_local": "10:00",
            "end_time_local": "18:00",
            "applies_to_days": ["sat"],
        },
    ]


def build_priority_rules() -> List[dict]:
    # User-provided concept: priorities can change; encode current example as windows.
    # 09:00-12:00 outbound voice > inbound voice
    # 12:00-18:00 inbound voice > outbound voice > inbound chat > inbound email
    # Apply Mon-Fri.
    return [
        {
            "name": "MonFri_0900_1200",
            "start_time_local": "09:00",
            "end_time_local": "12:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
            "priorities": [
                {"direction": "outbound", "channel": "voice", "rank": 1, "understaff_weight": 100.0},
                {"direction": "inbound", "channel": "voice", "rank": 2, "understaff_weight": 10.0},
            ],
        },
        {
            "name": "MonFri_1200_1800",
            "start_time_local": "12:00",
            "end_time_local": "18:00",
            "applies_to_days": ["mon", "tue", "wed", "thu", "fri"],
            "priorities": [
                {"direction": "inbound", "channel": "voice", "rank": 1, "understaff_weight": 100.0},
                {"direction": "outbound", "channel": "voice", "rank": 2, "understaff_weight": 25.0},
                {"direction": "inbound", "channel": "chat", "rank": 3, "understaff_weight": 10.0},
                {"direction": "inbound", "channel": "email", "rank": 4, "understaff_weight": 3.0},
            ],
        },
    ]


def build_skill_groups() -> List[SkillGroup]:
    # Based on user description (4 skill groups)
    return [
        SkillGroup(id="recover_v", name="recover-v", direction="outbound", channel="voice"),
        SkillGroup(id="billing_v", name="billing-v", direction="inbound", channel="voice"),
        SkillGroup(id="billing_c", name="billing-c", direction="inbound", channel="chat"),
        SkillGroup(id="billing_e", name="billing-e", direction="inbound", channel="email"),
    ]


def build_agents() -> List[dict]:
    # 15 fictional agents with a simple mapping to primary skill groups
    # Distribution: 4 voice inbound, 4 voice outbound, 4 chat, 3 email (total 15)
    # Employment groups: 10 full-time, 5 part-time (fictional mix)
    # Define multi-skill sets (fictional):
    # - Voice agents can also pick up chat/email
    # - Some outbound agents can also handle inbound voice
    # - A few "billing omni" can do voice+chat+email
    employees: List[Tuple[str, list[str]]] = [
        ("A01", ["billing_v", "billing_c"]),
        ("A02", ["billing_v", "billing_e"]),
        ("A03", ["billing_v"]),
        ("A04", ["billing_v", "recover_v"]),  # outbound-capable
        ("A05", ["recover_v", "billing_v"]),  # inbound-capable
        ("A06", ["recover_v"]),
        ("A07", ["recover_v", "billing_v"]),  # inbound-capable
        ("A08", ["recover_v"]),
        ("A09", ["billing_c", "billing_v"]),  # cross-skill
        ("A10", ["billing_c"]),
        ("A11", ["billing_c", "billing_e"]),
        ("A12", ["billing_c"]),
        ("A13", ["billing_e", "billing_v"]),  # cross-skill
        ("A14", ["billing_e"]),
        ("A15", ["billing_e", "billing_c"]),
    ]
    out = []
    full_time_ids = {"A01", "A02", "A03", "A04", "A05", "A06", "A09", "A10", "A13", "A14"}
    for emp_id, sg_ids in employees:
        out.append(
            {
                "id": emp_id,
                "name": f"Agent {emp_id}",
                "skill_group_ids": sg_ids,
                "employment_group_id": "full_time" if emp_id in full_time_ids else "part_time",
            }
        )
    return out


def build_agent_groups(skill_groups: List[SkillGroup], employees: List[dict]) -> List[dict]:
    # v1: agent_groups correspond 1:1 with skill groups
    groups: List[dict] = []
    for sg in skill_groups:
        groups.append(
            {
                "id": f"ag_{sg.id}",
                "name": sg.name,
            }
        )
    return groups


def build_skills(agent_groups: List[dict]) -> List[dict]:
    # v1: binary mapping of agent_group -> channel
    # recover-v and billing-v handle voice; billing-c handle chat; billing-e handle email
    out: List[dict] = []
    for ag in agent_groups:
        if ag["name"].endswith("-v"):
            out.append({"agent_group_id": ag["id"], "channel_id": "voice", "can_handle": True})
        elif ag["name"].endswith("-c"):
            out.append({"agent_group_id": ag["id"], "channel_id": "chat", "can_handle": True})
        elif ag["name"].endswith("-e"):
            out.append({"agent_group_id": ag["id"], "channel_id": "email", "can_handle": True})
    return out


def make_forecast_rows(
    start_date: date,
    days: int,
    bucket_minutes: int,
    skill_groups: List[SkillGroup],
    max_total_agents: int,
    variability: float,
) -> List[dict]:
    """
    Build forecast so that per-interval total demand across all streams <= max_total_agents.
    variability controls how spiky demand is (0..1).
    """
    sg_by_id = {sg.id: sg for sg in skill_groups}

    # Predefine base profiles per stream on Mon-Fri and Sat.
    # Inbound: 09-18 Mon-Fri, 10-18 Sat. Outbound: 16-21 Mon-Fri.
    # We'll allocate a "total demand" profile then split into streams.
    rows: List[dict] = []

    for d in daterange(start_date, days):
        dow = dow_key(d)
        is_monfri = dow in {"mon", "tue", "wed", "thu", "fri"}
        is_sat = dow == "sat"

        # Build bucket-level total demand profile for open hours
        # Use indices 0..47 (30-min buckets).
        for b in range(48):
            hour = b / 2.0

            total = 0.0
            inbound_total = 0.0
            outbound_total = 0.0

            if is_monfri:
                inbound_total = weekday_profile(b, start_h=9, end_h=18, peak_h=13, base=6.0, peak=12.0)
                outbound_total = weekday_profile(b, start_h=16, end_h=21, peak_h=19, base=2.0, peak=6.0)
            elif is_sat:
                inbound_total = weekday_profile(b, start_h=10, end_h=18, peak_h=13, base=5.0, peak=10.0)
                outbound_total = 0.0
            else:
                inbound_total = 0.0
                outbound_total = 0.0

            total = inbound_total + outbound_total
            if total <= 0:
                continue

            # Add some deterministic variability per date/bucket
            wobble = 1.0 + variability * 0.15 * math.sin((d.toordinal() % 17) + b / 3.0)
            total *= wobble
            total = clamp(total, 0.0, float(max_total_agents))

            # Split totals across streams with fixed shares (can be tuned)
            # Inbound split across voice/chat/email; outbound is voice.
            inbound_voice = inbound_total * 0.55
            inbound_chat = inbound_total * 0.30
            inbound_email = inbound_total * 0.15
            outbound_voice = outbound_total * 1.0

            # Apply wobble proportionally
            if inbound_total > 0:
                scale_in = (total - (outbound_total * wobble)) / max(1e-9, inbound_total * wobble)
                inbound_voice *= scale_in
                inbound_chat *= scale_in
                inbound_email *= scale_in
            outbound_voice *= wobble

            # Renormalize to max_total_agents per interval
            interval_sum = inbound_voice + inbound_chat + inbound_email + outbound_voice
            if interval_sum > max_total_agents:
                k = max_total_agents / interval_sum
                inbound_voice *= k
                inbound_chat *= k
                inbound_email *= k
                outbound_voice *= k

            # Round to 1 decimal to keep files compact
            inbound_voice = int(round(inbound_voice))
            inbound_chat = int(round(inbound_chat))
            inbound_email = int(round(inbound_email))
            outbound_voice = int(round(outbound_voice))

            dt = datetime(d.year, d.month, d.day, int(hour), 0 if b % 2 == 0 else 30, 0)

            def add(sg_id: str, agents: float) -> None:
                if agents <= 0:
                    return
                sg = sg_by_id[sg_id]
                rows.append(
                    {
                        "skill_group_id": sg.id,
                        "timestamp_local": fmt_ts_local(dt),
                        "direction": sg.direction,
                        "channel": sg.channel,
                        "agents": int(agents),
                    }
                )

            add("billing_v", inbound_voice)
            add("billing_c", inbound_chat)
            add("billing_e", inbound_email)
            add("recover_v", outbound_voice)

    return rows


def build_base_input(start_date: date, timezone: str, schedule_name: str, variability: float) -> dict:
    skill_groups = build_skill_groups()
    employees = build_agents()
    agent_groups = build_agent_groups(skill_groups, employees)

    obj = {
        "run": {
            "schedule_id": "demo_schedule",
            "schedule_name": schedule_name,
            "description": "Fictional contact center sample input",
        },
        "meta": {"version": "v1", "created_at": datetime.now(UTC).replace(microsecond=0).isoformat()},
        "time": {
            "start_date": start_date.isoformat(),
            "timezone": timezone,
            "days": 28,
            "bucket_minutes": 30,
        },
        "channels": [
            {"id": "voice", "name": "Voice"},
            {"id": "chat", "name": "Chat"},
            {"id": "email", "name": "Email"},
        ],
        "skill_groups": [{"id": sg.id, "name": sg.name} for sg in skill_groups],
        "employment_groups": [
            {
                "id": "part_time",
                "name": "Part Time",
                "hours_per_week": {"min": 20, "max": 30},
                "hours_per_day": {"min": 4, "max": 8},
            },
            {
                "id": "full_time",
                "name": "Full Time",
                "hours_per_week": {"min": 40, "max": 40},
                "hours_per_day": {"min": 6, "max": 8},
            },
        ],
        "forecast": make_forecast_rows(
            start_date=start_date,
            days=28,
            bucket_minutes=30,
            skill_groups=skill_groups,
            max_total_agents=15,
            variability=variability,
        ),
        "operating_hours": build_operating_hours(),
        "priority_rules": build_priority_rules(),
        "employees": employees,
        "agent_groups": agent_groups,
        "skills": build_skills(agent_groups),
        "shift_templates": build_templates(),
        "solver": {"name": "cbc", "time_limit_seconds": 60, "mip_gap": 0.01},
    }
    return obj


def main() -> None:
    ensure_dir("input")

    # Choose a Monday start date for clarity
    start = date(2026, 1, 5)  # Monday

    small = build_base_input(start_date=start, timezone="America/New_York", schedule_name="Sample Small", variability=0.2)
    stress = build_base_input(
        start_date=start, timezone="America/New_York", schedule_name="Sample Stress", variability=0.8
    )

    # Stress: add more shift start time density (every 30 min) to increase decision space, still 4h/8h.
    extra_templates = []
    for hh in range(9, 18):  # 09..17
        for mm in (0, 30):
            start_time = f"{hh:02d}:{mm:02d}"
            # 4h always
            extra_templates.append(
                {
                    "id": f"S_{start_time.replace(':', '')}_4H",
                    "name": f"{start_time} 4h",
                    "start_time_local": start_time,
                    "duration_minutes": 240,
                }
            )
            # 8h only if it ends by ~21:30 to keep plausible
            if (hh < 14) or (hh == 13 and mm == 30):
                extra_templates.append(
                    {
                        "id": f"S_{start_time.replace(':', '')}_8H",
                        "name": f"{start_time} 8h",
                        "start_time_local": start_time,
                        "duration_minutes": 480,
                    }
                )
    # Deduplicate by id
    seen = set()
    dedup = []
    for t in extra_templates:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        dedup.append(t)
    stress["shift_templates"] = dedup
    stress["solver"]["time_limit_seconds"] = 120

    with open("input/sample_input.small.json", "w", encoding="utf-8") as f:
        json.dump(small, f, indent=2)
        f.write("\n")

    with open("input/sample_input.stress.json", "w", encoding="utf-8") as f:
        json.dump(stress, f, indent=2)
        f.write("\n")

    print("Wrote input/sample_input.small.json")
    print("Wrote input/sample_input.stress.json")


if __name__ == "__main__":
    main()

