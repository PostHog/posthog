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
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings

from cachetools import TTLCache, cached

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

import modal
import requests
from modal.exception import (
    ConnectionError as ModalConnectionError,
    ServiceError as ModalServiceError,
    TimeoutError as ModalTimeoutError,
)

from posthog.exceptions_capture import capture_exception
from posthog.settings import CLOUD_DEPLOYMENT

from products.tasks.backend.constants import (
    ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS,
    SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
    SnapshotKind,
)
from products.tasks.backend.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxNotRunningError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
    SnapshotTimeoutError,
)
from products.tasks.backend.logic.services.agentsh import (
    AGENTSH_DAEMON_PORT,
    BASH_ENV_SCRIPT,
    ENV_FILE,
    ENV_WRAPPER_SCRIPT,
    SESSION_ID_FILE,
    _hostname_from_url,
    build_exec_prefix,
    build_setup_script,
    generate_bash_env_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
)
from products.tasks.backend.logic.services.local_packages import get_local_posthog_code_packages
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
from products.tasks.backend.logic.services.sandbox import (
    WORKING_DIR,
    SandboxBase,
    build_agent_runtime_env_prefix,
    redact_sandbox_command,
    wait_for_health_check,
)
from products.tasks.backend.models import SandboxSnapshot

from .sandbox import AgentServerResult, ExecutionResult, ExecutionStream, SandboxConfig, SandboxStatus, SandboxTemplate

logger = logging.getLogger(__name__)

DEFAULT_MODAL_APP_NAME = "posthog-sandbox-default"
NOTEBOOK_MODAL_APP_NAME = "posthog-sandbox-notebook"
STREAMLIT_MODAL_APP_NAME = "posthog-sandbox-streamlit"

SANDBOX_BASE_IMAGE = "ghcr.io/posthog/posthog-sandbox-base"
SANDBOX_NOTEBOOK_IMAGE = "ghcr.io/posthog/posthog-sandbox-notebook"
SANDBOX_VM_IMAGE = "ghcr.io/posthog/posthog-sandbox-vm"
SANDBOX_STREAMLIT_IMAGE = "ghcr.io/posthog/posthog-sandbox-streamlit"
SANDBOX_IMAGE = SANDBOX_BASE_IMAGE
AGENT_SERVER_PORT = 8080  # Modal connect tokens require port 8080
AGENT_SERVER_HEALTH_MAX_ATTEMPTS = 240
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

SESSION_INIT_PROBE_HOSTS = (
    "gateway.us.posthog.com",
    "gateway.eu.posthog.com",
    "api.anthropic.com",
    "mcp.posthog.com",
)

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

    The burstable request floor comes from ``cpu_request_cores`` / ``memory_request_mb`` (defaulting
    to the small floor in ``sandbox_config``). The request is clamped to the limit so it never
    exceeds it when the configured size is at or below the requested floor.
    """
    cpu_limit = float(config.cpu_cores)
    memory_limit_mb = int(config.memory_gb * 1024)
    if not config.burstable_resources:
        return {"cpu": cpu_limit, "memory": memory_limit_mb}

    cpu_value = (min(float(config.cpu_request_cores), cpu_limit), cpu_limit)
    if config.is_vm:
        return {"cpu": cpu_value, "memory": memory_limit_mb}
    return {
        "cpu": cpu_value,
        "memory": (min(int(config.memory_request_mb), memory_limit_mb), memory_limit_mb),
    }


LOCAL_MODAL_DOCKERFILES = {
    SandboxTemplate.DEFAULT_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"),
    SandboxTemplate.NOTEBOOK_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-notebook"),
    SandboxTemplate.VM_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-vm"),
    SandboxTemplate.STREAMLIT_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-streamlit"),
}
LOCAL_MODAL_INSTALL_SKILLS_SCRIPT = Path("products/tasks/backend/sandbox/images/install-skills.sh")
LOCAL_MODAL_GIT_GUARD_SCRIPT = Path("products/tasks/backend/sandbox/images/git-guard.sh")


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


def _attach_local_package_mounts(image: modal.Image, template: SandboxTemplate) -> modal.Image:
    """Overlay each local package's built `dist/` dir onto the installed package
    via add_local_dir(copy=False). No-op unless `template` bundles the agent-server
    and local packages are available.

    Transitive deps are resolved from the baked /scripts/node_modules/ tree;
    only compiled output is swapped live.
    """
    if template not in AGENT_SERVER_TEMPLATES:
        return image
    packages = get_local_posthog_code_packages()
    if not packages:
        return image
    for package in packages:
        image = image.add_local_dir(
            str(package.build_output_path),
            package.sandbox_build_output_path,
            copy=False,
        )
    return image


_template_image_cache: TTLCache = TTLCache(maxsize=3, ttl=300)
_template_image_lock = threading.Lock()


@cached(cache=_template_image_cache, lock=_template_image_lock)
def get_template_base_image(template: SandboxTemplate) -> modal.Image:
    """The template's base image without local dev mounts — safe to extend with further layers."""
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
    return modal.Image.from_registry(_get_sandbox_image_reference(registry_image))


