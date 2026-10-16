from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections, transaction
from django.test import override_settings
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.facade.trial import TaskTrialAdmission
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial_models import (
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)
from products.signals.backend.trial_policy import OperationAdmission, TrialPolicy, TrialRefused
from products.tasks.backend.models import Task


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
    def test_admission_and_cost_settlement_do_not_invert_locks(self) -> None:
        with patch("products.signals.backend.trial_policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
            SignalTrialOrganization.objects.filter(organization_id=self.organization.pk).update(
                billing_migrated_at=timezone.now()
            )
            signal_id = str(uuid4())
            report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
            task = Task.objects.create(
                team=self.team, title="Concurrent run", origin_product="signal_report", signal_report_id=report.id
            )
            record_llm_spend(
                "initial",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="research",
                token_cost_microusd=1,
                trial_grant_id=str(grant.id),
            )
            spend_locked, grant_locked = Event(), Event()
            original_bind = TaskTrialAdmission.bind

            def bind(
                admission: TaskTrialAdmission,
                *,
                run_id: UUID,
                origin: str,
                stage: str,
                report_id: UUID | None,
                model: str,
                runtime: str,
            ) -> dict[str, str | int]:
                result = original_bind(
                    admission,
                    run_id=run_id,
                    origin=origin,
                    stage=stage,
                    report_id=report_id,
                    model=model,
                    runtime=runtime,
                )
                grant_locked.set()
                assert spend_locked.wait(timeout=10)
                return result

            def settle() -> None:
                close_old_connections()
                try:
                    with transaction.atomic():
                        SignalSpend.objects.for_team(self.team.id).select_for_update().get(signal_id=signal_id)
                        spend_locked.set()
                        assert grant_locked.wait(timeout=10)
                        record_llm_spend(
                            "late",
                            team_id=self.team.id,
                            signal_id=signal_id,
                            stage="research",
                            token_cost_microusd=2,
                            trial_grant_id=str(grant.id),
                        )
                finally:
                    close_old_connections()

            def create_run() -> None:
                close_old_connections()
                try:
                    task.create_run()
                finally:
                    close_old_connections()

            with (
                patch.object(TaskTrialAdmission, "bind", bind),
                patch("products.tasks.backend.models.execute_after_commit", side_effect=transaction.on_commit),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first, second = pool.submit(settle), pool.submit(create_run)
                first.result(timeout=20)
                second.result(timeout=20)
            grant.refresh_from_db()
            assert grant.settled_microusd == 3
            assert task.runs.count() == 1

    @override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
    def test_concurrent_plans_reserve_all_layers_or_publish_only_parent(self) -> None:
        with patch("products.signals.backend.trial_policy.posthoganalytics.feature_enabled", return_value=True):
            policy = TrialPolicy(self.team)
            policy.claim(user_id=self.user.pk)
            SignalTrialOrganization.objects.filter(organization_id=self.organization.pk).update(
                billing_migrated_at=timezone.now()
            )
            parents = [
                SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS) for _ in range(2)
            ]
            for parent in parents:
                policy.admit(
                    OperationAdmission(
                        operation_key=str(parent.id),
                        report_id=parent.id,
                        stage=SignalTrialOperation.Stage.REPORT_PASS,
                    ),
                    paid_authorized=False,
                )
                parent.status = SignalReport.Status.READY
                parent.save(update_fields=["status"])
            barrier = Barrier(2)

            def publish_layers(parent: SignalReport) -> int:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    return len(
                        create_layer_reports(
                            parent=parent,
                            layers=[
                                ReportLayer(title="First", scope="First step"),
                                ReportLayer(title="Second", scope="Second step", depends_on=0),
                            ],
                            attribution=ArtefactAttribution.system(),
                        )
                    )
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(publish_layers, parents)) == [0, 2]
            assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count() == 4
            assert not SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="reserved").exists()

    @override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
    def test_final_organization_slot_and_report_slot_are_atomic(self) -> None:
        with patch("products.signals.backend.trial_policy.posthoganalytics.feature_enabled", return_value=True):
            TrialPolicy(self.team).claim(user_id=self.user.pk)
            second = Team.objects.create(organization=self.organization, name="Second")
            TrialPolicy(second).claim(user_id=self.user.pk)
            contenders = [Team.objects.create(organization=self.organization, name=f"Project {i}") for i in range(2)]
            barrier = Barrier(2)

            def claim(team: Team) -> bool:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    TrialPolicy(team).claim(user_id=self.user.pk)
                    return True
                except TrialRefused:
                    return False
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(claim, contenders)) == [False, True]
            allocation = SignalTrialOrganization.objects.get(organization_id=self.organization.id)
            assert allocation.grants_claimed == 3
            allocation.billing_migrated_at = timezone.now()
            allocation.save(update_fields=["billing_migrated_at"])
            policy = TrialPolicy(self.team)

            def publish() -> bool:
                report = uuid4()
                try:
                    policy.admit(
                        OperationAdmission(
                            operation_key=str(report),
                            stage=SignalTrialOperation.Stage.RESEARCH,
                            report_id=report,
                        ),
                        paid_authorized=False,
                    )
                    with policy.publish_report(report, delivered=True):
                        pass
                    return True
                except TrialRefused:
                    return False

            for _ in range(4):
                assert publish()
            barrier = Barrier(2)

            def race_publish(_: int) -> bool:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    return publish()
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(race_publish, range(2))) == [False, True]
            assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count() == 5
