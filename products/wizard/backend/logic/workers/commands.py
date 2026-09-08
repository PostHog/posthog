import re
import shlex
from uuid import UUID

from django.conf import settings

from posthog.utils import get_instance_region

from products.wizard.backend.facade.validation import is_executable_wizard_version
from products.wizard.backend.logic.artifacts.config import MAX_GIT_DIFF_BYTES
from products.wizard.backend.logic.workers.config import (
    LOCAL_WIZARD_ARCHIVE_PATH,
    LOCAL_WIZARD_INSTALL_PATH,
    MAX_HANDOFF_BODY_BYTES,
    WIZARD_DIFF_OUTPUT_PATH,
    WIZARD_PACKAGE_INSTALL_PATH,
    WIZARD_TIMEOUT_SECONDS,
)
from products.wizard.backend.logic.workers.errors import InvalidWizardProgramCommandError, InvalidWizardVersionError

_WIZARD_PROGRAM_COMMAND_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SANDBOX_LOG_BYTES = 64 * 1024


def bound_command_output(command: str, *, stdout_limit: int = MAX_SANDBOX_LOG_BYTES, tail: bool = True) -> str:
    """
    Wraps a command to limit its stdout and stderr output to a given number of bytes.
    Helps prevent runaway commands from filling up the worker's logs and causing OOM errors.
    """
    stdout_reader = "tail" if tail else "head"
    script = (
        f"( set -o pipefail; {command} ) "
        f"> >({stdout_reader} -c {stdout_limit}) 2> >(tail -c {MAX_SANDBOX_LOG_BYTES} >&2); "
        'status=$?; wait; exit "$status"'
    )
    return f"bash -c {shlex.quote(script)}"


def build_wizard_command(
    repository_path: str,
    team_id: int,
    wizard_version: str,
    program_command: tuple[str, ...],
    *,
    use_local_wizard_source: bool = False,
) -> str:
    if not is_executable_wizard_version(wizard_version):
        raise InvalidWizardVersionError

    if any(_WIZARD_PROGRAM_COMMAND_PATTERN.fullmatch(argument) is None for argument in program_command):
        raise InvalidWizardProgramCommandError

    setup_commands: list[str] = []
    if use_local_wizard_source:
        executable = f"node {shlex.quote(f'{LOCAL_WIZARD_INSTALL_PATH}/dist/bin.js')}"
    else:
        install_path = shlex.quote(WIZARD_PACKAGE_INSTALL_PATH)
        package = shlex.quote(f"@posthog/wizard@{wizard_version}")

        setup_commands = [
            f"rm -rf {install_path}",
            f"mkdir -p {install_path}",
            # removes previous npm configs, creating an empty one
            "rm -f /tmp/posthog-wizard-global.npmrc",
            "touch /tmp/posthog-wizard-global.npmrc",
            (
                # this helps reproducibility by avoiding global configs being inherited
                "npm --userconfig=/dev/null --globalconfig=/tmp/posthog-wizard-global.npmrc install "
                "--ignore-scripts --no-package-lock --no-save "
                f"--prefix {install_path} --registry=https://registry.npmjs.org {package}"
            ),
        ]

        executable = f"node {install_path}/node_modules/@posthog/wizard/dist/bin.js"

    invocation = [
        executable,
        *(shlex.quote(argument) for argument in program_command),
        "--headless-DONOTUSE-EXPERIMENTAL",
        "--install-dir .",
        f"--region {shlex.quote(_wizard_region())}",
        f"--project-id {shlex.quote(str(team_id))}",
    ]

    if settings.DEBUG:
        invocation.append('--base-url "$POSTHOG_API_URL"')

    commands = [*setup_commands, f"cd {shlex.quote(repository_path)}", " ".join(invocation)]
    return f"timeout -k 30 {WIZARD_TIMEOUT_SECONDS} sh -c {shlex.quote(' && '.join(commands))}"


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
    # Stage the diff to a file and ship at most MAX_GIT_DIFF_BYTES+1 back: the worker reads all
    # stdout into memory, so the byte cap is enforced sandbox-side. The sentinel extra byte lets
    # the artifact step tell "at the limit" from "oversized"; && preserves git's exit code.
    return (
        f"cd {shlex.quote(repository_path)} && git add -N --all && "
        f"git diff --binary --no-ext-diff HEAD > {shlex.quote(WIZARD_DIFF_OUTPUT_PATH)} && "
        f"head -c {MAX_GIT_DIFF_BYTES + 1} {shlex.quote(WIZARD_DIFF_OUTPUT_PATH)}"
    )


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
