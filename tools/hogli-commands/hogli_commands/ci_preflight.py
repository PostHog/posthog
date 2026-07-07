"""Catch the deterministic CI failures reachable from your diff before you push.

``ci:preflight`` is the pre-push counterpart to ``ci:insights``: insights tells
you what's broken on master, preflight stops you from being the one who breaks
it. It scopes a curated set of checks to the files your branch actually touched,
each mapped to a CI failure class we've seen take master down, plus an always-on
branch-freshness check that flags concrete merge risks (textual conflicts,
migration collisions, generated-file drift, CI changes on master).

    hogli ci:preflight            # report what your diff could break in CI
    hogli ci:preflight --fix      # auto-remediate what's safe, report the rest
    hogli ci:preflight --strict   # exit non-zero on failed checks (the pre-push hook)
    hogli ci:preflight --against origin/master   # diff against an explicit base

``HOGLI_PREFLIGHT_DISABLED=1`` makes the command (and thus the pre-push hook) a
no-op — the rollout/emergency kill switch (still emits a run event so opt-out
prevalence is measurable).

Checks declare what they need (``node`` modules, the dev ``stack``) and skip with
a note when it's absent, so the no-dependency checks always run — even on a bare
checkout or inside an agent sandbox. The pre-push hook runs ``--strict`` (failures
block, advisories never do); the fix loop is ``--fix`` — see the running-ci-preflight skill.
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

from hogli_commands.build import (
    TRIGGERS as BUILD_TRIGGERS,
    _match_commands,
)
from hogli_commands.change_detection import changed_files, matches_globs

Requirement = Literal["node", "stack", "clickhouse"]


@dataclass
class DiffCheck:
    """A CI failure class triggered by file globs in the diff, and how to catch it locally.
    The always-on branch-freshness check is a different shape — see ``_staleness``."""

    key: str
    label: str  # the CI failure class this intercepts
    triggers: list[str]  # fnmatch globs against changed paths (`*` spans `/`, as in build.py)
    verify: list[str] | None  # advisory command; None = guidance only (no runnable local check)
    fix: list[str] | None = None  # remediation for --fix
    requires: tuple[Requirement, ...] = ()  # capabilities the check needs, else it skips
    takes_files: bool = False  # append matched files to the command
    matched: list[str] = field(default_factory=list)


# Ordered cheapest-first. Grounded in failure classes seen in `hogli ci:insights`:
# broken lockfile blocking all CI, OpenAPI drift, formatting/lint, flag sort,
# workflow-convention failures, migration conflicts.
DIFF_CHECKS: list[DiffCheck] = [
    DiffCheck(
        key="lockfile",
        label="broken pnpm-lock.yaml (blocks ALL CI)",
        # pnpm-workspace.yaml (catalog versions) and patches/* (patchedDependencies
        # hashes) invalidate the lockfile just like a package.json edit.
        triggers=["package.json", "*/package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "patches/*"],
        # --lockfile-only validates manifest/lockfile agreement without touching node_modules.
        verify=["pnpm", "install", "--frozen-lockfile", "--lockfile-only"],
        fix=["pnpm", "install", "--no-frozen-lockfile"],
        requires=("node",),
    ),
    DiffCheck(
        key="uv-lock",
        label="uv.lock out of sync with pyproject.toml (blocks Python CI)",
        triggers=["pyproject.toml", "*/pyproject.toml", "uv.lock"],
        verify=["uv", "lock", "--check"],
        fix=["uv", "lock"],
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
        # --no-error-on-unmatched-pattern: .oxfmtrc.json ignores whole trees (rust/,
        # fixtures, ...) and oxfmt exits 2 when every given file is ignored.
        verify=["pnpm", "exec", "oxfmt", "--check", "--no-error-on-unmatched-pattern"],
        fix=["hogli", "format:markdown"],
        requires=("node",),
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
        requires=("stack",),
    ),
    DiffCheck(
        key="migrations",
        label="migration conflict / orphaned migration",
        triggers=["*/migrations/*.py"],
        # migrations:check declares both postgresql and clickhouse services.
        verify=["hogli", "migrations:check"],
        requires=("stack", "clickhouse"),
    ),
]


def _has_node_modules() -> bool:
    return (REPO_ROOT / "node_modules" / ".pnpm").exists()


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.3):
            return True
    except OSError:
        return False


def _capability_met(req: Requirement) -> bool:
    if req == "node":
        return _has_node_modules()
    if req == "stack":
        # Postgres reachable — proxy for "dev stack is running".
        return _port_open(5432)
    return _port_open(8123)  # ClickHouse HTTP


def _unmet(chk: DiffCheck) -> list[Requirement]:
    return [req for req in chk.requires if not _capability_met(req)]


Status = Literal["pass", "fail", "advisory", "skipped"]

# Generous: pnpm installs and migrations:check are legitimately slow, but a wedged
# command must not hang the agent loop forever (output is captured, not streamed).
_CHECK_TIMEOUT_SECONDS = 600


def _run_diff_check(chk: DiffCheck, do_fix: bool) -> tuple[Status, str]:
    unmet = _unmet(chk)
    if do_fix and chk.fix is not None and not unmet:
        cmd = list(chk.fix)
    elif chk.verify is None:
        # Guidance-only (no runnable local check, or its fix needs an absent capability):
        # advise regardless, so the hint still shows on a bare checkout — even with --fix.
        # Ownership framing lives once in the advisory footer, not per check.
        return "advisory", f"run `{' '.join(chk.fix or [])}` and commit before pushing"
    elif unmet:
        return "skipped", f"needs {', '.join(unmet)}"
    else:
        cmd = list(chk.verify)
    if chk.takes_files:
        # Drop deleted paths: ruff (and friends) error E902 on a path that no longer exists.
        present = [f for f in chk.matched if (REPO_ROOT / f).exists()]
        if not present:
            return "skipped", "only deleted files"
        cmd += present
    if shutil.which(cmd[0]) is None:
        return "skipped", f"{cmd[0]} not found"
    try:
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=_CHECK_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return "fail", f"`{cmd[0]}` timed out after {_CHECK_TIMEOUT_SECONDS}s"
    if result.returncode == 0:
        return "pass", "fixed" if do_fix else "ok"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return "fail", " · ".join(lines[:3]) if lines else f"exit {result.returncode}"


# Branch-freshness backstop thresholds. The risk signals in ``_staleness_risks``
# are the primary advisory trigger; these are a secondary net for branches old
# enough that generic (undetected) drift is likely. Deliberately aggressive to
# start — master moves fast and we'd rather over-warn and tune down from
# telemetry than under-warn. Advisory only (never auto-merged). Env-tunable.
_MASTER_REF = "origin/master"
_STALE_COMMITS_DEFAULT = 5
_STALE_DAYS_DEFAULT = 2
_FETCH_TTL_SECONDS = 600  # skip re-fetching origin/master if refreshed this recently


def _git_run(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str] | None:
    """Run a git command in the repo; None on OS error or timeout."""
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _git(*args: str, timeout: float = 5.0) -> str | None:
    """Like ``_git_run`` but collapses to trimmed stdout, None on any failure."""
    result = _git_run(*args, timeout=timeout)
    return result.stdout.strip() if result is not None and result.returncode == 0 else None


def _fetch_marker() -> Path | None:
    """Our own TTL marker — FETCH_HEAD won't do, since fetching *any* ref touches it."""
    raw = _git("rev-parse", "--git-path", "hogli-preflight-fetched")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / raw


