"""The PR's live "review in progress" status comment.

One marker-tagged issue comment per report on the publish (cloud trigger) path: posted right after
the run's gates pass, edited in place as the pipeline persists progress artefacts, and rewritten
with the turn's outcome at the end — the full found-vs-published counts, or a failure notice. Always
edited, never re-posted: comment edits don't notify PR subscribers, while every new comment emails
everyone. Progress renders from the same derivation the reviews API uses (`reviewer.progress`), so
the PR comment and the UI can never disagree.

The resolution stage shares the same comment (one ReviewHog voice per PR): its progress and closing
tally live in the table's "Resolve comments" row, spliced in by `update_resolution_status_comment`, which
also creates the comment on demand for standalone resolution runs that never had a review.

Every entry point here is best-effort by construction: a status comment must never fail, block, or
retry a review, so all exceptions are swallowed after logging.
"""

import random
import logging
from collections.abc import Collection, Sequence
from dataclasses import field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, Integration
from posthog.utils import pluralize

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import (
    ALREADY_RAISED_SHOWN,
    PRIORITIES_BY_URGENCY,
    PRIORITY_LABELS,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    finding_heading,
    published_priorities_for,
)
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.models.thread_resolution import CommitHold
from products.review_hog.backend.reviewer.persistence import load_findings_bundle
from products.review_hog.backend.reviewer.progress import (
    SnapshotStats,
    TurnStats,
    finding_counts,
    progress_payload,
    snapshot_stats,
    turn_stats,
)
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    github_api_get_paginated,
    github_api_request,
    is_app_bot_author,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import AlreadyRaised
from products.review_hog.backend.reviewer.tools.redaction import redact_secrets

logger = logging.getLogger(__name__)

# Refreshes are claimed atomically on this watermark, so the concurrent (perspective, chunk) fan-out
# collapses to at most one GitHub edit per interval instead of one per finished unit.
STATUS_EDIT_MIN_INTERVAL = timedelta(seconds=60)

_MODE_NAMES = {REVIEW_MODE_FLASH: "Standard", REVIEW_MODE_FULL: "Deep"}

# The steps follow the frontend's `progressLabel`, so the PR comment and the UI tell the same story.
# Each `progress_payload` stage maps to the step it belongs to. Fetching folds into step 1 there too.
_PIPELINE_STEPS = (
    "Prepare the diff",
    "Pick perspectives",
    "Run review passes",
    "Merge overlapping findings",
    "Validate findings",
    "Publish",
)
_SINGLE_AGENT_STEPS = ("Prepare the diff", "Main review and lenses", "Merge and cap", "Publish")
_STEP_BY_STAGE = {
    "fetching": 0,
    "chunking": 0,
    "selecting": 1,
    "reviewing": 2,
    "deduplicating": 3,
    "validating": 4,
    "finalizing": 5,
    "single_agent_preparing": 0,
    "single_agent_reviewing": 1,
    "single_agent_finalizing": 3,
}
_TABLE_HEADER = "| Step | Status | Result |"
_TABLE_DIVIDER = "|---|---|---|"
_RESOLVE_STEP = "Resolve comments"

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

# A clean review still posts a comment so silence never looks like a failed run.
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
    (
        "https://raw.githubusercontent.com/PostHog/pr-assets/"
        "e2fc77ad0eb32d2333ea265dfa604bbe33934905/2026/09/8193c291-b734-4c65-81c1-94488b902d14.png",
        "A white car on a quiet road",
    ),
    (
        "https://raw.githubusercontent.com/PostHog/pr-assets/"
        "ecedff577f7086db1ebb26557f5521dcbce9d322/2026/10/e052ee1b-41ec-406b-8c9d-2a1ea076490c.png",
        "Four people posing together",
    ),
    (
        "https://media.tenor.com/v-9wvFB5nBEAAAAC/twin-peaks-dance.gif",
        "The dancing man in the red room from Twin Peaks",
    ),
    (
        "https://media.tenor.com/6QRLKh0iM1wAAAAC/spoons-salad-fingers.gif",
        "Salad Fingers holds a rusty spoon",
    ),
    (
        "https://media.tenor.com/C4ta65SucIkAAAAC/dvd.gif",
        "The DVD logo bounces into a corner of an empty screen",
    ),
)


def status_marker(report_id: str) -> str:
    """The hidden marker identifying the report's status comment across turns and crashed runs."""
    return f"<!-- reviewhog:status:{report_id} -->"


