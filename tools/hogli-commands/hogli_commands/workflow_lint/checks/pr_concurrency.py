"""Workflows must declare concurrency, and cancel only the runs that are safe to cancel.

Without a block, every push to a PR branch starts a fresh run while the in-flight
one keeps burning minutes. The repo convention (used by 30+ workflows):

    concurrency:
        group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}
        cancel-in-progress: ${{ github.event_name == 'pull_request' }}

Alternatively, workflows may use job-level concurrency on every job instead of
a top-level block. This is useful when different jobs need different concurrency
strategies (e.g. some jobs are per-SHA while others are per-branch).

Using ``github.run_id`` as the fallback looks similar but disables dedup for
push events because every run gets a unique group.

A bare ``cancel-in-progress: true`` on a push-triggered workflow shares one
group across every commit on the branch, so each push kills the previous
commit's run and whatever it was proving. Gate it on the event, or key the
push arm per-SHA when the workflow publishes on push. Its opt-out is the
inline marker rather than ``SKIP``, so an exemption for one line sits beside
that line.

Some workflows are intentionally exempt from *requiring* a block (telemetry /
shadow measurement, schedule-dominant jobs). Those are listed in ``SKIP``
below with a one-line reason each.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

BAD_FALLBACK = re.compile(r"head_ref\s*\|\|\s*github\.run_id")
PER_SHA_PUSH_ARM = re.compile(r"event_name\s*==\s*['\"]push['\"]\s*&&\s*github\.sha")
MASTER_CANCEL_MARKER = "hogli-lint: allow-master-cancel"


class PrConcurrencyCheck(WorkflowCheck):
    id = "WF002-pr-concurrency"
    label = "PR concurrency"
    description = "ci-*.yml PR workflows declare concurrency; no workflow cancels master runs on push"

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
            # Shared concurrency group on master causes intermediate runs to be cancelled.
            "ci-security.yaml",
        }
    )

    @property
    def fix_hint(self) -> str | None:
        return (
            "Missing concurrency block: add a top-level one after `on:`:\n"
            "concurrency:\n"
            "    group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}\n"
            "    cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
            "Or give every job its own `concurrency:` block. If any block would lose data\n"
            "(telemetry, schedule-only PR triggers, etc.), add the filename to\n"
            f"{type(self).__name__}.SKIP with a one-line reason.\n"
            "\n"
            "`github.run_id` fallback: use `github.head_ref || github.ref` instead; run_id is unique\n"
            "per run, so push runs never deduplicate.\n"
            "\n"
            "Bare `cancel-in-progress: true` on push: every push cancels the previous commit's run.\n"
            "Gate it on the event as above, or key the push arm per-SHA when the workflow publishes:\n"
            "    group: ${{ github.workflow }}-${{ github.event_name == 'push' && github.sha || github.head_ref || github.ref }}\n"
            f"Where latest-wins is right (a cache warmer), say so with `# {MASTER_CANCEL_MARKER} -- <reason>`.\n"
            "SKIP does not exempt this rule; the marker is its opt-out."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            group_expr = _concurrency_group_expr(wf.concurrency)
            if _cancels_master_pushes(wf, group_expr):
                result.issues.append(
                    Issue(
                        workflow=wf.path.name,
                        message=(
                            "`cancel-in-progress: true` on a push-triggered workflow cancels master runs; "
                            "gate it with `${{ github.event_name == 'pull_request' }}`, or key the push arm "
                            "per-SHA when the workflow publishes on push"
                        ),
                        file=str(wf.path),
                    )
                )

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
            # Accept job-level concurrency as an alternative — the workflow
            # intentionally manages concurrency per-job instead of top-level.
            if _has_job_level_concurrency(wf):
                continue
            result.issues.append(
                Issue(
                    workflow=wf.path.name,
                    message="missing top-level concurrency block (or per-job concurrency on all jobs)",
                    file=str(wf.path),
                )
            )
        return result


def _cancels_master_pushes(wf: Workflow, group_expr: str) -> bool:
    if not isinstance(wf.concurrency, dict) or wf.concurrency.get("cancel-in-progress") is not True:
        return False
    if not wf.is_push_triggered:
        return False
    if _keys_pushes_per_sha(group_expr):
        return False
    return not _has_master_cancel_marker(wf.path)


def _keys_pushes_per_sha(group_expr: str) -> bool:
    """Report whether a push event resolves the group to a per-SHA value.

    Merely mentioning ``github.sha`` is not enough: when the SHA sits on some
    other arm of a conditional, pushes still fall through to one shared ref and
    cancel the commit before them.
    """
    if PER_SHA_PUSH_ARM.search(group_expr):
        return True
    if "&&" in group_expr or "||" in group_expr:
        return False
    return "github.sha" in group_expr


def _has_master_cancel_marker(path: Path) -> bool:
    """Report an explicit, reasoned bypass comment anywhere in the file.

    PyYAML drops comments, so the parsed model decides the violation and this
    raw scan only looks for the reviewable opt-out.
    """
    with open(path, encoding="utf-8") as f:
        for line in f:
            if MASTER_CANCEL_MARKER not in line:
                continue
            reason = line.partition(MASTER_CANCEL_MARKER)[2].strip()
            if reason.startswith("--") and reason[2:].strip():
                return True
    return False


def _has_job_level_concurrency(wf: Workflow) -> bool:
    """Return True if at least one job in the workflow declares its own concurrency block.

    This indicates the workflow intentionally manages concurrency at the job level
    rather than using a single top-level block (e.g. because different jobs need
    different strategies).
    """
    return any("concurrency" in job.raw for job in wf.jobs)


def _concurrency_group_expr(concurrency: dict | str | None) -> str:
    if isinstance(concurrency, str):
        return concurrency
    if not isinstance(concurrency, dict):
        return ""
    group = concurrency.get("group")
    return group if isinstance(group, str) else ""
