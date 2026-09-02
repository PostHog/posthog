"""Cyclomatic complexity lint, scoped to changed files.

Findings above a file's limit are warnings; the check never fails a build
(advisory while the pre-existing violation backlog settles). Python goes
through ruff's C901 (repo-wide C901 stays off in pyproject.toml for the same
reason; this surfaces it for files a branch actually touches). TypeScript goes
through ``bin/lint-complexity.mjs`` because oxlint has no complexity rule.
Both sides read their limits from ``bin/lint-complexity.limits.json`` so the
two implementations cannot drift.

    hogli lint:complexity                     # changed files vs origin/master
    hogli lint:complexity path/to/file.py     # explicit files
    hogli lint:complexity --against <ref>     # explicit diff base
"""

from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass

import click
from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import changed_files, matches_globs

_LIMITS: dict[str, int] = json.loads((REPO_ROOT / "bin" / "lint-complexity.limits.json").read_text())
WARN_AT: int = _LIMITS["production"]
# NIST SP 500-235 permits relaxing the usual limit of 10 up to 15. Tests get the
# relaxed bound because table-driven tests concentrate branching in one function
# without hurting maintainability.
TEST_WARN_AT: int = _LIMITS["test"]

# The complexity-linted trees: the posthog, ee, products, and frontend folders.
# Python exclusions (products/desktop, generated grammar) come from pyproject's
# ruff excludes (force-exclude honors them for explicitly passed files); the
# TypeScript ones live in bin/lint-complexity.mjs.
PYTHON_SCOPE = ("posthog/*.py", "ee/*.py", "products/*.py")
TYPESCRIPT_SCOPE = ("frontend/*.ts", "frontend/*.tsx", "ee/*.ts", "ee/*.tsx", "products/*.ts", "products/*.tsx")

_C901_MESSAGE = re.compile(r"`(?P<name>.+)` is too complex \((?P<complexity>\d+) > \d+\)")

# A test file: named test_*.py or *_test.py (pytest's python_files default),
# conftest.py, or inside a test/tests package. The suffix rule also classifies
# clickhouse-migration and user_scripts *_test.py modules as tests — same as
# pytest, and harmless for an advisory lint. bin/lint-complexity.mjs carries
# the TypeScript equivalent; keep the two in step.
_TEST_FILE = re.compile(r"(?:^|/)(?:test|tests)/|(?:^|/)[^/]*_test\.py$|(?:^|/)test_[^/]*\.py$|(?:^|/)conftest\.py$")


def is_test_file(path: str) -> bool:
    return bool(_TEST_FILE.search(path))


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    file: str
    line: int
    column: int
    name: str
    complexity: int
    # The limit the finding exceeded: WARN_AT for production files, TEST_WARN_AT for tests.
    limit: int


def _python_findings(files: list[str], *, max_complexity: int = WARN_AT) -> list[Finding]:
    cmd = [
        "ruff",
        "check",
        "--select",
        "C901",
        # C901 sits in pyproject's lint.ignore (pre-existing violations); clear
        # the ignore list for this run — only C901 is selected anyway.
        "--config",
        "lint.ignore=[]",
        "--config",
        f"lint.mccabe.max-complexity={max_complexity}",
        "--output-format",
        "json",
        *files,
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise click.ClickException(f"ruff failed: {(result.stderr or result.stdout).strip()}")
    findings = []
    for violation in json.loads(result.stdout):
        match = _C901_MESSAGE.fullmatch(violation["message"])
        if match is None:
            continue
        findings.append(
            Finding(
                file=os.path.relpath(violation["filename"], REPO_ROOT),
                line=violation["location"]["row"],
                column=violation["location"]["column"],
                name=match["name"],
                complexity=int(match["complexity"]),
                limit=max_complexity,
            )
        )
    return findings


def _ts_findings(files: list[str]) -> list[Finding]:
    cmd = ["node", "bin/lint-complexity.mjs", "--json", *files]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise click.ClickException(f"lint-complexity.mjs failed: {result.stderr.strip()}")
    return [Finding(**item) for item in json.loads(result.stdout)]


def _report(finding: Finding) -> None:
    message = f"`{finding.name}` has cyclomatic complexity {finding.complexity} (warn >{finding.limit})"
    click.echo(f"{finding.file}:{finding.line}:{finding.column}: warning: {message}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        click.echo(
            f"::warning file={finding.file},line={finding.line},col={finding.column},title=lint:complexity::{message}"
        )


@click.command(
    name="lint:complexity", help="Check cyclomatic complexity of changed Python/TypeScript files (warn-only)."
)
@click.argument("files", nargs=-1)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
@click.option(
    "--report",
    "report_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Also write the findings as JSON to this path (used by the CI report poster).",
)
def cmd_lint_complexity(files: tuple[str, ...], against: str | None, report_path: str | None) -> None:
    paths = list(files) if files else changed_files(against)
    present = [f for f in paths if (REPO_ROOT / f).is_file()]
    python_files = [f for f in present if matches_globs(f, PYTHON_SCOPE)]
    ts_files = [f for f in present if matches_globs(f, TYPESCRIPT_SCOPE)]

    findings: list[Finding] = []
    checked = 0
    degraded = False
    if python_files:
        if shutil.which("ruff") is None:
            # Printed to stdout too: a soft preflight check treats non-empty stdout as
            # "warning", so a degraded run surfaces instead of reading as a clean pass.
            click.echo("complexity: ruff not found — skipping Python files")
            degraded = True
        else:
            # One ruff run per limit: ruff's mccabe takes a single max-complexity per invocation.
            prod_files = [f for f in python_files if not is_test_file(f)]
            test_files = [f for f in python_files if is_test_file(f)]
            if prod_files:
                findings += _python_findings(prod_files, max_complexity=WARN_AT)
            if test_files:
                findings += _python_findings(test_files, max_complexity=TEST_WARN_AT)
            checked += len(python_files)

    if ts_files:
        # typescript is a @posthog/frontend dependency; without an install the
        # script cannot resolve it, so skip like preflight's node-needing checks.
        if not (REPO_ROOT / "frontend" / "node_modules").exists():
            click.echo("complexity: no node_modules — skipping TypeScript files")
            degraded = True
        else:
            findings += _ts_findings(ts_files)
            checked += len(ts_files)

    for finding in findings:
        _report(finding)
    summary = f"complexity: {checked} file(s) checked, {len(findings)} warning(s)"
    if degraded:
        summary += " (incomplete: some files were skipped, see above)"
    click.echo(summary, err=True)
    if report_path is not None:
        with open(report_path, "w") as f:
            json.dump([asdict(finding) for finding in findings], f)
