"""``hogli verify``: run the cheapest checks that are enough for the current diff.

The ladder and the decision table are the ones in ``.agents/skills/verifying-changes/SKILL.md``.
Keep the two in sync.
"""

from __future__ import annotations

import sys
import subprocess
import dataclasses
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

import click
from hogli.manifest import REPO_ROOT

from hogli_commands.build import TRIGGERS as BUILD_TRIGGERS
from hogli_commands.change_detection import changed_files, matches_globs
from hogli_commands.ci_preflight import (
    _COLOR,
    _ICON,
    DIFF_CHECKS,
    DiffCheck,
    Outcome,
    Scope,
    _capability_met,
    _run_diff_check,
)
from hogli_commands.test_runner import changed_test_files


class Rung(IntEnum):
    STATIC = 1
    UNIT_TEST = 2
    OPENAPI = 3
    STORYBOOK = 4
    STACK = 5
    END_TO_END = 6


class ChangeKind(StrEnum):
    DOCS_OR_SKILLS = "docs or skills"
    CI_WORKFLOW = "CI workflow"
    MIGRATION = "migration"
    END_TO_END_TEST = "Playwright spec"
    TEST = "test"
    API_SCHEMA = "DRF serializer or viewset"
    SQL_OR_HOGQL = "SQL or HogQL"
    KEA_LOGIC = "kea logic"
    CSS = "CSS"
    REACT_COMPONENT = "React component"
    APP_WIRING = "settings, URLs or middleware"
    PURE_LOGIC = "pure logic"


@dataclass(frozen=True, kw_only=True, slots=True)
class KindRule:
    kind: ChangeKind
    globs: tuple[str, ...]
    sufficient: Rung


# First match wins, so a narrow kind sits above a broad one that shares its files.
KIND_RULES: tuple[KindRule, ...] = (
    KindRule(
        kind=ChangeKind.DOCS_OR_SKILLS,
        globs=("*.md", "*.mdx", "docs/*", ".agents/skills/*", "products/*/skills/*"),
        sufficient=Rung.STATIC,
    ),
    KindRule(kind=ChangeKind.CI_WORKFLOW, globs=(".github/workflows/*", ".github/actions/*"), sufficient=Rung.STATIC),
    KindRule(kind=ChangeKind.MIGRATION, globs=("*/migrations/*.py",), sufficient=Rung.UNIT_TEST),
    KindRule(kind=ChangeKind.END_TO_END_TEST, globs=("playwright/*",), sufficient=Rung.END_TO_END),
    KindRule(
        kind=ChangeKind.TEST,
        globs=("test_*.py", "*/test_*.py", "*.test.ts", "*.test.tsx", "*/test/*", "*/tests/*", "*/__snapshots__/*"),
        sufficient=Rung.UNIT_TEST,
    ),
    KindRule(kind=ChangeKind.API_SCHEMA, globs=BUILD_TRIGGERS["build:openapi"], sufficient=Rung.OPENAPI),
    KindRule(
        kind=ChangeKind.SQL_OR_HOGQL,
        globs=("*.sql", "posthog/hogql/*", "posthog/hogql_queries/*", "products/*/backend/hogql_queries/*"),
        sufficient=Rung.UNIT_TEST,
    ),
    KindRule(kind=ChangeKind.KEA_LOGIC, globs=("*Logic.ts", "*Logic.tsx"), sufficient=Rung.UNIT_TEST),
    KindRule(kind=ChangeKind.CSS, globs=("*.css", "*.scss"), sufficient=Rung.STORYBOOK),
    KindRule(kind=ChangeKind.REACT_COMPONENT, globs=("*.tsx",), sufficient=Rung.STORYBOOK),
    KindRule(
        kind=ChangeKind.APP_WIRING,
        globs=(
            "posthog/settings/*",
            "posthog/urls.py",
            "products/*/backend/routes.py",
            "posthog/middleware.py",
            "posthog/csp_middleware.py",
            "docker-compose*.yml",
        ),
        sufficient=Rung.STACK,
    ),
)

FALLBACK_RULE = KindRule(kind=ChangeKind.PURE_LOGIC, globs=("*",), sufficient=Rung.UNIT_TEST)

NEXT_RUNG_BY_HAND: dict[Rung, str] = {
    Rung.OPENAPI: "Run `hogli build:openapi` (needs `hogli up -d`) and commit the generated types.",
    Rung.STORYBOOK: "Render the affected stories with `pnpm storybook` and compare them before and after.",
    Rung.STACK: "Start the stack with `hogli up -d` and `hogli wait`, then exercise the change in the app.",
    Rung.END_TO_END: "Run the changed Playwright specs with `hogli test <spec>` against a running stack.",
}

STATIC_CHECK_KEYS = (
    "ruff-lint",
    "ruff-format",
    "type-check",
    "frontend-format",
    "markdown-format",
    "desktop-biome",
    "agent-biome",
    "workflow-lint",
    "migrations",
)


def _streamed(command: list[str]) -> Callable[[Scope], Outcome]:
    # Preflight keeps three lines of a failure, and the pnpm banner fills them, so the compiler
    # errors and the typecheck wrapper's recovery steps print straight to the terminal instead.
    def run(_scope: Scope) -> Outcome:
        if not _capability_met("node"):
            return "skipped", "needs node"
        returncode = subprocess.run(command, cwd=REPO_ROOT).returncode
        return ("pass", "ok") if returncode == 0 else ("fail", f"exit {returncode}, see the output above")

    return run


FRONTEND_TS = ("frontend/src/*.ts", "frontend/src/*.tsx", "products/*/frontend/*.ts", "products/*/frontend/*.tsx")

