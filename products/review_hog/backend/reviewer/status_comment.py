"""The PR's live "review in progress" status comment.

One marker-tagged issue comment per report on the publish (cloud trigger) path: posted right after
the run's gates pass, edited in place as the pipeline persists progress artefacts, and rewritten
with the turn's outcome at the end — the full found-vs-published counts, or a failure notice. Always
edited, never re-posted: comment edits don't notify PR subscribers, while every new comment emails
everyone. Progress renders from the same derivation the reviews API uses (`reviewer.progress`), so
the PR comment and the UI can never disagree.

Every entry point here is best-effort by construction: a status comment must never fail, block, or
retry a review, so all exceptions are swallowed after logging.
"""

import logging
from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from posthog.models.integration import GitHubIntegration

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import effective_priority, published_priorities_for
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_findings_bundle, load_valid_findings
from products.review_hog.backend.reviewer.progress import (
    SnapshotStats,
    TurnStats,
    progress_payload,
    snapshot_stats,
    turn_stats,
)
from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    github_api_get_paginated,
    github_api_request,
)

logger = logging.getLogger(__name__)

# Refreshes are claimed atomically on this watermark, so the concurrent (perspective, chunk) fan-out
# collapses to at most one GitHub edit per interval instead of one per finished unit.
STATUS_EDIT_MIN_INTERVAL = timedelta(seconds=60)

# Mirrors the frontend's `progressLabel` step mapping — the PR comment and the UI must tell the same
# story. Fetching folds into step 1 there too.
_STAGE_LABELS = {
    "fetching": "Step 1/6 · Preparing the diff",
    "chunking": "Step 1/6 · Splitting into chunks",
    "selecting": "Step 2/6 · Picking perspectives",
    "reviewing": "Step 3/6 · Running review passes",
    "deduplicating": "Step 4/6 · Merging overlapping findings",
    "validating": "Step 5/6 · Validating findings",
    "finalizing": "Step 6/6 · Finalizing the review",
}

# The UI's urgency-threshold labels (`URGENCY_STOPS`), for the held-back explanation.
_THRESHOLD_LABELS = {
    IssuePriority.CONSIDER: "All issues",
    IssuePriority.SHOULD_FIX: "Should fix",
    IssuePriority.MUST_FIX: "Must fix",
}

_PRIORITY_LABELS = {
    IssuePriority.MUST_FIX: "must fix",
    IssuePriority.SHOULD_FIX: "should fix",
    IssuePriority.CONSIDER: "consider",
}


def status_marker(report_id: str) -> str:
    """The hidden marker identifying the report's status comment across turns and crashed runs."""
    return f"<!-- reviewhog:status:{report_id} -->"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def render_in_progress_body(report_id: str, progress: dict[str, Any] | None) -> str:
    """The running-state body: the current step (mirroring the UI), plus a one-line explainer."""
    label = _STAGE_LABELS.get(progress["review_stage"], "Review in progress") if progress else _STAGE_LABELS["fetching"]
    done = progress.get("done") if progress else None
    total = progress.get("total") if progress else None
    counter = f" · {done}/{total}" if done is not None and total else ""
    return "\n".join(
        [
            "### \U0001f994 ReviewHog is reviewing this pull request",
            "",
            f"**{label}{counter}**",
            "",
            "Specialist review perspectives read the changed code in parallel, a blind-spot sweep "
            "catches what they missed, and only validated findings are published back to this pull request.",
            "",
            "<sub>This comment updates as the review progresses.</sub>",
            "",
            status_marker(report_id),
        ]
    )


