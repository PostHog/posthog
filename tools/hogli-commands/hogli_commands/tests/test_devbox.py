"""Tests for the hogli devbox commands."""

from __future__ import annotations

import os
import csv
import json
import errno
import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands.devbox import (
    cli as devbox_cli,
    coder,
    config as devbox_config,
    mutagen as devbox_mutagen,
    sync as devbox_sync,
)

runner = CliRunner()


@pytest.fixture
def devbox_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "hogli_devbox.json"
    monkeypatch.setattr(devbox_config, "get_config_path", lambda: config_path)
    return config_path


class TestDevboxConfig:
    """Test persisted devbox preferences."""

    def test_save_git_identity_persists_trimmed_values(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity(" PostHog Engineer ", " test-user@example.com ")

        assert devbox_config.load_config() == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }
        assert json.loads(devbox_config_path.read_text()) == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }

    def test_save_dotfiles_uri_persists_trimmed_value(self, devbox_config_path: Path) -> None:
        devbox_config.save_dotfiles_uri(" https://github.com/user/dotfiles ")

        config = devbox_config.load_config()
        assert config["dotfiles_uri"] == "https://github.com/user/dotfiles"

    def test_save_dotfiles_uri_merges_with_existing_config(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
            "dotfiles_uri": "https://github.com/user/dotfiles",
        }

    def test_clear_dotfiles_uri_removes_only_dotfiles(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")

        devbox_config.clear_dotfiles_uri()

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }

    def test_clear_dotfiles_uri_is_noop_when_unset(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")

        devbox_config.clear_dotfiles_uri()

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }

    def test_clear_git_identity_leaves_dotfiles_intact(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")

        devbox_config.clear_git_identity()

        config = devbox_config.load_config()
        assert config == {"dotfiles_uri": "https://github.com/user/dotfiles"}

    def test_save_region_persists_alongside_other_fields(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_region("eu-central-1")

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
            "region": "eu-central-1",
        }

    def test_clear_region_leaves_other_fields_intact(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_region("eu-central-1")

        devbox_config.clear_region()

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }

    def test_clear_region_is_noop_when_unset(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")

        devbox_config.clear_region()

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }


class TestUserSecrets:
    """Test the per-user Coder secret helpers used for Git signing."""

    def test_upsert_creates_when_secret_does_not_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[list[str], str | None]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((args, kwargs.get("input")))  # type: ignore[arg-type]
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)
        monkeypatch.setattr(coder, "_resolve_coder", lambda args: args)

        coder.upsert_user_secret("API_KEY", "v1", env_name="API_KEY")

        assert calls == [(["coder", "secret", "create", "API_KEY", "--env", "API_KEY"], "v1")]

    def test_upsert_falls_back_to_update_when_create_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            returncode = 1 if "create" in args else 0
            return subprocess.CompletedProcess(args, returncode, "", "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)
        monkeypatch.setattr(coder, "_resolve_coder", lambda args: args)

        coder.upsert_user_secret("API_KEY", "v2", env_name="API_KEY")

        assert calls == [
            ["coder", "secret", "create", "API_KEY", "--env", "API_KEY"],
            ["coder", "secret", "update", "API_KEY", "--env", "API_KEY"],
        ]

    def test_upsert_pipes_value_via_stdin_never_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Security invariant: the value MUST be piped on stdin, never as a
        # CLI flag. coder secret create's --value would expose it in argv /
        # /proc/<pid>/cmdline / ps aux.
        calls: list[tuple[list[str], str | None]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((args, kwargs.get("input")))  # type: ignore[arg-type]
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)
        monkeypatch.setattr(coder, "_resolve_coder", lambda args: args)

        coder.upsert_user_secret("API_KEY", "super-secret", env_name="API_KEY", description="api creds")

        argv, stdin = calls[0]
        assert stdin == "super-secret"
        assert "--value" not in argv
        assert "super-secret" not in argv
        assert argv[: argv.index("--env")] == ["coder", "secret", "create", "API_KEY"]
        assert "--description" in argv and argv[argv.index("--description") + 1] == "api creds"

    def test_upsert_exits_when_both_create_and_update_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 2, "", "boom")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)
        monkeypatch.setattr(coder, "_resolve_coder", lambda args: args)

        with pytest.raises(SystemExit) as excinfo:
            coder.upsert_user_secret("API_KEY", "v3", env_name="API_KEY")
        assert excinfo.value.code == 2

    def test_user_secret_exists_matches_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_run",
            lambda args, **kw: subprocess.CompletedProcess(args, 0, '[{"name":"API_KEY"},{"name":"OTHER"}]', ""),
        )
        assert coder.user_secret_exists("API_KEY") is True
        assert coder.user_secret_exists("MISSING") is False

    def test_user_secret_exists_returns_false_on_cli_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_run", lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "auth required"))
        assert coder.user_secret_exists("API_KEY") is False

    def test_user_secret_exists_returns_false_on_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_run", lambda args, **kw: subprocess.CompletedProcess(args, 0, "not json", ""))
        assert coder.user_secret_exists("API_KEY") is False


class TestResolveTailscale:
    """Test Tailscale CLI resolution with macOS app bundle fallback."""

    def test_prefers_path_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: "/usr/local/bin/tailscale")
        assert coder._resolve_tailscale() == "/usr/local/bin/tailscale"

    def test_falls_back_to_macos_app_bundle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "darwin")
        monkeypatch.setattr(coder.os.path, "isfile", lambda path: path == coder._MACOS_TAILSCALE_CLI)
        assert coder._resolve_tailscale() == coder._MACOS_TAILSCALE_CLI

    def test_returns_none_when_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "darwin")
        monkeypatch.setattr(coder.os.path, "isfile", lambda path: False)
        assert coder._resolve_tailscale() is None

    def test_skips_macos_path_on_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "linux")
        assert coder._resolve_tailscale() is None

    def test_tailscale_env_sets_cli_flag_for_app_bundle(self) -> None:
        env = coder._tailscale_env(coder._MACOS_TAILSCALE_CLI)
        assert env is not None
        assert env["TAILSCALE_BE_CLI"] == "1"

    def test_tailscale_env_returns_none_for_path_binary(self) -> None:
        assert coder._tailscale_env("/usr/local/bin/tailscale") is None

    def test_tailscale_status_uses_resolved_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: coder._MACOS_TAILSCALE_CLI)

        captured_args: list[list[str]] = []
        captured_env: list[object] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured_args.append(args)
            captured_env.append(kwargs.get("env"))
            return subprocess.CompletedProcess(args, 0, '{"BackendState": "Running"}', "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        status = coder._tailscale_status()

        assert status == {"BackendState": "Running"}
        assert captured_args[0][0] == coder._MACOS_TAILSCALE_CLI
        env = captured_env[0]
        assert isinstance(env, dict)
        assert env["TAILSCALE_BE_CLI"] == "1"

    def test_ensure_tailscale_connected_says_not_installed_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "tailscale_connected", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: None)
        monkeypatch.setattr(coder.sys, "platform", "linux")

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        out = capsys.readouterr().out
        assert "not installed" in out
        # The install hint must be present so the user can act without searching.
        assert "tailscale.com/install.sh" in out

    def test_ensure_tailscale_connected_install_hint_is_macos_specific(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "tailscale_connected", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: None)
        monkeypatch.setattr(coder.sys, "platform", "darwin")

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        out = capsys.readouterr().out
        assert "brew install --cask tailscale" in out

    def test_ensure_tailscale_connected_says_not_connected_when_daemon_down(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "tailscale_connected", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: "/usr/local/bin/tailscale")
        monkeypatch.setattr(coder, "_tailscale_cli_missing_on_macos", lambda: False)
        monkeypatch.setattr(coder.sys, "platform", "linux")

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        out = capsys.readouterr().out
        assert "installed but not connected" in out
        # On Linux the connect hint must mention `tailscale up`, not the macOS app.
        assert "tailscale up" in out

    def test_ensure_tailscale_connected_emits_symlink_hint_on_macos_when_cli_only_in_app_bundle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "tailscale_connected", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: coder._MACOS_TAILSCALE_CLI)
        monkeypatch.setattr(coder, "_tailscale_cli_missing_on_macos", lambda: True)

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        out = capsys.readouterr().out
        assert "not on your PATH" in out
        assert "ln -sfn" in out
        assert coder._MACOS_TAILSCALE_CLI in out


class TestTailscaleRoutesAccepted:
    """Test auto-enabling subnet route acceptance for devbox connectivity."""

    def test_detects_routes_not_accepted_from_health_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_tailscale_status",
            lambda: {"Health": ["Some peers are advertising routes but --accept-routes is false"]},
        )
        assert coder._tailscale_routes_accepted() is False

    def test_ensure_noop_when_already_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_tailscale_routes_accepted", lambda: True)
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        coder.ensure_tailscale_routes_accepted()

        assert calls == []

    def test_ensure_invokes_tailscale_set_accept_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_tailscale_routes_accepted", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: coder._MACOS_TAILSCALE_CLI)
        monkeypatch.setattr(coder.sys, "platform", "darwin")
        captured: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.append(args)
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        coder.ensure_tailscale_routes_accepted()

        assert captured == [[coder._MACOS_TAILSCALE_CLI, "set", "--accept-routes"]]


class TestCoderConfig:
    """Test config and runtime preflight helpers."""

    @pytest.mark.parametrize(
        "env_key, env_value, expected_url",
        [
            ("HOGLI_DEVBOX_CODER_URL", "https://env.example.com", "https://env.example.com"),
            ("CODER_URL", "https://coder-env.example.com", "https://coder-env.example.com"),
        ],
    )
    def test_get_coder_url_prefers_env_over_manifest(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_key: str,
        env_value: str,
        expected_url: str,
    ) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)
        monkeypatch.setenv(env_key, env_value)

        with patch(
            "hogli_commands.devbox.coder.load_manifest", return_value={"metadata": {"devbox": {"coder_url": "ignored"}}}
        ):
            assert coder.get_coder_url() == expected_url

    def test_get_coder_url_falls_back_to_manifest_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)

        with patch(
            "hogli_commands.devbox.coder.load_manifest",
            return_value={"metadata": {"devbox": {"coder_url": "https://manifest.example.com"}}},
        ):
            assert coder.get_coder_url() == "https://manifest.example.com"

    def test_runtime_ready_requires_setup_when_coder_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "ensure_tailscale_connected", lambda setup_hint=coder.RUNTIME_SETUP_HINT: None)
        monkeypatch.setattr(coder, "ensure_tailscale_routes_accepted", lambda: None)
        monkeypatch.setattr(coder, "ensure_coder_reachable", lambda: None)
        monkeypatch.setattr(coder, "coder_installed", lambda: False)

        with pytest.raises(SystemExit):
            coder.ensure_runtime_ready()

        assert "Run `hogli devbox:setup`." in capsys.readouterr().out

    def test_run_build_raises_if_stdout_pipe_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.subprocess, "Popen", lambda *args, **kwargs: MagicMock(stdout=None))

        with pytest.raises(RuntimeError, match="stdout pipe was not opened"):
            coder._run_build(["coder", "start", "devbox-test-user"])


class TestCoderVersion:
    """Test Coder CLI version pinning and mismatch warnings."""

    def test_get_server_version_queries_buildinfo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CODER_VERSION", raising=False)
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"version": "v2.30.5+abc123"}

        with patch("hogli_commands.devbox.coder.requests.get", return_value=mock_resp) as mock_get:
            assert coder.get_server_version() == "2.30.5"
            mock_get.assert_called_once_with("https://coder.example.com/api/v2/buildinfo", timeout=5)

    @pytest.mark.parametrize(
        "raw_version, expected",
        [
            ("v1.0.0", "1.0.0"),
            ("v2.30.5+3b2ded6", "2.30.5"),
            ("1.0.0+abc123", "1.0.0"),
            ("v0.1.0-rc1+build.42", "0.1.0-rc1"),
        ],
    )
    def test_get_installed_coder_version_normalizes(
        self, monkeypatch: pytest.MonkeyPatch, raw_version: str, expected: str
    ) -> None:
        monkeypatch.setattr(
            coder,
            "_run",
            lambda args, capture_output=False: subprocess.CompletedProcess(
                args, 0, json.dumps({"version": raw_version}), ""
            ),
        )
        assert coder.get_installed_coder_version() == expected

    def test_warn_version_mismatch_prints_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(coder, "get_server_version", lambda: "1.0.0")
        monkeypatch.setattr(coder, "get_installed_coder_version", lambda: "2.0.0")
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

        coder._warn_version_mismatch()
        output = capsys.readouterr().out
        assert "v2.0.0" in output
        assert "v1.0.0" in output
        assert "curl -fsSL https://coder.example.com/install.sh | sh" in output

    def test_ensure_coder_installed_uses_deployment_install_script(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        managed_dir = tmp_path / "bin"
        monkeypatch.setattr(coder, "coder_installed", lambda: False)
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")
        monkeypatch.setattr(coder, "get_server_version", lambda: "1.0.0")
        monkeypatch.setattr(coder, "_MANAGED_CODER_DIR", managed_dir)

        captured_cmd: list[str] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured_cmd.extend(args)
            managed_dir.mkdir(parents=True, exist_ok=True)
            (managed_dir / "coder").touch()
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        coder.ensure_coder_installed()
        full_cmd = " ".join(captured_cmd)
        assert "set -o pipefail" in full_cmd
        assert "curl -fsSL https://coder.example.com/install.sh" in full_cmd
        assert f"--prefix {tmp_path}" in full_cmd

    def test_ensure_coder_installed_fails_when_binary_missing_after_install(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(coder, "coder_installed", lambda: False)
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")
        monkeypatch.setattr(coder, "get_server_version", lambda: "1.0.0")
        monkeypatch.setattr(coder, "_MANAGED_CODER_DIR", tmp_path / "bin")

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        with pytest.raises(SystemExit):
            coder.ensure_coder_installed()

    def test_ensure_coder_authenticated_fails_fast_when_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "coder_installed", lambda: False)
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

        def boom(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("should not invoke coder when not installed")

        monkeypatch.setattr(coder.subprocess, "run", boom)

        with pytest.raises(SystemExit):
            coder.ensure_coder_authenticated()


class TestCoderReachable:
    """Test the Coder deployment reachability probe and diagnostic."""

    def test_coder_reachable_returns_false_on_request_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

        def boom(*a: object, **kw: object) -> object:
            raise coder.requests.ConnectionError("blackholed")

        monkeypatch.setattr(coder.requests, "get", boom)
        assert coder.coder_reachable() is False

    def test_ensure_coder_reachable_fails_when_unreachable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")
        monkeypatch.setattr(coder, "coder_reachable", lambda: False)
        monkeypatch.setattr(
            coder,
            "_diagnose_unreachable_coder",
            lambda: coder.CoderReachabilityDiagnosis(
                cause="stubbed cause.",
                next_step="stubbed step.",
                facts=["fact: one"],
            ),
        )

        with pytest.raises(SystemExit):
            coder.ensure_coder_reachable()

        out = capsys.readouterr().out
        assert "Cannot reach https://coder.example.com" in out
        assert "stubbed cause." in out
        assert "stubbed step." in out
        assert "fact: one" in out


class TestDiagnoseUnreachableCoder:
    """Test the structured cause-and-next-step diagnosis for unreachable Coder."""

    @pytest.fixture(autouse=True)
    def _stub_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

    def test_dns_failure_dominates_other_causes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_tailscale_status", lambda: {"CurrentTailnet": {"Name": "posthog.com"}})
        monkeypatch.setattr(coder, "_resolve_host_ip", lambda host: None)

        def must_not_run(*args: object, **kwargs: object) -> bool:
            raise AssertionError("TCP probe should be skipped when DNS fails")

        monkeypatch.setattr(coder, "_tcp_reachable", must_not_run)

        diagnosis = coder._diagnose_unreachable_coder()
        assert "DNS lookup" in diagnosis.cause
        assert "MagicDNS" in diagnosis.next_step
        assert "Tailscale tailnet: posthog.com" in diagnosis.facts

    def test_tcp_open_signals_tls_or_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_tailscale_status", lambda: {"CurrentTailnet": {"Name": "posthog.com"}})
        monkeypatch.setattr(coder, "_resolve_host_ip", lambda host: "10.0.0.1")
        monkeypatch.setattr(coder, "_tcp_reachable", lambda host, port, timeout=3.0: True)

        diagnosis = coder._diagnose_unreachable_coder()
        assert "HTTPS probe" in diagnosis.cause
        assert "clock" in diagnosis.next_step.lower()

    def test_no_subnet_routers_points_to_wrong_tailnet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_tailscale_status",
            lambda: {"CurrentTailnet": {"Name": "personal.tailnet"}, "Peer": {"k": {"PrimaryRoutes": None}}},
        )
        monkeypatch.setattr(coder, "_resolve_host_ip", lambda host: "10.0.0.1")
        monkeypatch.setattr(coder, "_tcp_reachable", lambda host, port, timeout=3.0: False)

        diagnosis = coder._diagnose_unreachable_coder()
        assert "No peer" in diagnosis.cause
        assert "Team DevEx" in diagnosis.next_step

    def test_routers_all_offline_says_relay_is_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_tailscale_status",
            lambda: {
                "CurrentTailnet": {"Name": "posthog.com"},
                "Peer": {
                    "k": {"HostName": "subnet-router-us", "PrimaryRoutes": ["10.0.0.0/16"], "Online": False},
                },
            },
        )
        monkeypatch.setattr(coder, "_resolve_host_ip", lambda host: "10.0.0.1")
        monkeypatch.setattr(coder, "_tcp_reachable", lambda host, port, timeout=3.0: False)

        diagnosis = coder._diagnose_unreachable_coder()
        assert "subnet-router-us" in diagnosis.cause
        assert "Wait a minute" in diagnosis.next_step

    def test_routers_online_points_at_acl_or_vpn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_tailscale_status",
            lambda: {
                "CurrentTailnet": {"Name": "posthog.com"},
                "Peer": {
                    "k": {"HostName": "subnet-router-us", "PrimaryRoutes": ["10.0.0.0/16"], "Online": True},
                },
            },
        )
        monkeypatch.setattr(coder, "_resolve_host_ip", lambda host: "10.0.0.1")
        monkeypatch.setattr(coder, "_tcp_reachable", lambda host, port, timeout=3.0: False)

        diagnosis = coder._diagnose_unreachable_coder()
        assert "blocked" in diagnosis.cause.lower()
        assert "ACL" in diagnosis.next_step or "VPN" in diagnosis.next_step.upper()


