from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation

TRIAL_FLAG = "self-driving-ubp"
POLICY_VERSION = 1
logger = structlog.get_logger(__name__)


class TrialRefused(APIException):
    status_code = 402
    default_code = "self_driving_trial_unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Self-driving trial: {reason}. Check the trial and billing status in Inbox.")


@frozen
class TrialFlagDecision:
    enabled: bool | None
    confirmed: bool


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
        try:
            decision = posthoganalytics.feature_enabled(
                TRIAL_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=True,
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

    def claim(self, *, user_id: int, limits: TrialLimits = STANDARD_TRIAL_LIMITS) -> SignalTrialGrant:
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
            if self.organization_grants_claimed() >= 3:
                raise TrialRefused("organization_limit")
            grant = SignalTrialGrant.objects.for_team(self.team_id, canonical=True).create(
                team_id=self.team_id,
                organization_id=self.organization_id,
                claimed_by_id=user_id,
                allowance_microusd=limits.allowance_microusd,
                report_limit=limits.report_limit,
            )
            self._pause_excess_scouts(grant)
            transaction.on_commit(
                lambda: logger.info(
                    "signals_trial_claimed",
                    grant_id=str(grant.id),
                    organization_id=str(self.organization_id),
                    team_id=self.team_id,
                )
            )
            return grant

    def _pause_excess_scouts(self, grant: SignalTrialGrant) -> None:
        from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle

        configs = list(
            SignalScoutConfig.objects.for_team(self.team_id, canonical=True)
            .filter(enabled=True)
            .order_by("created_at", "id")
        )
        for config in configs[grant.scout_limit :]:
            config.status = SignalScoutConfig.Status.PAUSED_BY_SYSTEM
            config.enabled = False
            config.pause_reason = SignalScoutConfig.PauseReason.TRIAL_SCOUT_LIMIT
            config.status_changed_at = timezone.now()
            config.status_changed_by_id = None
            config.save(update_fields=["status", "enabled", "pause_reason", "status_changed_at", "status_changed_by"])

    @contextmanager
    def locked_grant(self, grant_id: UUID) -> Iterator[SignalTrialGrant]:
        with transaction.atomic():
            grant = SignalTrialGrant.objects.for_team(self.team_id, canonical=True).select_for_update().get(id=grant_id)
            yield grant

    def _report_slots(self, grant: SignalTrialGrant) -> int:
        return (
            SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
            .filter(
                grant=grant,
                status__in=[SignalTrialReportReservation.Status.RESERVED, SignalTrialReportReservation.Status.CONSUMED],
            )
            .count()
        )

    def _reserve_report(self, grant: SignalTrialGrant, report_id: UUID) -> None:
        slots = SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
        slot = slots.filter(report_id=report_id).first()
        if slot and slot.status != SignalTrialReportReservation.Status.RELEASED:
            return
        if self._report_slots(grant) >= grant.report_limit:
            raise TrialRefused("report_limit")
        slots.update_or_create(
            team_id=self.team_id,
            report_id=report_id,
            defaults={"grant": grant, "status": SignalTrialReportReservation.Status.RESERVED},
        )

    def admit(
        self,
        *,
        paid_authorized: bool,
        parent: TrialFunding | None = None,
        report_id: UUID | None = None,
        finishing_research: bool = False,
    ) -> TrialFunding:
        if not self.enabled():
            # Funding already promised to a pass must survive rollout changes.
            return parent or TrialFunding(funding="existing")
        grant = self.grant()
        if parent is not None and parent.grant_id is None:
            return parent
        if grant is None:
            if parent is not None:
                raise TrialRefused("grant_unavailable")
            return TrialFunding(funding="existing")
        with self.locked_grant(grant.id) as grant:
            if parent is None and grant.exhausted_at:
                if paid_authorized:
                    return TrialFunding(funding="paid")
                raise TrialRefused(grant.exhaustion_reason)
            if parent is not None and parent.grant_id != grant.id:
                raise TrialRefused("grant_unavailable")
            self.check_admitted(grant, finishing_research=finishing_research)
            if report_id is not None:
                self._reserve_report(grant, report_id)
            return parent or TrialFunding(funding="trial", grant_id=grant.id, policy_version=grant.policy_version)

    def check_funding(self, funding: TrialFunding, *, finishing_research: bool = False) -> None:
        if not self.enabled():
            return
        if funding.grant_id is not None:
            with self.locked_grant(funding.grant_id) as grant:
                self.check_admitted(grant, finishing_research=finishing_research)

    def check_admitted(self, grant: SignalTrialGrant, *, finishing_research: bool = False) -> None:
        # Report exhaustion only stops new admissions; admitted work keeps its funding.
        if not finishing_research:
            self._check_accounting(grant)

    @staticmethod
    def _check_accounting(grant: SignalTrialGrant) -> None:
        if grant.exhaustion_reason == "cost_limit" or grant.settled_microusd >= grant.allowance_microusd:
            raise TrialRefused("cost_limit")
        if grant.incomplete_since and grant.incomplete_since < timezone.now() - timedelta(minutes=2):
            raise TrialRefused("accounting_pending")

    def reserve_direct_report(self, funding: TrialFunding, report_id: UUID, *, run_id: UUID | None = None) -> None:
        if funding.grant_id is None or not self.enabled():
            return
        with self.locked_grant(funding.grant_id) as grant:
            if grant.exhausted_at is not None:
                raise TrialRefused(grant.exhaustion_reason)
            self._check_accounting(grant)
            self._reserve_report(grant, report_id)
            reservation = SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True).get(
                report_id=report_id
            )
            if run_id is not None and run_id in reservation.attempt_run_ids:
                return
            reservation.active_attempts += 1
            if run_id is not None:
                reservation.attempt_run_ids.append(run_id)
            reservation.save(update_fields=["active_attempts", "attempt_run_ids"])

    def finish_direct_report_attempt(self, report_id: UUID, *, run_id: UUID | None = None) -> None:
        reservation = (
            SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
            .filter(report_id=report_id)
            .first()
        )
        if reservation is None:
            return
        with self.locked_grant(reservation.grant_id):
            reservation.refresh_from_db()
            if run_id is not None:
                if run_id not in reservation.attempt_run_ids:
                    return
                reservation.attempt_run_ids.remove(run_id)
            reservation.active_attempts = max(0, reservation.active_attempts - 1)
            if reservation.active_attempts == 0 and reservation.status == SignalTrialReportReservation.Status.RESERVED:
                reservation.status = SignalTrialReportReservation.Status.RELEASED
            reservation.save(update_fields=["active_attempts", "attempt_run_ids", "status"])

    @contextmanager
    def publish_report(self, report_id: UUID, *, delivered: bool) -> Iterator[None]:
        reservation = (
            SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
            .filter(report_id=report_id)
            .first()
        )
        if reservation is None:
            yield
            return
        from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

        snapshot = (
            SignalReport.objects.filter(team_id=self.environment_id, id=report_id)
            .values_list("self_driving_funding", flat=True)
            .first()
        )
        funding = TrialFunding.from_dict(snapshot)
        direct = direct_report_funding.get()
        if direct and direct[0] == self.environment_id:
            funding = direct[1]
        if funding is not None and funding.grant_id is None:
            yield
            return
        with self.locked_grant(reservation.grant_id) as grant:
            reservation.refresh_from_db()
            if reservation.status == SignalTrialReportReservation.Status.RELEASED and delivered and self.enabled():
                raise TrialRefused("report_reservation_released")
            yield
            if reservation.status != SignalTrialReportReservation.Status.CONSUMED and (
                delivered or reservation.active_attempts == 0
            ):
                reservation.status = (
                    SignalTrialReportReservation.Status.CONSUMED
                    if delivered
                    else SignalTrialReportReservation.Status.RELEASED
                )
                if delivered:
                    reservation.consumed_at = timezone.now()
                reservation.save(update_fields=["status", "consumed_at"])
            consumed = (
                SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
                .filter(grant=grant, status=SignalTrialReportReservation.Status.CONSUMED)
                .count()
            )
            if consumed >= grant.report_limit and grant.exhausted_at is None:
                grant.exhausted_at = timezone.now()
                grant.exhaustion_reason = "report_limit"
                grant.save(update_fields=["exhausted_at", "exhaustion_reason"])

    def reserve_report_layers(self, parent_id: UUID, child_ids: list[UUID]) -> bool:
        if not self.enabled():
            return True
        from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

        snapshot = (
            SignalReport.objects.filter(team_id=self.environment_id, id=parent_id)
            .values_list("self_driving_funding", flat=True)
            .first()
        )
        funding = TrialFunding.from_dict(snapshot)
        if funding is not None:
            grant_id = funding.grant_id
        else:
            grant_id = (
                SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
                .filter(report_id=parent_id)
                .values_list("grant_id", flat=True)
                .first()
            )
        if grant_id is None:
            return True
        with self.locked_grant(grant_id) as grant:
            if self._report_slots(grant) + len(child_ids) > grant.report_limit:
                return False
            for child_id in child_ids:
                self._reserve_report(grant, child_id)
        return True
