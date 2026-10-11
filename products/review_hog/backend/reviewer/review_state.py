import json
from collections.abc import Iterable

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import load_turn_findings


def _findings_review_mode(pairs: Iterable[tuple[ReviewIssueFinding, ValidationVerdict | None]]) -> str | None:
    for finding, _ in pairs:
        if finding.validation_context:
            try:
                context = json.loads(finding.validation_context)
            except (TypeError, ValueError):
                continue
            if isinstance(context, dict):
                mode = context.get("review_mode")
                if isinstance(mode, str) and mode in (REVIEW_MODE_FULL, REVIEW_MODE_FLASH):
                    return mode
    return None


def turn_review_mode(pairs: Iterable[tuple[ReviewIssueFinding, ValidationVerdict | None]]) -> str:
    """The mode a turn ran in, read from its findings. A turn without findings reads as a Deep (full) turn."""
    return _findings_review_mode(pairs) or REVIEW_MODE_FULL


def review_mode_for_run(report: ReviewReport, run_index: int) -> str:
    return turn_review_mode(load_turn_findings(team_id=report.team_id, report_id=str(report.id), run_index=run_index))


def published_heads_by_mode(report: ReviewReport) -> dict[str, str]:
    if report.published_heads_by_mode is not None:
        return dict(report.published_heads_by_mode)
    if not report.published_head_sha:
        return {}
    # Older reports stored the mode on findings, before publication had separate watermarks.
    run_index = max((int(index) for index in (report.published_head_shas or {})), default=report.run_count)
    return {review_mode_for_run(report, run_index): report.published_head_sha}


def completed_turn_review_mode(
    report: ReviewReport, pairs: Iterable[tuple[ReviewIssueFinding, ValidationVerdict | None]]
) -> str:
    """The mode of a report's completed turn. A turn without findings falls back to the publish watermarks."""
    mode = _findings_review_mode(pairs)
    if mode is not None:
        return mode
    head = report.completed_head_sha or report.head_sha
    # Legacy rows kept the mode on findings only, and the findings already said nothing.
    heads = report.published_heads_by_mode or {}
    if head and heads.get(REVIEW_MODE_FLASH) == head and heads.get(REVIEW_MODE_FULL) != head:
        return REVIEW_MODE_FLASH
    return REVIEW_MODE_FULL


def review_already_published(report: ReviewReport, head_sha: str, review_mode: str) -> bool:
    return bool(head_sha) and published_heads_by_mode(report).get(review_mode) == head_sha
