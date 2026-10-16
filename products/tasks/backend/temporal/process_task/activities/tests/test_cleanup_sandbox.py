import io
import os
import time
import uuid
import base64
import shutil
import tarfile
import threading
import subprocess
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import IO

import pytest
from unittest.mock import patch

from django.db import OperationalError
from django.test import override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from pytest_mock import MockerFixture
from temporalio.exceptions import ApplicationError

from posthog.models import OAuthAccessToken
from posthog.storage.object_storage import ObjectStorageError

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError, SandboxRateLimitedError
from products.tasks.backend.facade.billing import get_task_run_cost
from products.tasks.backend.logic.services.agentsh import GITHUB_ENV_FILE
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.gateway_usage import record_gateway_routing
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import (
    ExecutionResult,
    ExecutionStream,
    Sandbox,
    SandboxConfig,
    SandboxTemplate,
)
from products.tasks.backend.logic.services.sandbox_recovery import SandboxRecoveryArchive
from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    get_task_run_stream_completed_key,
    get_task_run_stream_generation,
    get_task_run_stream_key,
    reset_task_run_stream,
)
from products.tasks.backend.models import SandboxSession, TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import (
    CleanupSandboxInput,
    cleanup_sandbox,
    cleanup_sandbox_now,
    publish_run_stream_completion,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    GitHubSandboxCredential,
    apply_github_credentials_to_sandbox,
)


