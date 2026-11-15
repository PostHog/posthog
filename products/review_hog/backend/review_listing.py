"""The review list, the review table, one review's detail, and the perspective stats.

Every read is batched across the page of reports it describes, and returns facade contracts.
"""

from uuid import UUID

from django.db import models
from django.db.models import F, Func, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce

from posthog.models.user import User

from products.review_hog.backend.facade.contracts import (
    OWN_DEEP_STATS_REVIEW_LIMIT,
    RESOLUTION_RESOLVING,
    REVIEW_MODE_FULL,
    ResolutionRunState,
    ResolutionSummary,
    ReviewDetail,
    ReviewDroppedFinding,
    ReviewFinding,
    ReviewLineRange,
    ReviewNotFoundError,
    ReviewPerspectiveSelection,
    ReviewPerspectiveStat,
    ReviewPerspectiveStats,
    ReviewProgress,
    ReviewSelectionChunk,
    ReviewSummary,
    ReviewSummaryPage,
    ReviewTablePage,
    ReviewTurnNotFoundError,
)
from products.review_hog.backend.facade.enums import IssuePriority, ReviewActivityFilter, ReviewReportScope
from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    DroppedFindingArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import (
    TurnFindingsBundle,
    load_chunk_set,
    load_dropped_findings,
    load_findings_bundle,
)
from products.review_hog.backend.reviewer.progress import (
    SnapshotStats,
    TurnMarker,
    TurnStats,
    finding_counts,
    in_progress_report_ids,
    latest_resolution_summaries,
    live_turn_markers,
    progress_payload,
    resolution_states,
    running_q,
    snapshot_stats,
    turn_markers,
    turn_stats,
)
from products.review_hog.backend.reviewer.review_state import completed_turn_review_mode

# Effectiveness stats aggregate deeper than the list — enough history for survival rates to mean something.
PERSPECTIVE_STATS_REPORT_LIMIT = 50

# Display order for the detail view: most urgent first.
_PRIORITY_DISPLAY_RANK = {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.CONSIDER: 2}


def _completed_turn_mode(team_id: int) -> Subquery:
    """The review mode on the completed turn's marker, matching what `turn_markers` puts on the row."""
    content = Cast("content", models.JSONField())
    return Subquery(
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=OuterRef("id"), type=ReviewReportArtefact.ArtefactType.TURN_MARKER)
        .annotate(
            marker_run_index=Cast(KeyTextTransform("run_index", content), models.IntegerField()),
            marker_review_mode=KeyTextTransform("review_mode", content),
        )
        .filter(marker_run_index=OuterRef("run_count"))
        .order_by("-created_at", "-id")
        .values_list("marker_review_mode")[:1]
    )


def _completed_turn_published() -> Func:
    """Whether `published_head_shas` has the completed turn's run index as a key (the row's `turn_published`)."""
    return Coalesce(
        Func(
            F("published_head_shas"),
            Cast("run_count", models.CharField()),
            function="jsonb_exists",
            output_field=models.BooleanField(),
        ),
        Value(False),
    )


def _turn_progress(
    team_id: int,
    reports: list[ReviewReport],
    in_progress_ids: set[str],
    resolutions: dict[str, ResolutionRunState],
    bundle: TurnFindingsBundle,
    markers: dict[tuple[str, int], TurnMarker],
) -> dict[str, ReviewProgress]:
    """The in-flight review turn's stage for each visibly running report.

    A resolving report's live run is the resolution, not a review turn. Inferring a review stage
    from the completed turn's artefacts would relabel it "deduplicating".
    """
    resolving_ids = {report_id for report_id, state in resolutions.items() if state.status == RESOLUTION_RESOLVING}
    in_flight = [
        report for report in reports if str(report.id) in in_progress_ids and str(report.id) not in resolving_ids
    ]
    if not in_flight:
        return {}
    live_heads = {str(report.id): report.head_sha for report in in_flight}
    live_snapshots = snapshot_stats(team_id, live_heads)
    live_turns = turn_stats(team_id, live_heads)
    live_markers = live_turn_markers(team_id, in_flight, markers)
    return {
        str(report.id): ReviewProgress(
            **progress_payload(
                team_id,
                report,
                live_snapshots.get(str(report.id), SnapshotStats()),
                live_turns.get(str(report.id), TurnStats()),
                # The in-flight turn's findings live one run_index ahead of the completed watermark.
                bundle.turn(str(report.id), report.run_count + 1),
                live_markers.get(str(report.id)),
                markers.get((str(report.id), report.run_count)),
            )
        )
        for report in in_flight
    }


