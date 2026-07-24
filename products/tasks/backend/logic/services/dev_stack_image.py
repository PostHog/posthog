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
from pathlib import Path

from django.conf import settings

from products.tasks.backend.logic.services.sandbox import SandboxConfig, SandboxTemplate
from products.tasks.backend.metrics import observe_dev_stack_image_bake

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


class DevStackImageBakeError(Exception):
    pass


def bake_dev_stack_image(publish_name: str = DEV_STACK_IMAGE_NAME) -> str:
    """Run the bake in a fresh VM sandbox and publish the result; returns the image object id."""
    from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox  # noqa: PLC0415
    from products.tasks.backend.logic.services.sandbox import get_sandbox_class  # noqa: PLC0415

    sandbox_cls = get_sandbox_class()
    if not (isinstance(sandbox_cls, type) and issubclass(sandbox_cls, ModalSandbox)):
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

        log_tail: list[str] = []
        stream = sandbox.execute_stream(f"bash {BAKE_SCRIPT_SANDBOX_PATH} 2>&1")
        for line in stream.iter_stdout():
            logger.info("dev_stack_image_bake_output", extra={"sandbox_id": sandbox.id, "line": line.rstrip()})
            log_tail.append(line)
            while sum(len(chunk) for chunk in log_tail) > MAX_BAKE_LOG_CHARS and len(log_tail) > 1:
                log_tail.pop(0)
        result = stream.wait()
        if result.exit_code != 0:
            observe_dev_stack_image_bake("bake_failed")
            raise DevStackImageBakeError(
                f"Bake script exited with {result.exit_code}; output tail:\n{''.join(log_tail)[-MAX_BAKE_LOG_CHARS:]}"
            )

        image_id = sandbox.publish_filesystem_image(publish_name)
        observe_dev_stack_image_bake("succeeded")
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