@pytest.mark.django_db
def test_cleanup_sandbox_skips_agent_server_shutdown_for_regular_cleanup(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    get_by_id = mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    get_by_id.assert_called_once_with("sandbox-123")
    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
def test_cleanup_sandbox_records_cpu_usage_before_destroy(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.return_value = 12_345_678
    sandbox.read_billed_cpu_usage_usec.return_value = 15_000_000
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    close_session = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.close_sandbox_session"
    )

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    sandbox.read_cpu_usage_usec.assert_called_once_with()
    sandbox.destroy.assert_called_once_with()
    close_session.assert_called_once_with(
        "sandbox-123",
        reason="cleanup",
        cpu_usage_usec=12_345_678,
        billed_cpu_usage_usec=15_000_000,
        cpu_usage_measured_at=mocker.ANY,
    )


@pytest.mark.django_db
def test_cleanup_sandbox_ignores_cpu_usage_read_failure(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.side_effect = RuntimeError("unavailable")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
def test_cleanup_sandbox_requests_agent_server_shutdown_when_completing_stream(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.stop_agent_server.return_value.exit_code = 0
    get_by_id = mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(sandbox_id="sandbox-123", complete_stream_on_cleanup=True),
    )

    get_by_id.assert_called_once_with("sandbox-123")
    sandbox.stop_agent_server.assert_called_once_with()
    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()


@pytest.fixture
def accounting_session(test_task_run):
    record_gateway_routing(run_id=test_task_run.id, team_id=test_task_run.team_id, uses_gateway=True)
    now = timezone.now()
    return SandboxSession.objects.for_team(test_task_run.team_id).create(
        team_id=test_task_run.team_id,
        task_run=test_task_run,
        sandbox_id="sandbox-123",
        cpu_cores=2,
        memory_gb=4,
        ttl_seconds=600,
        created_at=now - timedelta(minutes=2),
        ttl_expires_at=now + timedelta(minutes=8),
        user_attributed_at=now - timedelta(minutes=2),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stop_outcome,state_error,resumed,credentials_cleared",
    [
        (0, None, False, True),
        (0, None, True, True),
        (1, None, False, True),
        (RuntimeError("transport failed"), None, False, True),
        (0, OperationalError("unavailable"), False, True),
        (0, None, False, False),
    ],
)
@override_settings(TASK_RUN_STREAM_GENERATION_ROTATION_ENABLED=True)
def test_retained_cleanup_preserves_recovery_state(
    mocker: MockerFixture,
    test_task_run: TaskRun,
    stop_outcome: int | RuntimeError,
    state_error: OperationalError | None,
    resumed: bool,
    credentials_cleared: bool,
) -> None:
    oauth = OAuthAccessToken.objects.create(
        token="synthetic-run-token",
        expires=timezone.now() + timedelta(hours=1),
        scope="task:write",
        sandbox_task_id=test_task_run.task_id,
    )
    generation = get_task_run_stream_generation(str(test_task_run.id))
    test_task_run.state = {
        "sandbox_oauth_token_ids": [str(oauth.id)],
        "sandbox_id": "sandbox-123",
        "sandbox_url": "https://sandbox.example.com",
        "sandbox_connect_token": "test-token",
        "sandbox_jwt_kid": "test-key",
        "sandbox_backend": "modal",
        "snapshot_external_id": "im-previous",
    }
    test_task_run.save(update_fields=["state"])
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.return_value = None
    sandbox.read_billed_cpu_usage_usec.return_value = None
    sandbox.execute.return_value.exit_code = 0 if credentials_cleared else 1
    sandbox.write_file.return_value.exit_code = 0
    if isinstance(stop_outcome, RuntimeError):
        sandbox.stop_agent_server.side_effect = stop_outcome
    else:
        sandbox.stop_agent_server.return_value.exit_code = stop_outcome
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    if state_error:
        mocker.patch.object(TaskRun, "update_state_atomic", side_effect=state_error)
    mocker.patch("products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.refresh_task_run_cost")
    archive = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.SandboxRecoveryArchive.create",
        side_effect=lambda *args, **kwargs: reset_task_run_stream(str(test_task_run.id)) if resumed else None,
    )
    publish = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_run_stream_completion",
        wraps=publish_run_stream_completion,
    )

    expected_error = type(state_error) if state_error else RuntimeError
    success = stop_outcome == 0 and state_error is None and credentials_cleared
    with nullcontext() if success else pytest.raises(expected_error):
        cleanup_sandbox_now(
            CleanupSandboxInput(
                sandbox_id="sandbox-123",
                run_id=str(test_task_run.id),
                retain_sandbox=True,
                complete_stream_on_cleanup=True,
                stream_generation=generation,
            )
        )

    assert sandbox.destroy.call_count == int(not success)
    oauth.refresh_from_db()
    assert (oauth.expires <= timezone.now()) == (state_error is None)
    assert sandbox.write_file.called
    sandbox.stop_agent_server.assert_called_once_with()
    test_task_run.refresh_from_db()
    if state_error is None:
        assert test_task_run.state["sandbox_retained_for_recovery"] == "sandbox-123"
        for key in ("sandbox_id", "sandbox_url", "sandbox_connect_token", "sandbox_jwt_kid", "sandbox_backend"):
            assert key not in test_task_run.state
    assert test_task_run.state["snapshot_external_id"] == "im-previous"
    assert publish.call_count == int(success)
    assert archive.call_count == int(success)
    completed = get_tasks_stream_redis_sync().exists(
        get_task_run_stream_completed_key(get_task_run_stream_key(str(test_task_run.id)))
    )
    assert bool(completed) == (success and not resumed)


