from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.usage import trial_usage


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_concurrent_accepted_plans_publish_all_layers_after_the_report_limit(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            policy = TrialPolicy(self.team)
            grant = policy.claim(user_id=self.user.pk)
            parents = [
                SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS) for _ in range(2)
            ]
            for parent in parents:
                policy.admit(
                    report_id=parent.id,
                    paid_authorized=False,
                )
                parent.refresh_from_db()
                parent.save(
                    update_fields=parent.transition_to(SignalReport.Status.READY, title="Plan", summary="Summary")
                )
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
                assert sorted(pool.map(publish_layers, parents)) == [2, 2]
            assert SignalReport.objects.filter(team=self.team, status=SignalReport.Status.READY).count() == 6
            assert trial_usage(grant).reports == 6
            assert trial_usage(grant).running_reports == 0

    def test_final_organization_claim_and_report_admission_are_atomic(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
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
            assert TrialPolicy(self.team).organization_grants_claimed() == 3
            policy = TrialPolicy(self.team)

            def publish() -> bool:
                report = SignalReport.objects.create(team=self.team)
                try:
                    policy.admit(
                        report_id=report.id,
                        paid_authorized=False,
                    )
                    report.refresh_from_db()
                    report.status = SignalReport.Status.IN_PROGRESS
                    report.save(update_fields=["status"])
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
            grant = policy.grant()
            assert grant is not None
            assert trial_usage(grant).running_reports == 5
