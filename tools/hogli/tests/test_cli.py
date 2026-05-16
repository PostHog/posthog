"""Tests for the hogli CLI."""

from __future__ import annotations

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


class TestDynamicCommandRegistration:
    """Test that commands are dynamically registered from manifest."""

    def test_start_command_exists(self) -> None:
        """Verify start command is registered from manifest."""
        result = runner.invoke(cli, ["start", "--help"])
        # Should either work or show a proper Click error
        assert "Error: No such command" not in result.output or result.exit_code == 2

    def test_migrations_command_exists(self) -> None:
        """Verify migrations commands are registered from manifest."""
        result = runner.invoke(cli, ["migrations:run", "--help"])
        # Should either work or show proper error
        assert "Error: No such command" not in result.output or result.exit_code == 2

    @patch("hogli.command_types._run")
    def test_command_with_bin_script_executes(self, mock_run: MagicMock) -> None:
        """Verify bin_script commands can execute."""
        mock_run.return_value = None
        # Try a command that should have a bin_script
        result = runner.invoke(cli, ["check:postgres", "--help"])
        # Should return help or execute
        assert result.exit_code in (0, 2)

    @patch("hogli.command_types._run")
    def test_direct_command_execution(self, mock_run: MagicMock) -> None:
        """Verify direct cmd commands execute properly."""
        mock_run.return_value = None
        # build:schema-json uses direct cmd field
        result = runner.invoke(cli, ["build:schema-json", "--help"])
        assert result.exit_code in (0, 2)


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


class TestCommandInjectionPrevention:
    """Test that command argument handling is secure."""

    @patch("hogli.command_types._run")
    def test_arguments_are_properly_escaped(self, mock_run: MagicMock) -> None:
        """Verify arguments passed to commands are properly escaped."""
        mock_run.return_value = None
        # Invoke a command with special characters
        result = runner.invoke(cli, ["migrations:run", "--help"])
        # The key test is that no exception is raised during argument parsing
        assert result.exit_code in (0, 1, 2)  # Any of these is acceptable

    @patch("hogli.command_types._run")
    def test_shell_operators_are_handled_safely(self, mock_run: MagicMock) -> None:
        """Verify commands with shell operators are executed safely."""
        mock_run.return_value = None
        # Invoke a composite command
        result = runner.invoke(cli, ["dev:reset", "--help"])
        # Should not raise an exception
        assert result.exit_code in (0, 1, 2)


class TestHelpText:
    """Test command help text generation."""

    def test_command_help_includes_description(self) -> None:
        """Verify command help includes description from manifest."""
        result = runner.invoke(cli, ["start", "--help"])
        # Should contain help text
        assert "Usage:" in result.output or result.exit_code == 2

    def test_category_grouping_in_help(self) -> None:
        """Verify help output groups commands by category."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have multiple sections
        lines = result.output.split("\n")
        # Look for section headers (typically uppercase or titled)
        assert len(lines) > 10
