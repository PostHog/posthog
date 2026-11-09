from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

CHANGE_GATE_RE = re.compile(r"(needs\.[\w-]+\.outputs\.[\w-]+)\s*==\s*'true'")


def _change_gate(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    condition = value.strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    match = CHANGE_GATE_RE.fullmatch(condition)
    return match[1] if match else None


def _missing_checkout_gate(job: Job) -> str | None:
    if len(job.steps) < 2 or job.raw.get("outputs") or job.raw.get("if") is not None:
        return None
    checkout, *work = job.steps
    if not (checkout.uses or "").lower().startswith("actions/checkout@") or checkout.raw.get("if") is not None:
        return None
    gate = _change_gate(work[0].raw.get("if"))
    if gate is None:
        return None
    return gate if all(_change_gate(step.raw.get("if")) == gate for step in work) else None


class CheckoutWorkGateCheck(WorkflowCheck):
    id = "WF018-checkout-work-gate"
    label = "checkout work gate"
    description = "checkouts skip when all later steps share a change-output gate"

    @property
    def fix_hint(self) -> str:
        return "Apply the shared change-output condition to checkout. Keep required-check jobs running when no files match."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for workflow in workflows:
            for job in workflow.jobs:
                gate = _missing_checkout_gate(job)
                if gate is not None:
                    result.issues.append(
                        Issue(
                            workflow=workflow.path.name,
                            file=str(workflow.path),
                            job=job.name,
                            step=job.steps[0].ref,
                            message=f"Checkout runs when all later steps skip; add if: {gate} == 'true' to checkout.",
                        )
                    )
        return result
