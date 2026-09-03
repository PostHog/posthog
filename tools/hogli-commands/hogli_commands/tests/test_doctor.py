import os
import json
import time
import fcntl
import shutil
import hashlib
import threading
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from click.testing import CliRunner
from hogli_commands.doctor import (
    _GIT_HOUSEKEEPING_PGREP_PATTERN,
    FLOX_LOG_MAX_AGE_DAYS,
    FLOX_LOG_MAX_TOTAL_BYTES,
    _binary_arches,
    _check_git_health,
    _collect_import_targets,
    _config_procs,
    _confirm_stack_teardown,
    _container_mounts,
    _copy_volume,
    _find_service_container,
    _find_volume_mount,
    _format_kv_block,
    _generated_config_path,
    _get_process_cwds,
    _git_common_dir,
    _git_health,
    _git_housekeeping_running,
    _git_main_worktree,
    _git_maintenance_registered,
    _is_excluded,
    _normalize_arch,
    _phrocs_info,
    _phrocs_runtime_pairs,
    _phrocs_socket_path,
    _posthog_shaped_projects,
    _probe_command_imports,
    _run_ok,
    _sanitize_compose_name,
    _scan_port_holders,
    _scan_unheld_via_lsof,
    _select_flox_logs_to_remove,
    _tail,
    doctor_git,
    doctor_migrate_volumes,
    doctor_ports,
)

_QUARTER_BUDGET = FLOX_LOG_MAX_TOTAL_BYTES // 4
_TWO_FIFTHS_BUDGET = int(FLOX_LOG_MAX_TOTAL_BYTES * 0.4)


@pytest.fixture(autouse=True)
def _neutralize_compose_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Several tests in this module hardcode "posthog"-prefixed volume/project
    # names, matching production code that reads COMPOSE_PROJECT_NAME from the
    # environment — without this, a developer with a legitimately overridden
    # project name (e.g. COMPOSE_PROJECT_NAME=ai-gateway) gets a red suite here.
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "posthog")
    # doctor_migrate_volumes locks a file named after the project to serialize
    # across worktrees; point it at a per-test directory so parallel test runs
    # don't contend on the same real /tmp path.
    monkeypatch.setattr("hogli_commands.doctor._MIGRATION_LOCK_DIR", tmp_path)


@pytest.mark.parametrize(
    "specs, expected_doomed, expected_retained",
    [
        pytest.param(
            [("old.log", 1, FLOX_LOG_MAX_AGE_DAYS + 1), ("recent.log", FLOX_LOG_MAX_TOTAL_BYTES // 2, 0)],
            ["old.log"],
            float(FLOX_LOG_MAX_TOTAL_BYTES // 2),
            id="age-cutoff-removes-old-keeps-large-recent",
        ),
        pytest.param(
            [
                ("newest.log", _TWO_FIFTHS_BUDGET, 1),
                ("middle.log", _TWO_FIFTHS_BUDGET, 2),
                ("oldest.log", _TWO_FIFTHS_BUDGET, 3),
            ],
            ["oldest.log"],
            float(2 * _TWO_FIFTHS_BUDGET),
            id="budget-trims-oldest-survivor-first",
        ),
        pytest.param(
            [("a.log", _QUARTER_BUDGET, 1), ("b.log", _QUARTER_BUDGET, 2)],
            [],
            float(2 * _QUARTER_BUDGET),
            id="within-age-and-budget-keeps-all",
        ),
    ],
)
def test_select_flox_logs_to_remove(
    specs: list[tuple[str, int, int]],
    expected_doomed: list[str],
    expected_retained: float,
) -> None:
    now = time.time()
    logs = [(Path(name), size, now - age_days * 86400) for name, size, age_days in specs]
    doomed, retained = _select_flox_logs_to_remove(logs)
    assert sorted(item.path.name for item in doomed) == sorted(expected_doomed)
    assert retained == expected_retained


@pytest.mark.parametrize(
    "args",
    [
        pytest.param("vim file.py", id="vim"),
        pytest.param("/usr/bin/git status", id="git-absolute"),
        pytest.param("code .", id="vscode-cli"),
        pytest.param("ssh user@host", id="ssh"),
        pytest.param("/usr/bin/tmux new -s dev", id="tmux"),
        pytest.param("claude --help", id="claude"),
        pytest.param("hogli doctor", id="hogli"),
        pytest.param("docker compose up -d", id="docker-compose"),
        pytest.param("dockerd", id="dockerd"),
        pytest.param("direnv exec /some/path", id="direnv"),
        pytest.param("grep -r pattern .", id="grep"),
        pytest.param("/usr/bin/lsof -p 123", id="lsof"),
        pytest.param("watchman watch-project /some/path", id="watchman"),
    ],
)
def test_is_excluded_matches_excluded_executables(args: str) -> None:
    assert _is_excluded(args) is True


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(
            "/nix/store/abc123/bin/node --require /Users/x/code/github/posthog/node_modules/.pnpm/tsx@4.20.5/node_modules/tsx/dist/preflight.cjs src/index.ts",
            id="node-with-code-in-path",
        ),
        pytest.param(
            "python /Users/x/code/github/posthog/manage.py runserver",
            id="python-with-code-in-path",
        ),
        pytest.param(
            "granian asgi 127.0.0.1:8000 posthog.asgi:application",
            id="granian",
        ),
        pytest.param(
            "celery -A posthog worker",
            id="celery",
        ),
        pytest.param(
            "/Users/x/code/github/posthog/rust/target/debug/capture",
            id="rust-capture",
        ),
    ],
)
def test_is_excluded_does_not_match_posthog_processes(args: str) -> None:
    assert _is_excluded(args) is False


def test_is_excluded_empty_string() -> None:
    assert _is_excluded("") is False


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        pytest.param(
            [("os", "macOS"), ("term_program", "iTerm")],
            ["os            macOS", "term_program  iTerm"],
            id="aligns-values",
        ),
        pytest.param([], [], id="empty"),
    ],
)
def test_format_kv_block(pairs: list[tuple[str, str]], expected: list[str]) -> None:
    assert _format_kv_block(pairs) == expected


class _FakeManifest:
    """Minimal stand-in for ``hogli.manifest.Manifest`` (structural match)."""

    def __init__(self, commands: dict[str, dict], boot_modules: list[str] | None = None) -> None:
        self._commands = commands
        self.config = {"boot_modules": boot_modules or []}

    def get_all_commands(self) -> list[str]:
        return list(self._commands)

    def get_command_config(self, command_name: str) -> dict | None:
        return self._commands.get(command_name)


def test_collect_import_targets_extracts_click_and_boot_modules() -> None:
    manifest = _FakeManifest(
        {
            "doctor": {"click": "hogli_commands.doctor:doctor"},
            "doctor:report": {"click": "hogli_commands.doctor:doctor_report"},
            "noclick": {"cmd": "echo hi"},
            "bad:format": {"click": "no_colon_here"},
        },
        boot_modules=["hogli_commands.prechecks"],
    )
    targets = _collect_import_targets(manifest)

    assert ("doctor", "hogli_commands.doctor", "doctor") in targets
    assert ("doctor:report", "hogli_commands.doctor", "doctor_report") in targets
    # Boot modules import the module with no attribute to resolve.
    assert ("hogli_commands.prechecks", "hogli_commands.prechecks", None) in targets
    # cmd-only and malformed click strings are skipped.
    assert not any(label == "noclick" for label, _, _ in targets)
    assert not any(label == "bad:format" for label, _, _ in targets)