class TestWorkspaceNaming:
    """Test workspace name derivation, label validation, and extraction."""

    def test_default_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name() == "devbox-test-user"

    def test_labeled_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name("api") == "devbox-test-user-api"

    def test_multi_segment_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name("my-project") == "devbox-test-user-my-project"

    @pytest.mark.parametrize("bad_label", ["", "UPPER", "has space", "-leading", "trailing-"])
    def test_invalid_label_rejected(self, monkeypatch: pytest.MonkeyPatch, bad_label: str) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        with pytest.raises(SystemExit):
            coder.get_workspace_name(bad_label)

    def test_extract_label_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("devbox-test-user") is None

    def test_extract_label_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("devbox-test-user-api") == "api"

    def test_extract_label_hyphenated_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user-two")
        assert coder.extract_workspace_label("devbox-test-user-two") is None
        assert coder.extract_workspace_label("devbox-test-user-two-api") == "api"

    def test_extract_label_unrelated_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("other-workspace") is None

    @pytest.mark.parametrize(
        "label, region, expected",
        [
            (None, "us-east-1", "devbox-test-user"),
            (None, "eu-central-1", "devbox-test-user-eu"),
            ("api", "us-east-1", "devbox-test-user-api"),
            ("api", "eu-central-1", "devbox-test-user-api-eu"),
            ("my-project", "eu-central-1", "devbox-test-user-my-project-eu"),
        ],
        ids=["default-us", "default-eu", "labeled-us", "labeled-eu", "hyphenated-labeled-eu"],
    )
    def test_workspace_name_encodes_region_suffix(
        self, monkeypatch: pytest.MonkeyPatch, label: str | None, region: str, expected: str
    ) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name(label, region=region) == expected

    @pytest.mark.parametrize(
        "workspace_name, expected_region",
        [
            ("devbox-test-user", "us-east-1"),
            ("devbox-test-user-api", "us-east-1"),
            ("devbox-test-user-eu", "eu-central-1"),
            ("devbox-test-user-api-eu", "eu-central-1"),
        ],
        ids=["default-us", "labeled-us", "default-eu", "labeled-eu"],
    )
    def test_region_from_workspace_name(self, workspace_name: str, expected_region: str) -> None:
        assert coder.region_from_workspace_name(workspace_name) == expected_region

    @pytest.mark.parametrize("reserved", ["eu", "api-eu", "foo-eu"])
    def test_label_colliding_with_region_suffix_rejected(self, monkeypatch: pytest.MonkeyPatch, reserved: str) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        with pytest.raises(SystemExit):
            coder.get_workspace_name(reserved)

    @pytest.mark.parametrize(
        "workspace_name, expected_label",
        [
            ("devbox-test-user-eu", None),
            ("devbox-test-user-api-eu", "api"),
            ("devbox-test-user-my-project-eu", "my-project"),
        ],
        ids=["region-only-default", "labeled-with-region", "hyphenated-label-with-region"],
    )
    def test_extract_label_strips_region_suffix(
        self, monkeypatch: pytest.MonkeyPatch, workspace_name: str, expected_label: str | None
    ) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label(workspace_name) == expected_label

    @pytest.mark.parametrize(
        "user, label, expected",
        [
            ("alice", None, "devbox-alice"),
            ("alice", "api", "devbox-alice-api"),
        ],
    )
    def test_shared_workspace_name_ignores_caller_region(self, user: str, label: str | None, expected: str) -> None:
        # Shared workspace lookups never apply the caller's region pref:
        # the remote workspace's region belongs to its owner.
        assert coder.resolve_shared_workspace_name(user, label) == expected


class TestWorkspaceRegion:
    """Reading the region back from the workspace `region` metadata item."""

    @pytest.mark.parametrize(
        "workspace, expected",
        [
            # Region item present on a resource.
            (
                {"latest_build": {"resources": [{"metadata": [{"key": "region", "value": "eu-central-1"}]}]}},
                "eu-central-1",
            ),
            # Region item sits among other metadata items.
            (
                {
                    "latest_build": {
                        "resources": [
                            {"metadata": [{"key": "cpu", "value": "8"}, {"key": "region", "value": "us-east-1"}]}
                        ]
                    }
                },
                "us-east-1",
            ),
            # Region item lives on a later resource.
            (
                {
                    "latest_build": {
                        "resources": [
                            {"metadata": [{"key": "cpu", "value": "8"}]},
                            {"metadata": [{"key": "region", "value": "us-east-1"}]},
                        ]
                    }
                },
                "us-east-1",
            ),
            # No metadata at all (box created before the item existed).
            ({"latest_build": {"resources": [{"metadata": []}]}}, None),
            ({"latest_build": {"resources": []}}, None),
            ({"latest_build": {}}, None),
            ({}, None),
            # Empty value is treated as unknown.
            (
                {"latest_build": {"resources": [{"metadata": [{"key": "region", "value": ""}]}]}},
                None,
            ),
            # Malformed metadata entries are ignored, not crashed on.
            (
                {
                    "latest_build": {
                        "resources": [{"metadata": ["not-a-dict", {"key": "region", "value": "us-east-1"}]}]
                    }
                },
                "us-east-1",
            ),
        ],
        ids=[
            "single-item",
            "among-others",
            "later-resource",
            "empty-metadata",
            "no-resources",
            "no-build-resources",
            "empty-payload",
            "empty-value",
            "malformed-entry-skipped",
        ],
    )
    def test_get_workspace_region(self, workspace: dict[str, object], expected: str | None) -> None:
        assert coder.get_workspace_region(workspace) == expected


def _parse_parameter_flags(args: list[str]) -> dict[str, str]:
    """Extract `key=value` pairs from `--parameter` flags in argv."""
    out: dict[str, str] = {}
    for flag, value in zip(args, args[1:]):
        if flag == "--parameter":
            key, _, val = value.partition("=")
            out[key] = val
    return out


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value paired with the given flag in argv, or None."""
    for cur, nxt in zip(args, args[1:]):
        if cur == flag:
            return nxt
    return None


def _stub_create_workspace(captured: dict[str, str | None]) -> Callable[..., None]:
    """Stub for ``devbox_cli.create_workspace`` that records its forwarded kwargs.

    Tracks every CLI-facing kwarg so devbox:start tests can assert on the
    specific subset they care about without redeclaring the signature.
    """

    def stub(
        name: str,
        disk_size: int,
        *,
        git_name: str | None = None,
        git_email: str | None = None,
        dotfiles_uri: str | None = None,
        region: str = coder.DEFAULT_REGION,
        template: str = coder.DEFAULT_TEMPLATE,
        preset: str = coder.DEFAULT_PRESET,
        start_app: bool | None = None,
        verbose: bool = False,
    ) -> None:
        captured.update(
            {
                "name": name,
                "disk_size": str(disk_size),
                "git_name": git_name,
                "git_email": git_email,
                "dotfiles_uri": dotfiles_uri,
                "region": region,
                "template": template,
                "preset": preset,
                "start_app": str(start_app),
            }
        )

    return stub


def _fake_run_build_capturing(captured: dict[str, object]) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return a `_run_build` stub that records its argv and reports success."""

    def fake(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["verbose"] = verbose
        return subprocess.CompletedProcess(args, 0, "", "")

    return fake


_DOTFILES = "https://github.com/user/dotfiles"
_REPO = "https://github.com/PostHog/posthog"


class TestWorkspaceCreation:
    """Test Coder workspace creation parameter passing and template selection."""

    @pytest.mark.parametrize(
        "kwargs, available_presets, expected_template, expected_preset, expected_params",
        [
            # Default opts out of presets so a vanilla create never claims a
            # prebuild; the resolved preset is the NO_PRESET sentinel.
            (
                {},
                ["Default (warm)", "Cold"],
                "posthog-linux",
                "none",
                {"disk_size": "100", "repo": _REPO, "workspace_region": "us-east-1"},
            ),
            # An explicit warm preset that the template defines flows through to
            # the coder argv unchanged, alongside all optional params.
            (
                {
                    "preset": "Default (warm)",
                    "git_name": "PostHog Engineer",
                    "git_email": "test-user@example.com",
                    "dotfiles_uri": _DOTFILES,
                },
                ["Default (warm)"],
                "posthog-linux",
                "Default (warm)",
                {
                    "disk_size": "100",
                    "repo": _REPO,
                    "workspace_region": "us-east-1",
                    "git_name": "PostHog Engineer",
                    "git_email": "test-user@example.com",
                    "dotfiles_uri": _DOTFILES,
                },
            ),
            (
                {"template": "posthog-microvm"},
                ["Default (warm)"],
                "posthog-microvm",
                "none",
                {"disk_size": "100", "repo": _REPO, "workspace_region": "us-east-1"},
            ),
            # Resolution fallback to "none" is exhaustively covered by
            # TestTemplatePresetResolution; one case here is enough to prove
            # the resolved value flows through to the coder argv. The requested
            # preset is not among the template's presets, so it falls back.
            (
                {"template": "posthog-microvm", "preset": "Default (warm)"},
                ["Cold only"],
                "posthog-microvm",
                "none",
                {"disk_size": "100", "repo": _REPO, "workspace_region": "us-east-1"},
            ),
            # A non-default region is forwarded verbatim as workspace_region.
            (
                {"region": "eu-central-1"},
                ["Default (warm)"],
                "posthog-linux",
                "none",
                {"disk_size": "100", "repo": _REPO, "workspace_region": "eu-central-1"},
            ),
        ],
        ids=[
            "defaults",
            "explicit-preset-all-optionals",
            "custom-template",
            "resolver-fallback-flows-through",
            "explicit-region",
        ],
    )
    def test_create_workspace_forwards_params_and_template(
        self,
        monkeypatch: pytest.MonkeyPatch,
        kwargs: dict[str, str],
        available_presets: list[str],
        expected_template: str,
        expected_preset: str,
        expected_params: dict[str, str],
    ) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(coder, "_run_build", _fake_run_build_capturing(captured))
        monkeypatch.setattr(coder, "_list_template_presets", lambda template: list(available_presets))

        coder.create_workspace("devbox-test-user", 100, **kwargs)

        args = captured["args"]
        assert args[:3] == ["coder", "create", "devbox-test-user"]
        assert _flag_value(args, "--template") == expected_template
        # `--preset` must always be forwarded -- newer coder versions otherwise
        # prompt interactively for a preset, which `--yes` does not bypass.
        assert _flag_value(args, "--preset") == expected_preset
        assert "--use-parameter-defaults" in args
        assert "--yes" in args
        # Security invariant: the Claude OAuth token is a Coder user secret
        # (env-injected at workspace start); it must never be forwarded as a
        # --parameter flag where it would leak into argv / process listings.
        params = _parse_parameter_flags(args)
        assert "claude_oauth_token" not in params
        assert params == expected_params

    @pytest.mark.parametrize(
        "start_app, expected",
        [(True, "true"), (False, "false"), (None, None)],
        ids=["enable", "disable", "omit"],
    )
    def test_create_workspace_forwards_start_app_parameter(
        self, monkeypatch: pytest.MonkeyPatch, start_app: bool | None, expected: str | None
    ) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(coder, "_run_build", _fake_run_build_capturing(captured))
        monkeypatch.setattr(coder, "_list_template_presets", lambda template: ["Default (warm)"])

        coder.create_workspace("devbox-test-user", 100, start_app=start_app)

        params = _parse_parameter_flags(captured["args"])
        if expected is None:
            assert coder.AUTO_START_APP_PARAMETER not in params
        else:
            assert params[coder.AUTO_START_APP_PARAMETER] == expected

    @pytest.mark.parametrize(
        "outputs, dropped, raises",
        [
            # Single unknown param dropped, retry succeeds.
            (
                [
                    (1, 'parameter "dotfiles_uri" is not present in the template\n'),
                    (0, ""),
                ],
                {"dotfiles_uri"},
                False,
            ),
            # Two unknown params reported one at a time; each is dropped in
            # turn before the final call succeeds.
            (
                [
                    (1, 'parameter "dotfiles_uri" is not present in the template\n'),
                    (1, 'parameter "git_name" is not present in the template\n'),
                    (0, ""),
                ],
                {"dotfiles_uri", "git_name"},
                False,
            ),
            # The magic phrase appearing inside a parameter value (not at the
            # start of a line) must not trigger a retry. _PARAM_NOT_PRESENT_RE
            # anchors the match to the start of a line.
            (
                [(1, "echoed back: --parameter foo='parameter \"dotfiles_uri\" is not present'\n")],
                set(),
                True,
            ),
            # Any other build failure aborts immediately.
            (
                [(1, "terraform apply failed\n")],
                set(),
                True,
            ),
        ],
        ids=["single-drop", "multi-drop", "phrase-in-value-no-retry", "unrelated-error-no-retry"],
    )
    def test_create_workspace_param_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        outputs: list[tuple[int, str]],
        dropped: set[str],
        raises: bool,
    ) -> None:
        queue = list(outputs)
        calls: list[list[str]] = []

        def fake_run_build(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            rc, stdout = queue.pop(0)
            return subprocess.CompletedProcess(args, rc, stdout, "")

        monkeypatch.setattr(coder, "_run_build", fake_run_build)
        monkeypatch.setattr(coder, "_list_template_presets", lambda template: ["Default (warm)"])

        def go() -> None:
            coder.create_workspace(
                "devbox-test-user",
                100,
                git_name="PostHog Engineer",
                dotfiles_uri=_DOTFILES,
            )

        if raises:
            with pytest.raises(SystemExit):
                go()
        else:
            go()

        assert len(calls) == len(outputs)
        assert dropped.isdisjoint(_parse_parameter_flags(calls[-1]))


class TestTemplatePresetResolution:
    """Test the runtime preset resolution that suppresses coder's picker."""

    @pytest.mark.parametrize(
        "rc, stdout, stderr, expected, warning_expected",
        [
            (0, '[{"name": "Default (warm)"}, {"name": "Cold"}]', "", ["Default (warm)", "Cold"], False),
            (1, "", "auth: token expired", [], True),
            (1, "", "", [], True),
            (0, '{"error": "no presets"}', "", [], False),
            (0, "not json", "", [], False),
            (0, '[{"name": "Default (warm)"}, {"description": "no-name"}]', "", ["Default (warm)"], False),
        ],
        ids=[
            "happy",
            "non-zero-exit-with-stderr",
            "non-zero-exit-bare",
            "non-list-json",
            "invalid-json",
            "skip-nameless",
        ],
    )
    def test_list_template_presets_parses_coder_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        rc: int,
        stdout: str,
        stderr: str,
        expected: list[str],
        warning_expected: bool,
    ) -> None:
        def fake_run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            assert args[:4] == ["coder", "templates", "presets", "list"]
            return subprocess.CompletedProcess(args, rc, stdout, stderr)

        monkeypatch.setattr(coder, "_run", fake_run)

        assert coder._list_template_presets(coder.DEFAULT_TEMPLATE) == expected
        output = capsys.readouterr().out
        if warning_expected:
            assert "Warning: failed to list presets" in output
            if stderr:
                assert stderr in output
        else:
            assert "Warning" not in output

    @pytest.mark.parametrize(
        "requested, presets, expected, warning_expected",
        [
            ("Default (warm)", ["Default (warm)", "Cold"], "Default (warm)", False),
            ("none", ["Default (warm)"], "none", False),
            ("Default (warm)", ["Cold only"], "none", True),
            ("Default (warm)", [], "none", False),
            ("Missing", ["Default (warm)"], "none", True),
        ],
        ids=["match", "explicit-none", "default-missing", "no-presets", "user-supplied-missing"],
    )
    def test_resolve_template_preset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        requested: str,
        presets: list[str],
        expected: str,
        warning_expected: bool,
    ) -> None:
        monkeypatch.setattr(coder, "_list_template_presets", lambda template: list(presets))

        result = coder.resolve_template_preset("posthog-linux", requested)

        assert result == expected
        output = capsys.readouterr().out
        if warning_expected:
            assert "Warning" in output
        else:
            assert "Warning" not in output


