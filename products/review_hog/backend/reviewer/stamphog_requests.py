from django.db.models import JSONField, QuerySet
from django.db.models.functions import Cast

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact


def _markers(report: ReviewReport) -> QuerySet[ReviewReportArtefact]:
    return ReviewReportArtefact.objects.for_team(report.team_id).filter(
        report_id=report.id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
    )


def stamphog_request_completed(report: ReviewReport, request_id: str) -> bool:
    """A retry resumes an unfinished turn, but cannot repeat a completed or published refusal review."""
    contents = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__stamphog_review_run_id=request_id)
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


def complete_stamphog_request(report: ReviewReport, run_index: int) -> None:
    marker = (
        _markers(report)
        .annotate(payload=Cast("content", JSONField()))
        .filter(payload__run_index=run_index)
        .order_by("-created_at", "-id")
        .first()
    )
    if marker is None:
        raise ValueError("The refusal review's turn marker is missing")
    content = TurnMarkerArtefact.model_validate_json(marker.content)
    completed = content.model_copy(update={"stamphog_review_completed": True})
    ReviewReportArtefact.objects.for_team(report.team_id).filter(id=marker.id).update(
        content=completed.model_dump_json()
    )
