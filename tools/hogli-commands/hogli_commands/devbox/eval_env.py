"""Prepare a devbox from a private environment bundle on the caller's machine."""

from __future__ import annotations

import os
import re
import stat
import time
import shlex
import hashlib
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlsplit

import click
from hogli.manifest import REPO_ROOT

from .cli import _workspace_arg_suffix, start_or_create_workspace
from .coder import (
    DEFAULT_PRESET,
    DEFAULT_TEMPLATE,
    REGIONS,
    _ssh_host_alias,
    coder_ssh_alias_configured,
    get_coder_url,
    get_username,
    get_workspace,
)

MAX_BUNDLE_BYTES = 2 * 1024**3
READY_TIMEOUT = 20 * 60
APP_TIMEOUT = 5 * 60
REMOTE_TIMEOUT = 60 * 60
TRANSFER_MODULE = "products.posthog_ai.eval_harness.environment.transfer"
TRANSFER_PATH = "products/posthog_ai/eval_harness/environment/transfer.py"

_PREPARE_SOURCE = r"""
set -eu
cd "$HOME/posthog"
commit="$1"
if [ -n "$commit" ] && [ "$(git rev-parse HEAD)" != "$commit" ]; then
    if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
        echo 'The target checkout has local changes. Use a new devbox or commit those changes before --ref.' >&2
        exit 1
    fi
    if pgrep -x phrocs >/dev/null || pgrep -x mprocs >/dev/null; then
        echo 'The target dev stack is running or starting. Stop it before changing --ref, or use a new devbox.' >&2
        exit 1
    fi
    for port in 8000 8010 8234; do
        if ( : > "/dev/tcp/127.0.0.1/$port" ) 2>/dev/null; then
            echo 'The target app is running. Stop it before changing --ref, or use a new devbox.' >&2
            exit 1
        fi
    done
    if ! git cat-file -e "$commit^{commit}" 2>/dev/null; then
        git fetch --quiet origin "$commit"
    fi
    git cat-file -e "$commit:products/posthog_ai/eval_harness/environment/transfer.py"
    git checkout --quiet --detach "$commit"
fi
if [ ! -f products/posthog_ai/eval_harness/environment/transfer.py ]; then
    echo 'The target checkout does not include eval environment setup. Retry with --ref <local-branch-or-commit> containing this command.' >&2
    exit 1
fi
if ! .codex/with-flox true >/dev/null 2>&1; then
    .codex/with-flox --prepare true
fi
"""


def resolve_source_commit(ref: str | None) -> str | None:
    if ref is None:
        return None
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise click.ClickException("--ref must name a commit available in this local PostHog checkout.")
    available = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{TRANSFER_PATH}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if available.returncode != 0:
        raise click.ClickException(
            "The selected --ref does not include eval environment setup. Commit and push it first."
        )
    return commit


def app_health(workspace: Mapping[str, object] | None) -> str | None:
    if workspace is None or not isinstance(build := workspace.get("latest_build"), dict):
        return None
    resources = build.get("resources")
    for resource in resources if isinstance(resources, list) else []:
        if not isinstance(resource, dict):
            continue
        agents = resource.get("agents")
        for agent in agents if isinstance(agents, list) else []:
            if not isinstance(agent, dict):
                continue
            apps = agent.get("apps")
            for app in apps if isinstance(apps, list) else []:
                if isinstance(app, dict) and app.get("slug") == "app":
                    health = app.get("health")
                    return health if isinstance(health, str) else None
    return None


