"""A trusted-context trigger must never check out the pull request head.

`pull_request_target`, `issue_comment` and `workflow_run` run in the base
repository's context: the secrets are the base repo's, and the token can write.
Checking out `github.event.pull_request.head.sha` there puts contributor code in
that context, and the next `run:` step executes it with those credentials. One
review comment or one push to a fork is then enough to take the token.

The rule fails closed. A checkout's `ref:` and `repository:` on a trusted
trigger may only be literals, or expressions that read base-side contexts
(`github.sha`, `github.ref`, `github.event.pull_request.base.*`,
`github.event.repository.*`, `vars.*`, ...). Anything else, such as `env.*`,
`matrix.*`, `needs.*.outputs` or `steps.*.outputs`, cannot be proven to be the
base and is reported, because each of those is one assignment away from the
head SHA. Matching known head expressions instead kept missing the next alias.

Local reusable workflows are followed to any depth. An `inputs.<name>` read in
a callee is judged by the value its caller passes, or by the input's `default:`
when the caller passes none.

A job that has to check out the head on purpose, behind its own approval gate,
says so above its job key: `# hogli-lint: allow-trusted-checkout -- <reason>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..check import CheckResult, Issue, WorkflowCheck
from ..markers import exempt_jobs
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
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
CONTEXT_REFERENCE = re.compile(
    r"\b(?:github|env|matrix|needs|steps|inputs|vars|secrets|job|jobs|runner|strategy)(?:\.[\w-]+|\[\d+\]|\.\*)*"
)

# Contexts that resolve to the base repository or a maintainer-controlled value
# under every trusted trigger. Matched as dotted prefixes.
SAFE_CONTEXTS = (
    "github.sha",
    "github.ref",
    "github.ref_name",
    "github.base_ref",
    "github.repository",
    "github.repository_owner",
    "github.event.repository.",
    "github.event.pull_request.base.",
    "github.event.workflow_run.repository.",
    "vars.",
    "secrets.",
)

ALLOW_MARKER = "hogli-lint: allow-trusted-checkout"


def _normalize(expression: str) -> str:
    return BRACKET_PROPERTY.sub(r".\1", expression)


def _is_safe_context(reference: str) -> bool:
    return any(reference == safe or (safe.endswith(".") and reference.startswith(safe)) for safe in SAFE_CONTEXTS)


def _unsafe_reason(value: str, unsafe_inputs: dict[str, str], *, top_level: bool) -> str | None:
    """Why `value` may not be the base, or None when it provably is.

    `unsafe_inputs` maps a callee input to the reason its supplied value is unsafe.
    At the top level, `inputs.*` can only come from `workflow_dispatch`, which a
    maintainer triggers, so it passes.
    """
    value = _normalize(value)
    if FORK_REPOSITORY.search(value):
        return "resolves to the contributor's fork"
    if HEAD_REF.search(value):
        return "resolves to the PR head"
    for expression in EXPRESSION.findall(value):
        for reference in CONTEXT_REFERENCE.findall(STRING_LITERAL.sub("''", expression)):
            if _is_safe_context(reference):
                continue
            if reference.startswith("inputs."):
                name = reference.split(".")[1]
                if top_level or name not in unsafe_inputs:
                    continue
                return f"reads input `{name}`, which {unsafe_inputs[name]}"
            return f"reads `{reference}`, which the rule cannot prove is the base"
    return None


def _triggers(wf: Workflow) -> set[str]:
    triggers = wf.on
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, (list, dict)):
        return {t for t in triggers if isinstance(t, str)}
    return set()


def _input_defaults(callee: Workflow) -> dict[str, str]:
    on = callee.on if isinstance(callee.on, dict) else {}
    call = on.get("workflow_call") if isinstance(on.get("workflow_call"), dict) else {}
    inputs = call.get("inputs") if isinstance(call.get("inputs"), dict) else {}
    return {
        str(name): str(spec["default"])
        for name, spec in inputs.items()
        if isinstance(spec, dict) and spec.get("default") is not None
    }


def _callee_unsafe_inputs(
    call: Job, callee: Workflow, caller_inputs: dict[str, str], *, top_level: bool
) -> dict[str, str]:
    """The callee's inputs whose value, as the caller supplies it, may not be the base."""
    supplied = call.raw.get("with") if isinstance(call.raw.get("with"), dict) else {}
    unsafe: dict[str, str] = {}
    for name, value in supplied.items():
        reason = _unsafe_reason(str(value), caller_inputs, top_level=top_level)
        if reason is not None:
            unsafe[str(name)] = reason
    for name, default in _input_defaults(callee).items():
        if name in supplied:
            continue
        # A default is evaluated in the caller's event context and cannot read inputs.
        reason = _unsafe_reason(default, {}, top_level=False)
        if reason is not None:
            unsafe[name] = f"defaults to a value that {reason}"
    return unsafe


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachedSteps:
    """Steps a trusted-trigger workflow runs, and how it reaches them."""

    job: Job  # the job in the trusted-trigger workflow, which owns any issue
    steps: list[Step]
    via: tuple[str, ...]  # reusable workflows called on the way, outermost first
    unsafe_inputs: dict[str, str]  # callee inputs whose supplied value may not be the base


