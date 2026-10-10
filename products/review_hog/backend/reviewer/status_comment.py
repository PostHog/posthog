"""The PR's live "review in progress" status comment.

One marker-tagged issue comment per report on the publish (cloud trigger) path: posted right after
the run's gates pass, edited in place as the pipeline persists progress artefacts, and rewritten
with the turn's outcome at the end. Always edited, never re-posted: comment edits don't notify PR
subscribers, while every new comment emails everyone. The body is one table with a row per step of
the turn, filled in as the run progresses. Progress renders from the same derivation the reviews
API uses (`reviewer.progress`), so the PR comment and the UI can never disagree.

The resolution stage shares the same comment (one ReviewHog voice per PR): its progress and closing
tally live in a marker-delimited section spliced in by `update_resolution_status_comment`, which
also creates the comment on demand for standalone resolution runs that never had a review.

Every entry point here is best-effort by construction: a status comment must never fail, block, or
retry a review, so all exceptions are swallowed after logging.
"""

import random
import logging
from collections.abc import Sequence
from dataclasses import field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, Integration

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import (
    ALREADY_RAISED_SHOWN,
    FLASH_LENSES,
    PRIORITIES_BY_URGENCY,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    effective_priority,
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
    progress_payload,
    snapshot_stats,
    turn_stats,
)
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_PERSPECTIVE_PREFIX
from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    github_api_get_paginated,
    github_api_request,
    is_app_bot_author,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import AlreadyRaised
from products.review_hog.backend.reviewer.tools.redaction import redact_secrets
from products.review_hog.backend.reviewer.tools.single_agent_review import FlashTurnStats

logger = logging.getLogger(__name__)

# Refreshes are claimed atomically on this watermark, so the concurrent (perspective, chunk) fan-out
# collapses to at most one GitHub edit per interval instead of one per finished unit.
STATUS_EDIT_MIN_INTERVAL = timedelta(seconds=60)

_MODE_NAMES = {REVIEW_MODE_FLASH: "Standard", REVIEW_MODE_FULL: "Deep"}

# The UI's urgency-threshold labels (`URGENCY_STOPS`), for the held-back explanation.
_THRESHOLD_LABELS = {
    IssuePriority.CONSIDER: "All issues",
    IssuePriority.SHOULD_FIX: "Should fix",
    IssuePriority.MUST_FIX: "Must fix",
}

_PRIORITY_NAMES = {
    IssuePriority.MUST_FIX: "Must fix",
    IssuePriority.SHOULD_FIX: "Should fix",
    IssuePriority.CONSIDER: "Consider",
}

# Whose threshold gated publishing, keyed by how the acting user resolved (`resolved_from`): the PR
# author's own settings, the requester's ("requester wins" when someone else triggers the review),
# or the built-in default when the author has no linked PostHog user. The default variant is
# defensive, because a default-resolved run gates at "All issues" and nothing can be held back, but
# the comment must never blame a settings page that played no part.
_THRESHOLD_ATTRIBUTIONS = {
    "author": "the author's",
    "override": "the requester's",
    "default": "the default",
}

_PERSPECTIVE_LABELS = {
    f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness": "Logic",
    f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security": "Security",
    f"{REVIEW_HOG_PERSPECTIVE_PREFIX}performance-reliability": "Performance",
}
# Longer cells wrap the table on narrow screens, so a long perspective list collapses to a count.
_MAX_CELL_CHARS = 45

