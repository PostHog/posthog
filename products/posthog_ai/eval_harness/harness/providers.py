from __future__ import annotations

import os
import shutil
import logging
import subprocess
from abc import ABC, abstractmethod
from contextlib import ExitStack
from pathlib import Path
from typing import Any, ClassVar, Literal

from .ports import DJANGO_LIVE_PORT, LLM_GATEWAY_PORT, MCP_PORT
from .tunnels import NgrokTunnels, resolve_authtoken

logger = logging.getLogger(__name__)

SandboxProvider = Literal["docker", "modal"]

SANDBOX_PROVIDER_SETTING: dict[SandboxProvider, str] = {
    "docker": "docker",
    "modal": "MODAL_EVALS",
}
"""Value each provider writes to ``settings.SANDBOX_PROVIDER``, which selects the
sandbox class in ``products.tasks``. ``modal`` maps to ``MODAL_EVALS``: a
``ModalSandbox`` subclass pinned to the ``posthog-sandbox-evals`` Modal app.

``__main__`` sets this in the environment before ``django.setup()``. It must be
correct before the *first* ``Sandbox`` access, because ``products.tasks`` resolves
that class once and caches it in module globals; a later ``override_settings`` can
no longer change it. ``.env`` ships ``SANDBOX_PROVIDER=docker``, so without the
early set a modal run would cache ``DockerSandbox`` and silently execute locally."""

EVAL_CONTAINER_PREFIX = "task-sandbox-"
"""Container name prefix the sandbox harness stamps on every eval container
(see ``SandboxConfig.name`` / ``get_sandbox_name_for_task``)."""

SETUP_GUIDE = "docs/internal/sandboxes-setup-guide.md"


class PreflightError(RuntimeError):
    """A provider prerequisite is missing. Raised before any infrastructure boots."""


def cleanup_case_containers(task_id: str) -> None:
    """Force-remove any sandbox container created for this case's task.

    Eval cases return as soon as ``poll_for_turn`` sees ``end_turn``, but the
    ``ProcessTaskWorkflow`` finally block that calls ``cleanup_sandbox`` runs
    asynchronously and can lag — or get cancelled when the temporal worker is
    shut down at session end. With 16GB-per-sandbox defaults and a handful of
    concurrent cases, accumulated containers exhaust host memory.

    Match by name prefix ``task-sandbox-{task_id}-`` (see ``get_sandbox_name_for_task``
    and ``DockerSandbox.create``) so we never touch a concurrently-running case's
    container.
    """
    name_prefix = f"{EVAL_CONTAINER_PREFIX}{task_id}-"
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={name_prefix}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        logger.warning("Failed to list sandbox containers for task %s", task_id, exc_info=True)
        return

    for container_id in result.stdout.strip().splitlines():
        if not container_id:
            continue
        logger.info("Cleaning up eval container %s for task %s", container_id, task_id)
        try:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, timeout=30)
        except Exception:
            logger.warning("Failed to remove sandbox container %s", container_id, exc_info=True)


def _modal_eval_app_name() -> str:
    """Name of the dedicated Modal app the eval sandboxes run under (the
    ``MODAL_EVALS`` provider), read from its source of truth in ``products.tasks``."""
    from products.tasks.backend.logic.services.sandbox import (  # noqa: PLC0415 — Django import, kept off the harness import path
        get_sandbox_class_for_backend,
    )

    app_name = getattr(get_sandbox_class_for_backend("MODAL_EVALS"), "DEFAULT_APP_NAME", "")
    return app_name if isinstance(app_name, str) else ""


def cleanup_modal_eval_sandboxes(app_name: str, task_ids: set[str]) -> None:
    """Terminate this run's leftover Modal sandboxes under the eval app.

    The Modal analog of the Docker container sweep: best effort, and also reached
    from an ``atexit`` hook. A case that finishes cleanly has its own workflow
    terminate its sandbox; this catches the ones a per-case timeout, a crash, or a
    Ctrl-C left running, so they don't idle (and bill) until their TTL.

    Scoped to this run's own tasks so two concurrent runs sharing the eval app
    don't reap each other. Each sandbox carries a ``task_id`` tag (see
    ``_build_sandbox_tags`` / ``ModalSandbox`` ``set_tags``), so we list per
    registered id and terminate only those. We filter on the tag rather than the
    ``task-sandbox-<id>-<hex>`` name because the installed Modal SDK does not
    expose a listed sandbox's name. Empty registry (nothing ran) sweeps nothing.
    """
    if not task_ids:
        return
    try:
        import modal  # noqa: PLC0415 — heavy, optional dep kept off the harness import path
    except Exception:
        return
    try:
        app = modal.App.lookup(app_name, create_if_missing=False)
    except Exception:
        # Nothing ever ran under this app, so there is nothing to sweep.
        return
    for task_id in task_ids:
        try:
            sandboxes = list(modal.Sandbox.list(app_id=app.app_id, tags={"task_id": task_id}))
        except Exception:
            logger.warning("Could not list Modal sandboxes for task %s during cleanup", task_id)
            continue
        for sandbox in sandboxes:
            try:
                logger.info("Terminating leftover Modal sandbox %s for task %s", sandbox.object_id, task_id)
                sandbox.terminate()
            except Exception:
                pass


