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
import functools
import importlib
import importlib.metadata
from collections import defaultdict
from pathlib import Path
from typing import Any

import click

from hogli import telemetry
from hogli.command_types import BinScriptCommand, CompositeCommand, DirectCommand, HogliCommand
from hogli.hooks import post_command_hooks, telemetry_property_hooks
from hogli.lazy_commands import add_commands_dir_to_path, add_repo_root_to_path, resolve_click_command
from hogli.manifest import (
    REPO_ROOT,
    Manifest,
    get_category_for_command,
    get_manifest,
    get_services_for_command,
    load_manifest,
)
from hogli.validate import auto_update_manifest, find_missing_manifest_entries, find_orphan_manifest_entries

_DEFAULT_HELP = "Developer CLI framework with YAML-based command definitions."

# Sentinel inherited by subprocesses so nested hogli invocations (composite
# steps, prechecks, process managers re-running hogli) can be told apart in
# telemetry. is_nested means "descends from a hogli process tree" -- a human
# typing hogli inside a shell that hogli spawned (flox:activate, sandbox)
# counts as nested too. Captured at import, before this process sets the
# sentinel for its own children.
_NESTED_INVOCATION_VAR = "HOGLI_NESTED_INVOCATION"
_IS_NESTED = _NESTED_INVOCATION_VAR in os.environ


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
            try:
                telemetry.flush()
            except Exception:
                pass
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
    # Defensive: skip env loading in resilient-parsing (completion) contexts.
    # click builds those contexts without invoking callbacks, so this guard is
    # belt-and-braces, not load-bearing.
    if not ctx.resilient_parsing:
        _apply_env_config(ctx.invoked_subcommand)
    # Auto-update manifest on every invocation (but skip for meta:check and git hooks)
    # Skip during git hooks to prevent manifest modifications during lint-staged execution
    in_git_hook = os.environ.get("GIT_DIR") is not None or os.environ.get("HUSKY") is not None
    if ctx.invoked_subcommand not in {"meta:check", "help"} and not in_git_hook:
        _auto_update_manifest()
        # telemetry:on still shows the notice (it arms tracking by setting
        # first_run_notice_shown); only off/status suppress it.
        if ctx.invoked_subcommand not in {"telemetry:off", "telemetry:status"}:
            telemetry.show_first_run_notice_if_needed()

    # Set before the send thread spawns below: mutating the environment while
    # another thread sits in C-level getenv (resolver, OpenSSL) is undefined
    # behavior on POSIX.
    os.environ[_NESTED_INVOCATION_VAR] = "1"

    # Fire early so long-running commands (e.g. hogli start) are counted even
    # on a hard kill (see flush_async). The gate decision is stashed so
    # command_completed reuses it: evaluating it again at command end could
    # disagree (config flipped mid-run) and unpair the events.
    ctx.meta["hogli.telemetry_active"] = _telemetry_active(ctx.invoked_subcommand)
    if ctx.meta["hogli.telemetry_active"]:
        try:
            telemetry.track(
                "command_started", {"command": ctx.invoked_subcommand, **_env_properties(ctx.invoked_subcommand)}
            )
            telemetry.flush_async()
        except Exception:
            pass


@cli.command(name="telemetry:on", help="Enable anonymous usage telemetry")
def telemetry_on() -> None:
    telemetry.set_enabled(True)
    click.echo("Telemetry enabled. Thank you for helping improve hogli!")


@cli.command(name="telemetry:off", help="Disable anonymous usage telemetry")
def telemetry_off() -> None:
    telemetry.set_enabled(False)
    click.echo("Telemetry disabled.")


