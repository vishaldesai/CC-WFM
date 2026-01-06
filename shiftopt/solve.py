from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .io import load_json, load_schema, validate_input
from .model import build_and_solve


def solve_file(
    input_path: str | Path,
    *,
    schema_path: str | Path = "schemas/shiftopt.input.schema.json",
    msg: bool = True,
) -> Dict[str, Any]:
    data = load_json(input_path)
    schema = load_schema(schema_path)
    vr = validate_input(data, schema)
    if not vr.ok:
        raise ValueError(vr.message)
    return build_and_solve(data, msg=msg)

