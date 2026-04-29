"""Every ``services/<name>/`` is covered by a language-specific Semgrep job.

The repo-wide ``semgrep-general`` job excludes ``services/``, so a new
service added without updating ``semgrep-python`` or ``semgrep-js`` silently
drops out of SAST.

Unlike the other checks, this one needs filesystem context (``services/``)
plus the contents of one specific workflow (``ci-security.yaml``), so it
walks both via ``REPO_ROOT`` rather than only iterating the parsed
``Workflow`` list.
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, find_repo_root

COVERING_JOBS = ("semgrep-python", "semgrep-js")
SECURITY_WORKFLOW_NAME = "ci-security.yaml"


class SemgrepServicesCoverageCheck(WorkflowCheck):
    id = "WF004-semgrep-services-coverage"
    label = "semgrep services coverage"
    description = f"every services/<name>/ appears in {' or '.join(COVERING_JOBS)} run-text in {SECURITY_WORKFLOW_NAME}"

    @property
    def fix_hint(self) -> str | None:
        return f"Add each missing service to the matching job's target list in {SECURITY_WORKFLOW_NAME}."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        services_dir = find_repo_root() / "services"
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

        services = sorted(p.name for p in services_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
        for name in services:
            if f"services/{name}/" not in run_text:
                result.issues.append(
                    Issue(
                        workflow=SECURITY_WORKFLOW_NAME,
                        message=f"services/{name}/ not covered by {' or '.join(COVERING_JOBS)}",
                        file=str(security_wf.path),
                    )
                )
        return result


def _covering_run_text(wf: Workflow) -> str:
    parts: list[str] = []
    for job in wf.jobs:
        if job.name not in COVERING_JOBS:
            continue
        for step in job.steps:
            if step.run is not None:
                parts.append(step.run)
    return "\n".join(parts)
