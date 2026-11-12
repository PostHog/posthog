from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from rest_framework.exceptions import APIException, PermissionDenied

from posthog.dataclasses import frozen
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.errors import NonReportableError

from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.limits import MAX_TRIAL_GRANTS_PER_ORGANIZATION, STANDARD_TRIAL_LIMITS, TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.usage import trial_usage

TRIAL_FLAG = "self-driving-ubp"
PRICING_LAUNCHED_AT = datetime(2026, 11, 9, 15, 26, tzinfo=UTC)
POLICY_VERSION = 1
logger = structlog.get_logger(__name__)


class TrialRefused(APIException):
    status_code = 402
    default_code = "self_driving_trial_unavailable"

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        super().__init__(detail or f"Self-driving trial: {reason}. Check the trial and billing status in Inbox.")


class TrialExecutionRefused(TrialRefused, NonReportableError):
    def __init__(self) -> None:
        super().__init__(
            "accounted_execution_required",
            detail="Self-driving trials require the PostHog AI gateway. Choose Claude Code or Codex with PostHog model access to start this run.",
        )


@frozen
class TrialFlagDecision:
    enabled: bool | None
    confirmed: bool


def activated_before_pricing_launch(organization_id: UUID) -> bool:
    from products.signals.backend.models import (  # noqa: PLC0415 -- model registration cycle
        SignalScoutConfig,
        SignalSourceConfig,
        SignalTeamConfig,
    )

    before_launch = {"team__organization_id": organization_id, "created_at__lt": PRICING_LAUNCHED_AT}
    if SignalSourceConfig.objects.filter(**before_launch).exists():
        return True
    if SignalScoutConfig.objects.unscoped().filter(**before_launch).exists():
        return True
    completed = SignalTeamConfig.objects.filter(
        team__organization_id=organization_id, onboarding__completed_at__isnull=False
    ).values_list("onboarding__completed_at", flat=True)
    return any(isinstance(value, str) and datetime.fromisoformat(value) < PRICING_LAUNCHED_AT for value in completed)


def pricing_flag_distinct_id(organization_id: UUID) -> str:
    # The pricing flag matches grandfathered orgs through a person cohort, so it needs the distinct id
    # of a real person, not the org id. One fixed member per org gives every caller the same answer,
    # including pipeline work that has no request user. An org that activated self-driving after the
    # pricing launch cannot be grandfathered, so it uses the org id, which no cohort matches. Otherwise
    # a cohort member would pass grandfathered pricing to every new org they set up.
    if not activated_before_pricing_launch(organization_id):
        return str(organization_id)
    distinct_id = (
        OrganizationMembership.objects.filter(organization_id=organization_id, user__is_active=True)
        .order_by("joined_at", "id")
        .values_list("user__distinct_id", flat=True)
        .first()
    )
    return distinct_id or str(organization_id)


def spend_billing_starts_later(organization_id: UUID) -> bool:
    cutoff = (
        Organization.objects.filter(id=organization_id)
        .values_list("usage__signals_spend_credits__billing_start_date", flat=True)
        .first()
    )
    return isinstance(cutoff, str) and date.fromisoformat(cutoff) > timezone.now().date()


def lock_organization_trial(organization_id: UUID) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"signals-trial:{organization_id}"])


