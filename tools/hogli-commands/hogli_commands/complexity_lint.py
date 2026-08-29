"""Cyclomatic complexity lint, scoped to changed files.

Complexity 11-15 is a warning, above 15 an error — only errors exit non-zero.
Python goes through ruff's C901 (repo-wide C901 stays off in pyproject.toml
because of the existing-violation backlog; this surfaces it for files a branch
actually touches). TypeScript goes through ``bin/lint-complexity.mjs`` because
oxlint has no complexity rule.

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
from dataclasses import dataclass

import click
from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import changed_files, matches_globs

# bin/lint-complexity.mjs declares the same thresholds; a test binds the two.
WARN_AT = 10
ERROR_AT = 15

# The complexity-linted trees: the posthog, ee, products, and frontend folders.
# Python exclusions (products/desktop, generated grammar) come from pyproject's
# ruff excludes (force-exclude honors them for explicitly passed files); the
# TypeScript ones live in bin/lint-complexity.mjs.
PYTHON_SCOPE = ("posthog/*.py", "ee/*.py", "products/*.py")
TYPESCRIPT_SCOPE = ("frontend/*.ts", "frontend/*.tsx", "ee/*.ts", "ee/*.tsx", "products/*.ts", "products/*.tsx")

_C901_MESSAGE = re.compile(r"`(?P<name>.+)` is too complex \((?P<complexity>\d+) > \d+\)")


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    file: str
    line: int
    column: int
    name: str
    complexity: int

    @property
    def severity(self) -> str:
        return "error" if self.complexity > ERROR_AT else "warning"


def _python_findings(files: list[str]) -> list[Finding]:
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
        f"lint.mccabe.max-complexity={WARN_AT}",
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
    message = f"`{finding.name}` has cyclomatic complexity {finding.complexity} (warn >{WARN_AT}, error >{ERROR_AT})"
    click.echo(f"{finding.file}:{finding.line}:{finding.column} {finding.severity}: {message}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        click.echo(
            f"::{finding.severity} file={finding.file},line={finding.line},col={finding.column},"
            f"title=lint:complexity::{message}"
        )


@click.command(name="lint:complexity", help="Check cyclomatic complexity of changed Python/TypeScript files.")
@click.argument("files", nargs=-1)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
def cmd_lint_complexity(files: tuple[str, ...], against: str | None) -> None:
    paths = list(files) if files else changed_files(against)
    present = [f for f in paths if (REPO_ROOT / f).is_file()]
    python_files = [f for f in present if matches_globs(f, PYTHON_SCOPE)]
    ts_files = [f for f in present if matches_globs(f, TYPESCRIPT_SCOPE)]

    findings: list[Finding] = []
    if python_files:
        if shutil.which("ruff") is None:
            click.echo("complexity: ruff not found — skipping Python files", err=True)
        else:
            findings += _python_findings(python_files)

    if ts_files:
        # typescript is a @posthog/frontend dependency; without an install the
        # script cannot resolve it, so skip like preflight's node-needing checks.
        if not (REPO_ROOT / "frontend" / "node_modules").exists():
            click.echo("complexity: no node_modules — skipping TypeScript files", err=True)
        else:
            findings += _ts_findings(ts_files)

    for finding in findings:
        _report(finding)
    warnings = sum(f.severity == "warning" for f in findings)
    errors = sum(f.severity == "error" for f in findings)
    checked = len(python_files) + len(ts_files)
    click.echo(f"complexity: {checked} file(s) checked — {warnings} warning(s), {errors} error(s)", err=True)
    raise SystemExit(1 if errors else 0)