def _line_ranges(finding: ReviewIssueFinding) -> list[ReviewLineRange]:
    return [ReviewLineRange(start=line_range.start, end=line_range.end) for line_range in finding.lines]


def _finding(finding: ReviewIssueFinding, verdict: ValidationVerdict) -> ReviewFinding:
    return ReviewFinding(
        title=finding.title,
        file=finding.file,
        lines=_line_ranges(finding),
        body=finding.body,
        suggestion=finding.suggestion,
        effective_priority=effective_priority(finding.priority, verdict.adjusted_priority).value,
        reviewer_priority=finding.priority.value,
        source_perspective=finding.source_perspective,
        validator_category=verdict.category,
        validator_note=verdict.argumentation,
    )


def _dropped_finding(dropped: DroppedFindingArtefact, pr_url: str | None) -> ReviewDroppedFinding:
    finding = dropped.finding
    comment_url = None
    if pr_url and dropped.duplicate_of and dropped.duplicate_of.startswith("comment:"):
        comment_url = f"{pr_url}#discussion_r{dropped.duplicate_of.removeprefix('comment:')}"
    return ReviewDroppedFinding(
        title=finding.title,
        file=finding.file,
        lines=_line_ranges(finding),
        body=finding.body,
        suggestion=finding.suggestion,
        priority=finding.priority.value,
        source_perspective=finding.source_perspective,
        disposition=dropped.disposition,
        duplicate_of=dropped.duplicate_of,
        comment_url=comment_url,
        rank=dropped.rank,
    )


def _selection(turn: TurnStats, chunks: ChunksList | None) -> ReviewPerspectiveSelection | None:
    """The selector's per-chunk plan for the detail drawer, joined with the chunk set's metadata."""
    if turn.selection_roster is None or turn.selection_chunks is None:
        return None
    meta_by_id = {chunk.chunk_id: chunk for chunk in chunks.chunks} if chunks is not None else {}
    rows: list[ReviewSelectionChunk] = []
    for entry in turn.selection_chunks:
        meta = meta_by_id.get(entry.chunk_id)
        selected = set(entry.perspectives)
        rows.append(
            ReviewSelectionChunk(
                chunk_id=entry.chunk_id,
                chunk_type=meta.chunk_type if meta else None,
                files=[f.filename for f in meta.files] if meta else [],
                perspectives=[name for name in turn.selection_roster if name in selected],
                skipped=[name for name in turn.selection_roster if name not in selected],
                reason=entry.reason,
            )
        )
    return ReviewPerspectiveSelection(roster=turn.selection_roster, chunks=rows)


