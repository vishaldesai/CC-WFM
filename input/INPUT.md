# Input

This folder contains sample inputs that conform to `schemas/shiftopt.input.schema.json`.

## Files
- `sample_input.small.json`
  - 28-day horizon, 30-minute buckets
  - 4 skill groups (billing voice/chat/email, recover outbound voice)
  - 15 agents mapped to skill groups
  - Employment mix: 10 `full_time`, 5 `part_time` (15 total)
  - Employment groups (contracts): part-time and full-time with min/max hours per day/week
  - Group rules (constraints enforced by the solver)
    - Employment groups:
      - `part_time`: 20–30 hours/week, 4–8 hours/day
      - `full_time`: 40–40 hours/week, 6–8 hours/day
    - Per employee:
      - At most **one shift assignment per day**
      - Weekly hours must satisfy the employee’s employment group min/max
      - Only shift templates whose duration fits the employment group’s daily min/max are allowed (e.g., part-time can take 4h or 8h; full-time can take 8h but not 4h)
  - Shift templates (fixed 4h/8h, no breaks in v1)
    - Each template has: `id`, `name`, `start_time_local` (HH:MM), `duration_minutes`
    - 8h templates (`duration_minutes: 480`): start at `09:00, 10:00, 11:00, 12:00, 13:00` (5 templates, e.g. `S_0900_8H`)
    - 4h templates (`duration_minutes: 240`): start at `09:00, 10:00, …, 17:00` (9 templates, e.g. `S_1700_4H`)
  - Mon–Fri operating hours: 09:00–21:00
    - inbound demand generated for 09:00–18:00
    - outbound demand generated for 16:00–21:00
  - Saturday operating hours: 10:00–18:00 (inbound only)
  - Per-interval total demand is capped at 15 agents across all streams
  - Notes on priority weights and solver settings
    - `priority_rules[].priorities[].understaff_weight` is **optional**:
      - If omitted, the solver auto-derives a weight from `rank` (defaults: 1→100, 2→10, 3→1, 4→0.3, 5→0.1, else 0.05).
      - If provided, it overrides the rank-derived default for that (direction, channel) during the window.
    - `solver.mip_gap` controls the CBC **relative MIP optimality gap**:
      - Example: `mip_gap: 0.01` allows the solver to stop once it proves the solution is within **1% of optimal** (often faster).

- `sample_input.stress.json`
  - Same demand/supply structure as small, but with higher variability in the generated demand profile
  - Denser shift template start times (every 30 minutes) to increase decision space
  - Employment mix: 10 `full_time`, 5 `part_time` (15 total)
  - Group rules (constraints enforced by the solver)
    - Employment groups:
      - `part_time`: 20–30 hours/week, 4–8 hours/day
      - `full_time`: 40–40 hours/week, 6–8 hours/day
    - Per employee:
      - At most **one shift assignment per day**
      - Weekly hours must satisfy the employee’s employment group min/max
      - Only shift templates whose duration fits the employment group’s daily min/max are allowed (e.g., part-time can take 4h or 8h; full-time can take 8h but not 4h)
  - Shift templates (denser starts; fixed 4h/8h, no breaks in v1)
    - 4h templates (`duration_minutes: 240`): start every 30 minutes from 09:00–17:30 (18 templates)
    - 8h templates (`duration_minutes: 480`): start every 30 minutes from 09:00–13:30 (10 templates)
  - Solver settings: longer time limit (120s) due to larger decision space

## How these were generated
Run:

```bash
python scripts/generate_sample_inputs.py
```

This will write/overwrite the two sample files in this directory (`input/`).

