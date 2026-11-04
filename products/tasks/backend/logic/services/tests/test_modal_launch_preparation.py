import os
import re
import shlex
import signal
import itertools
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import SandboxExecutionError
from products.tasks.backend.logic.services.agent_server_launcher import (
    AGENT_SERVER_PREFLIGHT_REUSE_MARKER,
    AgentServerPreflight,
    build_agent_server_preflight_lines,
)
from products.tasks.backend.logic.services.agentsh import (
    BASH_ENV_SCRIPT,
    ENV_WRAPPER_SCRIPT,
    GH_GUARD_INSTALL_PATH,
    SESSION_ID_FILE,
    generate_bash_env_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
    read_gh_guard_script,
)
from products.tasks.backend.logic.services.launch_preparation_metrics import (
    launch_preparation_metric_context,
    record_launch_preparation_ms,
)
from products.tasks.backend.logic.services.modal_launch_preparation import (
    build_modal_agent_server_launch_script,
    build_modal_launch_preparation_script,
)
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import (
    ExecutionResult,
    SandboxConfig,
    build_bundled_skills_clear_command,
)
from products.tasks.backend.logic.services.task_filesystem import TASK_FILESYSTEM_SCRIPT


@pytest.fixture
def shell_environment(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "date": "echo 1000",
        "sleep": "true",
        "pkill": "exit 1",
        "pgrep": '[ "${PREPARATION_FAULT:-}" = daemon_stop ]',
        "curl": 'if [ "${PREPARATION_FAULT:-}" = health ]; then echo 000; exit 7; fi; echo 200',
        "agentsh": """
if [ "$1" = server ]; then exit 0; fi
case "${PREPARATION_FAULT:-}" in
    session) echo '{"id":"partial-session"}'; exit 23 ;;
    empty_session) echo '{"id":""}' ;;
    null_session) echo '{"id":null}' ;;
    *) echo '{"id":"ready-session"}' ;;
esac
""",
    }
    for name, command in commands.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/bash\n{command}\n")
        path.chmod(0o755)
    untrusted_bin = tmp_path / "untrusted"
    untrusted_bin.mkdir()
    for name in ("agentsh", "mkdir", "rm"):
        path = untrusted_bin / name
        path.write_text(f"#!/bin/bash\ntouch {shlex.quote(str(tmp_path / 'untrusted-executed'))}\nexit 99\n")
        path.chmod(0o755)
    return {"PATH": f"{untrusted_bin}:{os.environ['PATH']}"}


def run_preparation(
    root: Path, allowed_domains: list[str] | None, environment: dict[str, str], script: str | None = None
) -> subprocess.CompletedProcess[str]:
    script = script if script is not None else build_modal_launch_preparation_script(allowed_domains)
    script = re.sub(r"/(?:tmp|etc|opt|var)/", lambda match: f"{root}{match.group()}", script)
    script = script.replace(
        "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        f"export PATH={shlex.quote(str(root / 'bin'))}:/usr/bin:/bin",
    )
    script = script.replace("/usr/bin/agentsh", str(root / "bin/agentsh"))
    if environment.get("PREPARATION_REAL_DAEMON") != "1":
        script = 'kill() { [ "${PREPARATION_FAULT:-}" != daemon_start ]; }\n' + script
    script_path = root / "preparation.sh"
    script_path.write_text(script)
    return subprocess.run(
        ["bash", str(script_path)], cwd=root, env=environment, capture_output=True, text=True, timeout=10
    )


