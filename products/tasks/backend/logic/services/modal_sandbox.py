from __future__ import annotations

import json
import time
import uuid
import shlex
import shutil
import asyncio
import logging
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import Any, cast

from django.conf import settings

import modal
import requests
from cachetools import TTLCache, cached
from modal.exception import (
    ConnectionError as ModalConnectionError,
    InvalidError as ModalInvalidError,
    ResourceExhaustedError as ModalResourceExhaustedError,
    ServiceError as ModalServiceError,
    TimeoutError as ModalTimeoutError,
)
from semantic_version import NpmSpec

from posthog.exceptions_capture import capture_exception
from posthog.settings import CLOUD_DEPLOYMENT

from products.tasks.backend.constants import (
    ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS,
    DEV_STACK_IMAGE_NAME,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
    SnapshotKind,
)
from products.tasks.backend.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNetworkPolicyError,
    SandboxNotFoundError,
    SandboxNotRunningError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
    SnapshotFileLimitExceededError,
    SnapshotTimeoutError,
)
from products.tasks.backend.logic.services.cpu_billing import (
    CPU_BILLING_SAMPLER_PATH as CPU_BILLING_SAMPLER_PATH,
    CPU_BILLING_STATE_PATH,
    build_sampler_start_command,
    compute_billed_cpu_usage_usec,
    parse_cpu_stat_usage_usec,
)
from products.tasks.backend.logic.services.local_packages import (
    LocalPackage,
    get_local_package_runtime_dependencies,
    get_local_posthog_code_packages,
)
from products.tasks.backend.logic.services.local_skills import (
    BUILT_SKILLS_RELATIVE_PATH as LOCAL_BUILT_SKILLS_PATH,
    LocalSkillsCache,
    populate_skills_directory,
)
from products.tasks.backend.logic.services.modal_provision_diagnostics import (
    SandboxProvisionDiagnostics,
    capture_modal_output_if_debug,
    summarize_modal_output,
)
from products.tasks.backend.logic.services.sandbox import redact_sandbox_command
from products.tasks.backend.models import SandboxSnapshot

from .agent_server_launcher import (
    AGENT_SERVER_PORT as AGENT_SERVER_PORT,
    AgentServerLaunchMixin,
    _session_init_probe_hosts as _session_init_probe_hosts,
)
from .sandbox import (
    AgentServerResult,
    ExecutionResult,
    ExecutionStream,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    SandboxWorkload,
)

logger = logging.getLogger(__name__)

DEFAULT_MODAL_APP_NAME = "posthog-sandbox-default"
NOTEBOOK_MODAL_APP_NAME = "posthog-sandbox-notebook"
STREAMLIT_MODAL_APP_NAME = "posthog-sandbox-streamlit"
# Self-driving runs boot the same default image as a user's task, so only the app separates them.
# Images and snapshots are workspace-scoped in Modal, not app-scoped, so a box here still restores
# a snapshot baked under the default app.
SELF_DRIVING_MODAL_APP_NAME = "posthog-sandbox-self-driving"


SANDBOX_BASE_IMAGE = "ghcr.io/posthog/posthog-sandbox-base"
SANDBOX_NOTEBOOK_IMAGE = "ghcr.io/posthog/posthog-sandbox-notebook"
SANDBOX_VM_IMAGE = "ghcr.io/posthog/posthog-sandbox-vm"
SANDBOX_STREAMLIT_IMAGE = "ghcr.io/posthog/posthog-sandbox-streamlit"
SANDBOX_IMAGE = SANDBOX_BASE_IMAGE

# SLIM_BASE has no registry image and no CD publish pipeline — it's built inline by Modal
# (see _build_slim_template_image below) from debian_slim + apt packages, so there's nothing
# to push or pin a digest for. Keep these two pins in sync with
# Dockerfile.sandbox-slim's NODE_MAJOR / uv COPY --from pins (and with Dockerfile.sandbox-base,
# which both mirror).
SANDBOX_SLIM_NODE_MAJOR = 24
SANDBOX_SLIM_UV_IMAGE = "ghcr.io/astral-sh/uv:0.11.15"
POST_RESTORE_PROBE_TIMEOUT_SECONDS = 45

# Recoverable infra errors Modal surfaces when filesystem snapshotting times out or loses its
# connection (e.g. the command router's "Deadline exceeded"). These usually succeed on retry, so
# Temporal should retry them rather than treating them as hard snapshot failures.
TRANSIENT_SNAPSHOT_ERRORS: tuple[type[BaseException], ...] = (
    ModalTimeoutError,
    ModalConnectionError,
    ModalServiceError,
    TimeoutError,
    ConnectionError,
    asyncio.CancelledError,
)

DIRECTORY_SNAPSHOT_TIMEOUT_SECONDS = 240

# Heavy, reproducible directories to prune before retrying a snapshot that hit Modal's
# 1M-file cap. Each is a package cache or install tree the resume sandbox rebuilds, so
# dropping them shrinks the file count without losing the run's own work.
SNAPSHOT_PRUNE_DIR_NAMES = (
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pnpm-store",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
)
SNAPSHOT_PRUNE_TIMEOUT_SECONDS = 90


def _is_snapshot_file_cap_error(error: BaseException) -> bool:
    """Whether Modal's ``ResourceExhaustedError`` is the permanent >1M-file snapshot cap
    rather than a generic (retryable) quota/rate-limit ``RESOURCE_EXHAUSTED``.

    ``ResourceExhaustedError`` is Modal's generic gRPC RESOURCE_EXHAUSTED wrapper, so we
    key on the file-count message ("... snapshot contains more than 1000000 files") to avoid
    classifying a transient quota/rate-limit blip as a permanent, non-retryable failure.
    """
    message = str(error).lower()
    return "snapshot" in message and "more than" in message and "file" in message


# Modal's snapshot_filesystem default timeout is 55s, which multi-GB sandbox filesystems
# routinely exceed. The default fits the standalone snapshot activity's 10-minute budget;
# resume snapshots run under a 5-minute activity budget and pass a tighter per-call
# timeout (see create_resume_snapshot) so Modal's classified timeout fires before
# Temporal kills the attempt. Published-image snapshots (the prebaked dev-stack bake,
# with gigabytes of docker state) get a far larger budget bounded only by the bake
# activity timeout.
FILESYSTEM_SNAPSHOT_TIMEOUT_SECONDS = 8 * 60
PUBLISHED_IMAGE_SNAPSHOT_TIMEOUT_SECONDS = 30 * 60

_MODAL_NETWORK_POLICY_REJECTION_MARKERS = (
    "outbound_domain_allowlist",
    "outbound domain allowlist",
    "domain allowlist",
    "allowed domains",
)


def _is_modal_network_policy_rejection(error: BaseException) -> bool:
    if not isinstance(error, ModalInvalidError):
        return False
    message = str(error).casefold()
    return any(marker in message for marker in _MODAL_NETWORK_POLICY_REJECTION_MARKERS)


