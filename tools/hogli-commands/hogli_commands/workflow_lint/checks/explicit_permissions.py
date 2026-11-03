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
only holds while every job the callee runs declares them, so a local callee is
followed through its own local calls, to any depth, and a bare job anywhere in
the chain is reported on the caller.
"""

from __future__ import annotations

from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, local_callee

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


def _declares_permissions(wf: Workflow, workflows: list[Workflow], seen: frozenset[Path] = frozenset()) -> bool:
    """Whether every job `wf` runs, through its own local calls too, has declared scopes.

    `any` let a callee with one declared job and one bare job through, and skipping
    a relay job (`uses:` with no `permissions:`) without following it let a two-deep
    chain end in a bare job. A relay job that declares `permissions:` caps its own
    callee, so the walk stops there. A remote callee is not visible here and passes.
    """
    if "permissions" in wf.raw:
        return True
    seen = seen | {wf.path}
    for job in wf.jobs:
        if "permissions" in job.raw:
            continue
        if not job.is_reusable_call:
            return False
        callee = local_callee(job.uses or "", workflows)
        if callee is None or callee.path in seen:
            continue
        if not _declares_permissions(callee, workflows, seen):
            return False
    return True


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
                # A job that declares its own scopes passes whether or not it calls a
                # reusable workflow: GitHub applies the caller job's permissions to the
                # callee, so the callee inheriting the repository default is not a risk
                # here. Test this before the reusable-call branch, or a caller that does
                # the right thing is failed for its callee's silence.
                if "permissions" in job.raw:
                    continue
                if job.is_reusable_call:
                    callee = local_callee(job.uses or "", workflows)
                    if callee is not None and not _declares_permissions(callee, workflows, frozenset({wf.path})):
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                job=job.name,
                                message=(
                                    f"calls {job.uses}, which declares no permissions for every job it runs "
                                    "(directly or through its own reusable calls), so those jobs inherit "
                                    "the repository default"
                                ),
                                file=str(wf.path),
                            )
                        )
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
