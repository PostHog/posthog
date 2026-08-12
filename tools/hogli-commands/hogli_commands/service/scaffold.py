from __future__ import annotations

import re
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_ROOT = Path(__file__).parent / "template"
VALID_SERVICE_NAME = re.compile(r"^[a-z](?:[a-z0-9-]*[a-z0-9])?$")


def _render(content: str, service_name: str) -> str:
    return content.replace("__SERVICE_NAME__", service_name)


def _register_workspace(workspace_file: Path, service_name: str) -> None:
    entry = f"    - services/{service_name}"
    lines = workspace_file.read_text().splitlines()
    if entry in lines:
        return

    service_indices = [index for index, line in enumerate(lines) if line.startswith("    - services/")]
    if not service_indices:
        raise click.ClickException("Could not find the services workspace entries in pnpm-workspace.yaml")

    lines.insert(service_indices[-1] + 1, entry)
    workspace_file.write_text("\n".join(lines) + "\n")


def _register_docker_context(dockerignore_file: Path, service_name: str) -> None:
    entry = f"!services/{service_name}"
    lines = dockerignore_file.read_text().splitlines()
    if entry in lines:
        return

    service_indices = [index for index, line in enumerate(lines) if line.startswith("!services/")]
    if not service_indices:
        raise click.ClickException("Could not find the service entries in .dockerignore")

    lines.insert(service_indices[-1] + 1, entry)
    dockerignore_file.write_text("\n".join(lines) + "\n")


def bootstrap_service(
    *,
    name: str,
    dry_run: bool,
    force: bool,
    repo_root: Path = REPO_ROOT,
    template_root: Path = TEMPLATE_ROOT,
) -> None:
    if not VALID_SERVICE_NAME.fullmatch(name):
        raise click.ClickException(
            f"Invalid service name '{name}'. Use lowercase letters, numbers, and hyphens, starting with a letter."
        )

    service_directory = repo_root / "services" / name
    if service_directory.exists() and not force:
        raise click.ClickException(
            f"Service '{name}' already exists at {service_directory}. Use --force to overwrite it."
        )

    template_files = sorted(path for path in template_root.rglob("*") if path.is_file() and not path.is_symlink())
    relative_files = [path.relative_to(template_root) for path in template_files]

    if dry_run:
        click.echo(f"Would create service '{name}' at {service_directory}")
        for relative_path in [*relative_files, Path("CLAUDE.md")]:
            click.echo(f"  {relative_path}")
        return

    for template_file, relative_path in zip(template_files, relative_files, strict=True):
        destination = service_directory / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_render(template_file.read_text(), name))

    claude_file = service_directory / "CLAUDE.md"
    if claude_file.exists() or claude_file.is_symlink():
        claude_file.unlink()
    claude_file.symlink_to("AGENTS.md")

    _register_workspace(repo_root / "pnpm-workspace.yaml", name)
    _register_docker_context(repo_root / ".dockerignore", name)

    click.echo(f"Created service '{name}' at {service_directory}")
    click.echo(f"Run `pnpm install` and `pnpm --filter=@posthog/{name} test` next.")
