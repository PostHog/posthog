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

For complex logic, define plain Click commands and reference them from `hogli.yaml` with `click: module.path:attribute`.

Click command modules are lazy-loaded. Top-level `hogli --help` uses the manifest description without importing Python command modules; `hogli <command> --help` and command execution import the target on demand.

The Click command name must match the manifest key — drift surfaces as a `ClickException` on resolution. The framework follows Click's recommendation that lazy loading be paired with a test that runs `--help` on each subcommand; PostHog's test suite parametrizes over every `click:` entry in `hogli.yaml` to do exactly that.

Mark commands hidden via `hidden: true` in `hogli.yaml`. Don't use `@click.command(hidden=True)` — the manifest is the single source of truth.

### Minimal: one importable package

```text
your-repo/
├── hogli.yaml
└── tools/
    └── hogli_commands/
        ├── __init__.py
        └── db.py
```

```yaml
# hogli.yaml
config:
  commands_dir: tools/hogli_commands

db:
  db:migrate:
    click: hogli_commands.db:db_migrate
    description: Run database migrations
```

```python
# tools/hogli_commands/db.py
import click

@click.command(name="db:migrate")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
def db_migrate(dry_run: bool) -> None:
    """Run database migrations."""
    if dry_run:
        click.echo("Would run migrations...")
    else:
        # Your migration logic here
        pass
```

`commands_dir` is optional and explicit: hogli only uses it when configured. It must be a relative path to an existing directory. hogli puts that directory's parent on `sys.path`, so the directory should be an importable package or module tree. It must not be named `hogli`, since that shadows the installed framework.

### Full: project package with submodules

For a larger command surface, keep the distribution/project directory separate from the import package:

```text
your-repo/
├── hogli.yaml
└── tools/
    └── hogli-commands/
        ├── pyproject.toml
        └── hogli_commands/    # underscored: this is the import name
            ├── __init__.py
            ├── build.py
            ├── db.py
            └── deploy.py
```

```yaml
# hogli.yaml
config:
  commands_dir: tools/hogli-commands/hogli_commands

build:
  build:
    click: hogli_commands.build:build
    description: Run build pipelines
```

The dashed outer dir + underscored inner package follows PEP 8 (dashed project name, underscored import name). This is the layout PostHog itself uses.

## Extension Hooks

Extensions can inject behavior at three framework call sites without forking. Register hooks from modules listed in `config.boot_modules`; those modules are imported once at startup, before command dispatch. Keep boot modules cheap to import and move heavy work inside hook functions. Exceptions raised by hooks are swallowed, so one extension can't break another.

```yaml
config:
  commands_dir: tools/hogli_commands
  boot_modules:
    - hogli_commands.boot
```

### Prechecks

Run validation before a command executes, keyed by `type:` in a `prechecks:` entry in `hogli.yaml`. Return `False` to abort, `True`/`None` to continue.

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
  prechecks:
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
  commands_dir: path/to/commands # Optional local Python command package
  boot_modules:
    - package.boot # Optional eager hook registration modules
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
- `hogli meta:check` - Validate manifest against bin scripts (for CI)
- `hogli meta:concepts` - Show infrastructure concepts (if defined)

## Requirements

- Python 3.10+
- click
- pyyaml

## Releasing

Releases are published to PyPI via `.github/workflows/publish-hogli.yml`,
triggered by pushing a `hogli-v*` tag from `master`.

1. Bump `version` in `tools/hogli/pyproject.toml` and merge to `master`.
2. From `master`, tag and push:

   ```bash
   git tag hogli-v0.1.1
   git push origin hogli-v0.1.1
   ```

The workflow verifies the tag matches the `pyproject.toml` version, builds
the sdist and wheel with `uv build`, smoke-tests the wheel in a fresh
venv, publishes via PyPI trusted publishing (OIDC) — no API tokens —
and creates a GitHub Release with auto-generated notes from the commits
since the previous tag.

To re-trigger after a failed publish, dispatch the workflow against the
existing tag — no need to retag:

```bash
gh workflow run publish-hogli.yml --ref hogli-v0.1.1
```

The publish job is guarded by `if: startsWith(github.ref, 'refs/tags/hogli-v')`,
so dispatches from a branch are no-ops.

## License

MIT
