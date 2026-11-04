from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import replace
from typing import Literal

from django.db import transaction

import structlog
from rest_framework.exceptions import PermissionDenied

from posthog.event_usage import report_user_action
from posthog.models import OrganizationMembership, Team, User
from posthog.user_permissions import UserPermissions

from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.trial.billing import TrialBilling, TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialReportReservation
from products.signals.backend.trial.policy import POLICY_VERSION, TrialPolicy, TrialRefused

from ee.billing.quota_limiting import QuotaLimitingCaches, is_team_limited, self_driving_quota_resource

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
                self.team.api_token,
                self_driving_quota_resource(self.team.organization),
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            ):
                return replace(status, continuation=TrialContinuation.LIMIT)
            return status
        except Exception:
            logger.warning(
                "signals_trial_billing_unavailable", organization_id=str(self.team.organization_id), exc_info=True
            )
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)

    def _capture_enrollment(
        self,
        user: User,
        *,
        source: Literal["explicit", "activation"],
        outcome: str,
        reason: str | None = None,
        grant_id: str | None = None,
    ) -> None:
        report_user_action(
            user=user,
            event="self-driving trial enrollment",
            team=self.team,
            properties={
                "source": source,
                "outcome": outcome,
                "reason": reason,
                "grant_id": grant_id,
                "policy_version": POLICY_VERSION,
            },
        )

    def _capture_enrollment_error(
        self, user: User, source: Literal["explicit", "activation"], error: Exception
    ) -> None:
        refused = isinstance(error, (TrialRefused, PermissionDenied))
        reason = (
            error.reason if isinstance(error, TrialRefused) else "permission_denied" if refused else "activation_failed"
        )
        self._capture_enrollment(user, source=source, outcome="refused" if refused else "failed", reason=reason)

    @contextmanager
    def _enrollment_outcome(self, user: User, *, source: Literal["explicit", "activation"]) -> Iterator[None]:
        existing = self.policy.grant() is not None
        try:
            yield
        except Exception as error:
            self._capture_enrollment_error(user, source, error)
            raise
        else:
            grant = self.policy.grant()
            outcome = "already_claimed" if existing else "activated" if grant else "paid_continuation"
            transaction.on_commit(
                lambda: self._capture_enrollment(
                    user, source=source, outcome=outcome, grant_id=str(grant.id) if grant else None
                ),
                robust=True,
            )

    def _check_membership(self, user: User) -> None:
        level = UserPermissions(
            user=user, team=self.team.parent_team or self.team
        ).current_team.effective_membership_level
        if level is None or level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("You need access to this project to start a trial.")

    def activate(self, *, user_id: int, api_scopes: list[str] | None) -> None:
        user = User.objects.get(pk=user_id)
        self._capture_enrollment(user, source="explicit", outcome="attempted")
        with self._enrollment_outcome(user, source="explicit"):
            self.policy.check_enabled()
            self._check_membership(user)
            if self.policy.grant() is not None:
                return
            billing = self.billing_status()
            if not billing.ready:
                raise TrialRefused("billing_not_ready")
            self.policy.claim(user_id=user_id, limits=billing.limits, api_scopes=api_scopes)

    def enroll_on_activation(
        self, *, user: User, enabled: bool, api_scopes: list[str] | None, parent_access_allowed: bool = False
    ) -> AbstractContextManager[None]:
        if not enabled or not self.policy.enabled() or self.policy.grant() is not None:
            return nullcontext()
        self._capture_enrollment(user, source="activation", outcome="attempted")
        try:
            self.policy.check_enabled()
            if self.team.parent_team_id and not parent_access_allowed:
                raise PermissionDenied("You don't have access to the project that owns this data.")
            self._check_membership(user)
            billing = self.billing_status()
            if not billing.ready:
                raise TrialRefused("billing_not_ready")
        except Exception as error:
            self._capture_enrollment_error(user, "activation", error)
            raise
        return self._claim_on_activation(user=user, billing=billing, api_scopes=api_scopes)

    @contextmanager
    def _claim_on_activation(
        self, *, user: User, billing: TrialBillingStatus, api_scopes: list[str] | None
    ) -> Iterator[None]:
        # Read billing before taking locks; roll back the grant if the activation write fails.
        with self._enrollment_outcome(user, source="activation"), transaction.atomic():
            try:
                self.policy.claim(user_id=user.pk, limits=billing.limits, api_scopes=api_scopes)
            except TrialRefused as error:
                if error.reason != "organization_limit" or not billing.paid_authorized:
                    raise
            yield

    def status(self) -> dict[str, object]:
        decision = self.policy.flag_decision()
        grant = self.policy.grant()
        grants_claimed = self.policy.organization_grants_claimed()
        billing = (
            self.billing_status()
            if decision.enabled
            else TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        )
        slots = SignalTrialReportReservation.objects.for_team(self.policy.team_id, canonical=True)
        consumed = slots.filter(status=SignalTrialReportReservation.Status.CONSUMED).count()
        reserved = slots.filter(status=SignalTrialReportReservation.Status.RESERVED).count()
        enabled_scouts = (
            SignalScoutConfig.objects.for_team(self.policy.team_id, canonical=True).filter(enabled=True).count()
        )
        ready = billing.ready
        eligible = bool(decision.enabled and decision.confirmed and grant is None and grants_claimed < 3 and ready)
        grant_status = "not_claimed"
        if grant is not None:
            grant_status = "exhausted" if grant.exhausted_at else "active"
        return {
            "enabled": decision.enabled is True,
            "flag_confirmed": decision.confirmed,
            "policy_version": POLICY_VERSION,
            "legacy_pr_restricted": self_driving_free_trial_enabled(self.team),
            "billing_ready": ready,
            "eligible": eligible,
            "organization_grants_remaining": 3 - grants_claimed,
            "grant_id": grant.id if grant else None,
            "grant_status": grant_status,
            "exhaustion_reason": grant.exhaustion_reason if grant else "",
            "reports_delivered": consumed,
            "reports_reserved": reserved,
            "report_limit": grant.report_limit if grant else billing.limits.report_limit,
            "allowance_microusd": grant.allowance_microusd if grant else billing.limits.allowance_microusd,
            "used_microusd": min(grant.settled_microusd, grant.allowance_microusd) if grant else 0,
            "accounting_pending": bool(grant and grant.incomplete_sources),
            "enabled_scouts": enabled_scouts,
            "scout_limit": grant.scout_limit if grant else 3,
            "scouts_to_pause": max(0, enabled_scouts - 3) if grant is None else 0,
            "paid_continuation": billing.continuation,
        }
