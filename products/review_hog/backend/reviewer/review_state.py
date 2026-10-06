import json
from typing import Any

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.constants import (
    REVIEW_DESIGN_PIPELINE,
    REVIEW_DESIGN_SINGLE_AGENT,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
)
from products.review_hog.backend.reviewer.persistence import load_turn_findings


def _finding_context(finding: ReviewIssueFinding) -> dict[str, Any] | None:
    if not finding.validation_context:
        return None
    try:
        context = json.loads(finding.validation_context)
    except (TypeError, ValueError):
        return None
    return context if isinstance(context, dict) else None


def review_design_for_finding(finding: ReviewIssueFinding) -> str:
    """The design that produced the finding. Findings from before the single-agent design ran the pipeline."""
    context = _finding_context(finding)
    design = context.get("review_design") if context is not None else None
    return REVIEW_DESIGN_SINGLE_AGENT if design == REVIEW_DESIGN_SINGLE_AGENT else REVIEW_DESIGN_PIPELINE


def review_mode_for_run(report: ReviewReport, run_index: int) -> str:
    for finding, _ in load_turn_findings(team_id=report.team_id, report_id=str(report.id), run_index=run_index):
        context = _finding_context(finding)
        if context is not None:
            mode = context.get("review_mode")
            if isinstance(mode, str) and mode in (REVIEW_MODE_FULL, REVIEW_MODE_FLASH):
                return mode
    return REVIEW_MODE_FULL


def review_design_for_run(report: ReviewReport, run_index: int) -> str:
    """The design of a completed turn, read from its findings like `review_mode_for_run`."""
    for finding, _ in load_turn_findings(team_id=report.team_id, report_id=str(report.id), run_index=run_index):
        if _finding_context(finding) is not None:
            return review_design_for_finding(finding)
    return REVIEW_DESIGN_PIPELINE


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
