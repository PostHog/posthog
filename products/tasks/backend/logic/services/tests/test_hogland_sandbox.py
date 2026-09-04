import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from hogland import ExecEvent, ExecResult, NotFoundError
from parameterized import parameterized

from products.tasks.backend.exceptions import (
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)
from products.tasks.backend.logic.services.cpu_billing import CPU_BILLING_STATE_PATH
from products.tasks.backend.logic.services.hogland_sandbox import (
    _STATIC_BOX_ENV,
    HoglandSandbox,
    get_hogland_api_token,
    get_hogland_client,
)
from products.tasks.backend.logic.services.sandbox import (
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    get_sandbox_class_for_sandbox_id,
)


def _exec_result(**overrides) -> ExecResult:
    payload = {"stdout": "", "stderr": "", "exit_code": 0, "timed_out": False, "duration_ms": 1}
    payload.update(overrides)
    return ExecResult.model_validate(payload)


def _mock_box(
    box_id: str = "box-abc123def456",
    status: str = "running",
    *,
    cpus: float = 4.0,
    memory_mib: int = 16384,
    disk_gib: int = 64,
) -> MagicMock:
    box = MagicMock()
    box.id = box_id
    box.status = status
    box.view.spec.cpus = cpus
    box.view.spec.memory_mib = memory_mib
    box.view.spec.disk_gib = disk_gib
    box.refresh.return_value = box
    return box


def _running_sandbox(box: MagicMock | None = None) -> HoglandSandbox:
    box = box if box is not None else _mock_box()
    return HoglandSandbox(box=box, config=SandboxConfig(name="test-sandbox"))


class TestHoglandSandboxCreate:
    def _create(self, config: SandboxConfig, box: MagicMock | None = None) -> tuple[HoglandSandbox, MagicMock]:
        client = MagicMock()
        client.create.return_value = box if box is not None else _mock_box()
        with patch("products.tasks.backend.logic.services.hogland_sandbox.get_hogland_client", return_value=client):
            sandbox = HoglandSandbox.create(config)
        return sandbox, client

    def test_create_maps_config_onto_the_golden_snapshot_restore(self):
        config = SandboxConfig(
            name="sandbox-task-1",
            environment_variables={"GITHUB_TOKEN": "tok", "IS_SANDBOX": "override"},
            metadata={"task_id": "t1", "run_id": "r1"},
        )
        sandbox, client = self._create(config)

        kwargs = client.create.call_args.kwargs
        assert kwargs["snapshot_id"] == "alias:posthog-tasks-default"
        # An omitted ttl on an unregistered kind means an immortal box.
        assert kwargs["ttl_seconds"] == config.ttl_seconds
        # Restores must inherit the golden snapshot's machine config.
        for sizing_key in ("cpus", "memory_mib", "disk_gib"):
            assert sizing_key not in kwargs
        # Explicit and defensive; a restore inherits the snapshot's "none" access_type anyway.
        assert kwargs["access_type"] == "none"
        assert kwargs["kind"] == "agent"
        assert kwargs["name"].startswith("sandbox-task-1-")
        assert sorted(kwargs["tags"]) == ["run_id=r1", "task_id=t1"]
        assert kwargs["env"]["GITHUB_TOKEN"] == "tok"
        assert kwargs["env"]["PATH"] == _STATIC_BOX_ENV["PATH"]
        # Per-run values win over the static baseline.
        assert kwargs["env"]["IS_SANDBOX"] == "override"
        assert sandbox.id == "box-abc123def456"
        assert config.snapshot_restored is False

    def test_create_records_the_read_back_box_shape_for_the_ledger(self):
        # The box ignores per-task overrides, so the ledger must reflect the shape the box
        # actually delivered, read back from box.view.spec — not the requested override and
        # not a pinned constant that a rebaked golden snapshot would silently desync.
        config = SandboxConfig(name="oversized", cpu_cores=16, memory_gb=64, disk_size_gb=100)
        box = _mock_box(cpus=8.0, memory_mib=32768, disk_gib=128)
        _sandbox, _client = self._create(config, box=box)
        assert (config.cpu_cores, config.memory_gb, config.disk_size_gb) == (8.0, 32.0, 128.0)

    def test_create_rejects_a_box_spec_missing_a_machine_dimension(self):
        # The read-back has no golden-constant fallback, so an incomplete spec must fail
        # loudly rather than price the ledger against a stale pinned shape.
        box = _mock_box()
        box.view.spec.memory_mib = None
        with pytest.raises(SandboxProvisionError):
            self._create(SandboxConfig(name="incomplete"), box=box)

    @parameterized.expand([(template,) for template in SandboxTemplate if template != SandboxTemplate.DEFAULT_BASE])
    def test_create_rejects_templates_without_a_golden_snapshot(self, template: SandboxTemplate):
        with pytest.raises(SandboxProvisionError):
            HoglandSandbox.create(SandboxConfig(name="t", template=template))


