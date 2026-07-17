"""Tests for the hogli CLI."""

from __future__ import annotations

import os
import sys

import pytest
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
from hogli.cli import cli
from hogli.manifest import get_manifest

runner = CliRunner()


def _manifest_click_commands() -> list[str]:
    manifest = get_manifest()
    return [
        cmd_name
        for cmd_name in manifest.get_all_commands()
        if (config := manifest.get_command_config(cmd_name)) and config.get("click")
    ]


def _manifest_click_modules() -> list[str]:
    manifest = get_manifest()
    modules: set[str] = set()
    for cmd_name in _manifest_click_commands():
        click_target = (manifest.get_command_config(cmd_name) or {}).get("click", "")
        module_name = click_target.split(":", 1)[0]
        if module_name:
            modules.add(module_name)
    return sorted(modules)


class TestMainCommand:
    """Test main command functionality."""

    def test_help_displays_commands(self) -> None:
        """Verify --help displays available commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        # Check for some core commands that should exist
        assert "start" in result.output or "docker" in result.output or "migrations" in result.output

    def test_help_displays_categories(self) -> None:
        """Verify --help displays command categories."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have at least one category from metadata
        output_lower = result.output.lower()
        assert any(
            category in output_lower for category in ["core development", "start services", "migrations", "tests"]
        )

    def test_invalid_command_fails(self) -> None:
        """Verify invalid commands fail gracefully."""
        result = runner.invoke(cli, ["nonexistent-command"])
        assert result.exit_code != 0


class TestQuickstartCommand:
    """Test quickstart command."""

    def test_quickstart_displays_help(self) -> None:
        """Verify quickstart command displays getting started info."""
        result = runner.invoke(cli, ["quickstart"])
        assert result.exit_code == 0
        assert "PostHog Development Quickstart" in result.output
        assert "hogli" in result.output
        assert "hogli start -d" not in result.output


class TestMetaCheckCommand:
    """Test meta:check command."""

    def test_meta_check_validates_manifest(self) -> None:
        """Verify meta:check validates manifest entries."""
        result = runner.invoke(cli, ["meta:check"])
        # Should either pass or report missing entries clearly
        assert "bin script" in result.output.lower() or "✓" in result.output


class TestMetaConceptsCommand:
    """Test meta:concepts command."""

    def test_meta_concepts_displays_services(self) -> None:
        """Verify meta:concepts displays infrastructure concepts."""
        result = runner.invoke(cli, ["meta:concepts"])
        assert result.exit_code == 0
        assert "Infrastructure" in result.output or "service" in result.output.lower()


class TestLazyClickCommands:
    @pytest.mark.parametrize("command_name", _manifest_click_commands())
    def test_lazy_click_command_help_loads(self, command_name: str) -> None:
        # Click's recommended sanity check: every lazy command's --help must
        # succeed. Catches bad `click:` import strings, missing modules,
        # missing attrs, wrong types, and Click-name drift in one shot.
        result = runner.invoke(cli, [command_name, "--help"])
        assert result.exit_code == 0, f"{command_name}: {result.output}"
        assert "Usage:" in result.output

    def test_top_level_help_does_not_import_lazy_command_modules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lazy_modules = _manifest_click_modules()
        assert lazy_modules, "expected at least one lazy click module in the manifest"
        for module_name in lazy_modules:
            monkeypatch.delitem(sys.modules, module_name, raising=False)

        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        for module_name in lazy_modules:
            assert module_name not in sys.modules, f"{module_name} was imported during top-level --help"

    def test_hidden_lazy_commands_are_hidden_from_help_and_listing(self) -> None:
        hidden_command = "dev:list-units"

        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert hidden_command not in result.output
        with click.Context(cli) as ctx:
            assert hidden_command not in cli.list_commands(ctx)
            assert isinstance(cli.get_command(ctx, hidden_command), click.Command)