@cli.command(name="telemetry:status", help="Show current telemetry settings")
def telemetry_status() -> None:
    enabled = telemetry.is_enabled()
    config_path = telemetry.get_config_path()

    if enabled and not telemetry.is_active():
        # Enabled but the first-run notice flag never persisted (fresh or
        # read-only HOME): nothing sends until the notice is shown.
        click.echo("Telemetry: enabled (pending first-run notice -- shown on your next tracked command)")
    else:
        click.echo(f"Telemetry: {'enabled' if enabled else 'disabled'}")

    # Show which mechanism controls the state
    if telemetry.is_ci():
        click.echo("Controlled by: CI environment detected")
    elif os.environ.get("POSTHOG_TELEMETRY_OPT_OUT") == "1":
        click.echo("Controlled by: POSTHOG_TELEMETRY_OPT_OUT=1")
    elif os.environ.get("DO_NOT_TRACK") == "1":
        click.echo("Controlled by: DO_NOT_TRACK=1")
    else:
        click.echo("Controlled by: config file")

    if enabled:
        click.echo(f"Anonymous ID: {telemetry.get_anonymous_id()}")
    else:
        click.echo("Anonymous ID: (not generated -- telemetry disabled)")
    click.echo(f"Config path: {config_path}")


@cli.command(name="meta:check", help="Validate manifest against bin scripts (for CI)")
def meta_check() -> None:
    """Validate that bin scripts and manifest entries stay in sync."""
    missing = find_missing_manifest_entries()
    orphans = find_orphan_manifest_entries()

    if not missing and not orphans:
        click.echo("✓ All bin scripts are in the manifest and all manifest entries resolve")
        return

    if missing:
        click.echo(f"✗ Found {len(missing)} bin script(s) not in manifest:")
        for script in sorted(missing):
            click.echo(f"  - {script}")
    if orphans:
        click.echo(f"✗ Found {len(orphans)} manifest entr(ies) with no matching bin script:")
        for cmd in sorted(orphans):
            click.echo(f"  - {cmd}")

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


# Sentinel that prevents `_apply_env_config` from re-execing into the wrap
# command in an infinite loop. Set by hogli right before exec'ing the wrap
# binary; checked at the top of `_apply_env_config` on subsequent invocations.
_SECRETS_WRAPPED_ENV = "HOGLI_SECRETS_WRAPPED"

# Substituted to the absolute path of the secrets file when building the wrap
# argv. Kept as a constant so the README, AGENTS.md, and runtime stay in sync.
_WRAP_FILE_PLACEHOLDER = "{file}"

# Built-in commands whose contract is "forward the resolved env" (e.g.
# `hogli run`). Manifest commands opt in via `needs_secrets: true`.
_BUILTIN_COMMANDS_NEEDING_SECRETS = frozenset({"run"})

# False until `main()` flips it (the only path the `hogli` script and
# `python -m hogli` both take). The secret-wrap re-exec is gated on it; see
# `_maybe_reexec_via_wrap` for why embedded callers must not execvp.
_is_process_entrypoint = False


def _load_env_file(
    path: os.PathLike[str],
    only_if_unset: bool = True,
    skip_pattern: str | None = None,
) -> None:
    """Load environment variables from a dotenv file (KEY=VALUE, # comments).

    Args:
        path: Path to the env file. Missing files are silently skipped
            (matches just/mise/task convention so optional `.env.local` etc.
            don't error).
        only_if_unset: If True (default), don't overwrite existing env vars.
            Lets shell env always win.
        skip_pattern: If set, any line whose VALUE substring-matches this
            pattern is skipped entirely. Used to keep secret-reference lines
            (e.g. `op://...`) from leaking into the environment as literal
            strings when the resolver isn't available. None disables filtering.
    """
    env_file = Path(path)
    if not env_file.exists():
        return

    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if skip_pattern and skip_pattern in value:
            continue
        if only_if_unset and name in os.environ:
            continue
        os.environ[name] = value


