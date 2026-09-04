"""Click entrypoint for ``lint:tach``.

tach reads one import graph for both of its checks, and the repo wants tests on only one
axis: a test must respect every product's interface, but a test importing a product's
public surface is not an architectural dependency of the product that owns the test. tach
cannot split that in ``tach.toml``, so this command runs the dependency pass with test
code excluded and the interface pass on the full graph. CI runs the same two passes.
"""

from __future__ import annotations

import sys
import subprocess

import click

# Every test spelling the repo uses. The interface pass sees all of them.
TEST_CODE_EXCLUDES = "tests,test,**/test_*.py,**/*_test.py"

PASSES: tuple[tuple[str, ...], ...] = (
    ("tach", "check", "--dependencies", "--exclude", TEST_CODE_EXCLUDES),
    ("tach", "check", "--interfaces"),
)


def run_tach_passes() -> int:
    failed = False
    for command in PASSES:
        click.echo("$ " + " ".join(command))
        # A signal-killed pass returns a negative code; anything but zero is a failure.
        failed = subprocess.run(command).returncode != 0 or failed
    return 1 if failed else 0


@click.command(
    name="lint:tach",
    help="Check module boundaries with tach: dependencies without test code, interfaces with it",
)
def cmd_lint_tach() -> None:
    sys.exit(run_tach_passes())
