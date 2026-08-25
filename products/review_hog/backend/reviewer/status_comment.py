"""The PR's live "review in progress" status comment.

One marker-tagged issue comment per report on the publish (cloud trigger) path: posted right after
the run's gates pass, edited in place as the pipeline persists progress artefacts, and rewritten
with the turn's outcome at the end — the full found-vs-published counts, or a failure notice. Always
edited, never re-posted: comment edits don't notify PR subscribers, while every new comment emails
everyone. Progress renders from the same derivation the reviews API uses (`reviewer.progress`), so
the PR comment and the UI can never disagree.

The resolution stage shares the same comment (one ReviewHog voice per PR): its progress and closing
tally live in a marker-delimited section spliced in by `update_resolution_status_comment`, which
also creates the comment on demand for standalone resolution runs that never had a review.

Every entry point here is best-effort by construction: a status comment must never fail, block, or
retry a review, so all exceptions are swallowed after logging.
"""

import random
import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, Integration

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import (
    PRIORITIES_BY_URGENCY,
    PRIORITY_LABELS,
    effective_priority,
    published_priorities_for,
)
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
    is_app_bot_author,
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

# Whose threshold gated publishing, keyed by how the acting user resolved (`resolved_from`): the PR
# author's own settings, the requester's ("requester wins" when someone else triggers the review),
# or the built-in default when the author has no linked PostHog user. The default variant is
# defensive — a default-resolved run gates at "All issues", so nothing can be held back — but the
# comment must never blame a settings page that played no part.
_THRESHOLD_ATTRIBUTIONS = {
    "author": "the author's",
    "override": "the requester's",
    "default": "the default",
}
# Only personal thresholds live in someone's ReviewHog settings; the default variant has no page to point at.
_PERSONAL_THRESHOLD_SOURCES = frozenset({"author", "override"})

# A clean review deserves a reward, not a bare "nothing here". We still post the comment (so "no
# comment" can never be mistaken for "the run broke"), but swap the flat sign-off for calming media.
# Assets are optimized and self-hosted on pr-assets (SHA-pinned, permanent) rather than hotlinked.
_NO_ISSUES_MEDIA = (
    (
        "https://raw.githubusercontent.com/PostHog/pr-assets/"
        "2cfa8ec2d6e5c88ed94a98881499a09153681886/2026/07/41e56d03-cfbe-4660-b7d5-8774d805af5c.gif",
        "Someone relaxing in a sunny garden",
    ),
    (
        "https://raw.githubusercontent.com/PostHog/pr-assets/"
        "e58e5703b12db9127e450347a5dc7882eec1a8dd/2026/07/fb797d93-c7f5-4f67-869b-68f630e0e1a2.png",
        "A happy dog on a sunny path",
    ),
    (
        "https://raw.githubusercontent.com/PostHog/pr-assets/"
        "3cf9366a6d40bc591284b00304cb6ecd84164343/2026/07/c755cc49-ef33-4435-87e0-51074f110b19.gif",
        "A panda relaxing and waving",
    ),
)


def status_marker(report_id: str) -> str:
    """The hidden marker identifying the report's status comment across turns and crashed runs."""
    return f"<!-- reviewhog:status:{report_id} -->"


# Delimits the resolution stage's section within the status comment, so resolution updates splice
# their part in place without touching the review's own body above it.
RESOLUTION_SECTION_START = "<!-- reviewhog:resolution:start -->"
RESOLUTION_SECTION_END = "<!-- reviewhog:resolution:end -->"

# GitHub-facing labels for the resolution stage's thread outcomes, in display order.
# already_fixed and obsolete collapse into one bucket — the distinction matters in the DB, not to
# the PR author skimming a tally.
_RESOLUTION_OUTCOME_LABELS = {
    "fixed": "fixed",
    "wont_fix": "declined",
    "already_fixed": "already settled",
    "obsolete": "already settled",
    "escalate": "left for you",
}
_RESOLUTION_OUTCOME_ORDER = ("fixed", "declined", "already settled", "left for you")


