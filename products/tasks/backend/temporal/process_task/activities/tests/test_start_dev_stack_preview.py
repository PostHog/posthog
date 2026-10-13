import asyncio

import pytest
from unittest.mock import MagicMock

from django.test import override_settings

from asgiref.sync import async_to_sync

from products.tasks.backend.constants import DEV_STACK_PREVIEW_PORT, DEV_STACK_PREVIEW_STATE_KEY
from products.tasks.backend.logic.services.sandbox import AgentServerResult, ExecutionResult
from products.tasks.backend.metrics import DEV_STACK_PREVIEW_TOTAL
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.start_dev_stack_preview import (
    StartDevStackPreviewInput,
    WaitDevStackPreviewInput,
    start_dev_stack_preview,
    wait_dev_stack_preview,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.start_dev_stack_preview"
SITE_URL = "https://us.posthog.example"
SANDBOX_HOST = "abc-8020.modal.host"
LOG_TAIL_WITH_A_SECRET = "hogli start failed POSTHOG_TASK_RUN_SESSION_TOKEN=super-secret-value"


def _sandbox(
    mocker,
    *,
    manifest_exit_code=0,
    prepare_exit_code=0,
    lock_exit_code=0,
    upload_exit_code=0,
    launch_exit_code=0,
    status_payload=None,
    on_status_read=None,
):
    sandbox = MagicMock()
    sandbox.create_preview_connect_credentials.return_value = AgentServerResult(
        url=f"https://{SANDBOX_HOST}", token="connect-token"
    )
    sandbox.write_file.return_value = ExecutionResult(stdout="", stderr="", exit_code=upload_exit_code)

    def _execute(command, timeout_seconds=None):
        if command.startswith("test -f"):
            return ExecutionResult(stdout="", stderr="", exit_code=manifest_exit_code)
        if command.startswith("mkdir "):
            return ExecutionResult(stdout="", stderr="", exit_code=prepare_exit_code)
        if command.startswith("flock "):
            return ExecutionResult(stdout="", stderr="", exit_code=lock_exit_code)
        if command.startswith("cat "):
            if on_status_read is not None:
                on_status_read()
            return ExecutionResult(stdout=status_payload or "", stderr="", exit_code=0)
        if command.startswith("tail "):
            return ExecutionResult(stdout=LOG_TAIL_WITH_A_SECRET, stderr="", exit_code=0)
        return ExecutionResult(stdout="", stderr="", exit_code=launch_exit_code)

    sandbox.execute.side_effect = _execute
    mocker.patch(f"{MODULE}.Sandbox.get_by_id", return_value=sandbox)
    return sandbox


def _enabled(context):
    context.dev_stack_preview_enabled = True
    context.repository = "PostHog/posthog"
    return context


def _start(context, activity_environment):
    return async_to_sync(activity_environment.run)(
        start_dev_stack_preview,
        StartDevStackPreviewInput(context=context, sandbox_id="sandbox-1", repository="PostHog/posthog"),
    )


def _wait(context, activity_environment):
    return async_to_sync(activity_environment.run)(
        wait_dev_stack_preview,
        WaitDevStackPreviewInput(context=context, sandbox_id="sandbox-1"),
    )


@pytest.fixture(autouse=True)
def fast_polling(mocker):
    mocker.patch(f"{MODULE}.POLL_INTERVAL_SECONDS", 0)
    mocker.patch(f"{MODULE}.READY_TIMEOUT_SECONDS", 0.05)


@pytest.fixture(autouse=True)
def agent_log(mocker):
    return mocker.patch(f"{MODULE}.emit_agent_log")


@pytest.fixture
def progress(mocker):
    return mocker.patch(f"{MODULE}.emit_progress")


def _outcome_count(outcome):
    return DEV_STACK_PREVIEW_TOTAL.labels(outcome=outcome)._value.get()


@pytest.mark.django_db
def test_start_is_skipped_when_the_run_has_no_preview(task_context, activity_environment, mocker, progress):
    sandbox = _sandbox(mocker)

    output = _start(task_context, activity_environment)

    assert output.started is False
    assert output.reason == "disabled"
    sandbox.execute.assert_not_called()
    progress.assert_not_called()


@pytest.mark.django_db
def test_start_is_skipped_when_the_sandbox_is_not_the_dev_stack_image(
    task_context, activity_environment, mocker, progress
):
    sandbox = _sandbox(mocker, manifest_exit_code=1)

    output = _start(_enabled(task_context), activity_environment)

    assert output.started is False
    assert output.reason == "not_dev_stack_image"
    sandbox.create_preview_connect_credentials.assert_not_called()
    progress.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure, expected_reason",
    [
        ({"prepare_exit_code": 5}, "prepare_exit_5"),
        ({"lock_exit_code": 1}, "lock_exit_1"),
        ({"upload_exit_code": 3}, "upload_exit_3"),
        ({"launch_exit_code": 7}, "launch_exit_7"),
    ],
)
def test_start_reports_step_failures_without_launching(
    task_context, activity_environment, mocker, progress, agent_log, failure, expected_reason
):
    sandbox = _sandbox(mocker, **failure)
    before = _outcome_count("launch_failed")

    output = _start(_enabled(task_context), activity_environment)

    assert output.started is False
    assert output.reason == expected_reason
    if "launch_exit_code" not in failure:
        assert not any(call.args[0].startswith("/usr/bin/env") for call in sandbox.execute.call_args_list)
    assert _outcome_count("launch_failed") == before + 1
    assert progress.call_args.kwargs["status"] == "failed"
    assert expected_reason in agent_log.call_args.args[2]