def _summary(
    report: ReviewReport,
    run_index: int,
    snapshot: SnapshotStats,
    turn: TurnStats,
    pairs: list[tuple[ReviewIssueFinding, ValidationVerdict | None]],
    marker: TurnMarker | None,
    progress: ReviewProgress | None,
    resolution: ResolutionRunState | None,
    latest_resolution: ResolutionSummary | None,
) -> ReviewSummary:
    """The list row for one report's turn at `run_index`; the detail layers findings on top."""
    counts, dismissed = finding_counts(pairs)
    meta = snapshot.meta
    return ReviewSummary(
        id=report.id,
        repository=report.repository,
        pr_number=report.pr_number,
        pr_title=meta.title if meta else None,
        pr_author=meta.author if meta else None,
        additions=meta.additions if meta else None,
        deletions=meta.deletions if meta else None,
        changed_files=meta.changed_files if meta else None,
        head_branch=report.head_branch,
        github_url=report.pr_url or f"https://github.com/{report.repository}/tree/{report.head_branch}",
        run_count=report.run_count,
        last_run_at=report.last_run_at,
        published=report.published_head_sha is not None,
        turn_published=str(run_index) in (report.published_head_shas or {}),
        review_mode=marker.review_mode if marker else None,
        review_design=marker.review_design if marker else snapshot.review_design,
        status_comment_url=f"{report.pr_url}#issuecomment-{report.status_comment_id}"
        if report.pr_url and report.status_comment_id
        else None,
        # Reads only the per-mode marker, so the list never loads findings to tell older reports apart.
        full_review_published=REVIEW_MODE_FULL in (report.published_heads_by_mode or {}),
        in_progress=progress is not None or (resolution is not None and resolution.status == RESOLUTION_RESOLVING),
        progress=progress,
        resolution=resolution,
        latest_resolution=latest_resolution,
        must_fix_count=counts[IssuePriority.MUST_FIX],
        should_fix_count=counts[IssuePriority.SHOULD_FIX],
        consider_count=counts[IssuePriority.CONSIDER],
        candidate_count=len(pairs),
        dismissed_count=dismissed,
        files_reviewed=snapshot.files_reviewed,
        chunk_count=turn.chunk_count,
        perspective_count=turn.perspective_count,
        perspective_issue_count=turn.perspective_issue_count,
        blind_spot_issue_count=turn.blind_spot_issue_count,
    )


def _summaries(team_id: int, reports: list[ReviewReport], in_progress_ids: set[str]) -> list[ReviewSummary]:
    """List rows for a page of reports, with every per-row read batched across the page."""
    # Row stats anchor to each report's COMPLETED turn (matching the findings' run_count); the
    # in-flight progress payload alone reads the live head. Pre-column rows fall back to the live
    # watermark, which is also correct for never-finalized first turns.
    snapshots = snapshot_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
    turns = turn_stats(team_id, {str(r.id): r.completed_head_sha or r.head_sha for r in reports})
    report_ids = [str(report.id) for report in reports]
    bundle = load_findings_bundle(team_id=team_id, report_ids=report_ids)
    resolution_map = resolution_states(team_id, reports)
    markers = turn_markers(team_id, report_ids)
    progress_map = _turn_progress(team_id, reports, in_progress_ids, resolution_map, bundle, markers)
    latest_resolutions = latest_resolution_summaries(team_id, reports)
    items = []
    for report in reports:
        report_id = str(report.id)
        items.append(
            _summary(
                report,
                report.run_count,
                snapshots.get(report_id, SnapshotStats()),
                turns.get(report_id, TurnStats()),
                bundle.turn(report_id, report.run_count),
                markers.get((report_id, report.run_count)),
                progress_map.get(report_id),
                resolution_map.get(report_id),
                latest_resolutions.get(report_id),
            )
        )
    return items


def _display_order(finding: ReviewFinding) -> tuple[int, str]:
    return (_PRIORITY_DISPLAY_RANK[IssuePriority(finding.effective_priority)], finding.file)