# Modal region mapping based on cloud deployment
MODAL_REGION_BY_DEPLOYMENT: dict[str | None, str] = {
    "EU": "eu-west",
    "US": "us-east",
}
DEFAULT_MODAL_REGION = "us-east"


def _get_modal_region() -> str:
    return MODAL_REGION_BY_DEPLOYMENT.get(CLOUD_DEPLOYMENT, DEFAULT_MODAL_REGION)


def _normalize_snapshot_kind(value: object) -> SnapshotKind:
    if value == SNAPSHOT_KIND_DIRECTORY:
        return SNAPSHOT_KIND_DIRECTORY
    return SNAPSHOT_KIND_FILESYSTEM


def _resource_create_kwargs(config: SandboxConfig) -> dict[str, object]:
    """Build the `cpu`/`memory` kwargs for ``modal.Sandbox.create``.

    `cpu_cores` / `memory_gb` are the limit (max). When the config is burstable, emit Modal's
    ``(request, limit)`` tuple form so the box is billed at ``max(request, actual)`` and can burst
    up to the limit; otherwise emit the flat scalar, which makes request == limit (fixed size).

    The burstable request floors come from the config's ``effective_*_request`` properties — the
    same values the usage ledger records — so what Modal reserves and what pricing bills can't
    diverge.
    """
    cpu_limit = float(config.cpu_cores)
    memory_limit_mb = int(config.memory_gb * 1024)
    if not config.burstable_resources:
        return {"cpu": cpu_limit, "memory": memory_limit_mb}

    return {
        "cpu": (config.effective_cpu_request_cores, cpu_limit),
        "memory": (config.effective_memory_request_mb, memory_limit_mb),
    }


LOCAL_MODAL_DOCKERFILES = {
    SandboxTemplate.DEFAULT_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"),
    SandboxTemplate.NOTEBOOK_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-notebook"),
    SandboxTemplate.VM_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-vm"),
    SandboxTemplate.STREAMLIT_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-streamlit"),
}
LOCAL_MODAL_INSTALL_SKILLS_SCRIPT = Path("products/tasks/backend/sandbox/images/install-skills.sh")
LOCAL_MODAL_GIT_GUARD_SCRIPT = Path("products/tasks/backend/sandbox/images/git-guard.sh")
LOCAL_MODAL_GH_GUARD_SCRIPT = Path("products/tasks/backend/sandbox/images/gh-guard.sh")
# The notebook image bakes the notebooks SQLV2 kernel and stamps its content hash,
# so a local build context needs the package and the module that computes the hash.
LOCAL_MODAL_NOTEBOOK_KERNEL_MODULE = Path("products/notebooks/backend/kernel_package.py")
LOCAL_MODAL_NOTEBOOK_KERNEL_DIR = Path("products/notebooks/backend/sandbox/kernel")
LOCAL_MODAL_CPU_BILLING_SAMPLER = Path("products/tasks/backend/sandbox/images/cpu_billing_sampler.py")
# The base image builds the agent-shadow observer from source in its first stage.
LOCAL_MODAL_AGENT_SHADOW_DIR = Path("products/desktop/packages/agent-shadow")


_image_ref_cache: TTLCache = TTLCache(maxsize=3, ttl=300)
_image_ref_lock = threading.Lock()


# Modal caches images by reference indefinitely. Falling back to the mutable
# `:master` tag therefore lets Modal keep serving a stale or broken image
# (e.g. one missing /scripts/node_modules/.bin/agent-server) forever, so we
# retry transient GHCR failures and otherwise fail closed.
_GHCR_RESOLVE_MAX_ATTEMPTS = 4
_GHCR_RESOLVE_BACKOFF_BASE_SECONDS = 1.0


class _ImageDigestResolutionError(Exception):
    """A single attempt to resolve the GHCR digest failed."""


def _resolve_image_digest_once(image: str) -> str:
    """Resolve ``image:master`` to an immutable ``image@sha256:...`` reference.

    Raises ``_ImageDigestResolutionError`` for non-200 responses or missing
    fields; network-level exceptions (``ConnectionError``, ``Timeout``, etc.)
    propagate as-is. The caller catches ``Exception`` in all cases, so we never
    fall back to the mutable ``:master`` tag.
    """
    image_repo = image.replace("ghcr.io/", "")

    token_resp = requests.get(
        f"https://ghcr.io/token?service=ghcr.io&scope=repository:{image_repo}:pull",
        timeout=10,
    )
    if token_resp.status_code != 200:
        raise _ImageDigestResolutionError(f"GHCR token request failed: status={token_resp.status_code}")

    token = token_resp.json().get("token")
    if not token:
        raise _ImageDigestResolutionError("GHCR token response missing token field")

    manifest_resp = requests.get(
        f"https://ghcr.io/v2/{image_repo}/manifests/master",
        headers={
            "Accept": "application/vnd.oci.image.index.v1+json",
            "Authorization": f"Bearer {token}",
        },
        timeout=10,
    )
    if manifest_resp.status_code != 200:
        raise _ImageDigestResolutionError(f"GHCR manifest request failed: status={manifest_resp.status_code}")

    digest = manifest_resp.headers.get("Docker-Content-Digest")
    if not digest:
        raise _ImageDigestResolutionError("GHCR manifest response missing Docker-Content-Digest header")

    return f"{image}@{digest}"


