"""PR-triggered ``ci-*.yml`` workflows must declare a top-level ``concurrency:`` block.

Without it, every push to a PR branch starts a fresh run while the in-flight
one keeps burning minutes. The repo convention (used by 30+ workflows):

    concurrency:
        group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
        cancel-in-progress: ${{ github.event_name == 'pull_request' }}

Some workflows are intentionally exempt from cancellation (telemetry / shadow
measurement, schedule-dominant jobs). Those are listed in ``SKIP`` below with
a one-line reason each.
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow


class PrConcurrencyCheck(WorkflowCheck):
    id = "WF002-pr-concurrency"
    label = "PR concurrency"
    description = "PR-triggered ci-*.yml workflows declare top-level concurrency"

    # Workflows intentionally exempt from concurrency cancellation. Each entry has
    # a one-line reason so the next reader knows why.
    SKIP: frozenset[str] = frozenset(
        {
            # Telemetry / shadow measurement — cancelling stale runs may drop data.
            "ci-test-selection-shadow.yml",
            # Schedule-dominant; PR trigger filtered to a single script — cosmetic gain.
            "ci-backend-update-test-timing.yml",
            # Migration enforcement; arguably wants to complete on every PR state.
            "ci-migrations-service-separation-check.yml",
        }
    )

    @property
    def fix_hint(self) -> str | None:
        return (
            "Add this block after `on:`:\n"
            "concurrency:\n"
            "    group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}\n"
            "    cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
            "\n"
            "Or, if cancelling stale runs would lose data (telemetry, schedule-only PR triggers, etc.),\n"
            f"add the filename to {type(self).__name__}.SKIP with a one-line reason."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            if not wf.path.name.startswith("ci-"):
                continue
            if wf.path.name in self.SKIP:
                continue
            if not wf.is_pr_triggered:
                continue
            if wf.concurrency is not None:
                continue
            result.issues.append(
                Issue(
                    workflow=wf.path.name,
                    message="missing top-level concurrency block",
                    file=str(wf.path),
                )
            )
        return result