VERIFY_ONLY_CHECKS: tuple[DiffCheck, ...] = (
    DiffCheck(
        key="oxlint",
        label="frontend lint (oxlint)",
        triggers=list(FRONTEND_TS),
        verify=["pnpm", "exec", "oxlint", "--quiet"],
        requires=("node",),
        takes_files=True,
    ),
    DiffCheck(
        key="typescript",
        label="frontend typecheck (tsgo)",
        triggers=list(FRONTEND_TS),
        verify=None,
        run=_streamed(["pnpm", "--filter=@posthog/frontend", "typescript:check"]),
    ),
    DiffCheck(
        key="skills-lint",
        label="agent skill sources",
        triggers=[".agents/skills/*", "products/*/skills/*"],
        verify=["hogli", "lint:skills"],
        requires=("python-env",),
    ),
)


@dataclass(frozen=True, kw_only=True, slots=True)
class LadderPlan:
    files_by_kind: dict[ChangeKind, list[str]]
    runs_unit_tests: bool
    rungs_by_hand: tuple[Rung, ...]


def classify(path: str) -> KindRule:
    return next((rule for rule in KIND_RULES if matches_globs(path, rule.globs)), FALLBACK_RULE)


def plan_ladder(paths: Iterable[str]) -> LadderPlan:
    files_by_kind: dict[ChangeKind, list[str]] = {}
    sufficient: set[Rung] = set()
    for path in paths:
        rule = classify(path)
        files_by_kind.setdefault(rule.kind, []).append(path)
        sufficient.add(rule.sufficient)
    return LadderPlan(
        files_by_kind=files_by_kind,
        runs_unit_tests=any(rung >= Rung.UNIT_TEST for rung in sufficient),
        rungs_by_hand=tuple(sorted(rung for rung in sufficient if rung in NEXT_RUNG_BY_HAND)),
    )


def _static_checks(files: list[str]) -> list[DiffCheck]:
    preflight_checks = [check for check in DIFF_CHECKS if check.key in STATIC_CHECK_KEYS]
    triggered = []
    for check in [*preflight_checks, *VERIFY_ONLY_CHECKS]:
        matched = [path for path in files if matches_globs(path, check.triggers)]
        if matched:
            triggered.append(dataclasses.replace(check, matched=matched))
    return triggered


def _print_plan(plan: LadderPlan) -> None:
    for kind, paths in plan.files_by_kind.items():
        click.echo(f"   {kind}: {len(paths)} file(s)")
    click.echo()


def _print_rungs_by_hand(plan: LadderPlan, outstanding: tuple[str, ...] = ()) -> None:
    covered = "Lint, format, typecheck and the nearest tests" if plan.runs_unit_tests else "Lint, format and typecheck"
    if outstanding:
        click.secho("  This diff is not verified yet. Do these, then run `hogli verify --changed` again:", fg="yellow")
        for step in outstanding:
            click.echo(f"   - {step}")
    if not plan.rungs_by_hand:
        if not outstanding:
            click.secho(f"  {covered} are enough for this diff. Higher rungs add no coverage.", fg="green")
        return
    click.secho(f"  {covered} are not enough for this diff. Run these next, cheapest first:", bold=True)
    for rung in plan.rungs_by_hand:
        click.echo(f"   {rung.value}. {NEXT_RUNG_BY_HAND[rung]}")


@click.command(name="verify", help="Run the cheapest checks that cover your diff, then name the next rung to run.")
@click.option("--changed", is_flag=True, help="Verify the files changed on this branch, plus uncommitted work.")
@click.option("--plan", "plan_only", is_flag=True, help="Show how the diff is classified without running checks.")
def verify(changed: bool, plan_only: bool) -> None:
    if not changed:
        raise click.UsageError("Pass --changed to verify the files changed on this branch.")
    files = changed_files()
    if not files:
        click.secho("No changed files on this branch.", fg="yellow")
        return
    plan = plan_ladder(files)
    click.secho(f"\n  hogli verify: {len(files)} changed file(s)\n", bold=True)
    _print_plan(plan)
    if plan_only:
        _print_rungs_by_hand(plan)
        return

    click.secho("  Rung 1: lint, format, typecheck", bold=True)
    failures = 0
    outstanding: list[str] = []
    for check in _static_checks(files):
        status, detail = _run_diff_check(check, do_fix=False, against=None, strict=False, changed=files)
        failures += status == "fail"
        if status == "skipped":
            outstanding.append(f"[{check.key}] was skipped: {detail}. Set up what it needs.")
        elif status == "advisory":
            outstanding.append(f"[{check.key}] did not run: {detail}.")
        click.secho(f"   {_ICON[status]} [{check.key}] {check.label}", fg=_COLOR[status])
        click.echo(f"       {detail}")
    click.echo()
    if failures:
        click.secho("  Fix the failures above, then run `hogli verify --changed` again.", fg="red")
        sys.exit(1)

    if plan.runs_unit_tests and not changed_test_files(skip_playwright=True).all_files:
        outstanding.append(
            "No tests were found for the changed files. Pick the nearest test and run `hogli test <file>`."
        )
    elif plan.runs_unit_tests:
        click.secho("  Rung 2: hogli test --changed --skip-playwright", bold=True)
        test_command = [sys.executable, "-m", "hogli", "test", "--changed", "--skip-playwright"]
        if subprocess.run(test_command, cwd=REPO_ROOT).returncode != 0:
            click.secho("\n  Tests failed. Fix them before you climb to a higher rung.", fg="red")
            sys.exit(1)
        click.echo()

    _print_rungs_by_hand(plan, tuple(outstanding))
