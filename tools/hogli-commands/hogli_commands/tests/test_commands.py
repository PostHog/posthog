"""Tests for PostHog-specific hogli commands and hooks."""

from __future__ import annotations

import json
import time

import pytest
from unittest.mock import patch

from hogli_commands.telemetry_props import (
    _AGENT_ENV_MARKERS,
    _DEVBOX_ENV_MARKERS,
    _detect_agent,
    _detect_environment,
    _infer_process_manager,
    _is_posthog_dev,
    _repo_commit,
    _repo_commit_properties,
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
        monkeypatch.delenv("HOGLI_AGENT", raising=False)
        for var, _ in _AGENT_ENV_MARKERS:
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
        ],
        ids=[
            "human",
            "claude_code",
            "codex",
            "posthog_code",
            "posthog_code_beats_claude",
            "declared_normalized",
            "declared_beats_sniffed",
        ],
    )
    def test_detection(self, monkeypatch, env_vars, expected) -> None:
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)
        assert _detect_agent() == expected


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
