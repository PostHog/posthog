from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_suppression import MessageSuppression
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import ImportProviderUnavailable
from products.messaging.backend.services.customerio_client import CustomerIOAPIError

SERVICE = "products.messaging.backend.services.customerio_import_service"


@patch(f"{SERVICE}.SUPPRESSION_PAGE_DELAY_SECONDS", 0)
@patch(f"{SERVICE}.SUPPRESSION_PAGE_SIZE", 2)
@patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
@patch(f"{SERVICE}.CustomerIOClient")
class TestProviderImportRuns(BaseTest):
    pages = {
        ("bounces", 0): [{"email": "a@example.com"}, {"email": "b@example.com"}],
        ("bounces", 2): [{"email": "c@example.com"}],
        ("spam_reports", 0): [{"email": "d@example.com"}],
    }

    def _start(self, steps: list[str]) -> ProviderImportRun:
        return runs.start_run(self.team.id, "customerio", steps, "app-key", self.user.id)

    def _suppressed(self) -> set[str]:
        return set(MessageSuppression.objects.for_team(self.team.id).values_list("identifier", flat=True))

    def test_suppressions_step_resumes_from_the_last_saved_page_and_does_not_rerun_once_completed(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        failures = {("bounces", 2): CustomerIOAPIError("Customer.io API error", status_code=503)}

        def get_suppressions(suppression_type: str, limit: int, offset: int) -> list[dict]:
            if error := failures.pop((suppression_type, offset), None):
                raise error
            return self.pages.get((suppression_type, offset), [])

        mock_client = mock_client_class.return_value
        mock_client.get_suppressions.side_effect = get_suppressions
        run = self._start(["suppressions"])

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        run.refresh_from_db()
        assert run.status == "running"
        assert run.progress["suppressions"]["checkpoint"] == {"suppression_type": "bounces", "offset": 2}
        assert run.progress["suppressions"]["last_error"] == "Customer.io returned HTTP 503."

        mock_client.get_suppressions.reset_mock()
        runs.run_step(self.team.id, run.id, "suppressions", attempt=2)

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
            "attempt": 2,
        }
        assert self._suppressed() == {"a@example.com", "b@example.com", "c@example.com", "d@example.com"}

        mock_client.get_suppressions.reset_mock()
        runs.run_step(self.team.id, run.id, "suppressions", attempt=3)

        mock_client.get_suppressions.assert_not_called()

    @parameterized.expand([("bounce", "a@example.com", True), ("spam_report", "d@example.com", False)])
    def test_only_bounce_suppressions_are_imported_as_hard_bounces(
        self,
        mock_client_class: MagicMock,
        _start_workflow: MagicMock,
        _name: str,
        identifier: str,
        hard_bounced: bool,
    ) -> None:
        mock_client_class.return_value.get_suppressions.side_effect = lambda suppression_type, limit, offset: (
            self.pages.get((suppression_type, offset), [])
        )
        run = self._start(["suppressions"])
        runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        row = MessageSuppression.objects.for_team(self.team.id).get(identifier=identifier)
        assert (row.hard_bounced_at is not None) is hard_bounced

    def test_an_older_attempt_stops_without_writing_once_a_newer_attempt_takes_over(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        run = self._start(["suppressions"])
        newer_attempt_started = False

        def get_suppressions(suppression_type: str, limit: int, offset: int) -> list[dict]:
            nonlocal newer_attempt_started
            if (suppression_type, offset) == ("bounces", 2) and not newer_attempt_started:
                newer_attempt_started = True
                runs.run_step(self.team.id, run.id, "suppressions", attempt=2)
            return self.pages.get((suppression_type, offset), [])

        mock_client_class.return_value.get_suppressions.side_effect = get_suppressions

        with self.assertRaises(runs.StaleImportAttempt):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        run.refresh_from_db()
        assert run.progress["suppressions"]["attempt"] == 2
        assert run.progress["suppressions"]["status"] == "completed"
        assert run.progress["suppressions"]["processed"] == 4
        assert self._suppressed() == {"a@example.com", "b@example.com", "c@example.com", "d@example.com"}

    def test_an_attempt_stops_without_writing_once_its_run_closes(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        run = self._start(["suppressions"])

        def get_suppressions(suppression_type: str, limit: int, offset: int) -> list[dict]:
            if (suppression_type, offset) == ("bounces", 2):
                runs.finish_run(self.team.id, run.id)
            return self.pages.get((suppression_type, offset), [])

        mock_client_class.return_value.get_suppressions.side_effect = get_suppressions

        with self.assertRaises(runs.ImportRunClosed):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.progress["suppressions"]["checkpoint"] == {"suppression_type": "bounces", "offset": 2}
        assert self._suppressed() == {"a@example.com", "b@example.com"}

    def test_opt_outs_step_completes_when_customerio_repeats_an_email(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        mock_client_class.return_value.get_globally_unsubscribed_customers.return_value = {
            "identifiers": [
                {"id": "1", "email": "shared@example.com"},
                {"id": "2", "email": "shared@example.com"},
                {"id": "3", "email": "other@example.com"},
            ],
            "next": "",
        }
        run = self._start(["opt_outs"])

        runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)

        run.refresh_from_db()
        assert run.progress["opt_outs"]["status"] == "completed"
        assert run.progress["opt_outs"]["imported"] == 2
        assert set(
            MessageRecipientPreference.objects.filter(team_id=self.team.id).values_list("identifier", flat=True)
        ) == {"shared@example.com", "other@example.com"}

    def test_opt_outs_merge_into_a_preference_saved_while_the_import_runs(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        mock_client_class.return_value.get_globally_unsubscribed_customers.return_value = {
            "identifiers": [{"id": "1", "email": "raced@example.com"}],
            "next": "",
        }
        MessageRecipientPreference.objects.create(
            team_id=self.team.id, identifier="raced@example.com", preferences={"category-1": "OPTED_OUT"}
        )
        run = self._start(["opt_outs"])
        read_existing = MessageRecipientPreference.objects.filter
        reads = 0

        def miss_the_first_read(*args: object, **kwargs: object) -> object:
            nonlocal reads
            reads += 1
            return MessageRecipientPreference.objects.none() if reads == 1 else read_existing(*args, **kwargs)

        with patch.object(MessageRecipientPreference.objects, "filter", side_effect=miss_the_first_read):
            with self.assertRaises(IntegrityError):
                runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)
            runs.run_step(self.team.id, run.id, "opt_outs", attempt=2)

        run.refresh_from_db()
        assert run.progress["opt_outs"]["status"] == "completed"
        preference = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="raced@example.com")
        assert preference.preferences == {
            "category-1": "OPTED_OUT",
            ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT",
        }

    def test_category_warnings_never_carry_raw_exception_text(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        mock_client_class.return_value.get_subscription_topics.return_value = [
            {"id": 1, "identifier": "topic_1", "name": "Newsletter"},
            {"id": 2, "identifier": "topic_2", "name": "Product updates"},
        ]
        run = self._start(["categories"])

        with patch(
            f"{SERVICE}.MessageCategory.objects.update_or_create",
            side_effect=IntegrityError("Key (key)=(internal-detail) already exists."),
        ):
            runs.run_step(self.team.id, run.id, "categories", attempt=1)

        run.refresh_from_db()
        assert run.progress["categories"]["warnings"] == [
            "2 subscription topics couldn't be imported. Run the import again to retry them."
        ]

    @parameterized.expand(
        [
            ("provider_error", "get_suppressions", CustomerIOAPIError("error for a@example.com", status_code=503)),
            ("database_error", "save", IntegrityError("Key (identifier)=(a@example.com) already exists.")),
        ]
    )
    def test_step_errors_shown_to_users_never_carry_raw_exception_text(
        self,
        mock_client_class: MagicMock,
        _start_workflow: MagicMock,
        _name: str,
        failing_call: str,
        error: Exception,
    ) -> None:
        mock_client = mock_client_class.return_value
        mock_client.get_suppressions.side_effect = lambda suppression_type, limit, offset: [{"email": "a@example.com"}]
        if failing_call == "get_suppressions":
            mock_client.get_suppressions.side_effect = error
        run = self._start(["suppressions"])

        with (
            patch(f"{SERVICE}.CustomerIOImportService.save_suppression_page", side_effect=error),
            self.assertRaises(Exception),
        ):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        run.refresh_from_db()
        assert run.progress["suppressions"]["last_error"] is not None
        assert "a@example.com" not in run.progress["suppressions"]["last_error"]

    def test_steps_of_a_run_whose_workflow_failed_to_start_import_nothing(
        self, mock_client_class: MagicMock, start_workflow: MagicMock
    ) -> None:
        start_workflow.side_effect = RuntimeError("Temporal did not answer")
        with self.assertRaises(RuntimeError):
            self._start(["suppressions"])
        run = ProviderImportRun.objects.for_team(self.team.id).get()

        with self.assertRaises(runs.ImportRunClosed):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        mock_client_class.return_value.get_suppressions.assert_not_called()
        assert ProviderImportRun.objects.for_team(self.team.id).filter(status="failed").count() == 1

    @parameterized.expand(
        [
            ("every_step_completed", ["completed", "completed"], "completed", ["completed", "completed"]),
            ("a_step_still_running", ["completed", "running"], "failed", ["completed", "failed"]),
            ("a_step_never_started", ["pending", "completed"], "failed", ["failed", "completed"]),
        ]
    )
    def test_finish_sets_the_run_status_from_its_steps_once(
        self,
        mock_client_class: MagicMock,
        _start_workflow: MagicMock,
        _name: str,
        step_statuses: list[str],
        expected_run_status: str,
        expected_step_statuses: list[str],
    ) -> None:
        run = self._start(["suppressions", "opt_outs"])
        for step, step_status in zip(run.steps, step_statuses):
            run.progress[step]["status"] = step_status
        run.save()

        with patch("products.messaging.backend.provider_imports.runs.report_team_action") as report:
            runs.finish_run(self.team.id, run.id)
            runs.finish_run(self.team.id, run.id)

        run.refresh_from_db()
        assert run.status == expected_run_status
        assert [run.progress[step]["status"] for step in run.steps] == expected_step_statuses
        assert run.finished_at is not None
        assert report.call_count == 1

    @time_machine.travel("2026-03-02T12:00:00Z", tick=False)
    def test_reading_an_expired_run_fails_it_and_its_unfinished_steps(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        run = self._start(["suppressions"])
        ProviderImportRun.objects.for_team(self.team.id).filter(id=run.id).update(
            created_at=timezone.now() - runs.STALE_RUN_AGE - timedelta(minutes=1)
        )

        expired = runs.get_run(self.team.id, run.id)

        assert expired is not None
        assert expired.status == "failed"
        assert expired.progress["suppressions"]["status"] == "failed"