class TestWorkspaceUpdate:
    """Test that `coder update` paths share the same retry behavior as create.

    Without this, a stale `dotfiles_uri` (or any param the new template
    doesn't declare) saved in the user's hogli config would abort the
    pre-start parameter sync the next time they switch templates.
    """

    @pytest.mark.parametrize(
        "call",
        [
            lambda: coder.update_workspace(
                "devbox-test-user",
                parameters={"dotfiles_uri": _DOTFILES, "git_name": "PostHog Engineer"},
            ),
            lambda: coder.update_workspace_parameters(
                "devbox-test-user",
                {"dotfiles_uri": _DOTFILES, "git_name": "PostHog Engineer"},
            ),
        ],
        ids=["update_workspace", "update_workspace_parameters"],
    )
    def test_update_paths_drop_unknown_params_and_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        call: Callable[[], None],
    ) -> None:
        calls: list[list[str]] = []

        def fake_run_build(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args, 1, 'parameter "dotfiles_uri" is not present in the template\n', ""
                )
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_build", fake_run_build)

        call()

        assert len(calls) == 2
        first = _parse_parameter_flags(calls[0])
        retried = _parse_parameter_flags(calls[1])
        assert "dotfiles_uri" in first and "git_name" in first
        assert "dotfiles_uri" not in retried
        assert retried["git_name"] == "PostHog Engineer"


class TestResolveWorkspaceName:
    """Test the CLI workspace resolution logic."""

    def test_explicit_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        # Own-label resolution fetches the workspace list to allow cross-region
        # fallback, so `workspaces` comes back populated even when the target
        # isn't found.
        name, workspaces = devbox_cli.resolve_workspace_name("api")
        assert name == "devbox-test-user-api"
        assert workspaces == []

    def test_explicit_shared_label_skips_workspace_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shared targets (`@user[/label]`) skip the own-workspace list call."""
        calls: list[str] = []
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: calls.append("listed") or [])
        name, workspaces = devbox_cli.resolve_workspace_name("@alice/api")
        assert name == "devbox-alice-api"
        assert workspaces is None
        assert calls == []

    def test_own_label_falls_back_to_cross_region_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If preferred-region name doesn't exist, find a workspace with the same label in another region."""
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "_preferred_region", lambda: "eu-central-1")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user-api"}],  # us-region workspace, no -eu suffix
        )
        name, workspaces = devbox_cli.resolve_workspace_name("api")
        # Preferred-region name would be `devbox-test-user-api-eu`; fallback finds the us workspace.
        assert name == "devbox-test-user-api"
        assert workspaces == [{"name": "devbox-test-user-api"}]

    def test_multiple_workspaces_falls_back_to_other_region_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no default in the preferred region, the other region's default wins over failing."""
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "_preferred_region", lambda: "eu-central-1")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-api"}],
        )
        name, _ = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"

    def test_own_label_prefers_preferred_region_when_both_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "_preferred_region", lambda: "eu-central-1")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user-api"}, {"name": "devbox-test-user-api-eu"}],
        )
        name, _ = devbox_cli.resolve_workspace_name("api")
        assert name == "devbox-test-user-api-eu"

    def test_preferred_region_falls_back_when_saved_value_unknown(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path
    ) -> None:
        # Simulate a hand-edited config with a region that's no longer in REGIONS.
        devbox_config_path.write_text(json.dumps({"region": "ap-southeast-2"}))
        assert devbox_cli._preferred_region() == coder.DEFAULT_REGION

    def test_no_workspaces_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli, "get_workspace_name", lambda label=None, region=coder.DEFAULT_REGION: "devbox-test-user"
        )
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"
        assert workspaces == []

    def test_single_workspace_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [{"name": "devbox-test-user-api"}])
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user-api"
        assert len(workspaces) == 1

    def test_multiple_workspaces_prefers_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli, "get_workspace_name", lambda label=None, region=coder.DEFAULT_REGION: "devbox-test-user"
        )
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-api"}],
        )
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"
        assert len(workspaces) == 2

    def test_multiple_workspaces_no_default_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli, "get_workspace_name", lambda label=None, region=coder.DEFAULT_REGION: "devbox-test-user"
        )
        monkeypatch.setattr(
            devbox_cli, "extract_workspace_label", lambda name: name.split("-", 2)[-1] if name.count("-") > 1 else None
        )
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user-api"}, {"name": "devbox-test-user-web"}],
        )
        with pytest.raises(SystemExit):
            devbox_cli.resolve_workspace_name(None)


class TestDevboxCommands:
    """Test the Click command contract for devbox commands."""

    def test_devbox_help_lists_setup_and_runtime_commands(self) -> None:
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "devbox:setup" in result.output
        assert "devbox:open" in result.output
        assert "devbox:logs" in result.output

    def test_plain_devbox_command_lists_available_workspace_commands(self) -> None:
        result = runner.invoke(cli, ["devbox"])

        assert result.exit_code == 0
        assert "hogli devbox:setup" in result.output
        assert "hogli devbox:start" in result.output
        assert "hogli devbox:list" in result.output
        assert "hogli devbox:restart" in result.output
        assert "hogli devbox:update" in result.output
        assert "hogli devbox:destroy" in result.output

    def test_devbox_setup_runs_explicit_setup_steps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": calls.append("tailscale"))
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_routes_accepted", lambda: calls.append("routes"))
        monkeypatch.setattr(devbox_cli, "ensure_coder_reachable", lambda: calls.append("reachable"))
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda **kw: calls.append("install"))
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: calls.append("login"))
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_ssh",
            lambda configure_ssh, **kw: calls.append(f"ssh:{configure_ssh}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_git_identity",
            lambda configure_git_identity: calls.append(f"git:{configure_git_identity}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_git_signing",
            lambda configure_git_signing, **kw: calls.append(f"signing:{configure_git_signing}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_region",
            lambda configure_region: calls.append(f"region:{configure_region}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_dotfiles",
            lambda configure_dotfiles: calls.append(f"dotfiles:{configure_dotfiles}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_claude_secret",
            lambda configure_claude, **kw: calls.append(f"claude:{configure_claude}"),
        )
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: calls.append("summary"))

        result = runner.invoke(
            cli,
            [
                "devbox:setup",
                "--skip-configure-ssh",
                "--skip-configure-git-identity",
                "--skip-configure-git-signing",
                "--skip-configure-region",
                "--skip-configure-dotfiles",
                "--skip-configure-claude",
            ],
        )

        assert result.exit_code == 0
        assert calls == [
            "tailscale",
            "routes",
            "reachable",
            "install",
            "login",
            "ssh:False",
            "git:False",
            "signing:False",
            "region:False",
            "dotfiles:False",
            "claude:False",
            "summary",
        ]

    def test_devbox_setup_threads_resolved_identity_agent_into_ssh_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_routes_accepted", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_reachable", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "_resolve_local_identity_agent_for_coder", lambda: "/tmp/resolved.sock")
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
        monkeypatch.setattr(devbox_cli, "maybe_configure_git_identity", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_git_signing", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_region", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_ssh",
            lambda *, configure_ssh, identity_agent_socket=None, **_: captured.update(
                {"identity_agent_socket": identity_agent_socket}
            ),
        )

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-git-identity"])

        assert result.exit_code == 0
        assert captured == {"identity_agent_socket": "/tmp/resolved.sock"}

    def test_devbox_setup_uses_coder_profile_as_prompt_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
    ) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_routes_accepted", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_reachable", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "_resolve_local_identity_agent_for_coder", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_git_signing", lambda configure_git_signing, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_region", lambda configure_region: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda configure_claude, **kw: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)
        monkeypatch.setattr(devbox_cli, "get_default_git_identity", lambda: ("Coder User", "coder@example.com"))

        # No Y/n gate -- prompts shown directly with coder profile defaults
        result = runner.invoke(
            cli,
            ["devbox:setup", "--skip-configure-ssh"],
            input="\n\n",
        )

        assert result.exit_code == 0
        assert "Saved Git identity for new workspaces: Coder User <coder@example.com>" in result.output
        assert json.loads(devbox_config_path.read_text()) == {
            "git_name": "Coder User",
            "git_email": "coder@example.com",
        }

    def test_devbox_setup_renders_compact_status_for_saved_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
    ) -> None:
        devbox_config_path.write_text(json.dumps({"git_name": "Existing User", "git_email": "existing@example.com"}))

        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_routes_accepted", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_reachable", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "_resolve_local_identity_agent_for_coder", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_git_signing", lambda configure_git_signing, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_region", lambda configure_region: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda configure_claude, **kw: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-ssh"])

        assert result.exit_code == 0
        assert "Currently configured:" in result.output
        assert "Git identity" in result.output
        assert "Existing User <existing@example.com>" in result.output

    def test_devbox_start_creates_workspace_with_default_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0
        assert captured == {
            "name": "devbox-test-user",
            "disk_size": "100",
            "git_name": None,
            "git_email": None,
            "dotfiles_uri": None,
            "region": coder.DEFAULT_REGION,
            "template": coder.DEFAULT_TEMPLATE,
            "preset": coder.DEFAULT_PRESET,
            "start_app": "None",
        }

    def test_devbox_start_with_name_creates_labeled_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "resolve_workspace_name",
            lambda ws, **kw: (f"devbox-test-user-{ws}" if ws else "devbox-test-user", []),
        )
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: "api")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
        )
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "api"])

        assert result.exit_code == 0
        assert captured["name"] == "devbox-test-user-api"
        assert captured["git_name"] == "PostHog Engineer"
        assert captured["git_email"] == "test-user@example.com"
        assert captured["dotfiles_uri"] == "https://github.com/user/dotfiles"
        assert captured["region"] == coder.DEFAULT_REGION
        assert captured["template"] == coder.DEFAULT_TEMPLATE
        assert captured["preset"] == coder.DEFAULT_PRESET
        assert "devbox:ssh api" in result.output

    def test_devbox_start_forwards_template_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "-t", "posthog-microvm"])

        assert result.exit_code == 0, result.output
        assert captured["template"] == "posthog-microvm"
        assert captured["preset"] == coder.DEFAULT_PRESET

    def test_devbox_start_forwards_preset_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "--preset", "none"])

        assert result.exit_code == 0, result.output
        assert captured["preset"] == "none"

    def test_devbox_start_forwards_region_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "--region", "eu-central-1"])

        assert result.exit_code == 0, result.output
        assert captured["region"] == "eu-central-1"
        assert "region=eu-central-1" in result.output

    @pytest.mark.parametrize(
        "flag, expected",
        [("--start-app", "True"), ("--no-start-app", "False")],
        ids=["enable", "disable"],
    )
    def test_devbox_start_forwards_start_app_flag(
        self, monkeypatch: pytest.MonkeyPatch, flag: str, expected: str
    ) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", flag])

        assert result.exit_code == 0, result.output
        assert captured["start_app"] == expected

    def test_devbox_start_rejects_unknown_region(self) -> None:
        # click.Choice rejects the value during option parsing, before the
        # command body runs, so no runtime collaborators need stubbing.
        result = runner.invoke(cli, ["devbox:start", "--region", "ap-southeast-2"])

        assert result.exit_code != 0
        assert "ap-southeast-2" in result.output

    def test_devbox_start_defaults_to_saved_region(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path
    ) -> None:
        """When no --region is given, devbox:start should honor the saved preference."""
        devbox_config.save_region("eu-central-1")

        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        # Real resolve_workspace_name so the -eu suffix gets applied.
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0, result.output
        assert captured["region"] == "eu-central-1"
        assert captured["name"] == "devbox-test-user-eu"
        assert "region=eu-central-1" in result.output

    def test_devbox_start_explicit_region_overrides_saved_preference(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path
    ) -> None:
        """An explicit --region flag should win over the saved preference for both region and name."""
        devbox_config.save_region("us-east-1")

        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "--region", "eu-central-1"])

        assert result.exit_code == 0, result.output
        assert captured["region"] == "eu-central-1"
        assert captured["name"] == "devbox-test-user-eu"

    @pytest.mark.parametrize(
        "saved_region, boxes, expected_resumed, expected_hint",
        [
            (None, ["devbox-test-user"], "devbox-test-user", None),
            (None, ["devbox-test-user-eu"], "devbox-test-user-eu", None),
            (
                "eu-central-1",
                ["devbox-test-user"],
                "devbox-test-user",
                "hogli devbox:start --region eu-central-1",
            ),
            (
                "eu-central-1",
                ["devbox-test-user", "devbox-test-user-api"],
                "devbox-test-user",
                "hogli devbox:start --region eu-central-1",
            ),
        ],
        ids=["matching-region", "other-region-no-pref", "other-region-with-pref", "multi-box-other-region-default"],
    )
    def test_devbox_start_bare_resumes_existing_box(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        saved_region: str | None,
        boxes: list[str],
        expected_resumed: str,
        expected_hint: str | None,
    ) -> None:
        """A bare start resumes the box the user has -- a saved pref alone never abandons it.

        When the resumed default is outside the saved pref, a hint says how to
        create one there explicitly; otherwise no hint is printed.
        """
        if saved_region is not None:
            devbox_config.save_region(saved_region)

        captured: dict[str, str | None] = {}
        resumed: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": name, "latest_build": {"status": "stopped"}} for name in boxes],
        )
        monkeypatch.setattr(
            devbox_cli,
            "_start_existing_workspace",
            lambda name, ws, start_app=None, verbose=False: resumed.append(name),
        )
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0, result.output
        assert resumed == [expected_resumed]
        assert captured == {}
        if expected_hint is None:
            assert "--region" not in result.output
        else:
            assert expected_hint in result.output

    @pytest.mark.parametrize(
        "existing_boxes",
        [
            ["devbox-test-user"],
            ["devbox-test-user", "devbox-test-user-api"],
        ],
        ids=["single-box", "multiple-boxes"],
    )
    def test_devbox_start_explicit_region_creates_default_alongside_existing_boxes(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path, existing_boxes: list[str]
    ) -> None:
        """`--region` targets that region's default directly, creating it even when other boxes exist."""
        captured: dict[str, str | None] = {}
        resumed: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": name, "latest_build": {"status": "stopped"}} for name in existing_boxes],
        )
        monkeypatch.setattr(
            devbox_cli,
            "_start_existing_workspace",
            lambda name, ws, start_app=None, verbose=False: resumed.append(name),
        )
        monkeypatch.setattr(devbox_cli, "create_workspace", _stub_create_workspace(captured))

        result = runner.invoke(cli, ["devbox:start", "--region", "eu-central-1"])

        assert result.exit_code == 0, result.output
        assert resumed == []
        assert captured["name"] == "devbox-test-user-eu"
        assert captured["region"] == "eu-central-1"

    def test_devbox_restart_calls_restart_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(
            devbox_cli,
            "restart_workspace",
            lambda name, verbose=False: captured.update({"name": name, "verbose": verbose}),
        )

        result = runner.invoke(cli, ["devbox:restart"])

        assert result.exit_code == 0
        assert "Restarting" in result.output
        assert captured["name"] == "devbox-test-user"

    def test_devbox_update_applies_when_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "outdated": True, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {"dotfiles_uri": "https://github.com/user/dotfiles"})
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace",
            lambda name, parameters=None, verbose=False: captured.update({"name": name, "parameters": parameters}),
        )

        result = runner.invoke(cli, ["devbox:update"])

        assert result.exit_code == 0
        assert "Updating" in result.output
        assert captured["name"] == "devbox-test-user"
        assert captured["parameters"] == {"dotfiles_uri": "https://github.com/user/dotfiles"}

    def test_devbox_update_skips_when_up_to_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "outdated": False, "latest_build": {"status": "running"}},
        )

        result = runner.invoke(cli, ["devbox:update"])

        assert result.exit_code == 0
        assert "already up to date" in result.output

    def test_local_port_check_ignores_missing_ipv6_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ipv4_socket = MagicMock()
        ipv4_socket.__enter__.return_value = ipv4_socket

        ipv6_socket = MagicMock()
        ipv6_socket.__enter__.return_value = ipv6_socket
        ipv6_socket.bind.side_effect = OSError(errno.EAFNOSUPPORT, "Address family not supported")

        sockets = iter([ipv4_socket, ipv6_socket])
        monkeypatch.setattr(devbox_cli.socket, "socket", lambda *args, **kwargs: next(sockets))

        assert devbox_cli._local_port_is_available(8010) is True

    def test_devbox_status_shows_update_hint_when_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["devbox:status"])

        assert result.exit_code == 0
        assert "devbox:update" in result.output

    @pytest.mark.parametrize(
        "status, resources, expected",
        [
            (
                "running",
                [{"metadata": [{"key": "region", "value": "eu-central-1"}]}],
                "Region:  eu-central-1",
            ),
            ("stopped", [], "Region:  unknown"),
        ],
        ids=["region-present", "region-absent"],
    )
    def test_devbox_status_shows_region(
        self, monkeypatch: pytest.MonkeyPatch, status: str, resources: list, expected: str
    ) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"latest_build": {"status": status, "resources": resources}},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["devbox:status"])

        assert result.exit_code == 0
        assert expected in result.output

    def test_devbox_list_shows_region_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [
                {
                    "name": "devbox-test-user",
                    "latest_build": {
                        "status": "running",
                        "resources": [{"metadata": [{"key": "region", "value": "eu-central-1"}]}],
                    },
                },
                {"name": "devbox-test-user-api", "latest_build": {"status": "stopped", "resources": []}},
            ],
        )
        monkeypatch.setattr(devbox_cli, "list_shared_workspaces", lambda: [])
        monkeypatch.setattr(devbox_cli, "get_shared_users", lambda name: [])
        monkeypatch.setattr(
            devbox_cli,
            "extract_workspace_label",
            lambda name: None if name == "devbox-test-user" else "api",
        )

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "REGION" in result.output
        assert "eu-central-1" in result.output
        # The box without region metadata renders the unknown placeholder.
        assert "unknown" in result.output

    def test_devbox_forward_forwards_when_local_port_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: True)
        monkeypatch.setattr(
            devbox_cli,
            "port_forward_replace",
            lambda name, local_port, remote_port: captured.update(
                {"name": name, "local_port": local_port, "remote_port": remote_port}
            ),
        )

        result = runner.invoke(cli, ["devbox:forward"])

        assert result.exit_code == 0
        assert "Forwarding devbox-test-user:8010 -> localhost:8010" in result.output
        assert captured == {"name": "devbox-test-user", "local_port": 8010, "remote_port": 8010}

    def test_devbox_forward_fails_early_when_local_port_is_in_use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: False)

        result = runner.invoke(cli, ["devbox:forward", "--port", "8010"])

        assert result.exit_code == 1
        assert "Local port 8010 is already in use." in result.output
        assert "hogli devbox:forward --port 8011" in result.output


