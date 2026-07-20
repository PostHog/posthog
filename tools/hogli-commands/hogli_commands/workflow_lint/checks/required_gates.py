"""Collate gates must run unconditionally and fail closed on non-success results.

A "collate gate" is the job that emits a required status check by inspecting its
dependencies' ``needs.*.result``. Two properties keep it honest, and both have
been violated in production before:

1. ``if: always()`` — the gate must run and emit an explicit verdict. Worker jobs
   should use ``!cancelled()`` so they actually stop when a run is superseded, but
   the gate itself is the thing branch protection reads, so it has to report.

2. Allowlist, not denylist — assert ``success``/``skipped`` and fail everything
   else. A gate that only tests ``== 'failure'`` lets a ``cancelled`` dependency
   fall through to a green required check with zero tests run.

Gates are identified by the repo-wide naming convention: a display name ending in
"Pass" (e.g. "Django Tests Pass", "Visual regression tests pass").
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"\balways\s*\(\s*\)")
# Quote-agnostic: bash in the wild uses both "failure" and 'failure'.
RESULT_TOKEN = re.compile(r"""["']?(success|skipped)["']?""")


def _display_name(job: Job) -> str:
    name = job.raw.get("name")
    return str(name) if isinstance(name, str) else job.name


def _is_gate(job: Job) -> bool:
    return bool(GATE_NAME.search(_display_name(job).strip()))


def _bash(job: Job) -> str:
    return "\n".join(step.run for step in job.steps if step.run)


class RequiredGateCheck(WorkflowCheck):
    id = "WF007-required-check-gates"
    label = "required-check gates"
    description = "collate gates use always() and assert success/skipped rather than only failure"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Keep `if: always()` on the gate and assert an allowlist: treat any result "
            "that is not `success` or `skipped` as a failure. See "
            ".agents/skills/authoring-ci-workflows/SKILL.md."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                if job.is_reusable_call or not _is_gate(job):
                    continue

                condition = job.raw.get("if")
                if not ALWAYS.search(str(condition or "")):
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message="required-check gate must use `if: always()` so it always emits a verdict",
                            file=str(wf.path),
                        )
                    )

                matched = {m.group(1) for m in RESULT_TOKEN.finditer(_bash(job))}
                if matched != {"success", "skipped"}:
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message=(
                                "required-check gate must assert `success`/`skipped` and fail "
                                "everything else; a denylist on `failure` lets a cancelled "
                                "dependency pass as green"
                            ),
                            file=str(wf.path),
                        )
                    )
        return result
