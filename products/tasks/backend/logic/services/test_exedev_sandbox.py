import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import (
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SnapshotCreationError,
)
from products.tasks.backend.logic.services.exedev_sandbox import (
    AGENT_SERVER_PORT,
    ExeDevSandbox,
    _exec_cli,
    _extract_vm_token,
    _find_vm,
)
from products.tasks.backend.logic.services.sandbox import (
    ExecutionResult,
    SandboxConfig,
    SandboxStatus,
    get_sandbox_class,
    get_sandbox_class_for_backend,
)


def _config(**overrides) -> SandboxConfig:
    base: dict = {"name": "posthog-task-abc", "environment_variables": None}
    base.update(overrides)
    return SandboxConfig(**base)


def _running_vm(name: str) -> str:
    return f'{{"vms":[{{"vm_name":"{name}","status":"running"}}]}}'


def _ok(stdout: str = "", exit_code: int = 0) -> ExecutionResult:
    return ExecutionResult(stdout=stdout, stderr="", exit_code=exit_code, error=None)


@pytest.fixture
def mock_exec():
    with patch("products.tasks.backend.logic.services.exedev_sandbox._exec_cli") as m:
        yield m


@pytest.fixture
def exedev_settings(settings):
    settings.SANDBOX_EXEDEV_API_TOKEN = "token"
    settings.SANDBOX_EXEDEV_IMAGE = "img"
    settings.SANDBOX_EXEDEV_REGION = None
    settings.SANDBOX_EXEDEV_EGRESS_ALLOWLIST = None
    return settings


class TestProviderSelection:
    def test_get_sandbox_class_exedev(self, settings):
        settings.SANDBOX_PROVIDER = "exedev"
        assert get_sandbox_class() is ExeDevSandbox

    def test_get_sandbox_class_exedev_upper(self, settings):
        settings.SANDBOX_PROVIDER = "EXEDEV"
        assert get_sandbox_class() is ExeDevSandbox

    def test_get_sandbox_class_for_backend_exedev(self):
        assert get_sandbox_class_for_backend("exedev") is ExeDevSandbox
        assert get_sandbox_class_for_backend("EXEDEV") is ExeDevSandbox


class TestFindVm:
    def test_parses_vms_envelope_and_running_status(self):
        assert _find_vm('{"vms":[{"vm_name":"bloggy","status":"running"}]}', "bloggy") == "running"

    def test_returns_none_for_missing_vm(self):
        assert _find_vm('{"vms":[]}', "missing") is None
        assert _find_vm("", "missing") is None

    def test_returns_status_for_stopped_vm(self):
        assert _find_vm('{"vms":[{"vm_name":"bloggy","status":"stopped"}]}', "bloggy") == "stopped"

    def test_tolerates_bare_object(self):
        assert _find_vm('{"vm_name":"bloggy","status":"running"}', "bloggy") == "running"


class TestCreate:
    def test_create_requires_image(self, exedev_settings, mock_exec):
        exedev_settings.SANDBOX_EXEDEV_IMAGE = None
        with pytest.raises(SandboxProvisionError):
            ExeDevSandbox.create(_config())
        mock_exec.assert_not_called()

    def test_create_requires_token(self, exedev_settings, mock_exec):
        exedev_settings.SANDBOX_EXEDEV_API_TOKEN = None
        with pytest.raises(SandboxProvisionError):
            ExeDevSandbox.create(_config())
        mock_exec.assert_not_called()

    def test_create_rejects_snapshots(self, exedev_settings, mock_exec):
        with pytest.raises(SandboxProvisionError):
            ExeDevSandbox.create(_config(snapshot_id="snap-1"))
        mock_exec.assert_not_called()

    def test_create_builds_new_command(self, exedev_settings, mock_exec):
        mock_exec.return_value = _ok('{"name":"posthog-task-abc-123456"}')

        sandbox = ExeDevSandbox.create(_config(cpu_cores=4, memory_gb=16, disk_size_gb=64))

        cmd = mock_exec.call_args.args[0]
        assert cmd.startswith("new ")
        assert "--image=img" in cmd
        assert "--cpu=4" in cmd
        assert "--memory=16GB" in cmd
        assert "--disk=64GB" in cmd
        assert sandbox.id.startswith("posthog-task-abc-")
        assert sandbox.sandbox_url == f"https://{sandbox.id}.exe.xyz:{AGENT_SERVER_PORT}"

    def test_create_includes_env_vars(self, exedev_settings, mock_exec):
        mock_exec.return_value = _ok()

        ExeDevSandbox.create(_config(environment_variables={"POSTHOG_PROJECT_ID": "1", "JWT_PUBLIC_KEY": "pk"}))

        cmd = mock_exec.call_args.args[0]
        assert "--env POSTHOG_PROJECT_ID=1" in cmd
        assert "--env JWT_PUBLIC_KEY=pk" in cmd


