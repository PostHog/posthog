import os
import time
import hashlib
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
    _sanitize_compose_name,
    _scan_port_holders,
    _scan_unheld_via_lsof,
    _select_flox_logs_to_remove,
    _tail,
    doctor_ports,
)

_QUARTER_BUDGET = FLOX_LOG_MAX_TOTAL_BYTES // 4
_TWO_FIFTHS_BUDGET = int(FLOX_LOG_MAX_TOTAL_BYTES * 0.4)


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
        return SimpleNamespace(returncode=1, stdout="p100\nn/repo/a\np200\nn/repo/b\n")

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


def _fake_docker_ps(monkeypatch: pytest.MonkeyPatch, port_scan_stdout: str = "", clickhouse_stdout: str = "") -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        if cmd[:2] == ["docker", "ps"] and "-a" not in cmd:
            return SimpleNamespace(returncode=0, stdout=port_scan_stdout)
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout=clickhouse_stdout)
        return SimpleNamespace(returncode=1, stdout="")

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
    holders = {h.port: h for h in _scan_port_holders("posthog")}
    if expected_holder is None:
        assert holders[expected_port].container is None
    else:
        assert holders[expected_port].container == "evilbox"
        assert holders[expected_port].project == expected_holder


def test_scan_port_holders_own_project_is_not_flagged_foreign(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker_ps(monkeypatch, port_scan_stdout="clickhouse|posthog|127.0.0.1:8123->8123/tcp")
    holders = {h.port: h for h in _scan_port_holders("posthog")}
    assert holders[8123].project == "posthog"


def test_scan_port_holders_sanitizes_malicious_project_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker_ps(monkeypatch, port_scan_stdout="evilbox|posthog-evil$(rm -rf /)|127.0.0.1:8010->8000/tcp")
    holders = {h.port: h for h in _scan_port_holders("posthog")}
    assert holders[8010].project == "posthog-evilrm-rf"


def test_posthog_shaped_projects_filters_by_clickhouse_label(monkeypatch: pytest.MonkeyPatch) -> None:
    # This is the exact partial-stack gap Greptile flagged (P1) against the
    # bash version: `docker ps -a` (all states) means a project whose
    # clickhouse container is stopped, but another service still holds a
    # port, is still offered for teardown — not just one whose CH is running.
    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        assert "label=com.docker.compose.service=clickhouse" in cmd
        return SimpleNamespace(returncode=0, stdout="stopped-proj\n")

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
        return SimpleNamespace(returncode=0, stdout=lsof_output)

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
        clickhouse_stdout="foreign-proj\n",
    )
    # CliRunner's stdin/stdout are never a TTY, so this exercises the
    # non-interactive (print-only, no subprocess teardown) branch.
    result = CliRunner().invoke(doctor_ports, [])
    assert result.exit_code == 0
    assert "foreign-proj" in result.output
    assert "docker compose -p foreign-proj -f docker-compose.dev.yml down --remove-orphans" in result.output


def test_doctor_ports_tears_down_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    # CliRunner always simulates a non-tty stdin/stdout with no override hook,
    # so the interactive branch is exercised by calling the command function
    # directly instead of through Click's dispatcher.
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("hogli_commands.doctor.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hogli_commands.doctor.sys.stdout.isatty", lambda: True)

    teardown_calls: list[list[str]] = []

    def dispatch(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        if cmd[:2] == ["docker", "ps"] and "-a" not in cmd:
            return SimpleNamespace(returncode=0, stdout="evilbox|foreign-proj|127.0.0.1:8010->8000/tcp")
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout="foreign-proj\n")
        if cmd[:2] == ["docker", "compose"]:
            teardown_calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", dispatch)

    # --yes skips the interactive prompt; verifies the exact teardown argv
    # (a reordered or dropped arg here would tear down the wrong compose file).
    assert doctor_ports.callback is not None
    doctor_ports.callback(yes=True)
    assert teardown_calls == [
        ["docker", "compose", "-p", "foreign-proj", "-f", "docker-compose.dev.yml", "down", "--remove-orphans"]
    ]