class TrialPolicy:
    def __init__(self, team: Team) -> None:
        self.environment_id = team.pk
        self.team_id = team.parent_team_id or team.pk
        self.organization_id = team.organization_id

    def flag_decision(self) -> TrialFlagDecision:
        org_id = str(self.organization_id)
        decision: bool | None
        try:
            # Billing has not moved this organization to usage-based pricing yet, so the trial does not apply.
            # The flag cannot exclude an organization that is evaluated as the org id, which no cohort matches.
            if spend_billing_starts_later(self.organization_id):
                decision = False
            else:
                # Remote evaluation is required because the SDK cannot evaluate a static cohort locally.
                decision = posthoganalytics.feature_enabled(
                    TRIAL_FLAG,
                    pricing_flag_distinct_id(self.organization_id),
                    groups={"organization": org_id},
                    group_properties={"organization": {"id": org_id}},
                    send_feature_flag_events=False,
                )
        except Exception:
            decision = None
        confirmed = type(decision) is bool
        key = f"signals:trial-flag:{org_id}"
        try:
            if confirmed:
                cache.set(key, decision, timeout=None)
            else:
                decision = cache.get(key)
        except Exception:
            logger.warning("signals_trial_flag_cache_unavailable", organization_id=org_id, exc_info=True)
        return TrialFlagDecision(enabled=decision if type(decision) is bool else None, confirmed=confirmed)

    def organization_grants_claimed(self) -> int:
        return SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization_id).count()

    def enabled(self) -> bool:
        return self.flag_decision().enabled is True

    def check_enabled(self) -> None:
        decision = self.flag_decision()
        if not decision.confirmed or decision.enabled is not True:
            raise TrialRefused("flag_unavailable" if not decision.confirmed else "not_enabled")

    def grant(self) -> SignalTrialGrant | None:
        return SignalTrialGrant.objects.for_team(self.team_id, canonical=True).first()

    def active_grant(self) -> SignalTrialGrant | None:
        grant = self.grant()
        return grant if grant is not None and self.enabled() else None

    def admission_grant(self) -> SignalTrialGrant | None:
        grant = self.grant()
        if grant is None:
            return None
        decision = self.flag_decision()
        if decision.enabled is None:
            raise TrialRefused("flag_unavailable")
        return grant if decision.enabled else None

    def claim(
        self, *, user_id: int, limits: TrialLimits = STANDARD_TRIAL_LIMITS, api_scopes: list[str] | None = None
    ) -> SignalTrialGrant:
        from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle

        self.check_enabled()
        existing = self.grant()
        if existing is not None:
            return existing
        with transaction.atomic():
            # Scout writers acquire their config before the organization lock too.
            list(SignalScoutConfig.objects.for_team(self.team_id, canonical=True).select_for_update().order_by("id"))
            lock_organization_trial(self.organization_id)
            existing = self.grant()
            if existing is not None:
                return existing
            if self.organization_grants_claimed() >= MAX_TRIAL_GRANTS_PER_ORGANIZATION:
                raise TrialRefused("organization_limit")
            grant = SignalTrialGrant.objects.for_team(self.team_id, canonical=True).create(
                team_id=self.team_id,
                organization_id=self.organization_id,
                claimed_by_id=user_id,
                allowance_microusd=limits.allowance_microusd,
                report_limit=limits.report_limit,
            )
            self._pause_excess_scouts(grant, api_scopes=api_scopes)
            transaction.on_commit(
                lambda: logger.info(
                    "signals_trial_claimed",
                    grant_id=str(grant.id),
                    organization_id=str(self.organization_id),
                    team_id=self.team_id,
                )
            )
            return grant

    def _pause_excess_scouts(self, grant: SignalTrialGrant, *, api_scopes: list[str] | None) -> None:
        from products.signals.backend.scout_harness.lifecycle_lock import (
            user_holds_scout_lifecycle_claims,  # noqa: PLC0415 -- lifecycle permissions depend on Signals models
        )
        from products.signals.backend.trial.scouts import (  # noqa: PLC0415 -- the scout rules import this module
            pause_for_trial_scout_limit,
            trial_counted_scouts,
        )

        configs = list(trial_counted_scouts(self.team_id).order_by("created_at", "id"))
        excess = configs[grant.scout_limit :]
        if excess and api_scopes is not None and not {"*", "signal_scout:write"}.intersection(api_scopes):
            raise PermissionDenied("Starting this trial would pause scouts and requires signal_scout:write access.")
        locked = [config for config in excess if config.lifecycle_locked]
        if locked:
            team = Team.objects.get(pk=self.team_id)
            user = User.objects.get(pk=grant.claimed_by_id)
            if not user_holds_scout_lifecycle_claims(team=team, configs=locked, user=user):
                raise PermissionDenied(
                    "Starting this trial would pause a locked scout. Only the person its runs act as or a project admin can do that."
                )
        for config in excess:
            pause_for_trial_scout_limit(config)

    @contextmanager
    def locked_grant(self, grant_id: UUID) -> Iterator[SignalTrialGrant]:
        with transaction.atomic():
            grant = SignalTrialGrant.objects.for_team(self.team_id, canonical=True).select_for_update().get(id=grant_id)
            yield grant

    def admit(
        self,
        *,
        paid_authorized: bool,
        parent: TrialFunding | None = None,
        report_id: UUID | None = None,
        report_pass_key: str | None = None,
    ) -> TrialFunding:
        if parent is not None and parent.grant_id is None:
            return parent
        grant = self.admission_grant() if parent is None else self.grant()
        if grant is None:
            if parent is not None:
                raise TrialRefused("grant_unavailable")
            return TrialFunding(funding="existing")
        from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

        with transaction.atomic():
            # Report transitions already lock their row before admission locks the grant.
            if report_id is not None:
                report = SignalReport.objects.select_for_update().get(id=report_id, team_id=self.environment_id)
                previous = TrialFunding.from_dict(report.self_driving_funding)
                if (
                    parent is None
                    and previous is not None
                    and (report_pass_key is None or previous.report_pass_key == report_pass_key)
                ):
                    return previous
            with self.locked_grant(grant.id) as grant:
                if parent is not None and parent.grant_id != grant.id:
                    raise TrialRefused("grant_unavailable")
                if parent is not None:
                    funding = parent
                else:
                    reason = trial_usage(grant).exhaustion_reason(grant)
                    if reason:
                        if not paid_authorized:
                            raise TrialRefused(reason)
                        funding = TrialFunding(funding="paid")
                    else:
                        funding = TrialFunding(funding="trial", grant_id=grant.id)
                if report_id is not None:
                    # Task admission must not erase the enclosing report pass's retry identity.
                    previous = TrialFunding.from_dict(report.self_driving_funding)
                    if previous is not None and not funding.report_pass_key:
                        funding = replace(funding, report_pass_key=previous.report_pass_key)
                    report.self_driving_funding = funding.as_dict()
                    report.save(update_fields=["self_driving_funding"])
                return funding
