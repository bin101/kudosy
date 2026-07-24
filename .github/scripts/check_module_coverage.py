#!/usr/bin/env python3
"""Enforce the >=90% coverage target for "pure modules" documented in CLAUDE.md.

CLAUDE.md's Testing section calls out parsers.py, effective_config.py,
decision.py, and humanizer.py as pure functions that should carry >=90%
coverage — stricter than the >=85% project-wide gate (see `pytest.ini`
options in pyproject.toml). Coverage.py has no built-in per-file threshold,
so this reads the `coverage.json` report (produced by `pytest --cov-report
json` in the same CI step) and checks each module individually — a single
low-effort module can't hide behind the other three being at 100%.

Run after `pytest --cov=kudosy --cov-report=json`, from the repo root.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_THRESHOLD = 90.0
_PURE_MODULES = [
    "src/kudosy/parsers.py",
    "src/kudosy/effective_config.py",
    "src/kudosy/decision.py",
    "src/kudosy/humanizer.py",
]


def main() -> int:
    report_path = Path("coverage.json")
    if not report_path.exists():
        print(f"ERROR: {report_path} not found — run pytest with --cov-report=json first.")
        return 1

    data = json.loads(report_path.read_text(encoding="utf-8"))
    files = data.get("files", {})

    results: dict[str, float | None] = dict.fromkeys(_PURE_MODULES)
    for raw_path, info in files.items():
        normalised = raw_path.replace("\\", "/")
        if normalised in results:
            results[normalised] = info["summary"]["percent_covered"]

    missing = [m for m, pct in results.items() if pct is None]
    if missing:
        print("ERROR: expected module(s) not found in coverage.json (renamed/moved?):")
        for m in missing:
            print(f"  - {m}")
        return 1

    failed = []
    for module, pct in results.items():
        marker = "OK" if pct >= _THRESHOLD else "FAIL"
        print(f"[{marker}] {module}: {pct:.1f}% (threshold {_THRESHOLD:.0f}%)")
        if pct < _THRESHOLD:
            failed.append(module)

    if failed:
        print(f"\nPure-module coverage gate failed for: {', '.join(failed)}")
        return 1

    print("\nPure-module coverage gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