@pytest.mark.parametrize(
    ("commands", "expected_failure"),
    [
        pytest.param(
            {"doctor": {"click": "hogli_commands.doctor:doctor"}},
            None,
            id="all-ok",
        ),
        pytest.param(
            {"ghost": {"click": "hogli_commands.does_not_exist:thing"}},
            ("ghost", "ModuleNotFoundError"),
            id="missing-module",
        ),
        pytest.param(
            {"typo": {"click": "hogli_commands.doctor:not_a_real_command"}},
            ("typo", "missing attribute 'not_a_real_command'"),
            id="missing-attribute",
        ),
    ],
)
def test_probe_command_imports(commands: dict[str, dict], expected_failure: tuple[str, str] | None) -> None:
    probed, failures = _probe_command_imports(_FakeManifest(commands))
    assert probed == 1
    if expected_failure is None:
        assert failures == []
        return
    assert len(failures) == 1
    label, error = failures[0]
    assert label == expected_failure[0]
    assert expected_failure[1] in error


def test_get_process_cwds_skips_lsof_for_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise AssertionError("lsof must not run for an empty pid list")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fail)
    assert _get_process_cwds([]) == {}


def test_get_process_cwds_parses_and_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=1, stdout="p100\nn/repo/a\np200\nn/repo/b\n", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    # Non-zero rc (a pid vanished) must not discard the records that did resolve.
    assert _get_process_cwds([100, 200]) == {100: "/repo/a", 200: "/repo/b"}
    # One batched, ANDed lsof call covering every pid — not one call per pid.
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:2] == ["lsof", "-a"]
    assert "100,200" in cmd


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("arm64", "arm64"),
        ("aarch64", "arm64"),
        ("x86_64", "x86_64"),
        ("x86-64", "x86_64"),
        ("amd64", "x86_64"),
        ("AMD64", "x86_64"),
        ("riscv64", "riscv64"),
    ],
)
def test_normalize_arch(value: str, expected: str) -> None:
    assert _normalize_arch(value) == expected


def test_binary_arches_parses_file_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hogli_commands.doctor._run_output",
        lambda *_: "Mach-O 64-bit executable arm64",
    )
    assert _binary_arches("/opt/homebrew/bin/phrocs") == {"arm64"}


def test_binary_arches_handles_universal_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hogli_commands.doctor._run_output",
        lambda *_: "Mach-O universal binary with 2 architectures: [x86_64] [arm64]",
    )
    assert _binary_arches("/usr/local/bin/phrocs") == {"x86_64", "arm64"}


def test_binary_arches_empty_when_file_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hogli_commands.doctor._run_output", lambda *_: None)
    assert _binary_arches("/opt/homebrew/bin/phrocs") == set()


def _patch_phrocs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    which: str | None,
    version: str | None,
    file_out: str | None,
    machine: str,
) -> None:
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: which)
    monkeypatch.setattr("hogli_commands.doctor.platform.machine", lambda: machine)

    def fake_run_output(cmd: list[str], *_a: object, **_k: object) -> str | None:
        return file_out if cmd[0] == "file" else version

    monkeypatch.setattr("hogli_commands.doctor._run_output", fake_run_output)


def test_phrocs_info_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_phrocs(monkeypatch, which=None, version=None, file_out=None, machine="arm64")
    _, value = _phrocs_info()
    assert value.startswith("MISSING")


def test_phrocs_info_healthy_matching_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_phrocs(
        monkeypatch,
        which="/opt/homebrew/bin/phrocs",
        version="phrocs 1.0.8 (abc, 2026-04-14)",
        file_out="Mach-O 64-bit executable arm64",
        machine="arm64",
    )
    _, value = _phrocs_info()
    assert "phrocs 1.0.8" in value
    assert "[arm64]" in value
    assert "MISMATCH" not in value


def test_phrocs_info_flags_arch_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_phrocs(
        monkeypatch,
        which="/usr/local/bin/phrocs",
        version="phrocs 1.0.8 (abc, 2026-04-14)",
        file_out="Mach-O 64-bit executable x86_64",
        machine="arm64",
    )
    _, value = _phrocs_info()
    assert "ARCH MISMATCH vs host arm64" in value


def test_phrocs_info_flags_broken_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_phrocs(
        monkeypatch,
        which="/opt/homebrew/bin/phrocs",
        version=None,
        file_out="Mach-O 64-bit executable arm64",
        machine="arm64",
    )
    _, value = _phrocs_info()
    assert "--version failed" in value


def test_generated_config_path_honors_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOGLI_MPROCS_PATH", "/custom/mprocs.yaml")
    assert _generated_config_path(tmp_path) == Path("/custom/mprocs.yaml")


def test_generated_config_path_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HOGLI_MPROCS_PATH", raising=False)
    assert _generated_config_path(tmp_path) == tmp_path / ".posthog" / ".generated" / "mprocs.yaml"


def test_phrocs_socket_path_matches_phrocs_formula(tmp_path: Path) -> None:
    real = os.path.realpath(tmp_path)
    expected = "/tmp/phrocs-" + hashlib.sha256(real.encode()).digest()[:4].hex() + ".sock"
    socket = _phrocs_socket_path(tmp_path)
    assert str(socket) == expected
    assert socket == _phrocs_socket_path(tmp_path)  # stable


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("procs:\n  a: {}\n  b: {}\n", "2 procs", id="counts-procs"),
        pytest.param("_posthog: {}\n", "no procs", id="no-procs-key"),
        pytest.param("procs: not-a-mapping\n", "no procs", id="procs-not-mapping"),
        pytest.param("procs:\n  - [unbalanced\n", "unparseable", id="malformed-yaml"),
    ],
)
def test_config_procs(tmp_path: Path, content: str, expected: str) -> None:
    config = tmp_path / "mprocs.yaml"
    config.write_text(content)
    assert _config_procs(config).startswith(expected)


def test_tail_returns_last_lines(tmp_path: Path) -> None:
    log = tmp_path / "phrocs.log"
    log.write_text("\n".join(f"line {i}" for i in range(20)))
    assert _tail(log, 3) == ["line 17", "line 18", "line 19"]


def test_tail_missing_file_is_empty(tmp_path: Path) -> None:
    assert _tail(tmp_path / "nope.log", 5) == []


def test_phrocs_runtime_pairs_reports_state(tmp_path: Path) -> None:
    config = tmp_path / ".posthog" / ".generated" / "mprocs.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("procs:\n  backend: {}\n  frontend: {}\n  capture: {}\n")

    pairs = dict(_phrocs_runtime_pairs(tmp_path))
    assert set(pairs) == {"generated_config", "phrocs_log", "ipc_socket", "stdout_tty", "terminal_size"}
    assert "3 procs" in pairs["generated_config"]
    assert "absent" in pairs["phrocs_log"]


def test_phrocs_runtime_pairs_flags_missing_config(tmp_path: Path) -> None:
    pairs = dict(_phrocs_runtime_pairs(tmp_path))
    assert "MISSING" in pairs["generated_config"]
    assert "hogli dev:generate" in pairs["generated_config"]


