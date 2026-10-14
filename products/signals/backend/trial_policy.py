from collections.abc import Iterator
from contextlib import contextmanager
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

from products.signals.backend.trial_models import (
    SignalTrialCostSource,
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
    estimated_microusd: int
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
            )
        except Exception:
            decision = None
        allocation, _ = SignalTrialOrganization.objects.get_or_create(organization_id=self.organization_id)
        confirmed = type(decision) is bool
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
        if admission.estimated_microusd <= 0:
            raise ValueError("Admission requires a positive bounded cost estimate")
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
            if grant.exhausted_at is not None and not (parent and grant.exhaustion_reason == "report_limit"):
                raise TrialRefused(grant.exhaustion_reason)
            if not SignalTrialOrganization.objects.filter(
                organization_id=self.organization_id, billing_migrated_at__isnull=False
            ).exists():
                raise TrialRefused("billing_pending")
            if (
                grant.settled_microusd + grant.reserved_microusd + admission.estimated_microusd
                > grant.allowance_microusd
            ):
                raise TrialRefused("allowance_reserved")
            if admission.report_id is not None and admission.stage in {
                SignalTrialOperation.Stage.RESEARCH,
                SignalTrialOperation.Stage.REPORT_PASS,
            }:
                self._reserve_report(grant, admission.report_id)
            operation = operations.create(
                team_id=self.team_id,
                operation_key=admission.operation_key,
                grant=grant,
                reserved_microusd=admission.estimated_microusd,
                **self._operation_defaults(admission, funding=funding),
            )
            grant.reserved_microusd += admission.estimated_microusd
            grant.save(update_fields=["reserved_microusd"])
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
            "estimated_microusd": admission.estimated_microusd,
        }

    def start(self, operation_id: UUID, *, mark_started: bool = True) -> SignalTrialOperation:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return operation
        with self.locked_grant(operation.grant_id) as grant:
            operation.refresh_from_db()
            if operation.finished_at or operation.cancel_requested_at:
                raise TrialRefused("operation_finished")
            if grant.exhaustion_reason == "cost_limit" and not (
                operation.stage in {SignalTrialOperation.Stage.RESEARCH, SignalTrialOperation.Stage.REPORT_PASS}
                and operation.started_at is not None
            ):
                raise TrialRefused("cost_limit")
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
            reservation.save(update_fields=["active_attempts"])

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

    def reserve_finalization(self, operation_id: UUID, amount: int) -> None:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return
        with self.locked_grant(operation.grant_id) as grant:
            operation.refresh_from_db()
            if operation.finished_at or operation.cancel_requested_at:
                raise TrialRefused("report_pass_finished")
            executing_research = (
                operation.stage in {SignalTrialOperation.Stage.REPORT_PASS, SignalTrialOperation.Stage.RESEARCH}
                and operation.started_at is not None
            )
            if (
                not executing_research
                and grant.settled_microusd + grant.reserved_microusd + amount > grant.allowance_microusd
            ):
                raise TrialRefused("allowance_reserved")
            operation.estimated_microusd += amount
            operation.reserved_microusd += amount
            grant.reserved_microusd += amount
            operation.save(update_fields=["estimated_microusd", "reserved_microusd"])
            grant.save(update_fields=["reserved_microusd"])

    def reserve_task_gateway(self, operation_id: UUID, amount: int) -> None:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return
        with self.locked_grant(operation.grant_id):
            operation.refresh_from_db()
            if operation.gateway_mint_attempts:
                self.reserve_finalization(operation_id, amount)
            operation.gateway_mint_attempts += 1
            operation.save(update_fields=["gateway_mint_attempts"])

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

    def reconcile(
        self,
        *,
        operation_id: UUID,
        source_id: str,
        is_task: bool,
        token_cost_microusd: int | None,
        compute_cost_microusd: int | None,
        complete: bool,
    ) -> None:
        if any(value is not None and value < 0 for value in (token_cost_microusd, compute_cost_microusd)):
            raise ValueError("Costs cannot be negative")
        if complete and (token_cost_microusd is None or compute_cost_microusd is None):
            raise ValueError("Complete accounting requires both cost components")
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            return
        with self.locked_grant(operation.grant_id) as grant:
            operation.refresh_from_db()
            sources = SignalTrialCostSource.objects.for_team(self.team_id, canonical=True)
            source, _ = sources.get_or_create(
                team_id=self.team_id, source_id=source_id, is_task=is_task, defaults={"operation": operation}
            )
            if source.operation_id != operation.id:
                raise ValueError("A cost source cannot change its funding operation")
            if token_cost_microusd is not None:
                source.token_cost_microusd = max(source.token_cost_microusd or 0, token_cost_microusd)
            if compute_cost_microusd is not None:
                source.compute_cost_microusd = max(source.compute_cost_microusd or 0, compute_cost_microusd)
            source.complete = complete
            source.save()
            self._refresh_operation_cost(operation, grant)

    def finish(self, operation_id: UUID) -> None:
        operation = SignalTrialOperation.objects.for_team(self.team_id, canonical=True).get(id=operation_id)
        if operation.grant_id is None:
            SignalTrialOperation.objects.for_team(self.team_id, canonical=True).filter(
                id=operation.id, finished_at__isnull=True
            ).update(finished_at=timezone.now())
            return
        with self.locked_grant(operation.grant_id) as grant:
            operation.refresh_from_db()
            operation.finished_at = operation.finished_at or timezone.now()
            operation.save(update_fields=["finished_at"])
            self._refresh_operation_cost(operation, grant)

    def _refresh_operation_cost(self, operation: SignalTrialOperation, grant: SignalTrialGrant) -> None:
        sources = list(SignalTrialCostSource.objects.for_team(self.team_id, canonical=True).filter(operation=operation))
        cost = sum((source.token_cost_microusd or 0) + (source.compute_cost_microusd or 0) for source in sources)
        complete = bool(sources) and all(source.complete for source in sources) and operation.finished_at is not None
        # Unknown sources retain their full hold, including work which produced no report.
        reserved = 0 if complete else max(operation.estimated_microusd - cost, 0)
        grant.settled_microusd += cost - operation.settled_microusd
        grant.reserved_microusd += reserved - operation.reserved_microusd
        operation.settled_microusd = cost
        operation.reserved_microusd = reserved
        operation.accounting_complete = complete
        operation.save(update_fields=["settled_microusd", "reserved_microusd", "accounting_complete"])
        grant.overrun_microusd = max(0, grant.settled_microusd - grant.allowance_microusd)
        if grant.settled_microusd >= grant.allowance_microusd:
            grant.exhausted_at = grant.exhausted_at or timezone.now()
            grant.exhaustion_reason = "cost_limit"
            SignalTrialOperation.objects.for_team(self.team_id, canonical=True).filter(
                grant=grant, finished_at__isnull=True, cancel_requested_at__isnull=True
            ).exclude(
                stage__in=[SignalTrialOperation.Stage.RESEARCH, SignalTrialOperation.Stage.REPORT_PASS],
                started_at__isnull=False,
            ).update(cancel_requested_at=timezone.now())
        grant.save(
            update_fields=[
                "settled_microusd",
                "reserved_microusd",
                "overrun_microusd",
                "exhausted_at",
                "exhaustion_reason",
            ]
        )
        logger.info(
            "signals_trial_reconciled",
            grant_id=str(grant.id),
            operation_id=str(operation.id),
            team_id=self.team_id,
            settled_microusd=grant.settled_microusd,
            reserved_microusd=grant.reserved_microusd,
            overrun_microusd=grant.overrun_microusd,
            accounting_complete=complete,
            exhaustion_reason=grant.exhaustion_reason,
        )