_DROP_REASONS = {
    "dedup_prior": "repeats",
    "dedup_comment": "repeats",
    "dedup_anchor": "repeats",
    "dedup_sibling": "repeats",
    "old_code": "unchanged code",
    "cap": "limit",
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

_TABLE_HEADER = "| Step | Status | Result |"


def report_deep_link(team_id: int, report_id: str) -> str:
    """The app URL opening this report's review drawer — the held-back "view in PostHog" target.

    `?review=<report id>` is a permanent public contract (baked into GitHub comments that never get
    re-edited); the frontend's Code review URL sync accepts exactly this param, so the two must keep
    agreeing. Auth-gated like any app link — the same posture as posting Slack links publicly.
    """
    return f"{settings.SITE_URL}/project/{team_id}/code-review?review={report_id}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _header(review_mode: str, verb: str, head_sha: str | None) -> str:
    target = f"`{head_sha[:7]}`" if head_sha else "this pull request"
    return f"### \U0001f994 PostHog Review · {_MODE_NAMES.get(review_mode, 'Deep')} · {verb} {target}"


@frozen
class TurnFacts:
    """What the turn's persisted working state says, for the table's Result cells.

    None means the step has not produced the number yet, and the cell stays empty.
    """

    files_reviewed: int | None = None
    chunk_count: int | None = None
    perspectives: tuple[str, ...] = ()
    planned_passes: int | None = None
    # Finished review sessions without the blind-spot check: perspective passes, or single-agent sessions.
    passes_done: int = 0
    pass_issues: int | None = None
    blind_spot_done: int = 0
    blind_spot_issues: int | None = None
    merged: int = 0
    judged: int = 0
    kept: int = 0


def turn_facts(
    snapshot: SnapshotStats,
    turn: TurnStats,
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
) -> TurnFacts:
    chunks = turn.selection_chunks
    verdicts = [verdict for _, verdict in pairs if verdict is not None]
    blind_spot_done = turn.blind_spot_reads or 0
    return TurnFacts(
        files_reviewed=snapshot.files_reviewed,
        chunk_count=turn.chunk_count,
        perspectives=tuple(dict.fromkeys(name for chunk in chunks or [] for name in chunk.perspectives)),
        planned_passes=sum(len(chunk.perspectives) for chunk in chunks) if chunks is not None else None,
        passes_done=(turn.perspective_reads or 0) - blind_spot_done,
        pass_issues=turn.perspective_issue_count,
        blind_spot_done=blind_spot_done,
        blind_spot_issues=turn.blind_spot_issue_count,
        merged=len(pairs),
        judged=len(verdicts),
        kept=sum(1 for verdict in verdicts if verdict.is_valid),
    )


_NO_FACTS = TurnFacts()


@frozen
class _Step:
    label: str
    result: str = ""
    counter: str | None = None
    # Whether the result already means something while the step still runs.
    partial: bool = False


@frozen
class _Row:
    step: str
    status: str
    result: str = ""


def _count(value: int | None, noun: str) -> str:
    return _plural(value, noun) if value is not None else ""


def _perspective_names(names: Sequence[str]) -> str:
    labels = [
        _PERSPECTIVE_LABELS.get(name) or name.removeprefix(REVIEW_HOG_PERSPECTIVE_PREFIX).replace("-", " ").capitalize()
        for name in names
    ]
    text = ", ".join(labels)
    return text if len(text) <= _MAX_CELL_CHARS else _plural(len(labels), "perspective")


def _pipeline_steps(facts: TurnFacts, publish_result: str = "") -> list[_Step]:
    raw = None
    blind_spot_result = ""
    if facts.pass_issues is not None:
        raw = facts.pass_issues + (facts.blind_spot_issues or 0)
        if facts.blind_spot_issues is not None:
            blind_spot_result = f"+{_plural(facts.blind_spot_issues, 'issue')} ({raw} in total)"
    return [
        _Step(
            label="Prepare the diff",
            result=", ".join(
                part for part in (_count(facts.files_reviewed, "file"), _count(facts.chunk_count, "chunk")) if part
            ),
        ),
        _Step(label="Pick perspectives", result=_perspective_names(facts.perspectives)),
        _Step(
            label="Review passes",
            result=_count(facts.pass_issues, "issue"),
            counter=f"{facts.passes_done}/{facts.planned_passes}" if facts.planned_passes else None,
            partial=True,
        ),
        _Step(
            label="Blind-spot check",
            result=blind_spot_result,
            counter=f"{facts.blind_spot_done}/{facts.chunk_count}" if facts.chunk_count else None,
            partial=True,
        ),
        _Step(label="Merge overlapping findings", result=f"{raw} → {facts.merged}" if raw is not None else ""),
        _Step(
            label="Validate",
            result=f"{facts.kept} kept, {facts.judged - facts.kept} dismissed" if facts.judged else "",
            counter=f"{facts.judged}/{facts.merged}" if facts.merged else None,
            partial=True,
        ),
        _Step(label="Publish", result=publish_result),
    ]


def _single_agent_steps(
    facts: TurnFacts, flash: FlashTurnStats | None = None, failed_sessions: int = 0, publish_result: str = ""
) -> list[_Step]:
    sessions = _Step(
        label="Main review and lenses",
        result=f"{_plural(facts.passes_done, 'session')} finished" if facts.passes_done else "",
        partial=True,
    )
    merge = _Step(label="Merge and cap")
    if flash is not None:
        lenses = len(FLASH_LENSES) * flash.lens_part_count
        total = 1 + lenses
        raised = sum(flash.candidates.values())
        sessions = _Step(
            label=f"Main review + {lenses} {'lens' if lenses == 1 else 'lenses'}" if lenses else "Main review",
            result=_plural(raised, "finding"),
            counter=f"{total - failed_sessions}/{total}",
        )
        # An unknown disposition stays out of the cell rather than failing the outcome edit.
        reasons = ", ".join(
            dict.fromkeys(
                _DROP_REASONS[reason] for reason, count in flash.dropped.items() if count and reason in _DROP_REASONS
            )
        )
        merge = _Step(label="Merge and cap", result=f"{raised} → {flash.kept}" + (f" ({reasons})" if reasons else ""))
    return [
        _Step(label="Prepare the diff", result=_count(facts.files_reviewed, "file")),
        sessions,
        merge,
        _Step(label="Publish", result=publish_result),
    ]


def _steps(
    review_design: str,
    facts: TurnFacts,
    *,
    flash: FlashTurnStats | None = None,
    failed_sessions: int = 0,
    publish_result: str = "",
) -> list[_Step]:
    # Branch on the design, not the mode: an older Standard turn ran the full pipeline.
    if review_design == REVIEW_DESIGN_SINGLE_AGENT:
        return _single_agent_steps(facts, flash, failed_sessions, publish_result)
    return _pipeline_steps(facts, publish_result)


_PIPELINE_STEP_BY_STAGE = {
    "fetching": 0,
    "chunking": 0,
    "selecting": 1,
    "reviewing": 2,
    "deduplicating": 4,
    "validating": 5,
    "finalizing": 6,
}
_SINGLE_AGENT_STEP_BY_STAGE = {
    "single_agent_preparing": 0,
    "single_agent_reviewing": 1,
    "single_agent_finalizing": 3,
}


def _current_step(progress: dict[str, Any] | None, review_design: str, facts: TurnFacts) -> int:
    if review_design == REVIEW_DESIGN_SINGLE_AGENT:
        # A single-agent turn starts its sessions right after the kickoff, and the next refresh waits
        # for the first session result, so the kickoff already shows the review step.
        stage = progress["review_stage"] if progress else "single_agent_reviewing"
        return _SINGLE_AGENT_STEP_BY_STAGE.get(stage, 1)
    stage = progress["review_stage"] if progress else "fetching"
    # Each chunk's blind-spot check runs after that chunk's passes, all inside the "reviewing" stage.
    if stage == "reviewing" and facts.planned_passes is not None and facts.passes_done >= facts.planned_passes:
        return 3
    return _PIPELINE_STEP_BY_STAGE.get(stage, 0)


def _rows(steps: list[_Step], current: int | None, *, failed: bool = False) -> list[_Row]:
    """Rows before `current` are done, later ones wait (or were skipped). `current=None` means all done."""
    rows = []
    for index, step in enumerate(steps):
        if current is None or index < current:
            rows.append(_Row(step=step.label, status=f"✅ {step.counter or 'Done'}", result=step.result))
        elif index > current:
            rows.append(_Row(step=step.label, status="Skipped" if failed else "⏸ Waiting"))
        elif failed:
            rows.append(_Row(step=step.label, status="❌ Failed"))
        else:
            result = step.result if step.partial else ""
            rows.append(_Row(step=step.label, status=f"⏳ {step.counter or 'Running'}", result=result))
    return rows


def _table_row(step: str, status: str, result: str) -> str:
    return f"| {step} | {status} | {result} |"


def _table(rows: Sequence[_Row]) -> list[str]:
    return [_TABLE_HEADER, "|---|---|---|", *(_table_row(row.step, row.status, row.result) for row in rows)]


def render_in_progress_body(
    report_id: str,
    progress: dict[str, Any] | None,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
    head_sha: str | None = None,
    facts: TurnFacts = _NO_FACTS,
) -> str:
    """The running-state body: done steps with their results, the current step, and the waiting ones."""
    steps = _steps(review_design, facts)
    current = _current_step(progress, review_design, facts)
    return "\n".join(
        [
            _header(review_mode, "reviewing", head_sha),
            "",
            f"Reviewing · step {current + 1} of {len(steps)}",
            "",
            *_table(_rows(steps, current)),
            "",
            "<sub>This comment updates as the review runs.</sub>",
            "",
            status_marker(report_id),
        ]
    )


def render_failed_body(
    report_id: str,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
    head_sha: str | None = None,
    progress: dict[str, Any] | None = None,
    facts: TurnFacts = _NO_FACTS,
) -> str:
    """The failed-state body: the table up to the step that failed, so the author sees where it stopped."""
    steps = _steps(review_design, facts)
    current = _current_step(progress, review_design, facts)
    # A push starts only a Standard review. A Deep review runs only when someone asks for it.
    retry = (
        "It runs again on the next push to this pull request."
        if review_mode == REVIEW_MODE_FLASH
        else "Ask for a Deep review again to retry."
    )
    return "\n".join(
        [
            _header(review_mode, "couldn't finish reviewing", head_sha),
            "",
            f'The review failed at "{steps[current].label}". {retry}',
            "",
            *_table(_rows(steps, current, failed=True)),
            "",
            status_marker(report_id),
        ]
    )


def _priority_counts(counts: dict[IssuePriority, int], priorities: set[IssuePriority]) -> str:
    return ", ".join(
        f"{counts[priority]} {_PRIORITY_NAMES[priority]}"
        for priority in PRIORITIES_BY_URGENCY
        if priority in priorities and counts.get(priority)
    )


def _publish_result(
    *,
    counts: dict[IssuePriority, int],
    published_count: int,
    held_back_count: int,
    threshold: IssuePriority,
    review_url: str | None,
    resolved_from: str,
    report_url: str | None,
) -> str:
    parts = []
    if published_count > 0:
        posted = f"{published_count} posted"
        if review_url:
            posted += f" ([view review]({review_url}))"
        parts.append(posted)
    if held_back_count > 0:
        held = _priority_counts(counts, set(PRIORITIES_BY_URGENCY) - published_priorities_for(threshold))
        attribution = _THRESHOLD_ATTRIBUTIONS.get(resolved_from, _THRESHOLD_ATTRIBUTIONS["author"])
        sentence = f'{held} held back by {attribution} "{_THRESHOLD_LABELS[threshold]}" threshold'
        if report_url:
            sentence += f" ([view in PostHog]({report_url}))"
        parts.append(sentence)
    return " · ".join(parts) or "Nothing to post"


def _raised_elsewhere_lines(raised_elsewhere: Sequence[AlreadyRaised], total: int, pr_url: str | None) -> list[str]:
    shown = raised_elsewhere[:ALREADY_RAISED_SHOWN]
    lines = ["Also found in comments already on this pull request, so not posted again:"]
    for raised in shown:
        link = f" ([comment]({pr_url}#discussion_r{raised.comment_id}))" if pr_url else ""
        lines.append(f"- {finding_heading(raised.title, raised.level)}, raised by `{raised.commenter}`{link}")
    hidden = max(total, len(raised_elsewhere)) - len(shown)
    if hidden > 0:
        lines.append(f"- and {hidden} more")
    return lines


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
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
    head_sha: str | None = None,
    facts: TurnFacts = _NO_FACTS,
    flash: FlashTurnStats | None = None,
    failed_sessions: int = 0,
    celebrate_clean_reviews: bool = True,
    marker: ReviewHogMarker | None = None,
    capped_lens_parts: int | None = None,
    raised_elsewhere: Sequence[AlreadyRaised] = (),
    raised_elsewhere_count: int = 0,
    pr_url: str | None = None,
) -> str:
    """The completed-state body: every step done, what was posted, and what the threshold held back.

    The summary and the table count everything the run found, even when only a subset was published,
    so two inline comments on the PR never read as "the review only found two things". The Publish
    cell attributes the gating threshold to whoever it belonged to (`resolved_from`) and links to the
    report in PostHog (`report_url`, auth-gated), because the PR is otherwise the only place the author
    hears about held-back findings. `capped_lens_parts` is set when a single-agent turn reviewed a PR
    past the lens part cap. The note goes here and not in the review body, because a clean turn posts
    no review. `raised_elsewhere` lists the findings a Deep turn did not post because another
    reviewer's PR comment raises them, each linked to that comment under `pr_url`;
    `raised_elsewhere_count` counts all of them.
    """
    publish_result = _publish_result(
        counts=counts,
        published_count=published_count,
        held_back_count=held_back_count,
        threshold=threshold,
        review_url=review_url,
        resolved_from=resolved_from,
        report_url=report_url,
    )
    steps = _steps(review_design, facts, flash=flash, failed_sessions=failed_sessions, publish_result=publish_result)
    table = _table(_rows(steps, None))

    found_total = sum(counts.values())
    if published_count > 0:
        summary = f"Posted {_plural(published_count, 'finding')}: {_priority_counts(counts, published_priorities_for(threshold))}."
    elif held_back_count > 0:
        summary = f"Nothing posted: {_plural(held_back_count, 'finding')} below the urgency threshold."
    elif raised_elsewhere:
        summary = "Nothing new to raise."
    else:
        summary = "Nothing worth raising."

    lines = [_header(review_mode, "reviewed", head_sha), "", summary, "", *table]
    if capped_lens_parts is not None:
        lines.extend(
            [
                "",
                f"This pull request is large, so the review ran in {capped_lens_parts} parts with less depth than usual.",
            ]
        )
    if raised_elsewhere:
        lines.extend(["", *_raised_elsewhere_lines(raised_elsewhere, raised_elsewhere_count, pr_url)])
    # A Standard turn is the quick pass, so a clean one gets no celebration.
    elif found_total == 0 and review_mode != REVIEW_MODE_FLASH and celebrate_clean_reviews:
        media_url, media_alt = random.choice(_NO_ISSUES_MEDIA)
        lines.extend(["", f"![{media_alt}]({media_url})"])
    lines.extend(["", status_marker(report_id)])
    if marker is not None:
        lines.append(marker.hidden_comment())
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


