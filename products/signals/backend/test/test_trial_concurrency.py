from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial_models import (
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)
from products.signals.backend.trial_policy import OperationAdmission, TrialPolicy, TrialRefused


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

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
                        estimated_microusd=100_000,
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
                            estimated_microusd=100_000,
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