_OLD_RESOLUTION_START = "<!-- reviewhog:resolution:start -->"
_OLD_RESOLUTION_END = "<!-- reviewhog:resolution:end -->"

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
_HOLD_REASONS = {
    CommitHold.STACKED: "a pull request is stacked on this branch",
    CommitHold.BRANCH_PROTECTED: "this branch is protected",
    CommitHold.MERGE_QUEUE: "this pull request was submitted to the merge queue",
}


def report_deep_link(team_id: int, report_id: str) -> str:
    """The app URL opening this report's review drawer — the held-back "view in PostHog" target.

    `?review=<report id>` is a permanent public contract (baked into GitHub comments that never get
    re-edited); the frontend's Code review URL sync accepts exactly this param, so the two must keep
    agreeing. Auth-gated like any app link — the same posture as posting Slack links publicly.
    """
    return f"{settings.SITE_URL}/project/{team_id}/code-review?review={report_id}"


def _header(review_mode: str, verb: str, head_sha: str | None) -> str:
    target = f"`{head_sha[:7]}`" if head_sha else "this pull request"
    return f"### PostHog Review · {_MODE_NAMES.get(review_mode, 'Deep')} · {verb} {target}"


def _table_row(step: str, status: str, result: str) -> str:
    return f"| {step} | {status} | {result} |"


def _table(rows: Sequence[tuple[str, str, str]]) -> list[str]:
    return [_TABLE_HEADER, _TABLE_DIVIDER, *(_table_row(*row) for row in rows)]


def _review_design(snapshot: SnapshotStats, fallback: str) -> str:
    # The fetch records the turn's design in the snapshot. Before that, the caller's design applies.
    return (snapshot.review_design if snapshot.head_matched else None) or fallback


def _step_results(
    review_design: str,
    snapshot: SnapshotStats,
    turn: TurnStats,
    pairs: Sequence[tuple[ReviewIssueFinding, ValidationVerdict | None]],
) -> list[str]:
    """The Result cell of each step before Publish. A cell stays empty until its step has a number."""
    raw = None
    if turn.perspective_issue_count is not None or turn.blind_spot_issue_count is not None:
        raw = (turn.perspective_issue_count or 0) + (turn.blind_spot_issue_count or 0)
    counts, dismissed = finding_counts(pairs)
    kept = sum(counts.values())
    files = pluralize(snapshot.files_reviewed, "file") if snapshot.files_reviewed is not None else ""
    if review_design == REVIEW_DESIGN_SINGLE_AGENT:
        # The merge and cap step persists its dropped findings as dismissed, so the kept count is its output.
        return [files, pluralize(raw, "issue") if raw is not None else "", f"{raw} → {kept}" if raw is not None else ""]

    chunks = pluralize(turn.chunk_count, "chunk") if turn.chunk_count is not None else ""
    if turn.selection_chunks is not None:
        perspective_count: int | None = len({name for chunk in turn.selection_chunks for name in chunk.perspectives})
    else:
        perspective_count = turn.perspective_count
    passes = ""
    if turn.perspective_issue_count is not None or turn.blind_spot_issue_count is not None:
        passes = pluralize(turn.perspective_issue_count or 0, "issue")
        if turn.blind_spot_issue_count:
            passes += f" (+{turn.blind_spot_issue_count} blind-spot)"
    return [
        ", ".join(part for part in (files, chunks) if part),
        pluralize(perspective_count, "perspective") if perspective_count else "",
        passes,
        f"{raw} → {len(pairs)}" if raw is not None else "",
        f"{kept} kept, {dismissed} dismissed" if kept or dismissed else "",
    ]