def render_final_body(
    report_id: str,
    *,
    counts: dict[IssuePriority, int],
    published_count: int,
    held_back_count: int,
    threshold: IssuePriority,
    review_url: str | None,
) -> str:
    """The completed-state body: the full found counts, and how many the threshold held back.

    The counts always show everything the run found, even when only a subset was published, so
    two inline comments on the PR never read as "the review only found two things".
    """
    found_total = sum(counts.values())
    found_line = "Found " + ", ".join(
        f"**{counts[priority]} {_PRIORITY_LABELS[priority]}**"
        for priority in (IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER)
    )
    lines = ["### \U0001f994 ReviewHog reviewed this pull request", ""]
    if found_total == 0:
        lines.append("Found no issues worth raising, so no review was posted.")
    else:
        lines.append(found_line + ".")
        lines.append("")
        if published_count > 0:
            published_line = f"Published {_plural(published_count, 'finding')}"
            if review_url:
                published_line += f" ([view the review]({review_url}))"
            lines.append(published_line + ".")
        if held_back_count > 0:
            lines.append(
                f"{_plural(held_back_count, 'finding')} stayed below the author's "
                f'"{_THRESHOLD_LABELS[threshold]}" urgency threshold in their ReviewHog settings, '
                "so they were not published."
            )
    lines.extend(["", status_marker(report_id)])
    return "\n".join(lines)


def render_failed_body(report_id: str) -> str:
    return "\n".join(
        [
            "### \U0001f994 ReviewHog couldn't finish this review",
            "",
            "The review run failed partway. It will run again on the next push to this pull request.",
            "",
            status_marker(report_id),
        ]
    )


def _auth(team_id: int, repository: str) -> tuple[str, str | None] | None:
    """The installation token + id for `repository`, or None when no installation reaches it.

    `first_for_team_repository` probes the GitHub API, so this costs a call per invocation — fine at
    the refresh cadence (`STATUS_EDIT_MIN_INTERVAL`), and every call is egress-gated regardless.
    """
    github = GitHubIntegration.first_for_team_repository(team_id, repository)
    if github is None:
        return None
    return github.get_access_token(), github.github_installation_id


def _find_marker_comment(
    owner: str, repo: str, pr_number: int, marker: str, *, token: str, installation_id: str | None
) -> int | None:
    """The id of the PR's comment carrying `marker`, or None — recovers the handle after a crash
    between posting the comment and saving its id."""
    for comment in github_api_get_paginated(
        f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
    ):
        if marker in (comment.get("body") or ""):
            return comment.get("id")
    return None


def _post_comment(
    owner: str, repo: str, pr_number: int, body: str, *, token: str, installation_id: str | None
) -> int | None:
    response = github_api_request(
        "POST",
        f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
        json={"body": body},
    )
    return response.json().get("id")


def _patch_comment(
    owner: str, repo: str, comment_id: int, body: str, *, token: str, installation_id: str | None
) -> None:
    github_api_request(
        "PATCH",
        f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}",
        json={"body": body},
    )


def _split_repository(repository: str) -> tuple[str, str]:
    owner, _, repo = repository.partition("/")
    return owner, repo


def ensure_status_comment(team_id: int, report_id: str) -> None:
    """Post (or reset) the report's status comment at run kickoff and remember its id.

    Reuses the previous turn's comment when one exists — by the stored id, falling back to a marker
    scan for a crashed prior run — so a PR carries one status comment across every re-review. A
    stored id whose comment was deleted on GitHub falls back to posting fresh.
    """
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.pr_number is None:
            return
        auth = _auth(team_id, report.repository)
        if auth is None:
            return
        token, installation_id = auth
        owner, repo = _split_repository(report.repository)
        marker = status_marker(report_id)
        body = render_in_progress_body(report_id, None)

        comment_id = report.status_comment_id
        if comment_id is None:
            comment_id = _find_marker_comment(
                owner, repo, report.pr_number, marker, token=token, installation_id=installation_id
            )
        if comment_id is not None:
            try:
                _patch_comment(owner, repo, comment_id, body, token=token, installation_id=installation_id)
            except GitHubAPIError as e:
                if e.status != 404:
                    raise
                comment_id = None  # the stored comment was deleted on GitHub; post fresh
        if comment_id is None:
            comment_id = _post_comment(
                owner, repo, report.pr_number, body, token=token, installation_id=installation_id
            )
        report.status_comment_id = comment_id
        report.status_comment_edited_at = timezone.now()
        report.save(update_fields=["status_comment_id", "status_comment_edited_at", "updated_at"])
    except Exception:
        logger.exception("Could not post the ReviewHog status comment; the review continues without it")


