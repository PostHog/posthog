"""Every job must declare ``timeout-minutes``.

Without an explicit ``timeout-minutes``, GitHub Actions jobs default to a
6-hour execution limit, so a stuck runner silently burns CI credits.

Reusable workflow calls (``jobs.<id>.uses``) don't support ``timeout-minutes``
at the job level — timeouts are set inside the called workflow — so we skip
those jobs.
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow


class JobTimeoutsCheck(WorkflowCheck):
    id = "WF001-job-timeouts"
    label = "job timeouts"
    description = "every job declares timeout-minutes (reusable-workflow calls excepted)"

    @property
    def fix_hint(self) -> str | None:
        return "Add `timeout-minutes: <n>` at the job level."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                if job.is_reusable_call:
                    continue
                if job.has_timeout:
                    continue
                result.issues.append(
                    Issue(
                        workflow=wf.path.name,
                        job=job.name,
                        message="missing timeout-minutes",
                        file=str(wf.path),
                    )
                )
        return result
