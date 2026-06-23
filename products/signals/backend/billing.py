"""Signals billing — a flat credit charge per report that ships an implementation PR.

Signals is billed on outcomes, not LLM spend: each signal report whose implementation task
opens a pull request is charged a flat number of credits, once. The chargeable moment is
deterministic — the first implementation `TaskRun` with a `pr_url` set — so a report is
billed exactly once, in the period that PR first appeared, regardless of any later status
changes, re-judgements, or additional runs.

The PR↔report link lives on the `SignalReportTask` bridge (relationship="implementation"); the
PR URL itself is written to `TaskRun.output['pr_url']`. There is no artefact that records the
implementation task or its PR, so the query is rooted on that bridge, not on artefacts.

Because this is a billing source it fails closed: a run only bills when its PR URL is a GitHub
URL and the run, task, bridge, and report teams all agree, so malformed bridge rows never
produce a charge.

Credits use the same unit as ai_credits: 1 credit = $0.01, so the flat $15 charge is 1500
credits.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from django.db.models import F, QuerySet

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.models import SignalReportTask

_IMPLEMENTATION = TASK_RUN_TYPE_IMPLEMENTATION

# Only PRs hosted on GitHub are billable. The PR URL is GitHub's `html_url`
# (https://github.com/owner/repo/pull/N), so validate the host prefix to avoid charging
# for malformed or non-GitHub values written into `output.pr_url`.
_GITHUB_PR_URL_PREFIX = "https://github.com/"

SIGNALS_CREDITS_PER_DOLLAR = 100  # 1 credit = $0.01, matching ai_credits

# Flat credits charged once per report whose implementation shipped a PR ($15).
SIGNALS_CREDITS_PER_REPORT_WITH_PR = 15 * SIGNALS_CREDITS_PER_DOLLAR  # 1500


def _bridges_with_pr_run(**run_created_at: datetime) -> QuerySet[SignalReportTask]:
    """Implementation bridges whose task shipped a billable PR run matching `run_created_at`.

    Rooted on the signals-owned `SignalReportTask` bridge and traversing to runs via the
    `task__runs` relation, so the query never imports the tasks product's internals — it stays
    behind the tasks public interface. Postgres is free to drive the join from the run
    `created_at` index regardless, so the period scan stays bounded by PRs shipped, not by the
    number of bridges.

    Fail closed: a bridge only counts when one of its runs carries a GitHub PR URL within the
    given `created_at` bound and the four teams in the chain — run, task, bridge, and report —
    all agree. A malformed bridge whose teams disagree is excluded rather than charged to
    whichever team_id happened to be on it. The run-level conditions sit in one `filter()` so
    they all resolve against the same `TaskRun` row.
    """
    return SignalReportTask.objects.filter(
        relationship=_IMPLEMENTATION,
        task__runs__output__pr_url__startswith=_GITHUB_PR_URL_PREFIX,
        # Fail closed on team disagreement across run / task / bridge / report.
        task__team_id=F("team_id"),
        report__team_id=F("team_id"),
        task__runs__team_id=F("team_id"),
        # `output__pr_url__startswith` only matches present, string-typed values, so no
        # separate isnull / empty-string guard is needed.
        **run_created_at,
    )


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
    # Reports whose implementation produced a billable PR within this period, mapped to the team
    # that owns the report. The teams are guaranteed equal by `_bridges_with_pr_run()`, so the
    # bridge's team_id is the report's team.
    report_team: dict[uuid.UUID, int] = {}
    for report_id, team_id in _bridges_with_pr_run(
        task__runs__created_at__gte=begin,
        task__runs__created_at__lt=end,
    ).values_list("report_id", "team_id"):
        report_team.setdefault(report_id, team_id)

    if not report_team:
        return []

    report_ids = list(report_team)

    # Exclude reports whose first implementation PR predates this period — they were billed in an
    # earlier period. This is what makes billing idempotent across re-runs and prevents
    # double-charging when a report ships more PR runs later.
    billed_earlier = set(
        _bridges_with_pr_run(task__runs__created_at__lt=begin)
        .filter(report_id__in=report_ids)
        .values_list("report_id", flat=True)
    )

    totals: dict[int, int] = defaultdict(int)
    for report_id, team_id in report_team.items():
        if report_id in billed_earlier:
            continue
        totals[team_id] += SIGNALS_CREDITS_PER_REPORT_WITH_PR

    return list(totals.items())
