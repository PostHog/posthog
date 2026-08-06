import os
import json
import time
import fcntl
import hashlib
import threading
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from click.testing import CliRunner
from hogli_commands.doctor import (
    FLOX_LOG_MAX_AGE_DAYS,
    FLOX_LOG_MAX_TOTAL_BYTES,
    _binary_arches,
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