class SandboxProviderStrategy(ABC):
    """Per-provider bootstrap, settings, and teardown for a harness run."""

    name: ClassVar[SandboxProvider]

    default_max_sandboxes: ClassVar[int | None]
    """``None`` means unbounded — every case may hold a sandbox at once."""

    def __init__(self) -> None:
        self._task_ids: set[str] = set()
        """Task ids whose sandboxes this run created. The end-of-run sweep filters
        on these so it only reaps this run's own sandboxes — never a dev-stack task
        sandbox or a concurrent run sharing the same provider."""

    def register_task(self, task_id: str) -> None:
        """Record a task whose sandbox this run created, so ``cleanup()`` can scope
        its sweep to this run. The runner calls it once per case, right after the
        task's workflow is triggered."""
        self._task_ids.add(task_id)

    @abstractmethod
    def preflight(self) -> None:
        """Fail fast when a prerequisite is missing, before anything is started."""

    def start(self, stack: ExitStack) -> None:  # noqa: B027 — optional hook; docker brings up nothing of its own
        """Bring up provider-owned infrastructure, registering teardown on ``stack``."""

    @abstractmethod
    def settings_overrides(self) -> dict[str, Any]:
        """Django settings the sandbox and its temporal activities read."""

    def sandbox_timeout_seconds(self, per_case_timeout_seconds: int) -> int | None:
        """Per-sandbox max lifetime, or ``None`` to keep ``SANDBOX_TTL_SECONDS``."""
        return None

    def cleanup_case(self, task_id: str) -> None:  # noqa: B027 — optional hook; only providers whose per-case teardown can lag override it
        """Per-case teardown run after each case settles, on top of the workflow's own cleanup."""

    def cleanup(self) -> None:  # noqa: B027 — optional hook; providers that own teardown override it
        """End-of-run sweep for anything per-case teardown may have missed."""


class DockerProviderStrategy(SandboxProviderStrategy):
    """Local Docker sandboxes. Each container defaults to 16 GB, so host RAM,
    not the sandbox API, is what bounds concurrency."""

    name: ClassVar[SandboxProvider] = "docker"
    default_max_sandboxes: ClassVar[int | None] = 4

    def __init__(self, *, keep_containers: bool = False, rebuild_image: bool = False) -> None:
        super().__init__()
        self.keep_containers = keep_containers
        self.rebuild_image = rebuild_image

    def preflight(self) -> None:
        if shutil.which("docker") is None:
            raise PreflightError("`docker` not found on PATH. The docker provider needs a local Docker daemon.")
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
        except Exception as e:
            raise PreflightError(f"Could not reach the Docker daemon: {e}") from e
        if result.returncode != 0:
            raise PreflightError("The Docker daemon is not reachable. Start Docker and retry.")

    def start(self, stack: ExitStack) -> None:
        # Verify posthog-sandbox-base is fresh (rebuilding when @posthog/agent published a
        # newer version or the Dockerfile changed) before any case grabs a sandbox, so a
        # stale image can't break the whole run. Imported here because it pulls in Django.
        from products.tasks.backend.logic.services.docker_sandbox import (  # noqa: PLC0415 — Django import, kept off the harness import path
            ensure_fresh_base_image,
        )

        ensure_fresh_base_image(force=self.rebuild_image)

    def settings_overrides(self) -> dict[str, Any]:
        # Docker containers reach the host via host.docker.internal.
        return {
            "SANDBOX_PROVIDER": SANDBOX_PROVIDER_SETTING[self.name],
            "SANDBOX_API_URL": f"http://host.docker.internal:{DJANGO_LIVE_PORT}",
            "SANDBOX_LLM_GATEWAY_URL": f"http://host.docker.internal:{LLM_GATEWAY_PORT}",
            "SANDBOX_MCP_URL": f"http://host.docker.internal:{MCP_PORT}/mcp",
        }

    def cleanup_case(self, task_id: str) -> None:
        # Belt-and-braces on top of the workflow's own shutdown: its cleanup_sandbox
        # can lag or be cancelled at worker shutdown, so reclaim this case's container
        # by name before the next case grabs a slot. --keep-sandbox-containers skips
        # this too — the flag exists to inspect a failed case's container, and the
        # per-case reclaim would otherwise remove it before anyone could look.
        if self.keep_containers:
            return
        cleanup_case_containers(task_id)

    def cleanup(self) -> None:
        if self.keep_containers:
            logger.info("--keep-sandbox-containers set, skipping container cleanup")
            return
        # Scope the sweep to this run's own tasks so we never reap a dev-stack task
        # sandbox that happens to share the `task-sandbox-` prefix. Empty registry
        # (nothing ran) sweeps nothing.
        for task_id in self._task_ids:
            cleanup_case_containers(task_id)