@pytest.mark.django_db
def test_retained_archive_clears_the_last_senders_credentials(
    mocker: MockerFixture, test_task_run: TaskRun, tmp_path: Path
) -> None:
    repositories = ["example/first", "example/second"]
    test_task_run.state = {"repositories": repositories}
    test_task_run.save(update_fields=["state"])
    token = "synthetic-followup-sender-token"
    late_token = "synthetic-late-readonly-token"
    native = mocker.Mock(object_id="sandbox-123")
    native.poll.return_value = None

    def execute(*args: str, **kwargs: object) -> subprocess.Popen[str]:
        argv = [
            arg.replace("/tmp/workspace", str(tmp_path)).replace(GITHUB_ENV_FILE, str(tmp_path / "github.env"))
            for arg in args
        ]
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def write_file(path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        (tmp_path / "github.env").write_bytes(payload)
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    native.exec.side_effect = execute
    sandbox = ModalSandbox(sandbox=native, config=SandboxConfig(name="archive-test"))
    mocker.patch.object(sandbox, "write_file", side_effect=write_file)
    for repository in repositories:
        result = sandbox.execute(
            f"git init /tmp/workspace/repos/{repository} && "
            f"git -C /tmp/workspace/repos/{repository} remote add origin https://github.com/{repository}.git"
        )
        assert result.exit_code == 0
    assert apply_github_credentials_to_sandbox(sandbox, repositories, token)
    assert token in (tmp_path / "repos/example/first/.git/config").read_text()
    shutil.copytree(tmp_path / "repos/example/first", tmp_path / "copied-checkout")
    (tmp_path / "repos/example/second").rename(tmp_path / "moved-checkout")
    local = DockerSandbox(container_id="local-test", config=SandboxConfig(name="archive-test"), host_port=8000)
    mocker.patch.object(local, "is_running", return_value=True)
    popen = subprocess.Popen

    def execute_stream(
        command: str, timeout_seconds: int | None = None, *, isolated: bool = False, buffer_stdout: bool = True
    ) -> ExecutionStream:
        def launch(argv: list[str], **kwargs: object) -> subprocess.Popen[str]:
            return popen(
                [arg.replace("/tmp/workspace", str(tmp_path)) for arg in argv[3:]],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )

        with patch("subprocess.Popen", side_effect=launch):
            return local.execute_stream(command, timeout_seconds, isolated=isolated, buffer_stdout=buffer_stdout)

    mocker.patch.object(sandbox, "execute_stream", side_effect=execute_stream)
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    mocker.patch.object(sandbox, "stop_agent_server", return_value=ExecutionResult(stdout="", stderr="", exit_code=0))
    mocker.patch.object(sandbox, "read_cpu_usage_usec", return_value=None)
    mocker.patch.object(sandbox, "read_billed_cpu_usage_usec", return_value=None)
    archive = io.BytesIO()

    def upload(path: str, stream: IO[bytes], extras: dict[str, str]) -> None:
        archive.write(stream.read())

    mocker.patch("posthog.storage.object_storage.write_stream", side_effect=upload)
    mocker.patch("posthog.storage.object_storage.head_object", side_effect=lambda _: {"ContentLength": archive.tell()})

    def resolve_token(*args: object, **kwargs: object) -> str:
        cleanup_sandbox_now(
            CleanupSandboxInput(sandbox_id=sandbox.id, run_id=str(test_task_run.id), retain_sandbox=True)
        )
        return late_token

    mocker.patch(
        "products.tasks.backend.temporal.process_task.sandbox_credentials.get_readonly_github_token",
        side_effect=resolve_token,
    )
    context = TaskProcessingContext(
        task_id=str(test_task_run.task_id),
        run_id=str(test_task_run.id),
        team_id=test_task_run.team_id,
        team_uuid="team",
        organization_id="organization",
        github_integration_id=None,
        repository=None,
        distinct_id="test-user",
        state={"github_read_access": True, "repositories": repositories},
    )
    assert not GitHubSandboxCredential().refresh(sandbox, context, test_task_run.task).refreshed
    assert late_token not in (tmp_path / "github.env").read_text()

    archive.seek(0)
    with tarfile.open(fileobj=archive, mode="r:gz") as exported:
        assert "./copied-checkout/.git/HEAD" in exported.getnames()
        assert "./moved-checkout/.git/HEAD" in exported.getnames()
        assert not any(name.endswith("/.git/config") for name in exported.getnames())
        for member in exported.getmembers():
            if member.isfile():
                file = exported.extractfile(member)
                assert file is not None
                assert token.encode() not in file.read()


@pytest.mark.django_db
@pytest.mark.parametrize("already_stopped,verified", [(False, False), (True, False), (True, True)])
def test_retained_cleanup_retries_export_but_accepts_expired_sandbox(
    mocker: MockerFixture, test_task_run: TaskRun, already_stopped: bool, verified: bool
) -> None:
    if verified:
        test_task_run.state = {"sandbox_recovery_archive_sandbox_id": "sandbox-123"}
        test_task_run.save(update_fields=["state"])
    mocker.patch("posthog.storage.object_storage.head_object", return_value={"ContentLength": 10})
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.execute.return_value.exit_code = 0
    sandbox.write_file.return_value.exit_code = 0
    sandbox.stop_agent_server.return_value.exit_code = 0
    sandbox.read_cpu_usage_usec.return_value = None
    sandbox.read_billed_cpu_usage_usec.return_value = None
    if already_stopped:
        sandbox.stop_agent_server.side_effect = SandboxNotRunningError(
            "Sandbox expired", {"sandbox_id": sandbox.id}, cause=RuntimeError("expired"), capture=False
        )
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    archive = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.SandboxRecoveryArchive.create",
        side_effect=RuntimeError("upload failed"),
    )
    publish = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_run_stream_completion"
    )
    with nullcontext() if verified else pytest.raises(ApplicationError if already_stopped else RuntimeError):
        cleanup_sandbox_now(
            CleanupSandboxInput(
                sandbox_id=sandbox.id,
                run_id=str(test_task_run.id),
                retain_sandbox=True,
                complete_stream_on_cleanup=True,
            )
        )
    sandbox.destroy.assert_not_called()
    assert archive.call_count == int(not already_stopped)
    assert publish.call_count == int(verified)

    if not already_stopped:
        test_task_run.refresh_from_db()
        original_deadline = test_task_run.state["sandbox_recovery_deadline"]
        archive.side_effect = None
        cleanup_sandbox_now(
            CleanupSandboxInput(
                sandbox_id=sandbox.id,
                run_id=str(test_task_run.id),
                retain_sandbox=True,
                recovery_deadline=original_deadline + 600,
            )
        )
        test_task_run.refresh_from_db()
        assert test_task_run.state["sandbox_recovery_deadline"] == original_deadline


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [None, "partial", "archive", "download", "size", "upload", "rate_limit"])
@override_settings(OBJECT_STORAGE_TASKS_FOLDER="custom-task-prefix")
def test_recovery_archive_is_published_only_after_verified_upload(
    mocker: MockerFixture, test_task_run: TaskRun, failure: str | None
) -> None:
    test_task_run.state = {
        "sandbox_retained_for_recovery": "sandbox-123",
        "sandbox_recovery_archive_sandbox_id": "sandbox-old",
    }
    test_task_run.save(update_fields=["state"])
    assert SandboxRecoveryArchive.download_url(test_task_run) is None
    sandbox = mocker.Mock(id="sandbox-123")
    execution = sandbox.execute_stream.return_value
    stop = mocker.Mock()
    stop.wait.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    sandbox.execute_stream.side_effect = [execution, stop]
    payload = b"synthetic archive"
    encoded = base64.b64encode(payload).decode()
    sandbox.execute_stream.return_value.iter_stdout.return_value = iter([encoded[:3], encoded[3:8] + "\n", encoded[8:]])
    if failure == "download":
        sandbox.execute_stream.return_value.iter_stdout.side_effect = RuntimeError("download failed")
    sandbox.execute_stream.return_value.wait.return_value = ExecutionResult(
        stdout="",
        stderr="tar: GITHUB_TOKEN=synthetic-token Permission denied",
        exit_code=2 if failure == "archive" else int(failure == "partial"),
    )
    provider_error = SandboxRateLimitedError("Sandbox stream rate limited", {"sandbox_id": sandbox.id})
    if failure == "rate_limit":

        def limited_output() -> Iterator[str]:
            yield encoded[:4]
            raise provider_error

        sandbox.execute_stream.return_value.iter_stdout.return_value = limited_output()
    uploaded: list[tuple[str, bytes]] = []

    def upload(path: str, stream: IO[bytes], extras: dict[str, str]) -> None:
        assert extras == {"Tagging": f"ttl_days=30&team_id={test_task_run.team_id}"}
        if failure == "upload":
            raise RuntimeError("upload failed")
        try:
            uploaded.append((path, stream.read()))
        except Exception as error:
            raise ObjectStorageError("write_stream failed") from error

    mocker.patch("posthog.storage.object_storage.write_stream", side_effect=upload)
    mocker.patch(
        "posthog.storage.object_storage.head_object",
        return_value={"ContentLength": 0 if failure == "size" else len(payload)},
    )
    success = failure in {None, "partial"}

    error_type = SandboxRateLimitedError if failure == "rate_limit" else RuntimeError
    with nullcontext() if success else pytest.raises(error_type) as error:
        SandboxRecoveryArchive.create(test_task_run, sandbox)
    if failure == "rate_limit":
        assert error is not None
        assert error.value is provider_error
        assert provider_error.next_retry_delay is not None
    if failure == "archive":
        assert error is not None
        assert "exit 2" in str(error.value)
        assert "Permission denied" in str(error.value)
        assert "synthetic-token" not in str(error.value)

    test_task_run.refresh_from_db()
    assert ((test_task_run.state or {}).get("sandbox_recovery_archive_sandbox_id") == sandbox.id) == success
    assert sandbox.execute_stream.call_args.kwargs["isolated"]
    assert sandbox.execute_stream.call_args.kwargs["buffer_stdout"] is False
    execution.close.assert_called_once()
    stop.close.assert_called_once()
    if success:
        assert uploaded[0][0].startswith("custom-task-prefix/recovery/")
        assert uploaded == [(SandboxRecoveryArchive.storage_path(test_task_run, sandbox.id), payload)]
        assert uploaded[0][0] != SandboxRecoveryArchive.storage_path(test_task_run, "sandbox-old")
        assert (test_task_run.state or {})["sandbox_recovery_archive_partial"] == (failure == "partial")
        sandbox.reset_mock()
        SandboxRecoveryArchive.create(test_task_run, sandbox)
        sandbox.execute_stream.assert_not_called()


