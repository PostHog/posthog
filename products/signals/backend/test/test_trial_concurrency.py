from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.trial_models import (
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)
from products.signals.backend.trial_policy import OperationAdmission, TrialPolicy, TrialRefused


class TestTrialConcurrency(NonAtomicBaseTest):
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