class TestHoglandSandboxExecution:
    def test_execute_returns_execution_result(self):
        box = _mock_box()
        box.exec.return_value = _exec_result(stdout="out", stderr="err", exit_code=3)
        sandbox = _running_sandbox(box)

        result = sandbox.execute("echo hi", timeout_seconds=5)

        assert (result.stdout, result.stderr, result.exit_code) == ("out", "err", 3)
        assert box.exec.call_args.args[0] == ["bash", "-c", "echo hi"]
        assert box.exec.call_args.kwargs["timeout_seconds"] == 5
        # No per-call env forwards as None, so the box keeps its baked/create env.
        assert box.exec.call_args.kwargs["env"] is None

    def test_execute_forwards_per_call_env_to_the_sdk(self):
        box = _mock_box()
        box.exec.return_value = _exec_result(stdout="out")
        sandbox = _running_sandbox(box)

        per_call_env = {"POSTHOG_TASK_RUN_SESSION_TOKEN": "fresh"}
        sandbox.execute("run", timeout_seconds=5, env=per_call_env)

        assert box.exec.call_args.kwargs["env"] == per_call_env

    def test_execute_timeout_raises_sandbox_timeout_error(self):
        box = _mock_box()
        box.exec.return_value = _exec_result(exit_code=-1, timed_out=True)
        sandbox = _running_sandbox(box)

        with pytest.raises(SandboxTimeoutError):
            sandbox.execute("sleep 100", timeout_seconds=1)

    def test_execute_wraps_transport_errors_and_redacts_the_command(self):
        box = _mock_box()
        box.exec.side_effect = RuntimeError("POSTHOG_TASK_RUN_SESSION_TOKEN='secret' boom")
        sandbox = _running_sandbox(box)

        with pytest.raises(SandboxExecutionError) as err:
            sandbox.execute("env POSTHOG_TASK_RUN_SESSION_TOKEN='secret' run", timeout_seconds=1)

        assert "secret" not in str(err.value.context)

    def test_execute_stream_buffers_output_and_defaults_missing_exit_to_minus_one(self):
        box = _mock_box()
        events = [
            {"kind": "stdout", "data": "a"},
            {"kind": "stderr", "data": "warn"},
            {"kind": "stdout", "data": "b"},
        ]
        box.exec_stream.return_value = iter([ExecEvent.model_validate(e) for e in events])
        sandbox = _running_sandbox(box)

        stream = sandbox.execute_stream("cmd")
        assert list(stream.iter_stdout()) == ["a", "b"]
        result = stream.wait()
        assert (result.stdout, result.stderr, result.exit_code) == ("ab", "warn", -1)


class TestHoglandSandboxLifecycle:
    def test_get_by_id_maps_not_found(self):
        client = MagicMock()
        client.get.side_effect = NotFoundError(status_code=404, body=None, request_id=None, message="nope")
        with patch("products.tasks.backend.logic.services.hogland_sandbox.get_hogland_client", return_value=client):
            with pytest.raises(SandboxNotFoundError):
                HoglandSandbox.get_by_id("box-000000000000")

    @parameterized.expand(
        [
            ("running", SandboxStatus.RUNNING),
            ("paused", SandboxStatus.SHUTDOWN),
            ("stopped", SandboxStatus.SHUTDOWN),
            ("failed", SandboxStatus.SHUTDOWN),
        ]
    )
    def test_get_status_maps_box_status(self, box_status: str, expected: SandboxStatus):
        sandbox = _running_sandbox(_mock_box(status=box_status))
        assert sandbox.get_status() == expected

    def test_get_status_of_deleted_box_is_shutdown(self):
        box = _mock_box()
        box.refresh.side_effect = NotFoundError(status_code=404, body=None, request_id=None, message="gone")
        sandbox = _running_sandbox(box)
        assert sandbox.get_status() == SandboxStatus.SHUTDOWN

    def test_connect_credentials_carry_no_token(self):
        box = _mock_box()
        box.proxy_url.return_value = "https://hogland.example/v1/hogboxes/hb-abc123/proxy/8080/"
        sandbox = _running_sandbox(box)

        credentials = sandbox.get_connect_credentials()

        # The hogland account bearer must never land in TaskRun.state; callers
        # attach it at request time instead.
        assert credentials.token is None
        assert credentials.url == "https://hogland.example/v1/hogboxes/hb-abc123/proxy/8080"
        assert sandbox.sandbox_url == credentials.url

    def test_snapshots_are_rejected(self):
        sandbox = _running_sandbox()
        with pytest.raises(SnapshotCreationError):
            sandbox.create_snapshot()
        with pytest.raises(SnapshotCreationError):
            sandbox.create_directory_snapshot("/tmp/workspace")


class TestSandboxIdPrefixDispatch:
    @parameterized.expand([("box-b99582fcb238", True), ("sb-abc123", False), ("sandbox-legacy", False)])
    def test_get_by_id_routes_on_id_prefix(self, sandbox_id: str, expect_hogland: bool):
        resolved = get_sandbox_class_for_sandbox_id(sandbox_id)
        assert (resolved is HoglandSandbox) == expect_hogland


