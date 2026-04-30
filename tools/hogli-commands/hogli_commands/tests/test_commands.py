"""Tests for PostHog-specific hogli commands and hooks."""

from __future__ import annotations

import json
import time

import pytest
from unittest.mock import patch

from hogli_commands.commands import _infer_container_runtime, _infer_process_manager, _is_posthog_dev


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


class TestInferContainerRuntime:
    @pytest.fixture(autouse=True)
    def _isolate_socket(self, monkeypatch):
        monkeypatch.delenv("DOCKER_HOST", raising=False)
        monkeypatch.setattr(
            "hogli_commands.commands._read_docker_socket_fingerprint",
            lambda: (None, False),
        )

    @pytest.mark.parametrize(
        ("docker_host", "expected"),
        [
            ("unix:///Users/jane/.orbstack/run/docker.sock", "orbstack"),
            ("unix:///Users/jane/.docker/run/docker.sock", "docker_desktop"),
            ("unix:///Users/jane/.colima/default/docker.sock", "colima"),
            ("unix:///Users/jane/.rd/docker.sock", "rancher_desktop"),
            ("unix:///run/user/1000/podman/podman.sock", "podman"),
            ("tcp://10.0.0.1:2375", "other"),
        ],
        ids=["orbstack", "docker_desktop", "colima", "rancher_desktop", "podman", "other"],
    )
    def test_docker_host_env_var(self, monkeypatch, docker_host, expected):
        monkeypatch.setenv("DOCKER_HOST", docker_host)
        assert _infer_container_runtime() == expected

    @pytest.mark.parametrize(
        ("link_target", "expected"),
        [
            ("/Users/jane/.orbstack/run/docker.sock", "orbstack"),
            ("/Users/jane/.docker/run/docker.sock", "docker_desktop"),
            ("/Users/jane/.colima/default/docker.sock", "colima"),
        ],
        ids=["orbstack", "docker_desktop", "colima"],
    )
    def test_socket_symlink_target(self, monkeypatch, link_target, expected):
        monkeypatch.setattr(
            "hogli_commands.commands._read_docker_socket_fingerprint",
            lambda: (link_target, True),
        )
        assert _infer_container_runtime() == expected

    def test_native_socket_returns_docker_engine(self, monkeypatch):
        monkeypatch.setattr(
            "hogli_commands.commands._read_docker_socket_fingerprint",
            lambda: (None, True),
        )
        assert _infer_container_runtime() == "docker_engine"

    def test_no_socket_returns_none(self):
        assert _infer_container_runtime() is None
