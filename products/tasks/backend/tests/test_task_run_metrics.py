from contextlib import nullcontext
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

import posthoganalytics
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Organization, Team, User

from products.tasks.backend.metrics import CustomImageBuildOutcome, observe_custom_image_build, observe_sandbox_deadline
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.metrics import StepTimer
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities.track_workflow_event import (
    TrackWorkflowEventInput,
    track_workflow_event,
)


def _sample_value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestCustomImageBuildMetrics:
    @parameterized.expand(["started", "succeeded", "failed", "scan_rejected"])
    def test_counter_tracks_lifecycle_outcomes(self, outcome: CustomImageBuildOutcome) -> None:
        labels: dict[str, str] = {"outcome": outcome}
        before = _sample_value("posthog_tasks_custom_image_build_total", labels)

        observe_custom_image_build(outcome)

        assert _sample_value("posthog_tasks_custom_image_build_total", labels) == before + 1

    @patch("products.tasks.backend.metrics.CUSTOM_IMAGE_BUILD_TOTAL.labels", side_effect=RuntimeError("boom"))
    def test_counter_failure_does_not_escape(self, _mock_labels: MagicMock) -> None:
        observe_custom_image_build("succeeded")


class TestSandboxDeadlineMetrics:
    @parameterized.expand(["turn_open", "agent_activity", "activity_during_snapshot", "activity_during_handoff"])
    def test_reason_is_preserved(self, reason: str) -> None:
        labels = {"outcome": "snapshot_only", "reason": reason, "origin_product": "workflow"}
        before = _sample_value("posthog_tasks_sandbox_deadline_total", labels)

        observe_sandbox_deadline(dict[str, object](labels))

        assert _sample_value("posthog_tasks_sandbox_deadline_total", labels) == before + 1


