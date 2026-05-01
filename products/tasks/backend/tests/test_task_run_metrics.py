from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Organization, Team, User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.process_task.activities.track_workflow_event import (
    TrackWorkflowEventInput,
    track_workflow_event,
)


def _sample_value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestTaskRunMetrics(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")
        self.task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )

    def test_create_run_increments_created_counter_with_run_metadata(self) -> None:
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": "background",
            "run_source": "manual",
            "runtime_adapter": "codex",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            extra_state={"run_source": "manual", "runtime_adapter": "codex"},
        )

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1

    def test_create_run_bounds_unexpected_state_labels(self) -> None:
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": "other",
            "run_source": "other",
            "runtime_adapter": "other",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="custom-mode",
            extra_state={"run_source": "custom-source", "runtime_adapter": "custom-adapter"},
        )

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1

    @parameterized.expand(
        [
            ("started", True, "user", True, None, [("attempted", "requested"), ("started", "accepted")], True),
            (
                "missing_user",
                False,
                "none",
                True,
                None,
                [("attempted", "requested"), ("blocked", "missing_user")],
                False,
            ),
            (
                "feature_flag",
                False,
                "user",
                False,
                None,
                [("attempted", "requested"), ("blocked", "feature_flag")],
                False,
            ),
            (
                "permission_validation",
                False,
                "missing",
                True,
                None,
                [("attempted", "requested"), ("failed", "permission_validation")],
                False,
            ),
            (
                "temporal_start",
                True,
                "user",
                True,
                RuntimeError("boom"),
                [("attempted", "requested"), ("failed", "temporal_start")],
                True,
            ),
        ]
    )
    def test_workflow_start_increments_outcome_counters(
        self,
        _name: str,
        debug: bool,
        user_kind: str,
        feature_enabled: bool,
        sync_connect_side_effect: Exception | None,
        expected_outcomes: list[tuple[str, str]],
        expect_sync_connect_called: bool,
    ) -> None:
        task_run = self.task.create_run(environment=TaskRun.Environment.CLOUD)
        base_labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": "background",
            "run_source": "unknown",
            "runtime_adapter": "unknown",
        }
        labels_by_outcome = [
            {**base_labels, "outcome": outcome, "reason": reason} for outcome, reason in expected_outcomes
        ]
        before_by_outcome = [
            _sample_value("posthog_tasks_task_run_workflow_start_total", labels) for labels in labels_by_outcome
        ]
        user_id = {
            "user": self.user.id,
            "none": None,
            "missing": self.user.id + 1,
        }[user_kind]

        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock()

        with (
            override_settings(DEBUG=debug),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled") as mock_feature_enabled,
            patch("products.tasks.backend.temporal.client.sync_connect") as mock_sync_connect,
        ):
            mock_feature_enabled.return_value = feature_enabled
            if sync_connect_side_effect is not None:
                mock_sync_connect.side_effect = sync_connect_side_effect
            else:
                mock_sync_connect.return_value = temporal_client

            execute_task_processing_workflow(
                task_id=str(self.task.id),
                run_id=str(task_run.id),
                team_id=self.team.id,
                user_id=user_id,
            )

        for labels, before in zip(labels_by_outcome, before_by_outcome, strict=True):
            assert _sample_value("posthog_tasks_task_run_workflow_start_total", labels) == before + 1

        assert mock_sync_connect.called is expect_sync_connect_called

    def test_task_run_failed_event_increments_failure_counter(self) -> None:
        distinct_id = self.user.distinct_id
        assert distinct_id is not None

        labels = {
            "origin_product": "user_created",
            "mode": "background",
            "run_source": "manual",
            "runtime_adapter": "codex",
            "error_type": "ActivityError",
            "temporal_activity_type": "forward_pending_user_message",
            "temporal_activity_retry_state": "MAXIMUM_ATTEMPTS_REACHED",
            "cause_error_type": "RuntimeError",
        }
        before = _sample_value("posthog_tasks_task_run_failed_total", labels)

        with patch(
            "products.tasks.backend.temporal.process_task.activities.track_workflow_event.posthoganalytics.capture"
        ):
            track_workflow_event(
                TrackWorkflowEventInput(
                    event_name="task_run_failed",
                    distinct_id=distinct_id,
                    properties={
                        "origin_product": "user_created",
                        "environment": "cloud",
                        "mode": "background",
                        "run_source": "manual",
                        "runtime_adapter": "codex",
                        "error_type": "ActivityError",
                        "temporal_activity_type": "forward_pending_user_message",
                        "temporal_activity_retry_state": "MAXIMUM_ATTEMPTS_REACHED",
                        "cause_error_type": "RuntimeError",
                    },
                )
            )

        assert _sample_value("posthog_tasks_task_run_failed_total", labels) == before + 1
