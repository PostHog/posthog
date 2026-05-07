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
from collections import defaultdict
from typing import Any

import click

from hogli import telemetry
from hogli.command_types import BinScriptCommand, CompositeCommand, DirectCommand, HogliCommand
from hogli.hooks import post_command_hooks, telemetry_property_hooks
from hogli.lazy_commands import add_commands_dir_to_path, add_repo_root_to_path, resolve_click_command
from hogli.manifest import REPO_ROOT, get_category_for_command, get_manifest, get_services_for_command, load_manifest
from hogli.validate import auto_update_manifest, find_missing_manifest_entries

_DEFAULT_HELP = "Developer CLI framework with YAML-based command definitions."


class CategorizedGroup(click.Group):
    """Custom Click group that formats help output like git help with categories.

    Overrides ``invoke`` to wrap every subcommand execution with telemetry
    tracking (timing, exit code) using ``ctx.meta`` for state instead of a
    module-level singleton.
    """

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command

        config = get_manifest().get_command_config(cmd_name)
        if not config or "click" not in config:
            return None

        return resolve_click_command(cmd_name, config["click"])

    def list_commands(self, ctx: click.Context) -> list[str]:
        manifest_obj = get_manifest()
        commands = {name for name in super().list_commands(ctx) if not manifest_obj.is_command_hidden(name)}
        for cmd_name in manifest_obj.get_all_commands():
            config = manifest_obj.get_command_config(cmd_name)
            if config and "click" in config and not manifest_obj.is_command_hidden(cmd_name):
                commands.add(cmd_name)
        return sorted(commands)

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
        child_commands = {
            child
            for parent in manifest_obj.get_all_commands()
            for child in manifest_obj.get_children_for_command(parent)
        }

        # Group commands by category, storing (key, title) tuple
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        grouped_command_names: set[str] = set()
        for cmd_name, cmd in self.commands.items():
            # Skip hidden commands (they're still callable, just not shown in help)
            if manifest_obj.is_command_hidden(cmd_name):
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
            grouped_command_names.add(cmd_name)

        for cmd_name in manifest_obj.get_all_commands():
            config = manifest_obj.get_command_config(cmd_name)
            if not config or "click" not in config or manifest_obj.is_command_hidden(cmd_name):
                continue
            if cmd_name in grouped_command_names or cmd_name in child_commands:
                continue

            category_title = get_category_for_command(cmd_name)
            category_key = next(
                (key for key, title in category_key_to_title.items() if title == category_title), "commands"
            )
            grouped[(category_key, category_title)].append((cmd_name, config.get("description", "")))
            grouped_command_names.add(cmd_name)

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

    Supports four eagerly registered entry types:
    1. ``steps:`` — compose multiple hogli commands in sequence.
    2. ``cmd:`` — execute a direct shell command.
    3. ``hogli:`` — wrap another hogli command with extra args.
    4. ``bin_script:`` — delegate to a shell script in ``config.scripts_dir``.

    ``click:`` entries are resolved lazily by ``CategorizedGroup.get_command``.
    """
    manifest = get_manifest()
    scripts_dir = manifest.scripts_dir

    for _category, scripts in manifest.data.items():
        if not isinstance(scripts, dict):
            continue

        for cli_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            steps = config.get("steps")
            cmd = config.get("cmd")
            hogli = config.get("hogli")
            bin_script = config.get("bin_script")

            if "click" in config:
                continue

            if steps:
                CompositeCommand(cli_name, config).register(cli)
                continue

            if cmd:
                DirectCommand(cli_name, config).register(cli)
                continue

            if hogli:
                HogliCommand(cli_name, config).register(cli)
                continue

            if bin_script:
                script_path = scripts_dir / bin_script
                if script_path.exists():
                    BinScriptCommand(cli_name, config, script_path).register(cli)


def _load_boot_modules() -> None:
    """Import modules listed in ``config.boot_modules`` once at startup.

    Boot modules register precheck handlers, telemetry property hooks, and
    post-command hooks against ``hogli.hooks``. They run eagerly so the hooks
    are populated before the first command dispatches. They must be cheap to
    import — keep heavy work behind lazy imports inside handler bodies. Any
    import failure aborts hogli, so these are validated implicitly by every
    test that invokes the CLI.
    """
    manifest = get_manifest()
    add_repo_root_to_path(REPO_ROOT)
    add_commands_dir_to_path(manifest.commands_dir)

    for module_path in manifest.config.get("boot_modules", []):
        if module_path not in sys.modules:
            importlib.import_module(module_path)


# Register all script commands from manifest, then trigger boot modules so
# any framework-extension hooks (prechecks, telemetry props, post-command
# hints) are registered before the first command runs.
_register_script_commands()
_load_boot_modules()


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
