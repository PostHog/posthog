"""Collate gates must run unconditionally and fail closed on every dependency.

A "collate gate" is the job that emits a required status check by inspecting its
dependencies' ``needs.*.result``. Two properties keep it honest:

1. ``if: always()`` — the gate must run and emit an explicit verdict. Worker jobs
   should use ``!cancelled()`` so they actually stop when a run is superseded, but
   the gate itself is what branch protection reads, so it has to report.

2. Allowlist **per dependency** — assert ``success``/``skipped`` and block
   everything else. One bad dependency is enough, so judging the step as a whole
   would call a mostly-correct gate clean. The trap is a ``changes`` detector
   cleared with a bare ``== 'failure'`` test: ``cancelled`` passes it, the gate
   then reads ``needs.changes.outputs.*``, which is empty on a cancelled job, and
   takes its "nothing to test" exit — green, with zero tests run.

Gates are found two ways, because the "name it ``… Pass``" convention is not
universally followed: by that name, and structurally (``always()`` plus a step
that reads ``needs.<dep>.result``). Jobs that inspect results without gating
anything opt out with ``ALLOW_MARKER`` plus a reason.

Keep gate bodies inline. Routing results through a shell function or an ``env:``
block hides them from the per-dependency pass, which then falls back to the much
weaker step-wide check that an allowlist appears *somewhere*.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow

ALLOW_MARKER = "hogli-lint: not-a-required-gate"

GATE_NAME = re.compile(r"\bpass$", re.IGNORECASE)
ALWAYS = re.compile(r"\balways\s*\(\s*\)")
READS_RESULT = re.compile(r"needs\.[A-Za-z0-9_\-]+\.result")

SAFE_LITERALS = frozenset({"success", "skipped"})
SAFE_LITERAL = re.compile(rf"""["'](?:{"|".join(sorted(SAFE_LITERALS))})["']""")

# `"${{ needs.build.result }}" != "success"` and friends, quote-agnostic. Captures
# the literal each dependency's result is compared against, so the verdict is per
# dependency rather than over the step as a whole.
RESULT_ASSERTION = re.compile(
    r"""needs\.(?P<dep>[A-Za-z0-9_\-]+)\.result\s*\}\}["']?\s*(?:==|!=)\s*["']?(?P<literal>[a-z]+)["']?"""
)


def _bash(job: Job) -> str:
    return "\n".join(step.run for step in job.steps if step.run)


def _exempt_jobs(path: Path, job_names: frozenset[str]) -> frozenset[str]:
    """Job ids carrying an allow marker, with a reason, in the comments above them.

    Keyed off the parsed job names rather than indentation depth, so it doesn't
    care how the file is formatted and can't be fooled by a nested mapping key.
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    exempt: set[str] = set()
    for idx, line in enumerate(lines):
        match = re.match(r"^\s*(?P<job>[A-Za-z0-9_\-]+):\s*$", line)
        if match is None or match.group("job") not in job_names:
            continue
        # Walk up through the contiguous comment block directly above the job key.
        for above in reversed(lines[:idx]):
            if not above.strip().startswith("#"):
                break
            _, marker, reason = above.partition(ALLOW_MARKER)
            if marker and reason.strip(" -—:"):
                exempt.add(match.group("job"))
                break
    return frozenset(exempt)


def _is_gate(job: Job) -> bool:
    name = job.raw.get("name")
    display = name if isinstance(name, str) else job.name
    if GATE_NAME.search(display.strip()):
        return True
    return bool(ALWAYS.search(str(job.raw.get("if") or "")) and READS_RESULT.search(_bash(job)))


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
            "Keep `if: always()` on the gate, and test every dependency inline as "
            '`!= "success" && != "skipped"` rather than `== "failure"`. A job that reads '
            f"results without gating anything opts out with `# {ALLOW_MARKER} — <reason>`. "
            "See .agents/skills/authoring-ci-workflows/SKILL.md."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            gates = [job for job in wf.jobs if not job.is_reusable_call and _is_gate(job)]
            if not gates:
                continue
            # Only worth re-reading the file once we know there's a gate to exempt.
            exempt = _exempt_jobs(wf.path, frozenset(job.name for job in wf.jobs))
            for job in gates:
                if job.name in exempt:
                    continue
                for message in _problems(job):
                    result.issues.append(Issue(workflow=wf.path.name, job=job.name, message=message, file=str(wf.path)))
        return result
