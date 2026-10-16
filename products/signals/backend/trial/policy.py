from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.signals.backend.trial.models import (
    SignalTrialGrant,
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)

TRIAL_FLAG = "self-driving-free-tier-v2"
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


@frozen
class OperationAdmission:
    operation_key: str
    stage: SignalTrialOperation.Stage
    model: str = ""
    runtime: str = ""
    report_id: UUID | None = None
    report_pass_id: UUID | None = None


class TrialPolicy:
    def __init__(self, team: Team) -> None:
        self.environment_id = team.pk
        self.team_id = team.parent_team_id or team.pk
        self.organization_id = team.organization_id

    def flag_decision(self) -> TrialFlagDecision:
        checked_at = timezone.now()
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
        allocation = SignalTrialOrganization.objects.filter(organization_id=self.organization_id).first()
        if allocation is None:
            if decision is not True:
                return TrialFlagDecision(enabled=decision if confirmed else None, confirmed=confirmed)
            allocation, _ = SignalTrialOrganization.objects.get_or_create(organization_id=self.organization_id)
        if confirmed and allocation.flag_enabled is not decision:
            SignalTrialOrganization.objects.filter(organization_id=self.organization_id).filter(
                Q(flag_checked_at__isnull=True) | Q(flag_checked_at__lt=checked_at)
            ).update(flag_enabled=decision, flag_checked_at=checked_at)
            allocation.refresh_from_db(fields=["flag_enabled"])
        if allocation.flag_enabled and not settings.SELF_DRIVING_TRIAL_V2_BILLING_READY:
            logger.info("signals_trial_shadow_decision", organization_id=org_id, confirmed=confirmed)
        return TrialFlagDecision(enabled=allocation.flag_enabled, confirmed=confirmed)

    def grant(self) -> SignalTrialGrant | None:
        return (
            SignalTrialGrant.objects.for_team(self.team_id, canonical=True)
            .filter(organization_id=self.organization_id)
            .first()
        )

    def claim(self, *, user_id: int) -> SignalTrialGrant:
        from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle

        existing = self.grant()
        if existing is not None:
            return existing
        decision = self.flag_decision()
        if not decision.confirmed or decision.enabled is not True:
            raise TrialRefused("flag_unavailable" if not decision.confirmed else "not_enabled")
        if not getattr(settings, "SELF_DRIVING_TRIAL_V2_BILLING_READY", False):
            raise TrialRefused("billing_not_ready")
        with transaction.atomic():
            # Scout writers lock their config before the quiet organization allocation row.
            # Recount after that allocation lock, so a concurrent new config is included too.
            list(SignalScoutConfig.objects.for_team(self.team_id, canonical=True).select_for_update().order_by("id"))
            allocation = SignalTrialOrganization.objects.select_for_update().get(organization_id=self.organization_id)
            existing = self.grant()
            if existing is not None:
                return existing
            if allocation.flag_enabled is not True:
                raise TrialRefused("not_enabled")
            if allocation.grants_claimed >= 3:
                raise TrialRefused("organization_limit")
            grant = SignalTrialGrant.objects.for_team(self.team_id, canonical=True).create(
                team_id=self.team_id, organization=allocation, claimed_by_id=user_id
            )
            allocation.grants_claimed += 1
            allocation.save(update_fields=["grants_claimed"])
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
            grant = (
                SignalTrialGrant.objects.for_team(self.team_id, canonical=True)
                .select_for_update()
                .get(id=grant_id, organization_id=self.organization_id)
            )
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
        self, admission: OperationAdmission, *, paid_authorized: bool, decision: TrialFlagDecision | None = None
    ) -> SignalTrialOperation:
        operations = SignalTrialOperation.objects.for_team(self.team_id, canonical=True)
        existing = operations.filter(operation_key=admission.operation_key).first()
        if existing is not None:
            return existing
        decision = decision if decision is not None else self.flag_decision()
        grant = self.grant()
        funding: str = SignalTrialOperation.Funding.EXISTING
        parent = (
            operations.filter(id=admission.report_pass_id, finished_at__isnull=True).first()
            if admission.report_pass_id
            else None
        )
        if admission.report_pass_id and parent is None:
            raise TrialRefused("report_pass_finished")
        if parent is not None:
            funding = parent.funding
            grant = self.grant() if parent.grant_id else None
        elif decision.enabled is True:
            if grant is None or grant.exhausted_at is not None:
                if not paid_authorized:
                    raise TrialRefused("start_trial" if grant is None else grant.exhaustion_reason)
                funding = SignalTrialOperation.Funding.PAID
            else:
                funding = SignalTrialOperation.Funding.TRIAL
        if funding != SignalTrialOperation.Funding.TRIAL:
            operation, _ = operations.get_or_create(
                team_id=self.team_id,
                operation_key=admission.operation_key,
                defaults=self._operation_defaults(admission, funding=funding),
            )
            return operation
        assert grant is not None
        with self.locked_grant(grant.id) as grant:
            existing = operations.filter(operation_key=admission.operation_key).first()
            if existing is not None:
                return existing
            finishing_research = parent is not None and self._executing_research(parent)
            if grant.exhausted_at is not None and not (
                parent and (grant.exhaustion_reason == "report_limit" or finishing_research)
            ):
                raise TrialRefused(grant.exhaustion_reason)
            if not SignalTrialOrganization.objects.filter(
                organization_id=self.organization_id, billing_migrated_at__isnull=False
            ).exists():
                raise TrialRefused("billing_pending")
            if not finishing_research:
                self._check_accounting(grant)
            if admission.report_id is not None and admission.stage in {
                SignalTrialOperation.Stage.RESEARCH,
                SignalTrialOperation.Stage.REPORT_PASS,
            }:
                self._reserve_report(grant, admission.report_id)
            operation = operations.create(
                team_id=self.team_id,
                operation_key=admission.operation_key,
                grant=grant,
                **self._operation_defaults(admission, funding=funding),
            )
            return operation

    def _operation_defaults(self, admission: OperationAdmission, *, funding: str) -> dict[str, object]:
        return {
            "environment_id": self.environment_id,
            "organization_id": self.organization_id,
            "funding": funding,
            "policy_version": POLICY_VERSION,
            "stage": admission.stage,
            "report_id": admission.report_id,
            "report_pass_id": admission.report_pass_id,
            "model": admission.model,
            "runtime": admission.runtime,
        }

    def start(self, operation_id: UUID, *, mark_started: bool = True) -> SignalTrialOperation:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return operation
        with self.locked_grant(operation.grant_id) as grant:
            operation.refresh_from_db()
            if operation.finished_at or operation.cancel_requested_at:
                raise TrialRefused("operation_finished")
            if grant.exhaustion_reason == "cost_limit" and not self._executing_research(operation):
                raise TrialRefused("cost_limit")
            if not self._executing_research(operation):
                self._check_accounting(grant)
            if operation.started_at is None and mark_started:
                operation.started_at = timezone.now()
                operation.save(update_fields=["started_at"])
                if operation.stage == SignalTrialOperation.Stage.RESEARCH and operation.report_pass_id:
                    SignalTrialOperation.objects.for_team(self.team_id, canonical=True).filter(
                        id=operation.report_pass_id,
                        grant=grant,
                        started_at__isnull=True,
                    ).update(started_at=timezone.now())
            return operation

    @staticmethod
    def _executing_research(operation: SignalTrialOperation) -> bool:
        return (
            operation.stage
            in {
                SignalTrialOperation.Stage.RESEARCH,
                SignalTrialOperation.Stage.REPORT_PASS,
            }
            and operation.started_at is not None
        )

    @staticmethod
    def _check_accounting(grant: SignalTrialGrant) -> None:
        if grant.settled_microusd >= grant.allowance_microusd:
            raise TrialRefused("cost_limit")
        if grant.incomplete_since and grant.incomplete_since < timezone.now() - timedelta(minutes=2):
            raise TrialRefused("accounting_pending")

    def reserve_direct_report(self, operation_id: UUID, report_id: UUID) -> None:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return
        with self.locked_grant(operation.grant_id) as grant:
            if grant.exhausted_at is not None:
                raise TrialRefused(grant.exhaustion_reason)
            self._reserve_report(grant, report_id)
            reservation = SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True).get(
                report_id=report_id
            )
            reservation.active_attempts += 1
            if operation.id not in reservation.attempt_operation_ids:
                reservation.attempt_operation_ids.append(operation.id)
            reservation.save(update_fields=["active_attempts", "attempt_operation_ids"])

    def release_abandoned_report_attempts(self, operation: SignalTrialOperation) -> None:
        if operation.grant_id is None:
            return
        with self.locked_grant(operation.grant_id):
            reservations = SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True).filter(
                grant_id=operation.grant_id,
                status=SignalTrialReportReservation.Status.RESERVED,
                attempt_operation_ids__contains=[operation.id],
            )
            for reservation in reservations:
                if (
                    not SignalTrialOperation.objects.for_team(self.team_id, canonical=True)
                    .filter(id__in=reservation.attempt_operation_ids, finished_at__isnull=True)
                    .exists()
                ):
                    reservation.status = SignalTrialReportReservation.Status.RELEASED
                    reservation.active_attempts = 0
                    reservation.save(update_fields=["status", "active_attempts"])

    def finish_direct_report_attempt(self, report_id: UUID) -> None:
        reservation = (
            SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
            .filter(report_id=report_id)
            .first()
        )
        if reservation is None:
            return
        with self.locked_grant(reservation.grant_id):
            reservation.refresh_from_db()
            reservation.active_attempts = max(0, reservation.active_attempts - 1)
            if reservation.active_attempts == 0 and reservation.status == SignalTrialReportReservation.Status.RESERVED:
                reservation.status = SignalTrialReportReservation.Status.RELEASED
            reservation.save(update_fields=["active_attempts", "status"])

    @contextmanager
    def publish_report(self, report_id: UUID, *, delivered: bool) -> Iterator[None]:
        reservation = (
            SignalTrialReportReservation.objects.for_team(self.team_id, canonical=True)
            .filter(report_id=report_id)
            .first()
        )
        if reservation is None:
            yield
            self._finish_report_passes(report_id)
            return
        funding = (
            SignalTrialOperation.objects.for_team(self.team_id, canonical=True)
            .filter(report_id=report_id, stage=SignalTrialOperation.Stage.REPORT_PASS)
            .order_by("-admitted_at")
            .values_list("funding", flat=True)
            .first()
        )
        if funding in {SignalTrialOperation.Funding.PAID, SignalTrialOperation.Funding.EXISTING}:
            yield
            self._finish_report_passes(report_id)
            return
        with self.locked_grant(reservation.grant_id) as grant:
            reservation.refresh_from_db()
            if reservation.status == SignalTrialReportReservation.Status.RELEASED and delivered:
                raise TrialRefused("report_reservation_released")
            yield
            if reservation.status != SignalTrialReportReservation.Status.CONSUMED:
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
            self._finish_report_passes(report_id)

    def _finish_report_passes(self, report_id: UUID) -> None:
        for operation in SignalTrialOperation.objects.for_team(self.team_id, canonical=True).filter(
            report_id=report_id, stage=SignalTrialOperation.Stage.REPORT_PASS, finished_at__isnull=True
        ):
            self.finish(operation.id)

    def reserve_report_layers(self, parent_id: UUID, child_ids: list[UUID]) -> bool:
        operations = SignalTrialOperation.objects.for_team(self.team_id, canonical=True)
        parent_pass = (
            operations.filter(report_id=parent_id, stage=SignalTrialOperation.Stage.REPORT_PASS)
            .order_by("-admitted_at")
            .first()
        )
        if parent_pass is not None:
            grant_id = parent_pass.grant_id
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

    def finish(self, operation_id: UUID) -> None:
        SignalTrialOperation.objects.for_team(self.team_id, canonical=True).filter(
            id=operation_id, finished_at__isnull=True
        ).update(finished_at=timezone.now())