def _fetch_master() -> None:
    """Refresh origin/master for an accurate diff base and behind-count, skipping the
    fetch if done recently (the agent loop reruns preflight often). Offline → keep
    the local ref."""
    marker = _fetch_marker()
    if marker is not None:
        try:
            if time.time() - marker.stat().st_mtime < _FETCH_TTL_SECONDS:
                return
        except OSError:
            pass
    if _git("fetch", "--quiet", "origin", "master", timeout=10.0) is not None and marker is not None:
        marker.touch()


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


def _merge_conflicts() -> list[str] | None:
    """Files that would conflict if master were merged right now, computed without
    touching the working tree (``git merge-tree``, git >= 2.38). None = can't tell."""
    result = _git_run("merge-tree", "--write-tree", "--name-only", "HEAD", _MASTER_REF)
    if result is None or result.returncode not in (0, 1):
        return None
    # returncode 1 = conflicts; first output line is the merged tree OID.
    return [line for line in result.stdout.splitlines()[1:] if line] if result.returncode == 1 else []


def _changed_on_master(merge_base: str) -> list[str]:
    result = _git_run("diff", "--name-only", "-z", f"{merge_base}..{_MASTER_REF}")
    if result is None or result.returncode != 0:
        return []
    return [path for path in result.stdout.split("\0") if path]


