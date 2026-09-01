from datetime import timedelta

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from products.tasks.backend.models import Loop, Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    SANDBOX_GONE_STATE_KEY,
    TIMED_OUT_INACTIVITY_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
    UpdateTaskRunStatusInput,
    update_task_run_status,
)

TOKEN_USAGE = {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500, "turns": 3}


async def _run_update_task_run_status(
    activity_environment: ActivityEnvironment, input_data: UpdateTaskRunStatusInput
) -> None:
    await activity_environment.run(update_task_run_status, input_data)


@pytest.mark.requires_secrets
class TestUpdateTaskRunStatusActivity:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "status,environment,sets_completed_at",
        [
            (TaskRun.Status.IN_PROGRESS, TaskRun.Environment.CLOUD, False),
            (TaskRun.Status.COMPLETED, TaskRun.Environment.CLOUD, True),
            (TaskRun.Status.FAILED, TaskRun.Environment.CLOUD, True),
            (TaskRun.Status.CANCELLED, TaskRun.Environment.CLOUD, True),
            (TaskRun.Status.CANCELLED, TaskRun.Environment.LOCAL, False),
        ],
    )
    def test_updates_status(self, activity_environment, test_task_run, status, environment, sets_completed_at):
        test_task_run.environment = environment
        test_task_run.save(update_fields=["environment"])
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=status)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.status == status
        if sets_completed_at:
            assert test_task_run.completed_at is not None
        else:
            assert test_task_run.completed_at is None

    @pytest.mark.django_db(transaction=True)
    def test_cancelled_run_is_not_resurrected_by_a_late_workflow_completion(self, activity_environment, test_task_run):
        # A run cancelled out of band (loop cancel_previous overlap, owner deactivation) must stay
        # cancelled even if its own workflow finishes and reports completed afterward.
        test_task_run.status = TaskRun.Status.CANCELLED
        test_task_run.save(update_fields=["status"])

        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.COMPLETED)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.CANCELLED

    @pytest.mark.django_db(transaction=True)
    def test_updates_error_message(self, activity_environment, test_task_run):
        error_msg = "Something went wrong"
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.FAILED,
            error_message=error_msg,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.error_message == error_msg

    @pytest.mark.django_db(transaction=True)
    def test_timed_out_inactivity_sets_state_marker_without_error_message(self, activity_environment, test_task_run):
        test_task_run.state = {**(test_task_run.state or {}), "existing_key": "kept"}
        test_task_run.save(update_fields=["state"])

        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.COMPLETED,
            timed_out_inactivity=True,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.COMPLETED
        assert test_task_run.error_message is None
        assert test_task_run.state.get("timed_out_inactivity") is True
        # Merge, not replace: pre-existing state keys survive the marker write.
        assert test_task_run.state.get("existing_key") == "kept"

    @pytest.mark.django_db(transaction=True)
    def test_timed_out_unclaimed_prewarm_soft_deletes_task(
        self, activity_environment: ActivityEnvironment, test_task_run: TaskRun
    ) -> None:
        test_task_run.task.title = ""
        test_task_run.task.description = ""
        test_task_run.task.save(update_fields=["title", "description", "updated_at"])
        test_task_run.state = {"prewarmed": True, "await_user_message": True}
        test_task_run.save(update_fields=["state", "updated_at"])

        async_to_sync(_run_update_task_run_status)(
            activity_environment,
            UpdateTaskRunStatusInput(
                run_id=str(test_task_run.id),
                status=TaskRun.Status.COMPLETED,
                timed_out_inactivity=True,
            ),
        )

        test_task_run.task.refresh_from_db()
        assert test_task_run.task.deleted is True

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "state,timed_out,expected_reason",
        [
            ({"prewarmed": True, "await_user_message": True}, True, "idle_timeout"),
            ({"prewarmed": True, "await_user_message": True}, False, "other"),
            # Activation clears `await_user_message`, so this warm was used. Counting it as a miss
            # would understate the warm hit rate the rollout decision reads.
            ({"prewarmed": True}, True, None),
            # Mid-activation: the marker is set before the first message is signaled and
            # `await_user_message` is cleared only after, so a run that terminalizes in between still
            # carries both older markers while already counted as activated.
            ({"prewarmed": True, "await_user_message": True, "warm_activated": True}, True, None),
            # Never warmed at all — a plain run terminalizing is not a warm miss.
            ({}, True, None),
        ],
    )
    def test_counts_a_warm_run_that_terminalized_unused(
        self, activity_environment: ActivityEnvironment, test_task_run: TaskRun, state, timed_out, expected_reason
    ) -> None:
        test_task_run.state = state
        test_task_run.save(update_fields=["state", "updated_at"])

        with patch("products.tasks.backend.metrics.observe_prewarmed_unused") as m_observe:
            async_to_sync(_run_update_task_run_status)(
                activity_environment,
                UpdateTaskRunStatusInput(
                    run_id=str(test_task_run.id),
                    status=TaskRun.Status.COMPLETED,
                    timed_out_inactivity=timed_out,
                ),
            )

        if expected_reason is None:
            m_observe.assert_not_called()
        else:
            assert m_observe.call_args.kwargs["reason"] == expected_reason

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "marker",
        [TIMED_OUT_WALL_CLOCK_STATE_KEY, SANDBOX_GONE_STATE_KEY],
    )
    def test_timeout_marker_is_recorded_in_state(self, activity_environment, test_task_run, marker):
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.FAILED,
            timeout_marker=marker,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.FAILED
        assert test_task_run.error_message is None
        assert test_task_run.state.get(marker) is True

    @pytest.mark.django_db(transaction=True)
    def test_unknown_timeout_marker_is_not_written(self, activity_environment, test_task_run):
        # The marker comes off the wire, so only allowlisted keys may reach TaskRun.state.
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.FAILED,
            timeout_marker="arbitrary_key",
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert "arbitrary_key" not in (test_task_run.state or {})

    @pytest.mark.django_db(transaction=True)
    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    def test_publishes_stream_state_event(self, mock_publish_stream_state_event, activity_environment, test_task_run):
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.IN_PROGRESS)

        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        mock_publish_stream_state_event.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "status,expected_event",
        [
            (TaskRun.Status.COMPLETED, "task_run_completed"),
            (TaskRun.Status.FAILED, "task_run_failed"),
        ],
    )
    @patch("products.tasks.backend.temporal.process_task.activities.update_task_run_status.record_run_token_usage")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_terminal_transition_captures_analytics_with_usage(
        self, mock_capture, mock_record, activity_environment, test_task_run, status, expected_event
    ):
        test_task_run.state = {
            **(test_task_run.state or {}),
            "token_usage": dict(TOKEN_USAGE),
            "rtk_effective": True,
            "runtime_adapter": "codex",
        }
        test_task_run.save(update_fields=["state"])

        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=status,
            error_message="boom" if status == TaskRun.Status.FAILED else None,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == expected_event]
        assert len(captured) == 1
        props = captured[0].kwargs["properties"]
        assert props["input_tokens"] == 1200
        assert props["total_tokens"] == 1500
        assert props["usage_turns"] == 3
        assert props["rtk_enabled"] is True
        assert props["run_environment"] == test_task_run.environment
        assert props["termination_reason"] is None
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["rtk_enabled"] is True
        assert mock_record.call_args.kwargs["runtime_adapter"] == "codex"
        assert mock_record.call_args.kwargs["status"] == status

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "status,timed_out_inactivity,timeout_marker,expected_event,expected_reason",
        [
            (TaskRun.Status.COMPLETED, True, None, "task_run_completed", TIMED_OUT_INACTIVITY_STATE_KEY),
            (
                TaskRun.Status.FAILED,
                False,
                TIMED_OUT_WALL_CLOCK_STATE_KEY,
                "task_run_failed",
                TIMED_OUT_WALL_CLOCK_STATE_KEY,
            ),
        ],
    )
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_terminal_analytics_carries_termination_reason(
        self,
        mock_capture,
        activity_environment,
        test_task_run,
        status,
        timed_out_inactivity,
        timeout_marker,
        expected_event,
        expected_reason,
    ):
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=status,
            timed_out_inactivity=timed_out_inactivity,
            timeout_marker=timeout_marker,
            agent_active_at_termination=False,
            end_of_turn_received=True,
            last_agent_heartbeat_at="2026-08-19T10:00:00+00:00",
            seconds_since_last_agent_heartbeat=1800.0,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == expected_event]
        properties = captured[0].kwargs["properties"]
        assert properties["termination_reason"] == expected_reason
        assert properties["agent_active_at_termination"] is False
        assert properties["end_of_turn_received"] is True
        assert properties["last_agent_heartbeat_at"] == "2026-08-19T10:00:00+00:00"
        assert properties["seconds_since_last_agent_heartbeat"] == 1800.0

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "error_type,expected_error_type",
        [
            ("ActivityError", "ActivityError"),
            (None, "unspecified"),
        ],
    )
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_failed_transition_carries_error_type_and_message_tail(
        self, mock_capture, activity_environment, test_task_run, error_type, expected_error_type
    ):
        error_message = "x" * 1400 + "TypeError: cannot read boot manifest"
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.FAILED,
            error_message=error_message,
            error_type=error_type,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "task_run_failed"]
        assert len(captured) == 1
        props = captured[0].kwargs["properties"]
        assert props["error_type"] == expected_error_type
        assert len(props["error_message"]) == 500
        assert props["error_message"].endswith("TypeError: cannot read boot manifest")

    @pytest.mark.django_db(transaction=True)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_repeated_terminal_update_does_not_double_capture(self, mock_capture, activity_environment, test_task_run):
        test_task_run.task.origin_product = Task.OriginProduct.POSTHOG_AI
        test_task_run.task.save(update_fields=["origin_product"])
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.COMPLETED)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        completed = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "task_run_completed"]
        assert len(completed) == 1
        chats = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "chat with ai"]
        assert len(chats) == 1

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "origin_product,status,expected_event",
        [
            (Task.OriginProduct.POSTHOG_AI, TaskRun.Status.COMPLETED, "chat with ai"),
            (Task.OriginProduct.POSTHOG_AI, TaskRun.Status.FAILED, "chat with ai failed"),
            (Task.OriginProduct.USER_CREATED, TaskRun.Status.COMPLETED, None),
            (Task.OriginProduct.USER_CREATED, TaskRun.Status.FAILED, None),
        ],
    )
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_posthog_ai_chat_outcome_is_captured_per_origin_and_status(
        self, mock_capture, activity_environment, test_task_run, origin_product, status, expected_event
    ):
        test_task_run.task.origin_product = origin_product
        test_task_run.task.save(update_fields=["origin_product"])

        async_to_sync(activity_environment.run)(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=str(test_task_run.id),
                status=status,
                error_message="boom" if status == TaskRun.Status.FAILED else None,
            ),
        )

        chats = [c for c in mock_capture.call_args_list if str(c.kwargs.get("event", "")).startswith("chat with ai")]
        if expected_event is None:
            assert chats == []
            return
        assert [c.kwargs["event"] for c in chats] == [expected_event]
        props = chats[0].kwargs["properties"]
        assert props["agent_runtime"] == "sandbox"
        assert props["agent_mode"] is None
        assert props["is_new_conversation"] is True
        if status == TaskRun.Status.FAILED:
            assert props["error_message"] == "boom"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "predecessor_state,run_state,expected_is_new",
        [
            # An earlier run that held a chat continues the conversation.
            ({}, {}, False),
            # An earlier prewarm nobody typed into does not — the next message resumes into a
            # successor, so counting it would report the first real chat as a continuation.
            ({"prewarmed": True, "await_user_message": True}, {}, True),
            # A conversation carried over from LangGraph is continued, however little sandbox
            # history it has: the conversion starts it on a fresh task with no earlier run.
            (None, {"converted_from_langgraph": True}, False),
            (None, {}, True),
        ],
    )
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_prior_history_decides_whether_a_conversation_is_new(
        self, mock_capture, activity_environment, test_task_run, predecessor_state, run_state, expected_is_new
    ):
        test_task_run.task.origin_product = Task.OriginProduct.POSTHOG_AI
        test_task_run.task.save(update_fields=["origin_product"])
        if run_state:
            test_task_run.state = run_state
            test_task_run.save(update_fields=["state", "updated_at"])
        if predecessor_state is not None:
            predecessor = TaskRun.objects.create(
                task=test_task_run.task,
                team=test_task_run.team,
                status=TaskRun.Status.COMPLETED,
                state=predecessor_state,
            )
            # `created_at` is auto_now_add, so pin the ordering rather than trusting two inserts
            # microseconds apart.
            TaskRun.objects.filter(id=predecessor.id).update(created_at=test_task_run.created_at - timedelta(seconds=1))

        async_to_sync(activity_environment.run)(
            update_task_run_status,
            UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.COMPLETED),
        )

        chats = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "chat with ai"]
        assert len(chats) == 1
        assert chats[0].kwargs["properties"]["is_new_conversation"] is expected_is_new

    @pytest.mark.django_db(transaction=True)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_a_prewarm_nobody_typed_into_is_not_a_chat(self, mock_capture, activity_environment, test_task_run):
        test_task_run.task.origin_product = Task.OriginProduct.POSTHOG_AI
        test_task_run.task.title = ""
        test_task_run.task.description = ""
        test_task_run.task.save(update_fields=["origin_product", "title", "description", "updated_at"])
        test_task_run.state = {"prewarmed": True, "await_user_message": True}
        test_task_run.save(update_fields=["state", "updated_at"])

        async_to_sync(_run_update_task_run_status)(
            activity_environment,
            UpdateTaskRunStatusInput(
                run_id=str(test_task_run.id),
                status=TaskRun.Status.COMPLETED,
                timed_out_inactivity=True,
            ),
        )

        events = [c.kwargs.get("event") for c in mock_capture.call_args_list]
        assert not [e for e in events if str(e).startswith("chat with ai")]
        # Only the chat reading is suppressed — the run still completed, and still reports it.
        assert "task_run_completed" in events

    @pytest.mark.django_db(transaction=True)
    def test_terminal_retry_completes_loop_bookkeeping_exactly_once(self, activity_environment, test_task_run):
        loop = Loop(
            team=test_task_run.team,
            created_by=test_task_run.task.created_by,
            name="Nightly digest",
            instructions="Summarize",
            runtime_adapter="claude",
        )
        loop.save()
        test_task_run.state = {**(test_task_run.state or {}), "loop_id": str(loop.id)}
        test_task_run.status = TaskRun.Status.FAILED
        test_task_run.error_message = "sandbox crashed"
        test_task_run.save(update_fields=["state", "status", "error_message"])

        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id), status=TaskRun.Status.FAILED, error_message="sandbox crashed"
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        loop.refresh_from_db()
        assert loop.last_run_status == TaskRun.Status.FAILED
        assert loop.last_error == "sandbox crashed"
        assert loop.consecutive_failures == 1
        assert loop.last_run_at is not None

    @pytest.mark.django_db(transaction=True)
    def test_missing_task_run_raises_non_retryable(self, activity_environment):
        # Rows hard-deleted mid-run (team deletion cascade) must fail the workflow fast,
        # not be swallowed as a successful status write.
        non_existent_run_id = "550e8400-e29b-41d4-a716-446655440000"
        input_data = UpdateTaskRunStatusInput(
            run_id=non_existent_run_id,
            status=TaskRun.Status.IN_PROGRESS,
        )
        with pytest.raises(ApplicationError) as exc_info:
            async_to_sync(activity_environment.run)(update_task_run_status, input_data)
        assert exc_info.value.non_retryable is True

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "extra_state,output,expected_delta",
        [
            ({"wizard_head_branch": "posthog/instrumentation-ab12cd"}, None, 1.0),
            ({"wizard_head_branch": "posthog/instrumentation-ab12cd"}, {"pr_url": "https://x/pull/1"}, 0.0),
            ({}, None, 0.0),
        ],
    )
    def test_terminal_status_counts_unbound_wizard_runs(
        self, activity_environment, test_task_run, extra_state, output, expected_delta
    ):
        from prometheus_client import REGISTRY

        test_task_run.state = {**(test_task_run.state or {}), **extra_state}
        if output:
            test_task_run.output = output
        test_task_run.save(update_fields=["state", "output"])
        labels = {"status": "completed"}
        before = REGISTRY.get_sample_value("posthog_tasks_wizard_run_unbound_total", labels) or 0.0

        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.COMPLETED)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        after = REGISTRY.get_sample_value("posthog_tasks_wizard_run_unbound_total", labels) or 0.0
        assert after == before + expected_delta