@cached(cache=_image_ref_cache, lock=_image_ref_lock)
def _get_sandbox_image_reference(image: str = SANDBOX_IMAGE) -> str:
    """Resolve the sandbox image to an immutable digest pin.

    Modal caches sandbox images by reference indefinitely, so a mutable
    ``:master`` tag would let Modal keep serving a stale or broken image. We
    therefore retry transient GHCR failures with exponential backoff and, if
    resolution still fails, fail closed by raising ``SandboxProvisionError``
    (transient — the provisioning activity retries) rather than ever returning
    the floating tag. Successful resolutions are cached for ~5 minutes;
    failures are not cached and re-resolve on the next call.
    """
    last_error: Exception | None = None
    for attempt in range(1, _GHCR_RESOLVE_MAX_ATTEMPTS + 1):
        try:
            reference = _resolve_image_digest_once(image)
            logger.info(f"Resolved sandbox image digest for {image} on attempt {attempt}: {reference}")
            return reference
        except Exception as e:
            last_error = e
            logger.warning(
                f"Failed to resolve sandbox image digest for {image} "
                f"(attempt {attempt}/{_GHCR_RESOLVE_MAX_ATTEMPTS}): {e}"
            )
            if attempt < _GHCR_RESOLVE_MAX_ATTEMPTS:
                time.sleep(_GHCR_RESOLVE_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    raise SandboxProvisionError(
        f"Could not resolve an immutable digest for {image}:master after "
        f"{_GHCR_RESOLVE_MAX_ATTEMPTS} attempts; refusing to fall back to the mutable "
        f":master tag because Modal caches images by reference indefinitely",
        {"image": image},
        cause=last_error if last_error is not None else RuntimeError("digest resolution failed"),
    )


# Templates whose image bundles the agent-server at /scripts and can therefore
# take a live local dist overlay in DEBUG. Add new agent-server-bearing templates here.
AGENT_SERVER_TEMPLATES = frozenset({SandboxTemplate.DEFAULT_BASE, SandboxTemplate.VM_BASE})


@dataclass(frozen=True)
class ImageCandidate:
    """One entry of the ordered image-downgrade chain a sandbox is created from."""

    image: modal.Image
    label: str
    restored_from_snapshot: bool = False
    # The image is a Modal sandbox filesystem snapshot (a resume snapshot or the
    # published dev-stack image), so a boot from it needs the post-create health probe —
    # snapshot restores can come up dead with every RPC succeeding.
    snapshot_derived: bool = False


def _merge_runtime_dependency_specs(name: str, existing: str, candidate: str) -> str:
    if existing == candidate:
        return existing

    try:
        NpmSpec(existing)
        NpmSpec(candidate)
    except ValueError as error:
        raise ValueError(
            f"Conflicting non-semver runtime dependency specs for {name}: {existing!r} and {candidate!r}"
        ) from error

    return f"{existing} {candidate}"


def _local_package_bin_link_commands(packages: tuple[LocalPackage, ...]) -> list[str]:
    commands: list[str] = []
    bin_root = "/scripts/node_modules/.bin"

    for package in packages:
        manifest = json.loads((package.source_path / "package.json").read_text())
        package_name = manifest.get("name")
        package_bin = manifest.get("bin", {})
        if not isinstance(package_name, str):
            continue
        if isinstance(package_bin, str):
            package_bin = {package_name.rsplit("/", 1)[-1]: package_bin}
        if not isinstance(package_bin, dict):
            continue

        for executable, target in package_bin.items():
            if not isinstance(executable, str) or not isinstance(target, str):
                continue
            target_path = f"../{package_name}/{target.removeprefix('./')}"
            executable_path = f"{bin_root}/{executable}"
            commands.append(f"ln -sfn {shlex.quote(target_path)} {shlex.quote(executable_path)}")

    return commands


def _attach_local_package_mounts(
    image: modal.Image, template: SandboxTemplate, *, install_dependencies: bool = True
) -> modal.Image:
    """Overlay each local package's built `dist/` dir onto the installed package
    via add_local_dir(copy=False). No-op unless `template` bundles the agent-server
    and local packages are available.

    Install external runtime dependencies that are missing from the published image
    before mounting the compiled output. The published package can lag behind a local
    branch, but running npm inside it would also process unpublished workspace packages.

    ``install_dependencies=False`` skips that npm-install build layer and attaches the
    mounts only. Sandbox filesystem snapshots (resume/repo snapshots, the published
    dev-stack image) cannot take Modal build steps — the image build fails and the
    sandbox loses the snapshot entirely — while the mounts are attached at create time
    without a build. Runtime dependencies a local branch added over the published
    package are then missing; that dev-only gap surfaces as an agent-server import
    error rather than silently forfeiting the snapshot.
    """
    if template not in AGENT_SERVER_TEMPLATES:
        return image
    packages = get_local_posthog_code_packages()
    if not packages:
        return image

    dependencies = get_local_package_runtime_dependencies(packages)
    if dependencies and not install_dependencies:
        logger.info(
            "Skipping local package dependency install on snapshot-derived image; attaching dist mounts only",
            extra={"packages": sorted(dependencies)},
        )
    elif dependencies:
        if any("@openai/codex" in package_dependencies for package_dependencies in dependencies.values()):
            image = image.apt_install("musl")

        runtime_dependencies: dict[str, str] = {}
        for package_dependencies in dependencies.values():
            for name, version in package_dependencies.items():
                if existing_version := runtime_dependencies.get(name):
                    runtime_dependencies[name] = _merge_runtime_dependency_specs(name, existing_version, version)
                    continue
                runtime_dependencies[name] = version

        dependency_json = json.dumps(runtime_dependencies, separators=(",", ":"), sort_keys=True)
        merge_manifest_script = (
            'const fs=require("fs");'
            'const path="/scripts/package.json";'
            'const manifest=JSON.parse(fs.readFileSync(path,"utf8"));'
            "const dependencies=JSON.parse(process.argv[1]);"
            "manifest.dependencies={...(manifest.dependencies||{}),...dependencies};"
            "fs.writeFileSync(path,JSON.stringify(manifest));"
        )
        install_command = (
            f"node -e {shlex.quote(merge_manifest_script)} {shlex.quote(dependency_json)} && "
            "npm install --prefix /scripts --package-lock=false "
            "--omit=dev --no-audit --no-fund"
        )
        image = image.run_commands(install_command)

    bin_link_commands = _local_package_bin_link_commands(packages)
    if bin_link_commands:
        image = image.run_commands(*bin_link_commands)

    for package in packages:
        image = image.add_local_dir(
            str(package.build_output_path),
            package.sandbox_build_output_path,
            copy=False,
        )
    return image


def _build_slim_template_image() -> modal.Image:
    """Inline image for SLIM_BASE: git + ca-certificates + node + uv, nothing else.

    Built and cached by Modal itself from debian_slim — no registry image, no CD publish
    pipeline, no digest pin to resolve. The first sandbox create after this definition
    changes pays a one-time Modal-side build; every create after that reuses the cached
    image layers.
    """
    return (
        modal.Image.debian_slim()
        # bash is required by the NodeSource setup script below; debian_slim doesn't guarantee it.
        .apt_install("git", "ca-certificates", "curl", "bash")
        .run_commands(
            f"curl -fsSL https://deb.nodesource.com/setup_{SANDBOX_SLIM_NODE_MAJOR}.x | bash -",
            "apt-get install -y --no-install-recommends nodejs",
            "rm -rf /var/lib/apt/lists/*",
        )
        .dockerfile_commands(
            [f"COPY --from={SANDBOX_SLIM_UV_IMAGE} /uv /uvx /usr/local/bin/"],
        )
    )


def _build_canvas_template_image() -> modal.Image:
    # The builder script and its platform manifest are baked in beside the
    # npm dependencies, so a build only ships its project payload into the
    # sandbox. node resolves /scripts/node_modules from the script's parent.
    builder_dir = Path(settings.CANVAS_BUILDER_DIR)
    return (
        _build_slim_template_image()
        .add_local_file(str(builder_dir / "package.json"), "/scripts/package.json", copy=True)
        .add_local_file(str(builder_dir / "package-lock.json"), "/scripts/package-lock.json", copy=True)
        .run_commands("npm ci --prefix /scripts --omit=dev --no-audit --no-fund")
        .add_local_file(str(builder_dir / "build.mjs"), "/scripts/canvas-builder/build.mjs", copy=True)
        .add_local_file(str(builder_dir / "manifest.json"), "/scripts/canvas-builder/manifest.json", copy=True)
    )


_template_image_cache: TTLCache = TTLCache(maxsize=4, ttl=300)
_template_image_lock = threading.Lock()


@cached(cache=_template_image_cache, lock=_template_image_lock)
def get_template_base_image(template: SandboxTemplate) -> modal.Image:
    """The template's base image without local dev mounts — safe to extend with further layers."""
    if template == SandboxTemplate.SLIM_BASE:
        # Built inline (see _build_slim_template_image), never from a registry or a local
        # Dockerfile build context — same image in DEBUG and in production.
        return _build_slim_template_image()
    if template == SandboxTemplate.CANVAS_BUILD:
        return _build_canvas_template_image()

    registry_image = {
        SandboxTemplate.DEFAULT_BASE: SANDBOX_BASE_IMAGE,
        SandboxTemplate.NOTEBOOK_BASE: SANDBOX_NOTEBOOK_IMAGE,
        SandboxTemplate.VM_BASE: SANDBOX_VM_IMAGE,
        SandboxTemplate.STREAMLIT_BASE: SANDBOX_STREAMLIT_IMAGE,
    }.get(template)
    if registry_image is None:
        raise ValueError(f"Unknown template: {template}")

    if settings.DEBUG:
        dockerfile_path, context_dir = _prepare_local_modal_build_context(template)
        return modal.Image.from_dockerfile(dockerfile_path, context_dir=context_dir, ignore=[])
    image_reference = resolve_template_base_image_reference(template)
    if image_reference is None:
        raise ValueError(f"Template does not use a registry image: {template}")
    return modal.Image.from_registry(image_reference)


def _get_template_image(template: SandboxTemplate) -> modal.Image:
    return _attach_local_package_mounts(get_template_base_image(template), template)


def resolve_template_base_image(template: SandboxTemplate) -> modal.Image:
    # Undecorated import surface: the @cached wrapper on get_template_base_image trips
    # mypy's cross-module attribute resolution intermittently, so external callers import this.
    return get_template_base_image(template)


def resolve_template_base_image_reference(template: SandboxTemplate) -> str | None:
    if settings.DEBUG:
        return None

    registry_image = {
        SandboxTemplate.DEFAULT_BASE: SANDBOX_BASE_IMAGE,
        SandboxTemplate.NOTEBOOK_BASE: SANDBOX_NOTEBOOK_IMAGE,
        SandboxTemplate.VM_BASE: SANDBOX_VM_IMAGE,
        SandboxTemplate.STREAMLIT_BASE: SANDBOX_STREAMLIT_IMAGE,
    }.get(template)
    if registry_image is None:
        raise ValueError(f"Template does not use a registry image: {template}")
    return _get_sandbox_image_reference(registry_image)


@lru_cache(maxsize=3)
def _prepare_local_modal_build_context(template: SandboxTemplate) -> tuple[str, str]:
    dockerfile_relative_path = LOCAL_MODAL_DOCKERFILES.get(template)
    if dockerfile_relative_path is None:
        raise ValueError(f"Unknown template: {template}")

    base_dir = Path(settings.BASE_DIR)
    source_dockerfile_path = base_dir / dockerfile_relative_path
    if not source_dockerfile_path.exists():
        raise FileNotFoundError(f"Dockerfile not found at {source_dockerfile_path}")

    context_dir = Path(tempfile.mkdtemp(prefix=f"posthog-modal-build-{template.value}-"))
    destination_dockerfile_path = context_dir / dockerfile_relative_path
    destination_dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dockerfile_path, destination_dockerfile_path)

    # Both base and notebook Dockerfiles COPY the git and gh guards, so include
    # them in every local build context.
    destination_git_guard_path = context_dir / LOCAL_MODAL_GIT_GUARD_SCRIPT
    destination_git_guard_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_dir / LOCAL_MODAL_GIT_GUARD_SCRIPT, destination_git_guard_path)
    destination_gh_guard_path = context_dir / LOCAL_MODAL_GH_GUARD_SCRIPT
    destination_gh_guard_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_dir / LOCAL_MODAL_GH_GUARD_SCRIPT, destination_gh_guard_path)

    if template in {SandboxTemplate.DEFAULT_BASE, SandboxTemplate.VM_BASE}:
        destination_sampler_path = context_dir / LOCAL_MODAL_CPU_BILLING_SAMPLER
        destination_sampler_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_dir / LOCAL_MODAL_CPU_BILLING_SAMPLER, destination_sampler_path)

    if template == SandboxTemplate.DEFAULT_BASE:
        source_install_script_path = base_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path = context_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_install_script_path, destination_install_script_path)

        # Refresh dist/skills if out of date so the context picks up the
        # latest rendered output.
        LocalSkillsCache(base_dir).ensure_built()
        populate_skills_directory(context_dir / LOCAL_BUILT_SKILLS_PATH, base_dir=base_dir)

        shutil.copytree(base_dir / LOCAL_MODAL_AGENT_SHADOW_DIR, context_dir / LOCAL_MODAL_AGENT_SHADOW_DIR)

    elif template == SandboxTemplate.NOTEBOOK_BASE:
        destination_kernel_module_path = context_dir / LOCAL_MODAL_NOTEBOOK_KERNEL_MODULE
        destination_kernel_module_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_dir / LOCAL_MODAL_NOTEBOOK_KERNEL_MODULE, destination_kernel_module_path)
        # A checkout that ran the tests locally has bytecode here, and this context
        # bypasses .dockerignore, so drop it rather than bake it into the image.
        shutil.copytree(
            base_dir / LOCAL_MODAL_NOTEBOOK_KERNEL_DIR,
            context_dir / LOCAL_MODAL_NOTEBOOK_KERNEL_DIR,
            ignore=shutil.ignore_patterns("__pycache__"),
        )

    elif template == SandboxTemplate.STREAMLIT_BASE:
        # Copy all sibling files (streamlit_auth_proxy.py, etc.)
        # needed by COPY instructions in the Dockerfile
        source_images_dir = source_dockerfile_path.parent
        dest_images_dir = destination_dockerfile_path.parent
        for sibling in source_images_dir.iterdir():
            if sibling.is_file() and sibling != source_dockerfile_path:
                shutil.copy2(sibling, dest_images_dir / sibling.name)

    return str(destination_dockerfile_path), str(context_dir)


