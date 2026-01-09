# hogli

Developer CLI framework with YAML-based command definitions.

## Installation

```bash
pip install hogli
```

## Quick Start

1. Create `hogli.yaml` in your repo root:

```yaml
dev:
    dev:start:
        cmd: docker compose up -d && npm run dev
        description: Start development environment

    dev:reset:
        steps:
            - dev:stop
            - dev:clean
            - dev:start
        description: Full reset

test:
    test:unit:
        cmd: pytest tests/unit
        description: Run unit tests
```

2. Run commands:

```bash
hogli dev:start
hogli test:unit
hogli --help
```

## Command Types

### Direct commands (`cmd`)

Execute shell commands directly:

```yaml
build:
    cmd: npm run build
    description: Build the project
```

### Script delegation (`bin_script`)

Delegate to a script in your scripts directory (default: `bin/`):

```yaml
deploy:
    bin_script: deploy.sh
    description: Deploy to production
```

Scripts are resolved relative to `config.scripts_dir` (see Configuration below).

### Composite commands (`steps`)

Run multiple hogli commands in sequence:

```yaml
release:
    steps:
        - test:all
        - build
        - deploy
    description: Full release pipeline
```

## Custom Python Commands

Create `hogli/` folder next to `hogli.yaml` with Click commands:

```python
# hogli/commands.py
import click
from hogli.cli import cli

@cli.command(name="my:thing")
def my_thing():
    """Custom command."""
    click.echo("Hello!")
```

## Configuration

```yaml
config:
    commands_dir: path/to/custom/commands  # Custom Python commands, defaults to hogli/
    scripts_dir: scripts                    # For bin_script commands, defaults to bin/

metadata:
    categories:
        - key: dev
          title: Development
        - key: test
          title: Testing
```

## Script Discovery

hogli can auto-discover executable scripts in your `scripts_dir` that aren't yet in the manifest:

```bash
hogli meta:check  # Shows scripts missing from manifest
```

This helps keep your manifest in sync with available scripts.

## License

MIT
