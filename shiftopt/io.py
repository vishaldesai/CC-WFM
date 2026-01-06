from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str


def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(schema_path: str | Path) -> Dict[str, Any]:
    return load_json(schema_path)


def validate_input(data: Dict[str, Any], schema: Dict[str, Any]) -> ValidationResult:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if not errors:
        return ValidationResult(ok=True, message="OK")

    # Show first ~10 errors with paths for usability
    lines = []
    for e in errors[:10]:
        path = "$"
        for part in e.path:
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                path += f".{part}"
        lines.append(f"- {path}: {e.message}")
    if len(errors) > 10:
        lines.append(f"- ... and {len(errors) - 10} more")

    return ValidationResult(ok=False, message="Schema validation failed:\n" + "\n".join(lines))

