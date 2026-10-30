"""Workflows that run on untrusted input state the token scopes they need.

The repository default for `GITHUB_TOKEN` is read-only, so a job with no
`permissions:` key inherits read-only today and behaves correctly. That default
is a repository setting, not part of the file: it can change under the workflow,
and a reader cannot tell which scopes the job actually relies on. GitHub's own
least-privilege rule and the OpenSSF token-permissions check both ask for the
scopes to be declared where they are used.

Two shapes satisfy the rule. One top-level `permissions:` block covers every job.
Per-job `permissions:` is stricter, because each job states its own scopes, so a
workflow that declares one on every job needs no top-level block.

Reusable-workflow call jobs are exempt because they run the callee's jobs, and
the callee's own `permissions:` sets their scopes when the caller does not. That
only holds while the callee declares some, so a local callee with no
`permissions:` anywhere is reported on the caller.
"""

from __future__ import annotations

from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

UNTRUSTED_TRIGGERS = frozenset(
    {
        "pull_request",
        "pull_request_target",
        "issue_comment",
        "issues",
        "discussion",
        "discussion_comment",
        "pull_request_review",
        "pull_request_review_comment",
        "workflow_run",
    }
)


def _triggers(wf: Workflow) -> set[str]:
    triggers = wf.on
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, list):
        return {t for t in triggers if isinstance(t, str)}
    if isinstance(triggers, dict):
        return {t for t in triggers if isinstance(t, str)}
    return set()


def _declares_permissions(wf: Workflow) -> bool:
    return "permissions" in wf.raw or any("permissions" in job.raw for job in wf.jobs)


def _local_callee(uses: str, workflows: list[Workflow]) -> Workflow | None:
    """The parsed callee of a `./.github/workflows/x.yml` call, if it is in this page."""
    if not uses.startswith("./"):
        return None
    target = Path(uses[2:]).as_posix()
    for candidate in workflows:
        if candidate.path.as_posix().endswith(target):
            return candidate
    return None


class ExplicitPermissionsCheck(WorkflowCheck):
    id = "WF015-explicit-permissions"
    label = "explicit permissions"
    description = "workflows on untrusted triggers declare token scopes (top-level or per job)"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Add `permissions: {}` (or the scopes the job uses, e.g. `contents: read`) to the job, "
            "or one top-level `permissions:` block for the workflow."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            if not (_triggers(wf) & UNTRUSTED_TRIGGERS):
                continue
            if "permissions" in wf.raw:
                continue
            for job in wf.jobs:
                if job.is_reusable_call:
                    callee = _local_callee(job.uses or "", workflows)
                    if callee is not None and not _declares_permissions(callee):
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                job=job.name,
                                message=(
                                    f"calls {job.uses}, which declares no permissions, so both inherit "
                                    "the repository default"
                                ),
                                file=str(wf.path),
                            )
                        )
                    continue
                if "permissions" in job.raw:
                    continue
                result.issues.append(
                    Issue(
                        workflow=wf.path.name,
                        job=job.name,
                        message="no permissions declared for a job on an untrusted trigger",
                        file=str(wf.path),
                    )
                )
        return result


__all__ = ["ExplicitPermissionsCheck", "UNTRUSTED_TRIGGERS"]