@pytest.mark.django_db
def test_start_raises_provider_errors_so_temporal_retries(task_context, activity_environment, mocker, progress):
    mocker.patch(f"{MODULE}.Sandbox.get_by_id", side_effect=RuntimeError("sandbox gone"))
    before = _outcome_count("launch_failed")

    with pytest.raises(RuntimeError):
        _start(_enabled(task_context), activity_environment)

    assert _outcome_count("launch_failed") == before + 1
    progress.assert_not_called()


@pytest.mark.django_db
def test_start_attaches_to_a_launch_already_in_progress(task_context, activity_environment, mocker, progress):
    sandbox = _sandbox(mocker, lock_exit_code=75)
    before = {outcome: _outcome_count(outcome) for outcome in ("started", "attached")}

    output = _start(_enabled(task_context), activity_environment)

    assert output.started is True
    assert output.attached is True
    sandbox.write_file.assert_not_called()
    assert not any(call.args[0].startswith("/usr/bin/env") for call in sandbox.execute.call_args_list)
    assert _outcome_count("attached") == before["attached"] + 1
    assert _outcome_count("started") == before["started"]
    assert progress.call_args.kwargs["status"] == "in_progress"


@pytest.mark.django_db
def test_start_launches_the_stack_against_the_minted_preview_host(task_context, activity_environment, mocker, progress):
    sandbox = _sandbox(mocker)

    output = _start(_enabled(task_context), activity_environment)

    assert output.started is True
    sandbox.create_preview_connect_credentials.assert_called_once()
    assert sandbox.create_preview_connect_credentials.call_args.kwargs["port"] == DEV_STACK_PREVIEW_PORT
    assert sandbox.write_file.call_args.args[0] == "/tmp/start-dev-stack-preview.sh"
    launch_command = sandbox.execute.call_args.args[0]
    assert launch_command.startswith("/usr/bin/env -i ")
    assert "HOME=/root" in launch_command
    assert "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/go/bin" in launch_command
    assert f"MODAL_HOST={SANDBOX_HOST}" in launch_command
    assert f"PREVIEW_PORT={DEV_STACK_PREVIEW_PORT}" in launch_command
    assert "REPO_PATH=/tmp/workspace/repos/posthog/posthog" in launch_command
    assert progress.call_args.kwargs["status"] == "in_progress"


