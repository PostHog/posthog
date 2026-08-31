import re
import shlex
from uuid import UUID

from django.conf import settings

from posthog.utils import get_instance_region

from products.wizard.backend.facade.validation import is_executable_wizard_version
from products.wizard.backend.logic.workers.config import (
    LOCAL_WIZARD_ARCHIVE_PATH,
    LOCAL_WIZARD_INSTALL_PATH,
    MAX_HANDOFF_BODY_BYTES,
    WIZARD_TIMEOUT_SECONDS,
)

_WIZARD_PROGRAM_COMMAND_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def build_wizard_command(
    repository_path: str,
    team_id: int,
    wizard_version: str,
    program_command: tuple[str, ...],
    *,
    use_local_wizard_source: bool = False,
) -> str:
    if not is_executable_wizard_version(wizard_version):
        raise ValueError("Invalid Wizard version")

    if any(_WIZARD_PROGRAM_COMMAND_PATTERN.fullmatch(argument) is None for argument in program_command):
        raise ValueError("Invalid Wizard program command")

    executable = (
        f"node {shlex.quote(f'{LOCAL_WIZARD_INSTALL_PATH}/dist/bin.js')}"
        if use_local_wizard_source
        else f"npx --yes {shlex.quote(f'@posthog/wizard@{wizard_version}')}"
    )

    parts = [
        f"cd {shlex.quote(repository_path)} &&",
        f"timeout -k 30 {WIZARD_TIMEOUT_SECONDS}",
        executable,
        *(shlex.quote(argument) for argument in program_command),
        "--headless-DONOTUSE-EXPERIMENTAL",
        "--install-dir .",
        f"--region {shlex.quote(_wizard_region())}",
        f"--project-id {shlex.quote(str(team_id))}",
    ]

    if settings.DEBUG:
        parts.append('--base-url "$POSTHOG_API_URL"')

    return " ".join(parts)


def build_local_wizard_preparation_command() -> str:
    archive_path = shlex.quote(LOCAL_WIZARD_ARCHIVE_PATH)
    install_path = shlex.quote(LOCAL_WIZARD_INSTALL_PATH)
    return " && ".join(
        (
            "apt-get update -qq && apt-get install -y --no-install-recommends build-essential python3",
            f"rm -rf {install_path}",
            f"mkdir -p {install_path}",
            f"tar -xzf {archive_path} -C {install_path}",
            f"cd {install_path}",
            "corepack enable pnpm",
            "HUSKY=0 pnpm install --frozen-lockfile",
            "pnpm run prebuild",
            "WIZARD_BUILD_NODE_ENV=ci pnpm exec tsdown",
            "chmod +x ./dist/bin.js",
            "cp -r scripts/** dist",
            "rm -f dist/*.no-jest.*",
        )
    )


def build_git_diff_command(repository_path: str) -> str:
    return f"cd {shlex.quote(repository_path)} && git add -N --all && git diff --binary --no-ext-diff HEAD"


def build_sanitize_repository_remote_command(repository_path: str, repository: str) -> str:
    remote_url = f"https://github.com/{repository}.git"
    return f"git -C {shlex.quote(repository_path)} remote set-url origin {shlex.quote(remote_url)}"


def wizard_handoff_output_path(run_id: UUID) -> str:
    return f"/tmp/posthog-wizard-handoff-{run_id.hex}.md"


def build_read_handoff_command(run_id: UUID) -> str:
    return f"head -c {MAX_HANDOFF_BODY_BYTES} {shlex.quote(wizard_handoff_output_path(run_id))}"


def pull_request_branch(run_id: UUID) -> str:
    return f"posthog/wizard-{run_id.hex[:12]}"


def _wizard_region() -> str:
    return "eu" if get_instance_region() == "EU" else "us"
