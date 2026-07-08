import logging
from dataclasses import dataclass
from typing import Any, Required, TypedDict

from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.diff_position import (
    build_diff_line_map,
    find_diff_position,
    format_line_ranges,
)
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_pr_snapshot, load_valid_findings
from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    github_api_get_paginated,
    github_api_request,
)

logger = logging.getLogger(__name__)


class ReviewComment(TypedDict, total=False):
    """One inline comment in the `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` body."""

    path: Required[str]
    body: Required[str]
    side: str
    line: int
    start_line: int
    start_side: str


@dataclass
class PublishOutcome:
    """Whether a review was actually posted, and where (the GitHub review permalink, when known).

    `review_url` is None on a no-op (nothing publishable / already published) and on the
    marker-found idempotency skip (the review exists on GitHub from a prior crashed attempt, but
    this call didn't create it, so it has no handle to it).
    """

    posted: bool
    review_url: str | None = None


def publish_persisted_review(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    run_index: int,
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    published_priorities: set[IssuePriority],
    installation_id: str | None = None,
) -> PublishOutcome:
    """Publish an already-computed review for `report_id` at `head_sha`, idempotently.

    The DB-driven publish path shared by the workflow's publish activity and the standalone
    `publish_review` management command — no recompute, no sandbox. Skips if this exact head was
    already published (so a re-trigger / re-run can't double-post or re-fire the one-time promo),
    rebuilds the inline comments from this run's valid findings against the snapshot diff, and records
    the published-head watermark only on a real post (a no-op turn must not block a later publish at
    the same head). Reads the DB, so callers run it off the event loop.
    """
    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    if report.published_head_sha == head_sha:
        logger.info(f"Review for {owner}/{repo}#{pr_number} already published at {head_sha}; skipping")
        return PublishOutcome(posted=False)
    snapshot = load_pr_snapshot(team_id=team_id, report_id=report_id, head_sha=head_sha)
    pr_files = snapshot.pr_files if snapshot is not None else []
    outcome = publish_review(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        team_id=team_id,
        report_id=report_id,
        run_index=run_index,
        pr_files=pr_files,
        token=token,
        head_sha=head_sha,
        # The alpha promo comment is posted once per report (first real publish), not every turn.
        post_promo=report.published_head_sha is None,
        published_priorities=published_priorities,
        installation_id=installation_id,
    )
    if outcome.posted:
        report.published_head_sha = head_sha
        report.save(update_fields=["published_head_sha", "updated_at"])
    return outcome


def _review_marker(report_id: str, head_sha: str) -> str:
    """A hidden marker (HTML comment) embedded in the review body for publish idempotency.

    Posting isn't atomic with saving the `published_head_sha` watermark; if we crash between them, the
    marker lets the retry spot its own already-posted review and skip.
    """
    return f"<!-- reviewhog:published:{report_id}:{head_sha} -->"


def _promo_marker(report_id: str) -> str:
    """A hidden marker (HTML comment) embedded in the promo comment — posted once per report."""
    return f"<!-- reviewhog:promo:{report_id} -->"


