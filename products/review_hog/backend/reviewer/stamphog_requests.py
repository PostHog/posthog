from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import JSONField, Q, QuerySet
from django.db.models.functions import Cast

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL

if TYPE_CHECKING:
    from products.review_hog.backend.temporal.types import CompleteJoinedStamphogRequestsInput


def _markers(report: ReviewReport) -> QuerySet[ReviewReportArtefact]:
    return ReviewReportArtefact.objects.for_team(report.team_id).filter(
        report_id=report.id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
    )


def stamphog_request_completed(report: ReviewReport, request_id: str) -> bool:
    """A retry resumes an unfinished turn, but cannot repeat a completed or published refusal review."""
    contents = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(
            Q(payload__stamphog_review_run_id=request_id)
            | Q(payload__joined_stamphog_review_run_ids__contains=[request_id])
        )
        .values_list("content", flat=True)
    )
    markers = (TurnMarkerArtefact.model_validate_json(content) for content in contents)
    return any(
        marker.stamphog_review_completed or str(marker.run_index) in (report.published_head_shas or {})
        for marker in markers
    )


def stamphog_request_for_turn(report: ReviewReport, run_index: int) -> str | None:
    content = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__run_index=run_index)
        .order_by("-created_at", "-id")
        .values_list("content", flat=True)
        .first()
    )
    return TurnMarkerArtefact.model_validate_json(content).stamphog_review_run_id if content is not None else None


def complete_stamphog_request(report: ReviewReport, run_index: int, *, required: bool = True) -> None:
    marker = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__run_index=run_index)
        .order_by("-created_at", "-id")
        .first()
    )
    if marker is None:
        if required:
            raise ValueError("The refusal review's turn marker is missing")
        return
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    completed = content.model_copy(update={"stamphog_review_completed": True})
    ReviewReportArtefact.objects.for_team(report.team_id).filter(id=marker.id).update(
        content=completed.model_dump_json()
    )


def complete_joined_stamphog_requests(input: CompleteJoinedStamphogRequestsInput) -> bool:
    report = ReviewReport.objects.for_team(input.team_id).get(id=input.report_id)
    marker = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__queue_turn_id=input.queue_turn_id, payload__head_sha=input.head_sha)
        .order_by("-created_at", "-id")
        .first()
    )
    if marker is None:
        return False
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    if content.review_mode != REVIEW_MODE_FULL or not content.publishes or not content.stamphog_review_completed:
        return False
    completed = content.model_copy(
        update={
            "joined_stamphog_review_run_ids": sorted(set(content.joined_stamphog_review_run_ids + input.request_ids))
        }
    )
    ReviewReportArtefact.objects.for_team(report.team_id).filter(id=marker.id).update(
        content=completed.model_dump_json()
    )
    return True