def render_resolution_held_section(hold: CommitHold, *, done: int = 0, total: int = 0) -> str:
    """Why the stage did not commit fixes, so the author knows the open threads are theirs.

    `total` is set only when the run stopped part way.
    """
    if hold == CommitHold.STACKED:
        line = (
            f"Stopped resolving comments at {done}/{total}: another pull request is now stacked on this branch"
            if total
            else "Not resolving comments: other pull requests are stacked on this branch"
        )
        why = "A fix commit here would leave the stacked pull requests out of date"
    elif hold == CommitHold.BRANCH_PROTECTED:
        line = (
            f"Stopped resolving comments at {done}/{total}: this branch is now protected"
            if total
            else "Not resolving comments: this branch is protected"
        )
        why = "A person decides what lands on a protected branch"
    else:
        line = (
            f"Stopped resolving comments at {done}/{total}: this pull request was submitted to the merge queue"
            if total
            else "Not resolving comments: this pull request is submitted to the merge queue"
        )
        why = "A fix commit would change what was submitted, or remove it from the queue"
    return "\n".join([f"**{line}**", "", f"<sub>{why}, so the open threads stay with you.</sub>"])


def _splice_resolution_section(body: str, section: str) -> str:
    """Replace (or append) the marker-delimited resolution section within a comment body."""
    block = f"{RESOLUTION_SECTION_START}\n{section}\n{RESOLUTION_SECTION_END}"
    if RESOLUTION_SECTION_START in body and RESOLUTION_SECTION_END in body:
        head, _, rest = body.partition(RESOLUTION_SECTION_START)
        _, _, tail = rest.partition(RESOLUTION_SECTION_END)
        return f"{head.rstrip()}\n\n{block}{tail}"
    return f"{body.rstrip()}\n\n{block}" if body.strip() else block


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
    snapshot: SnapshotStats
    turn: TurnStats
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]]