def publish_review(
    *,
    owner: str,
    repo: str,
    pr_number: int,
    team_id: int,
    report_id: str,
    run_index: int,
    pr_files: list[PRFile],
    token: str,
    head_sha: str,
    post_promo: bool,
    published_priorities: set[IssuePriority],
    installation_id: str | None = None,
) -> PublishOutcome:
    """Publish the review to GitHub: the stored body plus inline comments from the durable rows.

    The body is `ReviewReport.report_markdown` (rendered this turn); the inline comments are rebuilt
    from this turn's valid finding/verdict rows (`run_index`-scoped, so a prior turn's findings are
    never replayed), positioned against the PR's diff. `token` is the team's GitHub App installation
    token; `head_sha` pins the review to the exact reviewed commit so a force-push between review and
    post can't misattribute comments. `post_promo` posts the one-time "ReviewHog Alpha" feedback
    comment (the caller passes it only on the first publish for the report, so it isn't re-posted
    every turn). Reads the DB, so callers run it off the event loop.

    `posted` is False when there was nothing publishable — the caller records the published-head
    watermark only on a real post, so a no-op turn doesn't block a later turn (with a valid finding)
    from publishing at the same head.
    """
    logger.info(f"Publishing review for {owner}/{repo}#{pr_number}")

    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    marker = _review_marker(report_id, head_sha)
    body = f"{report.report_markdown}\n\n{marker}"
    valid_findings = load_valid_findings(team_id=team_id, report_id=report_id, run_index=run_index)

    diff_lines = build_diff_line_map(pr_files)
    comments = _build_inline_comments(valid_findings, diff_lines, published_priorities)

    # Gate on whether there's anything worth posting, NOT on whether any comment positioned: a valid
    # publishable finding on an off-diff line has no inline anchor but is surfaced in the body's
    # "Other findings" section, so the body must still post rather than dropping the whole review. The
    # validator's priority override wins over the reviewer's, so the gate reads the effective priority.
    publishable = [
        finding
        for finding, verdict in valid_findings
        if effective_priority(finding.priority, verdict.adjusted_priority) in published_priorities
    ]
    if not publishable:
        logger.info("No publishable issues found, skipping review")
        return PublishOutcome(posted=False)

    logger.info(f"Review: {len(body)} chars body, {len(comments)} inline comments")
    review_url = _post_github_review(
        owner,
        repo,
        pr_number,
        body,
        comments,
        token=token,
        head_sha=head_sha,
        post_promo=post_promo,
        marker=marker,
        promo_marker=_promo_marker(report_id),
        installation_id=installation_id,
    )
    return PublishOutcome(posted=True, review_url=review_url)


def _format_issue_comment(finding: ReviewIssueFinding, verdict: ValidationVerdict) -> str:
    """Format a finding + its verdict as an inline comment body."""
    formatted_lines = format_line_ranges(finding.lines)
    priority = effective_priority(finding.priority, verdict.adjusted_priority)

    meta_parts = [f"**Priority:** {priority.value}"]
    if verdict.category:
        meta_parts.append(f"**Category:** {verdict.category}")
    meta_parts.append(f"**Lines:** {formatted_lines}")

    lines = [
        f"### {finding.title}",
        "",
        " | ".join(meta_parts),
        "",
        "---",
        "",
        finding.body,
        "",
        "<details>",
        "<summary><strong>Suggested fix</strong></summary>",
        "<br>",
        "",
        finding.suggestion,
        "",
        "</details>",
        "",
        "<details>",
        ("<summary><strong>Why we think it's a valid issue</strong></summary>"),
        "<br>",
        "",
        verdict.argumentation,
        "",
        "</details>",
        "",
        "<details>",
        ("<summary><strong>Prompt to fix with AI (copy-paste)</strong></summary>"),
        "<br>",
        "",
        "```",
        "## Context",
    ]

    for lr in finding.lines:
        if lr.end is None or lr.end == lr.start:
            lines.append(f"@{finding.file}#L{lr.start}")
        else:
            lines.append(f"@{finding.file}#L{lr.start}-{lr.end}")

    lines.extend(
        [
            "",
            "<issue_description>",
            finding.body,
            "</issue_description>",
            "",
            "<issue_validation>",
            verdict.argumentation,
            "</issue_validation>",
            "",
            "## Task",
            "Investigate the issue and solve it",
            "",
            "<potential_solution>",
            finding.suggestion,
            "</potential_solution>",
            "```",
            "",
            "</details>",
            "",
        ]
    )

    return "\n".join(lines)


def _build_inline_comments(
    valid_findings: list[tuple[ReviewIssueFinding, ValidationVerdict]],
    diff_lines: dict[str, set[int]],
    published_priorities: set[IssuePriority],
) -> list[ReviewComment]:
    """Build inline comment dicts for the GitHub PR review API from valid finding/verdict rows."""
    comments: list[ReviewComment] = []

    for finding, verdict in valid_findings:
        if effective_priority(finding.priority, verdict.adjusted_priority) not in published_priorities:
            continue

        position = find_diff_position(finding.file, finding.lines, diff_lines)
        if position is None:
            # No inline anchor (off-diff line) — surfaced in the body's "Other findings" section.
            logger.info(f"Off-diff finding in {finding.file}; surfacing it in the review body, not inline")
            continue

        start_line, end_line = position
        comment = ReviewComment(
            path=finding.file,
            body=_format_issue_comment(finding, verdict),
            side="RIGHT",
        )

        if end_line is not None and end_line != start_line:
            comment["start_line"] = start_line
            comment["start_side"] = "RIGHT"
            comment["line"] = end_line
        else:
            comment["line"] = start_line

        comments.append(comment)

    return comments


