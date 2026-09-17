#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest-snob>=0.1.14",
# ]
# ///
"""Measure what Django-derived edges add to backend test selection.

Runs the existing selector twice over the same changed-file sets — once as it runs in
CI today, once with the edges from `tools/django_edges/extract.py` — and reports the
difference. Needs `snob_lib`, so it runs under the same inline-dependency environment
as the selector itself.

    tools/django_edges/measure.py --edges django_edges.json --out measurements.json

Scenario families:

`url`      one changed view file per scenario, for every file the URL resolver ties to
           at least one test. A test the resolver reaches but the selector does not is
           a miss with a framework-level explanation.
`signal`   one changed file per scenario, for every file on either side of a signal
           connection. Reports what the blanket "all API-client tests" fallback selects
           today against what the registry-derived expansion selects.
`commit`   the changed-file list of a real commit, for end-to-end numbers.
"""

from __future__ import annotations

import sys
import json
import argparse
import subprocess
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_DIR.parent
SELECTOR_PATH = TOOLS_DIR / "snob_backend_test_selection_shadow.py"


def load_selector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snob_backend_test_selection_shadow", SELECTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Measurement:
    """One changed-file set, selected both ways."""

    def __init__(self, selector: ModuleType, edges: Any, features: dict[str, Any], durations: dict[str, float]) -> None:
        self.selector = selector
        self.edges = edges
        self.features = features
        self.durations = durations
        # A scenario without a signal expansion hands Snob the same input twice, and a
        # Snob call rebuilds the whole import graph, so memoize on the input.
        self.snob_cache: dict[tuple[str, ...], dict[str, Any]] = {}

    def _snob(self, changed: list[str], expansion: list[str]) -> dict[str, Any]:
        key = tuple(sorted({*changed, *expansion}))
        if key not in self.snob_cache:
            self.snob_cache[key] = self.selector.snob_select_tests(changed, expansion)
        return self.snob_cache[key]

    def _select(self, changed: list[str], with_edges: bool) -> dict[str, Any]:
        edges = self.edges if with_edges else None
        ast_selection = self.selector.ast_select_tests(changed, self.features, edges)
        expansion = edges.signal_expansion(changed) if edges else []
        snob = self._snob(changed, expansion)
        tests = set(snob.get("tests", [])) | set(ast_selection.tests)
        return {
            "tests": tests,
            "groups": {name: len(items) for name, items in ast_selection.groups.items()},
            "snob_count": snob.get("count", 0),
            "expansion": expansion,
            "full_run_reasons": ast_selection.full_run_reasons,
            "seconds": self.selector.estimate_duration(sorted(tests), self.durations),
        }

    def run(self, name: str, changed: list[str]) -> dict[str, Any]:
        before = self._select(changed, with_edges=False)
        after = self._select(changed, with_edges=True)
        expected_from_urls = {test for path in changed for test in self.edges.tests_reaching_view(path)}
        return {
            "scenario": name,
            "changed_files": changed,
            "before_count": len(before["tests"]),
            "after_count": len(after["tests"]),
            "added": sorted(after["tests"] - before["tests"]),
            "dropped": sorted(before["tests"] - after["tests"]),
            "url_edge_tests": len(expected_from_urls),
            "url_edge_tests_missed_before": sorted(expected_from_urls - before["tests"]),
            "signal_expansion": after["expansion"],
            "before_seconds": round(before["seconds"]),
            "after_seconds": round(after["seconds"]),
            "before_groups": before["groups"],
            "after_groups": after["groups"],
            "full_run_before": before["full_run_reasons"],
        }


def commit_scenarios(count: int) -> list[tuple[str, list[str]]]:
    log = subprocess.run(
        ["git", "log", "--format=%H", "-n", str(count * 3), "--no-merges", "master"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    scenarios: list[tuple[str, list[str]]] = []
    for sha in log.stdout.split():
        files = subprocess.run(
            ["git", "show", "--pretty=format:", "--name-only", sha],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        python_files = [f for f in files if f.endswith(".py")]
        if not python_files or len(files) > 50:
            continue
        scenarios.append((f"commit:{sha[:9]}", files))
        if len(scenarios) >= count:
            break
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edges", required=True, help="Edge JSON from tools/django_edges/extract.py")
    parser.add_argument("--out", required=True, help="Write the measurement JSON here")
    parser.add_argument(
        "--families",
        default="url,signal,commit",
        help="Comma-separated subset of url,signal,commit",
    )
    parser.add_argument("--commits", type=int, default=15, help="How many recent commits to replay")
    parser.add_argument("--limit", type=int, default=0, help="Cap scenarios per family (0 = no cap)")
    parser.add_argument("--files", default="", help="Comma-separated extra single-file scenarios to measure")
    args = parser.parse_args()

    families = {name.strip() for name in args.families.split(",") if name.strip()}
    selector = load_selector()
    edges = selector.DjangoEdgeMap.load(args.edges)
    features = selector.classify_tests()
    durations = selector.load_durations()
    runner = Measurement(selector, edges, features, durations)

    scenarios: list[tuple[str, list[str]]] = []
    if "url" in families:
        scenarios += [(f"url:{path}", [path]) for path in sorted(edges.view_file_to_tests)]
    if "signal" in families:
        scenarios += [(f"signal:{path}", [path]) for path in sorted(edges.signal_neighbors)]
    if "commit" in families:
        scenarios += commit_scenarios(args.commits)
    scenarios += [(f"file:{path.strip()}", [path.strip()]) for path in args.files.split(",") if path.strip()]

    if args.limit:
        capped: list[tuple[str, list[str]]] = []
        seen: dict[str, int] = {}
        for name, changed in scenarios:
            family = name.split(":", 1)[0]
            if seen.get(family, 0) >= args.limit:
                continue
            seen[family] = seen.get(family, 0) + 1
            capped.append((name, changed))
        scenarios = capped

    results = []
    for index, (name, changed) in enumerate(scenarios, start=1):
        results.append(runner.run(name, changed))
        if index % 20 == 0:
            sys.stderr.write(f"{index}/{len(scenarios)} scenarios\n")
            sys.stderr.flush()

    Path(args.out).write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n")
    sys.stderr.write(f"wrote {len(results)} scenarios to {args.out}\n")


if __name__ == "__main__":
    main()