class TestHoglandCpuBilling:
    def test_cpu_usage_reads_cgroup_via_exec_not_read_file(self):
        # hogpanion's file endpoint returns an empty body for sysfs paths (stat size 0),
        # so a read_file port of the Modal code would silently zero all attribution.
        box = _mock_box()
        box.exec.return_value = _exec_result(stdout="usage_usec 123456\nuser_usec 100\n")
        sandbox = _running_sandbox(box)

        assert sandbox.read_cpu_usage_usec() == 123456
        assert box.exec.call_args.args[0] == ["bash", "-c", "cat /sys/fs/cgroup/cpu.stat"]
        box.read_file.assert_not_called()

    def test_cpu_usage_returns_none_when_cgroup_read_fails(self):
        box = _mock_box()
        box.exec.return_value = _exec_result(exit_code=1)
        assert _running_sandbox(box).read_cpu_usage_usec() is None

    def test_sampler_and_billed_read_use_the_modal_equivalent_floor(self):
        # The floor must stay Modal's 0.5-core burstable default, not hogland's
        # 4-core reservation — otherwise the like-for-like billed number inflates 8x.
        box = _mock_box()
        box.exec.return_value = _exec_result()
        sandbox = _running_sandbox(box)

        assert sandbox.start_cpu_billing_sampler() is True
        assert " 0.5 " in box.exec.call_args.args[0][2]

    @parameterized.expand(
        [
            # Busy window: actual delta (2_000_000) beats the 0.5-core floor (500_000).
            ("busy", "1000000 5000000 1000", 7_000_000, 1_000_000_000 + 1000, 1_000_000 + 2_000_000),
            # Idle window: floor tops up — 0.5 cores over 1s of elapsed ns = 500_000 usec.
            ("idle", "1000000 5000000 1000", 5_000_100, 1_000_000_000 + 1000, 1_000_000 + 500_000),
        ]
    )
    def test_billed_usage_math(self, _name, state, current_cpu, now_ns, expected):
        box = _mock_box()
        box.read_file.return_value = state.encode()
        box.exec.return_value = _exec_result(stdout=f"usage_usec {current_cpu}\n")
        sandbox = _running_sandbox(box)

        with patch("products.tasks.backend.logic.services.hogland_sandbox.time.time_ns", return_value=now_ns):
            assert sandbox.read_billed_cpu_usage_usec() == expected
        box.read_file.assert_called_once_with(CPU_BILLING_STATE_PATH)

    @parameterized.expand([("malformed_state", "1 2"), ("empty_state", "")])
    def test_billed_usage_returns_none_on_bad_state(self, _name, state):
        box = _mock_box()
        box.read_file.return_value = state.encode()
        box.exec.return_value = _exec_result(stdout="usage_usec 1\n")
        assert _running_sandbox(box).read_billed_cpu_usage_usec() is None

    def test_billed_usage_returns_none_when_state_file_is_gone(self):
        box = _mock_box()
        box.read_file.side_effect = NotFoundError("gone", status_code=404)
        assert _running_sandbox(box).read_billed_cpu_usage_usec() is None


class TestHoglandAuthPrecedence:
    def test_file_mode_builds_an_uncached_client_from_the_current_file_contents(self, tmp_path):
        token_path = tmp_path / "token"
        token_path.write_text("tok-before\n")
        with override_settings(
            HOGLAND_API_URL="https://hogland.example",
            HOGLAND_API_TOKEN="static-tok",
            HOGLAND_API_TOKEN_FILE=str(token_path),
        ):
            with patch("products.tasks.backend.logic.services.hogland_sandbox.Hogland") as client_cls:
                get_hogland_client()
                # The projected SA token rotates on disk; the next call must pick
                # the new value up instead of reusing a cached client.
                token_path.write_text("tok-after\n")
                get_hogland_client()

        assert [call.kwargs["token"] for call in client_cls.call_args_list] == ["tok-before", "tok-after"]

    @pytest.mark.parametrize(
        "file_state,static_token,expected",
        [
            ("readable", "static-tok", "file-tok"),
            ("unset", "static-tok", "static-tok"),
            ("missing", "static-tok", "static-tok"),
            ("unset", None, None),
        ],
        ids=[
            "file_wins_over_static",
            "static_when_file_env_unset",
            "static_when_file_missing",
            "none_when_nothing_configured",
        ],
    )
    def test_api_token_precedence(self, file_state: str, static_token: str | None, expected: str | None, tmp_path):
        if file_state == "readable":
            token_path = tmp_path / "token"
            token_path.write_text("file-tok\n")
            file_setting: str | None = str(token_path)
        elif file_state == "missing":
            file_setting = str(tmp_path / "does-not-exist")
        else:
            file_setting = None

        with override_settings(HOGLAND_API_TOKEN_FILE=file_setting, HOGLAND_API_TOKEN=static_token):
            assert get_hogland_api_token() == expected
