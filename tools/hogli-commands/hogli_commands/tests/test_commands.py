"""Tests for PostHog-specific hogli commands and hooks."""

from __future__ import annotations

import json
import time
import fcntl

import pytest
from unittest.mock import patch

from hogli.manifest import REPO_ROOT
from hogli_commands.telemetry_props import (
    _AGENT_ENV_MARKERS,
    _DEVBOX_ENV_MARKERS,
    _STANDARD_AGENT_ENV_VARS,
    RecordedRun,
    _detect_actor,
    _detect_agent,
    _detect_environment,
    _infer_process_manager,
    _is_posthog_dev,
    _repo_commit,
    _repo_commit_properties,
    _session_properties,
    classify_command,
    is_rerun,
)


class TestProcessManagerInference:
    @pytest.mark.parametrize(
        ("env_value", "argv", "expected"),
        [
            (None, ["hogli", "start"], "phrocs"),
            (None, ["hogli", "start", "--mprocs"], "mprocs"),
            ("/usr/local/bin/phrocs", ["hogli", "start", "--mprocs"], "phrocs"),
        ],
        ids=["default", "mprocs_flag", "env_override"],
    )
    def test_infer_process_manager(self, monkeypatch, env_value, argv, expected) -> None:
        if env_value is None:
            monkeypatch.delenv("HOGLI_PROCESS_MANAGER", raising=False)
        else:
            monkeypatch.setenv("HOGLI_PROCESS_MANAGER", env_value)
        monkeypatch.setattr("sys.argv", argv)

        assert _infer_process_manager("start") == expected


class TestDetectEnvironment:
    @pytest.fixture(autouse=True)
    def _neutral_environment(self, monkeypatch, tmp_path):
        # is_ci is the seam the code consults -- mock it instead of coupling
        # to the framework's internal list of CI env vars.
        monkeypatch.setattr("hogli_commands.telemetry_props.is_ci", lambda: False)
        monkeypatch.setattr("hogli_commands.telemetry_props._HOGLAND_MARKER", tmp_path / "absent")
        for var in ("HOGLI_ENVIRONMENT", *_DEVBOX_ENV_MARKERS):
            monkeypatch.delenv(var, raising=False)

    @pytest.mark.parametrize(
        ("env_vars", "ci", "hogland", "expected"),
        [
            ({}, False, False, "local"),
            ({}, True, False, "ci"),
            ({"CODER": "true"}, False, False, "devbox"),
            ({"CODER_WORKSPACE_NAME": "raul-devbox"}, False, False, "devbox"),
            ({}, False, True, "hogland"),
            ({"CODER": "true"}, False, True, "devbox"),
            ({"HOGLI_ENVIRONMENT": "sandbox"}, False, False, "sandbox"),
            ({"HOGLI_ENVIRONMENT": " Sandbox "}, False, False, "sandbox"),
            ({"HOGLI_ENVIRONMENT": "sandbox"}, True, False, "sandbox"),
            ({"CODER": "true"}, True, False, "ci"),
        ],
        ids=[
            "local",
            "ci",
            "coder",
            "coder_workspace",
            "hogland",
            "devbox_beats_hogland",
            "declared",
            "declared_normalized",
            "declared_beats_ci",
            "ci_beats_devbox",
        ],
    )
    def test_classification(self, monkeypatch, tmp_path, env_vars, ci, hogland, expected) -> None:
        if ci:
            monkeypatch.setattr("hogli_commands.telemetry_props.is_ci", lambda: True)
        if hogland:
            monkeypatch.setattr("hogli_commands.telemetry_props._HOGLAND_MARKER", tmp_path)
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)
        assert _detect_environment() == expected


