"""Tests for the hogli devbox commands."""

from __future__ import annotations

import json
import errno
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands.devbox import (
    cli as devbox_cli,
    coder,
    config as devbox_config,
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

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        assert "not installed" in capsys.readouterr().out


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
    """Test the Coder deployment reachability probe."""

    def test_coder_reachable_returns_false_on_request_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")

        def boom(*a: object, **kw: object) -> object:
            raise coder.requests.ConnectionError("blackholed")

        monkeypatch.setattr(coder.requests, "get", boom)
        assert coder.coder_reachable() is False

    def test_ensure_coder_reachable_fails_when_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_coder_url", lambda: "https://coder.example.com")
        monkeypatch.setattr(coder, "coder_reachable", lambda: False)
        with pytest.raises(SystemExit):
            coder.ensure_coder_reachable()


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


class TestWorkspaceCreation:
    """Test Coder workspace creation parameter passing."""

    def test_create_workspace_passes_git_identity_as_rich_parameters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["args"] = args
            captured["parameters"] = parameters
            captured["verbose"] = verbose
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace(
            "devbox-test-user",
            50,
            git_name="PostHog Engineer",
            git_email="test-user@example.com",
            verbose=True,
        )

        assert captured == {
            "args": ["coder", "create", "devbox-test-user", "--template", "posthog-linux", "--yes"],
            "parameters": {
                **coder._TEMPLATE_PARAMETER_DEFAULTS,
                "disk_size": "50",
                "repo": "https://github.com/PostHog/posthog",
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
            },
            "verbose": True,
        }

    def test_create_workspace_does_not_pass_claude_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["parameters"] = parameters
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace("devbox-test-user", 100, verbose=True)

        # The template no longer declares ``claude_oauth_token``; passing it would
        # cause Coder to reject the create call.
        assert "claude_oauth_token" not in captured["parameters"]

    def test_create_workspace_passes_dotfiles_uri_as_rich_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, dict[str, str]] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["parameters"] = parameters
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace(
            "devbox-test-user",
            100,
            dotfiles_uri="https://github.com/user/dotfiles",
            verbose=True,
        )

        assert captured["parameters"]["dotfiles_uri"] == "https://github.com/user/dotfiles"

    def test_create_workspace_includes_template_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, dict[str, str]] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["parameters"] = parameters
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace("devbox-test-user", 100, verbose=True)

        for key, value in coder._TEMPLATE_PARAMETER_DEFAULTS.items():
            assert captured["parameters"][key] == value