def _reachable_steps(wf: Workflow, workflows: list[Workflow]) -> list[ReachedSteps]:
    """Every step list this workflow can execute, following local calls to any depth."""
    reached: list[ReachedSteps] = []

    def walk(job: Job, callee: Workflow, via: tuple[str, ...], unsafe: dict[str, str], seen: frozenset) -> None:
        for callee_job in callee.jobs:
            reached.append(ReachedSteps(job=job, steps=callee_job.steps, via=via, unsafe_inputs=unsafe))
            nested = local_callee(callee_job.uses or "", workflows) if callee_job.is_reusable_call else None
            if nested is not None and nested.path not in seen:
                nested_unsafe = _callee_unsafe_inputs(callee_job, nested, unsafe, top_level=False)
                walk(job, nested, (*via, nested.path.name), nested_unsafe, seen | {nested.path})

    for job in wf.jobs:
        reached.append(ReachedSteps(job=job, steps=job.steps, via=(), unsafe_inputs={}))
        callee = local_callee(job.uses or "", workflows) if job.is_reusable_call else None
        if callee is not None:
            unsafe = _callee_unsafe_inputs(job, callee, {}, top_level=True)
            walk(job, callee, (callee.path.name,), unsafe, frozenset({wf.path, callee.path}))
    return reached


class UntrustedTriggerCheckoutCheck(WorkflowCheck):
    id = "WF016-untrusted-trigger-checkout"
    label = "no PR-head checkout on a trusted trigger"
    description = "pull_request_target / issue_comment / workflow_run never check out the PR head"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Check out the base ref and read the head commit as data, or move the work into a "
            "`pull_request` workflow that gets no secrets and a read-only token. A job that must build "
            "the head behind its own approval gate carries "
            "`# hogli-lint: allow-trusted-checkout -- <reason>` above its job key."
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
            exempt = exempt_jobs(wf.path, frozenset(job.name for job in wf.jobs), ALLOW_MARKER)
            for reached in _reachable_steps(wf, workflows):
                if reached.job.name in exempt:
                    continue
                top_level = not reached.via
                for step in reached.steps:
                    uses = (step.uses or "").lower()
                    if "checkout" not in uses:
                        continue
                    inputs = step.with_ or {}
                    message = None
                    for key in ("ref", "repository"):
                        value = str(inputs.get(key) or "")
                        reason = _unsafe_reason(value, reached.unsafe_inputs, top_level=top_level) if value else None
                        if reason is not None:
                            message = f"checkout {key} {reason}: {value.strip()}"
                            break
                    if message is None:
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


__all__ = ["ALLOW_MARKER", "UntrustedTriggerCheckoutCheck", "FORK_REPOSITORY", "HEAD_REF", "TRUSTED_CONTEXT_TRIGGERS"]