def report_deep_link(team_id: int, report_id: str) -> str:
    """The app URL opening this report's review drawer — the held-back "View them in PostHog" target.

    `?review=<report id>` is a permanent public contract (baked into GitHub comments that never get
    re-edited); the frontend's Code review URL sync accepts exactly this param, so the two must keep
    agreeing. Auth-gated like any app link — the same posture as posting Slack links publicly.
    """
    return f"{settings.SITE_URL}/project/{team_id}/code-review?review={report_id}"


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
            "Specialist review skills read the changed code in parallel each from their own perspective, a blind-spot sweep "
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
    resolved_from: str = "author",
    report_url: str | None = None,
) -> str:
    """The completed-state body: the full found counts, and how many the threshold held back.

    The counts always show everything the run found, even when only a subset was published, so
    two inline comments on the PR never read as "the review only found two things". The held-back
    sentence attributes the gating threshold to whoever it actually belonged to (`resolved_from`)
    and links to the report in PostHog (`report_url`, auth-gated) — the PR is otherwise the only
    place the author hears about held-back findings, so the comment must not dead-end.
    """
    found_total = sum(counts.values())
    found_line = "Found " + ", ".join(
        f"**{counts[priority]} {PRIORITY_LABELS[priority]}**" for priority in PRIORITIES_BY_URGENCY
    )
    lines = ["### \U0001f994 ReviewHog reviewed this pull request", ""]
    if found_total == 0:
        media_url, media_alt = random.choice(_NO_ISSUES_MEDIA)
        lines.extend(
            [
                "Nothing worth raising this time, so here's a calming picture instead:",
                "",
                f"![{media_alt}]({media_url})",
            ]
        )
    else:
        lines.append(found_line + ".")
        lines.append("")
        if published_count > 0:
            published_line = f"Published {_plural(published_count, 'finding')}"
            if review_url:
                published_line += f" ([view the review]({review_url}))"
            lines.append(published_line + ".")
        if held_back_count > 0:
            # An unrecognized resolved_from reads as "author" throughout (attribution AND suffix).
            source = resolved_from if resolved_from in _THRESHOLD_ATTRIBUTIONS else "author"
            sentence = (
                f"{_plural(held_back_count, 'finding')} stayed below {_THRESHOLD_ATTRIBUTIONS[source]} "
                f'"{_THRESHOLD_LABELS[threshold]}" urgency threshold'
            )
            if source in _PERSONAL_THRESHOLD_SOURCES:
                sentence += " in their ReviewHog settings"
            sentence += ", so they were not published."
            if report_url:
                sentence += f" [View them in PostHog]({report_url})."
            lines.append(sentence)
    lines.extend(["", status_marker(report_id)])
    return "\n".join(lines)


def render_resolution_progress_section(*, done: int, total: int, fixed: int, left_for_you: int) -> str:
    """The resolving-state section: the run's counter plus the outcomes that matter mid-run."""
    line = f"Resolving comments: {done}/{total}"
    outcome_bits = [
        bit for bit, count in ((f"{fixed} fixed", fixed), (f"{left_for_you} left for you", left_for_you)) if count
    ]
    if outcome_bits:
        line += " · " + ", ".join(outcome_bits)
    return "\n".join(
        [
            f"**{line}**",
            "",
            "<sub>Safe fixes are committed to the branch; every settled thread gets a reply. "
            "This line updates as threads settle.</sub>",
        ]
    )


def render_resolution_final_section(*, outcomes: dict[str, int], failed_turns: int) -> str:
    """The run's closing tally, including the threads the run could not handle."""
    counts: dict[str, int] = {}
    for outcome, count in outcomes.items():
        label = _RESOLUTION_OUTCOME_LABELS.get(outcome, outcome)
        counts[label] = counts.get(label, 0) + count
    bits = [f"{counts[label]} {label}" for label in _RESOLUTION_OUTCOME_ORDER if counts.get(label)]
    line = "Resolved comments: " + (", ".join(bits) if bits else "no threads needed action")
    if failed_turns:
        line += f" · couldn't handle {failed_turns}"
    return f"**{line}**"


def render_resolution_failed_section(*, done: int, total: int) -> str:
    """The crashed-run section, so a dead resolution never reads as forever in progress on the PR."""
    return "\n".join(
        [
            f"**Couldn't finish resolving comments: stopped at {done}/{total}**",
            "",
            "<sub>The remaining threads were not touched. The next review or resolution run picks them up.</sub>",
        ]
    )


def _splice_resolution_section(body: str, section: str) -> str:
    """Replace (or append) the marker-delimited resolution section within a comment body."""
    block = f"{RESOLUTION_SECTION_START}\n{section}\n{RESOLUTION_SECTION_END}"
    if RESOLUTION_SECTION_START in body and RESOLUTION_SECTION_END in body:
        head, _, rest = body.partition(RESOLUTION_SECTION_START)
        _, _, tail = rest.partition(RESOLUTION_SECTION_END)
        return f"{head.rstrip()}\n\n{block}{tail}"
    return f"{body.rstrip()}\n\n{block}" if body.strip() else block


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


