from types import SimpleNamespace

import pytest

from hogli_commands.doctor import (
    _collect_import_targets,
    _copy_to_clipboard,
    _format_kv_block,
    _is_excluded,
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


def test_copy_to_clipboard_returns_none_when_no_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda _: None)
    assert _copy_to_clipboard("anything") is None


def test_copy_to_clipboard_uses_first_available_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("hogli_commands.doctor.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("hogli_commands.doctor.subprocess.run", fake_run)

    assert _copy_to_clipboard("hello") == "pbcopy"
    assert captured["cmd"] == ["pbcopy"]
    assert captured["input"] == "hello"