def _apply_env_config(invoked_subcommand: str | None = None) -> None:
    """Apply ``config.env`` from hogli.yaml: load files, optionally re-exec via wrap.

    - No ``config.env``: no-op.
    - ``config.env.files``: each file loaded with only_if_unset=True; first
      listed wins for duplicate keys; shell env always wins.
    - ``config.env.secrets``: secrets file. Wrap re-exec is gated on
      ``_command_needs_secrets`` — when open, the file exists, the marker
      matches, and ``wrap[0]`` is on PATH, set the ``HOGLI_SECRETS_WRAPPED``
      sentinel and ``execvp`` into the wrap (which re-runs hogli with
      secrets resolved). Otherwise load the file directly with
      marker-matching lines skipped, so unresolved refs don't leak as
      literal env values.

    Precedence (highest wins): shell env > secrets file > env files.
    """
    manifest = get_manifest()
    try:
        secrets = manifest.secrets_config
        env_files = manifest.env_files
    except ValueError as e:
        click.echo(f"⚠️  Invalid config.env in hogli.yaml: {e}", err=True)
        return

    # Don't pop: subprocesses spawned by composite/steps commands need to
    # inherit this so they skip a redundant wrap re-exec. In-process callers
    # that want to retrigger the wrap must clear it themselves.
    already_wrapped = _SECRETS_WRAPPED_ENV in os.environ

    if secrets is not None and not already_wrapped:
        if _command_needs_secrets(invoked_subcommand, manifest):
            _maybe_reexec_via_wrap(secrets, env_files)

        # Load secrets BEFORE env_files so .env.local literals override
        # .env.development / .env.services — matches the wrap-resolved
        # path's precedence (where op layers .env.local on top).
        _load_env_file(secrets["file"], only_if_unset=True, skip_pattern=secrets["marker"])

    for path in env_files:
        _load_env_file(path, only_if_unset=True)


def _command_needs_secrets(invoked_subcommand: str | None, manifest: Manifest) -> bool:
    """Whether the invoked command opts into the secret wrap.

    Two sources, in order: built-in framework commands
    (``_BUILTIN_COMMANDS_NEEDING_SECRETS``), then ``needs_secrets: true`` on
    the manifest entry. Default False — most commands don't need secrets and
    shouldn't pay the wrap cost.
    """
    if not invoked_subcommand:
        return False
    if invoked_subcommand in _BUILTIN_COMMANDS_NEEDING_SECRETS:
        return True
    return manifest.command_flag(invoked_subcommand, "needs_secrets")


def _maybe_reexec_via_wrap(secrets: dict[str, Any], env_files: list[Path]) -> None:
    """Re-exec hogli under the configured wrap command if the secrets file warrants it.

    Returns normally if no re-exec is needed (caller falls through to direct
    file loading). Otherwise replaces the current process via ``os.execvp``.

    Only ever re-execs when hogli owns the process (``_is_process_entrypoint``).
    Embedded in-process callers (CliRunner tests, library use) fall through to
    direct file loading so execvp can't replace and kill the host process.
    """
    if not _is_process_entrypoint:
        return

    secrets_file: Path = secrets["file"]
    marker: str = secrets["marker"]
    wrap: list[str] | None = secrets["wrap"]

    if wrap is None or not secrets_file.exists():
        return

    # Marker-gated re-exec: only wrap when the file actually references the
    # external resolver. Saves a process exec on dev workflows that haven't
    # set up secrets yet.
    try:
        if marker not in secrets_file.read_text():
            return
    except OSError:
        return

    wrap_binary = wrap[0]
    if not shutil.which(wrap_binary):
        click.echo(
            f"⚠️  {secrets_file.name} contains '{marker}' refs but the configured wrap binary "
            f"'{wrap_binary}' is not on PATH.",
            err=True,
        )
        click.echo(
            f"   Refs will be skipped — services that need them will fail with their own errors. "
            f"Install '{wrap_binary}' or replace the refs with literal values in {secrets_file.name}.",
            err=True,
        )
        return

    # Pre-load non-secrets files so the wrap binary's child inherits them.
    # The wrap binary layers secrets on top, overriding these for any key
    # also defined in the secrets file.
    for path in env_files:
        _load_env_file(path, only_if_unset=True)

    resolved_wrap = [arg.replace(_WRAP_FILE_PLACEHOLDER, str(secrets_file)) for arg in wrap]
    os.environ[_SECRETS_WRAPPED_ENV] = "1"
    os.execvp(resolved_wrap[0], [*resolved_wrap, sys.executable, "-m", "hogli", *sys.argv[1:]])


