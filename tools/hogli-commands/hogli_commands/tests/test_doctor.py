from types import SimpleNamespace

import pytest

from hogli_commands.doctor import (
    _binary_arches,
    _collect_import_targets,
    _format_kv_block,
    _get_process_cwds,
    _is_excluded,
    _normalize_arch,
    _phrocs_info,
    _probe_command_imports,
)


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


def test_format_kv_block_aligns_values() -> None:
    block = _format_kv_block([("os", "macOS"), ("term_program", "iTerm")])
    assert block == ["os            macOS", "term_program  iTerm"]


def test_format_kv_block_empty() -> None:
    assert _format_kv_block([]) == []


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


def test_probe_command_imports_reports_all_ok() -> None:
    manifest = _FakeManifest({"doctor": {"click": "hogli_commands.doctor:doctor"}})
    probed, failures = _probe_command_imports(manifest)
    assert probed == 1
    assert failures == []


def test_probe_command_imports_flags_missing_module() -> None:
    manifest = _FakeManifest({"ghost": {"click": "hogli_commands.does_not_exist:thing"}})
    probed, failures = _probe_command_imports(manifest)
    assert probed == 1
    assert len(failures) == 1
    label, error = failures[0]
    assert label == "ghost"
    assert "ModuleNotFoundError" in error


def test_probe_command_imports_flags_missing_attribute() -> None:
    manifest = _FakeManifest({"typo": {"click": "hogli_commands.doctor:not_a_real_command"}})
    probed, failures = _probe_command_imports(manifest)
    assert probed == 1
    assert failures == [("typo", "missing attribute 'not_a_real_command'")]


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
