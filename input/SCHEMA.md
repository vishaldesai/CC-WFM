# ShiftOpt Input JSON — Schema Guide (Human Readable)

This document explains **every block** in the ShiftOpt input JSON in plain language.
For the authoritative machine validation rules, see `schemas/shiftopt.input.schema.json`.

## How to read this guide

- **Required vs optional**: The JSON Schema enforces required fields. This guide calls out what’s required and what’s optional.
- **IDs**: Many objects use stable IDs (e.g., `skill_group_id`). IDs are used to join data across sections.
- **Time model**: This project uses a **28-day horizon** and **30-minute buckets** in v1.
- **What the solver uses today**: Some blocks exist for future expansion. This guide explicitly notes whether each block is used by the solver **right now**.

---

## Top-level object (root)

The input JSON is one object with these top-level keys:

- **`run`** *(optional)*: schedule metadata (id/name/description)
- **`meta`** *(required)*: version + created timestamp
- **`time`** *(required)*: horizon definition
- **`channels`** *(required)*: channel list (voice/chat/email…)
- **`skill_groups`** *(required)*: master list of skill groups
- **`employment_groups`** *(required)*: contract definitions (part-time/full-time rules)
- **`forecast`** *(required)*: demand rows by skill group and timestamp
- **`operating_hours`** *(optional)*: “open hours” windows by (direction, channel)
- **`priority_rules`** *(optional)*: time-windowed priority rules that influence understaff penalties
- **`employees`** *(required)*: the labor supply (named individuals + skills + contract)
- **`agent_groups`** *(required)*: pooled groups (kept for future; see notes)
- **`skills`** *(required)*: mapping of groups to channels (kept for future; see notes)
- **`shift_templates`** *(required)*: allowed shift patterns (start time + duration/pattern)
- **`solver`** *(required)*: solver settings (CBC)

---

## `run` (optional) — schedule metadata

**Purpose**: Traceability. Helps you label runs and outputs.

**Fields**:
- **`schedule_id`** *(optional)*: string id (e.g. `"sched_2026wk01"`)
- **`schedule_name`** *(optional)*: human name (e.g. `"Jan Week 1 Draft"`)
- **`description`** *(optional)*: free text

**Used by solver?** No (metadata only).

---

## `meta` (required) — generation metadata

**Purpose**: Track schema version and creation time of the input file.

**Fields**:
- **`version`** *(required)*: string
- **`created_at`** *(required)*: ISO 8601 datetime (schema format: `date-time`)

**Used by solver?** No (metadata only).

---

## `time` (required) — horizon and bucket size

**Purpose**: Defines the time axis used throughout the problem.

**Fields**:
- **`start_date`** *(required)*: ISO date (`YYYY-MM-DD`) for `day_index = 0`
- **`timezone`** *(required)*: IANA timezone name (e.g. `"America/New_York"`)
- **`days`** *(required, fixed)*: must be `28` in v1
- **`bucket_minutes`** *(required, fixed)*: must be `30` in v1

**Used by solver?** Yes. This defines bucket indexing and weekly groupings.

**Interpretation**:
- A day has \(24 \times 60 / 30 = 48\) buckets.
- A timestamp belongs to one (day_index, bucket_index) pair.

---

## `channels` (required) — channel list

**Purpose**: Declare channel identifiers used across the model (voice, chat, email, …).

**Item shape**:
- **`id`** *(required)*: stable id (recommended: `"voice"`, `"chat"`, `"email"`)
- **`name`** *(required)*: display name

**Used by solver?** Indirectly. The solver uses `forecast[].channel` and `priority_rules` streams;
this list is primarily for validation/documentation consistency.

---

## `skill_groups` (required) — master list of skill groups

**Purpose**: Stable list of skill groups to join:
- demand (`forecast[].skill_group_id`)
- supply (`employees[].skill_group_ids`)
- reporting (`coverage.csv`, `employee_allocation.csv`, charts)

**Item shape**:
- **`id`** *(required)*: stable id (e.g. `"billing_v"`)
- **`name`** *(required)*: display name (e.g. `"billing-v"`)

**Used by solver?** Yes. Skill groups are the fundamental coverage dimensions.

---

## `employment_groups` (required) — contract rules

**Purpose**: Group employees into contracts (part-time/full-time…) so constraints are applied consistently.

**Item shape**:
- **`id`** *(required)*: stable id (e.g. `"part_time"`, `"full_time"`)
- **`name`** *(required)*: display name
- **`hours_per_week`** *(required)*:
  - **`min`** *(required)*: minimum weekly hours
  - **`max`** *(required)*: maximum weekly hours
- **`hours_per_day`** *(required)*:
  - **`min`** *(required)*: minimum daily hours (used as template eligibility)
  - **`max`** *(required)*: maximum daily hours (used as template eligibility)

**Used by solver?** Yes.

**How v1 uses these rules**:
- **Weekly min/max hours** are enforced as hard constraints per employee.
- **Daily min/max hours** are enforced by restricting which shift templates an employee is allowed to take
  (based on template duration).
- **One shift per day** is enforced per employee (not per group).

---

## `forecast` (required) — demand rows (required agents)

**Purpose**: The “demand” signal the solver tries to meet.

Each row expresses required agents for a specific:
- skill group
- local timestamp
- direction (inbound/outbound)
- channel (voice/chat/email…)

