from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_BLOCK_START = "# secure-connections-demo:start"
ENV_BLOCK_END = "# secure-connections-demo:end"
DEMO_ENVIRONMENT = {
    "SECURE_CONNECTION_MANAGEMENT_URL": "http://127.0.0.1:18081",
    "SECURE_CONNECTION_CONTROL_URL": "http://127.0.0.1:18081",
    "SECURE_CONNECTION_PUBLIC_CONTROL_URL": "http://burrow:8080",
    "SECURE_CONNECTION_ADMIN_TOKEN": "demo-admin-token",
    "SECURE_CONNECTION_DEMO_TENANT_SLUG": "acme",
}


def find_burrow_repo(explicit_path: Path | None = None) -> Path:
    candidates = [
        explicit_path,
        Path(os.environ["BURROW_REPO"]) if os.environ.get("BURROW_REPO") else None,
        REPO_ROOT.parent / "burrow",
    ]
    for candidate in candidates:
        if candidate and (candidate / "test/demo/run.sh").is_file():
            return candidate.resolve()
    raise click.ClickException(
        "Could not find the Burrow repository. Clone it next to the PostHog repository or pass --burrow-path."
    )


def update_demo_environment(env_file: Path, *, enabled: bool) -> None:
    existing = env_file.read_text() if env_file.exists() else ""
    before, marker, remainder = existing.partition(ENV_BLOCK_START)
    if marker:
        _, end_marker, after = remainder.partition(ENV_BLOCK_END)
        if not end_marker:
            raise click.ClickException(f"Could not update {env_file}: the secure connections demo block is incomplete.")
        existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
    else:
        existing = existing.strip()

    if enabled:
        values = "\n".join(f"{key}={value}" for key, value in DEMO_ENVIRONMENT.items())
        block = f"{ENV_BLOCK_START}\n{values}\n{ENV_BLOCK_END}"
        existing = f"{existing}\n\n{block}".strip()

    env_file.write_text(f"{existing}\n" if existing else "")


def run_demo_command(burrow_repo: Path, action: str) -> None:
    make_target = {
        "start": "demo",
        "test": "demo-test",
        "env": "demo-env",
        "stop": "demo-down",
    }[action]
    subprocess.run(["make", make_target], cwd=burrow_repo, check=True)


@click.command(name="secure-connections:demo")
@click.argument("action", type=click.Choice(["start", "test", "env", "stop"]), default="start")
@click.option(
    "--burrow-path",
    type=click.Path(path_type=Path, file_okay=False),
    help="Path to a Burrow checkout. Defaults to a sibling of the PostHog repository.",
)
def secure_connections_demo(action: str, burrow_path: Path | None) -> None:
    """Run the local secure connections demo stack."""
    repo = find_burrow_repo(burrow_path)
    run_demo_command(repo, action)

    if action == "start":
        update_demo_environment(REPO_ROOT / ".env.local", enabled=True)
        click.echo("")
        click.echo("Secure connections demo is ready.")
        click.echo("Restart PostHog, then open /settings/project/secure-connections.")
        click.echo("Run `hogli secure-connections:demo test` to check the full demo stack.")
    elif action == "stop":
        update_demo_environment(REPO_ROOT / ".env.local", enabled=False)
        click.echo("Secure connections demo stopped. Restart PostHog to clear the demo configuration.")