class ModalSandbox(AgentServerLaunchMixin):
    """
    Modal-based sandbox for production use.
    A box in the cloud. Sand optional.
    """

    id: str
    config: SandboxConfig
    _sandbox: modal.Sandbox
    _app: modal.App
    _sandbox_url: str | None
    provision_diagnostics: SandboxProvisionDiagnostics | None
    DEFAULT_APP_NAME = DEFAULT_MODAL_APP_NAME
    NOTEBOOK_APP_NAME = NOTEBOOK_MODAL_APP_NAME
    STREAMLIT_APP_NAME = STREAMLIT_MODAL_APP_NAME
    SELF_DRIVING_APP_NAME = SELF_DRIVING_MODAL_APP_NAME

    def __init__(self, sandbox: modal.Sandbox, config: SandboxConfig, sandbox_url: str | None = None):
        self.id = sandbox.object_id
        self.config = config
        self._sandbox = sandbox
        self._app = type(self)._get_app_for_config(config)
        self._sandbox_url = sandbox_url
        self.provision_diagnostics = None
        self._destroyed = False

    @property
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        return self._sandbox_url

    @classmethod
    def _template_app_name(cls, template: SandboxTemplate) -> str | None:
        """App a template owns outright, or None when it shares the general-purpose apps.

        Notebook and Streamlit boxes are their own products with their own images, so they stay
        in their own app whatever the workload — neither is ever self-driving.
        """
        if template == SandboxTemplate.NOTEBOOK_BASE:
            return cls.NOTEBOOK_APP_NAME
        if template == SandboxTemplate.STREAMLIT_BASE:
            return cls.STREAMLIT_APP_NAME
        return None

    @classmethod
    def _get_app_for_template(cls, template: SandboxTemplate) -> modal.App:
        """App for a template alone, ignoring workload. For image builds, where the built image
        is visible to every app in the workspace and so has no workload of its own."""
        return modal.App.lookup(cls._template_app_name(template) or cls.DEFAULT_APP_NAME, create_if_missing=True)

    @classmethod
    def _get_app_for_config(cls, config: SandboxConfig) -> modal.App:
        """App that owns this sandbox: the template's when it has one, otherwise the workload's."""
        app_name = cls._template_app_name(config.template)
        if app_name is None and config.workload == SandboxWorkload.SELF_DRIVING:
            app_name = cls.SELF_DRIVING_APP_NAME
        return modal.App.lookup(app_name or cls.DEFAULT_APP_NAME, create_if_missing=True)

    @classmethod
    def create(cls, config: SandboxConfig) -> ModalSandbox:
        try:
            modal.enable_output()
            app = cls._get_app_for_config(config)
            base_image = _get_template_image(config.template)
            custom_image_bare: modal.Image | None = None
            custom_image: modal.Image | None = None
            if config.custom_image_name:
                try:
                    custom_image_bare = modal.Image.from_name(config.custom_image_name)
                    # The prebaked dev-stack image is a published sandbox filesystem snapshot,
                    # which Modal cannot layer build steps on — mount-only overlay for it.
                    custom_image = _attach_local_package_mounts(
                        custom_image_bare,
                        config.template,
                        install_dependencies=config.custom_image_name != DEV_STACK_IMAGE_NAME,
                    )
                except Exception as e:
                    logger.warning(f"Failed to load custom image {config.custom_image_name}: {e}")
                    capture_exception(e)
            config.snapshot_restored = False
            config.image_fallback = None
            snapshot_external_id: str | None = None
            snapshot_kind = _normalize_snapshot_kind(config.snapshot_kind)
            # No default-fill: a directory snapshot must arrive with an explicit allowed mount
            # path, or the mount below is refused. Defaulting here would silently re-target a
            # snapshot that upstream validation invalidated (mount path stripped).
            snapshot_mount_path: str | None = config.snapshot_mount_path
            snapshot_image: modal.Image | None = None

            if config.snapshot_external_id:
                snapshot_external_id = config.snapshot_external_id
                try:
                    snapshot_image = modal.Image.from_id(config.snapshot_external_id)
                except Exception as e:
                    logger.warning(f"Failed to load resume snapshot image {config.snapshot_external_id}: {e}")
                    capture_exception(e)
            elif config.snapshot_id:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    snapshot_external_id = snapshot.external_id
                    snapshot_kind = _normalize_snapshot_kind(snapshot.metadata.get("snapshot_kind"))
                    metadata_mount_path = snapshot.metadata.get("snapshot_mount_path")
                    if isinstance(metadata_mount_path, str) and metadata_mount_path:
                        snapshot_mount_path = metadata_mount_path
                    try:
                        snapshot_image = modal.Image.from_id(snapshot.external_id)
                    except Exception as e:
                        logger.warning(f"Failed to load snapshot image {snapshot.external_id}: {e}")
                        capture_exception(e)
            # Keep the config's kind authoritative for downstream trust decisions — the
            # dev-stack bootstrap gate distinguishes directory from filesystem restores.
            config.snapshot_kind = snapshot_kind

            # Creation candidates, best first. Each later entry is a downgrade attempted only
            # when creating from the previous image fails (e.g. its overlay image build errors),
            # so a broken overlay costs the local packages, never the snapshot or custom image.
            candidates: list[ImageCandidate] = []
            if snapshot_image is not None and snapshot_kind == SNAPSHOT_KIND_FILESYSTEM:
                overlaid_snapshot = _attach_local_package_mounts(
                    snapshot_image, config.template, install_dependencies=False
                )
                if overlaid_snapshot is not snapshot_image:
                    candidates.append(
                        ImageCandidate(
                            overlaid_snapshot,
                            f"snapshot image {snapshot_external_id} with local package overlay",
                            restored_from_snapshot=True,
                            snapshot_derived=True,
                        )
                    )
                candidates.append(
                    ImageCandidate(
                        snapshot_image,
                        f"snapshot image {snapshot_external_id}",
                        restored_from_snapshot=True,
                        snapshot_derived=True,
                    )
                )
            if custom_image is not None and custom_image_bare is not None:
                # The published dev-stack image is itself a sandbox filesystem snapshot
                # (dockerd cannot run in the gVisor image builder), so booting it is the
                # same restore the health probe guards; user custom images are spec-built.
                custom_is_snapshot = config.custom_image_name == DEV_STACK_IMAGE_NAME
                if custom_image is not custom_image_bare:
                    candidates.append(
                        ImageCandidate(
                            custom_image,
                            f"custom image {config.custom_image_name} with local package overlay",
                            snapshot_derived=custom_is_snapshot,
                        )
                    )
                candidates.append(
                    ImageCandidate(
                        custom_image_bare,
                        f"custom image {config.custom_image_name}",
                        snapshot_derived=custom_is_snapshot,
                    )
                )
            candidates.append(ImageCandidate(base_image, "base image"))

            secrets = []
            if config.environment_variables:
                env_dict = cast(dict[str, str | None], config.environment_variables)
                secret = modal.Secret.from_dict(env_dict)
                secrets.append(secret)

            sandbox_name = f"{config.name}-{uuid.uuid4().hex[:6]}"

            region = _get_modal_region()

            create_kwargs: dict[str, object] = {
                "app": app,
                "name": sandbox_name,
                "timeout": config.ttl_seconds,
                **_resource_create_kwargs(config),
                "region": region,
                "verbose": True,
            }

            if config.is_vm:
                create_kwargs["experimental_options"] = {"vm_runtime": True}

            if config.block_network:
                create_kwargs["block_network"] = True

            if config.outbound_domain_allowlist is not None:
                create_kwargs["outbound_domain_allowlist"] = config.outbound_domain_allowlist

            if secrets:
                create_kwargs["secrets"] = secrets

            sb, modal_output, winner = cls._create_from_image_candidates(create_kwargs, candidates, config)

            if snapshot_kind == SNAPSHOT_KIND_DIRECTORY and snapshot_image is not None:
                # The mount REPLACES the target directory in the running sandbox — over a live
                # system path (the legacy "/tmp" default) that kills Modal's in-sandbox helpers,
                # and a snapshot's content only fits the path it was captured from. Last-line
                # guard for snapshot rows whose stored mount path bypassed normalization.
                if snapshot_mount_path not in ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS:
                    logger.warning(
                        "Refusing to mount directory snapshot at unsupported path; falling back to base image",
                        extra={
                            "snapshot_external_id": snapshot_external_id,
                            "snapshot_mount_path": snapshot_mount_path,
                        },
                    )
                elif not hasattr(sb, "mount_image"):
                    logger.warning(
                        "Modal sandbox does not support directory snapshot restore; falling back to base image",
                        extra={
                            "snapshot_external_id": snapshot_external_id,
                            "snapshot_mount_path": snapshot_mount_path,
                        },
                    )
                else:
                    try:
                        sb.mount_image(snapshot_mount_path, snapshot_image)
                        config.snapshot_restored = True
                    except Exception as e:
                        logger.warning(
                            f"Failed to mount directory snapshot image {snapshot_external_id} at {snapshot_mount_path}: {e}"
                        )
                        capture_exception(e)

            # A sandbox whose filesystem came out of a Modal snapshot restore can come up
            # dead with every RPC succeeding — probe before use. That covers resume
            # snapshots (image or directory mount) and the published dev-stack image,
            # which is itself a sandbox filesystem snapshot; spec-built images boot
            # normally and skip the probe. Loops because a recovery can land on another
            # snapshot-derived tier (resume snapshot -> dev-stack image -> base).
            while (config.snapshot_restored or winner.snapshot_derived) and not cls._is_healthy_after_restore(sb):
                logger.warning(
                    "Snapshot-restored sandbox is not executing processes; recreating from the remaining image candidates",
                    extra={
                        "sandbox_id": sb.object_id,
                        "winner_label": winner.label,
                        "snapshot_external_id": snapshot_external_id,
                        "snapshot_kind": snapshot_kind,
                        "snapshot_mount_path": snapshot_mount_path,
                    },
                )
                try:
                    sb.terminate()
                except Exception as e:
                    logger.warning(f"Failed to terminate wedged sandbox {sb.object_id}: {e}")
                if config.snapshot_restored and not winner.restored_from_snapshot:
                    # The directory resume mount (not the image) wedged the sandbox:
                    # recreate on the same chain and leave the mount off. The run loses
                    # its resume state — exactly what the fallback message must say,
                    # rather than implying an image downgrade that never happened.
                    wedged = (
                        f"directory resume snapshot {snapshot_external_id} "
                        "(sandbox unresponsive after mount; resume state dropped)"
                    )
                    remaining = [c for c in candidates if not c.restored_from_snapshot]
                else:
                    # The winning image itself restored wedged: drop it and every tier
                    # above it, along with any resume-snapshot candidates.
                    wedged = f"{winner.label} (unresponsive after restore)"
                    remaining = [c for c in candidates[candidates.index(winner) + 1 :] if not c.restored_from_snapshot]
                sb, modal_output, winner = cls._create_from_image_candidates(create_kwargs, remaining, config)
                config.image_fallback = f"{wedged} -> {winner.label}"

            if config.metadata:
                sb.set_tags(config.metadata)

            sandbox = cls(sandbox=sb, config=config)
            if modal_output is not None:
                sandbox.provision_diagnostics = summarize_modal_output(modal_output.getvalue())

            logger.info(
                f"Created sandbox {sandbox.id} for {config.name}",
                extra={"modal_app": getattr(app, "name", None), "workload": config.workload.value},
            )

            return sandbox

        except SandboxNetworkPolicyError:
            raise
        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(
                "Failed to create sandbox", {"config_name": config.name, "error": str(e)}, cause=e
            ) from e

    @staticmethod
    def _create_from_image_candidates(
        create_kwargs: dict[str, object],
        candidates: list[ImageCandidate],
        config: SandboxConfig,
    ) -> tuple[modal.Sandbox, StringIO | None, ImageCandidate]:
        """Create the sandbox from the best image candidate that works, downgrading in order.

        A downgrade is recorded on ``config.image_fallback`` so callers can surface it in
        run-visible logs instead of the run silently landing on a lesser image. The last
        candidate's failure propagates. Returns the winning candidate so callers that
        re-enter this chain (the wedged-restore recovery) can describe what they landed on.
        """
        for index, candidate in enumerate(candidates):
            attempt_kwargs = {**create_kwargs, "image": candidate.image}
            try:
                modal_output: StringIO | None
                with capture_modal_output_if_debug() as modal_output:
                    sb = modal.Sandbox.create(**attempt_kwargs)  # type: ignore[arg-type]
            except Exception as e:
                if config.outbound_domain_allowlist is not None and _is_modal_network_policy_rejection(e):
                    raise SandboxNetworkPolicyError(
                        "Modal rejected the requested sandbox network policy.",
                        {
                            "config_name": config.name,
                            "network_policy_fingerprint": config.network_policy_fingerprint,
                            "error": str(e),
                        },
                        cause=e,
                    ) from e
                if index == len(candidates) - 1:
                    raise
                logger.warning(
                    f"Failed to create sandbox with {candidate.label}, "
                    f"falling back to {candidates[index + 1].label}: {e}"
                )
                capture_exception(e)
                continue
            config.snapshot_restored = candidate.restored_from_snapshot
            if index > 0:
                config.image_fallback = f"{candidates[0].label} -> {candidate.label}"
            return sb, modal_output, candidate
        raise SandboxProvisionError(
            "No sandbox image candidates to create from",
            {"config_name": config.name},
            cause=RuntimeError("empty image candidate list"),
        )

    @staticmethod
    def _is_healthy_after_restore(sb: modal.Sandbox) -> bool:
        """Whether the sandbox executes processes after a snapshot restore (image or mount)."""
        try:
            process = sb.exec("true", timeout=30)
            # ContainerProcess.wait() has no timeout and can hang on a wedged container.
            deadline = time.monotonic() + POST_RESTORE_PROBE_TIMEOUT_SECONDS
            while (returncode := process.poll()) is None:
                if time.monotonic() >= deadline:
                    logger.warning(f"Post-restore health probe timed out for sandbox {sb.object_id}")
                    return False
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Post-restore health probe errored for sandbox {sb.object_id}: {e}")
            return False
        if returncode != 0:
            poll_result: int | str | None
            try:
                poll_result = sb.poll()
            except Exception:
                poll_result = "unavailable"
            logger.warning(
                "Post-restore health probe exited non-zero",
                extra={"sandbox_id": sb.object_id, "returncode": returncode, "sandbox_poll": str(poll_result)},
            )
            return False
        return True

    @staticmethod
    def get_by_id(sandbox_id: str) -> ModalSandbox:
        try:
            sb = modal.Sandbox.from_id(sandbox_id)

            config = SandboxConfig(name=getattr(sb, "name", f"sandbox-{sandbox_id}"))

            return ModalSandbox(sandbox=sb, config=config)

        except Exception as e:
            logger.exception(f"Failed to retrieve sandbox {sandbox_id}: {e}")
            raise SandboxNotFoundError(
                f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)}, cause=e
            )

    def get_status(self) -> SandboxStatus:
        return SandboxStatus.SHUTDOWN if self._destroyed or self._sandbox.poll() is not None else SandboxStatus.RUNNING

    def execute(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        if not self.is_running():
            raise SandboxNotRunningError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            redacted_command = redact_sandbox_command(command)
            process = self._sandbox.exec("bash", "-c", command, timeout=timeout_seconds)

            process.wait()

            stdout = process.stdout.read()
            stderr = process.stderr.read()

            result = ExecutionResult(
                stdout=stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout,  # type: ignore[unreachable]
                stderr=stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr,  # type: ignore[unreachable]
                exit_code=process.returncode,
                error=None,
            )

            return result

        except TimeoutError as e:
            capture_exception(e)
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=e,
            )
        except Exception as e:
            redacted_error = redact_sandbox_command(str(e))
            # Provider exceptions can echo the shell command, so avoid exc_info here.
            logger.error(  # noqa: TRY400
                "Failed to execute command", extra={"sandbox_id": self.id, "redacted_error": redacted_error}
            )
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": redacted_command, "error": redacted_error},
                cause=RuntimeError(redacted_error),
            )

    def execute_stream(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> ExecutionStream:
        if not self.is_running():
            raise SandboxNotRunningError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            redacted_command = redact_sandbox_command(command)
            process = self._sandbox.exec("bash", "-c", command, timeout=timeout_seconds)
        except TimeoutError as e:
            capture_exception(e)
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=e,
            )
        except Exception as e:
            redacted_error = redact_sandbox_command(str(e))
            # Provider exceptions can echo the shell command, so avoid exc_info here.
            logger.error(  # noqa: TRY400
                "Failed to execute command", extra={"sandbox_id": self.id, "redacted_error": redacted_error}
            )
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": redacted_command, "error": redacted_error},
                cause=RuntimeError(redacted_error),
            )

        class _ModalExecutionStream:
            def __init__(self, process: Any):
                self._process = process
                self._stdout_buffer: list[str] = []
                self._stdout_iterated = False

            def iter_stdout(self) -> Iterable[str]:
                self._stdout_iterated = True
                for line in self._process.stdout:
                    output = line.decode("utf-8") if isinstance(line, bytes) else line
                    self._stdout_buffer.append(output)
                    yield output

            def wait(self) -> ExecutionResult:
                self._process.wait()
                if not self._stdout_iterated:
                    stdout = self._process.stdout.read()
                    stdout_text = stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout
                else:
                    stdout_text = "".join(self._stdout_buffer)

                stderr = self._process.stderr.read()
                stderr_text = stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr
                return ExecutionResult(
                    stdout=stdout_text,
                    stderr=stderr_text,
                    exit_code=self._process.returncode,
                    error=None,
                )

        return _ModalExecutionStream(process)

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        if not self.is_running():
            raise SandboxNotRunningError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        temp_path = f"{path}.tmp-{uuid.uuid4().hex}"
        try:
            self._sandbox.filesystem.write_bytes(payload, temp_path)
            mv_command = f"mv {shlex.quote(temp_path)} {shlex.quote(path)}"
            result = self.execute(
                mv_command, timeout_seconds=timeout_seconds or self.config.default_execution_timeout_seconds
            )
            if result.exit_code != 0:
                logger.warning(
                    "sandbox_write_failed",
                    extra={"stdout": result.stdout, "stderr": result.stderr, "sandbox_id": self.id},
                )
            return result
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to write file to sandbox: {e}")
            raise SandboxExecutionError(
                "Failed to write file",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
            )

    def setup_repository(self, repository: str) -> ExecutionResult:
        """No-op: Repository setup is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {shlex.quote(repo_path)} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult:
        """No-op: Task execution is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def get_connect_credentials(self) -> AgentServerResult:
        """Get connect credentials (URL and token) for this sandbox.

        Modal connect tokens provide authenticated HTTP access to port 8080 in the sandbox.
        Should be called after sandbox creation to get the URL and token needed for connection.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        credentials = self._sandbox.create_connect_token()
        self._sandbox_url = credentials.url

        logger.info(f"Got connect credentials for sandbox {self.id}: {credentials.url}")
        return AgentServerResult(url=credentials.url, token=credentials.token)

    def create_preview_connect_credentials(self, port: int, user_metadata: dict[str, Any]) -> AgentServerResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        credentials = self._sandbox.create_connect_token(user_metadata=user_metadata, port=port)

        logger.info(f"Minted preview connect credentials for sandbox {self.id} on port {port}")
        return AgentServerResult(url=credentials.url, token=credentials.token)

    def _termination_failure_reason(self) -> str:
        poll = self._sandbox.poll()
        return (
            f"sandbox terminated before becoming healthy (poll={poll}); "
            "the VM/container exited (OOM, init exit, or reaping) rather than egress being blocked"
        )

    def _snapshot_filesystem_image(
        self, publish_name: str | None = None, *, timeout_seconds: int = FILESYSTEM_SNAPSHOT_TIMEOUT_SECONDS
    ) -> str:
        """Guarded filesystem snapshot, optionally published under a Modal image name.

        Returns the snapshot image's object id.
        """
        if not self.is_running():
            raise SandboxNotRunningError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        error_context = {"sandbox_id": self.id, **({"publish_name": publish_name} if publish_name else {})}
        try:
            # Modal can report the sandbox as running before filesystem snapshotting is ready.
            self._sandbox.exec("true", timeout=30).wait()
            # ttl=None keeps indefinite retention; modal 1.5.0 otherwise defaults snapshots to a 30-day TTL.
            image = self._sandbox.snapshot_filesystem(timeout=timeout_seconds, ttl=None)
            if publish_name is not None:
                image.publish(publish_name)
                logger.info(f"Published filesystem image {publish_name} ({image.object_id}) from sandbox {self.id}")
            else:
                logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {image.object_id}")
            return image.object_id

        except ModalResourceExhaustedError as e:
            if _is_snapshot_file_cap_error(e):
                # Modal rejects a snapshot whose tree exceeds its hard 1M-file cap. Permanent, not
                # transient: classify it separately so it neither retries forever nor mints a generic
                # captured issue.
                logger.warning(f"Filesystem snapshot for sandbox {self.id} exceeds Modal's file-count cap: {e}")
                raise SnapshotFileLimitExceededError(
                    f"Filesystem snapshot exceeds Modal's file-count cap: {e}",
                    {**error_context, "error": str(e)},
                    cause=e,
                )
            # A generic RESOURCE_EXHAUSTED (server-side quota / rate limit) is transient — let the
            # caller's retry recover it instead of failing permanently.
            logger.warning(f"Transient resource-exhausted error creating snapshot for sandbox {self.id}: {e}")
            raise SnapshotTimeoutError(
                f"Transient resource-exhausted error creating snapshot: {e}",
                {**error_context, "error": str(e)},
                cause=e,
                capture=False,
            )

        except TRANSIENT_SNAPSHOT_ERRORS as e:
            # Transient Modal infra timeout — Temporal retries the activity, so log at warning and
            # skip error-tracking capture to avoid a fresh issue for every recoverable deadline.
            logger.warning(f"Transient error creating snapshot for sandbox {self.id}, will retry: {e}")
            raise SnapshotTimeoutError(
                f"Transient error creating snapshot: {e}",
                {**error_context, "error": str(e)},
                cause=e,
                capture=False,
            )

        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(f"Failed to create snapshot: {e}", {**error_context, "error": str(e)}, cause=e)

    def create_snapshot(self, *, timeout_seconds: int | None = None) -> str:
        return self._snapshot_filesystem_image(
            timeout_seconds=timeout_seconds if timeout_seconds is not None else FILESYSTEM_SNAPSHOT_TIMEOUT_SECONDS
        )

    def prune_snapshot_heavy_dirs(self, path: str) -> None:
        """Delete reproducible package/cache trees under ``path`` so a later snapshot fits under
        Modal's file-count cap. Best-effort: a failure here must not crash the caller — a partial
        prune may already have shrunk the tree enough, and the caller decides what to do next.
        """
        quoted_path = shlex.quote(path)
        name_predicate = " -o ".join(f"-name {shlex.quote(name)}" for name in SNAPSHOT_PRUNE_DIR_NAMES)
        prune_command = (
            f"find {quoted_path} -type d \\( {name_predicate} \\) -prune -exec rm -rf {{}} + 2>/dev/null || true"
        )
        try:
            self.execute(prune_command, timeout_seconds=SNAPSHOT_PRUNE_TIMEOUT_SECONDS)
            logger.info(f"Pruned heavy directories under {path} for sandbox {self.id}")
        except Exception as e:
            logger.warning(f"Best-effort prune of heavy directories under {path} failed for sandbox {self.id}: {e}")

    def create_directory_snapshot(self, path: str) -> str:
        if not self.is_running():
            raise SandboxNotRunningError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        snapshot_directory = getattr(self._sandbox, "snapshot_directory", None)
        if snapshot_directory is None:
            raise SnapshotCreationError(
                "Modal SDK does not support directory snapshots",
                {"sandbox_id": self.id, "path": path},
                cause=RuntimeError("modal.Sandbox.snapshot_directory is unavailable"),
            )

        try:
            quoted_path = shlex.quote(path)
            self._sandbox.exec("bash", "-c", f"mkdir -p {quoted_path} && test -d {quoted_path}", timeout=30).wait()
            image = snapshot_directory(path, timeout=DIRECTORY_SNAPSHOT_TIMEOUT_SECONDS, ttl=None)
            snapshot_id = image.object_id

            logger.info(f"Created directory snapshot for sandbox {self.id}, path: {path}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except ModalResourceExhaustedError as e:
            if _is_snapshot_file_cap_error(e):
                # Modal rejects a snapshot whose tree exceeds its hard 1M-file cap. This is permanent,
                # not transient — retrying the same tree cannot succeed — so classify it separately
                # (the caller prunes the tree and retries) instead of misclassifying it as a generic error.
                logger.warning(f"Directory snapshot for sandbox {self.id} exceeds Modal's file-count cap: {e}")
                raise SnapshotFileLimitExceededError(
                    f"Directory snapshot exceeds Modal's file-count cap: {e}",
                    {"sandbox_id": self.id, "path": path, "error": str(e)},
                    cause=e,
                )
            # A generic RESOURCE_EXHAUSTED (server-side quota / rate limit) is transient — let the
            # caller's retry recover it instead of failing permanently.
            logger.warning(f"Transient resource-exhausted error creating directory snapshot for sandbox {self.id}: {e}")
            raise SnapshotTimeoutError(
                f"Transient resource-exhausted error creating directory snapshot: {e}",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
                capture=False,
            )

        except TRANSIENT_SNAPSHOT_ERRORS as e:
            logger.warning(f"Transient error creating directory snapshot for sandbox {self.id}, will retry: {e}")
            raise SnapshotTimeoutError(
                f"Transient error creating directory snapshot: {e}",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
                capture=False,
            )

        except Exception as e:
            logger.exception(f"Failed to create directory snapshot: {e}")
            raise SnapshotCreationError(
                f"Failed to create directory snapshot: {e}",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
            )

    def publish_filesystem_image(self, publish_name: str) -> str:
        """Snapshot the filesystem and publish it as a named Modal image.

        Republishing an existing name moves it to the new snapshot, so a fixed name
        (e.g. the prebaked dev-stack image) can be refreshed without touching its
        consumers. Returns the snapshot image's object id.
        """
        return self._snapshot_filesystem_image(publish_name, timeout_seconds=PUBLISHED_IMAGE_SNAPSHOT_TIMEOUT_SECONDS)

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Deleting snapshot {external_id}")
        try:
            logger.info(f"Snapshot {external_id} marked for cleanup")
        except Exception as e:
            logger.warning(f"Failed to delete snapshot {external_id}: {e}")

    def destroy(self) -> None:
        try:
            self._sandbox.terminate()
            self._destroyed = True
            logger.info(f"Destroyed sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

    def read_cpu_usage_usec(self) -> int | None:
        try:
            cpu_stat = self._sandbox.filesystem.read_text("/sys/fs/cgroup/cpu.stat")
        except Exception:
            cpu_stat = None
        if cpu_stat is not None and (usage := parse_cpu_stat_usage_usec(cpu_stat)) is not None:
            return usage
        try:
            cpuacct_usage = self._sandbox.filesystem.read_text("/sys/fs/cgroup/cpuacct/cpuacct.usage")
            if cpuacct_usage.strip():
                return int(cpuacct_usage) // 1000
        except Exception:
            pass
        return None

    def _cpu_billing_request_cores(self) -> float:
        return self.config.effective_cpu_request_cores if self.config.burstable_resources else self.config.cpu_cores

    def start_cpu_billing_sampler(self) -> bool:
        result = self.execute(build_sampler_start_command(self._cpu_billing_request_cores()), timeout_seconds=10)
        return result.exit_code == 0

    def read_billed_cpu_usage_usec(self) -> int | None:
        state_text = self._sandbox.filesystem.read_text(CPU_BILLING_STATE_PATH)
        current_cpu = self.read_cpu_usage_usec()
        if current_cpu is None:
            return None
        return compute_billed_cpu_usage_usec(state_text, current_cpu, self._cpu_billing_request_cores(), time.time_ns())

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