def test_sanitize_compose_name_strips_shell_metacharacters() -> None:
    # This value heads for a `docker compose -p <name> down` argv; if the
    # sanitizer regresses, a crafted compose label becomes shell injection.
    assert _sanitize_compose_name("posthog-evil$(touch /tmp/pwned);rm -rf /") == "posthog-eviltouchtmppwnedrm-rf"


def _fake_docker_ps(
    monkeypatch: pytest.MonkeyPatch,
    port_scan_stdout: str = "",
    clickhouse_stdout: str = "",
    extra: Callable[[list[str]], SimpleNamespace | None] | None = None,
) -> None:
    """Fake the two `docker ps` calls `doctor:ports` makes. `extra`, if given,
    handles any other command (e.g. the teardown `docker compose` call) —
    callers that need one don't have to reimplement the `docker ps` branches.
    """

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        if cmd[:2] == ["docker", "ps"] and "-a" not in cmd:
            return SimpleNamespace(returncode=0, stdout=port_scan_stdout, stderr="")
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout=clickhouse_stdout, stderr="")
        if extra is not None:
            result = extra(cmd)
            if result is not None:
                return result
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)


@pytest.mark.parametrize(
    ("ports_line", "expected_port", "expected_holder"),
    [
        pytest.param("evilbox|otherproj|127.0.0.1:8010->8000/tcp", 8010, "otherproj", id="plain-published-port"),
        pytest.param(
            "evilbox|otherproj|0.0.0.0:19000-19001->19000-19001/tcp", 19000, "otherproj", id="published-range-start"
        ),
        pytest.param(
            "evilbox|otherproj|0.0.0.0:19000-19001->19000-19001/tcp",
            9000,
            None,
            id="range-does-not-false-match-shorter-port",
        ),
    ],
)
def test_scan_port_holders_matches_published_port_forms(
    monkeypatch: pytest.MonkeyPatch, ports_line: str, expected_port: int, expected_holder: str | None
) -> None:
    # code-reviewer-testing's top concern on the bash version: a substring
    # match between port 9000 and 19000 would misattribute a collision.
    _fake_docker_ps(monkeypatch, port_scan_stdout=ports_line)
    holders = {h.port: h for h in _scan_port_holders()}
    if expected_holder is None:
        assert holders[expected_port].container is None
    else:
        assert holders[expected_port].container == "evilbox"
        assert holders[expected_port].project == expected_holder


