from dataclasses import replace

import structlog

from posthog.models import Team

from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.trial.billing import TrialBilling, TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialOrganization, SignalTrialReportReservation
from products.signals.backend.trial.policy import POLICY_VERSION, TrialPolicy, TrialRefused

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
                return replace(status, continuation=TrialContinuation.LIMIT)
            return status
        except Exception:
            logger.warning(
                "signals_trial_billing_unavailable", organization_id=str(self.team.organization_id), exc_info=True
            )
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)

    def activate(self, *, user_id: int) -> None:
        if self.policy.grant() is not None:
            return
        if not self.billing_status().ready:
            raise TrialRefused("billing_not_ready")
        self.policy.claim(user_id=user_id)

    def status(self) -> dict[str, object]:
        decision = self.policy.flag_decision()
        grant = self.policy.grant()
        organization = SignalTrialOrganization.objects.filter(organization_id=self.team.organization_id).first()
        billing = (
            self.billing_status()
            if decision.enabled or grant
            else TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        )
        slots = SignalTrialReportReservation.objects.for_team(self.policy.team_id, canonical=True)
        consumed = slots.filter(status=SignalTrialReportReservation.Status.CONSUMED).count()
        reserved = slots.filter(status=SignalTrialReportReservation.Status.RESERVED).count()
        enabled_scouts = (
            SignalScoutConfig.objects.for_team(self.policy.team_id, canonical=True).filter(enabled=True).count()
        )
        ready = billing.ready
        eligible = bool(
            decision.enabled
            and decision.confirmed
            and grant is None
            and (not organization or organization.grants_claimed < 3)
            and ready
        )
        grant_status = "not_claimed"
        if grant is not None:
            grant_status = "exhausted" if grant.exhausted_at else "active"
        return {
            "enabled": decision.enabled is True or grant is not None,
            "flag_confirmed": decision.confirmed,
            "policy_version": POLICY_VERSION,
            "legacy_pr_restricted": self_driving_free_trial_enabled(self.team),
            "billing_ready": ready,
            "eligible": eligible,
            "organization_grants_remaining": 3 - organization.grants_claimed if organization else 3,
            "grant_id": grant.id if grant else None,
            "grant_status": grant_status,
            "exhaustion_reason": grant.exhaustion_reason if grant else "",
            "reports_delivered": consumed,
            "reports_reserved": reserved,
            "report_limit": grant.report_limit if grant else 5,
            "allowance_microusd": grant.allowance_microusd if grant else 10_000_000,
            "used_microusd": min(grant.settled_microusd, grant.allowance_microusd) if grant else 0,
            "accounting_pending": bool(grant and grant.incomplete_sources),
            "enabled_scouts": enabled_scouts,
            "scout_limit": grant.scout_limit if grant else 3,
            "scouts_to_pause": max(0, enabled_scouts - 3) if grant is None else 0,
            "paid_continuation": billing.continuation,
        }
