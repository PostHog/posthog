from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.messaging.backend.models.message_suppression import MessageSuppression
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.services.customerio_client import CustomerIOAPIError


@patch("products.messaging.backend.services.customerio_import_service.SUPPRESSION_PAGE_DELAY_SECONDS", 0)
@patch("products.messaging.backend.services.customerio_import_service.SUPPRESSION_PAGE_SIZE", 2)
@patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
@patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
class TestProviderImportRuns(BaseTest):
    def _start(self, steps: list[str]) -> ProviderImportRun:
        return runs.start_run(self.team.id, "cio", steps, "app-key", self.user.id)

    def test_suppressions_step_resumes_from_the_last_saved_page_after_a_failure(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        pages = {
            ("bounces", 0): [{"email": "a@example.com"}, {"email": "b@example.com"}],
            ("bounces", 2): [{"email": "c@example.com"}],
            ("spam_reports", 0): [{"email": "d@example.com"}],
        }
        failures = {("bounces", 2): CustomerIOAPIError("API error: 503")}

        def get_suppressions(suppression_type: str, limit: int, offset: int) -> list[dict]:
            if error := failures.pop((suppression_type, offset), None):
                raise error
            return pages.get((suppression_type, offset), [])

        mock_client = mock_client_class.return_value
        mock_client.validate_credentials.return_value = True
        mock_client.get_suppressions.side_effect = get_suppressions
        run = self._start(["suppressions"])

        with self.assertRaises(CustomerIOAPIError):
            runs.run_step(self.team.id, run.id, "suppressions")

        run.refresh_from_db()
        assert run.status == "running"
        assert run.progress["suppressions"]["checkpoint"] == {"suppression_type": "bounces", "offset": 2}
        assert "503" in run.progress["suppressions"]["last_error"]

        mock_client.get_suppressions.reset_mock()
        runs.run_step(self.team.id, run.id, "suppressions")

        assert [(call.args[0], call.kwargs["offset"]) for call in mock_client.get_suppressions.call_args_list] == [
            ("bounces", 2),
            ("invalid_emails", 0),
            ("spam_reports", 0),
        ]
        run.refresh_from_db()
        assert run.progress["suppressions"] == {
            "status": "completed",
            "processed": 4,
            "imported": 4,
            "warnings": [],
            "last_error": None,
            "checkpoint": None,
        }
        assert set(MessageSuppression.objects.for_team(self.team.id).values_list("identifier", flat=True)) == {
            "a@example.com",
            "b@example.com",
            "c@example.com",
            "d@example.com",
        }

    @parameterized.expand(
        [
            ("every_step_completed", ["completed", "completed"], "completed", ["completed", "completed"]),
            ("a_step_still_running", ["completed", "running"], "failed", ["completed", "failed"]),
            ("a_step_never_started", ["pending", "completed"], "failed", ["failed", "completed"]),
        ]
    )
    def test_finish_sets_the_run_status_from_its_steps(
        self,
        mock_client_class: MagicMock,
        _start_workflow: MagicMock,
        _name: str,
        step_statuses: list[str],
        expected_run_status: str,
        expected_step_statuses: list[str],
    ) -> None:
        mock_client_class.return_value.validate_credentials.return_value = True
        run = self._start(["suppressions", "opt_outs"])
        for step, step_status in zip(run.steps, step_statuses):
            run.progress[step]["status"] = step_status
        run.save()

        runs.finish_run(self.team.id, run.id)

        run.refresh_from_db()
        assert run.status == expected_run_status
        assert [run.progress[step]["status"] for step in run.steps] == expected_step_statuses
        assert run.finished_at is not None
