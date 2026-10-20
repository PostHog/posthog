from typing import Any

from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.tests.test_api import BaseTaskAPITest

PR_ONE = "https://github.com/org/repo/pull/1"
PR_TWO = "https://github.com/org/repo/pull/2"


@patch("products.tasks.backend.facade.api.signal_workflow_completion")
class TestAgentRunEvents(BaseTaskAPITest):
    def setUp(self) -> None:
        super().setUp()
        self._create_run(self.create_task())

    def _create_run(self, task: Task, run_status: TaskRun.Status = TaskRun.Status.IN_PROGRESS) -> None:
        self.task = task
        self.task_run = TaskRun.objects.create(task=task, team=self.team, status=run_status)

    def _report(self, event: dict[str, Any], *, scopes: str | None = None):
        client = self._sandbox_oauth_client(self.task.id, scopes=scopes)
        return client.post(
            f"/api/projects/@current/tasks/{self.task.id}/runs/{self.task_run.id}/agent_callback/",
            {"kind": "run_event", "event": event},
            format="json",
        )

    def _run_fields(self, *fields: str) -> dict[str, Any]:
        self.task_run.refresh_from_db()
        return {field: getattr(self.task_run, field) for field in fields}

    @parameterized.expand(
        [
            ("started", {"type": "started", "agent_version": "1.2.3"}, {"status": "in_progress"}),
            (
                "failed",
                {"type": "failed", "error_type": "upstream_timeout", "cause": "boom"},
                {"status": "failed", "error_message": "upstream_timeout: boom"},
            ),
            (
                "branch_changed",
                {"type": "branch_changed", "branch": "feat/x"},
                {"branch": "feat/x", "output": {"head_branch": "feat/x"}},
            ),
            (
                "pr_detected",
                {"type": "pr_detected", "pr_url": PR_ONE},
                {"output": {"pr_url": PR_ONE, "pr_urls": [PR_ONE]}},
            ),
        ]
    )
    def test_run_event_updates_the_run(self, _signal, _name, event, expected) -> None:
        response = self._report(event)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._run_fields(*expected) == expected

    def test_run_event_is_accepted_without_the_callbacks_opt_in(self, _signal) -> None:
        response = self._report({"type": "usage", "token_usage": {"input_tokens": 3}})

        assert response.status_code == status.HTTP_200_OK
        self.task_run.refresh_from_db()
        assert self.task_run.state["token_usage"] == {"input_tokens": 3}

    @parameterized.expand(
        [
            ("acp", Task.Runtime.ACP, "Agent server crashed: boom"),
            ("pi", Task.Runtime.PI, "Pi agent server crashed: boom"),
        ]
    )
    def test_server_names_the_crashed_runtime(self, _signal, _name, runtime, expected_message) -> None:
        self._create_run(self.create_task(runtime=runtime))

        self._report({"type": "failed", "error_type": "agent_server_crash", "cause": "boom"})

        assert self._run_fields("error_message") == {"error_message": expected_message}

    def test_pr_detected_keeps_the_primary_pr(self, _signal) -> None:
        self.task_run.output = {"pr_url": PR_ONE, "pr_urls": [PR_ONE]}
        self.task_run.save(update_fields=["output"])

        self._report({"type": "pr_detected", "pr_url": PR_TWO})

        assert self._run_fields("output") == {"output": {"pr_url": PR_ONE, "pr_urls": [PR_ONE, PR_TWO]}}

    @parameterized.expand(
        [
            ("matching", {"summary": "done"}, status.HTTP_200_OK, {"summary": "done"}),
            ("mismatched", {"summary": 3}, status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_structured_output_is_checked_against_the_schema(
        self, _signal, _name, output, expected_status, expected_output
    ) -> None:
        self.task.json_schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
        self.task.save(update_fields=["json_schema"])

        response = self._report({"type": "structured_output", "output": output})

        assert response.status_code == expected_status
        assert self._run_fields("output") == {"output": expected_output}

    @parameterized.expand(
        [
            ("unknown_type", {"type": "exploded"}),
            ("missing_field", {"type": "failed", "cause": "boom"}),
            ("workflow_error_type", {"type": "failed", "error_type": "poll_timeout", "cause": "boom"}),
            ("field_of_another_type", {"type": "started", "agent_version": "1.2.3", "branch": "feat/x"}),
            ("non_github_pr", {"type": "pr_detected", "pr_url": "https://example.com/pull/1"}),
            ("empty_usage", {"type": "usage"}),
        ]
    )
    def test_invalid_event_is_rejected(self, _signal, _name, event) -> None:
        response = self._report(event)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._run_fields("status") == {"status": TaskRun.Status.IN_PROGRESS}

    @parameterized.expand(
        [
            ("other_status", {"type": "started", "agent_version": "1.2.3"}, 409),
            ("no_status", {"type": "branch_changed", "branch": "feat/x"}, 409),
            ("same_status_retry", {"type": "failed", "error_type": "agent_reported", "cause": "late"}, 200),
        ]
    )
    def test_event_for_an_ended_run(self, _signal, _name, event, expected_status) -> None:
        self._create_run(self.task, TaskRun.Status.FAILED)

        response = self._report(event)

        assert response.status_code == expected_status
        assert self._run_fields("status", "error_message") == {
            "status": TaskRun.Status.FAILED,
            "error_message": None,
        }

    def test_usage_is_kept_after_the_run_ended(self, _signal) -> None:
        self._create_run(self.task, TaskRun.Status.COMPLETED)

        response = self._report({"type": "usage", "token_usage": {"input_tokens": 3}})

        assert response.status_code == status.HTTP_200_OK
        self.task_run.refresh_from_db()
        assert self.task_run.state["token_usage"] == {"input_tokens": 3}

    @parameterized.expand(
        [
            ("first_report", TaskRun.Status.IN_PROGRESS),
            ("retry_after_the_run_failed", TaskRun.Status.FAILED),
        ]
    )
    def test_failed_event_retries_until_the_workflow_is_signalled(self, signal, _name, run_status) -> None:
        self._create_run(self.task, run_status)
        signal.return_value = False

        response = self._report({"type": "failed", "error_type": "agent_reported", "cause": "boom"})

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        signal.assert_called_once_with(str(self.task_run.id), TaskRun.Status.FAILED, "boom", "agent_reported")

    @parameterized.expand(
        [
            ("started", {"type": "started", "agent_version": "1.2.3"}, status.HTTP_200_OK),
            ("failed", {"type": "failed", "error_type": "agent_reported", "cause": "boom"}, status.HTTP_200_OK),
            ("branch_changed", {"type": "branch_changed", "branch": "feat/x"}, status.HTTP_403_FORBIDDEN),
            ("pr_detected", {"type": "pr_detected", "pr_url": PR_ONE}, status.HTTP_403_FORBIDDEN),
            ("malformed_type", {"type": ["started"]}, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_scout_trial_reports_only_lifecycle_events(self, _signal, _name, event, expected_status) -> None:
        self._create_run(
            Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Scout trial",
                description="Inspect recent activity",
                origin_product=Task.OriginProduct.SIGNALS_SCOUT,
                origin_key="scout-trial:run-events",
                repository="example/scout",
            )
        )

        response = self._report(event, scopes="task:read internal_run:read scout_experiment_internal:read")

        assert response.status_code == expected_status
