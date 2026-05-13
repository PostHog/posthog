"""Celery tasks for founder_mode.

Currently only validation runs async — the LLM round-trip is ~20-60s so we don't want it
blocking the request thread. The task is the single writer to FounderProject.validation
during its lifetime; callers must not mutate that column while a run is in progress.

Architectural note: skipping the facade for now since no other product consumes founder_mode.
Tasks call logic/ directly. Reintroduce a facade once a cross-product consumer appears.
"""

import json
import hashlib
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import shared_task

from posthog.models.user import User

from products.founder_mode.backend.logic.validation.service import run_validation
from products.founder_mode.backend.models import FounderProject

logger = structlog.get_logger(__name__)


def _ideation_hash(ideation: dict[str, Any]) -> str:
    """Stable hash of an ideation payload for staleness detection.

    Sorted JSON keys so semantically-identical payloads always produce the same hash.
    The frontend uses this to tell whether a saved report still matches the current ideation.
    """
    canonical = json.dumps(ideation, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@shared_task(ignore_result=True)
def run_validation_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Run the validation flow for a FounderProject and write the result back to its `validation` JSON.

    The task is fail-tolerant: any exception from the service is captured into the column
    so the frontend can render a failed state instead of polling forever.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping validation, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to run validation as", project_id=founder_project_id)
        return

    ideation_hash = _ideation_hash(project.ideation)
    started_at = _now_iso()

    project.validation = {
        "status": "running",
        "started_at": started_at,
        "ideation_hash": ideation_hash,
        "report": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])

    try:
        report, trace_id = run_validation(
            ideation_payload=project.ideation,
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("Validation run failed", project_id=founder_project_id)
        project.validation = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "ideation_hash": ideation_hash,
            "report": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["validation", "updated_at"])
        return

    project.validation = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "ideation_hash": ideation_hash,
        "report": report.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])
