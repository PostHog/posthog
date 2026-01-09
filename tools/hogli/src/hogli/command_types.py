"""Command classes for hogli CLI."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import click
from hogli.manifest import get_services_for_command


def _run(command: list[str] | str, *, env: dict[str, str] | None = None, shell: bool = False) -> None:
    """Execute a shell command."""
    from hogli.manifest import REPO_ROOT

    if isinstance(command, list):
        display = " ".join(command)
        click.echo(f"🚀 {display}")
    elif "\n" not in command:
        # Only show single-line commands
        display = command
        click.echo(f"🚀 {command}")
    else:
        # Multiline command - no display
        display = "<multiline command>"

    try:
        subprocess.run(
            command,
            cwd=REPO_ROOT,
            env={**os.environ, **(env or {})},
            check=True,
            shell=shell,
        )
    except subprocess.CalledProcessError as e:
        click.echo(click.style(f"💥 Command failed: {display}", fg="red", bold=True), err=True)
        raise SystemExit(1) from e


def _format_command_help(cmd_name: str, cmd_config: dict, underlying_cmd: str) -> str:
    """Format help text with service context and underlying command.

    Returns formatted help text with:
    - Original description
    - Service info if available
    - Underlying command being executed

    Note: Click will rewrap long lines, but we add paragraph breaks between
    services for better readability.
    """
    parts = []

    # Add main description
    if description := cmd_config.get("description", ""):
        parts.append(description)

    # Add service context if available
    services = get_services_for_command(cmd_name, cmd_config)
    if services:
        parts.append("Uses:")
        # Add each service as a separate paragraph to force line breaks
        for svc_name, about in services:
            parts.append(f"• {svc_name}: {about}")

    # Add underlying command
    if underlying_cmd:
        parts.append(f"Executes: {underlying_cmd}")

    # Join with double newlines to create paragraph breaks
    return "\n\n".join(parts)


class Command:
    """Base class for CLI commands."""

    def __init__(self, name: str, config: dict) -> None:
        """Initialize command with configuration."""
        self.name = name
        self.config = config
        self.description = config.get("description", "")
        self.env = config.get("env", {})

    def get_underlying_command(self) -> str:
        """Get the underlying command being executed. Override in subclasses."""
        return ""

    def get_help_text(self) -> str:
        """Generate formatted help text with service context and underlying command."""
        return _format_command_help(self.name, self.config, self.get_underlying_command())

    def _confirm(self, yes: bool = False) -> bool:
        """Prompt for confirmation if required.

        Returns True if confirmation was given (via --yes flag or user prompt), False otherwise.
        """
        if not self.config.get("destructive", False):
            return False

        if yes:
            return True

        click.echo()
        click.echo(click.style("⚠️  This command may be destructive!", fg="yellow", bold=True))
        click.echo(f"   Command: {self.name}")
        if self.description:
            click.echo(f"   {self.description}")
        click.echo()

        if not click.confirm("Are you sure you want to continue?", default=False):
            click.echo(click.style("Aborted.", fg="red"))
            raise SystemExit(0)

        return True

    def execute(self, *args: str) -> None:
        """Override in subclasses."""
        raise NotImplementedError("Subclasses must implement execute()")

    def register(self, cli_group: click.Group) -> Any:
        """Register this command with the CLI group."""
        help_text = self.get_help_text()

        @cli_group.command(self.name, help=help_text)
        @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
        @click.pass_context
        def cmd(ctx: click.Context, yes: bool) -> None:
            try:
                self._confirm(yes=yes)
                self.execute()
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd


class BinScriptCommand(Command):
    """Command that delegates to a shell script in bin/."""

    def __init__(self, name: str, config: dict, script_path: Path) -> None:
        """Initialize with script path."""
        super().__init__(name, config)
        self.script_path = script_path

    def get_underlying_command(self) -> str:
        """Return the script path relative to repo root."""
        from hogli.manifest import REPO_ROOT

        try:
            return str(self.script_path.relative_to(REPO_ROOT))
        except ValueError:
            # If not relative to repo root, just return the name
            return self.script_path.name

    def register(self, cli_group: click.Group) -> Any:
        """Register command with extra args support."""
        help_text = self.get_help_text()

        @cli_group.command(
            self.name,
            help=help_text,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
        @click.pass_context
        def cmd(ctx: click.Context, yes: bool) -> None:
            try:
                self._confirm(yes=yes)
                self.execute(*ctx.args)
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str) -> None:
        """Execute the script with any passed arguments."""
        _run([str(self.script_path), *args], env=self.env)


class DirectCommand(Command):
    """Command that executes a direct shell command."""

    def get_underlying_command(self) -> str:
        """Return the shell command."""
        return self.config.get("cmd", "")

    def register(self, cli_group: click.Group) -> Any:
        """Register command with extra args support."""
        help_text = self.get_help_text()

        @cli_group.command(
            self.name,
            help=help_text,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
        @click.pass_context
        def cmd(ctx: click.Context, yes: bool) -> None:
            try:
                self._confirm(yes=yes)
                self.execute(*ctx.args)
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str) -> None:
        """Execute the shell command with any passed arguments."""
        cmd_str = self.config.get("cmd", "")
        # Use shell=True if command contains shell operators or is multiline
        has_operators = any(op in cmd_str for op in [" && ", " || ", "|", "\n"])
        if has_operators:
            # For shell commands, pass args as positional parameters using sh -c
            if args:
                # Pass args as positional parameters: _ is placeholder for $0, then actual args as $1, $2, etc.
                escaped_args = " ".join(shlex.quote(arg) for arg in args)
                cmd_str = f"sh -c {shlex.quote(cmd_str)} _ {escaped_args}"
            _run(cmd_str, shell=True, env=self.env)
        else:
            # Use list format for simple commands without shell operators
            # Use shlex.split() to properly handle quoted arguments
            _run([*shlex.split(cmd_str), *args], env=self.env)


class CompositeCommand(Command):
    """Command that runs multiple hogli commands in sequence."""

    def get_underlying_command(self) -> str:
        """Return the composed command string."""
        steps = self.config.get("steps", [])
        step_strs = []
        for step in steps:
            if isinstance(step, str):
                step_strs.append(f"hogli {step}")
            elif isinstance(step, dict):
                name = step.get("name", "inline")
                step_strs.append(f"[{name}]")
        return " && ".join(step_strs)

    def register(self, cli_group: click.Group) -> Any:
        """Register command with extra args support."""
        help_text = self.get_help_text()

        @cli_group.command(self.name, help=help_text)
        @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
        @click.pass_context
        def cmd(ctx: click.Context, yes: bool) -> None:
            try:
                confirmed = self._confirm(yes=yes)
                # Store whether confirmation was given (via --yes or prompt)
                # Child commands should always get --yes if parent was confirmed
                self._confirmed = confirmed or yes
                self.execute()
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str) -> None:
        """Execute each step in sequence.

        Steps can be:
        - string: name of another hogli command to run
        - dict: inline command config (same format as manifest commands)
        """
        from hogli.manifest import REPO_ROOT

        steps = self.config.get("steps", [])
        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        # Pass --yes to children if parent required confirmation and it was confirmed
        confirmed = getattr(self, "_confirmed", False)

        for i, step in enumerate(steps):
            try:
                if isinstance(step, str):
                    # Named command - call hogli recursively
                    click.echo(f"✨ Executing: {step}")
                    if confirmed:
                        _run([bin_hogli, step, "--yes"], env=self.env)
                    else:
                        _run([bin_hogli, step], env=self.env)
                elif isinstance(step, dict) and "cmd" in step:
                    # Inline shell command
                    # TODO: support full inline command configs (bin_script, steps, etc.)
                    step_name = step.get("name", f"step-{i + 1}")
                    click.echo(f"✨ Executing: {step_name}")
                    _run(["bash", "-c", step["cmd"]], env=self.env)
            except SystemExit:
                raise