def _get_template_image(template: SandboxTemplate) -> modal.Image:
    return _attach_local_package_mounts(get_template_base_image(template), template)


def resolve_template_base_image(template: SandboxTemplate) -> modal.Image:
    # Undecorated import surface: the @cached wrapper on get_template_base_image trips
    # mypy's cross-module attribute resolution intermittently, so external callers import this.
    return get_template_base_image(template)


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

    # Both base and notebook Dockerfiles COPY the git guard, so include it in
    # every local build context.
    destination_git_guard_path = context_dir / LOCAL_MODAL_GIT_GUARD_SCRIPT
    destination_git_guard_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_dir / LOCAL_MODAL_GIT_GUARD_SCRIPT, destination_git_guard_path)

    if template == SandboxTemplate.DEFAULT_BASE:
        source_install_script_path = base_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path = context_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_install_script_path, destination_install_script_path)

        # Refresh dist/skills if out of date so the context picks up the
        # latest rendered output.
        LocalSkillsCache(base_dir).ensure_built()
        populate_skills_directory(context_dir / LOCAL_BUILT_SKILLS_PATH, base_dir=base_dir)

    elif template == SandboxTemplate.STREAMLIT_BASE:
        # Copy all sibling files (streamlit_auth_proxy.py, etc.)
        # needed by COPY instructions in the Dockerfile
        source_images_dir = source_dockerfile_path.parent
        dest_images_dir = destination_dockerfile_path.parent
        for sibling in source_images_dir.iterdir():
            if sibling.is_file() and sibling != source_dockerfile_path:
                shutil.copy2(sibling, dest_images_dir / sibling.name)

    return str(destination_dockerfile_path), str(context_dir)