class EvalEnvironmentDevbox:
    def __init__(self, name: str, state_dir: str) -> None:
        self.name = name
        self.state_dir = state_dir

    def ssh(self, script: str, *arguments: str) -> list[str]:
        return [
            "ssh",
            "-T",
            "-oBatchMode=yes",
            "-oConnectTimeout=15",
            "-oServerAliveInterval=15",
            "-oServerAliveCountMax=4",
            _ssh_host_alias(self.name),
            shlex.join(["bash", "-lc", script, "bash", *arguments]),
        ]

    def wait_for_checkout(self) -> None:
        click.echo("Waiting for the devbox connection and PostHog checkout...")
        deadline = time.monotonic() + READY_TIMEOUT
        next_update = deadline - READY_TIMEOUT + 30
        while (now := time.monotonic()) < deadline:
            if now >= next_update:
                click.echo("The devbox is still starting; waiting for its SSH connection...")
                next_update = now + 30
            try:
                result = subprocess.run(
                    self.ssh(
                        'cd "$HOME/posthog" && git rev-parse --verify HEAD >/dev/null '
                        "&& test -x .codex/with-flox && test -x bin/hogli"
                    ),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(5)
        raise click.ClickException(
            f"The devbox did not become reachable within {READY_TIMEOUT // 60} minutes. "
            f"Inspect `hogli devbox:logs{_workspace_arg_suffix(self.name)}` and retry."
        )

    @staticmethod
    def run_remote(
        command: list[str], *, operation: str, stdin: BinaryIO | int = subprocess.DEVNULL, allow_missing: bool = False
    ) -> int:
        try:
            result = subprocess.run(command, stdin=stdin, check=False, timeout=REMOTE_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise click.ClickException(
                f"{operation} exceeded {REMOTE_TIMEOUT // 60} minutes. Inspect the devbox before retrying; "
                "the remote operation may still be running. Its files and import state were kept."
            ) from error
        if result.returncode != 0 and not (allow_missing and result.returncode == 3):
            raise click.ClickException(
                f"{operation} failed (exit {result.returncode}). The private bundle and import state were kept. "
                "Follow the error above before retrying; an incomplete import needs a fresh --state-dir."
            )
        return result.returncode

    def prepare_source(self, commit: str | None) -> None:
        click.echo("Preparing the devbox's development environment...")
        self.run_remote(self.ssh(_PREPARE_SOURCE, commit or ""), operation="Preparing the devbox checkout")

    def run_python(self, *arguments: str) -> list[str]:
        return self.ssh('cd "$HOME/posthog" && exec .codex/with-flox python "$@"', *arguments)

    def transfer(self, bundle: BinaryIO, digest: str, size: int) -> None:
        options = ["--sha256", digest, "--size", str(size), "--state-dir", self.state_dir]
        cached = self.run_remote(
            self.run_python("-m", TRANSFER_MODULE, "check", *options),
            operation="Verifying the cached bundle",
            allow_missing=True,
        )
        if cached == 0:
            click.echo("The verified data bundle is already on the devbox; reusing it.")
            return
        click.echo(f"Copying the private data bundle over SSH ({size / 1024**2:.1f} MiB)...")
        bundle.seek(0)
        self.run_remote(
            self.run_python("-m", TRANSFER_MODULE, "receive", *options),
            stdin=bundle,
            operation="Copying the data bundle",
        )

    def app_origin(self) -> str:
        workspace = get_workspace(self.name)
        owner = workspace.get("owner_name") if workspace is not None else None
        username = owner if isinstance(owner, str) and owner else get_username()
        coder_url = urlsplit(get_coder_url())
        if coder_url.scheme != "https" or not coder_url.hostname or coder_url.username or coder_url.password:
            raise click.ClickException("The configured Coder URL must be an HTTPS origin.")
        return f"https://app--{self.name}--{username}.{coder_url.netloc}"

    def restore(self, digest: str, origin: str, user_id: int | None, target_cutoff: str | None) -> None:
        bundle = str(PurePosixPath(self.state_dir) / f"upload-{digest}.tar.gz")
        arguments = [
            "-m",
            "products.posthog_ai.eval_harness.environment",
            "prepare",
            bundle,
            "--sha256",
            digest,
            "--state-dir",
            self.state_dir,
            "--site-url",
            origin,
        ]
        if user_id is not None:
            arguments.extend(["--user-id", str(user_id)])
        if target_cutoff is not None:
            arguments.extend(["--target-cutoff", target_cutoff])
        click.echo("Restoring events and saved metrics, then checking the app...")
        self.run_remote(self.run_python(*arguments), operation="Restoring the eval environment")

    def wait_for_app(self) -> None:
        click.echo("Waiting for Coder to confirm the app is reachable...")
        deadline = time.monotonic() + APP_TIMEOUT
        next_update = deadline - APP_TIMEOUT + 30
        while (now := time.monotonic()) < deadline:
            if now >= next_update:
                click.echo("The data is ready; waiting for Coder's app health check...")
                next_update = now + 30
            if app_health(get_workspace(self.name)) == "healthy":
                return
            time.sleep(5)
        raise click.ClickException(
            "The data was restored, but Coder has not confirmed the app URL is ready. "
            "Keep the state directory and rerun this command to check it again."
        )


def prepare_eval_environment(
    *,
    name: str,
    bundle_path: Path,
    expected_sha256: str | None,
    ref: str | None,
    state_dir: str,
    user_id: int | None,
    target_cutoff: str | None,
    region: str | None,
    disk: int | None,
    verbose: bool,
) -> None:
    if name.startswith("@"):
        raise click.UsageError("Choose one of your own devbox labels with --name.")
    if state_dir.startswith("~"):
        raise click.UsageError("--state-dir is relative to ~/posthog on the devbox, or an absolute remote path.")
    if expected_sha256 is not None and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256) is None:
        raise click.UsageError("--sha256 must contain exactly 64 hexadecimal characters.")
    if target_cutoff is not None:
        try:
            cutoff = datetime.fromisoformat(target_cutoff.replace("Z", "+00:00"))
        except ValueError:
            raise click.UsageError("--target-cutoff must be an ISO datetime with a timezone.") from None
        if cutoff.tzinfo is None:
            raise click.UsageError("--target-cutoff must be an ISO datetime with a timezone.")
    with os.fdopen(os.open(bundle_path, os.O_RDONLY | os.O_NONBLOCK), "rb") as bundle:
        metadata = os.fstat(bundle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > MAX_BUNDLE_BYTES:
            raise click.ClickException("The bundle must be a nonempty regular .tar.gz file no larger than 2 GiB.")
        if not bundle_path.name.endswith(".tar.gz"):
            raise click.UsageError("--bundle must be a packed .tar.gz environment bundle.")
        digest = hashlib.file_digest(bundle, "sha256").hexdigest()
        if expected_sha256 is not None and digest != expected_sha256.lower():
            raise click.ClickException("The local bundle does not match --sha256. Nothing was transferred.")
        commit = resolve_source_commit(ref)
        click.echo(f"Verified local bundle: SHA-256 {digest}")
        # The wildcard Coder SSH entry must exist before creating a billable box.
        if not coder_ssh_alias_configured("eval-setup-check"):
            raise click.ClickException("Coder SSH access is not configured. Run `hogli devbox:setup` first.")
        workspace = start_or_create_workspace(name, disk, DEFAULT_TEMPLATE, DEFAULT_PRESET, region, False, verbose)
        target = EvalEnvironmentDevbox(workspace, state_dir)
        target.wait_for_checkout()
        target.prepare_source(commit)
        origin = target.app_origin()
        target.transfer(bundle, digest, metadata.st_size)
        target.restore(digest, origin, user_id, target_cutoff)
        target.wait_for_app()
        click.echo(f"Eval environment ready. Open the project URL above, or the app: {origin}")


@click.command(name="devbox:prepare-eval-env", help="Create or start a devbox and restore a private data bundle")
@click.option("--name", "-n", required=True, help="Your devbox label, for example eval1")
@click.option("--bundle", "bundle_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--sha256", "expected_sha256", help="Expected SHA-256 of the local bundle (otherwise computed)")
@click.option("--ref", help="Local Git branch or commit to check out on a clean, stopped target; must be pushed")
@click.option(
    "--state-dir", default=".flox/cache/eval-environment", show_default=True, help="State directory on the devbox"
)
@click.option("--user-id", type=click.IntRange(min=1), help="Existing devbox user to own the restored project")
@click.option("--target-cutoff", help="End of the restored time window as an ISO datetime with a timezone")
@click.option("--region", type=click.Choice(REGIONS), help="Region for a new devbox")
@click.option("--disk", type=click.IntRange(min=1), help="Disk size in GiB when creating the devbox")
@click.option("--verbose", "-v", is_flag=True, help="Show full Coder build output")
def cmd_prepare_eval_env(
    name: str,
    bundle_path: Path,
    expected_sha256: str | None,
    ref: str | None,
    state_dir: str,
    user_id: int | None,
    target_cutoff: str | None,
    region: str | None,
    disk: int | None,
    verbose: bool,
) -> None:
    """Run from the laptop containing the bundle after `hogli devbox:setup`."""
    try:
        prepare_eval_environment(
            name=name,
            bundle_path=bundle_path,
            expected_sha256=expected_sha256,
            ref=ref,
            state_dir=state_dir,
            user_id=user_id,
            target_cutoff=target_cutoff,
            region=region,
            disk=disk,
            verbose=verbose,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise click.ClickException(
            f"Eval environment setup could not run a required command or read a file ({type(error).__name__}). "
            "The private bundle and import state are preserved. "
            "Follow the error above before retrying; an incomplete import needs a fresh --state-dir."
        ) from error
