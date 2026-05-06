"""hogli - Developer CLI framework with YAML-based command definitions.

All commands are defined in hogli.yaml and auto-discovered.
Help output is dynamically generated from the manifest with category grouping.
"""

from __future__ import annotations

import os
import sys
import time as _time
import shutil
import platform
import importlib
import importlib.util
from collections import defaultdict
from typing import Any

import click

from hogli import telemetry
from hogli.command_types import BinScriptCommand, CompositeCommand, DirectCommand, HogliCommand
from hogli.hooks import post_command_hooks, telemetry_property_hooks
from hogli.manifest import get_category_for_command, get_manifest, get_services_for_command, load_manifest
from hogli.validate import auto_update_manifest, find_missing_manifest_entries

_DEFAULT_HELP = "Developer CLI framework with YAML-based command definitions."


class CategorizedGroup(click.Group):
    """Custom Click group that formats help output like git help with categories.

    Overrides ``invoke`` to wrap every subcommand execution with telemetry
    tracking (timing, exit code) using ``ctx.meta`` for state instead of a
    module-level singleton.
    """

    def invoke(self, ctx: click.Context) -> Any:
        ctx.meta["hogli.start_time"] = _time.monotonic()
        ctx.meta["hogli.has_extra_argv"] = len(sys.argv) > 2
        exit_code = 0
        try:
            return super().invoke(ctx)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            raise
        except KeyboardInterrupt:
            exit_code = 130
            raise
        except Exception:
            exit_code = 1
            raise
        finally:
            _fire_telemetry(ctx, exit_code)
            telemetry.flush()
            _fire_post_command_hooks(ctx.invoked_subcommand, exit_code)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format commands grouped by category, git-style with extends tree."""
        manifest_obj = get_manifest()
        categories_list = manifest_obj.categories

        # Build a mapping from category key to title
        category_key_to_title = {cat.get("key"): cat.get("title") for cat in categories_list}

        # Set of commands that extend others (will be rendered under their parent)
        child_commands = {child for parent in self.commands for child in manifest_obj.get_children_for_command(parent)}

        # Group commands by category, storing (key, title) tuple
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for cmd_name, cmd in self.commands.items():
            # Skip hidden commands (they're still callable, just not shown in help)
            hogli_config = getattr(cmd, "hogli_config", {})
            if hogli_config.get("hidden", False):
                continue

            # Skip child commands - they'll be rendered under their parent
            if cmd_name in child_commands:
                continue

            category_title = get_category_for_command(cmd_name)
            help_text = cmd.get_short_help_str(100) if hasattr(cmd, "get_short_help_str") else (cmd.help or "")

            # Find the key for this title
            category_key = next(
                (key for key, title in category_key_to_title.items() if title == category_title), "commands"
            )
            grouped[(category_key, category_title)].append((cmd_name, help_text))

        # Build category order from the list
        category_order = {idx: cat.get("key") for idx, cat in enumerate(categories_list)}

        def get_category_sort_key(item: tuple[tuple[str, str], list[tuple[str, str]]]) -> int:
            cat_tuple, _commands = item
            key = cat_tuple[0]
            if key == "commands":  # Default category goes last
                return len(category_order) + 1
            return next((idx for idx, k in category_order.items() if k == key), 999)

        sorted_categories = sorted(grouped.items(), key=get_category_sort_key)

        # Format each category section
        for (_category_key, category_title), commands in sorted_categories:
            rows: list[tuple[str, str]] = []
            for cmd_name, help_text in sorted(commands, key=lambda x: x[0]):
                rows.append((cmd_name, help_text))
                # Render children indented under parent
                for child in manifest_obj.get_children_for_command(cmd_name):
                    suffix = child.removeprefix(cmd_name)  # e.g., ":minimal"
                    rows.append((f"  └─ {suffix}", ""))
            if rows:
                with formatter.section(category_title):
                    formatter.write_dl(rows)


def _auto_update_manifest() -> None:
    """Automatically update manifest with missing entries."""
    added = auto_update_manifest()
    if added:
        click.secho(
            f"ℹ️  Auto-added to manifest: {', '.join(sorted(added))}",
            fg="blue",
            err=True,
        )


@click.group(
    cls=CategorizedGroup,
    help=get_manifest().config.get("description", _DEFAULT_HELP),
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """hogli - YAML-driven developer CLI."""
    # Auto-update manifest on every invocation (but skip for meta:check and git hooks)
    # Skip during git hooks to prevent manifest modifications during lint-staged execution
    in_git_hook = os.environ.get("GIT_DIR") is not None or os.environ.get("HUSKY") is not None
    if ctx.invoked_subcommand not in {"meta:check", "help"} and not in_git_hook:
        _auto_update_manifest()
        if ctx.invoked_subcommand not in {"telemetry:off", "telemetry:status"}:
            telemetry.show_first_run_notice_if_needed()

    # Fire early so long-running commands (e.g. hogli start) are always counted
    # even if the process is killed without a clean exit.
    if ctx.invoked_subcommand and ctx.invoked_subcommand != "telemetry:off":
        telemetry.track(
            "command_started", {"command": ctx.invoked_subcommand, **_env_properties(ctx.invoked_subcommand)}
        )


@cli.command(name="meta:check", help="Validate manifest against bin scripts (for CI)")
def meta_check() -> None:
    """Validate that all bin scripts are in the manifest."""
    missing = find_missing_manifest_entries()

    if not missing:
        click.echo("✓ All bin scripts are in the manifest")
        return

    click.echo(f"✗ Found {len(missing)} bin script(s) not in manifest:")
    for script in sorted(missing):
        click.echo(f"  - {script}")

    raise SystemExit(1)


@cli.command(name="meta:concepts", help="Show services and infrastructure concepts")
def concepts() -> None:
    """Display infrastructure concepts and services with descriptions and related commands."""
    manifest = load_manifest()
    services_dict = manifest.get("metadata", {}).get("services", {})

    if not services_dict:
        click.echo("No services found in manifest.")
        return

    # Build a reverse mapping: service_name -> service_key
    service_name_to_key = {svc_info.get("name", key): key for key, svc_info in services_dict.items()}

    # Build a map of service_key -> list of commands that use it
    service_commands: dict[str, set[str]] = {svc_key: set() for svc_key in services_dict}

    # Scan all commands for explicit services or prefix matching
    for category, scripts in manifest.items():
        if category == "metadata" or not isinstance(scripts, dict):
            continue
        for cmd_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            # Get services for this command
            services = get_services_for_command(cmd_name, config)
            for svc_name, _ in services:
                svc_key = service_name_to_key.get(svc_name)
                if svc_key:
                    service_commands[svc_key].add(cmd_name)

    click.echo("\nInfrastructure Concepts:\n")
    for service_key in sorted(services_dict.keys()):
        service_info = services_dict[service_key]
        name = service_info.get("name", service_key)
        about = service_info.get("about", "No description")
        click.echo(f"  {name}")
        click.echo(f"    {about}")

        commands = service_commands[service_key]
        if commands:
            click.echo(f"    Commands: {', '.join(sorted(commands))}")
        click.echo()


def _register_script_commands() -> None:
    """Dynamically register commands from hogli.yaml.

    Supports three types of entries:
    1. bin_script: Delegate to a shell script (in config.scripts_dir, default: bin/)
    2. steps: Compose multiple hogli commands in sequence
    3. cmd: Execute a direct shell command
    """
    manifest = get_manifest()
    scripts_dir = manifest.scripts_dir

    for _category, scripts in manifest.data.items():
        if not isinstance(scripts, dict):
            continue

        for cli_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            # Determine command type
            bin_script = config.get("bin_script")
            steps = config.get("steps")
            cmd = config.get("cmd")
            hogli = config.get("hogli")

            if not (bin_script or steps or cmd or hogli):
                continue

            # Handle composition (steps field)
            if steps:
                command = CompositeCommand(cli_name, config)
                command.register(cli)
                continue

            # Handle direct commands (cmd field)
            if cmd:
                command = DirectCommand(cli_name, config)
                command.register(cli)
                continue

            # Handle hogli wrapper commands (hogli field)
            if hogli:
                command = HogliCommand(cli_name, config)
                command.register(cli)
                continue

            # Handle bin_script delegation
            if bin_script:
                script_path = scripts_dir / bin_script
                if not script_path.exists():
                    continue

                command = BinScriptCommand(cli_name, config, script_path)
                command.register(cli)


# Register all script commands from manifest before app runs
_register_script_commands()


def _import_custom_commands() -> None:
    """Import custom commands from configured commands_dir.

    Looks for commands in:
    1. config.commands_dir in hogli.yaml (e.g., tools/hogli-commands/hogli_commands)
    2. Default: hogli/ folder next to hogli.yaml
    """
    manifest = get_manifest()
    commands_dir = manifest.commands_dir

    if not commands_dir:
        return

    # Skip if the commands package or any of its submodules is already in sys.modules.
    # Submodules are what carry `@cli.command` decorators, so re-importing would create
    # a second module object and duplicate registrations against different module
    # identities, which breaks test patches that target one path or the other.
    # NOTE: commands_dir should NOT be named "hogli" to avoid clobbering the hogli package
    package_name = commands_dir.name
    for mod_name in sys.modules:
        if mod_name == package_name or mod_name.startswith(package_name + "."):
            return

    # Add commands dir to path so imports work
    parent_dir = str(commands_dir.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    try:
        importlib.import_module(package_name)
        return
    except ModuleNotFoundError:
        # The package itself isn't importable via sys.path - fall back to file-spec load.
        # Narrower than ImportError so that a broken import *inside* the package
        # (e.g. a typo in one of its modules) still surfaces instead of being swallowed.
        pass

    # Fallback: manual load via file spec when the package isn't on sys.path in the normal sense
    init_file = commands_dir / "__init__.py"
    commands_file = commands_dir / "commands.py"

    if init_file.exists():
        spec = importlib.util.spec_from_file_location(
            package_name, init_file, submodule_search_locations=[str(commands_dir)]
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)
    elif commands_file.exists():
        spec = importlib.util.spec_from_file_location(f"{package_name}.commands", commands_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)


# Import custom commands from configured location
_import_custom_commands()


def _env_properties(command: str | None = None) -> dict[str, Any]:
    """Static environment properties shared across telemetry events."""
    ci_env_vars = ("CI", "GITHUB_ACTIONS", "JENKINS_URL", "GITLAB_CI", "CIRCLECI", "BUILDKITE")
    props: dict[str, Any] = {
        "terminal_width": shutil.get_terminal_size().columns,
        "os": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "is_ci": any(os.environ.get(v) for v in ci_env_vars),
    }
    for hook in telemetry_property_hooks:
        try:
            props.update(hook(command))
        except Exception:
            pass
    return props


def _fire_telemetry(ctx: click.Context, exit_code: int) -> None:
    """Send a command_completed telemetry event. Never raises."""
    command = ctx.invoked_subcommand
    # Skip when CLI itself errors before reaching a subcommand (e.g. bad flag)
    if command is None and exit_code != 0:
        return
    try:
        start_time: float = ctx.meta.get("hogli.start_time", 0.0)
        duration_s = _time.monotonic() - start_time
        props: dict[str, Any] = {
            "command": command,
            "command_category": get_category_for_command(command) if command else None,
            "duration_s": round(duration_s, 3),
            "exit_code": exit_code,
            "has_extra_argv": ctx.meta.get("hogli.has_extra_argv", False),
            **_env_properties(command),
        }
        # Merge devenv-specific properties (set by dev:generate)
        devenv = ctx.meta.get("hogli.devenv")
        if devenv:
            props.update(devenv)
        telemetry.track("command_completed", props)
    except Exception:
        pass


def _fire_post_command_hooks(command: str | None, exit_code: int) -> None:
    """Run registered post-command hooks. Never raises."""
    for hook in post_command_hooks:
        try:
            hook(command, exit_code)
        except Exception:
            pass


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
