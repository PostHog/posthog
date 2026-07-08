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

Two mechanisms remove a report from billing:

- **Refunds** (retrospective, `SignalReportRefund`): an `excluded`-path refund makes the usage
  query skip the report entirely — committed strictly on the same UTC day as the first billable
  PR run, so no usage send (all of which happen ≥3h45m into the next UTC day) can ever observe
  the exclusion flipping. A `credited`-path refund is deliberately NOT consulted here: usage
  stays truthful and the money comes back as a billing-service credit.
- **Exemptions** (prospective, `SignalReport.billing_exempt_reason`): PostHog-system-origin
  reports are marked never-billable before their billable moment exists, so they never enter
  usage (nor, via the same query driving quota `todays_usage`, consume a free-tier slot).

Emergent semantic to be aware of: because of the `billed_earlier` idempotency check below, a
report whose first billable PR run has been refunded can NEVER be billed again — a later, second
PR run on the same report finds the first run before the period and is skipped, and the first
run itself is refund-excluded (excluded path) or already handled by a credit (credited path).
This is why restoring a refunded report is blocked at the API layer: refund → restore → new PR
would otherwise be repeatable free work.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

from django.db.models import F, QuerySet, Sum
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.models import SignalReport, SignalReportRefund, SignalReportTask, SignalScoutRun

if TYPE_CHECKING:
    from posthog.models.organization import Organization

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


class BillingExemptionError(Exception):
    """A report can no longer be exempted — a billable PR run already exists (use a refund)."""


# PostHog-system scout skills whose reports must never bill — users must not pay for PRs that fix
# problems in PostHog's own systems. v1 policy is this code constant; the report→scout link is the
# runs' `emitted_report_ids` tally (report-channel scouts author their reports directly).
BILLING_EXEMPT_SCOUT_SKILLS: dict[str, str] = {
    "signals-scout-health-checks": SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK,
}

# Same policy for the signal channel: sources owned by PostHog systems (e.g. the temporal
# health-checks pipeline, `posthog/temporal/health_checks/signal_emitter.py`). Per-signal
# source_product never reaches Postgres, so this map is enforced where the report row is
# formed — the grouping activity stamps `billing_exempt_reason` at creation. Formation-time
# only: an exempt-origin signal joining an existing report never flips it (and vice versa),
# mirroring `mark_report_billing_exempt`'s first-reason-wins freeze.
BILLING_EXEMPT_SOURCE_PRODUCTS: dict[str, str] = {
    SignalSourceProduct.HEALTH_CHECKS: SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK,
}


def system_billing_exempt_reason(team_id: int, report_id: str | uuid.UUID) -> str | None:
    """The exemption reason system policy assigns to a report, or None for normal reports.

    Pure Postgres (no ClickHouse), so it is usable under the auto-start row lock: a report is
    exempt-origin when an exempt scout skill's run authored it via `emit_report`.
    """
    for skill_name, reason in BILLING_EXEMPT_SCOUT_SKILLS.items():
        if (
            SignalScoutRun.objects.for_team(team_id)
            .filter(skill_name=skill_name, emitted_report_ids__contains=[str(report_id)])
            .exists()
        ):
            return reason
    return None


def mark_report_billing_exempt(report: SignalReport, reason: str) -> bool:
    """Mark `report` never-billable, enforcing the prospective-only freeze rule (hard).

    Returns False (no-op) when the report already carries an exemption — the first reason wins,
    exemptions are never rewritten. Raises `BillingExemptionError` when the report already has a
    billable PR run: anything already billable is a refund, never a late exemption, so no usage
    report can ever observe this field flipping.

    Persists only the exemption column (deliberately not bumping `updated_at` — a billing-internal
    stamp must not resurface the report in recency-ordered lists). Callers needing atomicity with
    other writes should hold the report row lock; the auto-start hook does.
    """
    if report.billing_exempt_reason:
        return False
    if first_billable_pr_run_at(report.id) is not None:
        raise BillingExemptionError(
            f"Report {report.id} already has a billable PR run; use a refund instead of a billing exemption."
        )
    report.billing_exempt_reason = reason
    report.save(update_fields=["billing_exempt_reason"])
    return True


class FirstBillablePrRun(NamedTuple):
    created_at: datetime
    pr_url: str


def first_billable_pr_run(report_id: str | uuid.UUID) -> FirstBillablePrRun | None:
    """The report's billable moment: its first implementation run with a GitHub PR URL (with that
    run's `created_at` and `pr_url`), or None if it has never shipped one.

    Single source of truth for "when did this report become chargeable" — the refund action uses
    it for eligibility, snapshots, and the UTC-day path decision, and the exemption freeze rule
    uses it to refuse late exemptions. It applies the exact same fail-closed filters as the usage
    query, so the two can never disagree about whether a billable run exists.
    """
    row = (
        _bridges_with_pr_run()
        .filter(report_id=report_id)
        # Both columns resolve against the TaskRun join the filter established, so the earliest
        # billable run's timestamp and URL come from the same row.
        .order_by("task__runs__created_at")
        .values_list("task__runs__created_at", "task__runs__output__pr_url")
        .first()
    )
    if row is None:
        return None
    return FirstBillablePrRun(created_at=row[0], pr_url=row[1])


