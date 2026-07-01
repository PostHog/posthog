"""Catch the deterministic CI failures reachable from your diff before you push.

``ci:preflight`` is the pre-push counterpart to ``ci:insights``: insights tells
you what's broken on master, preflight stops you from being the one who breaks
it. It scopes a curated set of checks to the files your branch actually touched,
each mapped to a CI failure class we've seen take master down, plus an always-on
branch-freshness check (a stale branch breaks CI on merge whatever the diff), and
is advisory by default so it never blocks a push.

    hogli ci:preflight            # report what your diff could break in CI
    hogli ci:preflight --fix      # auto-remediate what's safe, report the rest
    hogli ci:preflight --strict   # exit non-zero on any finding (for hooks/CI)
    hogli ci:preflight --against origin/master   # diff against an explicit base

``HOGLI_PREFLIGHT_DISABLED=1`` makes the command a no-op — the rollout/emergency
kill switch for the definition-of-done requirement (still emits a run event so
opt-out prevalence is measurable).

Checks declare what they need (``node`` modules, the dev ``stack``) and skip with
a note when it's absent, so the no-dependency checks always run — even on a bare
checkout or inside an agent sandbox. The agent loop is expected to run this with
``--fix`` before declaring a task done; see the ci-preflight skill.
"""

from __future__ import annotations

import os
import json
import time
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import click
from hogli import telemetry
from hogli.hooks import telemetry_property_hooks
from hogli.manifest import REPO_ROOT

from hogli_commands.build import TRIGGERS as BUILD_TRIGGERS
from hogli_commands.change_detection import changed_files, matches_globs

Requirement = Literal["node", "stack"]


@dataclass
class DiffCheck:
    """A CI failure class triggered by file globs in the diff, and how to catch it locally.
    The always-on branch-freshness check is a different shape — see ``_staleness``."""

    key: str
    label: str  # the CI failure class this intercepts
    triggers: list[str]  # fnmatch globs against changed paths (`*` spans `/`, as in build.py)
    verify: list[str] | None  # advisory command; None = guidance only (no runnable local check)
    fix: list[str] | None = None  # remediation for --fix
    requires: Requirement | None = None  # capability the check needs, else it skips
    takes_files: bool = False  # append matched files to the command
    matched: list[str] = field(default_factory=list)


# Ordered cheapest-first. Grounded in failure classes seen in `hogli ci:insights`:
# broken lockfile blocking all CI, OpenAPI drift, formatting/lint, flag sort,
# workflow-convention failures, migration conflicts.
DIFF_CHECKS: list[DiffCheck] = [
    DiffCheck(
        key="lockfile",
        label="broken pnpm-lock.yaml (blocks ALL CI)",
        triggers=["package.json", "*/package.json", "pnpm-lock.yaml"],
        verify=["pnpm", "install", "--frozen-lockfile"],
        fix=["pnpm", "install", "--no-frozen-lockfile"],
        requires="node",
    ),
    DiffCheck(
        key="ruff-lint",
        label="Python lint (ruff check)",
        triggers=["*.py"],
        verify=["ruff", "check"],
        fix=["ruff", "check", "--fix"],
        takes_files=True,
    ),
    DiffCheck(
        key="ruff-format",
        label="Python format (ruff format)",
        triggers=["*.py"],
        verify=["ruff", "format", "--check"],
        fix=["ruff", "format"],
        takes_files=True,
    ),
    DiffCheck(
        key="markdown-format",
        label="markdown formatting (oxfmt)",
        triggers=["*.md", "*.mdx"],
        # Mirrors lint-staged's `format:markdown`, which agents bypass via --no-verify.
        verify=["pnpm", "exec", "oxfmt", "--check"],
        fix=["hogli", "format:markdown"],
        requires="node",
        takes_files=True,
    ),
    DiffCheck(
        key="feature-flags",
        label="FEATURE_FLAGS not alphabetically sorted",
        triggers=["frontend/src/lib/constants.tsx"],
        verify=["hogli", "lint:feature-flags"],
        fix=["hogli", "lint:feature-flags:fix"],
    ),
    DiffCheck(
        key="workflow-lint",
        label="workflow-convention failure in .github/workflows",
        triggers=[".github/workflows/*.yml", ".github/workflows/*.yaml"],
        verify=["hogli", "lint:workflows"],
    ),
    DiffCheck(
        key="openapi",
        label="OpenAPI types out of date (frontend/MCP drift)",
        # From build.py so preflight and build:openapi can't drift on which diffs need a regen.
        triggers=list(BUILD_TRIGGERS["build:openapi"]),
        # Drift detection regenerates then diffs — needs the DB. Guidance-only here.
        verify=None,
        fix=["hogli", "build:openapi"],
        requires="stack",
    ),
    DiffCheck(
        key="migrations",
        label="migration conflict / orphaned migration",
        triggers=["*/migrations/*.py"],
        verify=["hogli", "migrations:check"],
        requires="stack",
    ),
]