def render_in_progress_body(
    report_id: str,
    progress: dict[str, Any] | None,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
    head_sha: str | None = None,
    snapshot: SnapshotStats | None = None,
    turn: TurnStats | None = None,
    pairs: Sequence[tuple[ReviewIssueFinding, ValidationVerdict | None]] = (),
    failed: bool = False,
) -> str:
    """The running or failed body: done steps with their results, the current step, and the rest."""
    single_agent = review_design == REVIEW_DESIGN_SINGLE_AGENT
    steps = _SINGLE_AGENT_STEPS if single_agent else _PIPELINE_STEPS
    results = [*_step_results(review_design, snapshot or SnapshotStats(), turn or TurnStats(), pairs), ""]
    # The kickoff body has no progress yet. A single-agent turn starts its sessions right after the
    # kickoff and the next refresh waits for the first session result, so the kickoff shows the
    # reviewing step instead of the preparing step.
    stage = progress["review_stage"] if progress else ("single_agent_reviewing" if single_agent else "fetching")
    current = _STEP_BY_STAGE.get(stage, 0)
    done, total = (progress.get("done"), progress.get("total")) if progress else (None, None)
    rows = []
    for index, step in enumerate(steps):
        if index < current:
            rows.append((step, "done", results[index]))
        elif index > current:
            rows.append((step, "skipped" if failed else "waiting", ""))
        elif failed:
            rows.append((step, "failed", ""))
        else:
            rows.append((step, f"{done}/{total}" if done is not None and total else "running", ""))
    if failed:
        verb = "couldn't finish reviewing"
        # A push starts only a Standard review. A Deep review runs only when someone asks for it.
        retry = (
            "It runs again on the next push to this pull request."
            if review_mode == REVIEW_MODE_FLASH
            else "Ask for a Deep review again to retry."
        )
        intro = [f'The review failed at "{steps[current]}". {retry}', ""]
    else:
        verb, intro = "reviewing", []
    return "\n".join([_header(review_mode, verb, head_sha), "", *intro, *_table(rows), "", status_marker(report_id)])


def _priority_counts(counts: dict[IssuePriority, int], priorities: Collection[IssuePriority]) -> str:
    return ", ".join(
        f"{counts[priority]} {PRIORITY_LABELS[priority].capitalize()}"
        for priority in PRIORITIES_BY_URGENCY
        if priority in priorities and counts[priority]
    )


def render_final_body(
    report_id: str,
    *,
    threshold: IssuePriority,
    review_url: str | None,
    snapshot: SnapshotStats | None = None,
    turn: TurnStats | None = None,
    pairs: Sequence[tuple[ReviewIssueFinding, ValidationVerdict | None]] = (),
    head_sha: str | None = None,
    resolved_from: str = "author",
    report_url: str | None = None,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
    celebrate_clean_reviews: bool = True,
    marker: ReviewHogMarker | None = None,
    capped_lens_parts: int | None = None,
    raised_elsewhere: Sequence[AlreadyRaised] = (),
    raised_elsewhere_count: int = 0,
    pr_url: str | None = None,
) -> str:
    """The completed-state body: the full found counts, and how many the threshold held back.

    The counts always show everything the run found, even when only a subset was published, so
    two inline comments on the PR never read as "the review only found two things". The held-back
    note attributes the gating threshold to whoever it actually belonged to (`resolved_from`)
    and links to the report in PostHog (`report_url`, auth-gated) — the PR is otherwise the only
    place the author hears about held-back findings, so the comment must not dead-end.
    `capped_lens_parts` is set when a single-agent turn reviewed a PR past the lens part cap. The
    note goes here and not in the review body, because a clean turn posts no review. `raised_elsewhere`
    lists the findings a Full turn did not post because another reviewer's PR comment raises them, each
    linked to that comment under `pr_url`; `raised_elsewhere_count` counts all of them.
    """
    counts, _ = finding_counts(pairs)
    published = published_priorities_for(threshold)
    published_count = sum(count for priority, count in counts.items() if priority in published)
    held_back_count = sum(counts.values()) - published_count

    publish_parts = []
    if published_count:
        publish_parts.append(f"{published_count} posted" + (f" ([view review]({review_url}))" if review_url else ""))
    if held_back_count:
        # An unrecognized resolved_from reads as "author".
        attribution = _THRESHOLD_ATTRIBUTIONS.get(resolved_from, _THRESHOLD_ATTRIBUTIONS["author"])
        held = f'{held_back_count} held back by {attribution} "{_THRESHOLD_LABELS[threshold]}" threshold'
        publish_parts.append(held + (f" ([view in PostHog]({report_url}))" if report_url else ""))
    single_agent = review_design == REVIEW_DESIGN_SINGLE_AGENT
    steps = _SINGLE_AGENT_STEPS if single_agent else _PIPELINE_STEPS
    results = _step_results(review_design, snapshot or SnapshotStats(), turn or TurnStats(), pairs)
    results.append(" · ".join(publish_parts) or "Nothing to post")
    rows = [(step, "done", result) for step, result in zip(steps, results)]

    if published_count:
        summary = f"Posted {pluralize(published_count, 'finding')}: {_priority_counts(counts, published)}."
    elif held_back_count:
        summary = f"Found {pluralize(held_back_count, 'finding')}, all below the urgency threshold."
    else:
        summary = "Nothing to post."
    lines = [_header(review_mode, "reviewed", head_sha), "", summary, "", *_table(rows)]
    if capped_lens_parts is not None:
        lines.extend(
            [
                "",
                f"This pull request is large, so the review ran in {capped_lens_parts} parts with less depth than usual.",
            ]
        )
    if raised_elsewhere:
        shown = raised_elsewhere[:ALREADY_RAISED_SHOWN]
        lines.extend(["", "Also found in comments already on this pull request, so not posted again:"])
        for raised in shown:
            link = f" ([comment]({pr_url}#discussion_r{raised.comment_id}))" if pr_url else ""
            lines.append(f"- {finding_heading(raised.title, raised.level)}, raised by `{raised.commenter}`{link}")
        hidden = max(raised_elsewhere_count, len(raised_elsewhere)) - len(shown)
        if hidden > 0:
            lines.append(f"- and {hidden} more")
    # A Standard turn is the quick pass, so a clean one gets no celebration.
    elif sum(counts.values()) == 0 and review_mode != REVIEW_MODE_FLASH and celebrate_clean_reviews:
        media_url, media_alt = random.choice(_NO_ISSUES_MEDIA)
        lines.extend(["", f"![{media_alt}]({media_url})"])
    lines.extend(["", status_marker(report_id)])
    if marker is not None:
        lines.append(marker.hidden_comment())
    return "\n".join(lines)