class ReviewListing:
    """Reads of the review reports of one project. `team_id` is the root project id."""

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    def _reports(self, user_id: int, scope: ReviewReportScope) -> QuerySet[ReviewReport]:
        queryset = ReviewReport.objects.for_team(self.team_id, canonical=True)
        if scope == ReviewReportScope.MINE:
            # "For you" is the union of reviews the user ran (acting user) and reviews of PRs they
            # authored — a teammate-triggered review of your PR lands under THEIR acting_user, so
            # without the author match the findings would never reach you. The author match rides
            # the viewer's linked GitHub login (the reverse of the author→user mapping the reviewer
            # runs under), case-insensitively; no linked login keeps the acting-user-only behavior.
            mine = Q(acting_user_id=user_id)
            github_login = User.objects.get(id=user_id).get_github_login()
            if github_login:
                mine |= Q(author_login__iexact=github_login)
            queryset = queryset.filter(mine)
        return queryset

    def recent(self, user_id: int, scope: ReviewReportScope, limit: int) -> ReviewSummaryPage:
        # One row beyond the limit proves whether "Show more" has anything left to reveal.
        probe_limit = limit + 1
        queryset = self._reports(user_id, scope)
        completed = list(queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:probe_limit])
        # First-turn runs have no completed turn yet; they only surface while visibly running. A crashed
        # run stays ACTIVE, so rank by report activity: ranked by creation, newer crashed runs fill the
        # slice and hide an older live run.
        running_first_turn = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=True).order_by("-updated_at")[
                :probe_limit
            ]
        )
        # A re-review keeps the previous turn's last_run_at until it finalizes, so a dormant report's
        # in-flight turn can rank below the completed slice — fetch running re-reviews explicitly or
        # an actively reviewed PR vanishes from the list mid-run.
        running_re_review = list(
            queryset.filter(status=ReviewReport.Status.ACTIVE, last_run_at__isnull=False).order_by("-updated_at")[
                :probe_limit
            ]
        )
        in_progress_ids = in_progress_report_ids(self.team_id, running_first_turn + running_re_review + completed)
        # Visibly running first (first turns, then re-reviews), then recent completed — deduped so a
        # re-review that also ranks in the completed slice keeps its front position.
        seen: set[str] = set()
        reports: list[ReviewReport] = []
        for report in [
            *[report for report in running_first_turn if str(report.id) in in_progress_ids],
            *[report for report in running_re_review if str(report.id) in in_progress_ids],
            *completed,
        ]:
            if str(report.id) not in seen:
                seen.add(str(report.id))
                reports.append(report)
        return ReviewSummaryPage(
            results=_summaries(self.team_id, reports[:limit], in_progress_ids), has_more=len(reports) > limit
        )

    def table(
        self,
        user_id: int,
        scope: ReviewReportScope,
        *,
        repository: str | None,
        review_mode: str | None,
        activity: ReviewActivityFilter | None,
        published: bool | None,
        limit: int,
        offset: int,
    ) -> ReviewTablePage:
        queryset = self._reports(user_id, scope)
        running = running_q(self.team_id)
        # A first turn that died before completing has nothing to show, so it only appears while it runs.
        queryset = queryset.filter(Q(last_run_at__isnull=False) | running)
        if repository is not None:
            queryset = queryset.filter(repository__iexact=repository)
        if review_mode is not None:
            queryset = queryset.annotate(completed_turn_mode=_completed_turn_mode(self.team_id)).filter(
                completed_turn_mode=review_mode
            )
        if published is not None:
            queryset = queryset.annotate(completed_turn_published=_completed_turn_published()).filter(
                completed_turn_published=published
            )
        running_count = queryset.filter(running).count()
        if activity == ReviewActivityFilter.RUNNING:
            queryset = queryset.filter(running)
        elif activity == ReviewActivityFilter.COMPLETED:
            queryset = queryset.filter(last_run_at__isnull=False).exclude(running)

        reports = list(queryset.order_by("-updated_at", "-id")[offset : offset + limit])
        results = _summaries(self.team_id, reports, in_progress_report_ids(self.team_id, reports))
        return ReviewTablePage(count=queryset.count(), running_count=running_count, results=results)

    def perspective_stats(self, user_id: int, scope: ReviewReportScope) -> ReviewPerspectiveStats:
        queryset: QuerySet[ReviewReport]
        if scope == ReviewReportScope.OWN_DEEP:
            # Filter before the report limit, so newer Standard reports cannot push Deep ones out of the window.
            # Rows from before the per-mode watermark predate Standard reviews.
            queryset = ReviewReport.objects.for_team(self.team_id, canonical=True).filter(
                Q(published_heads_by_mode__has_key=REVIEW_MODE_FULL) | Q(published_heads_by_mode__isnull=True),
                acting_user_id=user_id,
            )
        else:
            queryset = self._reports(user_id, scope)
        reports = list(
            queryset.filter(last_run_at__isnull=False).order_by("-last_run_at")[:PERSPECTIVE_STATS_REPORT_LIMIT]
        )
        bundle = load_findings_bundle(team_id=self.team_id, report_ids=[str(report.id) for report in reports])
        turns = [bundle.turn(str(report.id), report.run_count) for report in reports]
        if scope == ReviewReportScope.OWN_DEEP:
            # Standard turns read none of the user's skills, so they would dilute the kept counts.
            turns = [
                pairs
                for report, pairs in zip(reports, turns)
                if completed_turn_review_mode(report, pairs) == REVIEW_MODE_FULL
            ]
            turns = turns[:OWN_DEEP_STATS_REVIEW_LIMIT]
        stats: dict[str, dict[str, int]] = {}
        for pairs in turns:
            for finding, verdict in pairs:
                entry = stats.setdefault(
                    finding.source_perspective or "unknown", {"raised": 0, "kept": 0, "dismissed": 0}
                )
                entry["raised"] += 1
                if verdict is not None:
                    entry["kept" if verdict.is_valid else "dismissed"] += 1
        items = [ReviewPerspectiveStat(skill_name=skill_name, **counts) for skill_name, counts in stats.items()]
        items.sort(key=lambda item: (-item.kept, -item.raised, item.skill_name))
        return ReviewPerspectiveStats(report_count=len(turns), perspectives=items)

    def detail(self, report_id: UUID, run_index: int | None) -> ReviewDetail:
        # Project-wide on purpose: the detail must open for any review the everyone-scope list shows.
        # Detail describes a completed turn — a first run still in flight has nothing to show yet.
        report = (
            ReviewReport.objects.for_team(self.team_id, canonical=True)
            .filter(id=report_id, last_run_at__isnull=False)
            .first()
        )
        if report is None:
            raise ReviewNotFoundError(f"No completed review {report_id}.")
        if run_index is None:
            run_index = report.run_count
        if not 1 <= run_index <= report.run_count:
            raise ReviewTurnNotFoundError(f"Review {report_id} has no completed turn {run_index}.")
        is_latest = run_index == report.run_count

        team_id = self.team_id
        key = str(report.id)
        markers = turn_markers(team_id, [key])
        marker = markers.get((key, run_index))
        # Everything the detail returns (stats, chunk set, link-anchoring head) describes the same
        # completed turn the findings come from, never an in-flight turn's watermark.
        if is_latest:
            turn_head = report.completed_head_sha or report.head_sha
        else:
            turn_head = (marker.head_sha if marker else None) or (report.published_head_shas or {}).get(str(run_index))
        snapshots = snapshot_stats(team_id, {key: turn_head})
        turns = turn_stats(team_id, {key: turn_head})
        bundle = load_findings_bundle(team_id=team_id, report_ids=[key])
        pairs = bundle.turn(key, run_index)
        chunk_set = load_chunk_set(team_id=team_id, report_id=key, head_sha=turn_head) if turn_head else None
        resolutions = resolution_states(team_id, [report])
        in_progress_ids = in_progress_report_ids(team_id, [report])
        progress = _turn_progress(team_id, [report], in_progress_ids, resolutions, bundle, markers).get(key)

        valid = [_finding(f, v) for f, v in pairs if v is not None and v.is_valid]
        dismissed = [_finding(f, v) for f, v in pairs if v is not None and not v.is_valid]
        run_urgency_threshold: str | None = (
            report.run_urgency_threshold
            if is_latest
            else (report.published_urgency_thresholds or {}).get(str(run_index))
        )
        return ReviewDetail(
            review=_summary(
                report,
                run_index,
                snapshots.get(key, SnapshotStats()),
                turns.get(key, TurnStats()),
                pairs,
                marker,
                progress,
                resolutions.get(key),
                latest_resolution_summaries(team_id, [report]).get(key),
            ),
            run_index=run_index,
            head_sha=turn_head,
            perspective_selection=_selection(turns.get(key, TurnStats()), chunk_set),
            report_markdown=report.report_markdown if is_latest else None,
            run_urgency_threshold=run_urgency_threshold or None,
            findings=sorted(valid, key=_display_order),
            dismissed_findings=sorted(dismissed, key=_display_order),
            dropped_findings=[
                _dropped_finding(dropped, report.pr_url)
                for dropped in load_dropped_findings(
                    team_id=team_id, report_id=key, run_index=run_index, head_sha=turn_head
                )
            ],
        )
