from __future__ import annotations

from django.db.models import OuterRef, Subquery
from django.utils import timezone

import structlog
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import ImplementationHandover, ImplementationReplacement
from products.signals.backend.models import SignalReportArtefact

logger = structlog.get_logger(__name__)
REPLACEMENT_SWEEP_BATCH_SIZE = 500


class ReplacementRecovery:
    def enqueue_page(self, after_id: str | None = None, through_id: str | None = None) -> None:
        from products.signals.backend.tasks import (
            reconcile_implementation_replacement,
            sweep_implementation_replacements,
        )

        replacements = SignalReportArtefact.objects.filter(type="implementation_replacement", task_id__isnull=False)
        if through_id is None:
            last_id = replacements.order_by("-id").values_list("id", flat=True).first()
            if last_id is None:
                return
            through_id = str(last_id)
        replacements = replacements.filter(id__lte=through_id)
        if after_id is not None:
            replacements = replacements.filter(id__gt=after_id)
        # Auto-start creates a new task for each replacement, so its latest handover belongs to this attempt.
        handover = SignalReportArtefact.objects.filter(
            team_id=OuterRef("team_id"),
            report_id=OuterRef("report_id"),
            task_id=OuterRef("task_id"),
            type="implementation_handover",
        ).order_by("-created_at", "-id")
        page = list(
            replacements.annotate(handover_content=Subquery(handover.values("content")[:1]))
            .order_by("id")
            .values_list("id", "team_id", "content", "handover_content")[:REPLACEMENT_SWEEP_BATCH_SIZE]
        )
        enqueued = failed = 0
        for replacement_id, team_id, content, handover_content in page:
            try:
                ImplementationReplacement.model_validate_json(content)
                if handover_content is not None:
                    progress = ImplementationHandover.model_validate_json(handover_content)
                    if progress.replacement_id != replacement_id:
                        raise ValueError("Handover belongs to a different replacement")
                    if progress.status != "processing" or (
                        progress.lease_until is not None and progress.lease_until > timezone.now()
                    ):
                        continue
            except (ValidationError, ValueError):
                logger.exception("signals_replacement_recovery_invalid_record", replacement_id=str(replacement_id))
                continue
            try:
                reconcile_implementation_replacement.delay(team_id, str(replacement_id))
                enqueued += 1
            except Exception:
                failed += 1
                logger.exception("signals_replacement_recovery_dispatch_failed", replacement_id=str(replacement_id))
        logger.info("signals_replacement_recovery_page", scanned=len(page), enqueued=enqueued, failed=failed)
        if len(page) == REPLACEMENT_SWEEP_BATCH_SIZE and str(page[-1][0]) != through_id:
            sweep_implementation_replacements.delay(str(page[-1][0]), through_id)
