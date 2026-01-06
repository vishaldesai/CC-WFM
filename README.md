# ShiftOpt (PuLP) — Contact Center Shift Scheduling Optimizer

This repo takes a JSON input (see `input/SCHEMA.md`) and solves a shift scheduling / allocation problem using PuLP + CBC, producing CSV/JSON outputs and an HTML report.

## Quickstart (Windows PowerShell)

### 1) Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) (Optional) Generate sample inputs

```powershell
python scripts/generate_sample_inputs.py
```

This writes:
- `input/sample_input.small.json`
- `input/sample_input.stress.json`

### 3) Run the optimizer

```powershell
python cli.py --input input/sample_input.small.json
```

Outputs are written to `output/` by default (override with `--out`).

## Common CLI options

```powershell
python cli.py --help
```

Examples:

```powershell
# Use the stress sample and keep solver output quiet
python cli.py --input input/sample_input.stress.json --quiet

# Write outputs to a custom folder
python cli.py --input input/sample_input.small.json --out output_run_1
```