def _auth_from_row(team_id: int, integration_row_id: int) -> tuple[str, str | None]:
    """A fresh installation token from an already-pinned integration row, skipping `_auth`'s probe.

    A resolution run selects its installation once and refreshes the status comment after every
    thread; re-running the selection probe each time repeats a `GET /repos/{repository}` for an
    answer the run already has. GitHub still enforces access on the edit itself, so a mid-run
    revocation surfaces there and is swallowed like any other status-comment failure.
    """
    github = GitHubIntegration(Integration.objects.get(id=integration_row_id, team_id=team_id))
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
        # Adopt only our own app-bot's comments (`is_app_bot_author`): anyone can paste the marker
        # on a public repo, and the returned id gets PATCHed — matching a stranger's comment would
        # overwrite it.
        if not is_app_bot_author(comment.get("user")):
            continue
        if marker in (comment.get("body") or ""):
            return comment.get("id")
    return None


def _get_comment(owner: str, repo: str, comment_id: int, *, token: str, installation_id: str | None) -> str:
    """The comment's current body — the resolution splice edits around the review's own text."""
    response = github_api_request(
        "GET",
        f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}",
    )
    return response.json().get("body") or ""


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


@frozen
class FinalizeStatusCommentInput:
    team_id: int
    report_id: str
    run_index: int
    # The run's snapshotted threshold, so the held-back explanation matches what publish enforced.
    urgency_threshold: str
    review_url: str | None = None
    # Whose threshold gated the run ("author" / "override" / "default", from the resolve snapshot) —
    # the held-back sentence must blame the right settings. Defaulted so pre-field payloads deserialize.
    resolved_from: str = "author"


def finalize_status_comment(input: FinalizeStatusCommentInput) -> None:
    """Rewrite the status comment with the turn's outcome: everything found vs. what was published."""
    try:
        report = ReviewReport.objects.for_team(input.team_id).filter(id=input.report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        counts = dict.fromkeys(IssuePriority, 0)
        for finding, verdict in load_valid_findings(
            team_id=input.team_id, report_id=input.report_id, run_index=input.run_index
        ):
            counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
        threshold = IssuePriority(input.urgency_threshold)
        published = published_priorities_for(threshold)
        published_count = sum(count for priority, count in counts.items() if priority in published)
        held_back_count = sum(count for priority, count in counts.items() if priority not in published)
        body = render_final_body(
            input.report_id,
            counts=counts,
            published_count=published_count,
            held_back_count=held_back_count,
            threshold=threshold,
            review_url=input.review_url,
            resolved_from=input.resolved_from,
            report_url=report_deep_link(input.team_id, input.report_id),
        )
        _edit_and_stamp(input.team_id, report, body)
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


def update_resolution_status_comment(
    team_id: int, report_id: str, section: str, *, integration_row_id: int | None = None
) -> None:
    """Splice the resolution stage's section into the report's status comment.

    Chained runs extend the review's existing comment (edits don't notify PR subscribers, and one
    ReviewHog voice per PR beats a second comment); standalone runs, where the PR never got a
    review comment, create it on demand carrying just the resolution section. Best-effort like
    every entry point here: a status edit must never fail or block a resolution run.

    A resolution run passes its pinned `integration_row_id` so the token is re-minted from that row
    (`_auth_from_row`) rather than re-running the installation-selection probe on every refresh;
    without one it falls back to the probe (`_auth`).
    """
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.pr_number is None:
            return
        auth = (
            _auth_from_row(team_id, integration_row_id)
            if integration_row_id is not None
            else _auth(team_id, report.repository)
        )
        if auth is None:
            return
        token, installation_id = auth
        owner, repo = _split_repository(report.repository)
        marker = status_marker(report_id)

        comment_id = report.status_comment_id
        if comment_id is None:
            comment_id = _find_marker_comment(
                owner, repo, report.pr_number, marker, token=token, installation_id=installation_id
            )
        body: str | None = None
        if comment_id is not None:
            try:
                body = _get_comment(owner, repo, comment_id, token=token, installation_id=installation_id)
            except GitHubAPIError as e:
                if e.status != 404:
                    raise
                comment_id = None  # the stored comment was deleted on GitHub; post fresh
        # An empty existing body falls back to the marker just like a missing one: splicing into an
        # empty base drops the marker, and _find_marker_comment recovery relies on it surviving so a
        # lost status_comment_id can re-adopt the comment instead of posting a duplicate.
        new_body = _splice_resolution_section(body if body else marker, section)
        if comment_id is not None:
            _patch_comment(owner, repo, comment_id, new_body, token=token, installation_id=installation_id)
        else:
            comment_id = _post_comment(
                owner, repo, report.pr_number, new_body, token=token, installation_id=installation_id
            )
        report.status_comment_id = comment_id
        report.status_comment_edited_at = timezone.now()
        report.save(update_fields=["status_comment_id", "status_comment_edited_at", "updated_at"])
    except Exception:
        logger.exception("Could not update the ReviewHog resolution status section; the run continues without it")


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