@pytest.fixture
def stub_setup_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op every external dependency in ``devbox_setup`` so reset/gate tests can run hermetically."""
    for name in (
        "ensure_tailscale_connected",
        "ensure_tailscale_routes_accepted",
        "ensure_coder_reachable",
        "ensure_coder_authenticated",
    ):
        monkeypatch.setattr(devbox_cli, name, lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda **kw: None)
    monkeypatch.setattr(devbox_cli, "_resolve_local_identity_agent_for_coder", lambda: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_git_identity", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_git_signing", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_region", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda *a, **kw: None)
    monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)
    monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
    monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
    monkeypatch.setattr(devbox_cli, "_confirm_run_setup", lambda: True)


@pytest.fixture
def stub_config_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the runtime guards that ``devbox:config:*`` commands call before doing work."""
    monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
    monkeypatch.setattr(devbox_cli, "_ensure_user_secrets_supported", lambda: None)
    monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
    monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])


class TestDevboxConfigCommands:
    """Cover the ``devbox:config:show`` and ``devbox:config:rm`` commands."""

    def test_show_reports_when_nothing_configured(
        self,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        result = runner.invoke(cli, ["devbox:config:show"])

        assert result.exit_code == 0
        assert "Nothing configured yet" in result.output

    def test_show_renders_saved_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config_path.write_text(
            json.dumps(
                {
                    "git_name": "PostHog Engineer",
                    "git_email": "engineer@example.com",
                    "dotfiles_uri": "https://github.com/user/dotfiles",
                }
            )
        )
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [{"name": coder.GIT_SIGNING_KEY_SECRET}])

        result = runner.invoke(cli, ["devbox:config:show"])

        assert result.exit_code == 0
        assert "Currently configured:" in result.output
        assert "PostHog Engineer <engineer@example.com>" in result.output
        assert "https://github.com/user/dotfiles" in result.output
        assert "Git signing" in result.output

    def test_rm_dotfiles_clears_config_and_pushes_empty_param_to_existing_workspaces(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-mobile"}],
        )
        param_pushes: list[tuple[str, dict[str, str]]] = []
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: param_pushes.append((name, params)),
        )

        result = runner.invoke(cli, ["devbox:config:rm", "dotfiles"])

        assert result.exit_code == 0, result.output
        assert devbox_config.load_config() == {}
        assert param_pushes == [
            ("devbox-test-user", {coder.DOTFILES_URI_PARAMETER: ""}),
            ("devbox-test-user-mobile", {coder.DOTFILES_URI_PARAMETER: ""}),
        ]
        assert "Cleared saved dotfiles repo" in result.output
        assert "Restart any running devbox" in result.output

    def test_rm_git_identity_clears_only_identity_keys(
        self,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "engineer@example.com")
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")

        result = runner.invoke(cli, ["devbox:config:rm", "git-identity"])

        assert result.exit_code == 0, result.output
        assert devbox_config.load_config() == {"dotfiles_uri": "https://github.com/user/dotfiles"}
        assert "Cleared saved Git identity" in result.output

    def test_rm_region_clears_only_region(
        self,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_git_identity("Eng", "eng@example.com")
        devbox_config.save_region("eu-central-1")

        result = runner.invoke(cli, ["devbox:config:rm", "region"])

        assert result.exit_code == 0, result.output
        assert devbox_config.load_config() == {"git_name": "Eng", "git_email": "eng@example.com"}
        assert "Cleared saved region preference" in result.output

    def test_show_renders_saved_region(
        self,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_region("eu-central-1")

        result = runner.invoke(cli, ["devbox:config:show"])

        assert result.exit_code == 0
        assert "Region" in result.output
        assert "eu-central-1" in result.output

    @pytest.mark.parametrize(
        "key,expected_secret",
        [
            ("git-signing", coder.GIT_SIGNING_KEY_SECRET),
            ("claude", coder.CLAUDE_CODE_OAUTH_ENV),
        ],
        ids=["git-signing", "claude"],
    )
    def test_rm_secret_keys_delete_the_right_coder_secret(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_config_runtime: None,
        key: str,
        expected_secret: str,
    ) -> None:
        deleted: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "delete_user_secret",
            lambda name: deleted.append(name) or subprocess.CompletedProcess(["coder"], 0, "", ""),
        )

        result = runner.invoke(cli, ["devbox:config:rm", key])

        assert result.exit_code == 0, result.output
        assert deleted == [expected_secret]

    def test_rm_multiple_keys_clears_each(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_git_identity("Eng", "eng@example.com")
        devbox_config.save_dotfiles_uri("https://x/y")
        deleted: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "delete_user_secret",
            lambda name: deleted.append(name) or subprocess.CompletedProcess(["coder"], 0, "", ""),
        )

        result = runner.invoke(cli, ["devbox:config:rm", "git-identity", "claude"])

        assert result.exit_code == 0, result.output
        assert devbox_config.load_config() == {"dotfiles_uri": "https://x/y"}
        assert deleted == [coder.CLAUDE_CODE_OAUTH_ENV]

    def test_rm_all_clears_every_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        devbox_config.save_git_identity("Eng", "eng@example.com")
        devbox_config.save_dotfiles_uri("https://x/y")
        deleted: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "delete_user_secret",
            lambda name: deleted.append(name) or subprocess.CompletedProcess(["coder"], 0, "", ""),
        )

        result = runner.invoke(cli, ["devbox:config:rm", "--all"])

        assert result.exit_code == 0, result.output
        assert devbox_config.load_config() == {}
        assert deleted == [coder.GIT_SIGNING_KEY_SECRET, coder.CLAUDE_CODE_OAUTH_ENV]

    def test_rm_with_no_args_fails_with_valid_keys_hint(self, stub_config_runtime: None) -> None:
        result = runner.invoke(cli, ["devbox:config:rm"])

        assert result.exit_code != 0
        assert "git-identity" in result.output
        assert "git-signing" in result.output
        assert "region" in result.output
        assert "dotfiles" in result.output
        assert "claude" in result.output

    def test_rm_with_unknown_key_fails_with_valid_keys_hint(self, stub_config_runtime: None) -> None:
        result = runner.invoke(cli, ["devbox:config:rm", "bogus"])

        assert result.exit_code != 0
        assert "Unknown key" in result.output
        assert "bogus" in result.output

    def test_rm_rejects_all_combined_with_positional_keys(self, stub_config_runtime: None) -> None:
        result = runner.invoke(cli, ["devbox:config:rm", "--all", "dotfiles"])

        assert result.exit_code != 0
        assert "--all" in result.output

    def test_rm_is_idempotent_for_already_empty_local_state(
        self,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        # No config file written and no secrets stubbed -- clearing should still succeed.
        result = runner.invoke(cli, ["devbox:config:rm", "dotfiles"])

        assert result.exit_code == 0, result.output
        assert "Nothing to clear: dotfiles was not set." in result.output
        # When nothing actually fired, the restart hint is misleading -- suppress it.
        assert "Restart any running devbox" not in result.output

    def test_rm_prints_restart_hint_only_when_something_actually_cleared(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
        stub_config_runtime: None,
    ) -> None:
        # Only dotfiles is set; the secret deletions report nothing-to-do.
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")
        monkeypatch.setattr(
            devbox_cli,
            "delete_user_secret",
            lambda name: subprocess.CompletedProcess(["coder"], 1, "", "not found"),
        )

        result = runner.invoke(cli, ["devbox:config:rm", "--all"])

        assert result.exit_code == 0, result.output
        # dotfiles fired -> hint present; the no-op secret deletions don't suppress it.
        assert "Cleared saved dotfiles repo" in result.output
        assert "Nothing to delete:" in result.output
        assert "Restart any running devbox" in result.output


class TestDevboxSetupGate:
    """Cover the Y/n gate at the top of ``hogli devbox:setup``."""

    def test_gate_bypassed_when_explicit_configure_flag_passed(
        self, monkeypatch: pytest.MonkeyPatch, stub_setup_environment: None
    ) -> None:
        gate_calls: list[None] = []
        monkeypatch.setattr(devbox_cli, "_confirm_run_setup", lambda: gate_calls.append(None) or True)

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-ssh"])

        assert result.exit_code == 0
        assert gate_calls == []

    def test_gate_shown_when_no_flags_and_aborts_on_no(
        self, monkeypatch: pytest.MonkeyPatch, stub_setup_environment: None
    ) -> None:
        monkeypatch.setattr(devbox_cli, "_confirm_run_setup", lambda: False)
        configure_calls: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_git_identity",
            lambda *a, **kw: configure_calls.append("git"),
        )

        result = runner.invoke(cli, ["devbox:setup"])

        assert result.exit_code == 0
        assert configure_calls == []
        assert "Aborted" in result.output

    def test_gate_helper_returns_true_when_stdin_is_not_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(
            devbox_cli.click,
            "confirm",
            lambda *a, **kw: pytest.fail("click.confirm must not be called when stdin is not a TTY"),
        )

        assert devbox_cli._confirm_run_setup() is True


