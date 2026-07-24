"""Bakes the prebaked PostHog dev-stack VM image.

Boots a plain VM-base sandbox, runs `bake-posthog-dev-stack.sh` inside it (pre-pull the
dev compose images, bring the stack up, run the Django/persons/ClickHouse migrations,
shut everything down cleanly), then publishes the sandbox's filesystem snapshot as a
named Modal image.

Orgs are routed onto the published image through the `tasks-modal-vm-sandbox` flag
payload: a payload variant with `"default_custom_image": "posthog-dev-stack"` makes it
the default base for that org's VM runs (see `vm_sandbox_default_custom_image` in
`products/tasks/backend/constants.py`). `hogli start` on those runs then skips the
multi-gigabyte docker pulls and only applies migrations that landed after the bake.

The bake must run on the real VM runtime — dockerd cannot run inside Modal's gVisor
image builder — which is why this is a sandbox snapshot rather than a spec-built image.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from django.conf import settings

from products.tasks.backend.feature_flags import is_dev_stack_image_bake_enabled
from products.tasks.backend.logic.services.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class
from products.tasks.backend.redis import get_tasks_cache

logger = logging.getLogger(__name__)

DEV_STACK_IMAGE_NAME = "posthog-dev-stack"

BAKE_SCRIPT_LOCAL_PATH = Path("products/tasks/backend/sandbox/images/bake-posthog-dev-stack.sh")
BAKE_SCRIPT_SANDBOX_PATH = "/tmp/bake-posthog-dev-stack.sh"

# Cold bake budget: multi-GB image pulls plus the full migration history from scratch.
BAKE_EXECUTION_TIMEOUT_SECONDS = 90 * 60
BAKE_SANDBOX_TTL_SECONDS = 3 * 60 * 60
BAKE_SANDBOX_CPU_CORES = 8.0
BAKE_SANDBOX_MEMORY_GB = 32.0

# Tail of bake output retained for error reporting.
MAX_BAKE_LOG_CHARS = 20_000

# VM base image reference the last successful bake layered on, so the refresh sweep can
# tell whether the published image is stale (mirrors SandboxCustomImage.base_image_reference).
BAKED_BASE_REFERENCE_CACHE_KEY = "tasks:dev-stack-image:baked-base-reference:{publish_name}"
BAKED_BASE_REFERENCE_TTL_SECONDS = 30 * 24 * 60 * 60
# Per-digest dispatch claim: a refresh is attempted at most once per new base reference
# (mirrors SandboxCustomImage.base_image_refresh_reference); a failed attempt is retried
# by the nightly bake, never by the next sweep tick.
REFRESH_CLAIM_CACHE_KEY = "tasks:dev-stack-image:refresh-claim:{publish_name}:{base_reference}"
REFRESH_CLAIM_TTL_SECONDS = 7 * 24 * 60 * 60


class DevStackImageBakeError(Exception):
    pass


def _record_baked_base_reference(publish_name: str) -> None:
    """Best-effort stamp of the base digest a successful bake used; losing it only costs
    one redundant rebake on the next sweep."""
    from products.tasks.backend.logic.services.modal_sandbox import (  # noqa: PLC0415 — keeps the Modal SDK off the import path
        resolve_template_base_image_reference,
    )

    try:
        base_reference = resolve_template_base_image_reference(SandboxTemplate.VM_BASE)
        if base_reference is None:
            return
        get_tasks_cache().set(
            BAKED_BASE_REFERENCE_CACHE_KEY.format(publish_name=publish_name),
            base_reference,
            timeout=BAKED_BASE_REFERENCE_TTL_SECONDS,
        )
    except Exception:
        logger.exception("dev_stack_image_baked_reference_record_failed", extra={"publish_name": publish_name})


def refresh_dev_stack_image_if_base_changed(publish_name: str = DEV_STACK_IMAGE_NAME) -> bool:
    """Rebake when the VM base image digest has moved since the last successful bake.

    The nightly bake keeps the heavy state (migrations, docker pulls) fresh; this is the
    fast lane mirroring the custom-image refresh fanout, so a new VM base publish (e.g. an
    agent-server release) reaches the prebaked image within a sweep tick instead of
    overnight. Also converges a region with no recorded bake (first enable, cache flush)
    by dispatching one. Returns whether a bake was dispatched.
    """
    if not is_dev_stack_image_bake_enabled():
        return False

    from products.tasks.backend.logic.services.modal_sandbox import (  # noqa: PLC0415 — keeps the Modal SDK off the import path
        resolve_template_base_image_reference,
    )

    base_reference = resolve_template_base_image_reference(SandboxTemplate.VM_BASE)
    if base_reference is None:
        return False

    cache = get_tasks_cache()
    baked_reference = cache.get(BAKED_BASE_REFERENCE_CACHE_KEY.format(publish_name=publish_name))
    if baked_reference == base_reference:
        return False

    claim_key = REFRESH_CLAIM_CACHE_KEY.format(publish_name=publish_name, base_reference=base_reference)
    if not cache.add(claim_key, True, timeout=REFRESH_CLAIM_TTL_SECONDS):
        return False

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — breaks the temporal.client -> dev_stack_image import cycle
        execute_bake_dev_stack_image_workflow,
    )

    logger.info(
        "dev_stack_image_refresh_dispatched",
        extra={"publish_name": publish_name, "base_reference": base_reference, "baked_reference": baked_reference},
    )
    execute_bake_dev_stack_image_workflow(publish_name)
    return True


def bake_dev_stack_image(publish_name: str = DEV_STACK_IMAGE_NAME) -> str:
    """Run the bake in a fresh VM sandbox and publish the result; returns the image object id."""
    from products.tasks.backend.logic.services.modal_sandbox import (  # noqa: PLC0415 — keeps the Modal SDK off the import path
        ModalSandbox,
    )

    sandbox_cls = get_sandbox_class()
    if not issubclass(sandbox_cls, ModalSandbox):
        raise DevStackImageBakeError("Dev-stack image bakes require the Modal sandbox provider")

    script = (Path(settings.BASE_DIR) / BAKE_SCRIPT_LOCAL_PATH).read_text()

    sandbox = sandbox_cls.create(
        SandboxConfig(
            name="dev-stack-image-bake",
            template=SandboxTemplate.VM_BASE,
            vm_runtime=True,
            cpu_cores=BAKE_SANDBOX_CPU_CORES,
            memory_gb=BAKE_SANDBOX_MEMORY_GB,
            ttl_seconds=BAKE_SANDBOX_TTL_SECONDS,
            default_execution_timeout_seconds=BAKE_EXECUTION_TIMEOUT_SECONDS,
            metadata={"purpose": "dev_stack_image_bake"},
        )
    )
    try:
        sandbox.write_file(BAKE_SCRIPT_SANDBOX_PATH, script.encode())

        log_tail: deque[str] = deque()
        tail_len = 0
        stream = sandbox.execute_stream(f"bash {BAKE_SCRIPT_SANDBOX_PATH} 2>&1")
        for line in stream.iter_stdout():
            logger.info("dev_stack_image_bake_output", extra={"sandbox_id": sandbox.id, "line": line.rstrip()})
            log_tail.append(line)
            tail_len += len(line)
            while tail_len > MAX_BAKE_LOG_CHARS and len(log_tail) > 1:
                tail_len -= len(log_tail.popleft())
        result = stream.wait()
        if result.exit_code != 0:
            raise DevStackImageBakeError(
                f"Bake script exited with {result.exit_code}; output tail:\n{''.join(log_tail)[-MAX_BAKE_LOG_CHARS:]}"
            )

        image_id = sandbox.publish_filesystem_image(publish_name)
        _record_baked_base_reference(publish_name)
        logger.info(
            "dev_stack_image_published",
            extra={"publish_name": publish_name, "image_id": image_id, "sandbox_id": sandbox.id},
        )
        return image_id
    finally:
        try:
            sandbox.destroy()
        except Exception:
            logger.exception("dev_stack_image_bake_sandbox_cleanup_failed", extra={"sandbox_id": sandbox.id})
