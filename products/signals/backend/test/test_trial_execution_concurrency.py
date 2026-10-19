from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections, transaction

from products.signals.backend.facade.trial import TaskTrialAdmission
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.models import Task


class TestTrialExecutionConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_admission_and_cost_settlement_do_not_invert_locks(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
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
            assert grant.settled_microusd == 3
            assert task.runs.count() == 1
