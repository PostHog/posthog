import logging

from django.db.models import Q

from products.tasks.backend.logic.services.modal_sandbox import resolve_template_base_image_reference
from products.tasks.backend.logic.services.sandbox import SandboxTemplate
from products.tasks.backend.models import SandboxCustomImage
from products.tasks.backend.temporal.client import execute_build_sandbox_image_workflow

logger = logging.getLogger(__name__)

CUSTOM_IMAGE_REFRESH_BATCH_SIZE = 10


def refresh_stale_sandbox_custom_images(batch_size: int = CUSTOM_IMAGE_REFRESH_BATCH_SIZE) -> int:
    base_image_reference = resolve_template_base_image_reference(SandboxTemplate.VM_BASE)
    if base_image_reference is None:
        return 0

    candidates = list(
        SandboxCustomImage.objects.unscoped()
        .filter(
            status=SandboxCustomImage.Status.READY,
        )
        .exclude(modal_image_name="")
        .exclude(spec={})
        .exclude(Q(base_image_reference=base_image_reference) | Q(base_image_refresh_reference=base_image_reference))
        .order_by("updated_at")
        .values_list("id", "team_id")[:batch_size]
    )

    dispatched = 0
    for image_id, team_id in candidates:
        claimed = (
            SandboxCustomImage.objects.unscoped()
            .filter(
                id=image_id,
                status=SandboxCustomImage.Status.READY,
            )
            .exclude(
                Q(base_image_reference=base_image_reference) | Q(base_image_refresh_reference=base_image_reference)
            )
            .update(
                status=SandboxCustomImage.Status.BUILDING,
                error="",
                build_log="",
                base_image_refresh_reference=base_image_reference,
            )
        )
        if not claimed:
            continue

        try:
            execute_build_sandbox_image_workflow(str(image_id), team_id, refresh=True)
        except Exception:
            (
                SandboxCustomImage.objects.unscoped()
                .filter(
                    id=image_id,
                    status=SandboxCustomImage.Status.BUILDING,
                )
                .update(status=SandboxCustomImage.Status.READY, base_image_refresh_reference=None)
            )
            logger.exception(
                "sandbox_custom_image_refresh_dispatch_failed",
                extra={"image_id": str(image_id), "team_id": team_id},
            )
            continue

        dispatched += 1

    logger.info(
        "sandbox_custom_image_refresh_fanout_completed",
        extra={"base_image_reference": base_image_reference, "dispatched": dispatched},
    )
    return dispatched
