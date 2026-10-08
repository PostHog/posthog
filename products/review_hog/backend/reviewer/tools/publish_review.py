import re
import logging
from dataclasses import dataclass
from typing import Any, Required, TypedDict

from django.db import transaction

from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import (
    LEGACY_FLASH_MODE_MESSAGE_PREFIX,
    PRIORITY_LABELS,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    effective_priority,
    published_priorities_for,
)
from products.review_hog.backend.reviewer.diff_position import build_diff_line_map, find_diff_position
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_pr_snapshot, load_valid_findings
from products.review_hog.backend.reviewer.review_state import published_heads_by_mode, review_already_published
from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    github_api_get_paginated,
    github_api_request,
    is_app_bot_author,
)
from products.review_hog.backend.reviewer.tools.github_threads import REVIEW_HOG_FINDING_MARKER
from products.review_hog.backend.reviewer.tools.redaction import redact_secrets

logger = logging.getLogger(__name__)

# GitHub rejects a review body over 65,536 characters; the margin covers the closing line.
FALLBACK_BODY_MAX_CHARS = 60_000


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


def _mark_report_idle(team_id: int, report_id: str) -> None:
    """Return the report to rest. Publishing runs defer finalize's idle write to this stage, and
    the reviews API reads ACTIVE as in-progress, so every publish outcome (posted, already-posted
    skip, nothing publishable) must end with the report IDLE or the UI shows a finished run as
    running until the staleness cutoff."""
    ReviewReport.objects.for_team(team_id).filter(id=report_id).update(status=ReviewReport.Status.IDLE)


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
    urgency_threshold: IssuePriority,
    installation_id: str | None = None,
    review_mode: str = REVIEW_MODE_FULL,
) -> PublishOutcome:
    """Publish an already-computed review for `report_id` at `head_sha`, idempotently.

    The DB-driven publish path shared by the workflow's publish activity and the standalone
    `publish_review` management command — no recompute, no sandbox. Skips if this exact head was
    already published (so a re-trigger / re-run can't double-post or re-fire the one-time promo),
    rebuilds the inline comments from this run's valid findings against the snapshot diff, and records
    the published-head watermark only on a real post (a no-op turn must not block a later publish at
    the same head). `urgency_threshold` gates which findings publish and is snapshotted on the report
    under this turn's `run_index`, so outcome classification later reconstructs the published set from
    the threshold that actually gated each turn, not the user's live setting and not whichever
    threshold happened to be in force at the last publish. Reads the DB, so callers run it off the
    event loop.
    """
    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    if review_already_published(report, head_sha, review_mode):
        logger.info(f"Review for {owner}/{repo}#{pr_number} already published at {head_sha}; skipping")
        _mark_report_idle(team_id, report_id)
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
        published_priorities=published_priorities_for(urgency_threshold),
        installation_id=installation_id,
        review_mode=review_mode,
    )
    if outcome.posted:
        if report.outcomes_emitted_at is not None:
            # Outcome idempotency is report-scoped: the sweep skips any report already stamped
            # emitted, so this turn's findings will never be classified. Only reachable by
            # re-triggering a review on a PR that already merged and was already classified, at a
            # head it had not been published to before. Logged rather than handled because making
            # the sweep publish-scoped would mean re-deciding outcomes per publish.
            logger.warning(
                "Report %s re-published at %s after its outcomes were emitted; this turn's findings "
                "will not be classified",
                report_id,
                head_sha,
            )
        # Every map below merges into the row's CURRENT value, so it has to be re-read under a row
        # lock: the snapshot above predates the GitHub post, and a publish that finished during it
        # would be overwritten. The standalone publish command runs outside the per-PR queue, so a
        # Flash and a Full publication really can land in this block at once, each dropping the
        # other's mode watermark. Nothing slow runs inside the lock — the posting is already done.
        with transaction.atomic():
            locked = ReviewReport.objects.for_team(team_id).select_for_update().get(id=report_id)
            locked.published_heads_by_mode = {**published_heads_by_mode(locked), review_mode: head_sha}
            locked.published_head_sha = head_sha
            # Recorded per turn, never overwritten: this turn posted only its own findings, so an
            # earlier turn's threshold stays the truth about what that turn put on the PR.
            locked.published_urgency_thresholds = {
                **(locked.published_urgency_thresholds or {}),
                str(run_index): urgency_threshold.value,
            }
            # The base a later sweep compares this turn's findings against. Without it every finding is
            # compared from the newest publish, so a fix landing between two turns falls outside the diff.
            locked.published_head_shas = {**(locked.published_head_shas or {}), str(run_index): head_sha}
            # Idle lands in the same save as the watermark, so no reader can see the published head
            # with the report still counting as in-progress.
            locked.status = ReviewReport.Status.IDLE
            locked.save(
                update_fields=[
                    "published_head_sha",
                    "published_heads_by_mode",
                    "published_urgency_thresholds",
                    "published_head_shas",
                    "status",
                    "updated_at",
                ]
            )
    else:
        _mark_report_idle(team_id, report_id)
    return outcome


