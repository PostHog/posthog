from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from django.db import close_old_connections, connection, transaction

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.facade.testing import claim_trial
from products.signals.backend.models import SignalReport
from products.tasks.backend.facade.api import run_task
from products.tasks.backend.logic.services.warm import SandboxWarmer
from products.tasks.backend.max_tools import RunTaskTool
from products.tasks.backend.models import Task


class TestTrialExecutionConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand([("model",), ("tool",), ("warmer",), ("idempotent_facade",)])
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
                    elif entrypoint == "warmer":
                        SandboxWarmer(task, user=self.user).warm(mode="background")
                    elif entrypoint == "idempotent_facade":
                        result = run_task(
                            task.id,
                            self.team.id,
                            self.user.id,
                            validated_data={"mode": "background"},
                            only_if_no_runs=True,
                        )
                        assert result is not None and result.error is None and result.run_error is None
                    else:
                        task.create_run()
            finally:
                close_old_connections()

        with (
            patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True),
            patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async", new_callable=AsyncMock),
            patch("products.tasks.backend.logic.services.warm.execute_task_processing_workflow"),
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
            patch.object(SandboxWarmer, "enforce_quota"),
        ):
            claim_trial(team=self.team, user_id=self.user.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report.id)
                    pending = pool.submit(create_run)
                    assert report_requested.wait(timeout=10)
                    Task.objects.select_for_update(nowait=True).get(id=task.id, team_id=self.team.id)
                pending.result(timeout=10)
        assert task.runs.count() == 1