@pytest.mark.django_db
def test_recovery_archive_refuses_an_expired_retry(mocker: MockerFixture, test_task_run: TaskRun) -> None:
    sandbox = mocker.Mock(id="sandbox-123")
    upload = mocker.patch("posthog.storage.object_storage.write_stream")
    with pytest.raises(RuntimeError, match="deadline expired"):
        SandboxRecoveryArchive.create(test_task_run, sandbox, deadline=time.time() - 1)
    upload.assert_not_called()
    sandbox.execute_stream.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "environment,uses_gateway,lookup_fails,strict",
    [
        (TaskRun.Environment.CLOUD, True, False, True),
        (TaskRun.Environment.CLOUD, False, False, True),
        (TaskRun.Environment.LOCAL, False, False, True),
        (TaskRun.Environment.CLOUD, True, True, True),
        (TaskRun.Environment.CLOUD, True, False, False),
    ],
)
def test_cleanup_sandbox_closes_session_after_cleanup_error(
    mocker: MockerFixture,
    test_task_run: TaskRun,
    accounting_session: SandboxSession,
    environment: TaskRun.Environment,
    uses_gateway: bool,
    lookup_fails: bool,
    strict: bool,
) -> None:
    if not uses_gateway:
        test_task_run.state = {}
        test_task_run.environment = environment
        test_task_run.save(update_fields=["state", "environment"])
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.return_value = 12_345_678
    sandbox.read_billed_cpu_usage_usec.return_value = 15_000_000
    sandbox.destroy.side_effect = RuntimeError("cleanup failed")
    mocker.patch.object(
        Sandbox,
        "get_by_id",
        side_effect=RuntimeError("cleanup failed") if lookup_fails else None,
        return_value=sandbox,
    )
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )
    closed_at = timezone.now()

    for attempt in range(2):
        with patch("django.utils.timezone.now", return_value=closed_at + timedelta(minutes=attempt)):
            with pytest.raises(RuntimeError, match="cleanup failed") if strict else nullcontext():
                cleanup_sandbox_now(
                    CleanupSandboxInput(
                        sandbox_id="sandbox-123",
                        run_id=str(test_task_run.id),
                        complete_stream_on_cleanup=strict,
                    ),
                )
            accounting_session.refresh_from_db()
            assert accounting_session.ended_at == closed_at
            if environment == TaskRun.Environment.CLOUD:
                test_task_run.refresh_from_db()
                assert (
                    test_task_run.state["compute_cost"]
                    == get_task_run_cost(run_id=test_task_run.id, team_id=test_task_run.team_id).compute_cost
                )

    assert sandbox.destroy.call_count == (0 if lookup_fails else 2)
    if not lookup_fails:
        assert accounting_session.provider_cpu_usage_usec == 12_345_678
        assert accounting_session.provider_billed_cpu_usage_usec == 15_000_000
    publish_complete.assert_not_called()


