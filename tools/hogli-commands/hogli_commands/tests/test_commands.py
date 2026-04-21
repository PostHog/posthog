"""Tests for PostHog-specific hogli commands and hooks."""

from __future__ import annotations

import json
import time

import pytest
from unittest.mock import patch

from hogli_commands.commands import _infer_process_manager, _is_posthog_dev


class TestProcessManagerInference:
    def test_start_defaults_to_phrocs(self, monkeypatch) -> None:
        monkeypatch.delenv("HOGLI_PROCESS_MANAGER", raising=False)
        monkeypatch.setattr("sys.argv", ["hogli", "start"])

        assert _infer_process_manager("start") == "phrocs"

    def test_start_uses_mprocs_flag(self, monkeypatch) -> None:
        monkeypatch.delenv("HOGLI_PROCESS_MANAGER", raising=False)
        monkeypatch.setattr("sys.argv", ["hogli", "start", "--mprocs"])

        assert _infer_process_manager("start") == "mprocs"

    def test_env_override_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("HOGLI_PROCESS_MANAGER", "/usr/local/bin/phrocs")
        monkeypatch.setattr("sys.argv", ["hogli", "start", "--mprocs"])

        assert _infer_process_manager("start") == "phrocs"


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

    @patch("hogli_commands.commands._check_github_org_membership", return_value=True)
    def test_cache_miss_calls_gh_and_persists(self, _mock_gh, _config_dir):
        assert _is_posthog_dev() is True
        assert json.loads(_config_dir.read_text())["is_posthog_org_member"] is True

    @patch("hogli_commands.commands._check_email_domain", return_value=True)
    @patch("hogli_commands.commands._check_github_org_membership", return_value=None)
    def test_gh_unavailable_falls_back_to_email_and_caches(self, _mock_gh, mock_email, _config_dir):
        assert _is_posthog_dev() is True
        mock_email.assert_called_once()
        assert json.loads(_config_dir.read_text())["is_posthog_org_member"] is True