class TestDetectAgent:
    @pytest.fixture(autouse=True)
    def _no_ambient_agent(self, monkeypatch):
        for var in ("HOGLI_AGENT", *dict(_AGENT_ENV_MARKERS), *_STANDARD_AGENT_ENV_VARS):
            monkeypatch.delenv(var, raising=False)

    @pytest.mark.parametrize(
        ("env_vars", "expected"),
        [
            ({}, None),
            ({"CLAUDECODE": "1"}, "claude-code"),
            ({"CODEX_SANDBOX": "seatbelt"}, "codex"),
            ({"POSTHOG_CODE_VERSION": "1.2.3"}, "posthog-code"),
            ({"POSTHOG_CODE_VERSION": "1.2.3", "CLAUDECODE": "1"}, "posthog-code"),
            ({"HOGLI_AGENT": " Goose "}, "goose"),
            ({"HOGLI_AGENT": "goose", "CLAUDECODE": "1"}, "goose"),
            ({"AI_AGENT": "Cursor-CLI@1.2.3"}, "cursor-cli"),
            ({"AI_AGENT": "claude-code_2-1-295_agent"}, "claude-code"),
            ({"AGENT": "1"}, "unknown"),
            ({"AGENT": "1", "OPENCODE": "1"}, "opencode"),
        ],
        ids=[
            "undeclared",
            "claude_code",
            "codex",
            "posthog_code",
            "posthog_code_beats_claude",
            "declared_normalized",
            "declared_beats_sniffed",
            "standard_var_drops_at_version",
            "standard_var_drops_underscore_version",
            "standard_var_bare_flag",
            "marker_beats_standard_var",
        ],
    )
    def test_detection(self, monkeypatch, env_vars, expected) -> None:
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)
        assert _detect_agent() == expected


class TestDetectActor:
    @pytest.mark.parametrize(
        ("agent", "terminal_fds", "inherited", "expected"),
        [
            ("claude-code", {0, 1, 2}, "human", "agent"),
            (None, {1, 2}, None, "human"),
            (None, set(), None, "unknown"),
            (None, set(), "human", "human"),
        ],
        ids=[
            "agent_beats_terminal_and_inherited",
            "pre_push_hook_stdin_piped",
            "no_terminal_no_agent",
            "nested_command_inherits_human",
        ],
    )
    def test_classification(self, monkeypatch, agent, terminal_fds, inherited, expected) -> None:
        monkeypatch.setattr("hogli_commands.telemetry_props.os.isatty", lambda fd: fd in terminal_fds)
        if inherited is None:
            monkeypatch.delenv("HOGLI_ACTOR", raising=False)
        else:
            monkeypatch.setenv("HOGLI_ACTOR", inherited)
        assert _detect_actor(agent) == expected


class TestRepoCommitProperties:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self):
        _repo_commit.cache_clear()
        yield
        _repo_commit.cache_clear()

    def test_returns_sha_and_date_in_a_git_checkout(self) -> None:
        props = _repo_commit_properties()
        assert set(props) == {"repo_sha", "repo_commit_date"}
        # %h honors core.abbrev, which git permits down to 4
        assert len(props["repo_sha"]) >= 4
        assert props["repo_commit_date"][:2] == "20"  # ISO date

    def test_returns_empty_when_git_fails(self) -> None:
        with patch("hogli_commands.telemetry_props.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            assert _repo_commit_properties() == {}


class TestIsPosthogDev:
    @pytest.fixture()
    def _config_dir(self, tmp_path, monkeypatch):
        config_file = tmp_path / "hogli_telemetry.json"
        monkeypatch.setattr("hogli.telemetry.get_config_path", lambda: config_file)
        return config_file

    def _write_config(self, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kwargs))

    def test_fresh_cache_skips_api(self, _config_dir):
        self._write_config(_config_dir, is_posthog_org_member=True, org_check_timestamp=time.time())
        assert _is_posthog_dev() is True

    @patch("hogli_commands.telemetry_props._check_github_org_membership", return_value=True)
    def test_cache_miss_calls_gh_and_persists(self, _mock_gh, _config_dir):
        assert _is_posthog_dev() is True
        assert json.loads(_config_dir.read_text())["is_posthog_org_member"] is True

    @patch("hogli_commands.telemetry_props._check_email_domain", return_value=True)
    @patch("hogli_commands.telemetry_props._check_github_org_membership", return_value=None)
    def test_gh_unavailable_falls_back_to_email_and_caches(self, _mock_gh, mock_email, _config_dir):
        assert _is_posthog_dev() is True
        mock_email.assert_called_once()
        assert json.loads(_config_dir.read_text())["is_posthog_org_member"] is True


