"""Signals credit quota enforcement.

Lives in its own module (not `billing.py`) to avoid a circular import: `billing.py` is imported by
`posthog.tasks.usage_report`, which `ee.billing.quota_limiting` imports in turn.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import connection

import structlog
import posthoganalytics
from temporalio import activity

from posthog.event_usage import groups
from posthog.temporal.common.metrics import get_metric_meter

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

if TYPE_CHECKING:
    from posthog.models import Team
    from posthog.models.organization import Organization

logger = structlog.get_logger(__name__)

# Enforcement kill switch for the pipeline quota gates (promotion, summary stages, auto-start).
# While the flag is off the gates still run and emit `signal_report_quota_paused` telemetry with
# `enforced=false`, but never block, so the would-block volume is measurable before rollout.
SELF_DRIVING_QUOTA_ENFORCEMENT_FLAG = "self-driving-quota-enforcement"


def record_quota_check_failed_open() -> None:
    """Count a self-driving quota check that errored and failed open (no-op outside a Temporal
    activity). Shared by every gate whose fail-open must stay alertable."""
    # Emit the meter directly rather than via products.signals.backend.temporal.metrics: importing
    # that package runs its __init__, which imports buffer.py, which imports this module (cycle).
    if not activity.in_activity():
        return
    get_metric_meter().create_counter(
        "signals_quota_check_failed_open_total",
        "Signals quota checks that errored and failed open, bypassing enforcement",
    ).add(1)


def is_team_signals_quota_limited(team_api_token: str) -> bool:
    """Whether a team is currently over its Signals credits quota.

    Fails open on a quota-limiter read error so an infra blip lets work through rather than stalling.
    Records `signals_quota_check_failed_open_total` so the bypass is alertable.
    Synchronous (Redis read); wrap in `sync_to_async` when calling from async code.
    """
    try:
        return is_team_limited(
            team_api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_quota_check_failed_open", exc_info=True)
        record_quota_check_failed_open()
        return False


@dataclass(frozen=True)
class SelfDrivingQuotaGate:
    """One pipeline gate decision: `limited` is the raw quota state (for telemetry), `enforced`
    is whether the gate should actually block (limited AND the enforcement flag is on)."""

    limited: bool
    enforced: bool


def self_driving_quota_enforcement_enabled(team: "Team") -> bool:
    """Whether quota-gate enforcement is rolled out to this team's org.

    Org-keyed like the `signals-pr-refunds` gate (the limit is the org's billing cap). Fails open
    (no enforcement) on a flag-read error, matching the quota check's own fail-open policy: a flag
    outage must not stall the fleet's pipelines. Also gates visibility of the refund-summary
    endpoint (the widget's source for the paused state), which must work with refunds off.
    """
    try:
        org_id = str(team.organization_id)
        return (
            posthoganalytics.feature_enabled(
                SELF_DRIVING_QUOTA_ENFORCEMENT_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
            )
            is True
        )
    except Exception:
        logger.warning("self_driving_quota_enforcement_flag_check_failed", exc_info=True)
        return False


def self_driving_quota_gate(team: "Team") -> SelfDrivingQuotaGate:
    """Resolve the quota gate for one team: is it quota-limited, and is enforcement on.

    The limit itself is org-level (the org's billing cap): the quota cron sums usage across all
    of the org's teams and, when the org crosses its limit, writes every one of the org's team
    tokens into the Redis limited set. This per-team check therefore reads an org-wide verdict,
    and all teams in an org pause together.

    The enforcement flag is only read when the team is actually limited, so the fleet-wide hot
    paths pay a single cached Redis read. Blocking network I/O; wrap in `sync_to_async` from
    async code.
    """
    if not is_team_signals_quota_limited(team.api_token):
        return SelfDrivingQuotaGate(limited=False, enforced=False)
    return SelfDrivingQuotaGate(limited=True, enforced=self_driving_quota_enforcement_enabled(team))


def self_driving_pr_reservation_limit_credits(organization: "Organization") -> int | None:
    """The org's self-driving PR cap in signals credits — `organization.usage["signals_credits"]["limit"]`,
    the same number the cron-driven Redis limiter compares usage against. Deliberately left in
    credits rather than converted to a PR count: `SIGNALS_CREDITS_PER_REPORT_WITH_PR` (1500) rarely
    divides a round-dollar limit evenly, and flooring the conversion would cap the org one PR below
    what the credit limit actually allows. None means uncapped: no limit configured, or billing
    hasn't synced usage for this org yet (a fresh org, or self-hosted).
    """
    resource_usage = (organization.usage or {}).get(QuotaResource.SIGNALS_CREDITS.value) or {}
    return resource_usage.get("limit")


def reserve_self_driving_pr_slot(team: "Team") -> SelfDrivingQuotaGate:
    """Atomically decide whether `team`'s organization has room for one more self-driving
    PR-opening task, in the same breath as reserving the slot.

    The org-wide PR limit only binds correctly if the check-and-spend is one operation: reading a
    cached "am I limited" snapshot (whether Redis's cron-refreshed flag, or a webhook-triggered
    async recompute) leaves a window where two concurrent task creations for the same org — the
    same report or different ones — both observe "under quota" and both proceed, jointly
    overshooting the cap. This closes that window with a per-organization Postgres advisory lock
    (`pg_advisory_xact_lock`, scoped to the current transaction) plus a live reservation count
    straight from Postgres (`count_self_driving_pr_reservations_in_period`), so a second concurrent
    caller blocks on the lock until the first has either created its task (and thus counted itself)
    or rolled back.

    Must therefore be called from inside the transaction that will create the implementation task
    (and its `SignalReportTask` "implementation" bridge row) — the lock releases the moment that
    transaction ends, so calling this outside one gives no protection at all.

    Falls back to the cached boolean gate (`self_driving_quota_gate`) when the org has no numeric
    limit resolved yet, so a fresh org or an instance whose billing usage hasn't synced fails open
    exactly like every other quota gate, rather than dividing by an unresolved limit.

    Credited-path PR refunds offset the reserved total the same way `_signals_credited_refund_offset`
    offsets the cron-driven usage check — a credited refund frees the customer's slot, even though
    the money already left billing's own usage number untouched.
    """
    from products.signals.backend.billing import (  # noqa: PLC0415 — avoid the usage_report import cycle quota.py exists to dodge
        SIGNALS_CREDITS_PER_REPORT_WITH_PR,
        count_self_driving_pr_reservations_in_period,
        credited_refund_credits_for_org,
        current_billing_period_bounds,
    )

    organization = team.organization
    limit_credits = self_driving_pr_reservation_limit_credits(organization)
    if limit_credits is None:
        return self_driving_quota_gate(team)

    if not connection.in_atomic_block:
        raise RuntimeError(
            "reserve_self_driving_pr_slot must run inside the transaction that creates the "
            "implementation task, otherwise its advisory lock releases before the reservation "
            "that spends it lands"
        )

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"self-driving-pr-quota:{organization.id}"])

    period = current_billing_period_bounds(organization)
    reserved_credits = (
        count_self_driving_pr_reservations_in_period(organization.id, period=period)
        * SIGNALS_CREDITS_PER_REPORT_WITH_PR
    )
    reserved_credits -= credited_refund_credits_for_org(organization.id, period.start, period.end)
    if reserved_credits < limit_credits:
        return SelfDrivingQuotaGate(limited=False, enforced=False)
    return SelfDrivingQuotaGate(limited=True, enforced=self_driving_quota_enforcement_enabled(team))


def capture_signal_report_quota_paused(team: "Team", *, report_id: str | None, stage: str, enforced: bool) -> None:
    """`signal_report_quota_paused`: a pipeline gate observed the team's org over its self-driving
    credits quota at `stage`. `enforced=false` rows are dark-launch would-blocks. Best-effort: telemetry
    must never fail the pipeline step that emitted it. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signal_report_quota_paused",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "report_id": report_id,
                "stage": stage,
                "enforced": enforced,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception(
            "Failed to capture signal_report_quota_paused", report_id=report_id, team_id=team.id, stage=stage
        )
