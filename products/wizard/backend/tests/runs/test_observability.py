import logging
from datetime import UTC, datetime
from uuid import UUID

from unittest import TestCase
from unittest.mock import patch

from kombu.exceptions import OperationalError
from parameterized import parameterized

from products.wizard.backend.facade.contracts import LocalFolderWorkspace, WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM
from products.wizard.backend.observability import metrics
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome
from products.wizard.backend.observability.service import WizardObservability


class TestWizardObservability(TestCase):
    @parameterized.expand(
        [
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ]
    )
    def test_dispatch_observations_survive_independent_failures(self, metric_fails: bool, event_fails: bool) -> None:
        run = WizardRunDTO(
            id=UUID(int=1),
            team_id=123,
            created_by_id=456,
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example-project"),
            program=POSTHOG_INTEGRATION_PROGRAM,
            status=WizardRunStatus.RUNNING,
            error_code=None,
            error_message=None,
            stage=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=None,
            started_at=None,
            finished_at=None,
            deadline_at=None,
        )

        with (
            patch.object(metrics.WIZARD_RUN_DISPATCH_ATTEMPTS_TOTAL, "labels") as counter,
            patch("products.wizard.backend.observability.events.celery_app.signature") as signature,
            self.assertLogs("products.wizard.backend.observability.service", level=logging.INFO) as logs,
        ):
            counter.return_value.inc.side_effect = ValueError("Metric unavailable") if metric_fails else None
            signature.return_value.apply_async.side_effect = (
                OperationalError("Queue unavailable") if event_fails else None
            )

            WizardObservability().dispatch_finished(run, WizardRunDispatchOutcome.SUCCEEDED)

        counter.return_value.inc.assert_called_once_with()
        signature.return_value.apply_async.assert_called_once_with()
        self.assertEqual(signature.call_args.kwargs["args"][3], "wizard run dispatch finished")
        messages = [record.getMessage() for record in logs.records]
        self.assertEqual("wizard_run_dispatch_metric_failed" in messages, metric_fails)
        self.assertEqual("wizard_run_dispatch_event_failed" in messages, event_fails)
        self.assertEqual(messages[-1], "wizard_run_dispatch_finished")
        self.assertEqual(logs.records[-1].levelno, logging.INFO)