class TestGetById:
    def test_get_by_id_found(self, mock_exec):
        mock_exec.return_value = _ok(_running_vm("vm-1"))
        sb = ExeDevSandbox.get_by_id("vm-1")
        assert sb.id == "vm-1"

    def test_get_by_id_missing_empty_list(self, mock_exec):
        mock_exec.return_value = _ok('{"vms":[]}')
        with pytest.raises(SandboxNotFoundError):
            ExeDevSandbox.get_by_id("vm-missing")

    def test_get_by_id_missing_nonzero_exit(self, mock_exec):
        mock_exec.return_value = _ok("", exit_code=1)
        with pytest.raises(SandboxNotFoundError):
            ExeDevSandbox.get_by_id("vm-missing")


class TestGetConnectCredentials:
    def test_mints_vm_token_and_returns_it(self, mock_exec):
        # 1st call: is_running's ls. 2nd: generate-api-key.
        mock_exec.side_effect = [_ok(_running_vm("vm-1")), _ok('{"token":"exe1.abc"}')]
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        creds = sb.get_connect_credentials()
        assert creds.url == f"https://vm-1.exe.xyz:{AGENT_SERVER_PORT}"
        assert creds.token == "exe1.abc"
        gen_cmd = mock_exec.call_args_list[1].args[0]
        assert gen_cmd.startswith("ssh-key generate-api-key --vm=vm-1")

    def test_raises_when_token_mint_returns_nothing(self, mock_exec):
        # ls succeeds, mint returns no token, and the VM is left for the workflow
        # to clean up (never destroyed inside the credential helper).
        mock_exec.side_effect = [_ok(_running_vm("vm-1")), _ok("")]
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        with pytest.raises(SandboxProvisionError):
            sb.get_connect_credentials()
        # Only the ls + mint calls; no `rm` issued.
        assert all(not c.args[0].startswith("rm ") for c in mock_exec.call_args_list)


class TestExtractVmToken:
    def test_extracts_from_json(self):
        assert _extract_vm_token('{"token":"exe1.abc"}') == "exe1.abc"
        assert _extract_vm_token('{"api_key":"k"}') == "k"

    def test_bare_string(self):
        assert _extract_vm_token("exe1.abc") == "exe1.abc"

    def test_none_when_empty(self):
        assert _extract_vm_token("") is None
        assert _extract_vm_token("   ") is None


class TestExecCliErrorMapping:
    def test_404_maps_to_not_found(self):
        resp = MagicMock(status_code=404, text="no such vm")
        with patch("products.tasks.backend.logic.services.exedev_sandbox.requests.post", return_value=resp):
            with patch("products.tasks.backend.logic.services.exedev_sandbox._api_token", return_value="token"):
                with pytest.raises(SandboxNotFoundError):
                    _exec_cli("ls --json missing")

    def test_422_returns_nonzero_result(self):
        resp = MagicMock(status_code=422, text='{"error":"boom"}')
        with patch("products.tasks.backend.logic.services.exedev_sandbox.requests.post", return_value=resp):
            with patch("products.tasks.backend.logic.services.exedev_sandbox._api_token", return_value="token"):
                result = _exec_cli("bad-cmd")
                assert result.exit_code != 0


class TestStatus:
    def test_running_when_vm_running(self, mock_exec):
        mock_exec.return_value = _ok(_running_vm("vm-1"))
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        assert sb.get_status() == SandboxStatus.RUNNING
        assert sb.is_running()

    def test_shutdown_when_vm_stopped(self, mock_exec):
        mock_exec.return_value = _ok('{"vms":[{"vm_name":"vm-1","status":"stopped"}]}')
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        assert sb.get_status() == SandboxStatus.SHUTDOWN

    def test_shutdown_when_vm_absent_from_list(self, mock_exec):
        mock_exec.return_value = _ok('{"vms":[]}')
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        assert sb.get_status() == SandboxStatus.SHUTDOWN

    def test_shutdown_on_gateway_error(self, mock_exec):
        mock_exec.side_effect = SandboxExecutionError("boom", {}, cause=RuntimeError("x"))
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        assert sb.get_status() == SandboxStatus.SHUTDOWN


class TestExecute:
    def test_execute_wraps_in_ssh_bash(self, mock_exec):
        mock_exec.side_effect = [_ok(_running_vm("vm-1")), _ok("hello\n")]
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        result = sb.execute("echo hello")
        ssh_cmd = mock_exec.call_args_list[1].args[0]
        assert ssh_cmd.startswith("ssh vm-1 bash -c ")
        assert result.stdout == "hello\n"

    def test_execute_raises_when_not_running(self, mock_exec):
        mock_exec.return_value = _ok('{"vms":[]}')
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        with pytest.raises(SandboxExecutionError):
            sb.execute("echo hi")


class TestDestroy:
    def test_destroy_calls_rm(self, mock_exec):
        mock_exec.return_value = _ok()
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        sb.destroy()
        assert mock_exec.call_args.args[0] == "rm --json vm-1"


class TestSnapshots:
    def test_snapshots_unsupported(self, mock_exec):
        sb = ExeDevSandbox(vm_name="vm-1", config=_config())
        with pytest.raises(SnapshotCreationError):
            sb.create_snapshot()
        with pytest.raises(SnapshotCreationError):
            sb.create_directory_snapshot("/x")
        with pytest.raises(SnapshotCreationError):
            ExeDevSandbox.delete_snapshot("ext-1")