@pytest.mark.django_db(transaction=True)
def test_start_skips_a_sandbox_that_already_serves_a_preview(
    task_context, test_task_run, activity_environment, mocker, progress
):
    TaskRun.update_state_atomic(
        test_task_run.id,
        updates={DEV_STACK_PREVIEW_STATE_KEY: {"port": DEV_STACK_PREVIEW_PORT, "sandbox_id": "sandbox-1"}},
    )
    sandbox = _sandbox(mocker)

    output = _start(_enabled(task_context), activity_environment)

    assert output.started is False
    assert output.reason == "already_ready"
    sandbox.execute.assert_not_called()
    progress.assert_not_called()


@pytest.mark.django_db(transaction=True)
@override_settings(SITE_URL=SITE_URL)
def test_wait_stamps_the_preview_and_links_it_through_posthog(
    task_context, test_task_run, activity_environment, mocker, progress
):
    _sandbox(mocker, status_payload='{"state": "ready"}')
    before = {outcome: _outcome_count(outcome) for outcome in ("ready", "failed", "timed_out", "cancelled")}

    output = _wait(_enabled(task_context), activity_environment)

    assert output.ready is True
    assert {outcome: _outcome_count(outcome) - before[outcome] for outcome in before} == {
        "ready": 1,
        "failed": 0,
        "timed_out": 0,
        "cancelled": 0,
    }
    test_task_run.refresh_from_db()
    preview = test_task_run.state[DEV_STACK_PREVIEW_STATE_KEY]
    assert preview["port"] == DEV_STACK_PREVIEW_PORT
    assert preview["sandbox_id"] == "sandbox-1"
    assert preview["ready_at"]
    detail = progress.call_args.kwargs["detail"]
    assert progress.call_args.kwargs["status"] == "completed"
    assert (
        detail
        == f"{SITE_URL}/api/projects/{task_context.team_id}/tasks/{task_context.task_id}/runs/{task_context.run_id}/preview/"
    )
    assert "modal.host" not in detail


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status_payload, expected_reason",
    [
        ("", "timed_out"),
        ('{"state": "starting"}', "timed_out"),
        ('{"state": "failed", "error": "hogli start failed"}', "failed"),
    ],
)
def test_wait_reports_a_failed_preview_without_failing_the_run(
    task_context, test_task_run, activity_environment, mocker, progress, agent_log, status_payload, expected_reason
):
    _sandbox(mocker, status_payload=status_payload)
    before = {outcome: _outcome_count(outcome) for outcome in ("ready", "failed", "timed_out", "cancelled")}

    output = _wait(_enabled(task_context), activity_environment)

    assert output.ready is False
    assert output.reason == expected_reason
    assert _outcome_count(expected_reason) == before[expected_reason] + 1
    assert sum(_outcome_count(outcome) - before[outcome] for outcome in before) == 1
    test_task_run.refresh_from_db()
    assert DEV_STACK_PREVIEW_STATE_KEY not in (test_task_run.state or {})
    assert progress.call_args.kwargs["status"] == "failed"
    warning = agent_log.call_args.args[2]
    assert "super-secret-value" not in warning
    assert "POSTHOG_TASK_RUN_SESSION_TOKEN=<redacted>" in warning


@pytest.mark.django_db
def test_wait_records_a_cancelled_boot(task_context, test_task_run, activity_environment, mocker, progress):
    mocker.patch(f"{MODULE}.READY_TIMEOUT_SECONDS", 60)
    _sandbox(mocker, status_payload='{"state": "starting"}', on_status_read=activity_environment.cancel)
    before = {outcome: _outcome_count(outcome) for outcome in ("ready", "failed", "timed_out", "cancelled")}

    with pytest.raises(asyncio.CancelledError):
        _wait(_enabled(task_context), activity_environment)

    assert _outcome_count("cancelled") == before["cancelled"] + 1
    assert sum(_outcome_count(outcome) - before[outcome] for outcome in before) == 1
    test_task_run.refresh_from_db()
    assert DEV_STACK_PREVIEW_STATE_KEY not in (test_task_run.state or {})