class TestStartExistingWorkspace:
    """Test workspace parameter sync when starting an existing workspace."""

    def test_syncs_workspace_parameters_before_starting_stopped_workspace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        captured_params: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
        )

        def fake_update(name: str, params: dict[str, str]) -> None:
            calls.append("update_params")
            captured_params.update({"name": name, "params": params})

        monkeypatch.setattr(devbox_cli, "update_workspace_parameters", fake_update)
        monkeypatch.setattr(
            devbox_cli,
            "start_workspace",
            lambda name, verbose=False: calls.append("start"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "stopped"}}, verbose=False)

        assert calls == ["update_params", "start"]
        assert captured_params == {
            "name": "devbox-test-user",
            "params": {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
        }

    def test_skips_sync_when_no_git_identity_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: calls.append("update_params"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "start_workspace",
            lambda name, verbose=False: calls.append("start"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "stopped"}}, verbose=False)

        assert calls == ["start"]

    @pytest.mark.parametrize(
        "start_app, expected",
        [(True, "true"), (False, "false"), (None, None)],
        ids=["enable", "disable", "omit"],
    )
    def test_pushes_start_app_param_before_starting(
        self, monkeypatch: pytest.MonkeyPatch, start_app: bool | None, expected: str | None
    ) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: captured.update(params),
        )
        monkeypatch.setattr(devbox_cli, "start_workspace", lambda name, verbose=False: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace(
            "devbox-test-user",
            {"latest_build": {"status": "stopped"}},
            start_app=start_app,
            verbose=False,
        )

        if expected is None:
            assert coder.AUTO_START_APP_PARAMETER not in captured
        else:
            assert captured == {coder.AUTO_START_APP_PARAMETER: expected}

    @pytest.mark.parametrize("status", ["running", "starting", "stopping"])
    def test_start_app_flag_never_pushed_unless_stopped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], status: str
    ) -> None:
        """`coder update` stops a running workspace, so the flag must only note, never push."""
        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: status)
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: pytest.fail("update_workspace_parameters must not run unless stopped"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace(
            "devbox-test-user", {"latest_build": {"status": status}}, start_app=True, verbose=False
        )

        assert "was not applied" in capsys.readouterr().out

    def test_sync_never_forwards_immutable_workspace_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pre-start sync must omit `workspace_region`.

        It is immutable; Coder carries it forward on its own and rejects any
        explicit value on `coder update` with "parameter is immutable and
        cannot be updated", which would break every resume of a region-aware
        box. Even for an eu-central-1 workspace, the region must not appear.
        """
        captured: dict[str, object] = {}
        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {"dotfiles_uri": "https://github.com/user/dotfiles"},
        )
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: captured.update({"name": name, "params": params}),
        )
        monkeypatch.setattr(devbox_cli, "start_workspace", lambda name, verbose=False: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        workspace = {
            "latest_build": {
                "status": "stopped",
                "resources": [{"metadata": [{"key": coder.REGION_METADATA_KEY, "value": "eu-central-1"}]}],
            },
        }
        devbox_cli._start_existing_workspace("devbox-test-user", workspace, verbose=False)

        assert captured["params"] == {"dotfiles_uri": "https://github.com/user/dotfiles"}
        assert coder.WORKSPACE_REGION_PARAMETER not in captured["params"]

    def test_skips_sync_for_running_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "running")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {"git_name": "PostHog Engineer", "git_email": "test-user@example.com"},
        )
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: calls.append("update_params"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "running"}}, verbose=False)

        assert calls == []


class TestDevboxList:
    """Test the devbox:list command."""

    def test_devbox_list_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        monkeypatch.setattr(devbox_cli, "list_shared_workspaces", lambda: [])

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "No devboxes found" in result.output

    def test_devbox_list_shows_workspaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: "api" if "api" in name else None)
        monkeypatch.setattr(devbox_cli, "list_shared_workspaces", lambda: [])
        monkeypatch.setattr(devbox_cli, "get_shared_users", lambda name: [])
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [
                {"name": "devbox-test-user", "latest_build": {"status": "running"}},
                {"name": "devbox-test-user-api", "latest_build": {"status": "stopped"}},
            ],
        )

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "(default)" in result.output
        assert "api" in result.output
        assert "devbox-test-user-api" in result.output

    def test_devbox_list_shows_shared_workspaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        monkeypatch.setattr(
            devbox_cli,
            "list_shared_workspaces",
            lambda: [
                {
                    "name": "devbox-alice",
                    "latest_build": {"status": "running"},
                    "owner_name": "alice",
                },
            ],
        )

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "Shared with you" in result.output
        assert "devbox-alice" in result.output
        assert "from alice" in result.output


class TestWorkspaceTargetParsing:
    """Test @user workspace target resolution."""

    @pytest.mark.parametrize(
        "target, expected",
        [
            ("@alice", "devbox-alice"),
            ("@alice/ml-lab", "devbox-alice-ml-lab"),
            ("@bob/test", "devbox-bob-test"),
        ],
    )
    def test_parse_workspace_target_shared(self, monkeypatch: pytest.MonkeyPatch, target: str, expected: str) -> None:
        assert coder.parse_workspace_target(target) == expected

    def test_parse_workspace_target_own_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.parse_workspace_target("api") == "devbox-test-user-api"


class TestDevboxShare:
    """Test the devbox:share command."""

    def test_share_grants_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(
            devbox_cli,
            "share_workspace",
            lambda name, users, role="use": captured.update({"name": name, "users": users, "role": role}),
        )

        result = runner.invoke(cli, ["devbox:share", "--user", "alice"])

        assert result.exit_code == 0
        assert captured == {"name": "devbox-test-user", "users": ["alice"], "role": "use"}
        assert "Shared" in result.output
        assert "alice" in result.output

    def test_unshare_revokes_and_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(
            devbox_cli,
            "unshare_workspace",
            lambda name, users: captured.update({"name": name, "users": users}),
        )

        result = runner.invoke(cli, ["devbox:unshare", "--user", "alice"])

        assert result.exit_code == 0
        assert captured == {"name": "devbox-test-user", "users": ["alice"]}
        assert "Revoked" in result.output
        assert "Restart" in result.output

    def test_unshare_without_user_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )

        result = runner.invoke(cli, ["devbox:unshare"])

        assert result.exit_code != 0
        assert "--user" in result.output

    def test_unshare_with_positional_username_hints_to_use_user_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)

        result = runner.invoke(cli, ["devbox:unshare", "georgesa"])

        assert result.exit_code != 0
        assert "--user georgesa" in result.output

    def test_share_list_shows_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(
            devbox_cli,
            "get_sharing_status",
            lambda name: subprocess.CompletedProcess([], 0, "alice  use\nbob  admin\n", ""),
        )

        result = runner.invoke(cli, ["devbox:share", "--list"])

        assert result.exit_code == 0
        assert "alice" in result.output
        assert "bob" in result.output

    def test_share_without_user_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )

        result = runner.invoke(cli, ["devbox:share"])

        assert result.exit_code != 0
        assert "--user" in result.output

    def test_share_with_positional_username_hints_to_use_user_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)

        result = runner.invoke(cli, ["devbox:share", "georgesa"])

        assert result.exit_code != 0
        assert "--user georgesa" in result.output


class TestSharingFunctions:
    """Test coder.py sharing subprocess wrappers."""

    def test_share_workspace_builds_correct_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_args: list[str] = []

        def fake_run(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            captured_args.extend(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run", fake_run)

        coder.share_workspace("devbox-test-user", ["alice", "bob"], role="admin")
        assert captured_args == ["coder", "sharing", "share", "devbox-test-user", "--user", "alice:admin,bob:admin"]

    def test_list_shared_workspaces_parses_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ws_data = [{"name": "devbox-alice", "latest_build": {"status": "running"}}]
        monkeypatch.setattr(
            coder,
            "_run",
            lambda args, capture_output=False: subprocess.CompletedProcess(args, 0, json.dumps(ws_data), ""),
        )

        result = coder.list_shared_workspaces()
        assert len(result) == 1
        assert result[0]["name"] == "devbox-alice"


class TestServerSupportsUserSecrets:
    """Test the >=2.33 gate for Coder user secrets."""

    @pytest.mark.parametrize(
        "version, expected",
        [
            ("2.32.5", False),
            ("2.33.0", True),
            ("2.33.1", True),
            ("3.0.0", True),
            ("2.33.0-rc1", True),
            ("1.0.0", False),
        ],
    )
    def test_version_gate(self, monkeypatch: pytest.MonkeyPatch, version: str, expected: bool) -> None:
        monkeypatch.setattr(coder, "get_server_version", lambda: version)
        assert coder.server_supports_user_secrets() is expected

    def test_returns_false_when_version_undetermined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> str:
            raise RuntimeError("offline")

        monkeypatch.setattr(coder, "get_server_version", boom)
        assert coder.server_supports_user_secrets() is False


class TestCoderUserSecrets:
    """Test the coder.py wrappers around `coder secret list/create/delete`."""

    def test_list_user_secrets_parses_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = [{"name": "CLAUDE_CODE_OAUTH_TOKEN", "env_name": "CLAUDE_CODE_OAUTH_TOKEN"}]
        monkeypatch.setattr(
            coder,
            "_run",
            lambda args, capture_output=False: subprocess.CompletedProcess(args, 0, json.dumps(payload), ""),
        )
        secrets = coder.list_user_secrets()
        assert secrets is not None
        assert secrets[0]["name"] == "CLAUDE_CODE_OAUTH_TOKEN"

    def test_list_user_secrets_returns_none_on_cli_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            coder,
            "_run",
            lambda args, capture_output=False: subprocess.CompletedProcess(args, 1, "", "unsupported"),
        )
        assert coder.list_user_secrets() is None

    def test_has_claude_oauth_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "list_user_secrets", lambda: [{"name": "CLAUDE_CODE_OAUTH_TOKEN"}])
        assert coder.has_claude_oauth_secret() is True
        monkeypatch.setattr(coder, "list_user_secrets", lambda: [{"name": "OTHER"}])
        assert coder.has_claude_oauth_secret() is False
        monkeypatch.setattr(coder, "list_user_secrets", lambda: None)
        assert coder.has_claude_oauth_secret() is False

    def test_delete_user_secret_passes_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []

        def fake_run(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run", fake_run)
        coder.delete_user_secret("CLAUDE_CODE_OAUTH_TOKEN")
        assert captured == [["coder", "secret", "delete", "CLAUDE_CODE_OAUTH_TOKEN", "--yes"]]


class TestSetupRegion:
    """Test the region-preference step in devbox:setup."""

    def test_skip_flag_short_circuits(self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path) -> None:
        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_region(False)

        assert any("Skipping region" in line for line in echoed)
        assert devbox_config.load_config().get("region") is None

    def test_skip_flag_silent_when_already_set(self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path) -> None:
        devbox_config.save_region("eu-central-1")
        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_region(False)

        # The compact status block at the top of devbox_setup owns the
        # "already set" line, so this helper stays silent.
        assert echoed == []
        assert devbox_config.load_config()["region"] == "eu-central-1"

    def test_skips_when_region_already_saved_and_no_explicit_flag(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path
    ) -> None:
        devbox_config.save_region("eu-central-1")
        prompts: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: prompts.append("called") or "")

        devbox_cli.maybe_configure_region(None)

        assert prompts == []

    def test_prompts_and_persists_when_unset(self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path) -> None:
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: "eu-central-1")

        devbox_cli.maybe_configure_region(None)

        assert devbox_config.load_config()["region"] == "eu-central-1"

    def test_explicit_configure_flag_reprompts_even_when_set(
        self, monkeypatch: pytest.MonkeyPatch, devbox_config_path: Path
    ) -> None:
        devbox_config.save_region("us-east-1")
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: "eu-central-1")

        devbox_cli.maybe_configure_region(True)

        assert devbox_config.load_config()["region"] == "eu-central-1"


class TestSetupClaudeSecret:
    """Test the Claude user-secret step in devbox:setup."""

    def test_skips_when_server_does_not_support_user_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: False)

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)
        assert any("older than 2.33" in line for line in echoed)

    def test_skips_silently_when_secret_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The compact status block at the top of devbox_setup now owns the
        # "Claude token: configured" line, so this helper returns silently on
        # the already-set path rather than re-stating the same info.
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: True)

        upserts: list[tuple[str, str]] = []
        monkeypatch.setattr(devbox_cli, "upsert_user_secret", lambda name, value, **kw: upserts.append((name, value)))
        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)
        assert upserts == []
        assert echoed == []

    def test_skip_flag_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)

        called: list[str] = []
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: called.append("listed") or False)

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(False)
        assert any("Skipping" in line for line in echoed)
        assert called == []

    def test_migrates_legacy_keychain_token_into_user_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: False)
        monkeypatch.setattr(devbox_cli, "_read_legacy_keychain_token", lambda: "legacy-token")
        monkeypatch.setattr(devbox_cli.click, "confirm", lambda *a, **kw: True)

        deleted: list[bool] = []
        monkeypatch.setattr(devbox_cli, "_delete_legacy_keychain_token", lambda: deleted.append(True) or True)

        upserts: list[tuple[str, str]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, **kw: upserts.append((name, value)),
        )

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)

        assert upserts == [("CLAUDE_CODE_OAUTH_TOKEN", "legacy-token")]
        assert deleted == [True]

    def test_fresh_setup_creates_secret_from_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: False)
        monkeypatch.setattr(devbox_cli, "_read_legacy_keychain_token", lambda: None)
        monkeypatch.setattr(devbox_cli.click, "pause", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "echo", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: "fresh-token")

        upserts: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, **kw: upserts.append(value),
        )

        devbox_cli.maybe_configure_claude_secret(None)
        assert upserts == ["fresh-token"]

    def test_empty_prompt_skips_create(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: False)
        monkeypatch.setattr(devbox_cli, "_read_legacy_keychain_token", lambda: None)
        monkeypatch.setattr(devbox_cli.click, "pause", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "echo", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: "")

        called: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda *a, **kw: called.append("upsert"),
        )

        devbox_cli.maybe_configure_claude_secret(None)
        assert called == []


class TestDevboxTaskClaudeWarning:
    """Test the Claude-secret warning printed by devbox:task."""

    def test_warns_when_secret_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: False)
        monkeypatch.setattr(devbox_cli, "create_task", lambda *a, **kw: None)

        result = runner.invoke(cli, ["devbox:task", "do something"])

        assert result.exit_code == 0
        assert "no 'CLAUDE_CODE_OAUTH_TOKEN' Coder user secret set" in result.output

    def test_no_warning_when_secret_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: True)
        monkeypatch.setattr(devbox_cli, "create_task", lambda *a, **kw: None)

        result = runner.invoke(cli, ["devbox:task", "do something"])

        assert result.exit_code == 0
        assert "no 'CLAUDE_CODE_OAUTH_TOKEN' Coder user secret set" not in result.output

    def test_no_warning_when_server_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: False)
        called: list[bool] = []
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: called.append(True) or False)
        monkeypatch.setattr(devbox_cli, "create_task", lambda *a, **kw: None)

        result = runner.invoke(cli, ["devbox:task", "do something"])

        assert result.exit_code == 0
        assert called == []


class TestDevboxSecretCommands:
    """Test the devbox:secret:list / set / rm wrappers."""

    def test_secret_list_renders_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(
            devbox_cli,
            "list_user_secrets",
            lambda: [
                {"name": "CLAUDE_CODE_OAUTH_TOKEN", "env_name": "CLAUDE_CODE_OAUTH_TOKEN", "description": "claude"},
                {"name": "GH_TOKEN", "env_name": "GH_TOKEN", "description": "github"},
            ],
        )

        result = runner.invoke(cli, ["devbox:secret:list"])
        assert result.exit_code == 0
        assert "CLAUDE_CODE_OAUTH_TOKEN" in result.output
        assert "GH_TOKEN" in result.output

    def test_secret_list_fails_on_old_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: False)

        result = runner.invoke(cli, ["devbox:secret:list"])
        assert result.exit_code != 0
        assert "does not support user secrets" in result.output

    def test_secret_set_upserts_from_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        captured: dict[str, object] = {}

        def fake_upsert(name: str, value: str, *, env_name=None, description=None) -> None:
            captured["name"] = name
            captured["value"] = value
            captured["env_name"] = env_name

        monkeypatch.setattr(devbox_cli, "upsert_user_secret", fake_upsert)

        result = runner.invoke(cli, ["devbox:secret:set", "GH_TOKEN"], input="ghp-value\nghp-value\n")

        assert result.exit_code == 0
        assert captured == {"name": "GH_TOKEN", "value": "ghp-value", "env_name": "GH_TOKEN"}

    def test_secret_set_reads_value_from_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        source = tmp_path / "secret.txt"
        source.write_text("file-value\n")  # trailing newline must be stripped

        captured: dict[str, object] = {}
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, **kw: captured.update({"name": name, "value": value}),
        )

        result = runner.invoke(cli, ["devbox:secret:set", "GH_TOKEN", "--file", str(source)])
        assert result.exit_code == 0, result.output
        assert captured == {"name": "GH_TOKEN", "value": "file-value"}

    def test_secret_rm_calls_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)

        captured: list[str] = []

        def fake_delete(name: str) -> subprocess.CompletedProcess[str]:
            captured.append(name)
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(devbox_cli, "delete_user_secret", fake_delete)

        result = runner.invoke(cli, ["devbox:secret:rm", "GH_TOKEN"])
        assert result.exit_code == 0
        assert captured == ["GH_TOKEN"]


class TestCreateTask:
    """Test the coder task create argv assembly."""

    @pytest.mark.parametrize(
        "prompt, task_name, quiet, expected_tail",
        [
            ("fix CI on PR #1234", None, False, ["fix CI on PR #1234"]),
            (None, None, False, ["--stdin"]),
            ("do the thing", "my-task", True, ["--name", "my-task", "--quiet", "do the thing"]),
        ],
    )
    def test_create_task_argv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        prompt: str | None,
        task_name: str | None,
        quiet: bool,
        expected_tail: list[str],
    ) -> None:
        captured: list[list[str]] = []
        monkeypatch.setattr(coder, "_run_or_exit", lambda args: captured.append(args))

        coder.create_task(prompt, task_name=task_name, quiet=quiet)

        assert captured == [["coder", "task", "create", "--template", "posthog-linux", *expected_tail]]

    def test_create_task_argv_uses_selected_template(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []
        monkeypatch.setattr(coder, "_run_or_exit", lambda args: captured.append(args))

        coder.create_task("do it", template="posthog-microvm")

        assert captured == [["coder", "task", "create", "--template", "posthog-microvm", "do it"]]


class TestDevboxTaskCommand:
    """Test the devbox:task Click command."""

    @pytest.mark.parametrize(
        "cli_args, expected",
        [
            (
                ["devbox:task", "fix CI on PR #1234"],
                {"prompt": "fix CI on PR #1234", "task_name": None, "quiet": False, "template": "posthog-linux"},
            ),
            (
                ["devbox:task", "--name", "my-task", "-q", "do it"],
                {"prompt": "do it", "task_name": "my-task", "quiet": True, "template": "posthog-linux"},
            ),
            (
                ["devbox:task", "-t", "posthog-microvm", "do it"],
                {"prompt": "do it", "task_name": None, "quiet": False, "template": "posthog-microvm"},
            ),
            (
                ["devbox:task", "--template", "posthog-microvm", "do it"],
                {"prompt": "do it", "task_name": None, "quiet": False, "template": "posthog-microvm"},
            ),
        ],
    )
    def test_options_forwarded_to_create_task(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cli_args: list[str],
        expected: dict[str, object],
    ) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "create_task",
            lambda prompt, task_name=None, quiet=False, template="posthog-linux": captured.update(
                {"prompt": prompt, "task_name": task_name, "quiet": quiet, "template": template}
            ),
        )

        result = runner.invoke(cli, cli_args)

        assert result.exit_code == 0
        assert captured == expected

    def test_no_prompt_on_tty_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)

        class FakeTTY:
            def isatty(self) -> bool:
                return True

        monkeypatch.setattr(devbox_cli.click, "get_text_stream", lambda stream: FakeTTY())

        called: list[bool] = []
        monkeypatch.setattr(devbox_cli, "create_task", lambda *a, **kw: called.append(True))

        result = runner.invoke(cli, ["devbox:task"])

        assert result.exit_code != 0
        assert "Provide a prompt" in result.output
        assert called == []

    def test_piped_stdin_passes_none_as_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "create_task",
            lambda prompt, task_name=None, quiet=False, template="posthog-linux": captured.update(
                {"prompt": prompt, "task_name": task_name, "quiet": quiet, "template": template}
            ),
        )

        result = runner.invoke(cli, ["devbox:task"], input="piped prompt\n")

        assert result.exit_code == 0
        assert captured == {"prompt": None, "task_name": None, "quiet": False, "template": "posthog-linux"}


class TestResolveLocalSigningKey:
    """Test reading user.signingkey from the engineer's local git config."""

    def test_returns_literal_ssh_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "ssh-ed25519 AAAA user@host\n", ""),
        )
        assert devbox_cli._resolve_local_signing_key() == "ssh-ed25519 AAAA user@host"

    def test_strips_key_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                a[0], 0, "key::ecdsa-sha2-nistp256 AAAA GitHub-Commit-Signing@host\n", ""
            ),
        )
        assert devbox_cli._resolve_local_signing_key() == "ecdsa-sha2-nistp256 AAAA GitHub-Commit-Signing@host"

    def test_reads_file_when_value_is_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key_file = tmp_path / "id_ed25519.pub"
        key_file.write_text("ssh-ed25519 AAAAFROMFILE user@host\n")
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, str(key_file), ""),
        )
        assert devbox_cli._resolve_local_signing_key() == "ssh-ed25519 AAAAFROMFILE user@host"

    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", ""))
        assert devbox_cli._resolve_local_signing_key() is None

    def test_returns_none_when_path_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing = str(tmp_path / "absent.pub")
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, missing, ""),
        )
        assert devbox_cli._resolve_local_signing_key() is None


