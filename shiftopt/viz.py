from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.io as pio


def write_html_report(
    *,
    coverage_csv: str | Path,
    employee_allocation_csv: str | Path,
    out_html: str | Path,
    title: str = "ShiftOpt Report",
    day_index: int = 0,
) -> Path:
    coverage_csv = Path(coverage_csv)
    employee_allocation_csv = Path(employee_allocation_csv)
    out_html = Path(out_html)

    cov = pd.read_csv(coverage_csv)
    alloc_emp = pd.read_csv(employee_allocation_csv) if employee_allocation_csv.exists() else pd.DataFrame()

    if cov.empty:
        out_html.write_text("<html><body><h2>No coverage data</h2></body></html>", encoding="utf-8")
        return out_html

    cov["stream"] = cov["direction"].astype(str) + ":" + cov["channel"].astype(str)
    cov["dt"] = pd.to_datetime(cov["date"].astype(str) + " " + cov["time_local"].astype(str), errors="coerce")

    figs = []

    # 1) Line chart: demand vs supply per interval (total across streams) for full horizon
    if cov["dt"].notna().any():
        by_dt = cov.groupby(["dt"], as_index=False)[["required", "allocated", "understaff"]].sum()
        fig_total = px.line(
            by_dt.sort_values("dt"),
            x="dt",
            y=["required", "allocated", "understaff"],
            title="Full horizon — total demand vs supply per interval",
        )
        fig_total.update_layout(xaxis_title="datetime (local)", yaxis_title="agents", height=600)
        fig_total.update_traces(mode="lines")  # no markers/edges
        fig_total.update_xaxes(showgrid=False, zeroline=False, rangeslider_visible=True, rangeslider_thickness=0.05)
        fig_total.update_yaxes(showgrid=False, zeroline=False)
        figs.append(fig_total)

        # Per-stream overlay (interactive legend), aggregated across skill groups
        stream_cov = (
            cov.groupby(["dt", "stream"], as_index=False)[["required", "allocated", "understaff"]]
            .sum()
            .sort_values(["dt", "stream"])
        )
        fig_stream = px.line(
            stream_cov,
            x="dt",
            y="required",
            color="stream",
            title="Full horizon — demand by direction-channel",
        )
        fig_stream.update_layout(xaxis_title="datetime (local)", yaxis_title="required agents", height=600)
        fig_stream.update_traces(mode="lines")
        fig_stream.update_xaxes(showgrid=False, zeroline=False, rangeslider_visible=True, rangeslider_thickness=0.05)
        fig_stream.update_yaxes(showgrid=False, zeroline=False)
        figs.append(fig_stream)

        fig_stream2 = px.line(
            stream_cov,
            x="dt",
            y="allocated",
            color="stream",
            title="Full horizon — supply (allocated) by stream",
        )
        fig_stream2.update_layout(xaxis_title="datetime (local)", yaxis_title="allocated agents", height=600)
        fig_stream2.update_traces(mode="lines")
        fig_stream2.update_xaxes(showgrid=False, zeroline=False, rangeslider_visible=True, rangeslider_thickness=0.05)
        fig_stream2.update_yaxes(showgrid=False, zeroline=False)
        figs.append(fig_stream2)

    # 2) (Grid table removed by request)

    # 3) Employee allocation timeline (shows cross-skill work over time)
    # Build segments from per-bucket allocation rows.
    # Also build demand/supply aggregates by skill group for a summary table (synced to zoom/filter).
    cov_sg = cov[cov["dt"].notna()].groupby(["dt", "skill_group_name"], as_index=False)[
        ["required", "allocated", "understaff"]
    ].sum()
    # Derived for UI convenience
    cov_sg["dt"] = cov_sg["dt"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    sg_full = (
        cov.groupby("skill_group_name", as_index=False)[["required", "allocated", "understaff"]]
        .sum()
        .sort_values("skill_group_name")
    )
    sg_names = sg_full["skill_group_name"].astype(str).tolist()

    sg_table_html = (
        "<h3>Table (Demand vs Supply)</h3>"
        "<div id='sg-table-meta' style='font-size:12px; color:#666; margin:6px 0 10px 0;'></div>"
        "<div id='sg-table-wrap' style='overflow:auto; max-width:100%; max-height:520px; border:1px solid #e5e5e5; background:#fff; border-radius:8px'>"
        "<div id='sg-grid'></div>"
        "</div>"
    )

    if not alloc_emp.empty:
        bucket_minutes = 30  # fixed in v1 schema
        # Prefer employee metadata if present in CSV (added by outputs.py); otherwise derive from allocation rows.
        if "employee_skill_groups" in alloc_emp.columns:
            emp_skills = (
                alloc_emp[["employee_id", "employee_name", "employee_skill_groups"]]
                .drop_duplicates()
                .reset_index(drop=True)
            )
        else:
            emp_skills = (
                alloc_emp.groupby(["employee_id", "employee_name"])["skill_group_name"]
                .apply(lambda s: ", ".join(sorted({str(x) for x in s.dropna().tolist()})))
                .reset_index()
                .rename(columns={"skill_group_name": "employee_skill_groups"})
            )
        if "employment_group_name" in alloc_emp.columns:
            emp_skills = emp_skills.merge(
                alloc_emp[["employee_id", "employee_name", "employment_group_name"]].drop_duplicates(),
                on=["employee_id", "employee_name"],
                how="left",
            )
        else:
            emp_skills["employment_group_name"] = ""

        alloc_emp["dt_start"] = pd.to_datetime(alloc_emp["date"].astype(str) + " " + alloc_emp["time_local"].astype(str))
        alloc_emp["dt_end"] = alloc_emp["dt_start"] + pd.to_timedelta(bucket_minutes, unit="m")
        alloc_emp = alloc_emp.sort_values(["employee_name", "dt_start"])

        seg_rows = []
        for (emp_id, day), sub in alloc_emp.groupby(["employee_id", "day_index"], as_index=False):
            sub = sub.sort_values("bucket_index")
            cur = None
            for _, r in sub.iterrows():
                sg = r["skill_group_name"]
                b = int(r["bucket_index"])
                if cur is None:
                    cur = {
                        "employee_id": r["employee_id"],
                        "employee_name": r["employee_name"],
                        "skill_group_name": sg,
                        "start": r["dt_start"],
                        "end": r["dt_end"],
                        "day_index": int(r["day_index"]),
                        "date": r["date"],
                        "start_bucket": b,
                        "end_bucket": b + 1,
                    }
                    continue
                if sg == cur["skill_group_name"] and b == cur["end_bucket"]:
                    cur["end"] = r["dt_end"]
                    cur["end_bucket"] = b + 1
                else:
                    seg_rows.append(cur)
                    cur = {
                        "employee_id": r["employee_id"],
                        "employee_name": r["employee_name"],
                        "skill_group_name": sg,
                        "start": r["dt_start"],
                        "end": r["dt_end"],
                        "day_index": int(r["day_index"]),
                        "date": r["date"],
                        "start_bucket": b,
                        "end_bucket": b + 1,
                    }
            if cur is not None:
                seg_rows.append(cur)

        seg = pd.DataFrame(seg_rows)
        seg = seg.merge(emp_skills, on=["employee_id", "employee_name"], how="left")
        fig_tl = px.timeline(
            seg,
            x_start="start",
            x_end="end",
            y="employee_name",
            color="skill_group_name",
            title="Employee work allocation by skill group (timeline)",
            hover_data=["employment_group_name", "employee_skill_groups", "date", "day_index", "start_bucket", "end_bucket"],
        )
        fig_tl.update_yaxes(autorange="reversed", title="employee")
        # Move legend to top to maximize horizontal plot area (helps align with the table)
        fig_tl.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(r=20, t=70),
        )
        # Reduce per-employee row height for a denser timeline
        fig_tl.update_layout(height=max(420, 22 * seg["employee_name"].nunique() + 140))
        # Make x-axis readable at different zoom levels:
        # - zoomed in: show HH:MM buckets
        # - zoomed out: show dates
        fig_tl.update_xaxes(
            title="datetime (local)",
            showgrid=False,
            zeroline=False,
            tickformatstops=[
                {"dtickrange": [None, 60 * 60 * 1000], "value": "%H:%M"},
                {"dtickrange": [60 * 60 * 1000, 24 * 60 * 60 * 1000], "value": "%H:%M"},
                {"dtickrange": [24 * 60 * 60 * 1000, 7 * 24 * 60 * 60 * 1000], "value": "%m-%d"},
                {"dtickrange": [7 * 24 * 60 * 60 * 1000, None], "value": "%Y-%m-%d"},
            ],
        )
        figs.append(fig_tl)

    # Write single HTML
    dt_min = cov["dt"].min() if cov["dt"].notna().any() else None
    dt_max = cov["dt"].max() if cov["dt"].notna().any() else None
    # Date-only bounds for filters
    d_min = dt_min.date() if dt_min is not None and not pd.isna(dt_min) else None
    d_max = dt_max.date() if dt_max is not None and not pd.isna(dt_max) else None
    d_min_str = d_min.strftime("%Y-%m-%d") if d_min is not None else ""
    d_max_str = d_max.strftime("%Y-%m-%d") if d_max is not None else ""
    d_min_label = d_min.strftime("%Y-%m-%d") if d_min is not None else "n/a"
    d_max_label = d_max.strftime("%Y-%m-%d") if d_max is not None else "n/a"

    controls_html = f"""
<div style="display:flex; gap:12px; align-items:flex-end; flex-wrap:wrap; padding:12px; border:1px solid #e5e5e5; background:#fafafa; border-radius:8px; margin:12px 0;">
  <div style="display:flex; flex-direction:column; gap:6px;">
    <div style="font-size:12px; color:#444;">Start date</div>
    <input id="filter-start" type="date" value="" min="{d_min_str}" max="{d_max_str}" style="padding:6px 8px; border:1px solid #ccc; border-radius:6px;">
  </div>
  <div style="display:flex; flex-direction:column; gap:6px;">
    <div style="font-size:12px; color:#444;">End date</div>
    <input id="filter-end" type="date" value="" min="{d_min_str}" max="{d_max_str}" style="padding:6px 8px; border:1px solid #ccc; border-radius:6px;">
  </div>
  <div style="display:flex; gap:8px; align-items:center;">
    <button id="filter-apply" style="padding:7px 10px; border:1px solid #444; background:#fff; border-radius:6px; cursor:pointer;">Apply</button>
    <button id="filter-reset" style="padding:7px 10px; border:1px solid #ccc; background:#fff; border-radius:6px; cursor:pointer;">Reset (full range)</button>
  </div>
  <div style="font-size:12px; color:#666; margin-left:auto;">
    Full range: <code>{d_min_label}</code> → <code>{d_max_label}</code>
  </div>
</div>
"""
    header = "".join(
        [
            "<html><head><meta charset='utf-8'/>",
            f"<title>{title}</title>",
            "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:18px}</style>",
            "</head><body>",
            f"<h2>{title}</h2>",
            f"<p>Coverage: <code>{coverage_csv.as_posix()}</code><br/>EmployeeAllocation: <code>{employee_allocation_csv.as_posix()}</code></p>",
            controls_html,
            "<hr/>",
        ]
    )
    body = []
    plotly_config = {"scrollZoom": True, "displaylogo": False}
    fig_div_ids: list[str] = []
    for i, fig in enumerate(figs):
        div_id = f"fig-{i}"
        fig_div_ids.append(div_id)
        # Insert skill-group summary table just above the employee allocation timeline (last figure).
        if i == len(figs) - 1:
            body.append(sg_table_html)
        body.append(pio.to_html(fig, include_plotlyjs="cdn", full_html=False, config=plotly_config, div_id=div_id))
        body.append("<hr/>")

    # Sync x-axis zoom across all figures (line charts + employee allocation timeline)
    # - When you zoom/pan/reset on one figure, all others follow the same x-range.
    # - We only sync x-axis range/autorange; y-axis stays independent.
    if len(fig_div_ids) >= 2:
        emp_meta = {}
        if not alloc_emp.empty and {"employee_name", "employee_skill_groups", "employment_group_name"}.issubset(
            set(alloc_emp.columns)
        ):
            meta_df = (
                alloc_emp[["employee_name", "employee_skill_groups", "employment_group_name"]]
                .drop_duplicates()
                .sort_values("employee_name")
            )
            emp_meta = {
                str(r["employee_name"]): {
                    "skills": str(r.get("employee_skill_groups", "") or ""),
                    "employment": str(r.get("employment_group_name", "") or ""),
                }
                for _, r in meta_df.iterrows()
            }

        sync_js = f"""
<script>
(function() {{
  const figIds = {fig_div_ids!r};
  const skillGroups = {json.dumps(sg_names)};
  const covPoints = {cov_sg.to_json(orient="records")};
  const employeeMeta = {json.dumps(emp_meta)};
  let globalSyncing = false;
  let tableTimer = null;
  const timelineId = figIds[figIds.length - 1]; // last fig is the employee timeline

  // Precompute dt ticks (ISO strings sort correctly) and a fast lookup map for table rendering
  const dtTicks = Array.from(new Set(covPoints.map(p => p.dt))).sort();
  function toMs(v) {{
    if (v == null) return null;
    if (typeof v === "number") return v;
    if (v instanceof Date) {{
      const t = v.getTime();
      return isNaN(t) ? null : t;
    }}
    if (typeof v === "string") {{
      let s = v.trim();
      // Plotly can emit "YYYY-MM-DD HH:MM:SS" (space). Some browsers don't parse it reliably.
      if (/^\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}/.test(s)) {{
        s = s.replace(" ", "T");
      }}
      // If missing seconds, add ":00"
      if (/^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}$/.test(s)) {{
        s = s + ":00";
      }}
      // Trim milliseconds if present
      s = s.replace(/\\.\\d+/, "");
      const t = Date.parse(s);
      return isNaN(t) ? null : t;
    }}
    try {{
      const t = new Date(v).getTime();
      return isNaN(t) ? null : t;
    }} catch (e) {{
      return null;
    }}
  }}
  const dtTickMs = dtTicks.map(dt => toMs(dt));
  // Map canonical bucket start (ms) -> canonical dt string from the dataset.
  const msToDt = new Map();
  for (let i = 0; i < dtTicks.length; i++) {{
    const t = dtTickMs[i];
    if (t != null) msToDt.set(t, dtTicks[i]);
  }}
  const cellKey = (sg, dt) => sg + "||" + dt;
  const cellMap = new Map();
  for (const p of covPoints) {{
    cellMap.set(cellKey(p.skill_group_name, p.dt), p);
  }}

  // Precompute daily aggregates per (date, skill_group)
  const dayKey = (sg, d) => sg + "||" + d;
  const dayMap = new Map();
  const days = Array.from(new Set(covPoints.map(p => String(p.dt).slice(0,10)))).sort();
  for (const p of covPoints) {{
    const d = String(p.dt).slice(0,10);
    const k = dayKey(p.skill_group_name, d);
    const cur = dayMap.get(k) || {{required: 0, allocated: 0}};
    cur.required += (p.required || 0);
    cur.allocated += (p.allocated || 0);
    dayMap.set(k, cur);
  }}

  function getRange(ev) {{
    const r0 = ev["xaxis.range[0]"] ?? (Array.isArray(ev["xaxis.range"]) ? ev["xaxis.range"][0] : null);
    const r1 = ev["xaxis.range[1]"] ?? (Array.isArray(ev["xaxis.range"]) ? ev["xaxis.range"][1] : null);
    return (r0 != null && r1 != null) ? [r0, r1] : null;
  }}

  function isZoomRelayout(ev) {{
    if (!ev) return false;
    return (
      ("xaxis.autorange" in ev) ||
      ("xaxis.range[0]" in ev) ||
      ("xaxis.range[1]" in ev) ||
      ("xaxis.range" in ev)
    );
  }}

  function syncTableLabelWidthFromTimeline() {{
    const gd = document.getElementById(timelineId);
    if (!gd || !gd._fullLayout || !gd._fullLayout._size) return;
    const l = gd._fullLayout._size.l;
    if (typeof l === "number" && isFinite(l) && l > 0) {{
      document.documentElement.style.setProperty("--sg-label-w", l + "px");
    }}
  }}

  function applyEmployeeAxisTooltips() {{
    const gd = document.getElementById(timelineId);
    if (!gd) return;
    // Plotly renders y-axis tick labels as SVG <text> nodes
    const nodes = gd.querySelectorAll(".yaxislayer-above text, .yaxislayer-above tspan");
    for (const n of nodes) {{
      const name = (n.textContent || "").trim();
      if (!name) continue;
      const meta = employeeMeta[name];
      if (!meta) continue;
      const skills = meta.skills || "";
      const emp = meta.employment || "";
      const tip = "Skills: " + skills + (emp ? ("\\nEmployment: " + emp) : "");
      // Ensure SVG tooltip works: add/replace <title>
      const el = (n.nodeName.toLowerCase() === "tspan") ? n.parentElement : n;
      if (!el) continue;
      el.style.cursor = "help";
      // remove any existing title children
      const existing = el.querySelectorAll("title");
      existing.forEach(t => t.remove());
      const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
      t.textContent = tip;
      el.appendChild(t);
    }}
  }}

  function renderSkillGrid(range) {{
    const container = document.getElementById("sg-grid");
    const meta = document.getElementById("sg-table-meta");
    if (!container) return;

    let startMs = null;
    let endMs = null;
    if (range && range.length === 2) {{
      const s = toMs(range[0]);
      const e = toMs(range[1]);
      if (s != null && e != null) {{
        startMs = s;
        endMs = e;
      }}
    }}

    const isFullRange = (startMs == null || endMs == null);
    const spanDays = (!isFullRange) ? Math.abs(endMs - startMs) / 86400000.0 : 1e9;
    const mode = (isFullRange || spanDays > 3.0) ? "day" : "interval";

    if (meta) {{
      meta.textContent =
        mode === "day"
          ? "Showing daily columns (zoom in to see 30-minute columns)."
          : "Showing 30-minute columns (same resolution as charts).";
    }}

    // Columns are derived from the current visible x-range (snapped to bucket boundaries),
    // so they truly match the chart/timeline x-axis window.
    const bucketMs = 30 * 60 * 1000;
    function pad2(n) {{ return String(n).padStart(2, "0"); }}
    function toLocalIsoNoTz(d) {{
      return (
        d.getFullYear()
        + "-" + pad2(d.getMonth() + 1)
        + "-" + pad2(d.getDate())
        + "T" + pad2(d.getHours())
        + ":" + pad2(d.getMinutes())
        + ":" + pad2(d.getSeconds())
      );
    }}
    function toLocalDateStr(d) {{
      return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
    }}
    function floorToBucket(ms) {{
      const d = new Date(ms);
      d.setSeconds(0, 0);
      const m = d.getMinutes();
      const floorm = m - (m % 30);
      d.setMinutes(floorm);
      return d;
    }}

    // If we don't have an explicit range, use full data bounds.
    if (isFullRange) {{
      const lo = dtTicks.length ? toMs(dtTicks[0]) : null;
      const hi = dtTicks.length ? toMs(dtTicks[dtTicks.length - 1]) : null;
      if (lo != null && hi != null) {{
        startMs = lo;
        endMs = hi;
      }}
    }}

    const cols = [];
    if (mode === "day") {{
      // Daily columns from start date to end date inclusive
      const startD = new Date(startMs);
      const endD = new Date(endMs);
      startD.setHours(0, 0, 0, 0);
      endD.setHours(0, 0, 0, 0);
      for (let d = new Date(startD); d.getTime() <= endD.getTime(); d = new Date(d.getTime() + 86400000)) {{
        cols.push(toLocalDateStr(d));
      }}
    }} else {{
      // 30-minute bucket columns snapped to visible window using canonical bucket starts.
      // We treat the visible range as half-open: [start, end). If end lands on a bucket boundary
      // (e.g. 18:00), we exclude the 18:00 bucket so 17:30–18:00 maps to the 17:30 column.
      const startBucketMs = floorToBucket(startMs).getTime();
      const endExclusiveMs = (endMs % bucketMs === 0) ? (endMs - 1) : endMs;
      const endBucketMs = floorToBucket(endExclusiveMs).getTime();
      for (let t = startBucketMs; t <= endBucketMs; t += bucketMs) {{
        // Prefer canonical dt strings from the dataset to avoid any parsing/format drift.
        const dt = msToDt.get(t) || toLocalIsoNoTz(new Date(t));
        cols.push(dt);
      }}
    }}

    if (cols.length === 0) {{
      container.innerHTML = "<div style='padding:10px; font-size:12px; color:#666;'>No data in selected range.</div>";
      return;
    }}

    const fmtInt = (v) => String(Math.round(v || 0));
    // Column header formatting:
    // - day mode: MM-DD
    // - interval mode: HH:MM for single-day views; MM-DD HH:MM if multiple days are present
    const multiDay = (mode === "interval") && (new Set(cols.map(c => c.slice(0,10))).size > 1);
    const fmtColLabel = (c) => {{
      if (mode === "day") {{
        return c.slice(5, 10); // MM-DD
      }}
      if (multiDay) {{
        return c.slice(5, 16).replace("T", " "); // MM-DD HH:MM
      }}
      return c.slice(11, 16); // HH:MM
    }};

    let html = "";
    html += "<table style='border-collapse:collapse; font-size:12px; width:max-content;'>";
    html += "<thead><tr>";
    html += "<th style='position:sticky; left:0; z-index:4; background:#fafafa; border-bottom:1px solid #eee; text-align:left; padding:8px; white-space:nowrap; min-width:var(--sg-label-w, 180px); max-width:var(--sg-label-w, 180px);'>skill_group · metric</th>";
    for (const c of cols) {{
      html += "<th style='background:#fafafa; border-bottom:1px solid #eee; text-align:right; padding:8px; white-space:nowrap; font-variant-numeric:tabular-nums;'>" + fmtColLabel(c) + "</th>";
    }}
    html += "</tr></thead>";
    html += "<tbody>";

    const metrics = [
      ["required", "required"],
      ["allocated", "allocated"],
    ];

    for (const sg of skillGroups) {{
      for (const [key, label] of metrics) {{
        html += "<tr>";
        html += "<td style='position:sticky; left:0; z-index:3; background:#fff; border-bottom:1px solid #f1f1f1; padding:8px; white-space:nowrap; min-width:var(--sg-label-w, 180px); max-width:var(--sg-label-w, 180px); overflow:hidden; text-overflow:ellipsis;'>";
        html += "<span style='font-weight:600;'>" + sg + "</span><span style='color:#666;'> · " + label + "</span>";
        html += "</td>";
        for (const c of cols) {{
          let p = null;
          if (mode === "day") {{
            p = dayMap.get(dayKey(sg, c));
          }} else {{
            p = cellMap.get(cellKey(sg, c));
          }}
          const req = p ? (p.required || 0) : 0;
          const alloc = p ? (p.allocated || 0) : 0;
          const v = p ? p[key] : 0;
          // Highlighting rules:
          // - allocated < required => light red on allocated row
          // - overstaff > 0 => light green on overstaff row
          const allocUnderBg = (key === "allocated" && alloc < req) ? " background:#ffe5e5;" : "";
          html += "<td style='border-bottom:1px solid #f1f1f1; text-align:right; padding:8px; white-space:nowrap; font-variant-numeric:tabular-nums;" + allocUnderBg + "'>" + fmtInt(v) + "</td>";
        }}
        html += "</tr>";
      }}
    }}

    html += "</tbody></table>";
    container.innerHTML = html;
  }}

  function scheduleTableUpdate(ev) {{
    if (!isZoomRelayout(ev)) return;
    if (tableTimer) clearTimeout(tableTimer);
    tableTimer = setTimeout(() => {{
      if (ev["xaxis.autorange"] === true) {{
        renderSkillGrid(null);
      }} else {{
        const rng = getRange(ev);
        if (rng) renderSkillGrid(rng);
      }}
    }}, 50);
  }}

  function syncFrom(sourceId, ev) {{
    if (globalSyncing) return;
    if (!isZoomRelayout(ev)) return;

    const sourceGd = document.getElementById(sourceId);
    if (sourceGd && sourceGd.__syncing) return;

    const update = {{}};
    if (ev["xaxis.autorange"] === true) {{
      update["xaxis.autorange"] = true;
    }} else {{
      const rng = getRange(ev);
      if (!rng) return;
      update["xaxis.range"] = rng;
      update["xaxis.autorange"] = false;
    }}

    globalSyncing = true;
    const promises = [];
    for (const id of figIds) {{
      if (id === sourceId) continue;
      const gd = document.getElementById(id);
      if (!gd) continue;
      gd.__syncing = true;
      try {{
        const p = Plotly.relayout(gd, update);
        if (p && typeof p.then === "function") {{
          promises.push(
            p.then(
              () => {{ gd.__syncing = false; }},
              () => {{ gd.__syncing = false; }}
            )
          );
        }} else {{
          gd.__syncing = false;
        }}
      }} catch (e) {{
        gd.__syncing = false;
      }}
    }}
    Promise.all(promises).then(
      () => {{ globalSyncing = false; }},
      () => {{ globalSyncing = false; }}
    );
  }}

  for (const id of figIds) {{
    const gd = document.getElementById(id);
    if (!gd) continue;
    gd.__syncing = false;
    gd.on("plotly_relayout", (ev) => syncFrom(id, ev));
    gd.on("plotly_relayout", (ev) => scheduleTableUpdate(ev));
    // Re-apply y-axis tick tooltips when timeline re-renders ticks
    if (id === timelineId) {{
      gd.on("plotly_relayout", () => setTimeout(applyEmployeeAxisTooltips, 0));
    }}
  }}

  // Keep the table aligned to the Plotly plot area (y-axis label margin can vary).
  const tl = document.getElementById(timelineId);
  if (tl) {{
    try {{
      tl.on("plotly_afterplot", () => syncTableLabelWidthFromTimeline());
      tl.on("plotly_afterplot", () => applyEmployeeAxisTooltips());
    }} catch (e) {{}}
  }}
  window.addEventListener("resize", () => setTimeout(syncTableLabelWidthFromTimeline, 0));

  // Initial render
  setTimeout(() => {{
    syncTableLabelWidthFromTimeline();
    renderSkillGrid(null);
  }}, 0);
}})();
</script>
"""
        body.append(sync_js)

        # Date range filter controls: apply/reset by relayouting the first chart; sync JS propagates.
        filter_js = f"""
<script>
(function() {{
  const figIds = {fig_div_ids!r};
  const primaryId = figIds[0];
  const startEl = document.getElementById("filter-start");
  const endEl = document.getElementById("filter-end");
  const applyBtn = document.getElementById("filter-apply");
  const resetBtn = document.getElementById("filter-reset");

  function relayoutPrimary(update) {{
    const gd = document.getElementById(primaryId);
    if (!gd) return;
    try {{
      Plotly.relayout(gd, update);
    }} catch (e) {{}}
  }}

  applyBtn?.addEventListener("click", () => {{
    const s = startEl?.value; // YYYY-MM-DD
    const e = endEl?.value;   // YYYY-MM-DD
    if (!s || !e) {{
      alert("Please set both start and end date.");
      return;
    }}
    if (s > e) {{
      alert("Start must be <= End.");
      return;
    }}
    // Expand to full-day datetime range for the Plotly x-axis
    const startDt = s + "T00:00";
    const endDt = e + "T23:59";
    relayoutPrimary({{"xaxis.range": [startDt, endDt], "xaxis.autorange": false}});
  }});

  resetBtn?.addEventListener("click", () => {{
    relayoutPrimary({{"xaxis.autorange": true}});
  }});
}})();
</script>
"""
        body.append(filter_js)
    footer = "</body></html>"
    out_html.write_text(header + "\n".join(body) + footer, encoding="utf-8")
    return out_html