def first_billable_pr_run_at(report_id: str | uuid.UUID) -> datetime | None:
    """`first_billable_pr_run`, timestamp only."""
    run = first_billable_pr_run(report_id)
    return run.created_at if run else None


def credited_refund_credits_for_org(organization_id: str | uuid.UUID, begin: datetime, end: datetime) -> int:
    """Sum of `credits` over the org's credited-path refunds whose refunded PR run falls in
    `[begin, end)` — the amount the quota check offsets so a credited refund frees the free-tier
    slot, not just the money. Keyed on `pr_run_created_at` (not refund creation) so the offset
    lines up with the period the usage was billed in. Unscoped: deliberately org-wide."""
    return (
        SignalReportRefund.objects.unscoped()
        .filter(
            team__organization_id=organization_id,
            billing_path=SignalReportRefund.BillingPath.CREDITED,
            pr_run_created_at__gte=begin,
            pr_run_created_at__lt=end,
        )
        .aggregate(total=Sum("credits"))["total"]
        or 0
    )


def current_billing_period_bounds(organization: "Organization") -> tuple[datetime, datetime]:
    """The org's current billing period `[start, end)`, falling back to the current UTC calendar
    month when billing hasn't populated `organization.usage["period"]` (e.g. self-hosted or a
    just-created org). Refund eligibility and the org-wide refund summary both key off this."""
    period = organization.current_billing_period
    if period is not None:
        return period
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (start, start + relativedelta(months=1))


def get_signals_billing_credits_by_team(
    begin: datetime, end: datetime, organization_id: str | uuid.UUID | None = None
) -> list[tuple[int, int]]:
    """Signals credits used per team in `[begin, end)`.

    A report is billable in this period when the first implementation PR for it appeared in the
    window — an implementation `TaskRun` with a `pr_url` was created in `[begin, end)` and no
    such run exists before `begin`. Each billable report is charged a flat
    `SIGNALS_CREDITS_PER_REPORT_WITH_PR`. Returns `[(team_id, credits), ...]` for teams with
    non-zero usage only. `organization_id` narrows the scan to one org (the widget's live-count
    path); usage reporting passes nothing and stays fleet-wide.

    The entry scan is bounded by PRs shipped in the period (via the `created_at` +
    `output__pr_url` indexes), not by the total number of reports, task runs, or teams.
    """
    # Reports whose implementation produced a billable PR within this period, mapped to the team
    # that owns the report. The teams are guaranteed equal by `_bridges_with_pr_run()`, so the
    # bridge's team_id is the report's team.
    bridges = _bridges_with_pr_run(
        task__runs__created_at__gte=begin,
        task__runs__created_at__lt=end,
    )
    if organization_id is not None:
        bridges = bridges.filter(team__organization_id=organization_id)
    report_team: dict[uuid.UUID, int] = {}
    for report_id, team_id in bridges.values_list("report_id", "team_id"):
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

    # Excluded-path refunds: billing must never learn these reports existed. Deterministic across
    # re-sends by the UTC-day path rule (see module docstring). Credited-path refunds are
    # deliberately absent — their usage stays truthful. Unscoped: this aggregates across all teams
    # outside any request context.
    refund_excluded = set(
        SignalReportRefund.objects.unscoped()
        .filter(report_id__in=report_ids, billing_path=SignalReportRefund.BillingPath.EXCLUDED)
        .values_list("report_id", flat=True)
    )

    # Billing-exempt reports (PostHog-system origins) never bill; the reason is frozen before the
    # billable moment exists, so this is deterministic across re-sends too.
    billing_exempt = set(
        # nosemgrep: idor-lookup-without-team (ids come from the team-grouped billing bridge query above; usage aggregation is deliberately cross-team)
        SignalReport.objects.filter(id__in=report_ids, billing_exempt_reason__isnull=False).values_list("id", flat=True)
    )

    skipped = billed_earlier | refund_excluded | billing_exempt

    totals: dict[int, int] = defaultdict(int)
    for report_id, team_id in report_team.items():
        if report_id in skipped:
            continue
        totals[team_id] += SIGNALS_CREDITS_PER_REPORT_WITH_PR

    return list(totals.items())


def period_billable_credits_for_org(organization_id: str | uuid.UUID, begin: datetime, end: datetime) -> int:
    """The org's billable signals credits for `[begin, end)` per the exact usage-report rules —
    including PRs created today that haven't been reported to billing yet.

    Powers the inbox usage widget's live PR count: the frontend takes the max of this and
    billing's recorded usage, so a fresh PR counts immediately and a same-UTC-day (excluded-path)
    refund visibly un-counts it. Display-only — usage reports never read this; credited-path
    refunds stay included here (usage is truthful) and are netted separately by the widget.
    """
    return sum(
        credits for _, credits in get_signals_billing_credits_by_team(begin, end, organization_id=organization_id)
    )