class TestHelpText:
    """Test command help text generation."""

    def test_category_grouping_in_help(self) -> None:
        """Verify help output groups commands by category."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have multiple sections
        lines = result.output.split("\n")
        # Look for section headers (typically uppercase or titled)
        assert len(lines) > 10


class TestLoadEnvFile:
    """Test _load_env_file behavior — esp. the optional skip_pattern."""

    def _write_env(self, tmp_path, content: str):
        env_file = tmp_path / ".env.test"
        env_file.write_text(content)
        return env_file

    @pytest.mark.parametrize(
        "op_line",
        [
            "OPENAI_API_KEY=op://General/abc/credential",
            'OPENAI_API_KEY="op://General/abc/credential"',
            "OPENAI_API_KEY= op://General/abc/credential",
        ],
        ids=["bare", "double-quoted", "leading-space"],
    )
    def test_skip_pattern_filters_matching_values(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, op_line: str
    ) -> None:
        """skip_pattern filters values that should never leak as literal env vars.

        Covers bare/quoted/space-padded forms (op run itself accepts all three),
        so users may write any of them and the substring match still skips them.
        """
        from hogli.cli import _load_env_file

        env_file = self._write_env(tmp_path, f"{op_line}\nLITERAL_VAR=actual_value\n")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITERAL_VAR", raising=False)

        _load_env_file(env_file, skip_pattern="op://")

        assert "OPENAI_API_KEY" not in os.environ
        assert os.environ["LITERAL_VAR"] == "actual_value"

    def test_no_skip_pattern_loads_everything(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without skip_pattern the loader stays a transparent dotenv parser.

        Important so the loader is reusable for plain dotenv files that have
        nothing to do with secrets resolution.
        """
        from hogli.cli import _load_env_file

        env_file = self._write_env(tmp_path, "API_KEY=op://foo/bar\nOTHER=baz\n")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("OTHER", raising=False)

        _load_env_file(env_file)  # no skip_pattern

        assert os.environ["API_KEY"] == "op://foo/bar"
        assert os.environ["OTHER"] == "baz"

    def test_missing_file_is_silent(self, tmp_path) -> None:
        """Missing env files should not raise — caller may pass an optional file."""
        from hogli.cli import _load_env_file

        _load_env_file(tmp_path / "does_not_exist.env")

    def test_only_if_unset_preserves_shell_env(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from hogli.cli import _load_env_file

        env_file = self._write_env(tmp_path, "MY_VAR=from_file\n")
        monkeypatch.setenv("MY_VAR", "from_shell")

        _load_env_file(env_file, only_if_unset=True)

        assert os.environ["MY_VAR"] == "from_shell"

    def test_ignores_comments_and_blanks(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from hogli.cli import _load_env_file

        env_file = self._write_env(tmp_path, "# comment\n\nREAL_VAR=42\n# another\n")
        monkeypatch.delenv("REAL_VAR", raising=False)

        _load_env_file(env_file)

        assert os.environ["REAL_VAR"] == "42"


class TestApplyEnvConfig:
    """End-to-end behavior of _apply_env_config against mocked manifest config.

    Patches `get_manifest` so each test can declare its own env_files /
    secrets_config and we don't depend on PostHog's hogli.yaml. The mocked
    manifest also keeps existing PostHog tests in the same file unaffected.
    """

    def _make_manifest(
        self,
        env_files=None,
        secrets_config=None,
        needs_secrets_commands: set[str] | None = None,
    ) -> MagicMock:
        """Build a fake Manifest. ``needs_secrets_commands`` is the set of
        invoked-subcommand names whose ``get_command_config`` lookup returns
        ``needs_secrets: true``. Any name not in the set returns an empty
        config (the realistic default for opted-out commands)."""
        m = MagicMock()
        m.env_files = env_files or []
        m.secrets_config = secrets_config
        opted_in = needs_secrets_commands or set()

        def get_command_config(name: str) -> dict:
            return {"needs_secrets": True} if name in opted_in else {}

        m.get_command_config.side_effect = get_command_config
        m.command_flag.side_effect = lambda name, key: bool(get_command_config(name).get(key, False))
        return m

    def test_no_env_config_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generic hogli installs with no `config.env` should not touch os.environ.

        The PyPI hogli package must stay transparent for users who don't opt in.
        """
        from hogli.cli import _apply_env_config

        monkeypatch.setattr("hogli.cli.get_manifest", lambda: self._make_manifest())
        monkeypatch.delenv("UNRELATED_VAR", raising=False)
        before = dict(os.environ)

        _apply_env_config("start")

        assert os.environ == before

    def test_loads_files_in_declared_order_first_wins(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Earlier files in `config.env.files` win for duplicate keys (matches just/mise/task)."""
        from hogli.cli import _apply_env_config

        first = tmp_path / ".env.first"
        second = tmp_path / ".env.second"
        first.write_text("SHARED=from_first\nONLY_FIRST=1\n")
        second.write_text("SHARED=from_second\nONLY_SECOND=2\n")

        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(env_files=[first, second]),
        )
        for k in ("SHARED", "ONLY_FIRST", "ONLY_SECOND", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)

        _apply_env_config("anything")

        assert os.environ["SHARED"] == "from_first"
        assert os.environ["ONLY_FIRST"] == "1"
        assert os.environ["ONLY_SECOND"] == "2"

    def test_shell_env_always_wins(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shell env beats every config file — same precedence as bin/start."""
        from hogli.cli import _apply_env_config

        env_file = tmp_path / ".env"
        env_file.write_text("OVERRIDE_ME=from_file\n")

        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(env_files=[env_file]),
        )
        monkeypatch.setenv("OVERRIDE_ME", "from_shell")
        monkeypatch.delenv("HOGLI_SECRETS_WRAPPED", raising=False)

        _apply_env_config("anything")

        assert os.environ["OVERRIDE_ME"] == "from_shell"

    def test_secrets_file_without_marker_loads_literals_directly(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Secrets file with no marker hit: load directly, no wrap re-exec."""
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("PLAIN_KEY=plain_value\n")

        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        monkeypatch.delenv("PLAIN_KEY", raising=False)
        monkeypatch.delenv("HOGLI_SECRETS_WRAPPED", raising=False)

        with patch("os.execvp") as mock_exec:
            _apply_env_config("start")

        mock_exec.assert_not_called()
        assert os.environ["PLAIN_KEY"] == "plain_value"

    def test_secrets_file_overrides_env_files_in_fallback_path(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """In the no-wrap fallback path, .env.local literal values must win
        over .env.development / .env.services — same precedence the wrap path
        gives (where the resolver layers .env.local on top). This guards the
        regression Codex flagged: loading env_files first with only_if_unset
        meant .env.development was beating .env.local literal overrides."""
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("SHARED_KEY=local_wins\n")
        env_file = tmp_path / ".env.development"
        env_file.write_text("SHARED_KEY=dev_loses\nDEV_ONLY=dev_value\n")

        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                env_files=[env_file],
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        for k in ("SHARED_KEY", "DEV_ONLY", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)

        with patch("os.execvp") as mock_exec:
            _apply_env_config("start")

        mock_exec.assert_not_called()
        assert os.environ["SHARED_KEY"] == "local_wins"
        assert os.environ["DEV_ONLY"] == "dev_value"

    def test_missing_secrets_file_falls_through_silently(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No `.env.local` file at all (fresh user) — env_files still load and
        no errors are raised. This is the bin/start "if one does not have the
        .env.local file already" scenario."""
        from hogli.cli import _apply_env_config

        env_file = tmp_path / ".env.development"
        env_file.write_text("DEV_ONLY=ok\n")
        secrets = {
            "file": tmp_path / ".env.local",  # doesn't exist
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                env_files=[env_file],
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        for k in ("DEV_ONLY", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)

        with patch("os.execvp") as mock_exec:
            _apply_env_config("start")

        mock_exec.assert_not_called()
        assert os.environ["DEV_ONLY"] == "ok"

    def test_marker_hit_with_wrap_binary_present_reexecs(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When marker matches AND the invoked command opts into needs_secrets
        AND the wrap binary is on PATH, hogli re-execs under the wrap.

        Verifies the wrap command is built with `{file}` substituted, the
        sentinel is set so the child won't loop, and pre-existing env_files
        were loaded into os.environ so the wrap child inherits them.
        """
        from hogli.cli import _apply_env_config

        env_file = tmp_path / ".env.development"
        env_file.write_text("PRELOADED=yes\n")
        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("API_KEY=op://vault/item/credential\n")

        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                env_files=[env_file],
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        for k in ("PRELOADED", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)
        # Re-exec only fires when hogli owns the process (real CLI entrypoint).
        monkeypatch.setattr("hogli.cli._is_process_entrypoint", True)

        with (
            patch("shutil.which", return_value="/usr/local/bin/op"),
            patch("os.execvp") as mock_exec,
        ):
            _apply_env_config("start")

        mock_exec.assert_called_once()
        args, _kwargs = mock_exec.call_args
        binary, argv = args
        assert binary == "op"
        # {file} got substituted with the absolute path
        assert str(secrets_file) in argv
        assert "{file}" not in argv
        # argv re-runs hogli (so the child completes the original invocation)
        assert any("hogli" in arg for arg in argv)
        # pre-loaded files were applied before the exec (so wrap-child inherits)
        assert os.environ["PRELOADED"] == "yes"
        # sentinel set to prevent infinite re-exec loop
        assert os.environ["HOGLI_SECRETS_WRAPPED"] == "1"

    def test_embedded_invocation_never_reexecs(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When hogli is invoked in-process (not the process entrypoint), the
        wrap must never os.execvp — even with the marker present and the wrap
        binary installed. execvp would replace and silently kill the host
        process (e.g. a click CliRunner test runner). Instead it falls through
        to direct file loading, skipping unresolved refs.

        This is the regression guard for the silent-death bug: any pytest run
        that drives the CLI through CliRunner on a machine with the wrap binary
        installed and marker refs in the secrets file would otherwise exec away
        the test process mid-run.
        """
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("API_KEY=op://vault/item/credential\nLITERAL=keep_me\n")
        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(secrets_config=secrets, needs_secrets_commands={"start"}),
        )
        # Embedded, not a real entrypoint: this is what CliRunner / library use sees.
        monkeypatch.setattr("hogli.cli._is_process_entrypoint", False)
        for k in ("API_KEY", "LITERAL", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)

        with (
            patch("shutil.which", return_value="/usr/local/bin/op"),
            patch("os.execvp") as mock_exec,
        ):
            _apply_env_config("start")

        mock_exec.assert_not_called()
        assert "API_KEY" not in os.environ  # op:// ref skipped, not leaked as a literal
        assert os.environ["LITERAL"] == "keep_me"

    def test_marker_hit_but_wrap_binary_missing_falls_back_with_warning(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """When wrap binary isn't installed, load files but skip ref lines + warn.

        This is the user-friendly degradation: the dev still gets `.env.local`
        literal values (if any), but the unresolved refs don't leak as garbage
        env values that produce confusing 401s downstream.
        """
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("OPENAI_API_KEY=op://vault/item/credential\nLITERAL=keep_me\n")

        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        for k in ("OPENAI_API_KEY", "LITERAL", "HOGLI_SECRETS_WRAPPED"):
            monkeypatch.delenv(k, raising=False)
        # The missing-binary warning is only meaningful for a real entrypoint
        # that would otherwise re-exec; simulate one.
        monkeypatch.setattr("hogli.cli._is_process_entrypoint", True)

        with (
            patch("shutil.which", return_value=None),
            patch("os.execvp") as mock_exec,
        ):
            _apply_env_config("start")

        mock_exec.assert_not_called()
        assert "OPENAI_API_KEY" not in os.environ
        assert os.environ["LITERAL"] == "keep_me"
        err = capsys.readouterr().err
        assert "op://" in err
        assert "op" in err  # wrap binary name surfaced

    def test_sentinel_skips_reexec_so_child_doesnt_loop(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After wrap re-execs hogli, the child sees HOGLI_SECRETS_WRAPPED and skips wrap.

        Without this, the wrap binary would re-exec hogli forever.

        Also verifies the sentinel PERSISTS in env after the wrap-child runs,
        so subprocesses spawned by composite/steps commands inherit it and
        also skip their own wrap (no cascading auth prompts on chained
        invocations like `dev:reset`).
        """
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("API_KEY=op://vault/item/credential\n")

        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(
                secrets_config=secrets,
                needs_secrets_commands={"start"},
            ),
        )
        # Simulate being the child of a wrap re-exec: sentinel set, wrap already
        # populated the env via op run (so OPENAI_API_KEY would be in env).
        monkeypatch.setenv("HOGLI_SECRETS_WRAPPED", "1")
        monkeypatch.setenv("API_KEY", "resolved_by_op")

        with patch("os.execvp") as mock_exec:
            _apply_env_config("start")

        mock_exec.assert_not_called()
        # Wrap binary's resolved value wins; the file isn't sourced over it
        assert os.environ["API_KEY"] == "resolved_by_op"
        # Sentinel must STAY in env so subprocesses spawned by this wrap-child
        # inherit it and skip re-wrapping. Popping would re-trigger auth
        # prompts for every step in a composite chain.
        assert os.environ["HOGLI_SECRETS_WRAPPED"] == "1"

    @pytest.mark.parametrize(
        "invoked_subcommand,opted_in,expect_wrap",
        [
            (None, {"start"}, False),
            ("lint", {"start"}, False),
            ("run", set(), True),
        ],
        ids=["no-subcommand", "manifest-opted-out", "builtin-run"],
    )
    def test_gate_controls_wrap_reexec(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        invoked_subcommand: str | None,
        opted_in: set[str],
        expect_wrap: bool,
    ) -> None:
        from hogli.cli import _apply_env_config

        secrets_file = tmp_path / ".env.local"
        secrets_file.write_text("API_KEY=op://vault/item/credential\n")
        secrets = {
            "file": secrets_file,
            "marker": "op://",
            "wrap": ["op", "run", "--env-file", "{file}", "--"],
        }
        monkeypatch.setattr(
            "hogli.cli.get_manifest",
            lambda: self._make_manifest(secrets_config=secrets, needs_secrets_commands=opted_in),
        )
        monkeypatch.delenv("HOGLI_SECRETS_WRAPPED", raising=False)
        # This test exercises the needs_secrets gate, not the entrypoint gate —
        # run as a real entrypoint so the wrap can fire when the gate opens.
        monkeypatch.setattr("hogli.cli._is_process_entrypoint", True)

        with (
            patch("shutil.which", return_value="/usr/local/bin/op"),
            patch("os.execvp") as mock_exec,
        ):
            _apply_env_config(invoked_subcommand)

        if expect_wrap:
            mock_exec.assert_called_once()
        else:
            mock_exec.assert_not_called()
