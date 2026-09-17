#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest-snob>=0.1.14",
# ]
# ///
"""Minimal reproduction: what an import graph sees in a Django project, and what it misses.

Run it from this directory. For each file in the fixture it prints the tests Snob's
import graph selects, the tests the Django edge map adds, and the tests that actually
fail when the file's behavior changes (recorded from the mutation runs described in the
write-up, so the table reads as a comparison without re-running pytest here).

    tools/django_edges/fixture/demo.py            # selection only
    tools/django_edges/fixture/demo.py --mutate   # also re-run the mutations

Regenerate the edge map first, from the repository root:

    python tools/django_edges/extract.py --out /tmp/fixture_edges.json \
        --root tools/django_edges/fixture --settings settings --source-roots .
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent
EDGE_PATH = FIXTURE_ROOT / "edges.json"
# The mutation runs need Django and pytest-django, which live in the repository's
# virtualenv. This script itself runs under uv with only `snob_lib`.
REPO_VENV_PYTHON = FIXTURE_ROOT.parents[2] / ".venv" / "bin" / "python"

# The behavior change `--mutate` applies to each file, chosen so that at least one test
# asserts the difference.
MUTATIONS = {
    "shop/receivers.py": (
        "order_total(instance.quantity, instance.unit_price)",
        "order_total(instance.quantity, instance.unit_price) * 2",
    ),
    "shop/pricing.py": ("total = quantity * unit_price", "total = quantity * unit_price + 1"),
    "shop/views.py": ('{"total": order_total', '{"amount": order_total'),
    "shop/apps.py": ("from shop import receivers  # noqa: F401, PLC0415", "pass"),
    "urls.py": ("orders/<int:pk>/summary/", "orders/<int:pk>/total/"),
    "settings.py": ("SHOP_BULK_DISCOUNT_THRESHOLD = 10", "SHOP_BULK_DISCOUNT_THRESHOLD = 100"),
}

FILES = (
    "shop/models.py",
    "shop/receivers.py",
    "shop/views.py",
    "shop/pricing.py",
    "shop/apps.py",
    "urls.py",
    "settings.py",
)


def snob_tests(changed: list[str]) -> set[str]:
    import snob_lib  # ty: ignore[unresolved-import]

    absolute = [str(FIXTURE_ROOT / path) for path in changed]
    return {os.path.relpath(test, FIXTURE_ROOT) for test in snob_lib.get_tests(absolute)}


def django_edge_tests(edges: dict[str, dict[str, list[str]]], changed: list[str]) -> set[str]:
    """Tests the Django edges add: URL-dispatch tests, plus Snob over the signal expansion."""
    tests: set[str] = set()
    expansion: set[str] = set()
    for path in changed:
        tests.update(edges.get("view_file_to_tests", {}).get(path, []))
        expansion.update(edges.get("signal_neighbors", {}).get(path, []))
    if expansion:
        tests.update(snob_tests(sorted(expansion)))
    return tests


def failing_tests(path: str, interpreter: Path) -> set[str]:
    """Tests that fail once `path` behaves differently."""
    if path not in MUTATIONS:
        return set()
    source = FIXTURE_ROOT / path
    original = source.read_text()
    before, after = MUTATIONS[path]
    if original.count(before) != 1:
        raise SystemExit(f"{path}: mutation anchor {before!r} is not unique")
    with tempfile.TemporaryDirectory() as backup_dir:
        backup = Path(backup_dir) / "backup.py"
        shutil.copy(source, backup)
        source.write_text(original.replace(before, after))
        try:
            result = subprocess.run(
                [str(interpreter), "-m", "pytest", "-c", "pytest.ini", "tests", "-q", "-p", "no:cacheprovider"],
                cwd=FIXTURE_ROOT,
                capture_output=True,
                text=True,
            )
        finally:
            shutil.copy(backup, source)
    return {
        line.split()[1].split("::", 1)[0]
        for line in result.stdout.splitlines()
        if line.startswith("FAILED") and len(line.split()) > 1
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutate", action="store_true", help="Re-run the mutations instead of skipping them")
    parser.add_argument("--python", default=None, help="Interpreter for the mutation runs (default: repo virtualenv)")
    args = parser.parse_args()

    interpreter = Path(args.python) if args.python else REPO_VENV_PYTHON
    if args.mutate and not interpreter.exists():
        raise SystemExit(f"{interpreter} is missing — pass --python with an interpreter that has Django installed")

    if not EDGE_PATH.exists():
        raise SystemExit(f"{EDGE_PATH} is missing — see this file's docstring for how to generate it")
    edges = json.loads(EDGE_PATH.read_text())

    sys.stdout.write(f"{'changed file':22s} {'snob':>6s} {'+django':>8s}  {'fails':>6s}  detail\n")
    for path in FILES:
        selected = snob_tests([path])
        added = django_edge_tests(edges, [path]) - selected
        fails = failing_tests(path, interpreter) if args.mutate else set()
        missed = fails - selected - added
        detail = []
        if added:
            detail.append("django adds " + ", ".join(sorted(added)))
        if missed:
            detail.append("STILL MISSED " + ", ".join(sorted(missed)))
        sys.stdout.write(f"{path:22s} {len(selected):6d} {len(added):8d}  {len(fails):6d}  {'; '.join(detail)}\n")


if __name__ == "__main__":
    main()