def _has_node_modules() -> bool:
    return (REPO_ROOT / "node_modules" / ".pnpm").exists()


def _stack_up() -> bool:
    """Cheap probe: is local Postgres reachable? Proxy for 'dev stack is running'."""
    try:
        with socket.create_connection(("localhost", 5432), timeout=0.3):
            return True
    except OSError:
        return False


def _capability_met(req: Requirement | None) -> bool:
    if req == "node":
        return _has_node_modules()
    if req == "stack":
        return _stack_up()
    return True


Status = Literal["pass", "fail", "advisory", "skipped"]


def _run_diff_check(chk: DiffCheck, do_fix: bool) -> tuple[Status, str]:
    if do_fix and chk.fix is not None:
        cmd = list(chk.fix)
    elif chk.verify is not None:
        cmd = list(chk.verify)
    else:
        # Guidance-only: advise regardless of capability, so the hint shows on a bare checkout.
        return "advisory", f"run `{' '.join(chk.fix or [])}` and commit drift"
    if not _capability_met(chk.requires):
        return "skipped", f"needs {chk.requires}"
    if chk.takes_files:
        # Drop deleted paths: ruff (and friends) error E902 on a path that no longer exists.
        present = [f for f in chk.matched if (REPO_ROOT / f).exists()]
        if not present:
            return "skipped", "only deleted files"
        cmd += present
    if shutil.which(cmd[0]) is None:
        return "skipped", f"{cmd[0]} not found"
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        return "pass", "fixed" if do_fix else "ok"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return "fail", " · ".join(lines[:3]) if lines else f"exit {result.returncode}"


# Branch-freshness thresholds. Aggressive on purpose: master moves hundreds of
# commits/day, so a stale branch hits merge conflicts and generated-file drift.
# Advisory only (never auto-merged). Env-tunable; calibrate from telemetry.
_MASTER_REF = "origin/master"
_STALE_COMMITS_DEFAULT = 10
_STALE_DAYS_DEFAULT = 1
_FETCH_TTL_SECONDS = 600  # skip re-fetching origin/master if refreshed this recently


def _git(*args: str, timeout: float = 5.0) -> str | None:
    """Run a git command in the repo, returning trimmed stdout or None on any failure."""
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _fetch_master() -> None:
    """Refresh origin/master for an accurate behind-count, skipping the fetch if done
    recently (the agent loop reruns preflight often). Offline → keep the local ref."""
    head = _git("rev-parse", "--git-path", "FETCH_HEAD")
    if head:
        marker = Path(head) if Path(head).is_absolute() else REPO_ROOT / head
        try:
            if time.time() - marker.stat().st_mtime < _FETCH_TTL_SECONDS:
                return
        except OSError:
            pass
    _git("fetch", "--quiet", "origin", "master", timeout=10.0)


def _env_int(var: str, default: int) -> int:
    try:
        return int(os.environ.get(var, default))
    except ValueError:
        return default


def _commit_age_days(ref: str) -> int | None:
    """Whole days since *ref* was committed — how long since the branch last held master's state."""
    iso = _git("show", "-s", "--format=%cI", ref)
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0, (datetime.now(when.tzinfo) - when).days)


def _staleness() -> tuple[Status, str, dict[str, Any]]:
    """How far the branch has drifted from master, independent of the diff. On
    squash-merge master, commits behind ≈ PRs merged since the branch last synced.
    Returns (status, detail, telemetry props)."""
    _fetch_master()
    merge_base = _git("merge-base", "HEAD", _MASTER_REF)
    if not merge_base:
        return "skipped", f"no merge-base with {_MASTER_REF}", {"stale": None}

    # Commits on master we don't have = how far behind; 0 means up to date.
    count = _git("rev-list", "--count", f"{merge_base}..{_MASTER_REF}")
    behind = int(count) if count and count.isdigit() else 0
    if behind == 0:
        return "pass", "even with master", {"stale": False, "behind_commits": 0, "branch_age_days": 0}

    age_days = _commit_age_days(merge_base)  # merge-base age ≈ time since the branch last synced with master
    props: dict[str, Any] = {"stale": False, "behind_commits": behind, "branch_age_days": age_days}

    reasons: list[str] = []
    if behind >= _env_int("HOGLI_PREFLIGHT_STALE_COMMITS", _STALE_COMMITS_DEFAULT):
        reasons.append(f"{behind} commits (≈ PRs) behind")
    if age_days is not None and age_days >= _env_int("HOGLI_PREFLIGHT_STALE_DAYS", _STALE_DAYS_DEFAULT):
        reasons.append(f"last synced {age_days}d ago")
    if reasons:
        props["stale"] = True
        return "advisory", f"{' · '.join(reasons)} — merge master in: git merge {_MASTER_REF}", props

    synced = f", synced {age_days}d ago" if age_days is not None else ""
    return "pass", f"{behind} commits behind master{synced}", props


