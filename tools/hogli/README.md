# hogli

A developer CLI framework for defining commands in YAML. Think of it as "GitHub Actions for your local dev environment" - declarative, composable, and easy to maintain.

## Why hogli?

- **Declarative**: Define commands in YAML instead of scattered shell scripts
- **Composable**: Chain commands together with `steps`
- **Discoverable**: Auto-generated help with categories, `--help` on every command
- **Extensible**: Add complex commands in Python when YAML isn't enough

## Installation

```bash
pip install hogli
```

## Quick Start

Create `hogli.yaml` in your repo root:

```yaml
config:
  scripts_dir: bin # Where bin_script looks for scripts (default: bin/)

metadata:
  categories:
    - key: dev
      title: Development
    - key: test
      title: Testing

dev:
  dev:start:
    cmd: docker compose up -d && npm run dev
    description: Start development environment

  dev:reset:
    steps:
      - dev:stop
      - dev:clean
      - dev:start
    description: Full environment reset

test:
  test:unit:
    cmd: pytest tests/unit
    description: Run unit tests
```

Run commands:

```bash
hogli dev:start
hogli --help        # Shows all commands grouped by category
hogli dev:start -h  # Help for specific command
```

## Command Types

### Shell commands (`cmd`)

Run shell commands directly. Supports shell operators (`&&`, `||`, `|`):

```yaml
build:
  cmd: npm run build && npm run test
  description: Build and test
```

### Script delegation (`bin_script`)

Delegate to scripts in your `scripts_dir`:

```yaml
deploy:
  bin_script: deploy.sh
  description: Deploy to production
```

### Composite commands (`steps`)

Chain multiple hogli commands:

```yaml
release:
  steps:
    - test:all
    - build
    - deploy
  description: Full release pipeline
```

Steps can also include inline commands:

```yaml
setup:
  steps:
    - name: Install deps
      cmd: npm install
    - name: Build
      cmd: npm run build
    - test:unit
```

## Command Options

```yaml
my:command:
  cmd: echo "hello"
  description: Short description for --help
  destructive: true # Prompts for confirmation before running
  hidden: true # Hides from --help (still runnable)
```

## Python Commands

For complex logic, create Python commands using Click. Two layouts are supported — pick based on how many commands you have.

The directory name is yours to choose. PostHog uses `hogli-commands` (and the examples below follow that). One constraint: it **must not** be named `hogli`, since that shadows the installed framework and your commands will be silently ignored.

### Minimal: single file (recommended for most repos)

A handful of commands needs nothing more than one `commands.py`:

```text
your-repo/
├── hogli.yaml
└── tools/
    └── hogli-commands/
        └── commands.py
```

```yaml
# hogli.yaml
config:
  commands_dir: tools/hogli-commands
```

```python
# tools/hogli-commands/commands.py
import click
from hogli.cli import cli

@cli.command(name="db:migrate")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
def db_migrate(dry_run: bool) -> None:
    """Run database migrations."""
    if dry_run:
        click.echo("Would run migrations...")
    else:
        # Your migration logic here
        pass
```

The directory can live anywhere `hogli.yaml` can reference — `tools/hogli-commands/` fits a monorepo with a `tools/` convention, but a top-level `hogli-commands/` or any other path works equally well.

### Full: package with submodules (for larger surfaces)

When commands grow past one file and need to import each other, promote to a package. Add an inner `hogli_commands/` directory with `__init__.py` and split commands into submodules; `commands.py` becomes the registration entry point that imports them for side-effects:

```text
your-repo/
├── hogli.yaml
└── tools/
    └── hogli-commands/
        └── hogli_commands/    # underscored: this is the import name
            ├── __init__.py
            ├── commands.py    # `from . import build, db, deploy`
            ├── build.py
            ├── db.py
            └── deploy.py
```

```yaml
# hogli.yaml
config:
  commands_dir: tools/hogli-commands/hogli_commands
```

The dashed outer dir + underscored inner package follows PEP 8 (dashed project name, underscored import name). This is the layout PostHog itself uses.

## Extension Hooks

Extensions can inject behavior at three framework call sites without forking. Register from a module that runs at command-load time (e.g. your `commands_dir` package's `__init__.py` or `commands.py`). Exceptions raised by hooks are swallowed — one extension can't break another.

### Prechecks

Run validation before a command executes, keyed by `type:` in a `precheck:` entry in `hogli.yaml`. Return `False` to abort, `True`/`None` to continue.

```python
from hogli.hooks import register_precheck

def check_migrations(check: dict, yes: bool) -> bool | None:
    # inspect check config, prompt user, decide
    return None

register_precheck("migrations", check_migrations)
```

```yaml
dev:start:
  cmd: docker compose up -d
  precheck:
    - type: migrations
```

### Telemetry properties

Inject extra key/value pairs into the `command_completed` telemetry event. Receives the invoked command name.

```python
from hogli.hooks import register_telemetry_properties

def env_props(command: str | None) -> dict[str, object]:
    return {"in_my_env": True}

register_telemetry_properties(env_props)
```

### Post-command hooks

Run after every command completes, regardless of success. Good for contextual hints, cleanup, or notifications.

```python
from hogli.hooks import register_post_command_hook

def maybe_show_hint(command: str | None, exit_code: int) -> None:
    if exit_code == 0:
        ...

register_post_command_hook(maybe_show_hint)
```

## Configuration Reference

```yaml
config:
  commands_dir: path/to/commands # Python commands directory (default: hogli/)
  scripts_dir: scripts # For bin_script resolution (default: bin/)

metadata:
  categories:
    - key: dev
      title: Development Commands
    - key: test
      title: Test Commands
```

## Built-in Commands

- `hogli quickstart` - Getting started guide
- `hogli meta:check` - Validate manifest, find undocumented scripts
- `hogli meta:concepts` - Show infrastructure concepts (if defined)

## Requirements

- Python 3.10+
- click
- pyyaml

## License

MIT
