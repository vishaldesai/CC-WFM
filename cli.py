from __future__ import annotations

import argparse
import json
from pathlib import Path

from shiftopt.solve import solve_file
from shiftopt.outputs import write_outputs
from shiftopt.io import load_json
from shiftopt.viz import write_html_report


def main() -> None:
    ap = argparse.ArgumentParser(description="ShiftOpt v1 (PuLP) - follow-demand shift scheduling")
    ap.add_argument("--input", required=True, help="Path to input JSON")
    ap.add_argument("--schema", default="schemas/shiftopt.input.schema.json", help="Path to JSON schema")
    ap.add_argument("--out", default="output", help="Output directory")
    ap.add_argument("--quiet", action="store_true", help="Suppress solver output")
    ap.add_argument("--no-viz", action="store_true", help="Skip HTML visualization report")
    ap.add_argument("--viz-day", type=int, default=0, help="Day index to plot in the line chart section")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sol = solve_file(args.input, schema_path=args.schema, msg=not args.quiet)
    input_data = load_json(args.input)

    paths = write_outputs(input_data=input_data, solution=sol, out_dir=out_dir)
    print(f"Wrote {paths.solution_json}")
    print(f"Wrote {paths.assignments_csv}")
    print(f"Wrote {paths.coverage_csv}")
    print(f"Wrote {paths.understaff_csv}")
    print(f"Wrote {paths.kpis_json}")

    if not args.no_viz:
        report = write_html_report(
            coverage_csv=paths.coverage_csv,
            employee_allocation_csv=paths.employee_allocation_csv,
            out_html=out_dir / "report.html",
            day_index=args.viz_day,
        )
        print(f"Wrote {report}")

    print(
        f"Status: {sol.get('status')}, objective={sol.get('objective_value')}, total_understaff={sol.get('total_understaff')}"
    )


if __name__ == "__main__":
    main()

