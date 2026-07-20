"""Collate gates must run unconditionally and fail closed on every dependency.

A "collate gate" is the job that emits a required status check by inspecting its
dependencies' ``needs.*.result``. Two properties keep it honest, and both have
been violated in production before:

1. ``if: always()`` — the gate must run and emit an explicit verdict. Worker jobs
   should use ``!cancelled()`` so they actually stop when a run is superseded, but
   the gate itself is what branch protection reads, so it has to report.

2. Allowlist per dependency — assert ``success``/``skipped`` and block everything
   else. A dependency tested only against ``failure`` lets ``cancelled`` fall
   through. That is not hypothetical: several gates cleared ``changes`` with a
   bare ``== 'failure'`` test and then read ``needs.changes.outputs.*``, which is
   empty on a cancelled job, so the gate took its "nothing to test" exit and
   reported green with zero tests run.

The allowlist rule is enforced **per dependency**, not over the step as a whole.
A gate that checks four dependencies correctly and one with a bare ``failure``
test is still wrong, and reading result words globally would call it clean.

Gates are identified by the repo-wide naming convention: a display name ending in
"Pass" (e.g. "Django Tests Pass", "Visual regression tests pass").
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"\balways\s*\(\s*\)")

# `"${{ needs.build.result }}" != "success"` and friends. Quote-agnostic: bash in
# the wild uses both "..." and '...'. Captures which literal each dependency's
# result is actually compared against, so the verdict is per dependency.
RESULT_ASSERTION = re.compile(
    r"""needs\.(?P<dep>[A-Za-z0-9_\-]+)\.result\s*\}\}["']?\s*(?:==|!=)\s*["']?(?P<literal>[a-z]+)["']?"""
)

SAFE_LITERALS = frozenset({"success", "skipped"})
SAFE_LITERAL = re.compile(r"""["'](?:success|skipped)["']""")


def _display_name(job: Job) -> str:
    name = job.raw.get("name")
    return str(name) if isinstance(name, str) else job.name


def _is_gate(job: Job) -> bool:
    return bool(GATE_NAME.search(_display_name(job).strip()))


def _bash(job: Job) -> str:
    return "\n".join(step.run for step in job.steps if step.run)


def _literals_by_dependency(bash: str) -> dict[str, set[str]]:
    """Map each ``needs.<dep>.result`` to the set of literals it is compared against."""
    found: dict[str, set[str]] = {}
    for match in RESULT_ASSERTION.finditer(bash):
        found.setdefault(match.group("dep"), set()).add(match.group("literal"))
    return found


class RequiredGateCheck(WorkflowCheck):
    id = "WF007-required-check-gates"
    label = "required-check gates"
    description = "collate gates use always() and allowlist each dependency's result"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Keep `if: always()` on the gate, and test every dependency as "
            '`!= "success" && != "skipped"` rather than `== "failure"`. See '
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

                bash = _bash(job)

                # Backstop for gates that reach results indirectly — via an `env:`
                # block and a loop, or a shared shell function — where no literal
                # sits next to `needs.<dep>.result`. Those are fine, but only if the
                # allowlist is applied *somewhere*.
                if not SAFE_LITERAL.search(bash):
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message=(
                                "required-check gate never tests a result against `success`/`skipped`, "
                                "so a cancelled dependency cannot block it"
                            ),
                            file=str(wf.path),
                        )
                    )

                by_dep = _literals_by_dependency(bash)
                for dep in sorted(by_dep):
                    if by_dep[dep] & SAFE_LITERALS:
                        continue
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            message=(
                                f"dependency '{dep}' is only compared against "
                                f"{'/'.join(sorted(by_dep[dep]))}; a cancelled '{dep}' would pass. "
                                'Test `!= "success" && != "skipped"` instead'
                            ),
                            file=str(wf.path),
                        )
                    )
        return result