def _turn_state(team_id: int, report: ReviewReport, run_index: int) -> _TurnState:
    """The turn's persisted working state, read the same way the reviews API reads it."""
    report_id = str(report.id)
    heads = {report_id: report.head_sha}
    return _TurnState(
        snapshot=snapshot_stats(team_id, heads).get(report_id, SnapshotStats()),
        turn=turn_stats(team_id, heads).get(report_id, TurnStats()),
        pairs=load_findings_bundle(team_id=team_id, report_ids=[report_id]).turn(report_id, run_index),
    )


def _live_body(report: ReviewReport, state: _TurnState, *, failed: bool, review_mode: str, review_design: str) -> str:
    progress = progress_payload(report.team_id, report, state.snapshot, state.turn, state.pairs)
    facts = turn_facts(state.snapshot, state.turn, state.pairs)
    if failed:
        return render_failed_body(
            str(report.id),
            progress=progress,
            review_mode=review_mode,
            review_design=review_design,
            head_sha=report.head_sha,
            facts=facts,
        )
    return render_in_progress_body(
        str(report.id),
        progress,
        review_mode=review_mode,
        review_design=review_design,
        head_sha=report.head_sha,
        facts=facts,
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
        # The in-flight turn's findings live one run_index ahead of the completed watermark.
        state = _turn_state(team_id, report, report.run_count + 1)
        body = _live_body(report, state, failed=False, review_mode=review_mode, review_design=review_design)
        auth = _auth(team_id, report.repository)
        if auth is None:
            return
        token, installation_id = auth
        owner, repo = _split_repository(report.repository)
        _patch_comment(
            owner,
            repo,
            report.status_comment_id,
            body,
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
    review_mode: str = REVIEW_MODE_FULL
    celebrate_clean_reviews: bool = True
    marker: ReviewHogMarker | None = None
    capped_lens_parts: int | None = None
    raised_elsewhere: list[AlreadyRaised] = field(default_factory=list)
    raised_elsewhere_count: int = 0
    review_design: str = REVIEW_DESIGN_PIPELINE
    flash_stats: FlashTurnStats | None = None
    failed_sessions: int = 0


def finalize_status_comment(input: FinalizeStatusCommentInput) -> None:
    """Rewrite the status comment with the turn's outcome: everything found vs. what was published."""
    try:
        report = ReviewReport.objects.for_team(input.team_id).filter(id=input.report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        state = _turn_state(input.team_id, report, input.run_index)
        counts = dict.fromkeys(IssuePriority, 0)
        for finding, verdict in state.pairs:
            if verdict is not None and verdict.is_valid:
                counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
        threshold = IssuePriority(input.urgency_threshold)
        published = published_priorities_for(threshold)
        published_count = sum(count for priority, count in counts.items() if priority in published)
        held_back_count = sum(count for priority, count in counts.items() if priority not in published)
        rendered = render_final_body(
            input.report_id,
            counts=counts,
            published_count=published_count,
            held_back_count=held_back_count,
            threshold=threshold,
            review_url=input.review_url,
            resolved_from=input.resolved_from,
            report_url=report_deep_link(input.team_id, input.report_id),
            review_mode=input.review_mode,
            review_design=input.review_design,
            head_sha=report.head_sha,
            facts=turn_facts(state.snapshot, state.turn, state.pairs),
            flash=input.flash_stats,
            failed_sessions=input.failed_sessions,
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


def fail_status_comment(
    team_id: int,
    report_id: str,
    *,
    review_mode: str = REVIEW_MODE_FULL,
    review_design: str = REVIEW_DESIGN_PIPELINE,
) -> None:
    """Rewrite the status comment as failed, so a dead run never reads as forever in progress."""
    try:
        report = ReviewReport.objects.for_team(team_id).filter(id=report_id).first()
        if report is None or report.status_comment_id is None or report.pr_number is None:
            return
        state = _turn_state(team_id, report, report.run_count + 1)
        body = _live_body(report, state, failed=True, review_mode=review_mode, review_design=review_design)
        _edit_and_stamp(team_id, report, body)
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