def _fixed_with_commits(fixed: int) -> str:
    return f"{fixed} fixed with {'a commit' if fixed == 1 else 'commits'} on your branch"


def render_resolution_progress_row(*, done: int, total: int, fixed: int, left_for_you: int) -> str:
    """The resolving-state row: the run's counter plus the outcomes that matter mid-run."""
    bits = [_fixed_with_commits(fixed)] if fixed else []
    if left_for_you:
        bits.append(f"{left_for_you} left for you")
    return _table_row(_RESOLVE_STEP, f"{done}/{total}", ", ".join(bits))


def render_resolution_final_row(*, outcomes: dict[str, int], failed_turns: int) -> str:
    """The run's closing tally, including the threads the run could not handle."""
    counts: dict[str, int] = {}
    for outcome, count in outcomes.items():
        label = _RESOLUTION_OUTCOME_LABELS.get(outcome, outcome)
        counts[label] = counts.get(label, 0) + count
    bits = [
        _fixed_with_commits(counts[label]) if label == "fixed" else f"{counts[label]} {label}"
        for label in _RESOLUTION_OUTCOME_ORDER
        if counts.get(label)
    ]
    if failed_turns:
        bits.append(f"couldn't handle {failed_turns}")
    return _table_row(_RESOLVE_STEP, "done", ", ".join(bits) or "No threads needed action")


def render_resolution_failed_row(*, done: int, total: int) -> str:
    """The crashed-run row, so a dead resolution never reads as forever in progress on the PR."""
    return _table_row(_RESOLVE_STEP, "failed", f"Stopped at {done}/{total}")


def render_resolution_held_row(hold: CommitHold, *, done: int = 0, total: int = 0) -> str:
    """Why the stage did not commit fixes, so the author knows the open threads are theirs.

    `total` is set only when the run stopped part way.
    """
    reason = _HOLD_REASONS[hold]
    if total:
        return _table_row(_RESOLVE_STEP, "stopped", f"Stopped at {done}/{total} because {reason}")
    return _table_row(_RESOLVE_STEP, "skipped", f"Not run because {reason}")


def _splice_resolution_row(body: str, row: str) -> str:
    """Replace the body's Resolve comments row, or add it after the last table row."""
    # Comments posted before the step table carry the resolution text between these markers.
    head, _, rest = body.partition(_OLD_RESOLUTION_START)
    body = head.rstrip() + rest.partition(_OLD_RESOLUTION_END)[2] if rest else body
    lines = body.split("\n")
    table_rows = [index for index, line in enumerate(lines) if line.startswith("| ")]
    for index in table_rows:
        if lines[index].startswith(f"| {_RESOLVE_STEP} |"):
            lines[index] = row
            return "\n".join(lines)
    if table_rows:
        lines.insert(table_rows[-1] + 1, row)
        return "\n".join(lines)
    return "\n".join([*lines, "", *_table([]), row])


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


def ensure_status_comment(
    team_id: int,
    report_id: str,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
) -> None:
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
        body = render_in_progress_body(
            report_id, None, review_mode=review_mode, review_design=review_design, head_sha=report.head_sha
        )

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


@frozen
class _TurnState:
    """The turn's snapshot facts, pipeline shape, and (finding, verdict) pairs at the report's head."""

    snapshot: SnapshotStats
    turn: TurnStats
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]]


