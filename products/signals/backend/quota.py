"""Signals credit quota enforcement.

Lives in its own module (not `billing.py`) to avoid a circular import: `billing.py` is imported by
`posthog.tasks.usage_report`, which `ee.billing.quota_limiting` imports in turn.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
import posthoganalytics
from temporalio import activity

from posthog.event_usage import groups
from posthog.temporal.common.metrics import get_metric_meter

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Enforcement kill switch for the pipeline quota gates (promotion, summary stages, auto-start).
# While the flag is off the gates still run and emit `signal_report_quota_paused` telemetry with
# `enforced=false`, but never block, so the would-block volume is measurable before rollout.
SIGNALS_QUOTA_ENFORCEMENT_FLAG = "signals-quota-enforcement"


def record_quota_check_failed_open() -> None:
    """Count a signals quota check that errored and failed open (no-op outside a Temporal
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
class SignalsQuotaGate:
    """One pipeline gate decision: `limited` is the raw quota state (for telemetry), `enforced`
    is whether the gate should actually block (limited AND the enforcement flag is on)."""

    limited: bool
    enforced: bool


def _enforcement_enabled(team: "Team") -> bool:
    """Whether quota-gate enforcement is rolled out to this team's org.

    Org-keyed like the `signals-pr-refunds` gate (the limit is the org's billing cap). Fails open
    (no enforcement) on a flag-read error, matching the quota check's own fail-open policy: a flag
    outage must not stall the fleet's pipelines.
    """
    try:
        org_id = str(team.organization_id)
        return (
            posthoganalytics.feature_enabled(
                SIGNALS_QUOTA_ENFORCEMENT_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
            )
            is True
        )
    except Exception:
        logger.warning("signals_quota_enforcement_flag_check_failed", exc_info=True)
        return False


def signals_quota_gate(team: "Team") -> SignalsQuotaGate:
    """Resolve the quota gate for one team: over the Signals credits quota, and is enforcement on.

    The flag is only read when the team is actually limited, so the fleet-wide hot paths pay a
    single cached Redis read. Blocking network I/O; wrap in `sync_to_async` from async code.
    """
    if not is_team_signals_quota_limited(team.api_token):
        return SignalsQuotaGate(limited=False, enforced=False)
    return SignalsQuotaGate(limited=True, enforced=_enforcement_enabled(team))


def capture_signal_report_quota_paused(team: "Team", *, report_id: str | None, stage: str, enforced: bool) -> None:
    """`signal_report_quota_paused` — a pipeline gate observed the team over its Signals credits
    quota at `stage`. `enforced=false` rows are dark-launch would-blocks. Best-effort: telemetry
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