class ModalSandbox(SandboxBase):
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

    def __init__(self, sandbox: modal.Sandbox, config: SandboxConfig, sandbox_url: str | None = None):
        self.id = sandbox.object_id
        self.config = config
        self._sandbox = sandbox
        self._app = type(self)._get_app_for_template(config.template)
        self._sandbox_url = sandbox_url
        self.provision_diagnostics = None

    @property
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        return self._sandbox_url

    @classmethod
    def _get_default_app(cls) -> modal.App:
        return modal.App.lookup(cls.DEFAULT_APP_NAME, create_if_missing=True)

    @classmethod
    def _get_app_for_template(cls, template: SandboxTemplate) -> modal.App:
        if template == SandboxTemplate.NOTEBOOK_BASE:
            return modal.App.lookup(cls.NOTEBOOK_APP_NAME, create_if_missing=True)
        if template == SandboxTemplate.STREAMLIT_BASE:
            return modal.App.lookup(STREAMLIT_MODAL_APP_NAME, create_if_missing=True)
        return cls._get_default_app()

    @classmethod
    def create(cls, config: SandboxConfig) -> ModalSandbox:
        try:
            modal.enable_output()
            app = cls._get_app_for_template(config.template)
            base_image = _get_template_image(config.template)
            image = base_image
            custom_image: modal.Image | None = None
            if config.custom_image_name:
                try:
                    custom_image = _attach_local_package_mounts(
                        modal.Image.from_name(config.custom_image_name), config.template
                    )
                    image = custom_image
                except Exception as e:
                    logger.warning(f"Failed to load custom image {config.custom_image_name}: {e}")
                    capture_exception(e)
            used_custom_image = custom_image is not None
            config.snapshot_restored = False
            snapshot_external_id: str | None = None
            snapshot_kind = _normalize_snapshot_kind(config.snapshot_kind)
            # No default-fill: a directory snapshot must arrive with an explicit allowed mount
            # path, or the mount below is refused. Defaulting here would silently re-target a
            # snapshot that upstream validation invalidated (mount path stripped).
            snapshot_mount_path: str | None = config.snapshot_mount_path
            snapshot_image: modal.Image | None = None
            used_snapshot_image = False

            if config.snapshot_external_id:
                snapshot_external_id = config.snapshot_external_id
                try:
                    snapshot_image = modal.Image.from_id(config.snapshot_external_id)
                    if snapshot_kind == SNAPSHOT_KIND_FILESYSTEM:
                        image = _attach_local_package_mounts(snapshot_image, config.template)
                        used_snapshot_image = True
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
                        if snapshot_kind == SNAPSHOT_KIND_FILESYSTEM:
                            image = _attach_local_package_mounts(snapshot_image, config.template)
                            used_snapshot_image = True
                    except Exception as e:
                        logger.warning(f"Failed to load snapshot image {snapshot.external_id}: {e}")
                        capture_exception(e)

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
                "image": image,
                "timeout": config.ttl_seconds,
                **_resource_create_kwargs(config),
                "region": region,
                "verbose": True,
            }

            if config.is_vm:
                create_kwargs["experimental_options"] = {"vm_runtime": True}

            if config.outbound_domain_allowlist:
                create_kwargs["outbound_domain_allowlist"] = config.outbound_domain_allowlist

            if secrets:
                create_kwargs["secrets"] = secrets

            try:
                modal_output: StringIO | None
                with capture_modal_output_if_debug() as modal_output:
                    sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]
                    config.snapshot_restored = used_snapshot_image
            except Exception as e:
                if not used_snapshot_image and not used_custom_image:
                    raise
                fallback_image = custom_image if used_snapshot_image and custom_image is not None else base_image
                logger.warning(
                    f"Failed to create sandbox with {'snapshot' if used_snapshot_image else 'custom'} image, "
                    f"falling back to {'custom' if fallback_image is custom_image else 'base'} image: {e}"
                )
                capture_exception(e)
                create_kwargs["image"] = fallback_image
                try:
                    with capture_modal_output_if_debug() as modal_output:
                        sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]
                        config.snapshot_restored = False
                except Exception as fallback_error:
                    if fallback_image is base_image:
                        raise
                    logger.warning(
                        f"Failed to create sandbox with custom image, falling back to base image: {fallback_error}"
                    )
                    capture_exception(fallback_error)
                    create_kwargs["image"] = base_image
                    with capture_modal_output_if_debug() as modal_output:
                        sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]
                        config.snapshot_restored = False

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

            # A restored sandbox can come up dead with every RPC succeeding; probe before use.
            if config.snapshot_restored and not cls._is_healthy_after_restore(sb):
                logger.warning(
                    "Snapshot-restored sandbox is not executing processes; recreating from base image",
                    extra={
                        "sandbox_id": sb.object_id,
                        "snapshot_external_id": snapshot_external_id,
                        "snapshot_kind": snapshot_kind,
                        "snapshot_mount_path": snapshot_mount_path,
                    },
                )
                try:
                    sb.terminate()
                except Exception as e:
                    logger.warning(f"Failed to terminate wedged sandbox {sb.object_id}: {e}")
                create_kwargs["image"] = base_image
                with capture_modal_output_if_debug() as modal_output:
                    sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]
                config.snapshot_restored = False

            if config.metadata:
                sb.set_tags(config.metadata)

            sandbox = cls(sandbox=sb, config=config)
            if modal_output is not None:
                sandbox.provision_diagnostics = summarize_modal_output(modal_output.getvalue())

            logger.info(f"Created sandbox {sandbox.id} for {config.name}")

            return sandbox

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(
                "Failed to create sandbox", {"config_name": config.name, "error": str(e)}, cause=e
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
        return SandboxStatus.RUNNING if self._sandbox.poll() is None else SandboxStatus.SHUTDOWN

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

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
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
            result = self.execute(mv_command, timeout_seconds=self.config.default_execution_timeout_seconds)
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

    def _build_agent_server_command(
        self,
        repo_path: str | None,
        task_id: str,
        run_id: str,
        mode: str,
        create_pr: bool,
        auto_publish: bool = False,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_servers_arg: str = "",
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
    ) -> str:
        env_prefix = build_agent_runtime_env_prefix(
            interaction_origin=interaction_origin,
            runtime_adapter=runtime_adapter,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            event_ingest_token=event_ingest_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
        )
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        # Only append when opted in: agent-server builds without the option reject unknown
        # flags, so default runs (and resumes of old snapshots) must not see it.
        auto_publish_flag = " --autoPublish true" if auto_publish else ""
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        domains_flag = f" --allowedDomains {shlex.quote(','.join(allowed_domains))}" if allowed_domains else ""
        repo_ready_flag = f" --repoReadyFile {shlex.quote(repo_ready_file)}" if repo_ready_file else ""
        # Scope BASH_ENV to the agent-server process (not the container env) so only the
        # agent's per-command tool shells re-source the refreshed token. Backend maintenance
        # execs (clone/checkout/token injection) must not source it — the script could be
        # persisted in a resume snapshot, so sourcing it from a backend exec is a trust hole.
        unset_flags = "".join(f"-u {name} " for name in SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS)
        server_cmd = (
            f"env {unset_flags}BASH_ENV={shlex.quote(BASH_ENV_SCRIPT)} "
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{auto_publish_flag}{branch_flag}{mcp_servers_arg}{domains_flag}{repo_ready_flag}"
        )

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"

        if allowed_domains is not None:
            return (
                f"cd /scripts && env -0 > {ENV_FILE} && "
                f"{build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(inner)} &"
            )
        else:
            return f"cd /scripts && env -0 > {ENV_FILE} && nohup {server_cmd} > /tmp/agent-server.log 2>&1 &"

    def _diagnose_startup_failure(self, allowed_domains: list[str] | None) -> dict[str, str]:
        diagnostics: dict[str, str] = {}
        try:
            if not self.is_running():
                poll = self._sandbox.poll()
                diagnostics["sandbox_terminated"] = "true"
                diagnostics["failure_reason"] = (
                    f"sandbox terminated before becoming healthy (poll={poll}); "
                    "the VM/container exited (OOM, init exit, or reaping) rather than egress being blocked"
                )
                return diagnostics

            diagnostics["sandbox_terminated"] = "false"
            log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            diagnostics["log"] = log_result.stdout
            health_result = self.execute(
                f"curl -s --max-time 3 http://localhost:{AGENT_SERVER_PORT}/health || echo 'no-health-response'",
                timeout_seconds=5,
            )
            diagnostics["health_response"] = health_result.stdout.strip()[:500]

            egress = self._probe_session_init_egress()
            diagnostics["egress_probe"] = egress
            blocked = [line for line in egress.splitlines() if "http_code=000" in line or line.endswith("FAILED")]
            if blocked:
                diagnostics["failure_reason"] = "egress blocked to required session-init host(s): " + "; ".join(blocked)
            else:
                diagnostics["failure_reason"] = (
                    "agent server alive but never reported hasSession=true; no egress block detected, "
                    "inspect agent-server log"
                )
        except Exception as e:
            diagnostics.setdefault("failure_reason", f"health check failed; diagnostics unavailable: {e}")
        return diagnostics

    def _probe_session_init_egress(self) -> str:
        hosts = list(SESSION_INIT_PROBE_HOSTS)
        gateway_host = _hostname_from_url(getattr(settings, "SANDBOX_LLM_GATEWAY_URL", None))
        if gateway_host and gateway_host not in hosts:
            hosts.insert(0, gateway_host)
        checks = "; ".join(
            f"printf '%s ' {shlex.quote(host)}; "
            f"curl -sS --max-time 3 -o /dev/null -w 'http_code=%{{http_code}}\\n' https://{host}/ 2>/dev/null || echo FAILED"
            for host in hosts
        )
        return self.execute(checks, timeout_seconds=30).stdout.strip()

    def start_agent_server(
        self,
        repository: str | None,
        task_id: str,
        run_id: str,
        mode: str = "background",
        create_pr: bool = True,
        auto_publish: bool = False,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        wait_for_health: bool = True,
    ) -> None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL and token should be obtained via get_connect_credentials()
        before calling this method. The agent-server runs on port 8080 which is
        exposed via Modal's connect token mechanism.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        if self._agent_server_is_healthy():
            logger.info(f"Agent-server already healthy in sandbox {self.id}; skipping relaunch")
            return
        self._free_agent_server_port()

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        self.write_file(BASH_ENV_SCRIPT, generate_bash_env_script().encode())

        if allowed_domains is not None:
            self._setup_agentsh(WORKING_DIR, allowed_domains)

        mcp_servers_arg = ""
        if mcp_configs:
            mcp_json = json.dumps([c.to_dict() for c in mcp_configs])
            mcp_servers_arg = f" --mcpServers {shlex.quote(mcp_json)}"

        if auto_publish and not self.agent_server_supports_auto_publish():
            logger.warning(f"Installed agent-server in sandbox {self.id} predates --autoPublish; starting review-first")
            auto_publish = False

        command = self._build_agent_server_command(
            repo_path,
            task_id,
            run_id,
            mode,
            create_pr,
            auto_publish,
            interaction_origin,
            branch,
            runtime_adapter,
            provider,
            model,
            reasoning_effort,
            mcp_servers_arg,
            allowed_domains=allowed_domains,
            event_ingest_token=event_ingest_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
            repo_ready_file=repo_ready_file,
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository or 'no-repo'}")
        launch_result = self.execute(command, timeout_seconds=30)
        if launch_result.exit_code != 0:
            logger.warning(f"Agent-server process failed to launch in sandbox {self.id}: {launch_result.stderr}")
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "stderr": launch_result.stderr, "exit_code": str(launch_result.exit_code)},
                cause=RuntimeError(launch_result.stderr or "launch command returned non-zero exit"),
            )

        if wait_for_health:
            self.wait_for_agent_server_ready(allowed_domains)

    def wait_for_agent_server_ready(self, allowed_domains: list[str] | None = None) -> None:
        if self._wait_for_health_check():
            logger.info(f"Agent-server ready in sandbox {self.id}")
            return
        diagnostics = self._diagnose_startup_failure(allowed_domains)
        raise SandboxExecutionError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, **diagnostics},
            cause=RuntimeError(diagnostics.get("failure_reason", "Health check failed after retries")),
        )

    def mark_repo_ready(self, repo_ready_file: str) -> None:
        self.execute(f"touch {shlex.quote(repo_ready_file)}", timeout_seconds=10)

    def _setup_agentsh(self, workspace_path: str, allowed_domains: list[str] | None = None) -> None:
        if allowed_domains is not None:
            logger.info("Configuring agentsh in sandbox %s for %d allowed domain(s)", self.id, len(allowed_domains))
        else:
            logger.info("Configuring agentsh in sandbox %s (allow-all mode)", self.id)

        config_yaml = generate_config_yaml(enable_ptrace=True, full_trace=True)
        policy_yaml = generate_policy_yaml(allowed_domains)

        self.execute("pkill -f 'agentsh server' || true", timeout_seconds=5)
        self.execute("mkdir -p /etc/agentsh/policies /var/log/agentsh /var/lib/agentsh/sessions", timeout_seconds=5)
        self.write_file("/etc/agentsh/config.yaml", config_yaml.encode())
        self.write_file("/etc/agentsh/policies/default.yaml", policy_yaml.encode())
        self.write_file(ENV_WRAPPER_SCRIPT, generate_env_wrapper().encode())
        self.execute(f"chmod +x {ENV_WRAPPER_SCRIPT}", timeout_seconds=5)

        setup_script = build_setup_script(workspace_path)
        result = self.execute(setup_script, timeout_seconds=30)
        if not self._agentsh_daemon_is_healthy():
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            logger.error(
                "agentsh daemon failed to start in sandbox %s (setup exit_code=%s); stderr=%r agentsh_log=%r",
                self.id,
                result.exit_code,
                result.stderr.strip()[:1000],
                agentsh_log.stdout.strip()[:2000],
            )
            raise SandboxExecutionError(
                "Failed to start agentsh daemon",
                {
                    "sandbox_id": self.id,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "exit_code": result.exit_code,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError(result.stderr or "agentsh daemon health check failed"),
            )

        session_check = self.execute(f"cat {SESSION_ID_FILE}", timeout_seconds=5)
        if session_check.exit_code != 0 or not session_check.stdout.strip():
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            logger.error(
                "agentsh session creation failed in sandbox %s; stderr=%r agentsh_log=%r",
                self.id,
                session_check.stderr.strip()[:1000],
                agentsh_log.stdout.strip()[:2000],
            )
            raise SandboxExecutionError(
                "Failed to create agentsh session",
                {
                    "sandbox_id": self.id,
                    "stderr": session_check.stderr,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError("agentsh session create failed"),
            )

        logger.info("agentsh daemon started and session created in sandbox %s", self.id)

    def _agentsh_daemon_is_healthy(self, max_attempts: int = 30, poll_interval: float = 0.5) -> bool:
        health_script = (
            f"for i in $(seq 1 {max_attempts}); do "
            f"  status=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{AGENTSH_DAEMON_PORT}/health); "
            f'  [ "$status" = "200" ] && exit 0; '
            f'  [ "$i" -lt {max_attempts} ] && sleep {poll_interval}; '
            f"done; "
            f"exit 1"
        )
        result = self.execute(health_script, timeout_seconds=max(30, int(max_attempts * poll_interval) + 5))
        return result.exit_code == 0

    def _wait_for_health_check(
        self, max_attempts: int = AGENT_SERVER_HEALTH_MAX_ATTEMPTS, poll_interval: float = 0.5
    ) -> bool:
        """Poll health endpoint until server is ready (single remote call)."""
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval)

    def _agent_server_is_healthy(self) -> bool:
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts=1, poll_interval=0.0)

    def read_agent_server_session_init_ms(self) -> int | None:
        return self._read_health_session_init_ms(AGENT_SERVER_PORT)

    def _free_agent_server_port(self) -> None:
        self.execute(
            "pkill -TERM -f agent-server 2>/dev/null || true; "
            "for _ in $(seq 1 10); do pgrep -f agent-server >/dev/null || break; sleep 0.5; done; "
            "pkill -KILL -f agent-server 2>/dev/null || true",
            timeout_seconds=15,
        )

    def create_snapshot(self) -> str:
        if not self.is_running():
            raise SandboxNotRunningError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            # Modal can report the sandbox as running before filesystem snapshotting is ready.
            self._sandbox.exec("true", timeout=30).wait()
            # ttl=None keeps indefinite retention; modal 1.5.0 otherwise defaults snapshots to a 30-day TTL.
            image = self._sandbox.snapshot_filesystem(ttl=None)

            snapshot_id = image.object_id

            logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except TRANSIENT_SNAPSHOT_ERRORS as e:
            # Transient Modal infra timeout — Temporal retries the activity, so log at warning and
            # skip error-tracking capture to avoid a fresh issue for every recoverable deadline.
            logger.warning(f"Transient error creating snapshot for sandbox {self.id}, will retry: {e}")
            raise SnapshotTimeoutError(
                f"Transient error creating snapshot: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
                capture=False,
            )

        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

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
            logger.info(f"Destroyed sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
