"""Per-team dreaming run orchestration.

A single dreaming run, for one team:

1. Resolve the team's GitHub source + a target repository.
2. List PRs merged since the team/repo's previous dreaming run (defaulting to the last 24h).
3. Fetch each PR's diff and detect missing instrumentation (product analytics, error
   tracking, LLM analytics) via the pure heuristics in ``instrumentation_gaps``.
4. Reconcile the SINGLE "dreaming-cleanup" PR — create it, or update the existing labelled
   one (never a duplicate).
5. Gather briefing context and generate + deliver the three-item project briefing
   (inbox + Slack).

The instrumentation/PR steps are split into a sync, GitHub-backed core
(``run_instrumentation_cleanup``) so they can be unit-tested with a mocked GitHub client.
The briefing is async because it calls the LLM gateway.

TODO(memory): the (separate-worktree) memory store will plug into two places here once it
lands — (a) reading prior dreaming observations to seed the briefing context, and (b)
writing this run's organized takeaways back so future runs compound. The hooks are marked
inline below.

TODO(daily-grouping): a daily duplicate-issue-grouping pass belongs alongside this run — it
would reuse the signals grouping step (`_process_signal_batch` in
`temporal/grouping.py`) on a 24h window to collapse issues that share a root cause across
sources, then feed the collapsed clusters into the briefing as a single "this keeps
happening" item rather than N near-duplicates. It is intentionally NOT built here: grouping
is embedding + LLM heavy and needs its own activity with ClickHouse access and its own
cost/timeout envelope, so it should land as a sibling activity wired into the dreaming
workflow rather than inline in this run, to keep the nightly tick's blast radius small.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.dreaming.briefing import BriefingContext
from products.signals.backend.temporal.dreaming.cleanup_content import (
    CLEANUP_PR_TITLE,
    build_cleanup_edits,
    render_pr_body,
)
from products.signals.backend.temporal.dreaming.cleanup_pr import CleanupPRResult, reconcile_cleanup_pr
from products.signals.backend.temporal.dreaming.instrumentation_gaps import (
    PullRequestDiff,
    PullRequestGaps,
    detect_gaps_across_prs,
)

logger = logging.getLogger(__name__)

# Default lookback when the team has no recorded previous dreaming run — one night's worth.
DEFAULT_LOOKBACK = timedelta(hours=24)

# Cap how many merged PRs one run inspects, and how large a single file's diff we feed to the
# detector, so a busy repo can't blow the activity's time budget or the ~2 MiB payload limit.
MAX_PRS_PER_RUN = 50
MAX_DIFF_CHARS_PER_FILE = 60_000


@dataclass(frozen=True)
class InstrumentationCleanupResult:
    """Outcome of the instrumentation-gap + cleanup-PR phase of a dreaming run."""

    repository: str | None
    prs_inspected: int
    gaps_detected: int
    pr_action: str  # "created" | "updated" | "noop" | "skipped"
    pr_number: int | None = None
    pr_url: str | None = None
    note: str = ""


def _fetch_pr_diffs(
    github: GitHubIntegration,
    repository: str,
    since_iso: str,
) -> list[PullRequestDiff]:
    """Fetch merged PRs since ``since_iso`` with their per-file diffs."""
    listed = github.list_merged_pull_requests_since(repository, since_iso)
    if not listed.get("success"):
        logger.warning(
            "dreaming: failed to list merged PRs",
            extra={"repository": repository, "error": listed.get("error")},
        )
        return []

    diffs: list[PullRequestDiff] = []
    for pr in listed.get("pull_requests", [])[:MAX_PRS_PER_RUN]:
        files_result = github.get_pull_request_files(repository, pr["number"])
        if not files_result.get("success"):
            logger.info(
                "dreaming: skipping PR with unreadable files",
                extra={"repository": repository, "pr_number": pr["number"]},
            )
            continue
        files: dict[str, str] = {}
        for f in files_result.get("files", []):
            filename = f.get("filename")
            patch = f.get("patch") or ""
            if not filename or not patch:
                continue
            files[filename] = patch[:MAX_DIFF_CHARS_PER_FILE]
        diffs.append(
            PullRequestDiff(
                number=pr["number"],
                title=pr.get("title", ""),
                merged_at=pr.get("merged_at", ""),
                author=pr.get("author", ""),
                files=files,
            )
        )
    return diffs


def run_instrumentation_cleanup(
    github: GitHubIntegration,
    repository: str,
    *,
    since_iso: str,
) -> InstrumentationCleanupResult:
    """Detect instrumentation gaps in PRs merged since ``since_iso`` and reconcile the
    singleton cleanup PR. Sync + GitHub-backed so it's unit-testable with a mocked client.
    """
    diffs = _fetch_pr_diffs(github, repository, since_iso)
    pr_gaps: list[PullRequestGaps] = detect_gaps_across_prs(diffs)
    gaps_total = sum(len(pr.gaps) for pr in pr_gaps)

    if not pr_gaps:
        return InstrumentationCleanupResult(
            repository=repository,
            prs_inspected=len(diffs),
            gaps_detected=0,
            pr_action="noop",
            note="no instrumentation gaps detected",
        )

    edits = build_cleanup_edits(pr_gaps)
    body = render_pr_body(pr_gaps)
    result: CleanupPRResult = reconcile_cleanup_pr(
        github,
        repository,
        title=CLEANUP_PR_TITLE,
        body=body,
        edits=edits,
    )
    return InstrumentationCleanupResult(
        repository=repository,
        prs_inspected=len(diffs),
        gaps_detected=gaps_total,
        pr_action=result.action,
        pr_number=result.pr_number,
        pr_url=result.pr_url,
        note=result.note,
    )


def resolve_since_iso(last_run_at_iso: str | None) -> str:
    """The ISO timestamp to inspect merges from: the previous dreaming run, or 24h ago."""
    if last_run_at_iso:
        return last_run_at_iso
    return (timezone.now() - DEFAULT_LOOKBACK).isoformat()


def gather_briefing_context(team_id: int, project_name: str, scout_skills: list[str]) -> BriefingContext:
    """Assemble the briefing context from the inbox + (future) profile / memory.

    Recent inbox reports are the strongest "what mattered" signal we have today. Profile
    highlights and memory notes will enrich this as those surfaces come online.
    """
    recent_titles: list[str] = [
        title
        for title in SignalReport.objects.filter(team_id=team_id)
        .exclude(status=SignalReport.Status.DELETED)
        .exclude(title__isnull=True)
        .exclude(title="")
        .order_by("-updated_at")
        .values_list("title", flat=True)[:8]
        if title
    ]

    # TODO(memory): read prior dreaming observations from the memory store and fold the most
    # relevant into `profile_highlights` (or a dedicated `memory_notes` slot on
    # BriefingContext) so the briefing compounds across nights instead of starting cold.
    profile_highlights: list[str] = []

    return BriefingContext(
        project_name=project_name,
        scout_skills=tuple(scout_skills),
        recent_report_titles=tuple(recent_titles),
        profile_highlights=tuple(profile_highlights),
    )
