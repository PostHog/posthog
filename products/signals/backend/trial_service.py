from django.conf import settings
from django.utils import timezone

import structlog

from posthog.models import Team

from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.trial_billing import TrialBilling, TrialBillingStatus, TrialContinuation
from products.signals.backend.trial_models import SignalTrialOrganization, SignalTrialReportReservation
from products.signals.backend.trial_policy import POLICY_VERSION, TrialPolicy, TrialRefused

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


class TrialService:
    def __init__(self, team: Team) -> None:
        self.team = team
        self.policy = TrialPolicy(team)
        self.billing = TrialBilling(team.organization)

    def billing_status(self) -> TrialBillingStatus:
        try:
            status = self.billing.status()
            if status.paid_authorized and is_team_limited(
                self.team.api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            ):
                return TrialBillingStatus(
                    ready=status.ready, migrated=status.migrated, continuation=TrialContinuation.LIMIT
                )
            return status
        except Exception:
            logger.warning(
                "signals_trial_billing_unavailable", organization_id=str(self.team.organization_id), exc_info=True
            )
            return TrialBillingStatus(ready=False, migrated=False, continuation=TrialContinuation.UNAVAILABLE)

    def activate(self, *, user_id: int) -> None:
        billing = self.billing_status()
        if not billing.ready and not (billing.migrated and self.policy.grant() is not None):
            raise TrialRefused("billing_not_ready")
        grant = self.policy.claim(user_id=user_id)
        # The grant is the durable retry key. A network failure leaves it pending, never reusable.
        try:
            acknowledged = self.billing.status(grant_id=grant.id)
        except Exception as error:
            raise TrialRefused("billing_pending") from error
        if not acknowledged.migrated:
            raise TrialRefused("billing_pending")
        SignalTrialOrganization.objects.filter(
            organization_id=self.team.organization_id, billing_migrated_at__isnull=True
        ).update(billing_migrated_at=timezone.now())

    def status(self) -> dict[str, object]:
        decision = self.policy.flag_decision()
        grant = self.policy.grant()
        organization = SignalTrialOrganization.objects.get(organization_id=self.team.organization_id)
        billing = (
            self.billing_status()
            if decision.enabled or grant
            else TrialBillingStatus(ready=False, migrated=False, continuation=TrialContinuation.UNAVAILABLE)
        )
        slots = SignalTrialReportReservation.objects.for_team(self.policy.team_id, canonical=True)
        consumed = slots.filter(status=SignalTrialReportReservation.Status.CONSUMED).count()
        reserved = slots.filter(status=SignalTrialReportReservation.Status.RESERVED).count()
        enabled_scouts = (
            SignalScoutConfig.objects.for_team(self.policy.team_id, canonical=True).filter(enabled=True).count()
        )
        ready = bool(settings.SELF_DRIVING_TRIAL_V2_BILLING_READY and billing.ready)
        eligible = bool(
            decision.enabled and decision.confirmed and grant is None and organization.grants_claimed < 3 and ready
        )
        grant_status = "not_claimed"
        if grant is not None:
            grant_status = (
                "exhausted" if grant.exhausted_at else "active" if organization.billing_migrated_at else "pending"
            )
        return {
            "enabled": decision.enabled is True,
            "flag_confirmed": decision.confirmed,
            "policy_version": POLICY_VERSION,
            "legacy_pr_restricted": self_driving_free_trial_enabled(self.team),
            "billing_ready": ready,
            "eligible": eligible,
            "organization_grants_remaining": 3 - organization.grants_claimed,
            "grant_id": grant.id if grant else None,
            "grant_status": grant_status,
            "exhaustion_reason": grant.exhaustion_reason if grant else "",
            "reports_delivered": consumed,
            "reports_reserved": reserved,
            "report_limit": grant.report_limit if grant else 5,
            "allowance_microusd": grant.allowance_microusd if grant else 10_000_000,
            "used_microusd": min(grant.settled_microusd, grant.allowance_microusd) if grant else 0,
            "reserved_microusd": grant.reserved_microusd if grant else 0,
            "enabled_scouts": enabled_scouts,
            "scout_limit": grant.scout_limit if grant else 3,
            "scouts_to_pause": max(0, enabled_scouts - 3) if grant is None else 0,
            "paid_continuation": billing.continuation,
        }
