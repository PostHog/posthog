"""Signals billing — a flat credit charge per report that ships an implementation PR.

Signals is billed on outcomes, not LLM spend: each signal report whose implementation task
opens a pull request is charged a flat number of credits, once. The chargeable moment is
deterministic — the first implementation `TaskRun` with a `pr_url` set — so a report is
billed exactly once, in the period that PR first appeared, regardless of any later status
changes, re-judgements, or additional runs.

The PR↔report link lives on the `SignalReportTask` bridge (relationship=IMPLEMENTATION); the
PR URL itself is written to `TaskRun.output['pr_url']`. There is no artefact that records the
implementation task or its PR, so the query is rooted on that bridge, not on artefacts.

Credits use the same unit as ai_credits: 1 credit = $0.01, so the flat $15 charge is 1500
credits.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from products.signals.backend.models import SignalReportTask
from products.tasks.backend.models import TaskRun

_IMPLEMENTATION = SignalReportTask.Relationship.IMPLEMENTATION

SIGNALS_CREDITS_PER_DOLLAR = 100  # 1 credit = $0.01, matching ai_credits

# Flat credits charged once per report whose implementation shipped a PR ($15).
SIGNALS_CREDITS_PER_REPORT_WITH_PR = 15 * SIGNALS_CREDITS_PER_DOLLAR  # 1500


def get_signals_billing_credits_by_team(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    """Signals credits used per team in `[begin, end)`.

    A report is billable in this period when the first implementation PR for it appeared in the
    window — an implementation `TaskRun` with a `pr_url` was created in `[begin, end)` and no
    such run exists before `begin`. Each billable report is charged a flat
    `SIGNALS_CREDITS_PER_REPORT_WITH_PR`. Returns `[(team_id, credits), ...]` for teams with
    non-zero usage only.

    The entry scan is bounded by PRs shipped in the period (via the `created_at` +
    `output__pr_url` indexes), not by the total number of reports, task runs, or teams.
    """
    # Reports whose implementation produced a PR within this period, mapped to the team that
    # owns the report (read off the bridge so credits land on the report's team regardless of
    # which team_id the run carries). The relationship and pr_url constraints stay in one
    # filter() so they resolve against a single bridge join.
    report_team: dict[uuid.UUID, int] = {}
    for report_id, team_id in (
        TaskRun.objects.filter(
            created_at__gte=begin,
            created_at__lt=end,
            output__pr_url__isnull=False,
            task__signal_report_tasks__relationship=_IMPLEMENTATION,
        )
        .exclude(output__pr_url="")
        .values_list("task__signal_report_tasks__report_id", "task__signal_report_tasks__team_id")
    ):
        if report_id is not None:
            report_team.setdefault(report_id, team_id)

    if not report_team:
        return []

    report_ids = list(report_team)

    # Exclude reports whose first implementation PR predates this period — they were billed in an
    # earlier period. This is what makes billing idempotent across re-runs and prevents
    # double-charging when a report ships more PR runs later.
    billed_earlier = set(
        TaskRun.objects.filter(
            created_at__lt=begin,
            output__pr_url__isnull=False,
            task__signal_report_tasks__relationship=_IMPLEMENTATION,
            task__signal_report_tasks__report_id__in=report_ids,
        )
        .exclude(output__pr_url="")
        .values_list("task__signal_report_tasks__report_id", flat=True)
    )

    totals: dict[int, int] = defaultdict(int)
    for report_id, team_id in report_team.items():
        if report_id in billed_earlier:
            continue
        totals[team_id] += SIGNALS_CREDITS_PER_REPORT_WITH_PR

    return list(totals.items())
