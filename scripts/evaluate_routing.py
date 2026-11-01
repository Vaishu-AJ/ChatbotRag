"""Run the small offline OKF route regression set without a model or database."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rag_system.config import get_settings
from rag_system.okf import search_bundle
from rag_system.pipeline import _route_kind


def main() -> int:
    root = ROOT
    suite = json.loads((root / "data/evaluations/routing_cases.json").read_text(encoding="utf-8"))
    settings = get_settings()
    failures = 0
    cases = suite["cases"]
    for case in cases:
        matches = search_bundle(case["question"], settings.okf_directory, limit=1)
        route = _route_kind(case["question"], matches)
        concept = matches[0]["metadata"]["title"] if matches else None
        passed = route == case["route"] and concept == case["concept"]
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'} route={route} concept={concept!r}: {case['question']}")
    print(f"Routing evaluation: {len(cases) - failures}/{len(cases)} passed")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