def test_scan_port_holders_own_project_is_not_flagged_foreign(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker_ps(monkeypatch, port_scan_stdout="clickhouse|posthog|127.0.0.1:8123->8123/tcp")
    holders = {h.port: h for h in _scan_port_holders()}
    assert holders[8123].project == "posthog"


def test_scan_port_holders_sanitizes_malicious_project_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker_ps(monkeypatch, port_scan_stdout="evilbox|posthog-evil$(rm -rf /)|127.0.0.1:8010->8000/tcp")
    holders = {h.port: h for h in _scan_port_holders()}
    assert holders[8010].project == "posthog-evilrm-rf"


def test_posthog_shaped_projects_filters_by_clickhouse_label(monkeypatch: pytest.MonkeyPatch) -> None:
    # This is the exact partial-stack gap Greptile flagged (P1) against the
    # bash version: `docker ps -a` (all states) means a project whose
    # clickhouse container is stopped, but another service still holds a
    # port, is still offered for teardown — not just one whose CH is running.
    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        assert "label=com.docker.compose.service=clickhouse" in cmd
        return SimpleNamespace(returncode=0, stdout="ch1|stopped-proj\n", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    result = _posthog_shaped_projects({"stopped-proj", "unrelated-proj"})
    assert result == {"stopped-proj"}


def test_scan_unheld_via_lsof_disambiguates_port_and_range(monkeypatch: pytest.MonkeyPatch) -> None:
    lsof_output = "\n".join(
        [
            "COMMAND   PID   USER   FD   TYPE DEVICE SIZE/OFF NODE NAME",
            "orbstack  111   phil   10u  IPv4 0x1     0t0      TCP  *:9000",
            "orbstack  111   phil   11u  IPv4 0x2     0t0      TCP  *:19000",
        ]
    )

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        assert cmd[0] == "lsof"
        return SimpleNamespace(returncode=0, stdout=lsof_output, stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/lsof")

    holders = {h.port: h for h in _scan_unheld_via_lsof([(9000, "clickhouse-native"), (19000, "objectstorage")])}
    assert holders[9000].process_holder == "orbstack (pid 111)"
    assert holders[19000].process_holder == "orbstack (pid 111)"


def test_confirm_stack_teardown_times_out_to_no(monkeypatch: pytest.MonkeyPatch) -> None:
    # Runs on every `hogli start`; if the timeout path regresses, a piped or
    # abandoned terminal hangs every developer's startup indefinitely.
    monkeypatch.setattr("hogli_commands.doctor.select.select", lambda *_a, **_k: ([], [], []))
    assert _confirm_stack_teardown("some-stack", timeout=0.01) is False


def test_confirm_stack_teardown_accepts_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hogli_commands.doctor.select.select", lambda *a, **_k: (a[0], [], []))
    monkeypatch.setattr("hogli_commands.doctor.sys.stdin.readline", lambda: "y\n")
    assert _confirm_stack_teardown("some-stack", timeout=0.01) is True


def test_doctor_ports_silent_when_nothing_foreign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    _fake_docker_ps(monkeypatch, port_scan_stdout="clickhouse|posthog|127.0.0.1:8123->8123/tcp")
    result = CliRunner().invoke(doctor_ports, [])
    assert result.exit_code == 0
    assert result.output == ""


def test_doctor_ports_reports_foreign_stack_noninteractively(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves the command wires scan -> shape-filter -> report together; each
    # piece has its own unit test above, but not that they're called in order.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    _fake_docker_ps(
        monkeypatch,
        port_scan_stdout="evilbox|foreign-proj|127.0.0.1:8010->8000/tcp",
        clickhouse_stdout="ch1|foreign-proj\n",
    )
    # CliRunner's stdin/stdout are never a TTY, so this exercises the
    # non-interactive (print-only, no subprocess teardown) branch.
    result = CliRunner().invoke(doctor_ports, [])
    assert result.exit_code == 0
    assert "foreign-proj" in result.output
    assert "docker compose -p foreign-proj -f docker-compose.dev.yml down --remove-orphans" in result.output


@pytest.mark.parametrize(
    ("confirmed", "expected_teardown_calls"),
    [
        pytest.param(True, 1, id="confirmed-tears-down"),
        pytest.param(False, 0, id="declined-leaves-stack-alone"),
    ],
)
def test_doctor_ports_teardown_respects_confirmation(
    monkeypatch: pytest.MonkeyPatch, confirmed: bool, expected_teardown_calls: int
) -> None:
    # CliRunner always simulates a non-tty stdin/stdout with no override hook,
    # so the interactive branch is exercised by calling the command function
    # directly instead of through Click's dispatcher. A declined prompt must
    # leave the foreign stack running, not tear it down anyway.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("hogli_commands.doctor.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hogli_commands.doctor.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("hogli_commands.doctor._confirm_stack_teardown", lambda *_a, **_k: confirmed)

    teardown_calls: list[list[str]] = []

    def record_teardown(cmd: list[str]) -> SimpleNamespace | None:
        if cmd[:2] == ["docker", "compose"]:
            teardown_calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return None

    _fake_docker_ps(
        monkeypatch,
        port_scan_stdout="evilbox|foreign-proj|127.0.0.1:8010->8000/tcp",
        clickhouse_stdout="ch1|foreign-proj\n",
        extra=record_teardown,
    )

    assert doctor_ports.callback is not None
    doctor_ports.callback(yes=False)
    assert len(teardown_calls) == expected_teardown_calls
    if confirmed:
        # Verifies the exact teardown argv — a reordered or dropped arg here
        # would tear down the wrong compose file.
        assert teardown_calls == [
            ["docker", "compose", "-p", "foreign-proj", "-f", "docker-compose.dev.yml", "down", "--remove-orphans"]
        ]


# ---------------------------------------------------------------------------
# doctor:migrate-volumes
# ---------------------------------------------------------------------------


def _mounts_json(entries: Sequence[tuple[str, str, str]]) -> str:
    """entries: (destination, volume name, mount type)."""
    return json.dumps([{"Destination": dest, "Name": name, "Type": type_} for dest, name, type_ in entries])


# Realistic mounts for a container built from docker-compose.dev.yml: the
# clickhouse service has one named-volume mount plus several bind mounts for
# config files; zookeeper has three named-volume mounts.
_CLICKHOUSE_MOUNTS = _mounts_json(
    [
        ("/idl", "", "bind"),
        ("/etc/clickhouse-server/config.xml", "", "bind"),
        ("/var/lib/clickhouse", "old-ch-vol", "volume"),
    ]
)
_ZOOKEEPER_MOUNTS = _mounts_json(
    [
        ("/datalog", "old-zk-datalog-vol", "volume"),
        ("/data", "old-zk-data-vol", "volume"),
        ("/logs", "old-zk-logs-vol", "volume"),
    ]
)


@pytest.mark.parametrize(
    ("ids_by_service", "service", "project", "expected"),
    [
        pytest.param({"clickhouse": []}, "clickhouse", "posthog", None, id="no-containers"),
        pytest.param({"clickhouse": ["ch1"]}, "clickhouse", "posthog", "ch1", id="single-match"),
        pytest.param({"clickhouse": ["ch1", "ch2"]}, "clickhouse", "posthog", None, id="ambiguous-two-matches"),
    ],
)
def test_find_service_container(
    monkeypatch: pytest.MonkeyPatch,
    ids_by_service: dict[str, list[str]],
    service: str,
    project: str,
    expected: str | None,
) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        svc = cmd[4].split("=")[-1]
        ids = ids_by_service.get(svc, [])
        return SimpleNamespace(returncode=0, stdout="\n".join(f"{cid}|{project}" for cid in ids), stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    assert _find_service_container(project, service) == expected


def test_find_service_container_ignores_matches_from_other_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    # A container from a sibling worktree's compose project must not be mistaken
    # for this project's — that would copy the wrong developer's data.
    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="ch1|other-project\n", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    assert _find_service_container("posthog", "clickhouse") is None


@pytest.mark.parametrize(
    ("mounts", "destination", "expected"),
    [
        pytest.param(
            [
                {"Destination": "/idl", "Name": "", "Type": "bind"},
                {"Destination": "/var/lib/clickhouse", "Name": "old-ch-vol", "Type": "volume"},
            ],
            "/var/lib/clickhouse",
            "old-ch-vol",
            id="single-volume-match-among-bind-mounts",
        ),
        pytest.param(
            [{"Destination": "/idl", "Name": "", "Type": "bind"}],
            "/var/lib/clickhouse",
            None,
            id="destination-not-mounted",
        ),
        pytest.param(
            [
                {"Destination": "/logs", "Name": "vol-a", "Type": "volume"},
                {"Destination": "/logs", "Name": "vol-b", "Type": "volume"},
            ],
            "/logs",
            None,
            id="duplicate-destination-is-ambiguous",
        ),
        pytest.param(
            [{"Destination": "/var/lib/clickhouse", "Name": "/host/path", "Type": "bind"}],
            "/var/lib/clickhouse",
            None,
            id="bind-mount-is-not-a-volume",
        ),
    ],
)
def test_find_volume_mount(mounts: list[dict[str, object]], destination: str, expected: str | None) -> None:
    assert _find_volume_mount(mounts, destination) == expected


@pytest.mark.parametrize(
    ("run_output", "expected"),
    [
        pytest.param(_CLICKHOUSE_MOUNTS, json.loads(_CLICKHOUSE_MOUNTS), id="valid-mounts-json"),
        pytest.param("not json", None, id="unparseable-inspect-output"),
        pytest.param(None, None, id="inspect-failed"),
    ],
)
def test_container_mounts(
    monkeypatch: pytest.MonkeyPatch, run_output: str | None, expected: list[dict[str, object]] | None
) -> None:
    monkeypatch.setattr("hogli_commands.doctor._run_output", lambda *_a, **_k: run_output)
    assert _container_mounts("some-container") == expected


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [
        pytest.param(1, False, id="copy-or-verify-fails"),
        pytest.param(0, True, id="copy-and-verify-succeed"),
    ],
)
def test_copy_volume(monkeypatch: pytest.MonkeyPatch, returncode: int, expected: bool) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    monkeypatch.setattr("hogli_commands.doctor.os.getpid", lambda: 4242)
    assert _copy_volume("old-vol", "new-vol") == expected
    # The destination-empty check now lives inside the copy container's own
    # command (there's no second container call left to catch it separately)
    # — lock in that the check itself doesn't silently disappear.
    assert calls[0] == [
        "docker",
        "run",
        "--rm",
        "--name",
        "hogli-migrate-volumes-4242",
        "-v",
        "old-vol:/from:ro",
        "-v",
        "new-vol:/to",
        "alpine",
        "sh",
        "-c",
        'rm -rf /to/* && cp -a /from/. /to/ && [ -n "$(ls -A /to)" ]',
    ]
    # A failed copy cleans up the named container so a later `docker volume rm -f`
    # on the destination doesn't fail with "volume is in use".
    if not expected:
        assert calls[1] == ["docker", "rm", "-f", "hogli-migrate-volumes-4242"]


def _fake_migrate_dispatcher(
    *,
    project: str = "posthog",
    named_volume_exists: bool = False,
    clickhouse_ids: Sequence[str] = ("ch1",),
    zookeeper_ids: Sequence[str] = ("zk1",),
    mounts_by_container: dict[str, str] | None = None,
    copy_returncode_by_dest: dict[str, int] | None = None,
    stop_returncode: int = 0,
) -> tuple[Callable[..., SimpleNamespace], list[list[str]]]:
    """Fake `subprocess.run` covering every docker call doctor_migrate_volumes
    can make, keyed off the same argv shapes the implementation builds.
    Records every call so tests can assert exactly what ran (or didn't).
    """
    calls: list[list[str]] = []
    mounts_by_container = mounts_by_container or {"ch1": _CLICKHOUSE_MOUNTS, "zk1": _ZOOKEEPER_MOUNTS}
    copy_returncode_by_dest = copy_returncode_by_dest or {}

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(cmd)

        if cmd[:3] == ["docker", "volume", "inspect"]:
            return SimpleNamespace(
                returncode=0 if named_volume_exists else 1, stdout="[]" if named_volume_exists else ""
            )

        if cmd[:3] == ["docker", "ps", "-a"]:
            service = cmd[4].split("=")[-1]
            ids = clickhouse_ids if service == "clickhouse" else zookeeper_ids
            return SimpleNamespace(returncode=0, stdout="\n".join(f"{cid}|{project}" for cid in ids), stderr="")

        if cmd[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=mounts_by_container.get(cmd[2], "[]"), stderr="")

        if cmd[:2] == ["docker", "stop"]:
            return SimpleNamespace(returncode=stop_returncode, stdout="", stderr="")

        if cmd[:3] == ["docker", "volume", "create"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        if cmd[:2] == ["docker", "run"] and "sh" in cmd:
            # argv: docker run --rm --name <container> -v <src>:/from:ro -v <dest>:/to alpine sh -c ...
            dest = cmd[8].split(":")[0]
            return SimpleNamespace(returncode=copy_returncode_by_dest.get(dest, 0), stdout="", stderr="")

        if cmd[:3] == ["docker", "volume", "rm"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        if cmd[:2] == ["docker", "start"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return SimpleNamespace(returncode=1, stdout="", stderr="")

    return fake_run, calls


def test_doctor_migrate_volumes_noop_when_already_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    # This runs on every `hogli start`; once the named volume exists, it must
    # be a single fast check, not a full docker ps/inspect sweep every time.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(named_volume_exists=True)
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert result.output == ""
    # All four destination volumes are checked in one call — the idempotency
    # check must not rely on clickhouse-data alone, or a migration interrupted
    # after the first volume would be mistaken for fully complete forever.
    assert calls == [
        [
            "docker",
            "volume",
            "inspect",
            "posthog_clickhouse-data",
            "posthog_zookeeper-data",
            "posthog_zookeeper-datalog",
            "posthog_zookeeper-logs",
        ]
    ]


def test_doctor_migrate_volumes_noop_on_fresh_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # No named volumes yet *and* no prior clickhouse container or postgres
    # volume means there was never any old data — must stay silent, not warn
    # a brand new checkout.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(named_volume_exists=False, clickhouse_ids=(), zookeeper_ids=())
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert result.output == ""
    # dest-volumes inspect + clickhouse existence check + prior-install (postgres) check
    assert len(calls) == 3


def test_doctor_migrate_volumes_warns_when_stack_was_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    # `docker compose down` removes containers but keeps volumes, so a developer
    # who stopped the stack (rather than never having one) has no clickhouse
    # container to salvage from, but still has real prior data. Silence here
    # would mean an empty ClickHouse with no explanation.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(named_volume_exists=False, clickhouse_ids=(), zookeeper_ids=())

    def with_prior_install(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[:3] == ["docker", "volume", "inspect"] and cmd[3:] == ["posthog_postgres-15-data"]:
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        return fake_run(cmd, **kwargs)

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", with_prior_install)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Switching ClickHouse/ZooKeeper to named docker volumes" in result.output
    assert "developing-locally.md" in result.output
    assert not any(c[:2] == ["docker", "stop"] for c in calls)


def test_doctor_migrate_volumes_happy_path_migrates_both_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("hogli_commands.doctor.os.getpid", lambda: 4242)
    fake_run, calls = _fake_migrate_dispatcher()
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Migrated ClickHouse/ZooKeeper data" in result.output

    # Both containers are stopped together before anything is copied — a live
    # `cp -a` against an actively-written data dir can read a torn snapshot. The
    # explicit grace period gives ClickHouse time to flush a multi-GB dataset;
    # docker's 10s default SIGKILLs it into crash recovery.
    assert ["docker", "stop", "-t", "60", "ch1", "zk1"] in calls

    # Each destination is pre-created with compose's own labels before the copy,
    # so compose doesn't warn "not created by Docker Compose" on every later `up`.
    assert [
        "docker",
        "volume",
        "create",
        "--label",
        "com.docker.compose.project=posthog",
        "--label",
        "com.docker.compose.volume=clickhouse-data",
        "posthog_clickhouse-data",
    ] in calls

    # Exact copy argv for both services — a reordered or missing flag here
    # would silently copy from (or into) the wrong volume.
    assert [
        "docker",
        "run",
        "--rm",
        "--name",
        "hogli-migrate-volumes-4242",
        "-v",
        "old-ch-vol:/from:ro",
        "-v",
        "posthog_clickhouse-data:/to",
        "alpine",
        "sh",
        "-c",
        'rm -rf /to/* && cp -a /from/. /to/ && [ -n "$(ls -A /to)" ]',
    ] in calls
    assert [
        "docker",
        "run",
        "--rm",
        "--name",
        "hogli-migrate-volumes-4242",
        "-v",
        "old-zk-data-vol:/from:ro",
        "-v",
        "posthog_zookeeper-data:/to",
        "alpine",
        "sh",
        "-c",
        'rm -rf /to/* && cp -a /from/. /to/ && [ -n "$(ls -A /to)" ]',
    ] in calls
    assert [
        "docker",
        "run",
        "--rm",
        "--name",
        "hogli-migrate-volumes-4242",
        "-v",
        "old-zk-datalog-vol:/from:ro",
        "-v",
        "posthog_zookeeper-datalog:/to",
        "alpine",
        "sh",
        "-c",
        'rm -rf /to/* && cp -a /from/. /to/ && [ -n "$(ls -A /to)" ]',
    ] in calls


@pytest.mark.parametrize(
    ("clickhouse_ids", "zookeeper_ids", "mounts_by_container"),
    [
        pytest.param(("ch1",), (), None, id="zookeeper-container-already-removed"),
        pytest.param(("ch1", "ch2"), ("zk1",), None, id="ambiguous-clickhouse-containers"),
        pytest.param(
            ("ch1",),
            ("zk1",),
            {
                "ch1": _CLICKHOUSE_MOUNTS,
                # zookeeper's own container and two of its three volumes resolve
                # fine — only /logs is duplicated. The whole plan must still be
                # discarded, not just the ambiguous piece.
                "zk1": _mounts_json(
                    [
                        ("/datalog", "old-zk-datalog-vol", "volume"),
                        ("/data", "old-zk-data-vol", "volume"),
                        ("/logs", "vol-a", "volume"),
                        ("/logs", "vol-b", "volume"),
                    ]
                ),
            },
            id="one-side-ambiguous-migrates-neither",
        ),
    ],
)
def test_doctor_migrate_volumes_falls_back_without_touching_anything(
    monkeypatch: pytest.MonkeyPatch,
    clickhouse_ids: Sequence[str],
    zookeeper_ids: Sequence[str],
    mounts_by_container: dict[str, str] | None,
) -> None:
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(
        clickhouse_ids=clickhouse_ids, zookeeper_ids=zookeeper_ids, mounts_by_container=mounts_by_container
    )
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Switching ClickHouse/ZooKeeper to named docker volumes" in result.output
    assert "developing-locally.md" in result.output
    # Never guess: an ambiguous or missing piece must abort before any stop
    # or copy call, not just skip that one piece.
    assert not any(c[:2] == ["docker", "stop"] for c in calls)
    assert not any(c[:2] == ["docker", "run"] for c in calls)


def test_doctor_migrate_volumes_copy_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # ClickHouse and zookeeper-data copy cleanly, but zookeeper-datalog fails
    # verification. Restoring only clickhouse+zookeeper-data would leave a
    # replicated table with "replica already exists" once ClickHouse starts
    # against restored state but ZooKeeper doesn't know about it.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(copy_returncode_by_dest={"posthog_zookeeper-datalog": 1})
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Switching ClickHouse/ZooKeeper to named docker volumes" in result.output
    assert "Migrated" not in result.output

    # The two volumes that copied successfully before the failure are rolled
    # back in one call, alongside the failed step's own (possibly
    # partially-written) volume — `docker run -v <dest>:/to ...` auto-creates
    # the destination volume before its command runs, so it must be removed
    # too, or a torn copy can survive rollback and get mistaken for a
    # completed migration on the next run. The containers we stopped are
    # restarted.
    assert [
        "docker",
        "volume",
        "rm",
        "-f",
        "posthog_clickhouse-data",
        "posthog_zookeeper-data",
        "posthog_zookeeper-datalog",
    ] in calls
    assert ["docker", "start", "ch1", "zk1"] in calls
    # The step after the failed one must never run.
    assert not any(c[:2] == ["docker", "run"] and "posthog_zookeeper-logs:/to" in c for c in calls)


def test_doctor_migrate_volumes_copy_timeout_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # A large ClickHouse volume on a slow disk can exceed the copy timeout.
    # subprocess.run raising TimeoutExpired must not skip rollback and leave
    # the old containers stopped with a half-written destination volume.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher()

    def timing_out_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[:2] == ["docker", "run"] and "posthog_clickhouse-data:/to" in cmd:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)
        return fake_run(cmd, **kwargs)

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", timing_out_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Switching ClickHouse/ZooKeeper to named docker volumes" in result.output
    assert ["docker", "volume", "rm", "-f", "posthog_clickhouse-data"] in calls
    assert ["docker", "start", "ch1", "zk1"] in calls


def test_doctor_migrate_volumes_interrupt_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ctrl-C during a multi-GB copy raises KeyboardInterrupt, which isn't a
    # subprocess.SubprocessError, so it wouldn't be caught by the same except
    # clause that handles a copy failure or timeout. Without an explicit
    # rollback on it, the destination volume survives half-written and the
    # next start's idempotency check mistakes it for a completed migration.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher()

    def interrupted_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[:2] == ["docker", "run"] and "posthog_clickhouse-data:/to" in cmd:
            raise KeyboardInterrupt
        return fake_run(cmd, **kwargs)

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", interrupted_run)

    assert doctor_migrate_volumes.callback is not None
    with pytest.raises(KeyboardInterrupt):
        doctor_migrate_volumes.callback()
    assert ["docker", "volume", "rm", "-f", "posthog_clickhouse-data"] in calls
    assert ["docker", "start", "ch1", "zk1"] in calls


def test_doctor_migrate_volumes_stop_failure_restarts_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    # `docker stop` on multiple containers can exit non-zero after partially
    # succeeding (e.g. one already vanished). Without a restart here, a
    # container that *did* stop would stay down even though no migration
    # happened — leaving a working dev stack unexpectedly offline.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(stop_returncode=1)
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert "Switching ClickHouse/ZooKeeper to named docker volumes" in result.output
    assert ["docker", "start", "ch1", "zk1"] in calls
    # Nothing was copied, so nothing needs to be rolled back.
    assert not any(c[:2] == ["docker", "run"] for c in calls)


def test_run_ok_echoes_stderr_on_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # `_run_ok` used to swallow captured stderr entirely on failure, so a real
    # docker-level error (permission denied, disk full, daemon hiccup) was
    # indistinguishable from any other failure once the caller fell back to its
    # generic warning.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="permission denied\n"),
    )
    assert _run_ok(["docker", "volume", "create", "x"]) is False
    assert "permission denied" in capsys.readouterr().out


def test_doctor_migrate_volumes_serializes_across_concurrent_worktrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `bin/start`'s own lock is per-worktree, but every worktree shares one compose
    # project, so two worktrees starting at once could both plan a migration for the
    # same destination volumes — one's rollback then deletes data the other just
    # copied. Prove a held lock blocks a concurrent invocation instead of letting it
    # race in unlocked.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(named_volume_exists=True)
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    lock_path = tmp_path / "hogli-migrate-volumes-posthog.lock"
    holder = open(lock_path, "w")
    fcntl.flock(holder, fcntl.LOCK_EX)

    done = threading.Event()
    thread = threading.Thread(target=lambda: (doctor_migrate_volumes.callback(), done.set()))  # type: ignore[misc]
    thread.start()
    try:
        # Still blocked on the lock: no docker call has run yet.
        assert not done.wait(timeout=0.1)
        assert calls == []
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()

    thread.join(timeout=5)
    assert done.is_set()
    assert calls  # released promptly and ran through once unblocked


def test_doctor_migrate_volumes_refuses_symlinked_lock_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The lock path is predictable and, on Linux, lives in world-writable /tmp.
    # Opening it with "w" follows a symlink another local user planted there and
    # truncates the target, handing them a file-destruction primitive in the
    # developer's account. Runs on every `hogli start`, so this must stay a
    # no-follow open — and must still fail open rather than crash the startup.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    fake_run, calls = _fake_migrate_dispatcher(named_volume_exists=True)
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    victim = tmp_path / "victim"
    victim.write_text("precious")
    (tmp_path / "hogli-migrate-volumes-posthog.lock").symlink_to(victim)

    result = CliRunner().invoke(doctor_migrate_volumes, [])
    assert result.exit_code == 0
    assert victim.read_text() == "precious"
    assert calls == []  # bailed before touching docker


def _make_pack_dir(common: Path, pack_count: int) -> None:
    pack_dir = common / "objects" / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    for i in range(pack_count):
        for ext in (".pack", ".idx", ".rev", ".promisor"):
            (pack_dir / f"pack-{i:040x}{ext}").touch()


def test_git_health_stops_counting_packs_past_the_cap(tmp_path: Path) -> None:
    # The check runs on every `hogli start`. A neglected clone holds tens of
    # thousands of packs. A full count would put seconds into a command that must
    # cost the same on a new clone and an old one. A report of exactly cap+1 proves
    # the scan stopped early.
    _make_pack_dir(tmp_path, 5000)

    health = _git_health(tmp_path, pack_cap=100)

    assert health.pack_count == 101
    assert health.packs_capped is True
    assert health.has_promisor is True


def test_git_health_reports_exact_count_below_the_cap(tmp_path: Path) -> None:
    _make_pack_dir(tmp_path, 7)

    health = _git_health(tmp_path, pack_cap=100)

    assert health.pack_count == 7
    assert health.packs_capped is False


def test_git_common_dir_resolves_a_worktree_to_the_shared_object_store(tmp_path: Path) -> None:
    # Packs, the commit-graph and the maintenance lock live in the shared .git, not
    # in the worktree's private directory. A wrong result makes every check pass on
    # a broken repo.
    common = tmp_path / "main" / ".git"
    (common / "worktrees" / "feature").mkdir(parents=True)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {common / 'worktrees' / 'feature'}\n")

    assert _git_common_dir(worktree) == common


def test_git_common_dir_handles_a_plain_checkout_and_a_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)
    assert _git_common_dir(plain) == plain / ".git"

    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    assert _git_common_dir(not_a_repo) is None


def test_git_maintenance_registered_matches_the_main_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A fresh clone has no registration, so none of git's scheduled tasks run.
    # Without this the check warns but never repairs the cause.
    repo = tmp_path / "posthog"

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=f"{tmp_path / 'other'}\n", returncode=0)

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)
    assert _git_maintenance_registered(repo) is False

    def fake_run_registered(cmd, **kwargs):
        return SimpleNamespace(stdout=f"{tmp_path / 'other'}\n{repo}\n", returncode=0)

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run_registered)
    assert _git_maintenance_registered(repo) is True


def test_git_maintenance_registered_fails_safe_when_git_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # A false "not registered" would rewrite the user's global git config because a
    # subprocess call failed.
    def boom(cmd, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", boom)
    assert _git_maintenance_registered(Path("/repo")) is True


def test_git_main_worktree_prefers_the_object_store_owner(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    assert _git_main_worktree(repo, tmp_path / "posthog" / ".git") == tmp_path / "posthog"


def test_git_main_worktree_falls_back_for_a_separate_git_dir(tmp_path: Path) -> None:
    # `git init --separate-git-dir` puts the metadata outside the tree, so the parent
    # of the common dir is not a work tree and git commands there fail.
    repo = tmp_path / "checkout"
    assert _git_main_worktree(repo, tmp_path / "elsewhere" / "myrepo.git") == repo


def test_doctor_git_spawns_the_repack_detached_instead_of_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # This runs on every `hogli start`. A repack takes minutes, so the command
    # spawns it and does not wait. A move back to subprocess.run makes start block.
    repo = tmp_path / "posthog"
    (repo / ".git" / "objects" / "pack").mkdir(parents=True)
    monkeypatch.setattr("hogli_commands.doctor.REPO_ROOT", repo)
    monkeypatch.setattr("hogli_commands.doctor._git_housekeeping_running", lambda *a: False)
    monkeypatch.setattr("hogli_commands.doctor._git_maintenance_registered", lambda _: True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=pack_cap + 1,
            packs_capped=True,
            has_promisor=True,
            stale_lock=None,
            missing_commit_graph=False,
        ),
    )
    ran: list[list[str]] = []
    spawned: list[list[str]] = []
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.Popen",
        lambda cmd, **kw: spawned.append(cmd) or SimpleNamespace(pid=1),
    )

    result = CliRunner().invoke(doctor_git, [])

    assert result.exit_code == 0
    assert len(spawned) == 1
    assert "repack" in spawned[0]
    assert not any("repack" in cmd for cmd in ran)


@pytest.mark.skipif(shutil.which("pgrep") is None, reason="pgrep is not installed")
def test_housekeeping_pattern_compiles_in_the_real_regex_engine() -> None:
    # pgrep uses a POSIX extended regular expression, which has no lazy quantifiers.
    # A pattern it rejects exits 2, which the scan must not read as "nothing running".
    # Testing this with Python's re passed while the real engine refused to compile.
    result = subprocess.run(["pgrep", "-f", _GIT_HOUSEKEEPING_PGREP_PATTERN], capture_output=True, text=True)
    assert result.returncode <= 1, result.stderr


@pytest.mark.parametrize(
    "command_line, expected",
    [
        ("git repack -adl --threads=0", True),
        ("git -C /home/x/posthog repack -adl --threads=0", True),
        ("git -C /tmp/PostHog Work/posthog repack -adl", True),
        ("taskpolicy -b git -C /home/x/posthog repack -adl", True),
        ("git -c gc.auto=0 gc --prune=now", True),
        ("git maintenance run --schedule=daily", True),
        ("git status --porcelain", False),
    ],
)
@pytest.mark.skipif(shutil.which("grep") is None, reason="grep is not installed")
def test_housekeeping_pattern_selects_candidate_processes(command_line: str, expected: bool) -> None:
    # The pattern is only a prefilter, so it may over-match. It must not under-match,
    # because a missed process means a second repack against the same object store.
    result = subprocess.run(
        ["grep", "-E", _GIT_HOUSEKEEPING_PGREP_PATTERN], input=command_line, capture_output=True, text=True
    )
    assert (result.returncode == 0) is expected


def test_housekeeping_scan_reports_a_pgrep_error_instead_of_assuming_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pgrep exits 2 on a pattern it cannot compile. Reading that as no-match leaves
    # the guard permanently off, which is how a bad pattern stays invisible.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: SimpleNamespace(returncode=2, stdout="", stderr="cannot compile"),
    )

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is True


