"""A trusted-context trigger must never check out the pull request head.

`pull_request_target`, `issue_comment` and `workflow_run` run in the base
repository's context: the secrets are the base repo's, and the token can write.
Checking out `github.event.pull_request.head.sha` there puts contributor code in
that context, and the next `run:` step executes it with those credentials. One
review comment or one push to a fork is then enough to take the token.

The safe shape checks out the base branch and reads the head commit as data, so
this notices the head commit reaching a `ref:` or a fork's `repository:` and
says nothing about scripts that merely print or compare it.

Local reusable workflows are followed to any depth, and a head commit passed
into one as an input (`with: sha: ...`, then `ref: ${{ inputs.sha }}`) is
tracked through the calls. A head commit carried through a job output
(`ref: ${{ needs.x.outputs.sha }}`) is not visible here: the rule sees values,
not data flow. A workflow that has to plumb one stays on the reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Step, Workflow, local_callee

TRUSTED_CONTEXT_TRIGGERS = frozenset(
    {
        "pull_request_target",
        "issue_comment",
        "issues",
        "workflow_run",
        # Review events run in the base repository with the base token and expose
        # `pull_request.head.*`, so a checkout there reaches the fork head just as
        # `pull_request_target` does. WF015 already lists both as untrusted.
        "pull_request_review",
        "pull_request_review_comment",
        "discussion",
        "discussion_comment",
    }
)

HEAD_REF = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref|label)"
    r"|github\.event\.pull_request\.merge_commit_sha"
    r"|github\.head_ref"
    r"|github\.event\.issue\.pull_request"
    r"|github\.event\.workflow_run\.(head_sha|head_branch|head_repository|pull_requests)"
    r"|refs/pull/[\w.${{ }}\[\]-]*/(head|merge)",
    re.IGNORECASE,
)

# A checkout of another repository's ref runs that repository's code, so pointing
# one at the fork's head is the same escape as a head `ref:`.
FORK_REPOSITORY = re.compile(
    r"github\.event\.workflow_run\.head_repository"
    r"|github\.event\.pull_request\.head\.repo",
    re.IGNORECASE,
)


# `github['head_ref']` and `github.event.pull_request['head'].sha` evaluate to the
# same values as their dotted forms, so they are rewritten before matching.
BRACKET_PROPERTY = re.compile(r"""\[\s*['"]([\w-]+)['"]\s*\]""")


def _normalize(expression: str) -> str:
    return BRACKET_PROPERTY.sub(r".\1", expression)


def _reads_tainted_input(value: str, tainted_inputs: frozenset[str]) -> bool:
    return any(re.search(rf"\binputs\.{re.escape(name)}\b", value) for name in tainted_inputs)


def _is_head_ref(value: str, tainted_inputs: frozenset[str]) -> bool:
    value = _normalize(value)
    return bool(HEAD_REF.search(value)) or _reads_tainted_input(value, tainted_inputs)


def _is_fork_repository(value: str, tainted_inputs: frozenset[str]) -> bool:
    value = _normalize(value)
    return bool(FORK_REPOSITORY.search(value)) or _reads_tainted_input(value, tainted_inputs)


def _triggers(wf: Workflow) -> set[str]:
    triggers = wf.on
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, (list, dict)):
        return {t for t in triggers if isinstance(t, str)}
    return set()


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachedSteps:
    """Steps a trusted-trigger workflow runs, and how it reaches them."""

    job: Job  # the job in the trusted-trigger workflow, which owns any issue
    steps: list[Step]
    via: tuple[str, ...]  # reusable workflows called on the way, outermost first
    tainted_inputs: frozenset[str]  # callee inputs the callers fed a PR-head value


def _tainted_inputs(call: Job, tainted: frozenset[str]) -> frozenset[str]:
    """Inputs of `call`'s callee that carry a PR-head ref or fork repository."""
    inputs = call.raw.get("with")
    if not isinstance(inputs, dict):
        return frozenset()
    return frozenset(
        str(key)
        for key, value in inputs.items()
        if _is_head_ref(str(value), tainted) or _is_fork_repository(str(value), tainted)
    )


def _reachable_steps(wf: Workflow, workflows: list[Workflow]) -> list[ReachedSteps]:
    """Every step list this workflow can execute, following local calls to any depth.

    A head SHA handed to a callee as an input (`with: sha: ...head.sha`, then
    `ref: ${{ inputs.sha }}`) is followed too, through nested calls.
    """
    reached: list[ReachedSteps] = []

    def walk(job: Job, callee: Workflow, via: tuple[str, ...], tainted: frozenset[str], seen: frozenset) -> None:
        for callee_job in callee.jobs:
            reached.append(ReachedSteps(job=job, steps=callee_job.steps, via=via, tainted_inputs=tainted))
            nested = local_callee(callee_job.uses or "", workflows) if callee_job.is_reusable_call else None
            if nested is not None and nested.path not in seen:
                walk(
                    job,
                    nested,
                    (*via, nested.path.name),
                    _tainted_inputs(callee_job, tainted),
                    seen | {nested.path},
                )

    for job in wf.jobs:
        reached.append(ReachedSteps(job=job, steps=job.steps, via=(), tainted_inputs=frozenset()))
        callee = local_callee(job.uses or "", workflows) if job.is_reusable_call else None
        if callee is not None:
            seen = frozenset({wf.path, callee.path})
            walk(job, callee, (callee.path.name,), _tainted_inputs(job, frozenset()), seen)
    return reached


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
            # A trusted-trigger workflow reaches a checkout directly, or through local
            # reusable workflows it calls, to any depth. A callee has no trigger of its
            # own (`workflow_call`), so it never matches the filter above and would
            # otherwise escape the rule. Follow the calls and inspect their steps too.
            for reached in _reachable_steps(wf, workflows):
                for step in reached.steps:
                    uses = (step.uses or "").lower()
                    if "checkout" not in uses:
                        continue
                    inputs = step.with_ or {}
                    ref = str(inputs.get("ref") or "")
                    repository = str(inputs.get("repository") or "")
                    if _is_head_ref(ref, reached.tainted_inputs):
                        message = f"checkout ref resolves to the PR head: {ref.strip()}"
                    elif _is_fork_repository(repository, reached.tainted_inputs):
                        message = f"checkout repository resolves to the contributor's fork: {repository.strip()}"
                    else:
                        continue
                    if reached.via:
                        chain = " -> ".join(reached.via)
                        message = f"{message} (in the reusable workflow {chain} this job calls)"
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=reached.job.name,
                            step=step.ref,
                            message=message,
                            file=str(wf.path),
                        )
                    )
        return result


__all__ = ["UntrustedTriggerCheckoutCheck", "FORK_REPOSITORY", "HEAD_REF", "TRUSTED_CONTEXT_TRIGGERS"]
