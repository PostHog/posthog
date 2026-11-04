from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from django.db import OperationalError, close_old_connections, connection, transaction

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.facade.trial import TaskTrialAdmission
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.facade.api import iter_trial_task_runs
from products.tasks.backend.max_tools import RunTaskTool
from products.tasks.backend.models import Task, TaskRun


class TestTrialExecutionConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand([("model",), ("tool",)])
    def test_waiting_for_report_does_not_lock_its_task(self, entrypoint: str) -> None:
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Implementation",
            origin_product="signal_report",
            signal_report=report,
            internal=True,
            created_by=self.user,
        )
        report_requested = Event()

        def observe(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            if '"signals_signalreport"' in sql and "FOR UPDATE" in sql:
                report_requested.set()
            return execute(sql, params, many, context)

        def create_run() -> None:
            close_old_connections()
            try:
                with connection.execute_wrapper(observe):
                    if entrypoint == "tool":
                        tool = RunTaskTool(team=self.team, user=self.user, config={})
                        async_to_sync(tool._arun_impl)(task_id=str(task.id))
                    else:
                        task.create_run()
            finally:
                close_old_connections()

        with (
            patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True),
            patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async", new_callable=AsyncMock),
        ):
            TrialPolicy(self.team).claim(user_id=self.user.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report.id)
                    pending = pool.submit(create_run)
                    assert report_requested.wait(timeout=10)
                    Task.objects.select_for_update(nowait=True).get(id=task.id, team_id=self.team.id)
                pending.result(timeout=10)
        assert task.runs.count() == 1

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

    def test_trial_run_scan_survives_connection_cleanup_between_cancellations(self) -> None:
        grant_id = str(uuid4())
        task = Task.objects.create(team=self.team, title="Cancellation scan", origin_product="signal_report")
        runs = TaskRun.objects.bulk_create(
            [
                TaskRun(
                    team=self.team,
                    task=task,
                    state={"self_driving_funding": {"funding": "trial", "grant_id": grant_id}},
                )
                for _ in range(501)
            ]
        )
        visited = set()
        for run in iter_trial_task_runs(team_id=self.team.id, grant_id=grant_id):
            connection.close()
            TaskRun.objects.filter(id=run.id).update(status=TaskRun.Status.CANCELLED)
            visited.add(run.id)
        assert visited == {run.id for run in runs}