def test_git_common_dir_resolves_a_relative_worktree_pointer(tmp_path: Path) -> None:
    # Git writes this pointer relative to the worktree in some layouts. Resolving it
    # against the process working directory finds the wrong object store, or none.
    common = tmp_path / "main" / ".git"
    (common / "worktrees" / "feature").mkdir(parents=True)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../main/.git/worktrees/feature\n")

    assert _git_common_dir(worktree) == common.resolve()


def test_git_common_dir_rejects_a_dangling_worktree_pointer(tmp_path: Path) -> None:
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {tmp_path / 'gone' / '.git' / 'worktrees' / 'feature'}\n")

    assert _git_common_dir(worktree) is None


def test_doctor_git_fix_writes_the_commit_graph_below_the_pack_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The check tells people to run --fix when the commit-graph is missing. Gating the
    # repair on a high pack count made --fix print success and repair nothing.
    repo = tmp_path / "posthog"
    (repo / ".git" / "objects" / "pack").mkdir(parents=True)
    monkeypatch.setattr("hogli_commands.doctor.REPO_ROOT", repo)
    monkeypatch.setattr("hogli_commands.doctor._git_housekeeping_running", lambda *a: False)
    monkeypatch.setattr("hogli_commands.doctor._git_maintenance_registered", lambda _: True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=3,
            packs_capped=False,
            has_promisor=True,
            stale_lock=None,
            missing_commit_graph=True,
        ),
    )
    ran: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        ran.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    result = CliRunner().invoke(doctor_git, ["--fix"])

    assert result.exit_code == 0
    assert any("commit-graph" in cmd for cmd in ran)
    assert not any("repack" in cmd for cmd in ran)


