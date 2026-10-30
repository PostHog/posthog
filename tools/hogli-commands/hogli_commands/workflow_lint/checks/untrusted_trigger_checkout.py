"""A trusted-context trigger must never check out the pull request head.

`pull_request_target`, `issue_comment` and `workflow_run` run in the base
repository's context: the secrets are the base repo's, and the token can write.
Checking out `github.event.pull_request.head.sha` there puts contributor code in
that context, and the next `run:` step executes it with those credentials. One
review comment or one push to a fork is then enough to take the token.

The safe shape checks out the base branch and reads the head commit as data, so
this notices the head commit reaching a `ref:` or a fork's `repository:` and
says nothing about scripts that merely print or compare it.

A head commit carried through a job output (`ref: ${{ needs.x.outputs.sha }}`)
is not visible here: the rule sees values, not data flow. A workflow that has to
plumb one stays on the reader.
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

TRUSTED_CONTEXT_TRIGGERS = frozenset({"pull_request_target", "issue_comment", "workflow_run", "issues"})

HEAD_REF = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref|label)"
    r"|github\.event\.pull_request\.merge_commit_sha"
    r"|github\.head_ref"
    r"|github\.event\.issue\.pull_request"
    r"|github\.event\.workflow_run\.(head_sha|head_branch|head_repository|pull_requests)"
    r"|refs/pull/[\w.${{ }}\[\]-]*/(head|merge)"
)

# A checkout of another repository's ref runs that repository's code, so pointing
# one at the fork's head is the same escape as a head `ref:`.
FORK_REPOSITORY = re.compile(
    r"github\.event\.workflow_run\.head_repository"
    r"|github\.event\.pull_request\.head\.repo"
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
                    inputs = step.with_ or {}
                    ref = str(inputs.get("ref") or "")
                    repository = str(inputs.get("repository") or "")
                    if HEAD_REF.search(ref):
                        message = f"checkout ref resolves to the PR head: {ref.strip()}"
                    elif FORK_REPOSITORY.search(repository):
                        message = f"checkout repository resolves to the contributor's fork: {repository.strip()}"
                    else:
                        continue
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            step=step.ref,
                            message=message,
                            file=str(wf.path),
                        )
                    )
        return result


__all__ = ["UntrustedTriggerCheckoutCheck", "FORK_REPOSITORY", "HEAD_REF", "TRUSTED_CONTEXT_TRIGGERS"]