_ICON: dict[Status, str] = {"pass": "✓", "fail": "✗", "advisory": "→", "skipped": "·"}
_COLOR: dict[Status, str] = {"pass": "green", "fail": "red", "advisory": "yellow", "skipped": "bright_black"}


def _emit_telemetry(summary: dict[str, Any]) -> None:
    """Emit ``ci_preflight_run`` to measure failures intercepted locally vs. what
    would reach CI. Gated on ``is_active()`` first so an opt-out/CI run doesn't fork
    the ``gh``/``git`` property hooks for an event ``track()`` would drop anyway."""
    if not telemetry.is_active():
        return
    keys = ("changed_files", "triggered", "failures", "mode", "stale", "behind_commits", "branch_age_days")
    props: dict[str, Any] = {k: summary[k] for k in keys if k in summary}
    props["results"] = {r["check"]: r["status"] for r in summary["results"]}
    # Registries are read directly by design (see hogli.hooks). Merge the same
    # dev-context props the command lifecycle attaches to command_completed
    # (incl. git_branch, so a run ties back to its PR).
    for hook in telemetry_property_hooks:
        try:
            props.update(hook("ci:preflight"))
        except Exception:
            pass
    telemetry.track("ci_preflight_run", props)


@click.command(
    name="ci:preflight",
    help="Catch the deterministic CI failures reachable from your diff before you push.",
)
@click.option("--fix", "do_fix", is_flag=True, help="Auto-remediate what's safe instead of only reporting.")
@click.option("--strict", is_flag=True, help="Exit non-zero on any finding (for hooks/CI).")
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
@click.option("--json", "as_json", is_flag=True, help="Emit the result summary as JSON.")
def ci_preflight(do_fix: bool, strict: bool, against: str | None, as_json: bool) -> None:
    if os.environ.get("HOGLI_PREFLIGHT_DISABLED", "").lower() in {"1", "true"}:
        disabled_summary: dict[str, Any] = {"mode": "disabled", "results": []}
        if as_json:
            click.echo(json.dumps(disabled_summary))
        else:
            click.secho("  ci:preflight disabled (HOGLI_PREFLIGHT_DISABLED) — CI remains the gate.", fg="yellow")
        _emit_telemetry(disabled_summary)
        return

    files = changed_files(against or "master")
    base = against or "branch base"

    triggered: list[DiffCheck] = []
    for chk in DIFF_CHECKS:
        chk.matched = [f for f in files if matches_globs(f, chk.triggers)]
        if chk.matched:
            triggered.append(chk)

    results: list[dict[str, Any]] = []
    failures = 0
    if not as_json:
        click.secho(f"\n  ci:preflight — {len(files)} changed file(s) vs {base}\n", bold=True)

    # Always-on branch-health check, independent of which files changed: a stale
    # branch breaks CI on merge no matter what the diff touches. Advisory only —
    # it never counts toward `failures` (a merge is the human/agent's call).
    stale_status, stale_detail, stale_props = _staleness()
    results.append({"check": "staleness", "status": stale_status, "files": 0, "detail": stale_detail})
    if not as_json:
        click.secho(f"   {_ICON[stale_status]} [staleness] branch freshness vs master", fg=_COLOR[stale_status])
        click.echo(f"       {stale_detail}")

    for chk in triggered:
        status, detail = _run_diff_check(chk, do_fix)
        failures += status == "fail"
        results.append({"check": chk.key, "status": status, "files": len(chk.matched), "detail": detail})
        if not as_json:
            click.secho(f"   {_ICON[status]} [{chk.key}] {chk.label}", fg=_COLOR[status])
            click.echo(f"       {len(chk.matched)} file(s) · {detail}")

    summary = {
        "changed_files": len(files),
        "triggered": [c.key for c in triggered],
        "failures": failures,
        "mode": "fix" if do_fix else ("strict" if strict else "advisory"),
        "results": results,
        **stale_props,
    }
    if as_json:
        click.echo(json.dumps(summary))
    else:
        if not triggered:
            click.secho("   ✓ Nothing in this diff maps to a known CI failure class.", fg="green")
        click.echo()
        click.echo(
            f"  summary {json.dumps({k: summary[k] for k in ('changed_files', 'triggered', 'failures', 'mode')})}"
        )
        click.echo()

    _emit_telemetry(summary)

    # Advisory by default — only --strict turns findings into a non-zero exit so a
    # push or CI gate can act on them. SystemExit so the telemetry wrapper records it.
    raise SystemExit(1 if (strict and failures) else 0)