def test_doctor_git_fix_reports_a_failed_step_instead_of_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A repack that runs out of disk used to print a green "Done." and record the check.
    repo = tmp_path / "posthog"
    (repo / ".git" / "objects" / "pack").mkdir(parents=True)
    monkeypatch.setattr("hogli_commands.doctor.REPO_ROOT", repo)
    monkeypatch.setattr("hogli_commands.doctor._git_housekeeping_running", lambda *a: False)
    monkeypatch.setattr("hogli_commands.doctor._git_maintenance_registered", lambda _: True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=pack_cap + 1,
            packs_capped=False,
            has_promisor=True,
            stale_lock=None,
            missing_commit_graph=True,
        ),
    )
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no space left on device"),
    )

    result = CliRunner().invoke(doctor_git, ["--fix"])

    assert result.exit_code == 1
    assert "Done." not in result.output


@pytest.mark.parametrize(
    "stale_lock, packs_over, missing_graph, expected",
    [
        (False, False, True, "run `hogli doctor:git --fix`"),
        (False, True, True, "run `hogli doctor:git --fix`"),
        (True, False, True, "run `hogli doctor:git --fix`"),
        (False, True, False, "run `hogli doctor:git`"),
    ],
)
def test_git_health_remediation_names_a_command_that_repairs_the_problem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stale_lock: bool,
    packs_over: bool,
    missing_graph: bool,
    expected: str,
) -> None:
    # Only --fix writes the commit-graph. Sending a graph-only warning to the default
    # path prints "clean" and leaves the warning standing on the next run.
    repo = tmp_path / "posthog"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=pack_cap + 1 if packs_over else 3,
            packs_capped=False,
            has_promisor=True,
            stale_lock=tmp_path / "lock" if stale_lock else None,
            missing_commit_graph=missing_graph,
        ),
    )

    assert _check_git_health(repo).remediation == expected