@pytest.mark.django_db
def test_cleanup_sandbox_destroys_before_accounting_lookup(
    mocker: MockerFixture, test_task_run: TaskRun, accounting_session: SandboxSession
) -> None:
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    destroyed_at_lookup: list[bool] = []

    def unavailable(*args: object, **kwargs: object) -> None:
        destroyed_at_lookup.append(sandbox.destroy.called)
        raise OperationalError("unavailable")

    with patch.object(TaskRun.objects, "filter", side_effect=unavailable):
        cleanup_sandbox_now(CleanupSandboxInput(sandbox_id="sandbox-123", run_id=str(test_task_run.id)))

    sandbox.destroy.assert_called_once_with()
    assert destroyed_at_lookup == [True]
    accounting_session.refresh_from_db()
    assert accounting_session.ended_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize("complete_stream,uses_gateway", [(False, True), (True, True), (True, False)])
def test_cleanup_sandbox_persists_compute_without_waiting_for_gateway_usage(
    mocker, test_task_run, accounting_session, complete_stream, uses_gateway
):
    test_task_run.refresh_from_db()
    test_task_run.state["unprocessed_request_ids"] = ["pending-request"]
    if not uses_gateway:
        test_task_run.state = {"token_cost_incomplete": True}
    test_task_run.save(update_fields=["state"])
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.stop_agent_server.return_value.exit_code = 0
    sandbox.read_cpu_usage_usec.return_value = None
    sandbox.read_billed_cpu_usage_usec.return_value = None
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    gateway_lookup = mocker.patch("aiohttp.ClientSession._request")

    def publish_complete(*_args, **_kwargs):
        test_task_run.refresh_from_db()
        assert (
            test_task_run.state["compute_cost"]
            == get_task_run_cost(run_id=test_task_run.id, team_id=test_task_run.team_id).compute_cost
        )
        assert test_task_run.state["compute_cost"] > 0
        return True

    publish = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete",
        side_effect=publish_complete,
    )
    cleanup_sandbox_now(
        CleanupSandboxInput(
            sandbox_id="sandbox-123", run_id=str(test_task_run.id), complete_stream_on_cleanup=complete_stream
        ),
    )

    sandbox.destroy.assert_called_once_with()
    assert sandbox.stop_agent_server.call_count == int(complete_stream)
    assert publish.call_count == int(complete_stream)
    gateway_lookup.assert_not_called()
    accounting_session.refresh_from_db()
    assert accounting_session.ended_at is not None
    test_task_run.refresh_from_db()
    assert test_task_run.state["compute_cost"] > 0
    if uses_gateway:
        assert test_task_run.state["unprocessed_request_ids"] == ["pending-request"]
    else:
        assert get_task_run_cost(run_id=test_task_run.id, team_id=test_task_run.team_id).token_cost is None