def _review_marker(report_id: str, head_sha: str, review_mode: str | None = None) -> str:
    """A hidden marker (HTML comment) embedded in the review body for publish idempotency.

    Posting isn't atomic with saving the `published_head_sha` watermark; if we crash between them, the
    marker lets the retry spot its own already-posted review and skip.
    """
    suffix = f":{review_mode}" if review_mode is not None else ""
    return f"<!-- reviewhog:published:{report_id}:{head_sha}{suffix} -->"


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
    review_mode: str = REVIEW_MODE_FULL,
) -> PublishOutcome:
    """Publish the review to GitHub: the stored body plus inline comments from the durable rows.

    The body is `ReviewReport.report_markdown` (rendered this turn); the inline comments are rebuilt
    from this turn's valid finding/verdict rows (`run_index`-scoped, so a prior turn's findings are
    never replayed), positioned against the PR's diff. `token` is the team's GitHub App installation
    token; `head_sha` pins the review to the exact reviewed commit so a force-push between review and
    post can't misattribute comments. `post_promo` posts the one-time "PostHog Review alpha" feedback
    comment (the caller passes it only on the first publish for the report, so it isn't re-posted
    every turn). Reads the DB, so callers run it off the event loop.

    `posted` is False when there was nothing publishable — the caller records the published-head
    watermark only on a real post, so a no-op turn doesn't block a later turn (with a valid finding)
    from publishing at the same head.
    """
    logger.info(f"Publishing review for {owner}/{repo}#{pr_number}")

    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    marker = _review_marker(report_id, head_sha, review_mode)
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

    # When every publishable finding has its own inline comment, the body's tally repeats what the
    # comments already show, so the review posts only the hidden marker with them.
    inline_body = marker if len(comments) == len(publishable) else None

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
        inline_body=inline_body,
        legacy_marker=_review_marker(report_id, head_sha),
        review_mode=review_mode,
    )
    return PublishOutcome(posted=True, review_url=review_url)


def _finding_meta_line(priority: IssuePriority, category: str | None) -> str:
    """The severity (+ optional category) line under the title, in plain text so it reads the same
    in the PR, in email notifications, and with images blocked."""
    meta = f"**{PRIORITY_LABELS[priority].capitalize()}**"
    if category:
        meta += f" · {category.replace('_', ' ')}"
    return meta


def _format_issue_comment(
    finding: ReviewIssueFinding, verdict: ValidationVerdict, *, with_suggestion_code: bool = False
) -> str:
    """Format a finding + its verdict as an inline comment body: title, severity, issue, fix.

    The validator's argumentation stays out of the comment. It is stored on the verdict and the
    reviews API returns it as `validator_note`. The title must stay the first line, because the
    outcome sweep (`find_finding_comment`) matches a finding to its comment by that line.
    A single-agent finding has no suggestion text, and may carry replacement code instead, which
    `with_suggestion_code` posts as a GitHub suggestion block.
    """
    priority = effective_priority(finding.priority, verdict.adjusted_priority)
    lines = [f"### {finding.title}", "", _finding_meta_line(priority, verdict.category), "", finding.body, ""]
    if finding.suggestion.strip():
        lines.extend(["**Suggested fix**", "", finding.suggestion, ""])
    if with_suggestion_code and finding.suggestion_code is not None:
        lines.extend(["```suggestion", finding.suggestion_code, "```", ""])
    # Hidden marker so the resolution stage recognizes this as one of ReviewHog's own threads.
    lines.append(REVIEW_HOG_FINDING_MARKER)
    return "\n".join(lines)


