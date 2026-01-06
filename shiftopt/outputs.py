from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd

from .time_index import TimeIndex


@dataclass(frozen=True)
class OutputPaths:
    solution_json: Path
    assignments_csv: Path
    coverage_csv: Path
    understaff_csv: Path
    employee_schedule_csv: Path
    employee_allocation_csv: Path
    kpis_json: Path


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _build_time_index(data: Dict[str, Any]) -> TimeIndex:
    start_date = date.fromisoformat(data["time"]["start_date"])
    return TimeIndex(
        start_date=start_date,
        days=int(data["time"]["days"]),
        bucket_minutes=int(data["time"]["bucket_minutes"]),
    )


def _day_to_date(ti: TimeIndex, day_idx: int) -> date:
    return date.fromordinal(ti.start_date.toordinal() + day_idx)


def write_outputs(
    *,
    input_data: Dict[str, Any],
    solution: Dict[str, Any],
    out_dir: str | Path,
) -> OutputPaths:
    out_dir = Path(out_dir)
    _ensure_dir(out_dir)

    paths = OutputPaths(
        solution_json=out_dir / "solution.json",
        assignments_csv=out_dir / "assignments.csv",
        coverage_csv=out_dir / "coverage.csv",
        understaff_csv=out_dir / "understaff.csv",
        employee_schedule_csv=out_dir / "employee_schedule.csv",
        employee_allocation_csv=out_dir / "employee_allocation.csv",
        kpis_json=out_dir / "kpis.json",
    )

    # Write raw-ish solution
    paths.solution_json.write_text(json.dumps(solution, indent=2) + "\n", encoding="utf-8")

    ti = _build_time_index(input_data)

    # Shift templates / metadata
    templates = {t["id"]: t for t in input_data["shift_templates"]}
    employment_groups = {eg["id"]: eg for eg in input_data["employment_groups"]}
    employees = {e["id"]: e for e in input_data["employees"]}
    skill_groups = {sg["id"]: sg for sg in input_data["skill_groups"]}

    # Assignments table (employee shift assignments)
    shifts = pd.DataFrame(solution.get("employee_shifts", []))
    assn = shifts.copy()
    if not assn.empty:
        assn["date"] = assn["day_index"].apply(lambda d: _day_to_date(ti, int(d)).isoformat())
        assn["employee_name"] = assn["employee_id"].map(lambda x: employees.get(x, {}).get("name", x))
        assn["employment_group_name"] = assn["employment_group_id"].map(lambda x: employment_groups.get(x, {}).get("name", x))
        assn["start_time_local"] = assn["shift_template_id"].map(lambda x: templates.get(x, {}).get("start_time_local", ""))
        assn["duration_minutes"] = assn["shift_template_id"].map(lambda x: templates.get(x, {}).get("duration_minutes", None))
        assn["duration_hours"] = assn["duration_minutes"].map(lambda m: float(m) / 60.0 if m is not None else None)
        assn = assn[
            [
                "day_index",
                "date",
                "employee_id",
                "employee_name",
                "employment_group_id",
                "employment_group_name",
                "shift_template_id",
                "start_time_local",
                "duration_minutes",
                "duration_hours",
            ]
        ].sort_values(["day_index", "employment_group_id", "employee_id", "shift_template_id"])
    assn.to_csv(paths.assignments_csv, index=False)

    # Coverage table
    cov = pd.DataFrame(solution.get("coverage", []))
    if not cov.empty:
        cov["date"] = cov["day_index"].apply(lambda d: _day_to_date(ti, int(d)).isoformat())
        cov["time_local"] = cov["bucket_index"].apply(
            lambda b: f"{(int(b) * ti.bucket_minutes)//60:02d}:{(int(b) * ti.bucket_minutes)%60:02d}"
        )
        cov["skill_group_name"] = cov["skill_group_id"].map(lambda x: skill_groups.get(x, {}).get("name", x))
        cov = cov[
            [
                "day_index",
                "date",
                "bucket_index",
                "time_local",
                "skill_group_id",
                "skill_group_name",
                "direction",
                "channel",
                "required",
                "allocated",
                "understaff",
                "weight",
            ]
        ].sort_values(["day_index", "bucket_index", "skill_group_id"])
    cov.to_csv(paths.coverage_csv, index=False)

    # Understaff (sparse)
    us = pd.DataFrame(solution.get("understaff", []))
    if not us.empty:
        us["date"] = us["day_index"].apply(lambda d: _day_to_date(ti, int(d)).isoformat())
        us["time_local"] = us["bucket_index"].apply(
            lambda b: f"{(int(b) * ti.bucket_minutes)//60:02d}:{(int(b) * ti.bucket_minutes)%60:02d}"
        )
        us["skill_group_name"] = us["skill_group_id"].map(lambda x: skill_groups.get(x, {}).get("name", x))
        us = us[
            [
                "day_index",
                "date",
                "bucket_index",
                "time_local",
                "skill_group_id",
                "skill_group_name",
                "direction",
                "channel",
                "required",
                "understaff",
                "weight",
            ]
        ].sort_values(["day_index", "bucket_index", "skill_group_id"])
    us.to_csv(paths.understaff_csv, index=False)

    # Employee-level shift schedule (directly from model)
    emp_sched = shifts.copy()
    if not emp_sched.empty:
        emp_sched["date"] = emp_sched["day_index"].apply(lambda d: _day_to_date(ti, int(d)).isoformat())
        emp_sched["employee_name"] = emp_sched["employee_id"].map(lambda x: employees.get(x, {}).get("name", x))
        emp_sched["employment_group_name"] = emp_sched["employment_group_id"].map(lambda x: employment_groups.get(x, {}).get("name", x))
        emp_sched["start_time_local"] = emp_sched["shift_template_id"].map(lambda x: templates.get(x, {}).get("start_time_local", ""))
        emp_sched["duration_minutes"] = emp_sched["shift_template_id"].map(lambda x: templates.get(x, {}).get("duration_minutes", None))
        emp_sched = emp_sched[
            [
                "employee_id",
                "employee_name",
                "employment_group_id",
                "employment_group_name",
                "day_index",
                "date",
                "shift_template_id",
                "start_time_local",
                "duration_minutes",
            ]
        ].sort_values(["day_index", "employee_id"])
    emp_sched.to_csv(paths.employee_schedule_csv, index=False)

    # Employee allocation (sparse, per bucket)
    alloc = pd.DataFrame(solution.get("employee_allocation", []))
    if not alloc.empty:
        alloc["date"] = alloc["day_index"].apply(lambda d: _day_to_date(ti, int(d)).isoformat())
        alloc["time_local"] = alloc["bucket_index"].apply(
            lambda b: f"{(int(b) * ti.bucket_minutes)//60:02d}:{(int(b) * ti.bucket_minutes)%60:02d}"
        )
        alloc["employee_name"] = alloc["employee_id"].map(lambda x: employees.get(x, {}).get("name", x))
        alloc["employment_group_id"] = alloc["employee_id"].map(lambda x: employees.get(x, {}).get("employment_group_id", ""))
        alloc["employment_group_name"] = alloc["employment_group_id"].map(lambda x: employment_groups.get(x, {}).get("name", x))
        alloc["skill_group_name"] = alloc["skill_group_id"].map(lambda x: skill_groups.get(x, {}).get("name", x))

        # Employee skill groups (from input employee.skill_group_ids, not just what they happened to work)
        def _emp_skill_names(emp_id: str) -> str:
            emp = employees.get(emp_id, {})
            sg_ids = emp.get("skill_group_ids", []) or []
            names = [skill_groups.get(sg_id, {}).get("name", sg_id) for sg_id in sg_ids]
            # deterministic order
            return ", ".join(sorted({str(n) for n in names if n}))

        alloc["employee_skill_groups"] = alloc["employee_id"].map(_emp_skill_names)
        alloc = alloc[
            [
                "employee_id",
                "employee_name",
                "employment_group_id",
                "employment_group_name",
                "employee_skill_groups",
                "day_index",
                "date",
                "bucket_index",
                "time_local",
                "skill_group_id",
                "skill_group_name",
                "work",
            ]
        ].sort_values(["employee_id", "day_index", "bucket_index"])
    alloc.to_csv(paths.employee_allocation_csv, index=False)

    # KPIs
    kpis: Dict[str, Any] = {
        "status": solution.get("status"),
        "objective_value": solution.get("objective_value"),
        "total_understaff": solution.get("total_understaff"),
        "employee_shift_rows": int(len(solution.get("employee_shifts", []))),
        "understaff_rows": int(len(solution.get("understaff", []))),
    }
    if not cov.empty:
        tmp = cov.copy()
        tmp["stream"] = tmp["direction"] + ":" + tmp["channel"]
        tmp["skill_group"] = tmp["skill_group_id"]
        kpis["understaff_by_skill_group"] = (
            tmp.groupby("skill_group", as_index=True)["understaff"].sum().sort_values(ascending=False).to_dict()
        )
        kpis["understaff_by_stream"] = (
            tmp.groupby("stream", as_index=True)["understaff"].sum().sort_values(ascending=False).to_dict()
        )
        kpis["required_by_stream"] = (
            tmp.groupby("stream", as_index=True)["required"].sum().sort_values(ascending=False).to_dict()
        )
    paths.kpis_json.write_text(json.dumps(kpis, indent=2) + "\n", encoding="utf-8")

    return paths

