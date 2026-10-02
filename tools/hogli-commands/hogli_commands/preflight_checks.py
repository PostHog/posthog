"""``ci:preflight`` checks that read the diff itself instead of running one command over it."""

from __future__ import annotations

import os
import re
import json
import shutil
import tempfile
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import matches_globs

Status = Literal["pass", "fail", "warning", "advisory", "skipped"]
Outcome = tuple[Status, str]


@dataclass(frozen=True, kw_only=True, slots=True)
class Scope:
    """What a push carries: the matched files, the ref they are diffed against, and which copy to read."""

    files: list[str]
    changed: list[str]
    base: str
    committed_only: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class FunctionCheck:
    key: str
    label: str
    triggers: list[str]
    run: Callable[[Scope], Outcome]


def _git(*args: str, timeout: float = 20.0) -> bytes | None:
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _merge_base(base: str) -> str | None:
    out = _git("merge-base", "HEAD", base)
    return out.decode().strip() if out else None


SNAPSHOT_MANIFEST = "frontend/snapshots.yml"
# A story identifier comes from the story file's title and export names, and the Storybook
# config decides which story files load. A removal that touches none of these deleted no story.
STORY_SOURCES = ["*.stories.*", ".storybook/*", "common/storybook/*"]
_SNAPSHOT_ENTRY = re.compile(r"^    ([^\s#:][^:\n]*):[ \t]*$", re.MULTILINE)


def _snapshot_identifiers(manifest: str) -> set[str]:
    return set(_SNAPSHOT_ENTRY.findall(manifest))


def check_snapshot_baselines(scope: Scope) -> Outcome:
    merge_base = _merge_base(scope.base)
    if merge_base is None:
        return "skipped", f"no merge-base with {scope.base}"
    before = _git("show", f"{merge_base}:{SNAPSHOT_MANIFEST}")
    if scope.committed_only:
        after = _git("show", f"HEAD:{SNAPSHOT_MANIFEST}")
    else:
        path = REPO_ROOT / SNAPSHOT_MANIFEST
        after = path.read_bytes() if path.exists() else None
    if before is None or after is None:
        return "skipped", f"could not read {SNAPSHOT_MANIFEST} on both sides"

    removed = sorted(_snapshot_identifiers(before.decode()) - _snapshot_identifiers(after.decode()))
    if not removed:
        return "pass", "no baseline entries removed"
    count = f"{len(removed)} baseline {'entry' if len(removed) == 1 else 'entries'} removed"
    if any(matches_globs(path, STORY_SOURCES) for path in scope.changed):
        return "pass", f"{count} alongside a story change"
    return (
        "fail",
        f"{count} but no story file changed (e.g. {removed[0]}). "
        "The stories still render, so the merge queue fails every batch that carries this file. "
        f"Restore the entries from `git show {merge_base[:12]}:{SNAPSHOT_MANIFEST}`",
    )


SEMGREP_WORKFLOW = ".github/workflows/ci-security.yaml"
SEMGREP_RULES = ".semgrep/rules/devex"
# The directories the `semgrep-devex` CI job scans.
SEMGREP_SCOPE = [
    f"{root}/*"
    for root in (
        "bin",
        "common",
        "docs/onboarding",
        "ee",
        "frontend",
        "packages",
        "posthog",
        "products",
        "services",
        "tools",
    )
]
_SEMGREP_IMAGE = re.compile(r"SEMGREP_IMAGE:\s*semgrep/semgrep:([0-9][0-9A-Za-z.\-]*)")
_SEMGREP_TIMEOUT_SECONDS = 300

# One finding: the rule, the file, and the source text it matched.
Finding = tuple[str, str, str]


def _semgrep_version() -> str | None:
    """The version CI pins, so a local run and the CI job apply the same rule semantics."""
    try:
        match = _SEMGREP_IMAGE.search((REPO_ROOT / SEMGREP_WORKFLOW).read_text())
    except OSError:
        return None
    return match.group(1) if match else None


def _semgrep_findings(semgrep: list[str], root: Path, files: list[str]) -> dict[Finding, list[int]] | None:
    """Findings in *files* under *root*, each with the lines it starts on. None when the scan did not run."""
    if not files:
        return {}
    try:
        result = subprocess.run(
            [
                *semgrep,
                "--config",
                str(REPO_ROOT / SEMGREP_RULES),
                "--severity=WARNING",
                "--severity=ERROR",
                "--metrics=off",
                "--quiet",
                "--json",
                *files,
            ],
            cwd=root,
            env={**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "false"},
            capture_output=True,
            text=True,
            timeout=_SEMGREP_TIMEOUT_SECONDS,
        )
        results = json.loads(result.stdout)["results"]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError):
        return None
    findings: dict[Finding, list[int]] = {}
    sources: dict[str, list[str]] = {}
    for item in results:
        path = item["path"]
        if path not in sources:
            sources[path] = (root / path).read_text(errors="replace").splitlines()
        start, end = item["start"]["line"], item["end"]["line"]
        matched = "\n".join(line.strip() for line in sources[path][start - 1 : end])
        # The id prefix encodes the rule file's path relative to the working directory,
        # which differs between the two scans. The last segment is the rule's own id.
        rule = item["check_id"].rsplit(".", 1)[-1]
        findings.setdefault((rule, path, matched), []).append(start)
    return findings