def _review_already_posted(
    owner: str, repo: str, pr_number: int, marker: str, *, token: str, installation_id: str | None
) -> bool:
    """True if a review carrying this run's `marker` is already on the PR (we posted, then crashed).

    Best-effort idempotency backstop: if the readback fails we proceed to post rather than silently
    drop the review — the `published_head_sha` watermark still guards the common retry path.
    """
    try:
        return any(
            marker in (review.get("body") or "")
            for review in github_api_get_paginated(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                token=token,
                installation_id=installation_id,
                endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            )
        )
    except (GitHubAPIError, GitHubRateLimitError) as e:
        logger.warning(f"Could not read existing reviews to check publish idempotency: {e}. Proceeding to post.")
        return False


def _promo_already_posted(
    owner: str, repo: str, pr_number: int, promo_marker: str, *, token: str, installation_id: str | None
) -> bool:
    """True if the promo comment is already on the PR (posted on an attempt that later failed).

    The promo posts before the review, so a transient review-creation failure retries the whole
    activity with `published_head_sha` still unset — without this check the retry would post the
    promo a second time. Failure stakes invert versus the review readback: a duplicate promo is
    spam while a missing one is harmless, so an unreadable comment list counts as already posted.
    """
    try:
        return any(
            promo_marker in (comment.get("body") or "")
            for comment in github_api_get_paginated(
                f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
                token=token,
                installation_id=installation_id,
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            )
        )
    except (GitHubAPIError, GitHubRateLimitError) as e:
        logger.warning(f"Could not read issue comments to check promo idempotency: {e}. Skipping the promo.")
        return True


def _post_github_review(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    comments: list[ReviewComment],
    *,
    token: str,
    head_sha: str,
    post_promo: bool,
    marker: str,
    promo_marker: str,
    installation_id: str | None = None,
) -> str | None:
    """Post the review to GitHub as a PR review, pinned to the reviewed `head_sha`.

    Returns the posted review's permalink, or None on the marker-found idempotency skip.
    """
    # Idempotency: if our own review for this (report, head) is already on the PR — we posted it but
    # crashed before saving the watermark — don't double-post (the body carries the same marker).
    if _review_already_posted(owner, repo, pr_number, marker, token=token, installation_id=installation_id):
        logger.info(f"Review for {owner}/{repo}#{pr_number} at {head_sha[:12]} already on PR (marker found); skipping")
        return None

    if post_promo and not _promo_already_posted(
        owner, repo, pr_number, promo_marker, token=token, installation_id=installation_id
    ):
        github_api_request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            token=token,
            installation_id=installation_id,
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={
                "body": "ReviewHog Alpha \U0001f994 "
                "If you find any issues helpful - "
                'please reply "valid", "invalid", etc., '
                f"for evaluation purposes \U0001f64f\n\n{promo_marker}"
            },
        )

    # Pin the review to the exact commit we reviewed; without it GitHub posts against the PR's latest
    # head, so a force-push between review and post would misplace the inline comments. Best-effort:
    # the probe isolates an unresolvable commit (stale/unreachable head) from a comment-positioning
    # failure, so we post unpinned rather than failing (or dropping the inline comments).
    review_payload: dict[str, Any] = {"body": body, "event": "COMMENT"}
    if head_sha:
        try:
            github_api_request(
                "GET",
                f"/repos/{owner}/{repo}/commits/{head_sha}",
                token=token,
                installation_id=installation_id,
                endpoint="/repos/{owner}/{repo}/commits/{ref}",
            )
            review_payload["commit_id"] = head_sha
        except (GitHubAPIError, GitHubRateLimitError) as e:
            logger.warning(f"Could not resolve head_sha {head_sha} to pin the review: {e}. Posting unpinned.")

    def _create_review(payload: dict[str, Any]) -> str | None:
        review = github_api_request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            token=token,
            installation_id=installation_id,
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json=payload,
        ).json()
        return review.get("html_url")

    if comments:
        try:
            review_url = _create_review({**review_payload, "comments": comments})
            logger.info(f"Review posted with {len(comments)} inline comments")
            return review_url
        except (GitHubAPIError, GitHubRateLimitError) as e:
            logger.warning(f"Failed to post review with inline comments: {e}. Posting review body only.")

    review_url = _create_review(review_payload)
    logger.info("Review posted (body only)")
    return review_url