def _covers_whole_range(finding: ReviewIssueFinding, start_line: int, end_line: int | None) -> bool:
    """Whether the inline comment spans exactly the finding's single line range.

    GitHub applies a suggestion block to the commented lines, so replacement code written for the
    finding's range is only safe to post when the comment covers that same range.
    """
    if len(finding.lines) != 1:
        return False
    line_range = finding.lines[0]
    return start_line == line_range.start and (end_line or start_line) == (line_range.end or line_range.start)


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
            body=_format_issue_comment(
                finding, verdict, with_suggestion_code=_covers_whole_range(finding, start_line, end_line)
            ),
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
    owner: str,
    repo: str,
    pr_number: int,
    marker: str,
    *,
    token: str,
    installation_id: str | None,
    legacy_marker: str | None = None,
    review_mode: str = REVIEW_MODE_FULL,
) -> bool:
    """True if a review carrying this run's `marker` is already on the PR (we posted, then crashed).

    Best-effort idempotency backstop: if the readback fails we proceed to post rather than silently
    drop the review — the `published_head_sha` watermark still guards the common retry path. Only
    our own app-bot's reviews count (`is_app_bot_author`, shared with the status comment's marker
    scan): on a public repo anyone can paste the marker, and a spoofed match would silently
    suppress the publish.
    """
    try:
        return any(
            is_app_bot_author(review.get("user"))
            and (
                marker in (review.get("body") or "")
                or (
                    legacy_marker is not None
                    and legacy_marker in (review.get("body") or "")
                    and (review.get("body") or "").startswith(("FLASH MODE\n", LEGACY_FLASH_MODE_MESSAGE_PREFIX))
                    == (review_mode == REVIEW_MODE_FLASH)
                )
            )
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


def _code_span(text: str) -> str:
    """`text` as a Markdown code span whose fence is longer than any backtick run inside it."""
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest_run + 1)
    # CommonMark strips one space on each side, so padding keeps an edge backtick from merging with the fence.
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _with_inline_findings(body: str, comments: list[ReviewComment]) -> str:
    """`body` plus the inline comments written out, for the body-only fallback.

    The stored body lists only the off-diff findings, so without this section a fallback post would
    drop every finding that was meant to go inline. GitHub rejects a review body over 65,536
    characters, so the section stops at `FALLBACK_BODY_MAX_CHARS` and says how many findings it left out.
    """
    if not comments:
        return body
    lines = [body, "", "## Findings on the changed lines", ""]
    size = sum(len(line) + 1 for line in lines)
    for index, comment in enumerate(comments):
        # The thread marker belongs only on a real review thread, so the fallback leaves it out.
        comment_body = comment["body"].replace(REVIEW_HOG_FINDING_MARKER, "").rstrip()
        entry = [f"{_code_span(f'{comment["path"]}:{comment.get("line", "")}')}", "", comment_body, ""]
        entry_size = sum(len(line) + 1 for line in entry)
        if size + entry_size > FALLBACK_BODY_MAX_CHARS:
            omitted = len(comments) - index
            lines.append(f"{omitted} more finding(s) left out because the review body is too long.")
            break
        lines.extend(entry)
        size += entry_size
    return "\n".join(lines)


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
    inline_body: str | None = None,
    legacy_marker: str | None = None,
    review_mode: str = REVIEW_MODE_FULL,
) -> str | None:
    """Post the review to GitHub as a PR review, pinned to the reviewed `head_sha`.

    `inline_body` replaces `body` when the review posts together with its inline comments. The
    body-only fallback posts the full `body` plus the text of every inline comment, because without
    the comments the body is the only place the review shows anything. Both bodies must carry
    `marker` for the idempotency check.
    Returns the posted review's permalink, or None on the marker-found idempotency skip.
    """
    # Idempotency: if our own review for this (report, head) is already on the PR — we posted it but
    # crashed before saving the watermark — don't double-post (the body carries the same marker).
    if _review_already_posted(
        owner,
        repo,
        pr_number,
        marker,
        token=token,
        installation_id=installation_id,
        legacy_marker=legacy_marker,
        review_mode=review_mode,
    ):
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
                "body": "PostHog Review alpha \U0001f994 "
                "If you find any issues helpful - "
                'please reply "valid", "invalid", etc., '
                f"for evaluation purposes \U0001f64f\n\n{promo_marker}"
            },
        )

    # Pin the review to the exact commit we reviewed; without it GitHub posts against the PR's latest
    # head, so a force-push between review and post would misplace the inline comments. Best-effort:
    # the probe isolates an unresolvable commit (stale/unreachable head) from a comment-positioning
    # failure, so we post unpinned rather than failing (or dropping the inline comments).
    # The review and validation sandboxes hold live tokens, and the model text arrives here unfiltered.
    body, redacted = redact_secrets(body)
    inline_body, count = redact_secrets(inline_body if inline_body is not None else body)
    redacted += count
    scrubbed: list[ReviewComment] = []
    for comment in comments:
        comment_body, count = redact_secrets(comment["body"])
        redacted += count
        scrubbed.append({**comment, "body": comment_body})
    comments = scrubbed
    if redacted:
        logger.warning(f"Redacted {redacted} value(s) from the review for {owner}/{repo}#{pr_number} before posting")

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
            review_url = _create_review({**review_payload, "body": inline_body, "comments": comments})
            logger.info(f"Review posted with {len(comments)} inline comments")
            return review_url
        except GitHubAPIError as e:
            # 422 = GitHub rejected the comment payload itself (e.g. a bad diff position) — the one case a
            # body-only fallback fixes. Anything else is transient: raise so the retry keeps the comments.
            if e.status != 422:
                raise
            logger.warning(f"Failed to post review with inline comments: {e}. Posting review body only.")
            review_payload["body"] = _with_inline_findings(body, comments)

    review_url = _create_review(review_payload)
    logger.info("Review posted (body only)")
    return review_url