**Item shape**:
- **`skill_group_id`** *(required)*: joins to `skill_groups[].id`
- **`timestamp_local`** *(required)*: string in format `DD-MON-YYYY HH24:MI:SS`
  - Example: `"06-JAN-2026 09:30:00"`
- **`direction`** *(required)*: `"inbound"` or `"outbound"`
- **`channel`** *(required)*: channel id (recommended to match `channels[].id`)
- **`agents`** *(required)*: integer ≥ 0

**Used by solver?** Yes. This becomes the coverage requirement per bucket.

**Important**:
- In v1, `agents` is assumed to already include shrinkage and any upstream adjustments.
- If multiple rows map to the same (day, bucket, skill_group_id), they are summed.

---

## `operating_hours` (optional) — “open hours” by stream

**Purpose**: Describe when a (direction, channel) stream is open.

**Item shape**:
- **`name`** *(optional)*: label
- **`direction`** *(required)*: `"inbound"` / `"outbound"`
- **`channel`** *(required)*: channel id
- **`start_time_local`** *(required)*: `"HH:MM"`
- **`end_time_local`** *(required)*: `"HH:MM"`
- **`applies_to_days`** *(optional)*: subset of `["mon","tue","wed","thu","fri","sat","sun"]`

**Used by solver?**
- **Not enforced as hard constraints in v1** (i.e., the solver doesn’t force zero staffing outside these windows).
- It is still useful for input clarity and future constraints/reporting.

---

## `priority_rules` (optional) — time-windowed priority weighting

**Purpose**: Change the “importance” of understaffing by time window.
This does **not** change the demand; it changes the **objective weights**.

**Window item shape**:
- **`name`** *(optional)*: label
- **`start_time_local`** *(required)*: `"HH:MM"`
- **`end_time_local`** *(required)*: `"HH:MM"`
- **`applies_to_days`** *(optional)*: day-of-week filter
- **`priorities`** *(required)*: list of priority items

**Priority item shape**:
- **`direction`** *(required)*: `"inbound"` / `"outbound"`
- **`channel`** *(required)*: channel id
- **`rank`** *(required)*: integer, where **1 is highest priority**
- **`understaff_weight`** *(optional)*:
  - If omitted, the solver auto-derives a weight from `rank` (defaults: 1→100, 2→10, 3→1, 4→0.3, 5→0.1, else 0.05).
  - If provided, it overrides the rank-derived default for that (direction, channel) during the window.

**Used by solver?** Yes. It builds a per-(day,bucket,stream) weight and multiplies understaff slack in the objective.

---

## `employees` (required) — the labor supply (named individuals)

**Purpose**: Define the available agents and what they can work.

**Item shape**:
- **`id`** *(required)*: employee id (e.g. `"A01"`)
- **`name`** *(required)*: display name (e.g. `"Agent A01"`)
- **`skill_group_ids`** *(required)*: list of skill group ids the employee can cover
  - This enables cross-skill assignment in the model.
- **`employment_group_id`** *(required)*: joins to `employment_groups[].id`
- **`pay_rate`** *(optional)*: reserved for later (not used in v1 objective)

**Used by solver?** Yes. v1 is **employee-level** scheduling and allocation.

**Key v1 behavior**:
- A scheduled employee can be allocated to **at most one** skill group in each bucket.
- Allocation is constrained to the employee’s `skill_group_ids`.
- Total allocation per skill group is capped to demand (so allocations remain interpretable).

---

## `agent_groups` (required) — pooled groups (reserved in v1)

**Purpose**: Represents pooled capacity groups (common in WFM).

**Used by solver?** **Not currently** in the employee-level v1 model.
This block is kept for future extensions (group-level constraints/caps/costs).

---

## `skills` (required) — group-to-channel capability (reserved in v1)

**Purpose**: In a group-based model, expresses which groups can serve which channels.

**Used by solver?** **Not currently** in the employee-level v1 model.
Employee capabilities come from `employees[].skill_group_ids`.

---

## `shift_templates` (required) — allowed shift patterns

**Purpose**: The building blocks used to assign work to employees.

Each template defines:
- when a shift starts (`start_time_local`)
- how long it lasts (`duration_minutes`) **or** an explicit per-bucket pattern (`bucket_work_pattern`)

**Item shape**:
- **`id`** *(required)*: template id (e.g. `"S_0900_8H"`)
- **`name`** *(required)*: label (e.g. `"09:00 8h"`)
- **`start_time_local`** *(required)*: `"HH:MM"`
- **Either**:
  - **`duration_minutes`** *(required in the common case)*: integer minutes (e.g. `240`, `480`)
  - **or** **`bucket_work_pattern`** *(optional advanced)*: array of 0/1 indicating which buckets are worked, starting from `start_time_local`

**Used by solver?** Yes. Templates define which (day,bucket) positions a shift covers.

**Notes**:
- v1 assumes templates represent **fully working time** (no explicit breaks in the template definition).
- Templates can wrap past midnight (handled by the model).

---

## `solver` (required) — solver configuration

**Purpose**: Configure the optimization solver backend.

**Fields**:
- **`name`** *(required)*: `"cbc"` (PuLP’s CBC backend)
- **`time_limit_seconds`** *(optional)*: wall-clock time limit
- **`mip_gap`** *(optional)*: relative optimality gap tolerance for CBC
  - Example: `0.01` allows the solver to stop once it proves the solution is within **1% of optimal** (often faster).

**Used by solver?** Yes.