class TestResolveWorkspaceName:
    """Test the CLI workspace resolution logic."""

    def test_explicit_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        name, workspaces = devbox_cli.resolve_workspace_name("api")
        assert name == "devbox-test-user-api"
        assert workspaces is None

    def test_no_workspaces_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
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
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-api"}],
        )
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"
        assert len(workspaces) == 2

    def test_multiple_workspaces_no_default_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
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
            "maybe_configure_dotfiles",
            lambda configure_dotfiles: calls.append(f"dotfiles:{configure_dotfiles}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_claude_secret",
            lambda configure_claude: calls.append(f"claude:{configure_claude}"),
        )
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: calls.append("summary"))

        result = runner.invoke(
            cli,
            [
                "devbox:setup",
                "--skip-configure-ssh",
                "--skip-configure-git-identity",
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
            "dotfiles:False",
            "claude:False",
            "summary",
        ]

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
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda configure_claude: None)
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

    def test_devbox_setup_skips_git_identity_when_already_saved(
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
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh, **kw: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_secret", lambda configure_claude: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-ssh"])

        assert result.exit_code == 0
        assert "Using saved Git identity: Existing User <existing@example.com>" in result.output

    def test_devbox_start_creates_workspace_with_default_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(
            devbox_cli,
            "create_workspace",
            lambda name, disk_size, git_name=None, git_email=None, dotfiles_uri=None, verbose=False: captured.update(
                {
                    "name": name,
                    "disk_size": str(disk_size),
                    "git_name": git_name,
                    "git_email": git_email,
                    "dotfiles_uri": dotfiles_uri,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0
        assert captured == {
            "name": "devbox-test-user",
            "disk_size": "100",
            "git_name": None,
            "git_email": None,
            "dotfiles_uri": None,
        }

    def test_devbox_start_with_name_creates_labeled_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "resolve_workspace_name",
            lambda ws: (f"devbox-test-user-{ws}" if ws else "devbox-test-user", []),
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
        monkeypatch.setattr(
            devbox_cli,
            "create_workspace",
            lambda name, disk_size, git_name=None, git_email=None, dotfiles_uri=None, verbose=False: captured.update(
                {
                    "name": name,
                    "git_name": git_name,
                    "git_email": git_email,
                    "dotfiles_uri": dotfiles_uri,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start", "api"])

        assert result.exit_code == 0
        assert captured["name"] == "devbox-test-user-api"
        assert captured["git_name"] == "PostHog Engineer"
        assert captured["git_email"] == "test-user@example.com"
        assert captured["dotfiles_uri"] == "https://github.com/user/dotfiles"
        assert "devbox:ssh api" in result.output

    def test_devbox_restart_calls_restart_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["devbox:status"])

        assert result.exit_code == 0
        assert "devbox:update" in result.output

    def test_devbox_forward_forwards_when_local_port_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: False)

        result = runner.invoke(cli, ["devbox:forward", "--port", "8010"])

        assert result.exit_code == 1
        assert "Local port 8010 is already in use." in result.output
        assert "hogli devbox:forward --port 8011" in result.output


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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda ws: ("devbox-test-user", []))
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

    def test_create_user_secret_passes_env_and_file_with_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            file_index = args.index("--file") + 1
            captured["args"] = args
            captured["file_contents"] = Path(args[file_index]).read_text()
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run", fake_run)
        coder.create_user_secret(
            "CLAUDE_CODE_OAUTH_TOKEN",
            "secret-value",
            env_name="CLAUDE_CODE_OAUTH_TOKEN",
            description="Claude Code OAuth token (managed by hogli)",
        )

        args = captured["args"]
        assert args[:4] == ["coder", "secret", "create", "CLAUDE_CODE_OAUTH_TOKEN"]
        assert "--env" in args
        assert args[args.index("--env") + 1] == "CLAUDE_CODE_OAUTH_TOKEN"
        assert "--description" in args
        assert captured["file_contents"] == "secret-value"

    def test_delete_user_secret_passes_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []

        def fake_run(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run", fake_run)
        coder.delete_user_secret("CLAUDE_CODE_OAUTH_TOKEN")
        assert captured == [["coder", "secret", "delete", "CLAUDE_CODE_OAUTH_TOKEN", "--yes"]]


class TestSetupClaudeSecret:
    """Test the Claude user-secret step in devbox:setup."""

    def test_skips_when_server_does_not_support_user_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: False)

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)
        assert any("older than 2.33" in line for line in echoed)

    def test_skips_when_secret_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: True)

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)
        assert any("already set as a Coder user secret" in line for line in echoed)

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

        created: list[str] = []

        def fake_create(name: str, value: str, *, env_name=None, description=None) -> subprocess.CompletedProcess[str]:
            created.append(value)
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(devbox_cli, "create_user_secret", fake_create)

        echoed: list[str] = []
        monkeypatch.setattr(devbox_cli.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))

        devbox_cli.maybe_configure_claude_secret(None)

        assert created == ["legacy-token"]
        assert deleted == [True]

    def test_fresh_setup_creates_secret_from_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "has_claude_oauth_secret", lambda: False)
        monkeypatch.setattr(devbox_cli, "_read_legacy_keychain_token", lambda: None)
        monkeypatch.setattr(devbox_cli.click, "pause", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "echo", lambda *a, **kw: None)
        monkeypatch.setattr(devbox_cli.click, "prompt", lambda *a, **kw: "fresh-token")

        created: list[str] = []

        def fake_create(name: str, value: str, *, env_name=None, description=None) -> subprocess.CompletedProcess[str]:
            created.append(value)
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(devbox_cli, "create_user_secret", fake_create)

        devbox_cli.maybe_configure_claude_secret(None)
        assert created == ["fresh-token"]

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
            "create_user_secret",
            lambda *a, **kw: called.append("create") or subprocess.CompletedProcess([], 0, "", ""),
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
        assert "Claude user secret set" not in result.output

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

    def test_secret_set_creates_secret_from_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [])
        captured: dict[str, object] = {}

        def fake_create(name, value, *, env_name=None, description=None) -> subprocess.CompletedProcess[str]:
            captured["name"] = name
            captured["value"] = value
            captured["env_name"] = env_name
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(devbox_cli, "create_user_secret", fake_create)

        result = runner.invoke(cli, ["devbox:secret:set", "GH_TOKEN"], input="ghp-value\nghp-value\n")

        assert result.exit_code == 0
        assert captured == {"name": "GH_TOKEN", "value": "ghp-value", "env_name": "GH_TOKEN"}

    def test_secret_set_replaces_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "server_supports_user_secrets", lambda: True)
        monkeypatch.setattr(devbox_cli, "list_user_secrets", lambda: [{"name": "GH_TOKEN"}])

        deleted: list[str] = []
        monkeypatch.setattr(
            devbox_cli,
            "delete_user_secret",
            lambda name: deleted.append(name) or subprocess.CompletedProcess([], 0, "", ""),
        )
        monkeypatch.setattr(
            devbox_cli,
            "create_user_secret",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""),
        )

        result = runner.invoke(cli, ["devbox:secret:set", "GH_TOKEN"], input="new-value\nnew-value\n")
        assert result.exit_code == 0
        assert deleted == ["GH_TOKEN"]

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


class TestDevboxTaskCommand:
    """Test the devbox:task Click command."""

    @pytest.mark.parametrize(
        "cli_args, expected",
        [
            (
                ["devbox:task", "fix CI on PR #1234"],
                {"prompt": "fix CI on PR #1234", "task_name": None, "quiet": False},
            ),
            (
                ["devbox:task", "--name", "my-task", "-q", "do it"],
                {"prompt": "do it", "task_name": "my-task", "quiet": True},
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
            lambda prompt, task_name=None, quiet=False: captured.update(
                {"prompt": prompt, "task_name": task_name, "quiet": quiet}
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
            lambda prompt, task_name=None, quiet=False: captured.update(
                {"prompt": prompt, "task_name": task_name, "quiet": quiet}
            ),
        )

        result = runner.invoke(cli, ["devbox:task"], input="piped prompt\n")

        assert result.exit_code == 0
        assert captured == {"prompt": None, "task_name": None, "quiet": False}