_MIGRATION_GLOB = ["*/migrations/*.py"]


def _staleness_risks(branch_files: list[str], master_files: list[str], conflicts: list[str] | None) -> list[str]:
    """Concrete ways merging master late will break this branch — each a failure
    class that recurs on unrebased PRs: textual conflicts, migration collisions,
    generated-file drift, and CI workflows changing underneath the branch."""
    risks: list[str] = []
    if conflicts:
        risks.append(f"merging master conflicts in {len(conflicts)} file(s) (e.g. {conflicts[0]})")
    branch_apps = {str(Path(f).parent) for f in branch_files if matches_globs(f, _MIGRATION_GLOB)}
    master_apps = {str(Path(f).parent) for f in master_files if matches_globs(f, _MIGRATION_GLOB)}
    collisions = sorted(branch_apps & master_apps)
    if collisions:
        risks.append(f"migrations added on both sides in {', '.join(collisions)}")
    drift = sorted(set(_match_commands(branch_files)) & set(_match_commands(master_files)))
    if drift:
        risks.append(f"master also changed {', '.join(drift)} inputs — regenerate after merging")
    workflows = sum(f.startswith(".github/workflows/") for f in master_files)
    if workflows:
        risks.append(f"CI workflows changed on master ({workflows} file(s))")
    return risks


def _staleness(branch_files: list[str]) -> tuple[Status, str, dict[str, Any]]:
    """Whether merging master *now* would break this branch. Risk signals are the
    primary advisory trigger; a raw behind-count backstop also fires, aggressively
    by default. On squash-merge master, commits behind ≈ PRs merged.
    Returns (status, detail, telemetry props)."""
    merge_base = _git("merge-base", "HEAD", _MASTER_REF)
    if not merge_base:
        return "skipped", f"no merge-base with {_MASTER_REF}", {"stale": None}

    # Commits on master we don't have = how far behind; 0 means up to date.
    # A failed/timed-out count must not read as "even with master".
    count = _git("rev-list", "--count", f"{merge_base}..{_MASTER_REF}")
    if count is None or not count.isdigit():
        return "skipped", "could not count commits behind master", {"stale": None}
    behind = int(count)
    if behind == 0:
        return "pass", "even with master", {"stale": False, "behind_commits": 0, "branch_age_days": 0}

    age_days = _commit_age_days(merge_base)  # merge-base age ≈ time since the branch last synced with master
    conflicts = _merge_conflicts()
    risks = _staleness_risks(branch_files, _changed_on_master(merge_base), conflicts)
    if behind >= _env_int("HOGLI_PREFLIGHT_STALE_COMMITS", _STALE_COMMITS_DEFAULT):
        risks.append(f"{behind} commits (≈ PRs) behind")
    elif age_days is not None and age_days >= _env_int("HOGLI_PREFLIGHT_STALE_DAYS", _STALE_DAYS_DEFAULT):
        risks.append(f"last synced {age_days}d ago")

    props: dict[str, Any] = {
        "stale": bool(risks),
        "behind_commits": behind,
        "branch_age_days": age_days,
        "merge_conflict_files": len(conflicts) if conflicts is not None else None,
        "staleness_risks": len(risks),
    }
    if risks:
        return "advisory", f"{' · '.join(risks)} — merge master in: git merge {_MASTER_REF}", props

    synced = f", synced {age_days}d ago" if age_days is not None else ""
    return "pass", f"{behind} commits behind master{synced} — no conflict or drift risk detected", props