@pytest.mark.parametrize("allowed_domains", [None, [], ["example.com", "$(touch injected);'example.com"]])
def test_preparation_installs_complete_files_and_can_be_reapplied(
    tmp_path: Path, shell_environment: dict[str, str], allowed_domains: list[str] | None
) -> None:
    expected_files = {
        BASH_ENV_SCRIPT: (generate_bash_env_script().encode(), 0o644),
        GH_GUARD_INSTALL_PATH: (read_gh_guard_script(), 0o755),
    }
    if allowed_domains is not None:
        expected_files.update(
            {
                "/etc/agentsh/config.yaml": (generate_config_yaml(enable_ptrace=True, full_trace=True).encode(), 0o644),
                "/etc/agentsh/policies/default.yaml": (generate_policy_yaml(allowed_domains).encode(), 0o644),
                ENV_WRAPPER_SCRIPT: (generate_env_wrapper().encode(), 0o755),
                SESSION_ID_FILE: (b"ready-session", 0o600),
            }
        )
    for _ in range(2):
        clear = re.sub(
            r"/(?:root|scripts)/", lambda match: f"{tmp_path}{match.group()}", build_bundled_skills_clear_command()
        )
        result = subprocess.run(
            ["bash", "-c", clear],
            env={**shell_environment, "POSTHOG_CODE_DISABLE_BUNDLED_SKILLS": "1"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "untrusted-executed").exists()
        result = run_preparation(tmp_path, allowed_domains, shell_environment)
        assert result.returncode == 0, result.stderr
        for path, (payload, mode) in expected_files.items():
            installed = tmp_path / path.lstrip("/")
            assert installed.read_bytes() == payload
            assert installed.stat().st_mode & 0o777 == mode
        assert not list(tmp_path.rglob("*.tmp.*"))
        assert not (tmp_path / "preparation.sh").exists()
        assert not (tmp_path / "injected").exists()
        assert not (tmp_path / "untrusted-executed").exists()
    if allowed_domains is None:
        assert not (tmp_path / "etc/agentsh").exists()
        assert not (tmp_path / SESSION_ID_FILE.lstrip("/")).exists()


def run_launch_script(
    root: Path, environment: dict[str, str], *, agent_server_healthy: bool
) -> subprocess.CompletedProcess[str]:
    health_body = '{"status":"ok","hasSession":true}' if agent_server_healthy else '{"status":"ok","hasSession":false}'
    (root / "bin/curl").write_text(
        f'#!/bin/bash\ncase "$*" in *localhost:8080/health*) echo {shlex.quote(health_body)} ;; *) echo 200 ;; esac\n'
    )
    script = build_modal_agent_server_launch_script(
        ["example.com"],
        bundled_skills_clear_command="true",
        preflight_lines=build_agent_server_preflight_lines(probe_health=True, executable_paths=()),
    ).replace(f"/usr/bin/python3 -I {TASK_FILESYSTEM_SCRIPT} enter -- ", "")
    return run_preparation(root, ["example.com"], environment, script)


@pytest.mark.parametrize("agent_server_healthy", [True, False])
def test_launch_script_reports_reuse_only_for_a_healthy_agent_server(
    tmp_path: Path, shell_environment: dict[str, str], agent_server_healthy: bool
) -> None:
    result = run_launch_script(tmp_path, shell_environment, agent_server_healthy=agent_server_healthy)

    assert (AGENT_SERVER_PREFLIGHT_REUSE_MARKER in result.stdout.splitlines()) is agent_server_healthy


@pytest.mark.parametrize("agent_server_healthy", [True, False])
def test_launch_script_creates_an_agentsh_session_only_when_not_reusing(
    tmp_path: Path, shell_environment: dict[str, str], agent_server_healthy: bool
) -> None:
    run_launch_script(tmp_path, shell_environment, agent_server_healthy=agent_server_healthy)

    assert (tmp_path / SESSION_ID_FILE.lstrip("/")).exists() is not agent_server_healthy


@pytest.mark.parametrize(
    "fault", ["install", "rename", "daemon_stop", "daemon_start", "health", "session", "empty_session", "null_session"]
)
def test_preparation_stops_on_failure_and_cleans_staged_files(
    tmp_path: Path, shell_environment: dict[str, str], fault: str
) -> None:
    bash_env = tmp_path / BASH_ENV_SCRIPT.lstrip("/")
    bash_env.parent.mkdir(parents=True)
    bash_env.write_bytes(b"previous-complete-file")
    if fault == "install":
        chmod = tmp_path / "bin/chmod"
        chmod.write_text("#!/bin/bash\nexit 19\n")
        chmod.chmod(0o755)
    elif fault == "rename":
        destination = tmp_path / GH_GUARD_INSTALL_PATH.lstrip("/")
        destination.mkdir(parents=True)

    result = run_preparation(tmp_path, [], {**shell_environment, "PREPARATION_FAULT": fault})

    assert result.returncode != 0
    stage = "install" if fault in ("install", "rename") else "daemon_session"
    assert f"__posthog_launch_preparation_failed={stage}" in result.stderr
    assert not list(tmp_path.rglob("*.tmp.*"))
    assert not (tmp_path / "preparation.sh").exists()
    assert not (tmp_path / SESSION_ID_FILE.lstrip("/")).exists()
    if fault == "install":
        assert bash_env.read_bytes() == b"previous-complete-file"


@pytest.mark.parametrize("fault", [None, "health", "session", "unresponsive_daemon"])
def test_preparation_preserves_daemon_only_on_success(
    tmp_path: Path, shell_environment: dict[str, str], fault: str | None
) -> None:
    os.mkfifo(tmp_path / "daemon_ready")
    os.mkfifo(tmp_path / "daemon_block")
    (tmp_path / "bin/agentsh").write_text(
        "#!/bin/bash\n"
        'if [ "$1" = server ]; then\n'
        + ("trap '' TERM\n" if fault == "unresponsive_daemon" else "")
        + "echo $$ > daemon.pid\n"
        "echo ready > daemon_ready\n"
        "exec cat daemon_block\n"
        "fi\n"
        'echo \'{"id":"partial-session"}\'\n' + ("exit 0\n" if fault is None else "exit 23\n")
    )
    (tmp_path / "bin/curl").write_text(
        "#!/bin/bash\n"
        "if [ ! -f probe_started ]; then read -r < daemon_ready; touch probe_started; fi\n"
        + ("echo 000\n" if fault == "health" else "echo 200\n")
    )
    try:
        result = run_preparation(tmp_path, [], {**shell_environment, "PREPARATION_REAL_DAEMON": "1"})

        daemon_pid = int((tmp_path / "daemon.pid").read_text())
        if fault is None:
            assert result.returncode == 0
            os.kill(daemon_pid, 0)
        else:
            assert result.returncode == (1 if fault == "health" else 23)
            assert "__posthog_launch_preparation_failed=daemon_session" in result.stderr
            with pytest.raises(ProcessLookupError):
                os.kill(daemon_pid, 0)
        assert not (tmp_path / "preparation.sh").exists()
    finally:
        if (tmp_path / "daemon.pid").exists():
            try:
                os.kill(int((tmp_path / "daemon.pid").read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize(
    ("failure", "log_available"),
    [("upload", True), ("execute", True), ("install", True), ("daemon_session", True), ("daemon_session", False)],
)
def test_failed_preparation_never_launches_agent_server(failure: str, log_available: bool) -> None:
    handle = MagicMock(object_id="sb-test")
    handle.poll.return_value = None
    with patch.object(ModalSandbox, "_get_app_for_config", return_value=MagicMock()):
        sandbox = ModalSandbox(handle, SandboxConfig(name="test"))

    def execute(command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        if command.startswith("bash /tmp/posthog-launch-preparation-"):
            if failure == "execute":
                raise SandboxExecutionError("execution failed", {}, cause=RuntimeError("execution failed"))
            return ExecutionResult(stdout="", stderr=f"__posthog_launch_preparation_failed={failure}\n", exit_code=1)
        if command.startswith("tail -c 2000 /var/log/agentsh/agentsh.log"):
            if not log_available:
                raise RuntimeError("log unavailable")
            return ExecutionResult(stdout="x" * 2100 + "daemon startup failed", stderr="", exit_code=0)
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    with (
        patch.object(sandbox, "execute", side_effect=execute) as remote_execute,
        patch.object(
            sandbox,
            "_agent_server_preflight",
            return_value=AgentServerPreflight(reused=False, capabilities=frozenset()),
        ),
        patch.object(
            sandbox,
            "write_file",
            return_value=ExecutionResult(stdout="", stderr="", exit_code=1 if failure == "upload" else 0),
        ) as write_file,
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        patch("products.tasks.backend.logic.services.modal_sandbox.logger") as logger,
        launch_preparation_metric_context(
            boot_path="overlap", runtime="gvisor", origin_product=None, used_snapshot=True
        ),
        patch("products.tasks.backend.logic.services.launch_preparation_metrics.metric_meter") as metric_meter,
    ):
        with pytest.raises(SandboxExecutionError) as raised:
            sandbox.start_agent_server(repository=None, task_id="task-test", run_id="run-test", allowed_domains=[])

    if failure not in ("upload", "execute"):
        context = raised.value.context
        assert context["preparation_stage"] == failure
        assert context["exit_code"] == 1
        assert context["stderr"] == f"__posthog_launch_preparation_failed={failure}\n"
        expected_log = (
            ("x" * 2100 + "daemon startup failed")[-2000:] if log_available and failure == "daemon_session" else ""
        )
        assert context["agentsh_log"] == expected_log
        assert capture_exception.call_args.args[1]["agentsh_log"] == expected_log
        if failure == "daemon_session":
            assert logger.error.call_args.args[-1] == expected_log
    metric_meter.return_value.with_additional_attributes.assert_called_once_with(
        {
            "boot_path": "overlap",
            "runtime": "gvisor",
            "origin_product": "unknown",
            "used_snapshot": "true",
            "status": "FAILED",
        }
    )
    metric_meter.return_value.with_additional_attributes.return_value.create_histogram_timedelta.return_value.record.assert_called_once()
    assert write_file.call_count == 1
    commands = [call.args[0] for call in remote_execute.call_args_list]
    assert not any("./node_modules/.bin/agent-server" in command for command in commands)
    preparation_commands = [
        command for command in commands if command.startswith("bash /tmp/posthog-launch-preparation-")
    ]
    assert len(preparation_commands) == (0 if failure == "upload" else 1)
    if preparation_commands:
        assert shlex.split(preparation_commands[0])[1] == write_file.call_args.args[0]


@pytest.mark.parametrize("export_fails", [False, True])
def test_preparation_metric_measures_only_upload_and_execution(export_fails: bool) -> None:
    handle = MagicMock(object_id="sb-test")
    with patch.object(ModalSandbox, "_get_app_for_config", return_value=MagicMock()):
        sandbox = ModalSandbox(handle, SandboxConfig(name="test"))
    with (
        launch_preparation_metric_context(
            boot_path="classic", runtime="vm", origin_product="user_created", used_snapshot=False
        ),
        patch.object(sandbox, "write_file", return_value=ExecutionResult(stdout="", stderr="", exit_code=0)),
        patch.object(sandbox, "execute", return_value=ExecutionResult(stdout="", stderr="", exit_code=0)),
        patch("products.tasks.backend.logic.services.modal_sandbox.time") as clock,
        patch("products.tasks.backend.logic.services.launch_preparation_metrics.metric_meter") as metric_meter,
        patch.object(sandbox, "is_running", return_value=True),
        patch("products.tasks.backend.temporal.metrics.record_startup_step_event") as startup_event,
        patch.object(
            sandbox, "_agent_server_preflight", return_value=AgentServerPreflight(reused=True, capabilities=frozenset())
        ),
    ):
        clock.monotonic.side_effect = itertools.chain([10.0, 10.0, 10.5, 11.25], itertools.repeat(20.0))
        if export_fails:
            metric_meter.side_effect = RuntimeError("export unavailable")

        sandbox._prepare_agent_server_launch(None)
        assert sandbox.start_agent_server(repository=None, task_id="task-test", run_id="run-test") == 0

    metric_meter.assert_called_once_with()
    startup_event.assert_called_once_with(
        "launch_preparation",
        1250,
        {
            "boot_path": "classic",
            "runtime": "vm",
            "origin_product": "user_created",
            "used_snapshot": "false",
            "status": "COMPLETED",
        },
    )
    if not export_fails:
        metric_meter.return_value.with_additional_attributes.assert_called_once_with(
            {
                "boot_path": "classic",
                "runtime": "vm",
                "origin_product": "user_created",
                "used_snapshot": "false",
                "status": "COMPLETED",
            }
        )
        metric_meter.return_value.with_additional_attributes.return_value.create_histogram_timedelta.assert_called_once_with(
            "tasks_modal_launch_preparation_latency",
            "Modal launch file installation and agentsh preparation, including upload",
            unit="ms",
        )
        metric_meter.return_value.with_additional_attributes.return_value.create_histogram_timedelta.return_value.record.assert_called_once_with(
            timedelta(milliseconds=1250)
        )
    with patch("products.tasks.backend.logic.services.launch_preparation_metrics.metric_meter") as unscoped_meter:
        record_launch_preparation_ms(50, "COMPLETED")
    unscoped_meter.assert_not_called()