class TestStartupStepMetrics:
    async def test_async_step_timer_waits_for_work_before_recording(self) -> None:
        @StepTimer("dispatch")
        async def dispatch() -> str:
            return "started"

        with (
            posthoganalytics.new_context(fresh=True, capture_exceptions=False),
            patch("products.tasks.backend.temporal.metrics.time.perf_counter", side_effect=[1, 3]),
            patch("products.tasks.backend.temporal.metrics.posthoganalytics.capture") as capture,
        ):
            posthoganalytics.tag("run_id", "test-run")
            assert await dispatch() == "started"

        assert capture.call_args.kwargs["properties"]["duration_ms"] == 2000

    @pytest.mark.parametrize("event", ["agent_first_activity_observed", "agent_first_command_dispatched"])
    def test_startup_milestone_capture_does_not_fetch_feature_flags(self, event: str) -> None:
        with patch(
            "products.tasks.backend.temporal.process_task.activities.track_workflow_event.posthoganalytics.capture"
        ) as capture:
            track_workflow_event(TrackWorkflowEventInput(event, "test-user", {"run_id": "test-run"}))
        assert capture.call_args.kwargs["send_feature_flags"] is False

    @pytest.mark.parametrize("fails", [False, True])
    def test_decorated_timer_keeps_nested_attempt_durations_and_failures_separate(self, fails: bool) -> None:
        @StepTimer("flag_streaming")
        def work(nested: bool) -> None:
            if nested:
                work(False)
            elif fails:
                raise ValueError("failed step")

        meter = MagicMock()
        with (
            posthoganalytics.new_context(fresh=True, capture_exceptions=False),
            patch("products.tasks.backend.temporal.metrics.time.perf_counter", side_effect=[0, 1, 2, 4]),
            patch("products.tasks.backend.temporal.metrics._metric_meter", return_value=meter) as metric_meter,
            patch("products.tasks.backend.temporal.metrics.posthoganalytics.capture") as capture,
            pytest.raises(ValueError, match="failed step") if fails else nullcontext(),
        ):
            posthoganalytics.tag("run_id", "test-run")
            posthoganalytics.tag("origin_product", "signals_scout")
            work(True)

        durations = [args.args[0] for args in meter.create_histogram_timedelta.return_value.record.call_args_list]
        assert durations == [timedelta(seconds=1), timedelta(seconds=4)]
        assert [args.args[0]["status"] for args in metric_meter.call_args_list] == [
            "FAILED" if fails else "COMPLETED"
        ] * 2
        events = [call.kwargs["properties"] for call in capture.call_args_list]
        assert [event["duration_ms"] for event in events] == [1000, 4000]
        assert all(event["run_id"] == "test-run" and event["origin_product"] == "signals_scout" for event in events)
        assert all(event["status"] == ("FAILED" if fails else "COMPLETED") for event in events)
        assert all(call.kwargs["send_feature_flags"] is False for call in capture.call_args_list)

    @pytest.mark.parametrize("capture_fails", [False, True])
    @pytest.mark.parametrize("override", [False, True])
    def test_step_events_use_scoped_run_context_without_affecting_work(
        self, capture_fails: bool, override: bool
    ) -> None:
        with (
            patch("products.tasks.backend.temporal.metrics.posthoganalytics.capture") as capture,
            patch("products.tasks.backend.temporal.metrics._metric_meter") as metric_meter,
        ):
            capture.side_effect = RuntimeError("queue unavailable") if capture_fails else None
            for run_id, origin in [("first-run", "slack"), ("second-run", "review_hog")]:
                with (
                    posthoganalytics.new_context(fresh=True, capture_exceptions=False),
                    log_activity_execution(
                        "startup",
                        run_id=run_id,
                        origin_product=origin,
                        environment="cloud",
                        runtime="vm",
                        sandbox_backend="modal",
                        boot_path="overlap",
                        used_snapshot=True,
                    ),
                    StepTimer(
                        "setup", runtime="gvisor" if override else None, used_snapshot=False if override else None
                    ),
                ):
                    pass
            with StepTimer("unrelated"):
                pass

        assert capture.call_count == 2
        properties = [call.kwargs["properties"] for call in capture.call_args_list]
        assert [(event["run_id"], event["origin_product"]) for event in properties] == [
            ("first-run", "slack"),
            ("second-run", "review_hog"),
        ]
        assert all(event["run_environment"] == "cloud" for event in properties)
        for event, sample in zip(properties, metric_meter.call_args_list[:2]):
            for key, expected in {
                "origin_product": event["origin_product"],
                "runtime": "gvisor" if override else "vm",
                "sandbox_backend": "modal",
                "boot_path": "overlap",
                "used_snapshot": "false" if override else "true",
            }.items():
                assert event[key] == sample.args[0][key] == expected
        assert metric_meter.call_args.args[0] == {
            "step": "unrelated",
            "used_snapshot": "unknown",
            "status": "COMPLETED",
        }


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
            "task_runtime": "acp",
            "runtime_adapter": "codex",
            "prewarmed": "false",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch("products.tasks.backend.models.posthoganalytics.capture") as capture,
        ):
            self.task.create_run(
                environment=TaskRun.Environment.CLOUD,
                extra_state={"run_source": "manual", "runtime_adapter": "codex"},
            )

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1
        created_event = next(call for call in capture.call_args_list if call.kwargs.get("event") == "task_run_created")
        assert created_event.kwargs["send_feature_flags"] is False

    def test_create_run_bounds_unexpected_state_labels(self) -> None:
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": "other",
            "run_source": "other",
            "task_runtime": "acp",
            "runtime_adapter": "other",
            "prewarmed": "false",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        with self.captureOnCommitCallbacks(execute=True):
            self.task.create_run(
                environment=TaskRun.Environment.CLOUD,
                mode="custom-mode",
                extra_state={"run_source": "custom-source", "runtime_adapter": "custom-adapter"},
            )

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1

    @parameterized.expand(
        [
            ("default_acp", Task.Runtime.ACP, "background", "acp", "claude"),
            ("pi", Task.Runtime.PI, "unknown", "pi", "pi"),
        ]
    )
    def test_create_run_labels_effective_runtime(
        self,
        _name: str,
        task_runtime: Task.Runtime,
        expected_mode: str,
        expected_task_runtime: str,
        expected_runtime_adapter: str,
    ) -> None:
        self.task.runtime = task_runtime
        self.task.save(update_fields=["runtime"])
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": expected_mode,
            "run_source": "unknown",
            "task_runtime": expected_task_runtime,
            "runtime_adapter": expected_runtime_adapter,
            "prewarmed": "false",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        with self.captureOnCommitCallbacks(execute=True):
            self.task.create_run(environment=TaskRun.Environment.CLOUD)

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1

    def test_prewarmed_run_created_carries_prewarmed_true_label(self) -> None:
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "mode": "interactive",
            "run_source": "unknown",
            "task_runtime": "acp",
            "runtime_adapter": "claude",
            "prewarmed": "true",
        }
        before = _sample_value("posthog_tasks_task_run_created_total", labels)

        with self.captureOnCommitCallbacks(execute=True):
            self.task.create_run(
                environment=TaskRun.Environment.CLOUD,
                mode="interactive",
                extra_state={"await_user_message": True, "prewarmed": True},
            )

        assert _sample_value("posthog_tasks_task_run_created_total", labels) == before + 1

    def test_activate_warm_run_increments_prewarmed_activated_counter(self) -> None:
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="interactive",
            extra_state={"await_user_message": True, "prewarmed": True},
        )
        labels = {"origin_product": "user_created"}
        before = _sample_value("posthog_tasks_prewarmed_activated_total", labels)

        with patch.object(facade, "signal_task_run_user_message", return_value=True):
            facade._activate_warm_run(run, self.task, self.team.id, message="go", branch=None, artifact_ids=[])

        assert _sample_value("posthog_tasks_prewarmed_activated_total", labels) == before + 1

    def test_failed_startup_during_activation_does_not_count_as_activated(self) -> None:
        from products.tasks.backend.facade import api as facade
        from products.tasks.backend.metrics import observe_prewarmed_unused_if_never_activated

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="interactive",
            extra_state={"await_user_message": True, "prewarmed": True},
        )
        labels = {"origin_product": "user_created", "reason": "other"}
        before = _sample_value("posthog_tasks_prewarmed_unused_total", labels)
        activation_labels = {"origin_product": "user_created"}
        activated_before = _sample_value("posthog_tasks_prewarmed_activated_total", activation_labels)

        def _terminalize_during_signal(*_args: object, **_kwargs: object) -> bool:
            TaskRun.objects.filter(id=run.id).update(status=TaskRun.Status.FAILED)
            observe_prewarmed_unused_if_never_activated(TaskRun.objects.get(id=run.id), reason="other")
            return True

        with (
            patch.object(facade, "signal_task_run_user_message", side_effect=_terminalize_during_signal),
            self.assertRaises(facade.WarmRunActivationUnavailable),
        ):
            facade._activate_warm_run(run, self.task, self.team.id, message="go", branch=None, artifact_ids=[])

        assert _sample_value("posthog_tasks_prewarmed_unused_total", labels) == before + 1
        assert _sample_value("posthog_tasks_prewarmed_activated_total", activation_labels) == activated_before

    def test_direct_terminal_write_counts_a_released_warm(self) -> None:
        # The cancel fallback writes the terminal status itself when the workflow is already gone, so
        # the status activity never runs and never books the miss.
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="interactive",
            extra_state={"await_user_message": True, "prewarmed": True},
        )
        labels = {"origin_product": "user_created", "reason": "released"}
        before = _sample_value("posthog_tasks_prewarmed_unused_total", labels)

        with patch.object(facade, "signal_workflow_completion"):
            facade.update_task_run(
                run.id,
                self.task.id,
                self.team.id,
                validated_data={"status": TaskRun.Status.CANCELLED},
            )

        assert _sample_value("posthog_tasks_prewarmed_unused_total", labels) == before + 1

    @parameterized.expand(
        [
            ("mark_failed", "failed", "janitor_timeout"),
            ("mark_completed", "completed", "unknown"),
            ("dispatch_failure", "failed", "workflow_start_failed"),
            ("claim_and_fail_stale_run", "failed", "sandbox_lost"),
        ]
    )
    def test_writers_outside_the_status_activity_count_the_terminal_transition_once(
        self, writer: str, status: str, error_type: str
    ) -> None:
        from products.tasks.backend.facade import api as facade
        from products.tasks.backend.temporal import client

        run = self.task.create_run(environment=TaskRun.Environment.CLOUD)
        labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "status": status,
            "error_type": error_type,
            "termination_reason": "unknown",
        }
        before = _sample_value("posthog_tasks_task_run_terminal_total", labels)

        with (
            patch("products.tasks.backend.push_dispatcher.notify_task_run_failed"),
            patch.object(client, "resume_workflow_step_for_run"),
            patch.object(facade, "resume_workflow_step_for_run"),
        ):
            for _ in range(2):  # a repeat write on a terminal run must not count again
                run.refresh_from_db()
                if writer == "mark_failed":
                    run.mark_failed("stuck", error_type="janitor_timeout")
                elif writer == "mark_completed":
                    run.mark_completed(notify=False)
                elif writer == "claim_and_fail_stale_run":
                    facade.claim_and_fail_stale_run(run.id, "worker lost", error_type="sandbox_lost")
                else:
                    client._terminalize_unstarted_task_run(str(run.id), "start failed")

        assert _sample_value("posthog_tasks_task_run_terminal_total", labels) == before + 1

    def test_terminal_save_locks_task_before_run(self) -> None:
        run = self.task.create_run(environment=TaskRun.Environment.CLOUD)
        run.status = TaskRun.Status.COMPLETED

        with CaptureQueriesContext(connection) as queries:
            assert run._save_terminal_status(["status"])

        locks = [query["sql"] for query in queries if "FOR UPDATE" in query["sql"]]
        assert len(locks) == 2
        assert f'FROM "{Task._meta.db_table}"' in locks[0]
        assert f'FROM "{TaskRun._meta.db_table}"' in locks[1]

    @parameterized.expand([("mark_failed",), ("mark_completed",)])
    def test_finalizer_on_a_stale_instance_does_not_count_a_run_another_writer_ended(self, writer: str) -> None:
        def terminal_total() -> float:
            return sum(
                _sample_value(
                    "posthog_tasks_task_run_terminal_total",
                    {
                        "origin_product": "user_created",
                        "run_environment": "cloud",
                        "status": status,
                        "error_type": error_type,
                        "termination_reason": "unknown",
                    },
                )
                for status, error_type in (("failed", "janitor_timeout"), ("completed", "unknown"))
            )

        run = self.task.create_run(environment=TaskRun.Environment.CLOUD)
        TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.CANCELLED)
        before = terminal_total()

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_failed"):
            if writer == "mark_failed":
                run.mark_failed("stuck", error_type="janitor_timeout")
            else:
                run.mark_completed(notify=False)

        assert terminal_total() == before

    def test_activating_run_without_prewarmed_marker_does_not_increment(self) -> None:
        # Warm Runs provisioned before this ships have await_user_message but no prewarmed marker;
        # activating them must not inflate the numerator (would push hit rate above 1).
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="interactive",
            extra_state={"await_user_message": True},
        )
        labels = {"origin_product": "user_created"}
        before = _sample_value("posthog_tasks_prewarmed_activated_total", labels)

        with patch.object(facade, "signal_task_run_user_message", return_value=True):
            facade._activate_warm_run(run, self.task, self.team.id, message="go", branch=None, artifact_ids=[])

        assert _sample_value("posthog_tasks_prewarmed_activated_total", labels) == before

    @parameterized.expand(
        [
            ("started", "team", None, [("attempted", "requested"), ("started", "accepted")], True),
            (
                "permission_validation",
                "missing_team",
                None,
                [("attempted", "requested"), ("failed", "permission_validation")],
                False,
            ),
            (
                "temporal_start",
                "team",
                RuntimeError("boom"),
                [("attempted", "requested"), ("failed", "temporal_start")],
                True,
            ),
        ]
    )
    def test_workflow_start_increments_outcome_counters(
        self,
        _name: str,
        team_kind: str,
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
            "task_runtime": "acp",
            "runtime_adapter": "claude",
            "prewarmed": "false",
        }
        labels_by_outcome = [
            {**base_labels, "outcome": outcome, "reason": reason} for outcome, reason in expected_outcomes
        ]
        before_by_outcome = [
            _sample_value("posthog_tasks_task_run_workflow_start_total", labels) for labels in labels_by_outcome
        ]
        team_id = {
            "team": self.team.id,
            "missing_team": self.team.id + 9999,
        }[team_kind]

        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock()

        with (
            patch("products.tasks.backend.temporal.client.sync_connect") as mock_sync_connect,
            patch("products.tasks.backend.temporal.metrics.posthoganalytics.capture") as capture,
        ):
            if sync_connect_side_effect is not None:
                mock_sync_connect.side_effect = sync_connect_side_effect
            else:
                mock_sync_connect.return_value = temporal_client

            execute_task_processing_workflow(
                task_id=str(self.task.id),
                run_id=str(task_run.id),
                team_id=team_id,
                user_id=self.user.id,
            )

        for labels, before in zip(labels_by_outcome, before_by_outcome, strict=True):
            assert _sample_value("posthog_tasks_task_run_workflow_start_total", labels) == before + 1

        assert mock_sync_connect.called is expect_sync_connect_called
        dispatch = next(
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.args
            and call.args[0] == "task_startup_step_completed"
            and call.kwargs["properties"]["step"] == "dispatch"
        )
        assert dispatch["status"] == ("COMPLETED" if _name == "started" else "FAILED")

    @parameterized.expand(
        [
            ("captures_analytics", True),
            ("metrics_only", False),
        ]
    )
    def test_task_run_failed_event_increments_failure_counter(self, _name: str, capture_analytics: bool) -> None:
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
        ) as mock_capture:
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
                    capture_analytics=capture_analytics,
                )
            )

        assert _sample_value("posthog_tasks_task_run_failed_total", labels) == before + 1
        assert mock_capture.called is capture_analytics

    @parameterized.expand(
        [
            ("modal", {}, {}, "agent_reported"),
            ("hogland", {"sandbox_backend": "hogland"}, {"error_type": "agent_declined"}, "agent_declined"),
        ]
    )
    def test_patch_terminal_failure_captures_single_typed_task_run_failed(
        self,
        sandbox_backend: str,
        sandbox_state: dict[str, str],
        error_type_payload: dict[str, str],
        expected_error_type: str,
    ) -> None:
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            extra_state={"sandbox_id": "sandbox-example", **sandbox_state},
        )
        long_error = "w" * 1400 + "Error: wizard exited with code 7"

        with (
            patch.object(facade, "signal_workflow_completion"),
            patch("products.tasks.backend.models.posthoganalytics.capture") as mock_capture,
        ):
            for _ in range(2):  # the repeat PATCH must not double-capture
                facade.update_task_run(
                    run.id,
                    self.task.id,
                    self.team.id,
                    validated_data={"status": "failed", "error_message": long_error, **error_type_payload},
                )

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "task_run_failed"]
        assert len(captured) == 1
        props = captured[0].kwargs["properties"]
        assert props["error_type"] == expected_error_type
        assert props["sandbox_backend"] == sandbox_backend
        assert len(props["error_message"]) == 500
        assert props["error_message"].endswith("Error: wizard exited with code 7")

    @parameterized.expand(
        [
            ("failed", 1.0, "agent_reported"),
            ("completed", 0.0, "unknown"),
        ]
    )
    def test_agent_turn_failure_counter_only_on_failed_transition(
        self, new_status: str, expected_delta: float, terminal_error_type: str
    ) -> None:
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            mode="interactive",
            extra_state={"run_source": "manual", "runtime_adapter": "codex"},
        )
        labels = {
            "origin_product": "user_created",
            "mode": "interactive",
            "run_source": "manual",
            "task_runtime": "acp",
            "runtime_adapter": "codex",
        }
        terminal_labels = {
            "origin_product": "user_created",
            "run_environment": "cloud",
            "status": new_status,
            "error_type": terminal_error_type,
            "termination_reason": "unknown",
        }
        before = _sample_value("posthog_tasks_agent_turn_failed_total", labels)
        terminal_before = _sample_value("posthog_tasks_task_run_terminal_total", terminal_labels)

        with patch.object(facade, "signal_workflow_completion"):
            for _ in range(2):  # the repeat PATCH must not double count
                facade.update_task_run(
                    run.id,
                    self.task.id,
                    self.team.id,
                    validated_data={"status": new_status, "error_message": "boom"},
                )

        assert _sample_value("posthog_tasks_agent_turn_failed_total", labels) == before + expected_delta
        assert _sample_value("posthog_tasks_task_run_terminal_total", terminal_labels) == terminal_before + 1

    @parameterized.expand(
        [
            ("acp_default", Task.Runtime.ACP, {"model": "claude-opus-5"}, "acp", "claude"),
            ("pi", Task.Runtime.PI, {}, "pi", "pi"),
        ]
    )
    def test_agent_turn_failure_counter_uses_effective_runtime(
        self,
        _name: str,
        runtime: Task.Runtime,
        extra_state: dict,
        expected_task_runtime: str,
        expected_runtime_adapter: str,
    ) -> None:
        from products.tasks.backend.facade import api as facade

        self.task.runtime = runtime
        self.task.save(update_fields=["runtime"])
        run = self.task.create_run(environment=TaskRun.Environment.CLOUD, extra_state=extra_state)
        labels = {
            "origin_product": "user_created",
            "mode": "background" if runtime == Task.Runtime.ACP else "unknown",
            "run_source": "unknown",
            "task_runtime": expected_task_runtime,
            "runtime_adapter": expected_runtime_adapter,
        }
        before = _sample_value("posthog_tasks_agent_turn_failed_total", labels)

        with patch.object(facade, "signal_workflow_completion"):
            facade.update_task_run(
                run.id,
                self.task.id,
                self.team.id,
                validated_data={"status": "failed", "error_message": "boom"},
            )

        assert _sample_value("posthog_tasks_agent_turn_failed_total", labels) == before + 1

    @parameterized.expand(
        [
            ("unbound_wizard_run", {"wizard_head_branch": "posthog/instrumentation-ab12cd"}, {}, 1.0),
            (
                "bound_wizard_run",
                {"wizard_head_branch": "posthog/instrumentation-ab12cd"},
                {"pr_url": "https://x/pull/1"},
                0.0,
            ),
            ("non_wizard_run", {}, {}, 0.0),
        ]
    )
    def test_terminal_transition_counts_unbound_wizard_runs(
        self, _name: str, extra_state: dict, output: dict, expected_delta: float
    ) -> None:
        from products.tasks.backend.facade import api as facade

        run = self.task.create_run(environment=TaskRun.Environment.CLOUD, extra_state=extra_state)
        if output:
            run.output = output
            run.save(update_fields=["output"])
        labels = {"status": "completed"}
        before = _sample_value("posthog_tasks_wizard_run_unbound_total", labels)

        with patch.object(facade, "signal_workflow_completion"):
            facade.update_task_run(
                run.id,
                self.task.id,
                self.team.id,
                validated_data={"status": "completed"},
            )

        assert _sample_value("posthog_tasks_wizard_run_unbound_total", labels) == before + expected_delta