class TestClassifyCommand:
    @pytest.mark.parametrize(
        ("command", "argv", "expected"),
        [
            ("ci:preflight", [], "verify-preflight"),
            ("test:e2e", [], "verify-e2e"),
            ("test", ["playwright/e2e/insights.spec.ts"], "verify-e2e"),
            ("test", ["posthog/api/test/test_team.py"], "verify-test"),
            ("test", ["posthog/api/test/test_playwright_setup.py"], "verify-test"),
            ("test:python", [], "verify-test"),
            ("desktop:test", [], "verify-test"),
            ("test:quarantine", [], "other"),
            ("desktop:typecheck", [], "verify-typecheck"),
            ("lint", [], "verify-lint"),
            ("lint:workflows", [], "verify-lint"),
            ("format:python", [], "verify-lint"),
            ("product:lint", [], "verify-lint"),
            ("product:lint:owners", [], "verify-lint"),
            ("desktop:lint:fix", [], "verify-lint"),
            ("tool:ruff", [], "verify-lint"),
            ("build:openapi", [], "build"),
            ("phrocs:build", [], "build"),
            ("start", [], "run-stack"),
            ("start:backend", [], "run-stack"),
            ("up", ["-d"], "run-stack"),
            ("docker:services:up", [], "run-stack"),
            ("devbox:start", [], "devbox"),
            ("metabase:query", [], "other"),
            (None, [], "other"),
        ],
    )
    def test_classification(self, command, argv, expected) -> None:
        assert classify_command(command, argv) == expected

    def test_a_spec_named_from_inside_the_playwright_directory_is_e2e(self, monkeypatch) -> None:
        monkeypatch.chdir(REPO_ROOT / "playwright")
        assert classify_command("test", ["e2e/insights.spec.ts"]) == "verify-e2e"


class TestIsRerun:
    NOW = 1_000_000.0

    @pytest.mark.parametrize(
        ("runs", "expected"),
        [
            ([], False),
            ([RecordedRun(session_id="s1", kind="verify-test", at=NOW - 60)], True),
            ([RecordedRun(session_id="s1", kind="verify-test", at=NOW - 30 * 60)], True),
            ([RecordedRun(session_id="s1", kind="verify-test", at=NOW - 30 * 60 - 1)], False),
            ([RecordedRun(session_id="s2", kind="verify-test", at=NOW - 60)], False),
            ([RecordedRun(session_id="s1", kind="verify-lint", at=NOW - 60)], False),
            ([RecordedRun(session_id="s1", kind="verify-test", at=NOW + 60)], False),
        ],
        ids=[
            "first_run",
            "same_session_same_kind",
            "window_edge_inclusive",
            "outside_window",
            "other_session",
            "other_kind",
            "clock_skew_future_entry",
        ],
    )
    def test_decision(self, runs, expected) -> None:
        assert is_rerun(runs, "s1", "verify-test", self.NOW) is expected


class TestSessionProperties:
    @pytest.fixture(autouse=True)
    def _isolated_state(self, monkeypatch, tmp_path):
        monkeypatch.setattr("hogli_commands.telemetry_props._TELEMETRY_STATE_PATH", tmp_path / "state.json")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
        for var in ("HOGLI_SESSION_ID", "POSTHOG_TASK_RUN_ID"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("sys.argv", ["hogli", "lint"])
        _session_properties.cache_clear()
        yield
        _session_properties.cache_clear()

    def test_next_process_in_session_is_a_rerun_but_repeated_hook_calls_are_not(self) -> None:
        assert _session_properties("lint")["is_rerun"] is False
        assert _session_properties("lint")["is_rerun"] is False
        _session_properties.cache_clear()
        rerun = _session_properties("lint")
        assert rerun == {
            "command_kind": "verify-lint",
            "session_id": rerun["session_id"],
            "session_id_source": "agent",
            "is_rerun": True,
        }
        assert rerun["session_id"].startswith("agent-")
        assert "sess-1" not in rerun["session_id"]

    def test_corrupt_state_file_does_not_raise(self, tmp_path) -> None:
        (tmp_path / "state.json").write_text('{"runs": [["only-two", 1], "junk"], "terminal_sessions": 3}')
        assert _session_properties("lint")["is_rerun"] is False

    def test_held_state_lock_does_not_block_the_command(self, tmp_path) -> None:
        with (tmp_path / "state.json.lock").open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            assert _session_properties("lint")["is_rerun"] is False
            fcntl.flock(holder, fcntl.LOCK_UN)
        _session_properties.cache_clear()
        assert _session_properties("lint")["is_rerun"] is True

    def test_recycled_leader_pid_gets_a_new_terminal_id(self, monkeypatch) -> None:
        for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("os.getsid", lambda _pid: 4242)
        monkeypatch.setattr("hogli_commands.telemetry_props._proc_start_time", lambda _pid: "1000")
        first = _session_properties("lint")["session_id"]
        _session_properties.cache_clear()
        monkeypatch.setattr("hogli_commands.telemetry_props._proc_start_time", lambda _pid: "2000")
        second = _session_properties("lint")
        assert first is not None and first.startswith("term-")
        assert second["session_id"] != first
        assert second["is_rerun"] is False
