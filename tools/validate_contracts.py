from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "python"))

from vea_contracts import load_schema, validate_contract  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402


def main() -> int:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    fixtures = json.loads((ROOT / "contracts" / "examples" / "contracts-v1.json").read_text(encoding="utf-8"))
    expected = set(schema["$defs"])
    if set(fixtures) != expected:
        print(f"contract fixture mismatch: missing={sorted(expected - set(fixtures))}, extra={sorted(set(fixtures) - expected)}")
        return 1
    failures = []
    for kind, value in fixtures.items():
        try:
            validate_contract(kind, value)
        except ValueError as error:
            failures.append(f"{kind}: {error}")
    if failures:
        print("contract validation: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print(f"contract validation: PASS ({len(fixtures)} contract definitions and fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
