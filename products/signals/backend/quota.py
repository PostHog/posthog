"""Signals credit quota enforcement.

Lives in its own module (not `billing.py`) to avoid a circular import: `billing.py` is imported by
`posthog.tasks.usage_report`, which `ee.billing.quota_limiting` imports in turn.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
import posthoganalytics
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions import QuotaLimitExceeded
from posthog.temporal.common.metrics import get_metric_meter

from products.signals.backend.trial.funding import TrialFunding

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited, self_driving_quota_resource

if TYPE_CHECKING:
    from posthog.models import Team

    from products.signals.backend.trial.billing import TrialBillingStatus

logger = structlog.get_logger(__name__)

# Enforcement kill switch for new report/scout pipelines and manual work.
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


def is_team_signals_quota_limited(team_api_token: str, resource: QuotaResource) -> bool:
    """Whether a team is currently over its Signals credits quota.

    Fails open on a quota-limiter read error so an infra blip lets work through rather than stalling.
    Records `signals_quota_check_failed_open_total` so the bypass is alertable.
    Synchronous (Redis read); wrap in `sync_to_async` when calling from async code.
    """
    try:
        return is_team_limited(team_api_token, resource, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
    except Exception:
        logger.warning("signals_quota_check_failed_open", exc_info=True)
        record_quota_check_failed_open()
        return False


@dataclass(frozen=True)
class SelfDrivingQuotaGate:
    """One pipeline gate decision: `limited` is the raw quota state (for telemetry), `enforced`
    is whether the gate should actually block. Billing limits respect the enforcement flag;
    trial allowances require funding for new work."""

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


@frozen
class SelfDrivingAdmission:
    team: "Team"
    gate: SelfDrivingQuotaGate
    parent: TrialFunding | None = None
    paid_authorized: bool = False
    reason: str = "billing_limit"

    @property
    def trial_accounting_required(self) -> bool:
        return self.parent.grant_id is not None if self.parent is not None else not self.paid_authorized

    def bind(self, *, report_id: UUID | None = None, report_pass_key: str | None = None) -> TrialFunding:
        from products.signals.backend.trial.policy import (  # noqa: PLC0415 -- avoid model registration cycle
            TrialPolicy,
            TrialRefused,
        )

        if self.gate.enforced:
            if self.reason == "billing_limit":
                raise QuotaLimitExceeded()
            raise TrialRefused(self.reason)
        return TrialPolicy(self.team).admit(
            parent=self.parent,
            paid_authorized=self.paid_authorized,
            report_id=report_id,
            report_pass_key=report_pass_key,
        )


def prepare_self_driving_admission(
    team: "Team", *, parent: TrialFunding | None = None, billing_status: "TrialBillingStatus | None" = None
) -> SelfDrivingAdmission:
    """Snapshot implementation eligibility before new work acquires admission locks."""
    admission = _self_driving_admission(team, parent=parent, billing_status=billing_status)
    if parent is None and admission.parent is not None:
        from products.signals.backend.free_trial import (  # noqa: PLC0415 -- legacy gate imports trial policy
            self_driving_free_trial_enabled,
        )

        return replace(
            admission,
            parent=replace(admission.parent, implementation_allowed=not self_driving_free_trial_enabled(team)),
        )
    return admission


def _self_driving_admission(
    team: "Team", *, parent: TrialFunding | None = None, billing_status: "TrialBillingStatus | None" = None
) -> SelfDrivingAdmission:
    """Resolve funding and limits before callers acquire admission locks.

    Accepted pipelines keep their funding. New trial work uses the project allowance; paid
    work uses the org quota that Billing syncs into Redis. Binding rechecks trial capacity
    under the grant lock, so concurrent direct report starts see each other's admissions.
    """
    from products.signals.backend.trial.billing import (  # noqa: PLC0415 -- trial policy imports Signals models
        paid_trial_continuation_authorized,
    )
    from products.signals.backend.trial.policy import TrialPolicy  # noqa: PLC0415 -- avoid model registration cycle
    from products.signals.backend.usage import trial_usage  # noqa: PLC0415 -- avoid model registration cycle

    allowed = SelfDrivingQuotaGate(limited=False, enforced=False)
    if parent is not None:
        return SelfDrivingAdmission(team=team, gate=allowed, parent=parent)
    grant = TrialPolicy(team).admission_grant()
    if grant is not None:
        reason = trial_usage(grant).exhaustion_reason(grant)
        if not reason:
            return SelfDrivingAdmission(team=team, gate=allowed)
        paid_authorized = (
            billing_status.paid_authorized if billing_status is not None else paid_trial_continuation_authorized(team)
        )
        return SelfDrivingAdmission(
            team=team,
            gate=SelfDrivingQuotaGate(limited=not paid_authorized, enforced=not paid_authorized),
            paid_authorized=paid_authorized,
            reason=reason,
        )
    limited = is_team_signals_quota_limited(team.api_token, self_driving_quota_resource(team.organization))
    return SelfDrivingAdmission(
        team=team,
        gate=SelfDrivingQuotaGate(limited=limited, enforced=limited and self_driving_quota_enforcement_enabled(team)),
        parent=TrialFunding(funding="existing"),
    )


def self_driving_quota_gate(
    team: "Team", *, billing_status: "TrialBillingStatus | None" = None
) -> SelfDrivingQuotaGate:
    """Expose admission for new work to workflows and the paused-state UI."""
    from products.signals.backend.trial.policy import TrialRefused  # noqa: PLC0415 -- avoid model registration cycle

    try:
        return _self_driving_admission(team, billing_status=billing_status).gate
    except TrialRefused:
        return SelfDrivingQuotaGate(limited=True, enforced=True)


def self_driving_limit_name(team: "Team") -> str:
    """Use the same cutover for customer-facing limit units and enforcement."""
    if self_driving_quota_resource(team.organization) == QuotaResource.SIGNALS_SPEND_CREDITS:
        return "spending limit"
    return "pull request limit"


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


def notify_scout_quota_paused(team: "Team") -> None:
    """Tell the org its self-driving credits quota is now blocking scout runs.

    The quota gate skips runs with no run row and no visible state, so without this a team's
    scouts read as silently dead until the next billing period. Idempotent per limiting episode:
    the key carries the org's `quota_limited_until` and limit, so a new episode (period rollover,
    or a raised limit that the org then exceeds again) notifies again. Best-effort: a failed send
    must never fail the gate that called it. Requires `team.organization` to be loaded.
    """
    try:
        resource = self_driving_quota_resource(team.organization)
        usage = (team.organization.usage or {}).get(resource.value) or {}
        limit_name = self_driving_limit_name(team)
        quota_limited_until = usage.get("quota_limited_until") or 0
        limit = usage.get("limit") or 0
        from products.notifications.backend.facade.api import (  # noqa: PLC0415 (keeps the heavy dep off the import path)
            NotificationData,
            NotificationType,
            TargetType,
            create_notification,
        )

        create_notification(
            NotificationData(
                team_id=team.id,
                notification_type=NotificationType.USAGE_SPIKE,
                title=f"New scout runs paused: self-driving {limit_name} reached",
                body=(
                    f"This project reached its self-driving {limit_name}. New scout runs are paused "
                    "until the limit lifts. Work already underway will finish. Usage and limits: Settings > Billing."
                ),
                target_type=TargetType.TEAM,
                target_id=str(team.id),
                source_url="/organization/billing",
                idempotency_key=f"signals_scout_quota_paused:{team.organization_id}:{resource.value}:{quota_limited_until}:{limit}",
            )
        )
    except Exception:
        logger.warning("signals_scout_quota_notification_failed", team_id=team.id, exc_info=True)