def _turn_state(team_id: int, report: ReviewReport, run_index: int) -> _TurnState:
    report_id = str(report.id)
    heads = {report_id: report.head_sha}
    return _TurnState(
        snapshot=snapshot_stats(team_id, heads).get(report_id, SnapshotStats()),
        turn=turn_stats(team_id, heads).get(report_id, TurnStats()),
        pairs=load_findings_bundle(team_id=team_id, report_ids=[report_id]).turn(report_id, run_index),
    )


def _render_live_body(team_id: int, report: ReviewReport, review_mode: str, review_design: str, *, failed: bool) -> str:
    # The in-flight turn's findings live one run_index ahead of the completed watermark.
    state = _turn_state(team_id, report, report.run_count + 1)
    return render_in_progress_body(
        str(report.id),
        progress_payload(team_id, report, state.snapshot, state.turn, state.pairs),
        review_mode=review_mode,
        review_design=_review_design(state.snapshot, review_design),
        head_sha=report.head_sha,
        snapshot=state.snapshot,
        turn=state.turn,
        pairs=state.pairs,
        failed=failed,
    )


def maybe_refresh_status_comment(
    team_id: int,
    report_id: str,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
) -> None:
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
        auth = _auth(team_id, report.repository)
        if auth is None:
            return
        token, installation_id = auth
        owner, repo = _split_repository(report.repository)
        body = _render_live_body(team_id, report, review_mode, review_design, failed=False)
        _patch_comment(owner, repo, report.status_comment_id, body, token=token, installation_id=installation_id)
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
    review_mode: str = REVIEW_MODE_FULL
    celebrate_clean_reviews: bool = True
    marker: ReviewHogMarker | None = None
    capped_lens_parts: int | None = None
    raised_elsewhere: list[AlreadyRaised] = field(default_factory=list)
    raised_elsewhere_count: int = 0


def finalize_status_comment(input: FinalizeStatusCommentInput) -> None:
    """Rewrite the status comment with the turn's outcome: everything found vs. what was published."""
    try:
        report = ReviewReport.objects.for_team(input.team_id).filter(id=input.report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        state = _turn_state(input.team_id, report, input.run_index)
        rendered = render_final_body(
            input.report_id,
            threshold=IssuePriority(input.urgency_threshold),
            review_url=input.review_url,
            snapshot=state.snapshot,
            turn=state.turn,
            pairs=state.pairs,
            head_sha=report.head_sha,
            resolved_from=input.resolved_from,
            report_url=report_deep_link(input.team_id, input.report_id),
            review_mode=input.review_mode,
            review_design=_review_design(state.snapshot, REVIEW_DESIGN_PIPELINE),
            celebrate_clean_reviews=input.celebrate_clean_reviews,
            marker=input.marker,
            capped_lens_parts=input.capped_lens_parts,
            raised_elsewhere=input.raised_elsewhere,
            raised_elsewhere_count=input.raised_elsewhere_count,
            pr_url=report.pr_url or None,
        )
        # The list of findings other reviewers raised carries model-written titles, which may quote sandbox output.
        body, redacted = redact_secrets(rendered)
        if redacted:
            logger.warning("Redacted %s credential-shaped string(s) from the status comment", redacted)
        _edit_and_stamp(input.team_id, report, body)
    except Exception:
        logger.exception("Could not finalize the ReviewHog status comment; the review is unaffected")


def fail_status_comment(team_id: int, report_id: str, *, review_mode: str = REVIEW_MODE_FULL) -> None:
    """Rewrite the status comment as failed, so a dead run never reads as forever in progress."""
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        _edit_and_stamp(
            team_id, report, _render_live_body(team_id, report, review_mode, REVIEW_DESIGN_PIPELINE, failed=True)
        )
    except Exception:
        logger.exception("Could not mark the ReviewHog status comment as failed")


def update_resolution_status_comment(
    team_id: int, report_id: str, row: str, *, integration_row_id: int | None = None
) -> None:
    """Splice the resolution stage's table row into the report's status comment.

    Chained runs extend the review's existing comment (edits don't notify PR subscribers, and one
    ReviewHog voice per PR beats a second comment); standalone runs, where the PR never got a
    review comment, create it on demand carrying just the resolution row. Best-effort like
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
        new_body = _splice_resolution_row(body if body else marker, row)
        if new_body == body:
            return
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
        logger.exception("Could not update the ReviewHog resolution status row; the run continues without it")


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