class TestResolveLocalIdentityAgent:
    """Test reading IdentityAgent from `ssh -G <host>`."""

    def test_returns_socket_path_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                a[0], 0, "host coder.dev\nidentityagent /tmp/agent.sock\nidentityfile ~/.ssh/id_ed25519\n", ""
            ),
        )
        assert devbox_cli._resolve_local_identity_agent("coder.dev") == "/tmp/agent.sock"

    def test_returns_none_for_placeholder_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "identityagent SSH_AUTH_SOCK\n", ""),
        )
        assert devbox_cli._resolve_local_identity_agent("coder.dev") is None

    def test_returns_none_for_none_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "identityagent none\n", ""),
        )
        assert devbox_cli._resolve_local_identity_agent("coder.dev") is None

    def test_returns_none_when_ssh_g_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 255, "", "Bad host"),
        )
        assert devbox_cli._resolve_local_identity_agent("coder.dev") is None


class TestConfigSshArgs:
    """Test the `coder config-ssh` argument builder.

    Two encoding layers in play, both have to round-trip:

    1. ``coder config-ssh --ssh-option`` is a cobra ``StringSlice``, so each
       value is CSV-parsed before coder uses it. A bare ``"`` in a non-quoted
       CSV field crashes coder's parser; the encoder wraps any value with
       quotes/commas so it survives.
    2. ``~/.ssh/config`` itself: an unquoted ``IdentityAgent`` path with
       spaces (1Password's ``~/Library/Group Containers/...``) makes ``ssh``
       reject the config with "extra arguments at end of line."

    The tests below assert the CSV-encoded value coder receives *and* the
    SSH form it decodes back to.
    """

    _SOCKET_WITH_SPACES = "/Users/me/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"

    @staticmethod
    def _ssh_option_values(args: list[str]) -> list[str]:
        return [args[i + 1] for i, a in enumerate(args) if a == "--ssh-option"]

    @staticmethod
    def _csv_decode(field: str) -> str:
        return next(csv.reader([field]))[0]

    def test_omits_identity_agent_when_socket_is_none(self) -> None:
        args = coder._config_ssh_args(identity_agent_socket=None)
        decoded = [self._csv_decode(v) for v in self._ssh_option_values(args)]
        assert decoded == ["ForwardAgent yes"]

    @pytest.mark.parametrize(
        "socket",
        [
            # 1Password's default path contains spaces; without quoting,
            # OpenSSH parses the trailing path components as "extra arguments"
            # and refuses to load the config file.
            "/Users/me/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock",
            "/tmp/agent.sock",
        ],
        ids=["spaces", "no-spaces"],
    )
    def test_identity_agent_socket_roundtrips_to_quoted_ssh_form(self, socket: str) -> None:
        args = coder._config_ssh_args(identity_agent_socket=socket)
        identity_option = next(v for v in self._ssh_option_values(args) if "IdentityAgent" in v)
        # After coder CSV-decodes it, ~/.ssh/config gets the SSH form -- an
        # IdentityAgent line with a quoted path. The quotes are what ssh needs
        # when the socket contains spaces; CSV encoding is what coder needs to
        # accept those quotes.
        assert self._csv_decode(identity_option) == f'IdentityAgent "{socket}"'


class TestEncodeSshOption:
    """Direct tests for the CSV-encoding helper backing `--ssh-option` values."""

    def test_plain_value_passes_through_unchanged(self) -> None:
        # QUOTE_MINIMAL only wraps fields that need it -- a plain option
        # should land as the literal string coder writes to the config.
        assert coder._encode_ssh_option("ForwardAgent yes") == "ForwardAgent yes"

    def test_value_with_embedded_quotes_is_csv_quoted_and_roundtrips(self) -> None:
        encoded = coder._encode_ssh_option('IdentityAgent "/path with space/sock"')
        # CSV-encoded: outer wrap + doubled internal quotes.
        assert encoded == '"IdentityAgent ""/path with space/sock"""'
        # And it round-trips through Go's CSV parser (which Python's csv module mirrors).
        assert next(csv.reader([encoded]))[0] == 'IdentityAgent "/path with space/sock"'

    def test_value_with_commas_is_csv_quoted(self) -> None:
        # Defensive: any SSH option containing the CSV delimiter must be quoted.
        encoded = coder._encode_ssh_option("ProxyCommand a,b")
        assert next(csv.reader([encoded]))[0] == "ProxyCommand a,b"


class TestSshReplace:
    """Verify devbox:ssh routes through the OpenSSH alias, not ``coder ssh``."""

    def test_host_alias_matches_coder_config_ssh_default(self) -> None:
        # `coder config-ssh` writes `Host coder.*` by default; the alias must match.
        assert coder._ssh_host_alias("devbox-foo") == "coder.devbox-foo"

    def test_execs_ssh_with_coder_host_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[tuple[str, list[str]]] = []
        monkeypatch.setattr(coder.os, "execvp", lambda file, args: captured.append((file, args)))

        coder.ssh_replace("devbox-foo")

        assert captured == [("ssh", ["ssh", coder._ssh_host_alias("devbox-foo")])]


class TestSetupGitSigning:
    """Test the Git commit signing step in devbox:setup.

    Identity-agent threading into ssh config is not the wizard's job -- the
    top-level ``devbox_setup`` resolves and applies it via ``ssh -G`` on every
    run. The wizard only writes the user secret.
    """

    PUBLIC_KEY = "ssh-ed25519 AAAAC3 user@host"
    AGENT_SOCKET = "/tmp/test-agent.sock"

    def _patch_local_config(self, monkeypatch: pytest.MonkeyPatch, *, key: str | None, agent: str | None) -> None:
        monkeypatch.setattr(devbox_cli, "_resolve_local_signing_key", lambda: key)
        monkeypatch.setattr(devbox_cli, "_resolve_local_identity_agent_for_coder", lambda: agent)

    def test_skips_when_secret_already_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "user_secret_exists", lambda name: True)
        upserts: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, env_name=None, description=None: upserts.append((name, value, env_name)),
        )

        devbox_cli.maybe_configure_git_signing(None)

        assert upserts == []

    def test_pushes_local_signing_key_to_user_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "user_secret_exists", lambda name: False)
        self._patch_local_config(monkeypatch, key=self.PUBLIC_KEY, agent=self.AGENT_SOCKET)
        upserts: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, env_name=None, description=None: upserts.append((name, value, env_name)),
        )

        devbox_cli.maybe_configure_git_signing(None)

        assert upserts == [(coder.GIT_SIGNING_KEY_SECRET, self.PUBLIC_KEY, coder.GIT_SIGNING_KEY_SECRET)]

    def test_explicit_reconfigure_overrides_existing_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "user_secret_exists", lambda name: True)
        self._patch_local_config(monkeypatch, key=self.PUBLIC_KEY, agent=self.AGENT_SOCKET)
        upserts: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, env_name=None, description=None: upserts.append((name, value, env_name)),
        )

        devbox_cli.maybe_configure_git_signing(True)

        assert upserts == [(coder.GIT_SIGNING_KEY_SECRET, self.PUBLIC_KEY, coder.GIT_SIGNING_KEY_SECRET)]

    def test_skips_when_signing_key_unset_locally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "user_secret_exists", lambda name: False)
        self._patch_local_config(monkeypatch, key=None, agent=None)
        upserts: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, env_name=None, description=None: upserts.append((name, value, env_name)),
        )

        devbox_cli.maybe_configure_git_signing(None)

        assert upserts == []

    def test_rejects_rsa_keys_per_handbook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "user_secret_exists", lambda name: False)
        self._patch_local_config(monkeypatch, key="ssh-rsa AAAAB3 old@host", agent=self.AGENT_SOCKET)
        upserts: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            devbox_cli,
            "upsert_user_secret",
            lambda name, value, env_name=None, description=None: upserts.append((name, value, env_name)),
        )

        devbox_cli.maybe_configure_git_signing(None)

        assert upserts == []


class TestMutagenReleaseUrl:
    """Test the platform -> mutagen release URL mapping."""

    @pytest.mark.parametrize(
        "system, machine, expected_suffix",
        [
            ("Darwin", "arm64", "mutagen_darwin_arm64_v0.18.1.tar.gz"),
            ("Darwin", "x86_64", "mutagen_darwin_amd64_v0.18.1.tar.gz"),
            ("Linux", "x86_64", "mutagen_linux_amd64_v0.18.1.tar.gz"),
            ("Linux", "aarch64", "mutagen_linux_arm64_v0.18.1.tar.gz"),
        ],
    )
    def test_url_per_platform(
        self, monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected_suffix: str
    ) -> None:
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: system)
        monkeypatch.setattr(devbox_mutagen.platform, "machine", lambda: machine)
        url = devbox_mutagen._mutagen_release_url()
        assert url.endswith(expected_suffix)
        assert url.startswith("https://github.com/mutagen-io/mutagen/releases/download/")

    def test_unsupported_os_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: "Windows")
        monkeypatch.setattr(devbox_mutagen.platform, "machine", lambda: "amd64")
        with pytest.raises(SystemExit):
            devbox_mutagen._mutagen_release_url()

    def test_unsupported_arch_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: "Linux")
        monkeypatch.setattr(devbox_mutagen.platform, "machine", lambda: "riscv64")
        with pytest.raises(SystemExit):
            devbox_mutagen._mutagen_release_url()


