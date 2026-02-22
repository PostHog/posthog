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
    scripts_dir: bin  # Where bin_script looks for scripts (default: bin/)

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
    destructive: true   # Prompts for confirmation before running
    hidden: true        # Hides from --help (still runnable)
```

## Python Commands

For complex logic, create Python commands using Click. Create a `commands.py` (or `__init__.py`) in your commands directory:

```python
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

Configure the location in `hogli.yaml`:

```yaml
config:
    commands_dir: tools/cli  # Defaults to hogli/ next to hogli.yaml
```

## Configuration Reference

```yaml
config:
    commands_dir: path/to/commands  # Python commands directory (default: hogli/)
    scripts_dir: scripts            # For bin_script resolution (default: bin/)

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