class ModalProviderStrategy(SandboxProviderStrategy):
    """Remote Modal sandboxes, reached from Modal's network through ngrok tunnels.

    Runs under the ``MODAL_EVALS`` provider — the same ``ModalSandbox`` class
    against the ``posthog-sandbox-evals`` app, so DEBUG-mode eval image builds
    don't share an image cache with production or local development sandboxes.
    """

    name: ClassVar[SandboxProvider] = "modal"
    default_max_sandboxes: ClassVar[int | None] = None

    def __init__(self) -> None:
        super().__init__()
        self._tunnels: NgrokTunnels | None = None
        self._sandbox_app_name: str | None = None

    def preflight(self) -> None:
        if shutil.which("ngrok") is None:
            raise PreflightError(
                "`ngrok` not found on PATH. Modal sandboxes run outside this host, so the "
                f"Django API, LLM gateway, and MCP server must be publicly reachable. See {SETUP_GUIDE}."
            )
        if resolve_authtoken() is None:
            # Three simultaneous tunnels need a paid, authenticated agent. Without a
            # token ngrok starts and then fails per-tunnel, which would otherwise
            # surface only as a 60s startup timeout.
            raise PreflightError(
                "No ngrok authtoken found. Set NGROK_AUTHTOKEN, or run `ngrok config add-authtoken <token>` "
                f"with a token from https://dashboard.ngrok.com/get-started/your-authtoken. See {SETUP_GUIDE}."
            )
        has_env_tokens = bool(os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"))
        if not has_env_tokens and not (Path.home() / ".modal.toml").exists():
            raise PreflightError(
                "No Modal credentials found. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET, "
                f"or run `modal token new`. See {SETUP_GUIDE}."
            )
        # SANDBOX_JWT_PRIVATE_KEY and the other env-only prerequisites are validated
        # earlier by env_preflight.validate_eval_env(); only checks with non-env
        # fallbacks (ngrok config file, ~/.modal.toml) live here.

    def start(self, stack: ExitStack) -> None:
        # Resolve the eval sandbox app now, while Django is configured, so cleanup()
        # can sweep leftover sandboxes later — including from the atexit path, where
        # importing products.tasks is unsafe. A failure here must not fail the run.
        try:
            self._sandbox_app_name = _modal_eval_app_name()
        except Exception:
            logger.warning("Could not resolve the Modal eval app; end-of-run sandbox sweep is disabled")

        tunnels = NgrokTunnels(
            {
                "django": DJANGO_LIVE_PORT,
                "gateway": LLM_GATEWAY_PORT,
                "mcp": MCP_PORT,
            }
        )
        tunnels.start()
        stack.callback(tunnels.stop)
        self._tunnels = tunnels

    def settings_overrides(self) -> dict[str, Any]:
        if self._tunnels is None:
            raise RuntimeError("ModalProviderStrategy.start() must run before settings_overrides()")
        return {
            "SANDBOX_PROVIDER": SANDBOX_PROVIDER_SETTING[self.name],
            "SANDBOX_API_URL": self._tunnels.url_for("django"),
            "SANDBOX_LLM_GATEWAY_URL": self._tunnels.url_for("gateway"),
            "SANDBOX_MCP_URL": f"{self._tunnels.url_for('mcp')}/mcp",
        }

    def sandbox_timeout_seconds(self, per_case_timeout_seconds: int) -> int | None:
        # Under TEST=1, SANDBOX_TTL_SECONDS equals the per-case timeout, so Modal
        # would reap a slow case's sandbox exactly as it was about to finish.
        return per_case_timeout_seconds + 10 * 60

    def cleanup_case(self, task_id: str) -> None:
        if self._sandbox_app_name:
            cleanup_modal_eval_sandboxes(self._sandbox_app_name, {task_id})

    def cleanup(self) -> None:
        # A finished case terminates its own sandbox; sweep the app for any that a
        # timeout, crash, or Ctrl-C left running so they don't idle until their TTL.
        # Scoped to this run's own tasks so a concurrent run sharing the eval app
        # keeps its sandboxes.
        if self._sandbox_app_name:
            cleanup_modal_eval_sandboxes(self._sandbox_app_name, self._task_ids)


def build_provider(
    provider: SandboxProvider, *, keep_containers: bool, rebuild_image: bool = False
) -> SandboxProviderStrategy:
    if provider == "docker":
        return DockerProviderStrategy(keep_containers=keep_containers, rebuild_image=rebuild_image)
    return ModalProviderStrategy()
