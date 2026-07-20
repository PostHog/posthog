"""Collate gates must run unconditionally and fail closed on every dependency.

A "collate gate" is the job that emits a required status check by inspecting its
dependencies' ``needs.*.result``. Two properties keep it honest, and both have
been violated in production before:

1. ``if: always()`` — the gate must run and emit an explicit verdict. Worker jobs
   should use ``!cancelled()`` so they actually stop when a run is superseded, but
   the gate itself is what branch protection reads, so it has to report.

2. Allowlist **per dependency** — assert ``success``/``skipped`` and block
   everything else. One bad dependency is enough, so reading result words over the
   step as a whole would call a mostly-correct gate clean. That is not
   hypothetical: four gates cleared ``changes`` with a bare ``== 'failure'`` test
   and then read ``needs.changes.outputs.*``, which is empty on a cancelled job, so
   the gate took its "nothing to test" exit and reported green with zero tests run.

Gates are identified by the repo-wide naming convention: a display name ending in
"Pass" (e.g. "Django Tests Pass", "Visual regression tests pass").
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"\balways\s*\(\s*\)")

SAFE_LITERALS = frozenset({"success", "skipped"})
SAFE_LITERAL = re.compile(rf"""["'](?:{"|".join(sorted(SAFE_LITERALS))})["']""")

# `"${{ needs.build.result }}" != "success"` and friends, quote-agnostic. Captures
# the literal each dependency's result is compared against, so the verdict is per
# dependency rather than over the step as a whole.
RESULT_ASSERTION = re.compile(
    r"""needs\.(?P<dep>[A-Za-z0-9_\-]+)\.result\s*\}\}["']?\s*(?:==|!=)\s*["']?(?P<literal>[a-z]+)["']?"""
)


def _is_gate(job: Job) -> bool:
    name = job.raw.get("name")
    display = name if isinstance(name, str) else job.name
    return bool(GATE_NAME.search(display.strip()))


def _bash(job: Job) -> str:
    return "\n".join(step.run for step in job.steps if step.run)


def _literals_by_dependency(bash: str) -> dict[str, set[str]]:
    """Map each ``needs.<dep>.result`` to the set of literals it is compared against."""
    found: dict[str, set[str]] = {}
    for match in RESULT_ASSERTION.finditer(bash):
        found.setdefault(match.group("dep"), set()).add(match.group("literal"))
    return found


def _problems(job: Job) -> Iterator[str]:
    if not ALWAYS.search(str(job.raw.get("if") or "")):
        yield "required-check gate must use `if: always()` so it always emits a verdict"

    bash = _bash(job)

    # Some gates reach results indirectly — through an `env:` block and a loop, or
    # a shared shell function — so no literal sits next to `needs.<dep>.result` for
    # the per-dependency pass below to read. That's fine, as long as the allowlist
    # is applied somewhere.
    if not SAFE_LITERAL.search(bash):
        yield (
            "required-check gate never tests a result against `success`/`skipped`, "
            "so a cancelled dependency cannot block it"
        )

    literals = _literals_by_dependency(bash)
    for dep in sorted(literals):
        if literals[dep] & SAFE_LITERALS:
            continue
        yield (
            f"dependency '{dep}' is only compared against {'/'.join(sorted(literals[dep]))}; "
            f'a cancelled \'{dep}\' would pass. Test `!= "success" && != "skipped"` instead'
        )


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
                for message in _problems(job):
                    result.issues.append(Issue(workflow=wf.path.name, job=job.name, message=message, file=str(wf.path)))
        return result
