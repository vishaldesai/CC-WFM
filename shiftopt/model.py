from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Tuple

import pulp

from .time_index import TimeIndex, parse_forecast_timestamp


Stream = Tuple[str, str]  # (direction, channel)


def _hhmm_to_bucket(start_hhmm: str, bucket_minutes: int) -> int:
    hh, mm = map(int, start_hhmm.split(":"))
    return (hh * 60 + mm) // bucket_minutes


def _template_covers_bucket(
    t: Dict[str, Any], bucket_minutes: int, buckets_per_day: int
) -> List[Tuple[int, int]]:
    """
    Returns list of (day_offset, bucket_idx_in_day) that this template covers,
    relative to the day it's assigned on. Handles wrap past midnight.
    v1: if duration_minutes is used, assume fully working. If bucket_work_pattern is used, use it.
    """
    start = _hhmm_to_bucket(t["start_time_local"], bucket_minutes)
    if "bucket_work_pattern" in t:
        pattern = t["bucket_work_pattern"]
        spans = []
        for off, v in enumerate(pattern):
            if v != 1:
                continue
            b = start + off
            day_off = b // buckets_per_day
            b_in = b % buckets_per_day
            spans.append((day_off, b_in))
        return spans

    dur_min = int(t["duration_minutes"])
    dur_buckets = dur_min // bucket_minutes
    spans = []
    for off in range(dur_buckets):
        b = start + off
        day_off = b // buckets_per_day
        b_in = b % buckets_per_day
        spans.append((day_off, b_in))
    return spans


