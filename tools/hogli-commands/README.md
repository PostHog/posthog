# PostHog Custom Commands

Custom Python commands for the PostHog monorepo. They extend hogli with PostHog-specific functionality that's too complex for YAML definitions.

## How It Works

Each command module is imported **on first use**, not at hogli startup. The hogli framework reads `config.commands_dir` from `/hogli.yaml`; manifest entries with a `click:` field are resolved by Click when the user invokes the command or runs per-command `--help`.

Boot-time registrations (precheck handlers, telemetry hooks, post-command hooks) live in their own modules listed under `config.boot_modules:` in `hogli.yaml`. Those modules **must** be cheap to import — keep heavy dependencies behind deferred imports inside handler bodies.

## Adding a Command

1. Create or edit a module with a plain `@click.command(...)` decorator (no need to import or reference hogli's `cli` group):

```python
# myfeature.py
import click

@click.command(name="my:command")
@click.option("--verbose", "-v", is_flag=True)
def my_command(verbose: bool) -> None:
    """One-line description shown in hogli --help."""
    click.echo("Done!")
```

2. Add an entry to `hogli.yaml` in the appropriate category section:

```yaml
tools:
  my:command:
    click: hogli_commands.myfeature:my_command
    description: One-line summary shown in `hogli --help`.
```

The Click command name must match the manifest key — drift surfaces as a `ClickException` on resolution. The hogli test suite parametrizes a `--help` invocation over every `click:` entry, which is Click's recommended sanity check.

Mark a command hidden by setting `hidden: true` on the manifest entry. Don't use `@click.command(hidden=True)`; the manifest is the only source of truth.

3. Test it:

```bash
hogli my:command --help
hogli my:command -v
```

That's it. No side-effect imports, no central registration list to maintain.

## Boot Modules

`config.boot_modules` in `hogli.yaml` lists modules imported once at startup. They register hooks via `hogli.hooks`:

- `hogli_commands.prechecks` — declares the `migrations` precheck (used by `dev:start`).
- `hogli_commands.telemetry_props` — adds PostHog environment props (`in_flox`, `is_worktree`, `is_posthog_dev`, `process_manager`, `has_devenv_config`) to every `command_completed` event.
- `hogli_commands.hint_hook` — shows a contextual hint after successful commands.

Add a new boot module by creating a file that calls one of the `register_*` helpers from `hogli.hooks` at import time, then list it under `config.boot_modules:`. Keep these modules import-light: the precheck handler in `prechecks.py` is the canonical example of deferring its heavy import until the handler actually fires.

## When to Use Python vs YAML

| Use Python here when...            | Use YAML (`hogli.yaml`) when...  |
| ---------------------------------- | -------------------------------- |
| Complex logic, loops, conditionals | Simple shell one-liners          |
| Need Click's argument parsing      | Delegating to bin/ scripts       |
| Interactive prompts or menus       | Chaining existing hogli commands |
| Accessing Python libraries         | Quick prototypes                 |

## File Structure

```text
tools/hogli-commands/
└── hogli_commands/
    ├── __init__.py       # Only the common/ sys.path workaround
    ├── prechecks.py      # Boot module — registers the migrations precheck
    ├── telemetry_props.py# Boot module — registers PostHog telemetry props
    ├── hint_hook.py      # Boot module — registers the post-command hint hook
    ├── build.py          # Lazy: hogli build
    ├── doctor.py         # Lazy: hogli doctor / doctor:disk / doctor:zombies
    ├── ...               # Other lazy command modules
    ├── devbox/           # Devbox subpackage (lazy)
    ├── devenv/           # Intent-based dev environment subpackage (lazy)
    └── product/          # Product scaffolding subpackage (lazy)
```

This directory is not packaged or installed — the hogli framework loads `hogli_commands` from disk at runtime via `config.commands_dir` in `/hogli.yaml`. Runtime dependencies (`click`, `pyyaml`, `pydantic`, `requests`) are declared in the root `/pyproject.toml` alongside the rest of the monorepo.

## Tips

- Use `click.echo()` for output, not `print()`
- Use `click.secho(msg, fg="green")` for colored output
- Add `@click.option("--yes", "-y", is_flag=True)` for destructive commands
- Keep commands focused — compose via YAML `steps:` if needed

## See Also

- `/hogli.yaml` — manifest with category placement, lazy `click:` import paths, and `boot_modules:` list
- `/tools/hogli/README.md` — framework documentation (command registry, hooks API)
- `/bin/` — shell scripts (referenced via `bin_script:` in YAML)