_ICON: dict[Status, str] = {"pass": "✓", "fail": "✗", "advisory": "→", "skipped": "·"}
_COLOR: dict[Status, str] = {"pass": "green", "fail": "red", "advisory": "yellow", "skipped": "bright_black"}


def _emit_telemetry(summary: dict[str, Any]) -> None:
    """Emit ``ci_preflight_run`` to measure failures intercepted locally vs. what
    would reach CI. Gated on ``is_active()`` first so an opt-out/CI run doesn't fork
    the ``gh``/``git`` property hooks for an event ``track()`` would drop anyway."""
    if not telemetry.is_active():
        return
    keys = (
        "changed_files",
        "triggered",
        "failures",
        "advisories",
        "mode",
        "stale",
        "behind_commits",
        "branch_age_days",
        "merge_conflict_files",
        "staleness_risks",
    )
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
@click.option(
    "--strict",
    is_flag=True,
    help="Exit non-zero on any failed check (advisories never block) — for the pre-push hook.",
)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
@click.option("--json", "as_json", is_flag=True, help="Emit the result summary as JSON.")
def ci_preflight(do_fix: bool, strict: bool, against: str | None, as_json: bool) -> None:
    if os.environ.get("HOGLI_PREFLIGHT_DISABLED", "").lower() in {"1", "true"}:
        disabled_summary: dict[str, Any] = {"mode": "disabled", "results": []}
        if as_json:
            click.echo(json.dumps(disabled_summary))
        else:
            click.secho(
                "  ci:preflight disabled by operator (HOGLI_PREFLIGHT_DISABLED) — intentional; "
                "do not unset. Nothing to check, CI remains the gate.",
                fg="yellow",
            )
        _emit_telemetry(disabled_summary)
        return

    # Fetch first so both the diff base and the staleness check see a fresh
    # origin/master — a stale local ref would inflate the diff with master's own commits.
    _fetch_master()
    files = changed_files(against)
    base = against or "origin/master"

    triggered: list[DiffCheck] = []
    for chk in DIFF_CHECKS:
        chk.matched = [f for f in files if matches_globs(f, chk.triggers)]
        if chk.matched:
            triggered.append(chk)

    results: list[dict[str, Any]] = []
    failures = 0
    advisories = 0
    if not as_json:
        click.secho(f"\n  ci:preflight — {len(files)} changed file(s) vs {base}\n", bold=True)

    # Always-on branch-health check, independent of which files changed: a stale
    # branch breaks CI on merge no matter what the diff touches. Advisory only —
    # it never counts toward `failures` (a merge is the human/agent's call).
    stale_status, stale_detail, stale_props = _staleness(files)
    results.append({"check": "staleness", "status": stale_status, "files": 0, "detail": stale_detail})
    if not as_json:
        click.secho(f"   {_ICON[stale_status]} [staleness] branch freshness vs master", fg=_COLOR[stale_status])
        click.echo(f"       {stale_detail}")

    for chk in triggered:
        status, detail = _run_diff_check(chk, do_fix)
        failures += status == "fail"
        advisories += status == "advisory"
        results.append({"check": chk.key, "status": status, "files": len(chk.matched), "detail": detail})
        if not as_json:
            click.secho(f"   {_ICON[status]} [{chk.key}] {chk.label}", fg=_COLOR[status])
            click.echo(f"       {len(chk.matched)} file(s) · {detail}")

    summary = {
        "changed_files": len(files),
        "triggered": [c.key for c in triggered],
        "failures": failures,
        "advisories": advisories,
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
        if advisories:
            # Non-blocking, so agents skip these as pre-existing. Restate ownership.
            click.secho(
                f"\n  {advisories} advisory(ies) are unpushed CI failures — resolve before pushing, "
                "including drift you didn't introduce. You own the branch state you push.",
                fg="yellow",
            )
        click.echo()

    _emit_telemetry(summary)

    # Advisory by default — --strict turns verified *failures* into a non-zero exit
    # for the pre-push hook. Advisories never block: guidance-only checks can't tell
    # done from not-done, so blocking on them would false-block every matching push.
    # SystemExit so the telemetry wrapper records it.
    raise SystemExit(1 if (strict and failures) else 0)
