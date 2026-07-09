from __future__ import annotations

import logging

from products.tasks.backend.constants import vm_sandbox_allowed_origins
from products.tasks.backend.logic.services.image_spec import (
    SANDBOX_IMAGE_SPEC_PATH,
    SandboxImageSpec,
    SandboxImageSpecError,
    parse_image_spec_yaml,
)
from products.tasks.backend.models import SandboxCustomImage, Task, TaskRun

logger = logging.getLogger(__name__)


def is_custom_images_enabled(*, distinct_id: str, organization_id: str) -> bool:
    """Custom images require the Modal VM runtime flag with `user_created` in its origin allowlist."""
    try:
        allowed = vm_sandbox_allowed_origins(distinct_id=distinct_id, organization_id=organization_id)
        return Task.OriginProduct.USER_CREATED.value in allowed
    except Exception as e:
        logger.warning("custom_images_flag_check_failed", extra={"error": str(e)})
        return False


IMAGE_BUILDER_MODEL = "claude-sonnet-4-6"
IMAGE_BUILDER_REASONING_EFFORT = "low"

IMAGE_BUILDER_PROMPT = """You are an expert at building sandbox base images for PostHog cloud tasks.

The user wants to create a custom base image named "{image_name}" for their cloud task sandboxes. Your job is to converse with them, figure out what they need installed or configured, and maintain a declarative image spec that captures it.

CONTEXT:
- You are running inside the exact VM sandbox base that custom images layer on top of (Ubuntu 24.04, Node 24, uv, gh CLI, Docker-in-Docker via `start-dockerd`). Anything you can do here, the built image can bake in.
- The custom image is built by replaying your spec on top of this base image, then published. It never replaces the base — agent tooling and git remain present.
- The spec lives at {spec_path}. Keep it up to date at all times: after every change the user agrees to, write the full spec file.

SPEC FORMAT (YAML):
apt_packages:  # Debian package names, installed via apt-get
  - postgresql-client
run_commands:  # shell commands executed in order at image BUILD time
  - curl -fsSL https://example.com/install.sh | bash
repo_setup_commands:  # only when a repository is linked: run inside a fresh checkout of it at BUILD time
  - pnpm install --frozen-lockfile
env:           # environment variables baked into the image
  MY_TOOL_HOME: /opt/my-tool

RULES:
- Verify before you promise: actually run installs/commands here in the sandbox to confirm they work, then record the working steps in the spec.
- Build-time commands must be non-interactive and idempotent. No `sudo` needed — builds run as root.
- Every run_commands / repo_setup_commands entry must be a SINGLE line: each becomes one Dockerfile RUN instruction, so multi-line strings (backslash continuations, heredocs) break the build. Chain steps with `&&`.
- Prefer apt_packages over run_commands when a Debian package exists.
- Keep the spec minimal: only what the user asked for, no speculative extras.
- Never put secrets, tokens, or credentials in the spec — it is scanned and rejected if it exfiltrates data or weakens sandbox security.
- Download-and-execute steps must be pinned and verifiable: fetch install scripts and binaries from a tagged release or commit hash (never a mutable branch) and verify a checksum when the vendor publishes one — unpinned `curl | sh` fails the security scan.
- Services (databases, daemons) cannot run "in" an image; you can install them and note that they start at task time.
- If the user points you at a repository, you may clone it here to verify their app runs, but do NOT bake repository code into the spec — only its runtime dependencies.
- After each spec update, show the user the current spec and briefly confirm what changed.
- When the user is happy, tell them to press "Save & build" (available right here in this conversation, and in the Environments settings) to scan, build, and publish the image.

Start by asking the user what they'd like this image to include, unless they already told you below.
"""

IMAGE_BUILDER_REPO_SECTION = """
REPOSITORY: {repository} is cloned in this sandbox at {repo_path}.
The user's goal is an image on which this repository comes up dependency-wise FAST. Two levers:
1. System-level tooling the repo needs (compilers, language runtimes, exact package-manager versions) goes in apt_packages / run_commands.
2. Dependency warming goes in repo_setup_commands: at image BUILD time these run inside a fresh checkout of {repository} (cwd = repo root), then the checkout is DISCARDED — but global package stores and caches persist in the image (pnpm store, npm/pip/uv caches, cargo registry, ~/.cache/*, …). Put the repo's dependency install there (e.g. `pnpm install --frozen-lockfile`, `uv sync`, `npm ci`), AND any post-install steps that download global tool binaries — `playwright install --with-deps`, browser/Electron binaries, model weights — so everything heavy is baked and a task-time install is just a fast linking pass against the warm store.
Verify both levers here: run the install, confirm it succeeds, then confirm a SECOND fresh clone + install (and tool startup, e.g. playwright finding its browsers) is fast thanks to the warmed caches. The checkout itself is never baked (tasks clone fresh at their own commit) — everything else is.
"""