def build_and_solve(
    data: Dict[str, Any],
    *,
    msg: bool = True,
) -> Dict[str, Any]:
    """
    Build and solve the v1 model (follow-demand only).
    Returns a dict with solution artifacts (assignments, understaff summary).
    """
    start_date = date.fromisoformat(data["time"]["start_date"])
    days = int(data["time"]["days"])
    bucket_minutes = int(data["time"]["bucket_minutes"])
    ti = TimeIndex(start_date=start_date, days=days, bucket_minutes=bucket_minutes)

    # Demand per (day,bucket,skill_group_id) and inferred mapping skill_group_id -> (direction, channel)
    demand: Dict[Tuple[int, int, str], int] = {}
    sg_stream: Dict[str, Stream] = {}
    for r in data["forecast"]:
        dt = parse_forecast_timestamp(r["timestamp_local"])
        d, b = ti.day_bucket_from_dt(dt)
        sg = r["skill_group_id"]
        stream = (r["direction"], r["channel"])
        if sg in sg_stream and sg_stream[sg] != stream:
            raise ValueError(f"skill_group_id {sg!r} appears with multiple streams: {sg_stream[sg]} vs {stream}")
        sg_stream[sg] = stream
        key = (d, b, sg)
        demand[key] = demand.get(key, 0) + int(r["agents"])

    # Streams referenced anywhere (for priority weighting)
    streams_set = set(sg_stream.values())
    for w in data.get("priority_rules", []):
        for p in w.get("priorities", []):
            streams_set.add((p["direction"], p["channel"]))
    for oh in data.get("operating_hours", []):
        streams_set.add((oh["direction"], oh["channel"]))
    streams: List[Stream] = sorted(streams_set)

    # Priority weights per (day,bucket,stream). Default 1.0.
    weights: Dict[Tuple[int, int, str, str], float] = {}
    for d, b in ti.iter_day_buckets():
        for direction, channel in streams:
            weights[(d, b, direction, channel)] = 1.0

    # Apply priority_rules by time window / day-of-week
    # If a window applies, choose max weight among applicable windows.
    # If understaff_weight not provided, map rank 1->100, 2->10, 3->1, 4->0.3, ...
    rank_default = {1: 100.0, 2: 10.0, 3: 1.0, 4: 0.3, 5: 0.1}

    # Day-of-week lookup for each day_idx
    day_dow: Dict[int, str] = {}
    for day_idx in range(days):
        dte = date.fromordinal(ti.start_date.toordinal() + day_idx)
        day_dow[day_idx] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dte.weekday()]

    for w in data.get("priority_rules", []):
        start_b = _hhmm_to_bucket(w["start_time_local"], bucket_minutes)
        end_b = _hhmm_to_bucket(w["end_time_local"], bucket_minutes)
        days_filter = set(w.get("applies_to_days", []))
        for day_idx in range(days):
            if days_filter and day_dow[day_idx] not in days_filter:
                continue
            for b in range(start_b, min(end_b, ti.buckets_per_day)):
                for p in w.get("priorities", []):
                    direction = p["direction"]
                    channel = p["channel"]
                    rank = int(p["rank"])
                    wgt = float(p.get("understaff_weight", rank_default.get(rank, 0.05)))
                    key = (day_idx, b, direction, channel)
                    weights[key] = max(weights.get(key, 1.0), wgt)

    # Employee supply (multi-skill)
    employees = data["employees"]
    employment_groups = {eg["id"]: eg for eg in data["employment_groups"]}

    # Shift templates list and coverage spans
    templates = {t["id"]: t for t in data["shift_templates"]}
    # Precompute coverage: cov[(template_id, day_offset, bucket_in_day)] = 1 if covers
    cov: Dict[Tuple[str, int, int], int] = {}
    for tid, t in templates.items():
        for day_off, b_in in _template_covers_bucket(t, bucket_minutes, ti.buckets_per_day):
            cov[(tid, day_off, b_in)] = 1

    # Allowed templates per employment group based on min/max hours per day
    # v1 simplification: enforce via template duration only.
    allowed: Dict[Tuple[str, str], bool] = {}
    for eg_id, eg in employment_groups.items():
        min_day = float(eg["hours_per_day"]["min"])
        max_day = float(eg["hours_per_day"]["max"])
        for tid, t in templates.items():
            dur_hr = float(t["duration_minutes"]) / 60.0
            allowed[(eg_id, tid)] = (dur_hr >= min_day - 1e-9) and (dur_hr <= max_day + 1e-9)

    # Model
    prob = pulp.LpProblem("shiftopt_v1", pulp.LpMinimize)

    emp_ids = [e["id"] for e in employees]
    template_ids = list(templates.keys())
    skill_group_ids = [sg["id"] for sg in data["skill_groups"]]

    # Shift assignment variables per employee
    s: Dict[Tuple[str, int, str], pulp.LpVariable] = {}
    for e in employees:
        eg = e["employment_group_id"]
        for day in range(days):
            for tid in template_ids:
                if not allowed.get((eg, tid), False):
                    continue
                s[(e["id"], day, tid)] = pulp.LpVariable(f"s_{e['id']}_d{day}_{tid}", lowBound=0, upBound=1, cat="Binary")

    # Work expression per employee per bucket (0..1, computed from shift assignment)
    work: Dict[Tuple[str, int, int], pulp.LpAffineExpression] = {}
    max_day_off = 1  # with 8h max, at most wrap into next day
    for e in employees:
        emp = e["id"]
        for day, b in ti.iter_day_buckets():
            expr = pulp.LpAffineExpression()
            for day_off in range(max_day_off + 1):
                src_day = day - day_off
                if src_day < 0:
                    continue
                for tid in template_ids:
                    var = s.get((emp, src_day, tid))
                    if var is None:
                        continue
                    if cov.get((tid, day_off, b), 0) == 1:
                        expr += var
            work[(emp, day, b)] = expr

    # One shift per employee per day
    for e in employees:
        emp = e["id"]
        for day in range(days):
            lhs = pulp.LpAffineExpression()
            for tid in template_ids:
                var = s.get((emp, day, tid))
                if var is not None:
                    lhs += var
            prob += lhs <= 1, f"one_shift_{emp}_d{day}"

    # Weekly hour constraints per employee (hard min/max)
    for e in employees:
        emp = e["id"]
        eg = e["employment_group_id"]
        min_w = float(employment_groups[eg]["hours_per_week"]["min"])
        max_w = float(employment_groups[eg]["hours_per_week"]["max"])
        for w in ti.weeks():
            day_start = w * 7
            day_end = min(days, day_start + 7)
            lhs_hours = pulp.LpAffineExpression()
            for day in range(day_start, day_end):
                for tid, t in templates.items():
                    var = s.get((emp, day, tid))
                    if var is None:
                        continue
                    dur_hr = float(t["duration_minutes"]) / 60.0
                    lhs_hours += dur_hr * var
            prob += lhs_hours >= min_w, f"min_week_hours_{emp}_w{w}"
            prob += lhs_hours <= max_w, f"max_week_hours_{emp}_w{w}"

    # Allocation variables per employee per bucket per skill_group (binary) only for skills they have
    z: Dict[Tuple[str, int, int, str], pulp.LpVariable] = {}
    for e in employees:
        emp = e["id"]
        for sg in e["skill_group_ids"]:
            for day, b in ti.iter_day_buckets():
                z[(emp, day, b, sg)] = pulp.LpVariable(f"z_{emp}_d{day}_b{b}_{sg}", lowBound=0, upBound=1, cat="Binary")

    # Understaff slack per (day,bucket,skill_group)
    u: Dict[Tuple[int, int, str], pulp.LpVariable] = {}
    for day, b in ti.iter_day_buckets():
        for sg in skill_group_ids:
            u[(day, b, sg)] = pulp.LpVariable(f"u_d{day}_b{b}_{sg}", lowBound=0, cat="Continuous")

    # Allocation limited by working: sum_sg z <= work(emp,day,b)
    for e in employees:
        emp = e["id"]
        for day, b in ti.iter_day_buckets():
            lhs = pulp.LpAffineExpression()
            for sg in e["skill_group_ids"]:
                lhs += z[(emp, day, b, sg)]
            prob += lhs <= work[(emp, day, b)], f"alloc_le_work_{emp}_d{day}_b{b}"

    # Coverage per skill group
    for day, b in ti.iter_day_buckets():
        for sg in skill_group_ids:
            req = demand.get((day, b, sg), 0)
            lhs = pulp.LpAffineExpression()
            for e in employees:
                emp = e["id"]
                if sg in e["skill_group_ids"]:
                    lhs += z[(emp, day, b, sg)]
            lhs += u[(day, b, sg)]
            prob += lhs >= req, f"cov_{sg}_d{day}_b{b}"

            # Do not allocate more employees than required (keeps allocations interpretable for reporting)
            if req >= 0:
                prob += lhs - u[(day, b, sg)] <= req, f"no_over_alloc_{sg}_d{day}_b{b}"

    # Objective: minimize weighted understaff
    obj = pulp.LpAffineExpression()
    for (day, b, sg), var in u.items():
        stream = sg_stream.get(sg)
        if stream is None:
            wgt = 1.0
        else:
            wgt = float(weights.get((day, b, stream[0], stream[1]), 1.0))
        obj += wgt * var
    prob += obj

    # Solve
    time_limit = data.get("solver", {}).get("time_limit_seconds")
    gap = data.get("solver", {}).get("mip_gap")
    solver = pulp.PULP_CBC_CMD(
        msg=msg,
        timeLimit=float(time_limit) if time_limit else None,
        gapRel=float(gap) if gap is not None else None,
    )
    status = prob.solve(solver)

    # Extract results
    employee_shifts = []
    for e in employees:
        emp = e["id"]
        eg = e["employment_group_id"]
        for day in range(days):
            for tid in template_ids:
                var = s.get((emp, day, tid))
                if var is None:
                    continue
                if float(var.value() or 0.0) >= 0.5:
                    employee_shifts.append(
                        {
                            "employee_id": emp,
                            "day_index": day,
                            "employment_group_id": eg,
                            "shift_template_id": tid,
                        }
                    )

    # Allocation (sparse): only nonzero z
    employee_allocation = []
    for e in employees:
        emp = e["id"]
        for sg in e["skill_group_ids"]:
            for day, b in ti.iter_day_buckets():
                var = z[(emp, day, b, sg)]
                val = float(var.value() or 0.0)
                if val >= 0.5:
                    employee_allocation.append(
                        {"employee_id": emp, "day_index": day, "bucket_index": b, "skill_group_id": sg, "work": 1}
                    )

    understaff = []
    total_under = 0.0
    for (day, b, sg), var in u.items():
        val = float(var.value() or 0.0)
        if val <= 1e-6:
            continue
        req = demand.get((day, b, sg), 0)
        total_under += val
        stream = sg_stream.get(sg, ("", ""))
        understaff.append(
            {
                "day_index": day,
                "bucket_index": b,
                "skill_group_id": sg,
                "direction": stream[0],
                "channel": stream[1],
                "required": req,
                "understaff": val,
                "weight": float(weights.get((day, b, stream[0], stream[1]), 1.0)) if stream[0] else 1.0,
            }
        )

    coverage = []
    for day, b in ti.iter_day_buckets():
        for sg in skill_group_ids:
            req = demand.get((day, b, sg), 0)
            under = float(u[(day, b, sg)].value() or 0.0)
            allocated = 0.0
            for e in employees:
                emp = e["id"]
                if sg in e["skill_group_ids"]:
                    allocated += float(z[(emp, day, b, sg)].value() or 0.0)
            stream = sg_stream.get(sg, ("", ""))
            coverage.append(
                {
                    "day_index": day,
                    "bucket_index": b,
                    "skill_group_id": sg,
                    "direction": stream[0],
                    "channel": stream[1],
                    "required": req,
                    "allocated": allocated,
                    "understaff": under,
                    "weight": float(weights.get((day, b, stream[0], stream[1]), 1.0)) if stream[0] else 1.0,
                }
            )

    return {
        "status": pulp.LpStatus.get(status, str(status)),
        "objective_value": float(pulp.value(prob.objective) or 0.0),
        "total_understaff": total_under,
        "employee_shifts": employee_shifts,
        "employee_allocation": employee_allocation,
        "understaff": understaff,
        "coverage": coverage,
    }

