from __future__ import annotations

from django.db.models import JSONField, QuerySet
from django.db.models.functions import Cast

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL

MAX_REFUSAL_REVIEWS_PER_PR = 2


def _markers(report: ReviewReport) -> QuerySet[ReviewReportArtefact]:
    return ReviewReportArtefact.objects.for_team(report.team_id).filter(
        report_id=report.id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
    )


def publication_turn(
    report: ReviewReport, run_index: int, head_sha: str, queue_turn_id: str | None = None
) -> ReviewReportArtefact | None:
    marker = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__run_index=run_index)
        .order_by("-created_at", "-id")
        .first()
    )
    if marker is None:
        return None
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    if content.head_sha != head_sha or (queue_turn_id is not None and content.queue_turn_id != queue_turn_id):
        return None
    return marker


def resume_stamphog_turn(report: ReviewReport, queue_turn_id: str) -> TurnMarkerArtefact | None:
    marker = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__queue_turn_id=queue_turn_id)
        .order_by("-created_at", "-id")
        .first()
    )
    if marker is None:
        return None
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    current = publication_turn(report, content.run_index, content.head_sha, queue_turn_id)
    return content if current is not None and current.id == marker.id else None


def refusal_review_skip_reason(
    report: ReviewReport, *, head_sha: str, requested_head_sha: str | None, queue_turn_id: str, pr_open: bool
) -> str | None:
    if not pr_open:
        return "closed"
    if requested_head_sha != head_sha:
        return "superseded"
    resumed = resume_stamphog_turn(report, queue_turn_id)
    if resumed is not None:
        return "completed" if resumed.publication_completed else None
    markers = [
        TurnMarkerArtefact.model_validate_json(content)
        for content in _markers(report).values_list("content", flat=True)
    ]
    fallback_turns = {marker.queue_turn_id for marker in markers if marker.stamphog_review_run_id is not None}
    for marker in markers:
        if marker.head_sha != head_sha:
            continue
        if marker.stamphog_review_run_id is not None:
            return "head_already_attempted"
        if marker.review_mode == REVIEW_MODE_FULL and marker.publishes and marker.publication_completed:
            return "head_already_reviewed"
    if len(fallback_turns) >= MAX_REFUSAL_REVIEWS_PER_PR:
        return "pr_budget_exhausted"
    return None


def finalize_stamphog_request(
    report: ReviewReport, queue_turn_id: str, run_index: int, head_sha: str, urgency_threshold: str
) -> None:
    marker = publication_turn(report, run_index, head_sha, queue_turn_id)
    if marker is None:
        raise ValueError("The refusal review's turn marker is missing")
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    marker.content = content.model_copy(update={"finalized_urgency_threshold": urgency_threshold}).model_dump_json()
    marker.save(update_fields=["content"])


def complete_review_turn(report: ReviewReport, run_index: int, head_sha: str, queue_turn_id: str | None = None) -> None:
    marker = publication_turn(report, run_index, head_sha, queue_turn_id)
    if marker is None:
        if queue_turn_id is not None:
            raise ValueError("The review's turn marker is missing")
        return
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    marker.content = content.model_copy(update={"publication_completed": True}).model_dump_json()
    marker.save(update_fields=["content"])
