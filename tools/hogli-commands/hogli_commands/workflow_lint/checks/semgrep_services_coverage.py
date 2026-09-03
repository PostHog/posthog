"""Every ``services/<name>/`` is covered by a language-specific Semgrep job.

The repo-wide ``semgrep-general`` job excludes ``services/``, so a new
service added without updating ``semgrep-python`` or ``semgrep-js`` silently
drops out of SAST.

Unlike the other checks, this one needs filesystem context (``services/``)
plus the contents of one specific workflow (``ci-security.yaml``), so it
walks both via ``REPO_ROOT`` rather than only iterating the parsed
``Workflow`` list.

Only git-tracked services count: a working tree can carry build residue
(``node_modules``, tsbuildinfo) from a branch that once had a service, and
CI — which sees only tracked files — would never scan those.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

COVERING_JOBS = ("semgrep-python", "semgrep-js")
SECURITY_WORKFLOW_NAME = "ci-security.yaml"


class SemgrepServicesCoverageCheck(WorkflowCheck):
    id = "WF004-semgrep-services-coverage"
    label = "semgrep services coverage"
    description = f"every services/<name>/ appears in {' or '.join(COVERING_JOBS)} run or with-args text in {SECURITY_WORKFLOW_NAME}"

    def __init__(self, repo_root: Path | None = None) -> None:
        # Injected so tests can point at a fixture tree without monkeypatching env vars.
        self._repo_root = repo_root or REPO_ROOT

    @property
    def fix_hint(self) -> str | None:
        return f"Add each missing service to the matching job's target list in {SECURITY_WORKFLOW_NAME}."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        services_dir = self._repo_root / "services"
        if not services_dir.exists():
            return result

        security_wf = next((wf for wf in workflows if wf.path.name == SECURITY_WORKFLOW_NAME), None)
        if security_wf is None:
            result.issues.append(
                Issue(
                    workflow=SECURITY_WORKFLOW_NAME,
                    message=f"workflow not found in workflows directory; cannot verify coverage of {COVERING_JOBS}",
                )
            )
            return result

        run_text = _covering_run_text(security_wf)

        services = _tracked_services(self._repo_root, services_dir)
        for name in services:
            # boundary-delimited: matches `services/api/` run targets as well as
            # `--include /services/api` args, but not `services/api-v2`
            if not re.search(rf"services/{re.escape(name)}(?=[/\s]|$)", run_text):
                result.issues.append(
                    Issue(
                        workflow=SECURITY_WORKFLOW_NAME,
                        message=f"services/{name}/ not covered by {' or '.join(COVERING_JOBS)}",
                        file=str(security_wf.path),
                    )
                )
        return result


def _tracked_services(repo_root: Path, services_dir: Path) -> list[str]:
    """Top-level ``services/`` dirs git tracks, falling back to the filesystem.

    The fallback keeps the check meaningful outside a git checkout (fixture
    trees, exported tarballs) rather than silently passing everything.
    """
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--", "services"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(p.name for p in services_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    tracked = {
        entry.split("/")[1]
        for entry in listing.stdout.split("\0")
        if entry.startswith("services/") and "/" in entry[9:]
    }
    return sorted(tracked)


def _covering_run_text(wf: Workflow) -> str:
    # scan targets may live in `run:` text or in a composite action's `args`
    # input (the semgrep-ci action)
    parts: list[str] = []
    for job in wf.jobs:
        if job.name not in COVERING_JOBS:
            continue
        for step in job.steps:
            if step.run is not None:
                parts.append(step.run)
            if step.with_ is not None:
                args = step.with_.get("args")
                if isinstance(args, str):
                    parts.extend(_include_patterns(args))
    return "\n".join(parts)


def _include_patterns(args: str) -> list[str]:
    # Only `--include` values count as coverage: an `--exclude /services/<name>`
    # or an unrelated input naming a service must not satisfy the check.
    tokens = args.split()
    return [value for flag, value in zip(tokens, tokens[1:]) if flag == "--include"]
