"""Command classes for hogli CLI."""

from __future__ import annotations

import os
import sys
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click

from hogli.hooks import precheck_handlers
from hogli.manifest import REPO_ROOT, get_manifest, get_services_for_command


def _find_hogli_executable() -> list[str]:
    """Resolve the hogli executable for recursive invocations.

    Resolution order:
    1. ``bin/hogli`` under the repo root (PostHog monorepo convention).
    2. ``hogli`` on PATH (installed console script, e.g. via pip/uv).
    3. ``sys.executable -m hogli`` (same interpreter, works anywhere the
       package is importable).
    """
    bin_hogli = REPO_ROOT / "bin" / "hogli"
    if bin_hogli.exists():
        return [str(bin_hogli)]

    on_path = shutil.which("hogli")
    if on_path:
        return [on_path]

    return [sys.executable, "-m", "hogli"]


def _run(
    command: list[str] | str,
    *,
    env: dict[str, str] | None = None,
    shell: bool = False,
    cwd: str | Path | None = None,
) -> None:
    """Execute a shell command."""
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
            cwd=cwd or REPO_ROOT,
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
    - Child commands (variants) if any

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

    # Add underlying command and variants
    manifest = get_manifest()
    children = manifest.get_children_for_command(cmd_name)
    if underlying_cmd:
        if children:
            parts.append("Executes:")
            parts.append(f"• {underlying_cmd}")
            for child in children:
                suffix = child.removeprefix(cmd_name)  # e.g., ":minimal"
                child_config = manifest.get_command_config(child)
                child_cmd = child_config.get("cmd", "") if child_config else ""
                parts.append(f"• {suffix} → {child_cmd}")
        else:
            parts.append(f"Executes: {underlying_cmd}")

    # Join with double newlines to create paragraph breaks
    return "\n\n".join(parts)


def _prompt_user(prompt: str | bool, *, name: str = "", description: str = "") -> bool:
    """Prompt user for confirmation.

    Args:
        prompt: True for destructive warning, string for custom question
        name: Command name (shown for destructive warning)
        description: Command description (shown for destructive warning)

    Returns:
        True if confirmed, False if declined
    """
    if prompt is True:
        # Destructive warning style
        click.echo()
        click.secho("⚠️  This command may be destructive!", fg="yellow", bold=True)
        if name:
            click.echo(f"   Command: {name}")
        if description:
            click.echo(f"   {description}")
        click.echo()
        return click.confirm("Are you sure you want to continue?", default=False)
    else:
        # Custom question
        return click.confirm(str(prompt), default=False)


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
        prompt = self.config.get("prompt")
        if not prompt:
            return False

        if yes:
            return True

        if not _prompt_user(prompt, name=self.name, description=self.description):
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


def _run_prechecks(prechecks: list[dict[str, Any]], yes: bool = False) -> bool:
    """Run prechecks and prompt user if issues are found.

    Returns True if prechecks passed or user chose to continue, False if user aborted.
    Handlers are registered via hogli.hooks.register_precheck().
    """
    for check in prechecks:
        check_type = check.get("type")
        handler = precheck_handlers.get(check_type) if check_type else None
        if handler is None:
            click.secho(f"\u26a0\ufe0f  Unknown precheck type: {check_type}", fg="yellow", err=True)
            continue
        result = handler(check, yes)
        if result is False:
            return False

    return True


class BinScriptCommand(Command):
    """Command that delegates to a shell script in bin/."""

    def __init__(self, name: str, config: dict, script_path: Path) -> None:
        """Initialize with script path."""
        super().__init__(name, config)
        self.script_path = script_path

    def get_underlying_command(self) -> str:
        """Return the script path relative to repo root."""
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
                # Run any prechecks before confirming/executing
                prechecks = self.config.get("prechecks", [])
                if prechecks and not _run_prechecks(prechecks, yes=yes):
                    raise SystemExit(1)

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
        needs_shell = any(op in cmd_str for op in [" && ", " || ", "|", "\n", "$"])
        if needs_shell:
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


def execute_command_config(
    config: dict | str, *, env: dict[str, str], confirmed: bool = False, step_index: int = 0
) -> None:
    """Execute a command config (recursive for hogli/else).

    Handles all step/command formats:
    - String: hogli command name (shorthand for hogli: <name>)
    - Dict with hogli: hogli command, can have prompt/else modifiers
    - Dict with cmd: inline shell command
    - Dict with steps: composite (each step follows same rules)
    """
    hogli_exe = _find_hogli_executable()

    def _run_hogli(name: str) -> None:
        click.echo(f"✨ Executing: {name}")
        cmd_args = [*hogli_exe, name]
        if confirmed:
            cmd_args.append("--yes")
        _run(cmd_args, env=env)

    if isinstance(config, str):
        # String = hogli command name
        _run_hogli(config)

    elif isinstance(config, dict):
        if "hogli" in config:
            hogli_cmd = config["hogli"]
            prompt = config.get("prompt")
            # Check for prompt guard (True for destructive, string for custom question)
            if prompt:
                # prompt: true = destructive warning, skippable with confirmed
                # prompt: "string" = user choice, always ask (it's a decision, not just confirmation)
                should_run = False
                if prompt is True:
                    # Destructive: skip if already confirmed
                    should_run = confirmed or _prompt_user(prompt, name=hogli_cmd)
                else:
                    # String prompt: always ask - this is a user choice, not just confirmation
                    should_run = _prompt_user(prompt, name=hogli_cmd)

                if should_run:
                    _run_hogli(hogli_cmd)
                elif "else" in config:
                    # User said no - run the else branch (recursive)
                    execute_command_config(config["else"], env=env, confirmed=confirmed)
                # else: user said no and no else branch, skip
            else:
                # No prompt, just run the hogli command
                _run_hogli(hogli_cmd)

        elif "cmd" in config:
            # Inline shell command
            step_name = config.get("name", f"step-{step_index + 1}")
            click.echo(f"✨ Executing: {step_name}")
            _run(["bash", "-c", config["cmd"]], env=env)

        elif "steps" in config:
            # Nested composite - run each step
            for i, step in enumerate(config["steps"]):
                execute_command_config(step, env=env, confirmed=confirmed, step_index=i)


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
                if "hogli" in step:
                    step_strs.append(f"hogli {step['hogli']}")
                else:
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
                # Child commands should always get --yes if parent was confirmed
                self.execute(confirmed=confirmed or yes)
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str, confirmed: bool = False) -> None:
        """Execute each step in sequence."""
        steps = self.config.get("steps", [])
        for i, step in enumerate(steps):
            try:
                execute_command_config(step, env=self.env, confirmed=confirmed, step_index=i)
            except SystemExit:
                raise


class HogliCommand(Command):
    """Command that wraps another hogli command with optional prompt guard."""

    def get_underlying_command(self) -> str:
        """Return the wrapped hogli command."""
        return f"hogli {self.config.get('hogli', '')}"

    def register(self, cli_group: click.Group) -> Any:
        """Register command."""
        help_text = self.get_help_text()

        @cli_group.command(self.name, help=help_text)
        @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
        @click.pass_context
        def cmd(ctx: click.Context, yes: bool) -> None:
            try:
                confirmed = self._confirm(yes=yes)
                self.execute(confirmed=confirmed or yes)
            except SystemExit:
                raise

        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str, confirmed: bool = False) -> None:
        """Execute the wrapped hogli command."""
        execute_command_config(self.config, env=self.env, confirmed=confirmed)
