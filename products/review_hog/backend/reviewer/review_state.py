import json

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import load_turn_findings


def review_mode_for_run(report: ReviewReport, run_index: int) -> str:
    for finding, _ in load_turn_findings(team_id=report.team_id, report_id=str(report.id), run_index=run_index):
        if finding.validation_context:
            try:
                context = json.loads(finding.validation_context)
            except (TypeError, ValueError):
                continue
            if isinstance(context, dict):
                mode = context.get("review_mode")
                if isinstance(mode, str) and mode in (REVIEW_MODE_FULL, REVIEW_MODE_FLASH):
                    return mode
    return REVIEW_MODE_FULL


def published_heads_by_mode(report: ReviewReport) -> dict[str, str]:
    if report.published_heads_by_mode is not None:
        return dict(report.published_heads_by_mode)
    if not report.published_head_sha:
        return {}
    # Older reports stored the mode on findings, before publication had separate watermarks.
    run_index = max((int(index) for index in (report.published_head_shas or {})), default=report.run_count)
    return {review_mode_for_run(report, run_index): report.published_head_sha}


def review_already_published(report: ReviewReport, head_sha: str, review_mode: str) -> bool:
    return bool(head_sha) and published_heads_by_mode(report).get(review_mode) == head_sha