def check_semgrep_devex(scope: Scope) -> Outcome:
    present = [f for f in scope.files if (REPO_ROOT / f).is_file()]
    if not present:
        return "skipped", "only deleted files"
    if shutil.which("uvx") is None:
        return "skipped", "uvx not found"
    version = _semgrep_version()
    if version is None:
        return "skipped", f"no semgrep version pinned in {SEMGREP_WORKFLOW}"
    merge_base = _merge_base(scope.base)
    if merge_base is None:
        return "skipped", f"no merge-base with {scope.base}"

    semgrep = ["uvx", f"semgrep@{version}"]
    try:
        # uvx downloads semgrep on first use. A sandbox without network cannot, and that
        # must read as "skipped" instead of a finding.
        probe = subprocess.run([*semgrep, "--version"], capture_output=True, timeout=_SEMGREP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return "skipped", "semgrep did not start"
    if probe.returncode != 0:
        return "skipped", "semgrep is not installable here (needs network on first run)"

    # CI blocks only on findings the branch introduced, and gets them from `--baseline-commit`.
    # That flag is not usable here: on a clean checkout semgrep runs `git reset --hard` to the
    # baseline and back, and otherwise it checks the whole repository out again. Scanning the
    # merge-base copies of the changed files gives the same comparison without touching the checkout.
    with tempfile.TemporaryDirectory() as tmp:
        baseline_root = Path(tmp)
        in_baseline: list[str] = []
        for path in present:
            content = _git("show", f"{merge_base}:{path}")
            if content is None:
                continue
            target = baseline_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            in_baseline.append(path)
        before = _semgrep_findings(semgrep, baseline_root, in_baseline)
    after = _semgrep_findings(semgrep, REPO_ROOT, present)
    if before is None or after is None:
        return "skipped", "semgrep produced no readable report"

    known = Counter({finding: len(lines) for finding, lines in before.items()})
    introduced = [
        f"{rule} at {path}:{line}"
        for (rule, path, matched), lines in sorted(after.items())
        for line in lines[known[(rule, path, matched)] :]
    ]
    if not introduced:
        return "pass", "no new findings"
    more = f" (+{len(introduced) - 3} more)" if len(introduced) > 3 else ""
    return "fail", f"{len(introduced)} new finding(s): {' · '.join(introduced[:3])}{more}"


LANE_TARGETS_SCRIPT = ".github/scripts/trunk-impacted-targets.js"
LANE_SUMMARY_SCRIPT = ".github/scripts/trunk-lane-telemetry.js"
_LANE_TIMEOUT_SECONDS = 120


def check_merge_queue_lane(scope: Scope) -> Outcome:
    if shutil.which("node") is None:
        return "skipped", "node not found"
    stdin = "\n".join(scope.changed)
    env = {**os.environ}
    merge_base = _merge_base(scope.base)
    if merge_base is not None:
        env["LANE_MERGE_BASE"] = merge_base
    try:
        targets = subprocess.run(
            ["node", LANE_TARGETS_SCRIPT],
            cwd=REPO_ROOT,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_LANE_TIMEOUT_SECONDS,
        )
        summary = subprocess.run(
            ["node", LANE_SUMMARY_SCRIPT],
            cwd=REPO_ROOT,
            env={**env, "IMPACTED_TARGETS": json.dumps({"impactedTargets": json.loads(targets.stdout)})},
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_LANE_TIMEOUT_SECONDS,
        )
        lane = json.loads(summary.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return "skipped", "could not compute the merge queue lane"

    if not lane.get("is_all"):
        return "pass", f"claims {lane.get('target_count', 0)} merge queue lane target(s)"
    widening = lane.get("tripwire_files") or []
    if not widening or len(widening) >= len(scope.changed):
        return "pass", "claims every merge queue lane, and every changed file needs it"
    return (
        "warning",
        f"claims every merge queue lane because of {', '.join(widening[:3])}. "
        "The whole queue then merges in series behind this PR. "
        "Moving those files to their own PR keeps the other changes in a parallel lane",
    )


FUNCTION_CHECKS: list[FunctionCheck] = [
    FunctionCheck(
        key="snapshot-baselines",
        label="visual baselines dropped from snapshots.yml (fails every merge queue batch)",
        triggers=[SNAPSHOT_MANIFEST],
        run=check_snapshot_baselines,
    ),
    FunctionCheck(
        key="semgrep-devex",
        label="new semgrep findings (devex rules)",
        triggers=SEMGREP_SCOPE,
        run=check_semgrep_devex,
    ),
    FunctionCheck(
        key="merge-queue-lane",
        label="merge queue lane this diff claims",
        triggers=["*"],
        run=check_merge_queue_lane,
    ),
]
