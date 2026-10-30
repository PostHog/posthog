"""A trusted-context trigger must never check out the pull request head.

`pull_request_target`, `issue_comment` and `workflow_run` run in the base
repository's context: the secrets are the base repo's, and the token can write.
Checking out `github.event.pull_request.head.sha` there puts contributor code in
that context, and the next `run:` step executes it with those credentials. One
review comment or one push to a fork is then enough to take the token.

The safe shape checks out the base branch and reads the head commit as data, so
this notices the head commit reaching a `ref:` and says nothing about scripts
that merely print or compare it.
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

TRUSTED_CONTEXT_TRIGGERS = frozenset({"pull_request_target", "issue_comment", "workflow_run", "issues"})

HEAD_REF = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref)"
    r"|github\.head_ref"
    r"|github\.event\.issue\.pull_request"
    r"|refs/pull/[\w.${{ }}]*/head"
)


def _triggers(wf: Workflow) -> set[str]:
    triggers = wf.on
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, (list, dict)):
        return {t for t in triggers if isinstance(t, str)}
    return set()


class UntrustedTriggerCheckoutCheck(WorkflowCheck):
    id = "WF016-untrusted-trigger-checkout"
    label = "no PR-head checkout on a trusted trigger"
    description = "pull_request_target / issue_comment / workflow_run never check out the PR head"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Check out the base ref and read the head commit as data, or move the work into a "
            "`pull_request` workflow that gets no secrets and a read-only token."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            if not (_triggers(wf) & TRUSTED_CONTEXT_TRIGGERS):
                continue
            for job in wf.jobs:
                for step in job.steps:
                    uses = (step.uses or "").lower()
                    if "checkout" not in uses:
                        continue
                    ref = str((step.with_ or {}).get("ref") or "")
                    if not HEAD_REF.search(ref):
                        continue
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            step=step.ref,
                            message=f"checkout ref resolves to the PR head: {ref.strip()}",
                            file=str(wf.path),
                        )
                    )
        return result


__all__ = ["UntrustedTriggerCheckoutCheck", "HEAD_REF", "TRUSTED_CONTEXT_TRIGGERS"]
