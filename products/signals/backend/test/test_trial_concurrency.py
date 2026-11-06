from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import OperationalError, close_old_connections, transaction

from posthog.models import Team

from products.signals.backend import spend as spend_module
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.facade.trial import TaskTrialAdmission
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.tasks.backend.models import Task


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_concurrent_accepted_plans_publish_all_layers_after_the_report_limit(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            policy = TrialPolicy(self.team)
            policy.claim(user_id=self.user.pk)
            parents = [
                SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS) for _ in range(2)
            ]
            for parent in parents:
                policy.admit(
                    report_id=parent.id,
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
                assert sorted(pool.map(publish_layers, parents)) == [2, 2]
            assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count() == 6
            assert not SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="reserved").exists()

    def test_final_organization_slot_and_report_slot_are_atomic(self) -> None:
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
                report = uuid4()
                try:
                    policy.admit(
                        report_id=report,
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

    def test_report_finalization_and_late_settlement_share_a_grant_without_deadlocking(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
        first_id, pending_id = uuid4(), uuid4()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.IN_PROGRESS,
            triggering_signal_id=first_id,
            pending_triggering_signal_id=pending_id,
        )
        spend_module.record_llm_spend(
            team_id=self.team.id,
            signal_id=str(first_id),
            stage="research",
            token_cost_microusd=100,
            trial_grant_id=str(grant.id),
        )
        spend_module.record_llm_spend(
            team_id=self.team.id,
            signal_id=str(pending_id),
            stage="research",
            token_cost_microusd=None,
            source_id="late",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        first_locked, pending_locked, finalizing_pending = Event(), Event(), Event()
        lock_spend = spend_module._locked_ad_hoc_spend

        def coordinated_lock(*, team_id: int, signal_id: str, trial_grant_id: str | None = None) -> SignalSpend:
            if signal_id == str(pending_id):
                finalizing_pending.set()
            receipt = lock_spend(team_id=team_id, signal_id=signal_id, trial_grant_id=trial_grant_id)
            if signal_id == str(first_id):
                first_locked.set()
                assert pending_locked.wait(timeout=10)
            return receipt

        def finalize() -> None:
            close_old_connections()
            try:
                spend_module.finish_report_spend(
                    team_id=self.team.id, report_id=str(report.id), signal_id=str(first_id)
                )
            finally:
                close_old_connections()

        def settle() -> None:
            close_old_connections()
            try:
                assert first_locked.wait(timeout=10)
                with transaction.atomic():
                    SignalSpend.objects.for_team(self.team.id).select_for_update().get(signal_id=pending_id)
                    pending_locked.set()
                    assert finalizing_pending.wait(timeout=10)
                    spend_module.record_llm_spend(
                        "late-request",
                        team_id=self.team.id,
                        signal_id=str(pending_id),
                        stage="research",
                        source_id="late",
                        token_cost_microusd=200,
                    )
            finally:
                close_old_connections()

        with patch.object(spend_module, "_locked_ad_hoc_spend", side_effect=coordinated_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(finalize), pool.submit(settle)]
                for future in futures:
                    future.result(timeout=15)
        grant = SignalTrialGrant.objects.for_team(self.team.id, canonical=True).get(id=grant.id)
        assert grant.settled_microusd == 300
        assert grant.incomplete_sources == 0
        assert SignalSpend.objects.for_team(self.team.id).filter(finalized_at__isnull=False).count() == 2
        report.refresh_from_db()
        assert report.pending_triggering_signal_id is None

    def test_report_lock_precedes_trial_grant_lock_during_admission(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            TrialPolicy(self.team).claim(user_id=self.user.pk)
            report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
            task = Task.objects.create(
                team=self.team,
                title="Report admission",
                origin_product="signal_report",
                signal_report=report,
                internal=True,
            )
            original = TrialPolicy.locked_grant

            def can_lock_report() -> bool:
                close_old_connections()
                try:
                    with transaction.atomic():
                        SignalReport.objects.select_for_update(nowait=True).get(team_id=self.team.id, id=report.id)
                    return True
                except OperationalError as error:
                    assert getattr(error.__cause__, "sqlstate", None) == "55P03"
                    return False
                finally:
                    close_old_connections()

            @contextmanager
            def lock_grant(policy: TrialPolicy, grant_id: UUID) -> Iterator[SignalTrialGrant]:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    assert not pool.submit(can_lock_report).result(timeout=10)
                with original(policy, grant_id) as grant:
                    yield grant

            with patch.object(TrialPolicy, "locked_grant", lock_grant):
                task.create_run(extra_state={"ai_stage": "implementation"})

    def test_admission_and_cost_settlement_do_not_invert_locks(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
            signal_id = str(uuid4())
            report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
            task = Task.objects.create(
                team=self.team,
                title="Concurrent run",
                origin_product="signal_report",
                signal_report_id=report.id,
                internal=True,
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
                origin: str,
                stage: str,
                report_id: UUID | None,
            ) -> dict[str, str | int]:
                result = original_bind(
                    admission,
                    origin=origin,
                    stage=stage,
                    report_id=report_id,
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
            assert grant.settled_microusd == 40_003
            assert task.runs.count() == 1