@cli.command(name="run", help="Run a command with the manifest's resolved environment")
@click.argument("command", nargs=-1, required=True)
def run_with_env(command: tuple[str, ...]) -> None:
    """Run a command with the env loaded from ``config.env`` in hogli.yaml.

    Env loading (files + optional wrap) is applied by the parent ``cli()``
    group before this command runs, so by the time we get here ``os.environ``
    already reflects whatever the manifest declared. This command is just a
    thin ``execvp`` so callers don't need to repeat the wrapper pattern.

    Examples:
        hogli run ./manage.py shell
        hogli run pytest posthog/api/
    """
    os.execvp(command[0], list(command))


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


@functools.cache
def _hogli_version() -> str | None:
    try:
        return importlib.metadata.version("hogli")
    except importlib.metadata.PackageNotFoundError:
        return None


def _env_properties(command: str | None = None) -> dict[str, Any]:
    """Static environment properties shared across telemetry events."""
    props: dict[str, Any] = {
        "terminal_width": shutil.get_terminal_size().columns,
        "os": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "hogli_version": _hogli_version(),
        "is_ci": telemetry.is_ci(),
        "is_nested": _IS_NESTED,
    }
    for hook in telemetry_property_hooks:
        try:
            props.update(hook(command))
        except Exception:
            pass
    return props


# Core builtins exempt from telemetry: the telemetry:* management commands
# would pollute the dataset with self-referential noise, and `run`
# exec-replaces the process (os.execvp), so its started/completed events could
# never pair. Mirrors _BUILTIN_COMMANDS_NEEDING_SECRETS -- manifest-declared
# commands opt out the same way via `untracked: true` (e.g. exec-style devbox
# commands), so consumer command names stay out of core.
_UNTRACKED_BUILTINS = frozenset({"telemetry:on", "telemetry:off", "telemetry:status", "run"})


def _should_track(command: str | None) -> bool:
    """Whether a subcommand should emit command_started / command_completed.

    Requires a real subcommand (so bare ``hogli`` / ``--help`` don't fire a
    completed event with no matching started event), excludes the untracked
    core builtins, and honors a manifest-level ``untracked: true``.
    """
    if not command or command in _UNTRACKED_BUILTINS:
        return False
    return not get_manifest().command_flag(command, "untracked")


def _telemetry_active(command: str | None) -> bool:
    """Gate for command_started / command_completed -- identical for both so
    the events pair under stable config.

    Checked before property computation: the property hooks fork subprocesses,
    which inactive paths (CI, opt-outs, unconfigured HOMEs) shouldn't pay for.
    Never raises -- telemetry must not break commands.
    """
    try:
        return _should_track(command) and telemetry.is_active()
    except Exception:
        return False


def _outcome(exit_code: int) -> str:
    """Classify an exit code so signal kills are distinct from real failures."""
    if exit_code == 0:
        return "success"
    # Killed by a signal: a negative subprocess returncode, or the shell's
    # 128 + signum convention (e.g. 130 SIGINT). Exactly 128 is excluded -- it's
    # an application-error idiom (e.g. git's fatal errors), not a signal.
    if exit_code < 0 or exit_code > 128:
        return "interrupted"
    return "error"


def _fire_telemetry(ctx: click.Context, exit_code: int) -> None:
    """Send a command_completed telemetry event. Never raises."""
    command = ctx.invoked_subcommand
    # Reuse the gate decision made at command start (fail closed if the group
    # callback never ran) so started/completed pair even if config flips mid-run.
    if not ctx.meta.get("hogli.telemetry_active", False):
        return
    try:
        start_time: float = ctx.meta.get("hogli.start_time", 0.0)
        duration_s = _time.monotonic() - start_time
        props: dict[str, Any] = {
            "command": command,
            "command_category": get_category_for_command(command),
            "duration_s": round(duration_s, 3),
            "exit_code": exit_code,
            "outcome": _outcome(exit_code),
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
    """Main entry point — the only path allowed to re-exec via the secret wrap."""
    global _is_process_entrypoint
    _is_process_entrypoint = True
    cli()


if __name__ == "__main__":
    main()