IMAGE_BUILDER_UPDATE_SECTION = """
EXISTING SPEC: this image has already been built (build #{version}, status: {status}). Its current spec is:

{spec_yaml}
Write this spec to {spec_path} as your starting point before making changes. The user wants to update the image — apply their requested changes on top, re-verify anything you touch, and keep everything else intact.
"""


def build_image_builder_prompt(image: SandboxCustomImage) -> str:
    prompt = IMAGE_BUILDER_PROMPT.format(image_name=image.name, spec_path=SANDBOX_IMAGE_SPEC_PATH)
    if image.repository:
        org, _, repo = image.repository.lower().partition("/")
        prompt += IMAGE_BUILDER_REPO_SECTION.format(
            repository=image.repository, repo_path=f"/tmp/workspace/repos/{org}/{repo}"
        )
    if image.spec:
        from products.tasks.backend.logic.services.image_spec import spec_json_to_yaml  # noqa: PLC0415

        prompt += IMAGE_BUILDER_UPDATE_SECTION.format(
            version=image.version,
            status=image.status,
            spec_yaml=spec_json_to_yaml(image.spec),
            spec_path=SANDBOX_IMAGE_SPEC_PATH,
        )
    if image.description:
        prompt += f"\nUSER'S INITIAL REQUEST:\n{image.description}\n"
    return prompt


def ensure_image_builder_task(image: SandboxCustomImage, user_id: int) -> Task:
    """Reuse the builder task while its run is live; once terminal, spawn a fresh session seeded with the stored spec."""
    existing_task = image.builder_task
    if existing_task is not None:
        latest_run = existing_task.runs.order_by("-created_at").first()
        if latest_run is not None and not latest_run.is_terminal:
            return existing_task

    task = Task.create_and_run(
        team=image.team,
        title=f"Custom image: {image.name}",
        description=f"Image-builder session for custom sandbox image '{image.name}'",
        origin_product=Task.OriginProduct.IMAGE_BUILDER,
        user_id=user_id,
        repository=image.repository or None,
        create_pr=False,
        mode="interactive",
        interaction_origin="desktop",
        runtime_adapter="claude",
        model=IMAGE_BUILDER_MODEL,
        reasoning_effort=IMAGE_BUILDER_REASONING_EFFORT,
        pending_user_message=build_image_builder_prompt(image),
        custom_image_builder_id=str(image.id),
    )
    image.builder_task = task
    image.save(update_fields=["builder_task", "updated_at"])
    return task


def read_spec_from_builder_sandbox(image: SandboxCustomImage) -> SandboxImageSpec:
    """Read and validate the spec file from the builder task's live sandbox."""
    from products.tasks.backend.logic.services.sandbox import Sandbox

    if image.builder_task_id is None:
        raise SandboxImageSpecError("This image has no builder session; provide a spec directly instead")

    runs = TaskRun.objects.filter(task_id=image.builder_task_id).order_by("-created_at").only("id", "state")[:10]
    sandbox_id = next(
        (run.state.get("sandbox_id") for run in runs if isinstance(run.state, dict) and run.state.get("sandbox_id")),
        None,
    )
    if not sandbox_id:
        raise SandboxImageSpecError("The builder session has no sandbox yet; send it a message first")

    try:
        sandbox = Sandbox.get_by_id(sandbox_id)
        result = sandbox.execute(f"cat {SANDBOX_IMAGE_SPEC_PATH}", timeout_seconds=30)
    except Exception as e:
        logger.warning(
            "custom_image_spec_read_failed",
            extra={"image_id": str(image.id), "sandbox_id": sandbox_id, "error": str(e)},
        )
        raise SandboxImageSpecError(
            "Could not reach the builder sandbox (it may have expired); resume the conversation and try again"
        )

    if result.exit_code != 0:
        raise SandboxImageSpecError(
            f"No spec file found at {SANDBOX_IMAGE_SPEC_PATH} in the builder sandbox; ask the agent to write it first"
        )

    return parse_image_spec_yaml(result.stdout)