@pytest.mark.django_db
def test_cleanup_sandbox_ignores_invalid_optional_run_id(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(sandbox_id="sandbox-123", run_id="not-a-uuid"),
    )

    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
@pytest.mark.parametrize("current_sandbox", ["sandbox-123", "sandbox-replacement"])
@pytest.mark.parametrize("refresh_fails", [False, True])
def test_cleanup_sandbox_completes_stream_when_requested(mocker, test_task_run, current_sandbox, refresh_fails):
    run_id = str(test_task_run.id)
    connection = {
        "sandbox_id": current_sandbox,
        "sandbox_url": "https://sandbox.example.com",
        "sandbox_connect_token": "fake-token",
        "sandbox_jwt_kid": "fake-key",
        "sandbox_backend": "modal",
    }
    accounting_state: dict[str, object] = {"unprocessed_request_ids": [], "token_cost": {}}
    test_task_run.state = {"other": "preserved", **connection, **accounting_state}
    test_task_run.save(update_fields=["state"])
    if refresh_fails:
        mocker.patch(
            "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.refresh_task_run_cost",
            side_effect=OperationalError("unavailable"),
        )
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )

    cleanup_sandbox_now(
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()
    publish_complete.assert_called_once_with(run_id, False, expected_generation="initial")
    test_task_run.refresh_from_db()
    assert test_task_run.state == (
        {"other": "preserved", **accounting_state}
        | ({} if current_sandbox == "sandbox-123" else connection)
        | ({} if refresh_fails else {"compute_cost": None})
    )


@pytest.mark.django_db
def test_cleanup_sandbox_writes_real_completion_sentinel_when_requested(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    stream_key = get_task_run_stream_key(run_id)
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async def _read_stream_events():
        redis_stream = TaskRunRedisStream(stream_key)
        messages = await redis_stream._redis_client.xrange(stream_key)
        await redis_stream.delete_stream()
        return [message[b"data"] for _stream_id, message in messages]

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    assert async_to_sync(_read_stream_events)() == [b'{"type": "STREAM_STATUS", "status": "complete"}']


@pytest.mark.django_db
def test_cleanup_sandbox_completes_stream_when_sandbox_is_already_gone(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    mocker.patch.object(
        Sandbox,
        "get_by_id",
        side_effect=SandboxNotFoundError(
            "Sandbox sandbox-123 not found",
            {"sandbox_id": "sandbox-123"},
            cause=RuntimeError("not found"),
        ),
    )
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    publish_complete.assert_called_once_with(run_id, False, expected_generation="initial")


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCleanupSandboxActivity:
    @pytest.mark.django_db
    def test_cleanup_sandbox_success(self, activity_environment, assert_sandbox_shutdown):
        test_tag = f"test-cleanup-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-sandbox-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        existing_sandbox = Sandbox.get_by_id(sandbox_id)
        assert existing_sandbox.id == sandbox_id
        assert existing_sandbox.is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        assert_sandbox_shutdown(sandbox_id)

    @pytest.mark.django_db
    def test_cleanup_sandbox_not_found_does_not_raise(self, activity_environment):
        input_data = CleanupSandboxInput(sandbox_id="non-existent-sandbox-id")

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_idempotency(self, activity_environment, assert_sandbox_shutdown):
        test_tag = f"test-cleanup-idempotent-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-idempotent-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        assert Sandbox.get_by_id(sandbox_id).is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        assert_sandbox_shutdown(sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_during_execution(self, activity_environment, assert_sandbox_shutdown):
        test_tag = f"test-cleanup-during-exec-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-during-execution-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        def run_long_command():
            try:
                sandbox.execute("sleep 30", timeout_seconds=60)
            except Exception:
                pass

        long_task = threading.Thread(target=run_long_command)
        long_task.start()

        time.sleep(5)

        assert Sandbox.get_by_id(sandbox_id).is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)
        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        long_task.join(timeout=5)

        assert_sandbox_shutdown(sandbox_id)