def test_housekeeping_scan_ignores_git_in_another_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    # pgrep -f is machine wide. Treating an unrelated checkout's gc as this repo being
    # busy makes the repair skip itself, including removing a stale lock.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git -C /other/repo gc --prune=now\n", stderr="")
            if cmd[0] == "ps"
            else SimpleNamespace(returncode=0, stdout="n/other/repo\n", stderr="")
        ),
    )

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is False


def test_housekeeping_scan_claims_git_running_in_this_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git -C /home/x/posthog repack -adl\n", stderr="")
        ),
    )

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is True


def test_housekeeping_scan_is_idle_when_no_git_process_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is False


def test_housekeeping_scan_claims_a_sibling_linked_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    # A repack started from a sibling worktree without -C names neither the owning
    # checkout nor its path, but it uses the same object store. Missing it starts a
    # second repack against that store.
    common = Path("/home/x/posthog/.git")
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git repack -adl --threads=0\n", stderr="")
        ),
    )
    monkeypatch.setattr("hogli_commands.doctor._process_cwd", lambda pid: Path("/home/x/worktrees/tach"))
    monkeypatch.setattr("hogli_commands.doctor._common_dir_of", lambda cwd: common)

    assert _git_housekeeping_running(Path("/home/x/posthog"), common) is True