def maybe_refresh_status_comment(team_id: int, report_id: str) -> None:
    """Refresh the status comment with the turn's current stage, at most once per interval.

    Called after pipeline activities persist progress artefacts. The debounce is an atomic claim on
    `status_comment_edited_at`, so the concurrent fan-out's calls collapse to one edit per interval;
    a run without a status comment (eval / CLI / branch target) bails on the same claim.
    """
    try:
        now = timezone.now()
        claimed = (
            ReviewReport.objects.for_team(team_id)
            .filter(id=report_id, status_comment_id__isnull=False)
            .filter(
                Q(status_comment_edited_at__isnull=True)
                | Q(status_comment_edited_at__lt=now - STATUS_EDIT_MIN_INTERVAL)
            )
            .update(status_comment_edited_at=now)
        )
        if not claimed:
            return
        report = ReviewReport.objects.for_team(team_id).get(id=report_id)
        if report.status_comment_id is None or report.pr_number is None:
            return
        heads = {report_id: report.head_sha}
        snapshot = snapshot_stats(team_id, heads).get(report_id, SnapshotStats())
        turn = turn_stats(team_id, heads).get(report_id, TurnStats())
        # The in-flight turn's findings live one run_index ahead of the completed watermark.
        current_pairs = load_findings_bundle(team_id=team_id, report_ids=[report_id]).turn(
            report_id, report.run_count + 1
        )
        progress = progress_payload(team_id, report, snapshot, turn, current_pairs)
        auth = _auth(team_id, report.repository)
        if auth is None:
            return
        token, installation_id = auth
        owner, repo = _split_repository(report.repository)
        _patch_comment(
            owner,
            repo,
            report.status_comment_id,
            render_in_progress_body(report_id, progress),
            token=token,
            installation_id=installation_id,
        )
    except Exception:
        logger.exception("Could not refresh the ReviewHog status comment; the review continues without it")


def finalize_status_comment(
    team_id: int,
    report_id: str,
    *,
    run_index: int,
    urgency_threshold: str,
    review_url: str | None,
) -> None:
    """Rewrite the status comment with the turn's outcome: everything found vs. what was published."""
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        counts = dict.fromkeys(IssuePriority, 0)
        for finding, verdict in load_valid_findings(team_id=team_id, report_id=report_id, run_index=run_index):
            counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
        threshold = IssuePriority(urgency_threshold)
        published = published_priorities_for(threshold)
        published_count = sum(count for priority, count in counts.items() if priority in published)
        held_back_count = sum(count for priority, count in counts.items() if priority not in published)
        body = render_final_body(
            report_id,
            counts=counts,
            published_count=published_count,
            held_back_count=held_back_count,
            threshold=threshold,
            review_url=review_url,
        )
        _edit_and_stamp(team_id, report, body)
    except Exception:
        logger.exception("Could not finalize the ReviewHog status comment; the review is unaffected")


def fail_status_comment(team_id: int, report_id: str) -> None:
    """Rewrite the status comment as failed, so a dead run never reads as forever in progress."""
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        _edit_and_stamp(team_id, report, render_failed_body(report_id))
    except Exception:
        logger.exception("Could not mark the ReviewHog status comment as failed")


def _edit_and_stamp(team_id: int, report: ReviewReport, body: str) -> None:
    auth = _auth(team_id, report.repository)
    if auth is None:
        return
    token, installation_id = auth
    owner, repo = _split_repository(report.repository)
    assert report.status_comment_id is not None
    _patch_comment(owner, repo, report.status_comment_id, body, token=token, installation_id=installation_id)
    report.status_comment_edited_at = timezone.now()
    report.save(update_fields=["status_comment_edited_at", "updated_at"])
