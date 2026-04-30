"""PR-triggered ``ci-*.yml`` workflows must declare a safe top-level ``concurrency:`` block.

Without it, every push to a PR branch starts a fresh run while the in-flight
one keeps burning minutes. The repo convention (used by 30+ workflows):

    concurrency:
        group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}
        cancel-in-progress: ${{ github.event_name == 'pull_request' }}

Using ``github.run_id`` as the fallback looks similar but disables dedup for
push events because every run gets a unique group.

Some workflows are intentionally exempt from cancellation (telemetry / shadow
measurement, schedule-dominant jobs). Those are listed in ``SKIP`` below with
a one-line reason each.
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

BAD_FALLBACK = re.compile(r"head_ref\s*\|\|\s*github\.run_id")


class PrConcurrencyCheck(WorkflowCheck):
    id = "WF002-pr-concurrency"
    label = "PR concurrency"
    description = "PR-triggered ci-*.yml workflows declare safe top-level concurrency"

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
            "    group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}\n"
            "    cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
            "\n"
            "Do not use `github.run_id` as the fallback; it creates a unique concurrency group per push run.\n"
            "\n"
            "Or, if cancelling stale runs would lose data (telemetry, schedule-only PR triggers, etc.),\n"
            f"add the filename to {type(self).__name__}.SKIP with a one-line reason."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            group_expr = _concurrency_group_expr(wf.concurrency)
            if BAD_FALLBACK.search(group_expr):
                result.issues.append(
                    Issue(
                        workflow=wf.path.name,
                        message=(
                            "concurrency group uses `github.head_ref || github.run_id`; use "
                            "`github.head_ref || github.ref` so push runs deduplicate"
                        ),
                        file=str(wf.path),
                    )
                )

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


def _concurrency_group_expr(concurrency: dict | str | None) -> str:
    if isinstance(concurrency, str):
        return concurrency
    if not isinstance(concurrency, dict):
        return ""
    group = concurrency.get("group")
    return group if isinstance(group, str) else ""