def test_housekeeping_scan_stays_idle_when_the_working_directory_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Without lsof and without /proc the cwd cannot be read. Claiming the process
    # there would disable stale-lock removal and repacking on that machine forever.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git gc --prune=now\n", stderr="")
        ),
    )
    monkeypatch.setattr("hogli_commands.doctor._process_cwd", lambda pid: None)

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is False


def test_doctor_git_fix_refuses_while_a_repack_is_already_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # --fix used to start a second minutes-long repack against the same object store.
    repo = tmp_path / "posthog"
    (repo / ".git" / "objects" / "pack").mkdir(parents=True)
    monkeypatch.setattr("hogli_commands.doctor.REPO_ROOT", repo)
    monkeypatch.setattr("hogli_commands.doctor._git_housekeeping_running", lambda *a: True)
    monkeypatch.setattr("hogli_commands.doctor._git_maintenance_registered", lambda _: True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=pack_cap + 1,
            packs_capped=False,
            has_promisor=True,
            stale_lock=None,
            missing_commit_graph=True,
        ),
    )
    ran: list[list[str]] = []
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = CliRunner().invoke(doctor_git, ["--fix"])

    assert result.exit_code == 0
    assert not any("repack" in cmd for cmd in ran)


def test_housekeeping_scan_ignores_a_sibling_clone_with_a_shared_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # /work/posthog-copy starts with /work/posthog. A substring test claims it, which
    # suppresses stale-lock removal and repacking for the real repository.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git -C /work/posthog-copy repack -adl\n", stderr="")
        ),
    )
    monkeypatch.setattr("hogli_commands.doctor._process_cwd", lambda pid: Path("/work/posthog-copy"))
    monkeypatch.setattr("hogli_commands.doctor._common_dir_of", lambda cwd: Path("/work/posthog-copy/.git"))

    assert _git_housekeeping_running(Path("/work/posthog"), Path("/work/posthog/.git")) is False


def test_housekeeping_scan_ignores_a_repository_nested_under_another_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # /tmp/work/posthog ends with /work/posthog. A trailing boundary alone claims it.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git -C /tmp/work/posthog repack -adl\n", stderr="")
        ),
    )
    monkeypatch.setattr("hogli_commands.doctor._process_cwd", lambda pid: Path("/tmp/work/posthog"))
    monkeypatch.setattr("hogli_commands.doctor._common_dir_of", lambda cwd: Path("/tmp/work/posthog/.git"))

    assert _git_housekeeping_running(Path("/work/posthog"), Path("/work/posthog/.git")) is False


def test_doctor_git_reports_a_stale_lock_it_cannot_remove(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Swallowing the error printed "clean" while the lock still disabled every
    # scheduled git task, which is exactly the silent failure this check removes.
    repo = tmp_path / "posthog"
    (repo / ".git" / "objects" / "pack").mkdir(parents=True)
    lock = tmp_path / "maintenance.lock"
    lock.write_text("")
    monkeypatch.setattr("hogli_commands.doctor.REPO_ROOT", repo)
    monkeypatch.setattr("hogli_commands.doctor._git_housekeeping_running", lambda *a: False)
    monkeypatch.setattr("hogli_commands.doctor._git_maintenance_registered", lambda _: True)
    monkeypatch.setattr(
        "hogli_commands.doctor._git_health",
        lambda common, pack_cap: SimpleNamespace(
            pack_count=3,
            packs_capped=False,
            has_promisor=True,
            stale_lock=lock,
            missing_commit_graph=False,
        ),
    )
    monkeypatch.setattr(Path, "unlink", lambda self, **kw: (_ for _ in ()).throw(PermissionError("read-only")))

    result = CliRunner().invoke(doctor_git, [])

    assert "clean" not in result.output
    assert "stays disabled" in result.output


def test_housekeeping_scan_claims_git_dir_given_as_an_option_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `git --git-dir=<path> repack` puts an equals sign before the path, and the
    # process runs outside the checkout, so the working directory says nothing.
    monkeypatch.setattr(
        "hogli_commands.doctor.subprocess.run",
        lambda cmd, **kw: (
            SimpleNamespace(returncode=0, stdout="4242\n", stderr="")
            if cmd[0] == "pgrep"
            else SimpleNamespace(returncode=0, stdout="git --git-dir=/home/x/posthog/.git repack -adl\n", stderr="")
        ),
    )
    monkeypatch.setattr("hogli_commands.doctor._process_cwd", lambda pid: Path("/somewhere/else"))
    monkeypatch.setattr("hogli_commands.doctor._common_dir_of", lambda cwd: Path("/somewhere/else/.git"))

    assert _git_housekeeping_running(Path("/home/x/posthog"), Path("/home/x/posthog/.git")) is True