class TestMutagenInstall:
    """Test the install + version-pinning flow for the managed mutagen binary."""

    def _pin_platform(self, monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
        """Force a supported platform and pin its checksum to ``payload``'s hash."""
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: "Linux")
        monkeypatch.setattr(devbox_mutagen.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(
            devbox_mutagen, "_MUTAGEN_SHA256", {("linux", "amd64"): hashlib.sha256(payload).hexdigest()}
        )

    def test_install_verifies_checksum_then_extracts(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        managed = tmp_path / "bin"
        monkeypatch.setattr(devbox_mutagen, "_MANAGED_MUTAGEN_DIR", managed)
        payload = b"fake-mutagen-tarball"
        self._pin_platform(monkeypatch, payload)

        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if args[0] == "curl":
                out = Path(args[args.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)
            elif args[0] == "tar":
                (managed / "mutagen").touch()
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(devbox_mutagen.subprocess, "run", fake_run)

        devbox_mutagen._install_mutagen()

        # curl downloads first, tar extracts only after the checksum passes.
        assert [c[0] for c in calls] == ["curl", "tar"]
        assert "mutagen" in calls[1] and "mutagen-agents.tar.gz" in calls[1]
        assert (managed / "mutagen").is_file()
        # the downloaded tarball is cleaned up after extraction.
        assert not list(managed.glob("*.tar.gz"))

    def test_install_aborts_on_checksum_mismatch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        managed = tmp_path / "bin"
        monkeypatch.setattr(devbox_mutagen, "_MANAGED_MUTAGEN_DIR", managed)
        self._pin_platform(monkeypatch, b"expected")

        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if args[0] == "curl":
                out = Path(args[args.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"tampered")
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(devbox_mutagen.subprocess, "run", fake_run)

        with pytest.raises(SystemExit):
            devbox_mutagen._install_mutagen()

        # tar must never run on an unverified tarball, and nothing is left on disk.
        assert [c[0] for c in calls] == ["curl"]
        assert not (managed / "mutagen").exists()
        assert not list(managed.glob("*.tar.gz"))

    def test_install_fails_when_no_pinned_checksum(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(devbox_mutagen, "_MANAGED_MUTAGEN_DIR", tmp_path / "bin")
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: "Linux")
        monkeypatch.setattr(devbox_mutagen.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(devbox_mutagen, "_MUTAGEN_SHA256", {})

        ran: list[list[str]] = []
        monkeypatch.setattr(
            devbox_mutagen.subprocess,
            "run",
            lambda args, **kw: ran.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
        )

        with pytest.raises(SystemExit):
            devbox_mutagen._install_mutagen()
        assert ran == []  # bail before any download

    def test_install_fails_when_binary_missing_after_install(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        managed = tmp_path / "bin"
        monkeypatch.setattr(devbox_mutagen, "_MANAGED_MUTAGEN_DIR", managed)
        payload = b"valid-tarball"
        self._pin_platform(monkeypatch, payload)

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[0] == "curl":
                out = Path(args[args.index("-o") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)
            # tar reports success but extracts nothing.
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(devbox_mutagen.subprocess, "run", fake_run)

        with pytest.raises(SystemExit):
            devbox_mutagen._install_mutagen()

    def test_ensure_skips_install_when_version_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: True)
        monkeypatch.setattr(devbox_mutagen, "get_installed_mutagen_version", lambda: devbox_mutagen._MUTAGEN_VERSION)
        installed: list[bool] = []
        monkeypatch.setattr(devbox_mutagen, "_install_mutagen", lambda **kw: installed.append(True))

        devbox_mutagen.ensure_mutagen_installed()
        assert installed == []

    def test_ensure_reinstalls_on_version_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: True)
        monkeypatch.setattr(devbox_mutagen, "get_installed_mutagen_version", lambda: "0.17.0")
        installed: list[bool] = []
        monkeypatch.setattr(devbox_mutagen, "_install_mutagen", lambda **kw: installed.append(True))

        devbox_mutagen.ensure_mutagen_installed()
        assert installed == [True]

    def test_ensure_reinstalls_when_version_unreadable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Binary present but `mutagen version` fails (corrupt download) -> reinstall.
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: True)
        monkeypatch.setattr(devbox_mutagen, "get_installed_mutagen_version", lambda: None)
        installed: list[bool] = []
        monkeypatch.setattr(devbox_mutagen, "_install_mutagen", lambda **kw: installed.append(True))

        devbox_mutagen.ensure_mutagen_installed()
        assert installed == [True]


class TestMutagenSyncWrappers:
    """Test the thin subprocess wrappers around `mutagen sync ...`."""

    def test_sync_create_builds_one_way_safe_argv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        captured: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(devbox_mutagen, "_run", fake_run)

        config_path = tmp_path / "mutagen.yml"
        config_path.write_text("sync:\n")
        devbox_mutagen.sync_create(
            name="ph-devbox-test-user",
            src="/local",
            dst="coder.devbox-test-user:/home/coder/posthog",
            config_path=config_path,
            labels={"hogli-workspace": "devbox-test-user"},
        )

        assert len(captured) == 1
        args = captured[0]
        # Design invariant: never run in two-way modes. Local is source of truth.
        assert "--mode" in args and args[args.index("--mode") + 1] == "one-way-safe"
        assert "--ignore-vcs" in args
        assert "--name" in args and args[args.index("--name") + 1] == "ph-devbox-test-user"
        assert "--label" in args and args[args.index("--label") + 1] == "hogli-workspace=devbox-test-user"
        assert args[-2:] == ["/local", "coder.devbox-test-user:/home/coder/posthog"]

    def test_sync_list_returns_empty_when_mutagen_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: False)
        assert devbox_mutagen.sync_list(label_selector="hogli-workspace=devbox-test-user") == []

    def test_sync_list_parses_json_template_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: True)
        sessions = [{"name": "ph-devbox-test-user", "paused": False, "status": "watching"}]
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **kw: subprocess.CompletedProcess(args, 0, json.dumps(sessions), ""),
        )
        assert devbox_mutagen.sync_list(label_selector="hogli-workspace=devbox-test-user") == sessions

    def test_sync_list_returns_empty_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: True)
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "no sessions"),
        )
        assert devbox_mutagen.sync_list(label_selector="missing") == []

    def test_lifecycle_uses_label_selector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []
        # _label_op short-circuits when no session matches, so present one.
        monkeypatch.setattr(devbox_mutagen, "sync_list", lambda **kw: [{"name": "ph-x"}])
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **kw: captured.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
        )
        devbox_mutagen.sync_terminate("hogli-workspace=devbox-test-user")
        devbox_mutagen.sync_pause("hogli-workspace=devbox-test-user")
        devbox_mutagen.sync_resume("hogli-workspace=devbox-test-user")
        devbox_mutagen.sync_flush("hogli-workspace=devbox-test-user")
        verbs = [args[2] for args in captured]
        assert verbs == ["terminate", "pause", "resume", "flush"]
        for args in captured:
            assert "--label-selector" in args
            assert args[args.index("--label-selector") + 1] == "hogli-workspace=devbox-test-user"

    def test_terminate_swallows_no_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A session matches the precheck but vanishes before the op runs (race):
        # mutagen exits 1 with a "no sessions" message, which must be swallowed.
        monkeypatch.setattr(devbox_mutagen, "sync_list", lambda **kw: [{"name": "ph-x"}])
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "No sessions found"),
        )
        # Should not raise -- "no sessions" matching the selector is the expected
        # state when destroying a workspace without an active sync.
        devbox_mutagen.sync_terminate("hogli-workspace=missing")

    def test_label_op_noops_when_mutagen_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Lifecycle flags skip the install step, so a machine that never synced
        # must no-op rather than crash with FileNotFoundError from subprocess.
        monkeypatch.setattr(devbox_mutagen, "mutagen_installed", lambda: False)

        def fail_run(*a: object, **kw: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("_run must not be invoked when mutagen is absent")

        monkeypatch.setattr(devbox_mutagen, "_run", fail_run)
        # No exception, no subprocess.
        devbox_mutagen.sync_terminate("hogli-workspace=devbox-test-user")
        devbox_mutagen.sync_pause("hogli-workspace=devbox-test-user")


class TestKeepaliveShim:
    """Test the ssh keepalive shim that keeps sync alive across DERP path resets.

    mutagen hardcodes `-oServerAliveCountMax=1`; a single missed keepalive during
    a Tailscale path reset kills the sync. The shim rewrites the count upward and
    is wired into the daemon via MUTAGEN_SSH_PATH (see mutagen.py).
    """

    def test_run_injects_mutagen_ssh_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Any daemon mutagen auto-starts as a child of _run inherits this env --
        # the only channel that reaches the ssh-spawning daemon.
        captured: dict[str, object] = {}

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(devbox_mutagen.subprocess, "run", fake_run)
        monkeypatch.setattr(devbox_mutagen, "_mutagen_bin", lambda: "/x/mutagen")

        devbox_mutagen._run(["mutagen", "version"])

        env = captured["env"]
        assert isinstance(env, dict)
        assert env["MUTAGEN_SSH_PATH"] == str(devbox_mutagen._SSH_SHIM_DIR)

    @pytest.mark.parametrize(
        "target, bumped",
        [("coder.devbox-test-user", True), ("nobody@127.0.0.1", False)],
        ids=["devbox-host-bumped", "non-devbox-host-untouched"],
    )
    def test_shim_rewrites_keepalive_only_for_devbox_hosts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str, bumped: bool
    ) -> None:
        # End-to-end of the generated shim script: run it like mutagen would and
        # assert it bumps the keepalive ONLY for a coder.* (devbox) target, while
        # passing every other argument (and every non-devbox invocation) verbatim.
        shim_dir = tmp_path / "shim"
        log = tmp_path / "args.log"
        fake = tmp_path / "fakessh"
        fake.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > '" + str(log) + "'\n")
        fake.chmod(0o755)

        monkeypatch.setattr(devbox_mutagen, "_SSH_SHIM_DIR", shim_dir)
        monkeypatch.setattr(devbox_mutagen, "_resolve_real_ssh", lambda name: str(fake))
        devbox_mutagen.ensure_ssh_shim()

        incoming = [
            "-oConnectTimeout=5",
            "-oServerAliveInterval=10",
            "-oServerAliveCountMax=1",
            target,
            ".mutagen/agents/0.18.1/mutagen-agent",
            "synchronizer",
            "--log-level=info",
        ]
        result = subprocess.run([str(shim_dir / "ssh"), *incoming], capture_output=True, text=True)
        assert result.returncode == 0

        forwarded = log.read_text().splitlines()
        if bumped:
            bump = f"-oServerAliveCountMax={devbox_mutagen._KEEPALIVE_COUNT}"
            assert forwarded == [bump if a.startswith("-oServerAliveCountMax=") else a for a in incoming]
            assert "-oServerAliveCountMax=1" not in forwarded
        else:
            # Non-devbox ssh must pass through byte-for-byte, keepalive included.
            assert forwarded == incoming

    def test_ensure_ssh_shim_writes_both_executables_and_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        shim_dir = tmp_path / "shim"
        monkeypatch.setattr(devbox_mutagen, "_SSH_SHIM_DIR", shim_dir)
        monkeypatch.setattr(devbox_mutagen, "_resolve_real_ssh", lambda name: f"/usr/bin/{name}")

        devbox_mutagen.ensure_ssh_shim()
        ssh, scp = shim_dir / "ssh", shim_dir / "scp"
        assert ssh.exists() and scp.exists()
        # Owner-only: the daemon execs these, so no group/other access (0o700).
        assert ssh.stat().st_mode & 0o777 == 0o700
        assert scp.stat().st_mode & 0o777 == 0o700
        assert shim_dir.stat().st_mode & 0o077 == 0  # dir not group/other accessible
        assert f"-oServerAliveCountMax={devbox_mutagen._KEEPALIVE_COUNT}" in ssh.read_text()
        assert 'exec "/usr/bin/scp"' in scp.read_text()

        # Unchanged content must not rewrite the file (cheap, mtime-stable re-run).
        before = ssh.stat().st_mtime_ns
        devbox_mutagen.ensure_ssh_shim()
        assert ssh.stat().st_mtime_ns == before

    def test_write_owner_only_creates_0700_regardless_of_umask(self, tmp_path: Path) -> None:
        # The shim must be owner-only from creation, not via a post-write chmod
        # (which leaves a brief world-readable window). A permissive umask that
        # would make a plain write 0o666 must still yield 0o700.
        target = tmp_path / "ssh"
        old_umask = os.umask(0)
        try:
            devbox_mutagen._write_owner_only(target, "#!/bin/sh\n")
        finally:
            os.umask(old_umask)
        assert target.read_text() == "#!/bin/sh\n"
        assert target.stat().st_mode & 0o777 == 0o700
        assert not list(tmp_path.glob(".*.tmp"))  # temp renamed away, no leftover

    def test_resolve_real_ssh_never_returns_the_shim_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # A shim-dir ssh on PATH must never be picked, or the shim re-invokes
        # itself forever. Force the PATH fallback by hiding standard locations.
        shim_dir = tmp_path / "shim"
        shim_dir.mkdir()
        (shim_dir / "ssh").write_text("#!/bin/sh\n")
        monkeypatch.setattr(devbox_mutagen, "_SSH_SHIM_DIR", shim_dir)
        monkeypatch.setattr(devbox_mutagen.os.path, "isfile", lambda p: False)
        monkeypatch.setenv("PATH", str(shim_dir))

        # Only the shim dir is on PATH and it's excluded, so nothing resolves and
        # we fall back to the bare name -- crucially, never the shim's own ssh.
        assert devbox_mutagen._resolve_real_ssh("ssh") == "ssh"

    def test_daemon_uses_shim_matches_on_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(devbox_mutagen, "_daemon_pids", lambda: [111, 222])
        monkeypatch.setattr(
            devbox_mutagen,
            "_daemon_ssh_path",
            lambda pid: str(tmp_path) if pid == 222 else None,
        )
        assert devbox_mutagen._daemon_uses_shim(tmp_path) is True

        monkeypatch.setattr(devbox_mutagen, "_daemon_ssh_path", lambda pid: "/other")
        assert devbox_mutagen._daemon_uses_shim(tmp_path) is False

    @pytest.mark.parametrize(
        "ps_output, expected",
        [
            # `ps eww` env is space-delimited; a value with a space must not be
            # truncated, whether it's followed by another entry or ends the line.
            (
                "/Users/John Doe/.hogli/bin/mutagen daemon run "
                "XPC_SERVICE_NAME=0 MUTAGEN_SSH_PATH=/Users/John Doe/.hogli/mutagen-ssh-shim FOO=bar\n",
                "/Users/John Doe/.hogli/mutagen-ssh-shim",
            ),
            (
                "/x/mutagen daemon run MUTAGEN_SSH_PATH=/Users/John Doe/.hogli/mutagen-ssh-shim\n",
                "/Users/John Doe/.hogli/mutagen-ssh-shim",
            ),
            (
                "/x/mutagen daemon run MUTAGEN_SSH_PATH=/home/u/.hogli/mutagen-ssh-shim X=1\n",
                "/home/u/.hogli/mutagen-ssh-shim",
            ),
            ("/x/mutagen daemon run XPC_SERVICE_NAME=0\n", None),
        ],
        ids=["spaced-mid", "spaced-last", "plain", "absent"],
    )
    def test_daemon_ssh_path_parses_ps_env_with_spaces(
        self, monkeypatch: pytest.MonkeyPatch, ps_output: str, expected: str | None
    ) -> None:
        monkeypatch.setattr(devbox_mutagen.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            devbox_mutagen.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, ps_output, ""),
        )
        assert devbox_mutagen._daemon_ssh_path(123) == expected

    def test_ensure_daemon_fast_path_does_not_touch_daemon(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(devbox_mutagen, "ensure_ssh_shim", lambda: tmp_path)
        monkeypatch.setattr(devbox_mutagen, "_daemon_uses_shim", lambda d: True)

        def fail_run(*a: object, **k: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("daemon must not be reset when the shim is already active")

        monkeypatch.setattr(devbox_mutagen, "_run", fail_run)
        devbox_mutagen.ensure_daemon_with_shim()  # no exception, no daemon churn

    def test_ensure_daemon_resets_when_shim_inactive(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # A registered/launchd daemon's env can't carry the shim, so it must be
        # stopped, unregistered (so the restart forks an env-inheriting child),
        # then started fresh -- in that order.
        monkeypatch.setattr(devbox_mutagen, "ensure_ssh_shim", lambda: tmp_path)
        monkeypatch.setattr(devbox_mutagen, "_daemon_uses_shim", lambda d: False)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **k: calls.append(args[1:]) or subprocess.CompletedProcess(args, 0, "", ""),
        )

        devbox_mutagen.ensure_daemon_with_shim()

        assert calls == [["daemon", "stop"], ["daemon", "unregister"], ["daemon", "start"]]

    def test_ensure_daemon_warns_when_start_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(devbox_mutagen, "ensure_ssh_shim", lambda: tmp_path)
        monkeypatch.setattr(devbox_mutagen, "_daemon_uses_shim", lambda d: False)
        monkeypatch.setattr(
            devbox_mutagen,
            "_run",
            lambda args, **k: subprocess.CompletedProcess(args, 1, "", "boom"),
        )

        devbox_mutagen.ensure_daemon_with_shim()

        out = capsys.readouterr().out
        assert "keepalive shim" in out


class TestConflictCount:
    """Test that conflict counts include mutagen's truncated remainder."""

    @pytest.mark.parametrize(
        "session, expected",
        [
            # mutagen caps the inline list at 10 and reports the rest separately.
            ({"conflicts": [{}, {}], "excludedConflicts": 31}, 33),
            ({"conflicts": [], "excludedConflicts": 0}, 0),
            ({"conflicts": [{}]}, 1),  # no excludedConflicts key at all
            ({}, 0),
            ({"conflicts": [{}, {}], "excludedConflicts": "garbage"}, 2),  # falls back to shown
        ],
    )
    def test_sums_shown_and_excluded(self, session: dict, expected: int) -> None:
        assert devbox_mutagen.conflict_count(session) == expected


class TestWorkspaceLabels:
    """The create-side labels and the lookup-side selector must share one key."""

    def test_labels_and_selector_agree(self) -> None:
        labels = devbox_mutagen.workspace_labels("devbox-test-user")
        selector = devbox_mutagen.workspace_label_selector("devbox-test-user")
        assert labels == {"hogli-workspace": "devbox-test-user"}
        # Selector is exactly `key=value` for the single create-side label.
        ((key, value),) = labels.items()
        assert selector == f"{key}={value}"


class TestEnsureUserMutagenConfig:
    """Test that the user-side mutagen.yml is seeded from the packaged defaults."""

    def test_copies_defaults_when_absent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        target = tmp_path / "mutagen.yml"
        monkeypatch.setattr(devbox_mutagen, "_USER_CONFIG_PATH", target)

        result = devbox_mutagen.ensure_user_mutagen_config()

        assert result == target
        assert target.is_file()
        contents = target.read_text()
        assert "one-way-safe" in contents
        # Lockfiles must NOT be ignored -- they need to reach the devbox so the
        # AMI's prewarmed deps can be reconciled on next start.
        assert "pnpm-lock.yaml" not in contents
        assert "uv.lock" not in contents
        assert "Cargo.lock" not in contents
        # The worktree `.git` *file* must be ignored (`vcs: true` only catches the
        # `.git/` directory). The flox venv lives under `.flox/cache`, so only
        # flox's machine-local subdirs are ignored -- NOT all of `.flox` (that
        # would drop the tracked `.flox/env` definition) and NOT the
        # hand-maintained `common/hogql_parser` C++ sources.
        assert "'.git'" in contents
        assert "'.flox/cache'" in contents
        assert "\n                - '.flox'\n" not in contents
        assert "'common/hogql_parser'" not in contents

    def test_preserves_existing_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        target = tmp_path / "mutagen.yml"
        target.write_text("custom: contents\n")
        monkeypatch.setattr(devbox_mutagen, "_USER_CONFIG_PATH", target)

        devbox_mutagen.ensure_user_mutagen_config()

        assert target.read_text() == "custom: contents\n"

    def test_refreshes_unmodified_copy_when_defaults_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        target = tmp_path / "mutagen.yml"
        monkeypatch.setattr(devbox_mutagen, "_USER_CONFIG_PATH", target)
        devbox_mutagen.ensure_user_mutagen_config()
        original = target.read_text()

        # Simulate a shipped bump to the packaged defaults.
        new_defaults = tmp_path / "new_defaults.yml"
        new_defaults.write_text(original + "\n# new ignore added upstream\n")
        monkeypatch.setattr(devbox_mutagen, "_PACKAGED_DEFAULTS", new_defaults)

        devbox_mutagen.ensure_user_mutagen_config()
        # An untouched copy is refreshed in place rather than left stale.
        assert target.read_text() == original + "\n# new ignore added upstream\n"

    def test_does_not_clobber_user_edits_on_defaults_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        target = tmp_path / "mutagen.yml"
        monkeypatch.setattr(devbox_mutagen, "_USER_CONFIG_PATH", target)
        devbox_mutagen.ensure_user_mutagen_config()

        target.write_text("# my hand-tuned ignores\n")  # user edits their copy
        new_defaults = tmp_path / "new_defaults.yml"
        new_defaults.write_text("sync: {}\n# new ignore added upstream\n")
        monkeypatch.setattr(devbox_mutagen, "_PACKAGED_DEFAULTS", new_defaults)

        devbox_mutagen.ensure_user_mutagen_config()
        assert target.read_text() == "# my hand-tuned ignores\n"  # preserved


class TestDevboxSyncCommand:
    """Test the devbox:sync orchestrator."""

    def test_status_prints_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_sync.mutagen,
            "sync_list",
            lambda label_selector=None: [{"name": "ph-devbox-test-user", "status": "watching"}],
        )
        result = runner.invoke(cli, ["devbox:sync", "--status"])
        assert result.exit_code == 0, result.output
        assert "ph-devbox-test-user" in result.output

    def test_json_emits_summary_with_true_conflict_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_sync.mutagen,
            "sync_list",
            lambda label_selector=None: [
                {
                    "name": "ph-devbox-test-user",
                    "status": "watching",
                    "paused": False,
                    "conflicts": [{"root": "a.py"}, {"root": "b.py"}],
                    "excludedConflicts": 31,
                    "alpha": {"path": "/local"},
                    "beta": {"path": "coder.devbox-test-user:/home/coder/posthog"},
                }
            ],
        )
        result = runner.invoke(cli, ["devbox:sync", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert len(payload) == 1
        session = payload[0]
        # The whole point of the fix: 2 shown + 31 excluded, not a capped 2.
        assert session["conflicts"] == 33
        assert session["conflictPaths"] == ["a.py", "b.py"]
        assert session["state"] == "watching"
        assert session["beta"] == "coder.devbox-test-user:/home/coder/posthog"

    def test_json_rejects_lifecycle_combo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        result = runner.invoke(cli, ["devbox:sync", "--json", "--terminate"])
        assert result.exit_code != 0
        assert "json" in result.output.lower()

    def test_rejects_shared_at_user_target(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Syncing onto someone else's box would push your checkout over theirs;
        # the guard must fire before any resolution/create work.
        def boom(*a: object, **kw: object) -> tuple[str, None]:
            raise AssertionError("resolve_workspace_name must not run for @user targets")

        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", boom)
        result = runner.invoke(cli, ["devbox:sync", "@alice/api"])
        assert result.exit_code != 0
        assert "@user" in result.output or "own devboxes" in result.output

    def test_terminate_invokes_label_scoped_terminate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        captured: list[str] = []
        monkeypatch.setattr(devbox_sync.mutagen, "sync_terminate", lambda sel: captured.append(sel))

        result = runner.invoke(cli, ["devbox:sync", "--terminate"])

        assert result.exit_code == 0, result.output
        assert captured == ["hogli-workspace=devbox-test-user"]

    def test_default_run_is_idempotent_when_session_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        # The "inspect" hint calls _workspace_arg_suffix -> extract_workspace_label,
        # which shells out to `coder whoami`; stub it so the test is hermetic.
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_sync, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_mutagen_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_daemon_with_shim", lambda: None)
        monkeypatch.setattr(devbox_sync, "_ensure_ssh_config_for_workspace", lambda ws: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_user_mutagen_config", lambda: Path("/tmp/mutagen.yml"))
        monkeypatch.setattr(
            devbox_sync.mutagen,
            "sync_list",
            lambda label_selector=None: [{"name": "ph-devbox-test-user"}],
        )

        created: list[str] = []
        monkeypatch.setattr(devbox_sync.mutagen, "sync_create", lambda **kw: created.append(kw["name"]))

        result = runner.invoke(cli, ["devbox:sync"])

        assert result.exit_code == 0, result.output
        # Idempotent: don't recreate an existing session.
        assert created == []
        assert "Sync already running" in result.output

    def test_default_run_creates_one_way_sync(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(devbox_sync, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        # The "inspect" hint calls _workspace_arg_suffix -> extract_workspace_label,
        # which shells out to `coder whoami`; stub it so the test is hermetic.
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_sync, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_mutagen_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_daemon_with_shim", lambda: None)
        monkeypatch.setattr(devbox_sync, "_ensure_ssh_config_for_workspace", lambda ws: None)
        config_path = tmp_path / "mutagen.yml"
        config_path.write_text("sync: {}\n")
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_user_mutagen_config", lambda: config_path)
        monkeypatch.setattr(devbox_sync.mutagen, "sync_list", lambda label_selector=None: [])
        checkout = tmp_path / "posthog"
        checkout.mkdir()
        monkeypatch.setattr(devbox_sync, "_detect_local_posthog_checkout", lambda: checkout)

        captured: dict[str, object] = {}
        monkeypatch.setattr(
            devbox_sync.mutagen,
            "sync_create",
            lambda **kw: captured.update(kw),
        )

        result = runner.invoke(cli, ["devbox:sync"])

        assert result.exit_code == 0, result.output
        assert captured["name"] == "ph-devbox-test-user"
        assert captured["src"] == str(checkout)
        assert captured["dst"] == "coder.devbox-test-user:/home/coder/posthog"
        assert captured["labels"] == {"hogli-workspace": "devbox-test-user"}

    def test_default_run_fails_when_workspace_stopped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A stopped box passes the SSH-config check but mutagen can't dial it;
        # surface a clear error before creating the session.
        monkeypatch.setattr(
            devbox_sync,
            "resolve_workspace_name",
            lambda ws: ("devbox-test-user", [{"name": "devbox-test-user"}]),
        )
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_mutagen_installed", lambda **kw: None)
        monkeypatch.setattr(devbox_sync.mutagen, "ensure_daemon_with_shim", lambda: None)
        monkeypatch.setattr(devbox_sync.mutagen, "sync_list", lambda label_selector=None: [])
        monkeypatch.setattr(devbox_sync, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_sync, "get_workspace", lambda name, workspaces: {"name": name})
        monkeypatch.setattr(devbox_sync, "get_workspace_status", lambda ws: "stopped")
        created: list[str] = []
        monkeypatch.setattr(devbox_sync.mutagen, "sync_create", lambda **kw: created.append(kw["name"]))

        result = runner.invoke(cli, ["devbox:sync"])

        assert result.exit_code != 0
        assert "not running" in result.output
        assert created == []

    def test_status_surfaces_conflicts_and_error(self) -> None:
        rendered = devbox_sync._format_session_status(
            {"name": "ph-x", "status": "watching", "conflicts": [{}, {}], "lastError": "boom"}
        )
        assert "conflicts: 2" in rendered
        assert "boom" in rendered

    def test_detect_local_checkout_walks_up_from_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        checkout = tmp_path / "ph"
        (checkout / "subdir").mkdir(parents=True)
        (checkout / "hogli.yaml").write_text("")
        (checkout / ".git").mkdir()
        monkeypatch.chdir(checkout / "subdir")
        assert devbox_sync._detect_local_posthog_checkout() == checkout.resolve()

    def test_detect_local_checkout_fails_outside_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            devbox_sync._detect_local_posthog_checkout()

    def test_mutually_exclusive_lifecycle_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = runner.invoke(cli, ["devbox:sync", "--pause", "--resume"])
        assert result.exit_code != 0
        assert "at most one" in result.output


class TestDevboxLifecycleSyncIntegration:
    """Verify cli.py commands wire into mutagen sync at the right moments."""

    def test_destroy_terminates_sync_before_deleting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli.click, "confirm", lambda *a, **kw: True)
        monkeypatch.setattr(devbox_cli.mutagen, "sync_list", lambda label_selector=None: [{"name": "ph-x"}])
        monkeypatch.setattr(devbox_cli.mutagen, "sync_terminate", lambda sel: calls.append("terminate"))
        monkeypatch.setattr(devbox_cli, "delete_workspace", lambda name, verbose=False: calls.append("delete"))

        result = runner.invoke(cli, ["devbox:destroy"])

        assert result.exit_code == 0, result.output
        # terminate MUST run before delete: the remote endpoint disappearing
        # mid-sync produces noisy daemon errors otherwise.
        assert calls == ["terminate", "delete"]

    def test_destroy_proceeds_when_no_sync_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli.click, "confirm", lambda *a, **kw: True)
        monkeypatch.setattr(devbox_cli.mutagen, "sync_list", lambda label_selector=None: [])
        monkeypatch.setattr(
            devbox_cli.mutagen,
            "sync_terminate",
            lambda sel: calls.append("terminate"),
        )
        monkeypatch.setattr(devbox_cli, "delete_workspace", lambda name, verbose=False: calls.append("delete"))

        result = runner.invoke(cli, ["devbox:destroy"])

        assert result.exit_code == 0, result.output
        assert calls == ["delete"]

    def test_start_prints_sync_tip_when_no_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.mutagen, "sync_list", lambda label_selector=None: [])

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0, result.output
        assert "hogli devbox:sync" in result.output

    def test_start_omits_sync_tip_when_session_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws, **kw: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(devbox_cli, "create_workspace", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.mutagen, "sync_list", lambda label_selector=None: [{"name": "ph-x"}])

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0, result.output
        assert "Tip: run `hogli devbox:sync" not in result.output


class TestRenderSyncStatus:
    """Test the one-line sync-state summary shown in devbox:list / devbox:status."""

    def test_not_configured_when_no_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli.mutagen, "sync_list", lambda label_selector=None: [])
        assert "not configured" in devbox_cli._render_sync_status("devbox-test-user")

    def test_conflicts_render_as_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.mutagen,
            "sync_list",
            lambda label_selector=None: [{"status": "watching", "conflicts": [{}, {}]}],
        )
        assert "2 conflicts" in devbox_cli._render_sync_status("devbox-test-user")

    def test_halted_status_is_not_green_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.mutagen,
            "sync_list",
            lambda label_selector=None: [{"status": "halted-on-root-deletion"}],
        )
        rendered = devbox_cli._render_sync_status("devbox-test-user")
        assert "halted-on-root-deletion" in rendered
        assert "✗" in rendered

    def test_watching_status_is_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli.mutagen,
            "sync_list",
            lambda label_selector=None: [{"status": "watching"}],
        )
        rendered = devbox_cli._render_sync_status("devbox-test-user")
        assert "watching" in rendered
        assert "●" in rendered
