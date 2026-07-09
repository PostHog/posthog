from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models import User

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.perspective_selection import (
    ChunkPerspectiveSelection,
    PerspectiveSelection,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.persistence import (
    persist_chunk_set,
    persist_perspective_results,
    persist_perspective_selection,
    persist_pr_snapshot,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution


def _pr_metadata(head_sha: str, title: str) -> PRMetadata:
    return PRMetadata(
        number=5,
        title=title,
        state="open",
        draft=False,
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-01T00:00:00Z",
        author="skoob13",
        base_branch="main",
        head_branch="feat-branch",
        head_sha=head_sha,
        commits=3,
        additions=120,
        deletions=8,
        changed_files=7,
    )


def _issues_review(count: int) -> IssuesReview:
    return IssuesReview(
        issues=[
            Issue(
                id=f"1-1-{i}",
                title="t",
                file="f.py",
                lines=[LineRange(start=1)],
                issue="i",
                suggestion="s",
                priority=IssuePriority.CONSIDER,
            )
            for i in range(count)
        ]
    )


class TestRecentReviewsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/review_hog/reviews/"

    def _report(self, *, pr_number: int, acting_user: User | None, completed: bool = True, **kwargs) -> ReviewReport:
        return ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            repository="PostHog/posthog",
            pr_number=pr_number,
            pr_url=kwargs.pop("pr_url", f"https://github.com/PostHog/posthog/pull/{pr_number}"),
            head_branch="feat-branch",
            base_branch="main",
            acting_user=acting_user,
            run_count=kwargs.pop("run_count", 1),
            last_run_at=datetime(2026, 7, 1, tzinfo=UTC) if completed else None,
            # Mirror the pipeline: finalize flips a completed report to IDLE; a run in flight is ACTIVE.
            status=kwargs.pop("status", ReviewReport.Status.IDLE if completed else ReviewReport.Status.ACTIVE),
            **kwargs,
        )

    def _finding(
        self,
        report: ReviewReport,
        key: str,
        *,
        priority: IssuePriority,
        run_index: int = 1,
        is_valid: bool = True,
        adjusted: IssuePriority | None = None,
        judged: bool = True,
        perspective: str | None = None,
    ) -> None:
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ReviewIssueFinding(
                issue_key=key,
                run_index=run_index,
                title=f"title {key}",
                file="f.py",
                lines=[LineRange(start=10, end=20)],
                body="b",
                suggestion="s",
                priority=priority,
                source_perspective=perspective,
            ),
            attribution=ArtefactAttribution.system(),
        )
        if not judged:
            return
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ValidationVerdict(issue_key=key, is_valid=is_valid, argumentation="a", adjusted_priority=adjusted),
            attribution=ArtefactAttribution.system(),
        )

    def test_lists_only_my_completed_reviews(self) -> None:
        # The block is "your recent reviews": a teammate's report and an abandoned (stale, never
        # completed) run must not appear — a filter regression would leak other users' review
        # activity or show a dead run as forever in progress.
        mine = self._report(pr_number=1, acting_user=self.user)
        with freeze_time(timezone.now() - timedelta(hours=2)):
            self._report(pr_number=2, acting_user=self.user, completed=False)
        other = User.objects.create_and_join(self.organization, "other-reviews@posthog.com", None)
        self._report(pr_number=3, acting_user=other)

        res = self.client.get(self.url)

        assert res.status_code == 200
        rows = res.json()
        assert [r["pr_number"] for r in rows] == [1]
        assert rows[0]["github_url"] == mine.pr_url
        assert rows[0]["published"] is False
        assert "perspective_selection" not in rows[0]  # detail-only payload — the list stays lean

    def test_counts_scope_to_the_latest_run_and_fall_back_to_the_branch_url(self) -> None:
        # Counts must reflect only the latest turn's VALID findings at their EFFECTIVE priority —
        # stale turns, invalid findings, or ignoring the validator's override all miscount the row.
        report = self._report(pr_number=5, acting_user=self.user, pr_url="", run_count=2)
        self._finding(report, "2-a", priority=IssuePriority.MUST_FIX, run_index=2)
        self._finding(report, "2-b", priority=IssuePriority.CONSIDER, run_index=2, adjusted=IssuePriority.SHOULD_FIX)
        self._finding(report, "2-c", priority=IssuePriority.MUST_FIX, run_index=2, is_valid=False)
        self._finding(report, "1-stale", priority=IssuePriority.MUST_FIX, run_index=1)

        res = self.client.get(self.url)

        assert res.status_code == 200
        row = res.json()[0]
        assert row["github_url"] == "https://github.com/PostHog/posthog/tree/feat-branch"
        assert (row["must_fix_count"], row["should_fix_count"], row["consider_count"]) == (1, 1, 0)

    def test_list_enriches_rows_from_the_turns_working_state(self) -> None:
        # The PR facts and pipeline stats are extracted DB-side from jsonb; a broken extraction (or
        # broken head-matching) silently nulls every row's title/author/stats or shows a stale turn's.
        report = self._report(pr_number=5, acting_user=self.user, head_sha="new-sha")
        report_id = str(report.id)
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="old-sha",
            pr_metadata=_pr_metadata("old-sha", "old title"),
            pr_comments=[],
            pr_files=[],
        )
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="new-sha",
            pr_metadata=_pr_metadata("new-sha", "feat: current title"),
            pr_comments=[],
            pr_files=[
                PRFile(filename="a.py", status="modified", additions=1, deletions=0),
                PRFile(filename="b.py", status="modified", additions=1, deletions=0),
            ],
        )
        # A newer snapshot for a head that was never reviewed must not displace the reviewed one.
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="orphan-sha",
            pr_metadata=_pr_metadata("orphan-sha", "orphan title"),
            pr_comments=[],
            pr_files=[],
        )
        persist_chunk_set(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="old-sha",
            chunks=ChunksList(chunks=[Chunk(chunk_id=i, files=[FileInfo(filename="a.py")]) for i in range(5)]),
        )
        persist_chunk_set(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="new-sha",
            chunks=ChunksList(chunks=[Chunk(chunk_id=i, files=[FileInfo(filename="a.py")]) for i in range(2)]),
        )
        persist_perspective_results(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="old-sha",
            results={(1, 1): _issues_review(9)},
        )
        persist_perspective_results(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="new-sha",
            results={(1, 1): _issues_review(2), (2, 1): _issues_review(1), (1000, 1): _issues_review(1)},
        )
        # A stale-head selection must not surface; the reviewed head's one aggregates to run/skipped.
        persist_perspective_selection(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="old-sha",
            roster=["s-stale"],
            selection=PerspectiveSelection(
                chunks=[ChunkPerspectiveSelection(chunk_id=0, perspectives=["s-stale"], reason="old")]
            ),
        )
        persist_perspective_selection(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="new-sha",
            roster=["s-logic", "s-sec", "s-perf"],
            selection=PerspectiveSelection(
                chunks=[
                    ChunkPerspectiveSelection(chunk_id=0, perspectives=["s-logic"], reason="docs-only chunk"),
                    ChunkPerspectiveSelection(chunk_id=1, perspectives=["s-logic", "s-perf"], reason=""),
                ]
            ),
        )
        self._finding(report, "1-a", priority=IssuePriority.MUST_FIX)
        self._finding(report, "1-b", priority=IssuePriority.SHOULD_FIX, is_valid=False)
        self._finding(report, "1-c", priority=IssuePriority.CONSIDER, judged=False)

        res = self.client.get(self.url)

        assert res.status_code == 200
        row = res.json()[0]
        assert row["pr_title"] == "feat: current title"
        assert row["pr_author"] == "skoob13"
        assert (row["additions"], row["deletions"], row["changed_files"]) == (120, 8, 7)
        assert row["files_reviewed"] == 2
        assert row["chunk_count"] == 2
        assert (row["perspective_count"], row["perspective_issue_count"], row["blind_spot_issue_count"]) == (2, 3, 1)
        assert (row["candidate_count"], row["dismissed_count"]) == (3, 1)
        assert "perspective_selection" not in row

        # The detail exposes the head-matched selection per chunk (stale-head one filtered out),
        # joined with the chunk set's files, with skipped lenses computed against the roster.
        detail = self.client.get(f"{self.url}{report.id}/").json()
        assert detail["perspective_selection"] == {
            "roster": ["s-logic", "s-sec", "s-perf"],
            "chunks": [
                {
                    "chunk_id": 0,
                    "chunk_type": None,
                    "files": ["a.py"],
                    "perspectives": ["s-logic"],
                    "skipped": ["s-sec", "s-perf"],
                    "reason": "docs-only chunk",
                },
                {
                    "chunk_id": 1,
                    "chunk_type": None,
                    "files": ["a.py"],
                    "perspectives": ["s-logic", "s-perf"],
                    "skipped": ["s-sec"],
                    "reason": "",
                },
            ],
        }

    def test_retrieve_splits_findings_and_returns_the_published_body(self) -> None:
        # The drawer's contract: valid findings (most urgent first, validator override applied),
        # dismissed ones separately, unjudged ones in neither, and the published body verbatim.
        report = self._report(pr_number=7, acting_user=self.user, report_markdown="## Review body")
        self._finding(report, "1-low", priority=IssuePriority.CONSIDER)
        self._finding(report, "1-high", priority=IssuePriority.MUST_FIX, adjusted=IssuePriority.SHOULD_FIX)
        self._finding(report, "1-noise", priority=IssuePriority.SHOULD_FIX, is_valid=False)
        self._finding(report, "1-unjudged", priority=IssuePriority.MUST_FIX, judged=False)

        res = self.client.get(f"{self.url}{report.id}/")

        assert res.status_code == 200
        detail = res.json()
        assert detail["report_markdown"] == "## Review body"
        assert [f["title"] for f in detail["findings"]] == ["title 1-high", "title 1-low"]
        high = detail["findings"][0]
        assert (high["effective_priority"], high["reviewer_priority"]) == ("should_fix", "must_fix")
        assert high["lines"] == [{"start": 10, "end": 20}]
        assert high["validator_note"] == "a"
        assert [f["title"] for f in detail["dismissed_findings"]] == ["title 1-noise"]
        assert detail["perspective_selection"] is None  # no selection artefact → the drawer tab shows its empty state

    def test_in_progress_review_surfaces_with_stage_progress(self) -> None:
        # A visibly running first-turn review must appear first with a stage inferred from the
        # working state (fetching → chunking → selecting → reviewing n/m → deduplicating →
        # validating n/m → finalizing); completed rows never carry progress.
        self._report(pr_number=1, acting_user=self.user)
        running = self._report(pr_number=2, acting_user=self.user, completed=False, run_count=0, head_sha="sha1")
        running_id = str(running.id)

        rows = self.client.get(self.url).json()
        assert [r["pr_number"] for r in rows] == [2, 1]
        assert rows[0]["in_progress"] is True
        assert rows[0]["progress"] == {"review_stage": "fetching", "done": None, "total": None}
        assert rows[1]["in_progress"] is False
        assert rows[1]["progress"] is None

        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            pr_metadata=_pr_metadata("sha1", "in flight"),
            pr_comments=[],
            pr_files=[],
        )
        assert self.client.get(self.url).json()[0]["progress"]["review_stage"] == "chunking"

        persist_chunk_set(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            chunks=ChunksList(chunks=[Chunk(chunk_id=i, files=[FileInfo(filename="a.py")]) for i in range(2)]),
        )
        # A chunked turn with no reads and no plan yet is the selector's window.
        assert self.client.get(self.url).json()[0]["progress"] == {
            "review_stage": "selecting",
            "done": None,
            "total": None,
        }

        persist_perspective_results(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            results={(1, 1): _issues_review(1), (2, 1): _issues_review(0)},
        )
        # No persisted plan (a fallback run): the dense estimate — 2 chunks × (3 canonical
        # perspectives + the blind-spot sweep) = 8 expected reads.
        assert self.client.get(self.url).json()[0]["progress"] == {"review_stage": "reviewing", "done": 2, "total": 8}

        # Once the selector's plan lands, the total is exact: planned wave units + one blind spot per
        # chunk — without this, a pruned run's bar stalls below 100% against the dense estimate.
        persist_perspective_selection(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            roster=["s-logic", "s-sec", "s-perf"],
            selection=PerspectiveSelection(
                chunks=[
                    ChunkPerspectiveSelection(chunk_id=0, perspectives=["s-logic"], reason=""),
                    ChunkPerspectiveSelection(chunk_id=1, perspectives=[], reason="title-only chunk"),
                ]
            ),
        )
        assert self.client.get(self.url).json()[0]["progress"] == {"review_stage": "reviewing", "done": 2, "total": 3}

        # All planned reads in (1 selected wave unit + 2 blind spots = 3) → the dedup window.
        persist_perspective_results(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            results={(1000, 0): _issues_review(0)},
        )
        assert self.client.get(self.url).json()[0]["progress"] == {
            "review_stage": "deduplicating",
            "done": 3,
            "total": 3,
        }

        self._finding(running, "1-a", priority=IssuePriority.MUST_FIX)
        self._finding(running, "1-b", priority=IssuePriority.CONSIDER, judged=False)
        assert self.client.get(self.url).json()[0]["progress"] == {
            "review_stage": "validating",
            "done": 1,
            "total": 2,
        }

        # Every finding judged → the turn is building + publishing, the moments before it completes.
        self._finding(running, "1-b", priority=IssuePriority.CONSIDER, is_valid=False)
        assert self.client.get(self.url).json()[0]["progress"] == {
            "review_stage": "finalizing",
            "done": 2,
            "total": 2,
        }

    def test_in_progress_re_review_of_a_dormant_report_still_lists(self) -> None:
        # A re-review keeps the previous turn's last_run_at until it finalizes, so a dormant report's
        # in-flight turn ranks below the top-N completed slice — it used to be dropped from the
        # response entirely mid-run. It must surface first instead, as a running row.
        for pr_number in range(1, 6):
            self._report(pr_number=pr_number, acting_user=self.user)
        dormant = self._report(pr_number=99, acting_user=self.user, status=ReviewReport.Status.ACTIVE)
        # Older completed turn than the five above; updated_at (creation, i.e. now) keeps it fresh.
        ReviewReport.objects.for_team(self.team.id).filter(id=dormant.id).update(
            last_run_at=datetime(2026, 6, 1, tzinfo=UTC)
        )

        rows = self.client.get(self.url).json()

        assert len(rows) == 5
        assert rows[0]["pr_number"] == 99
        assert rows[0]["in_progress"] is True
        assert {r["pr_number"] for r in rows[1:]} <= set(range(1, 6))

    def test_perspective_stats_aggregate_latest_turns_of_my_reviews(self) -> None:
        # Effectiveness must aggregate each report's LATEST turn only and never mix in a teammate's
        # reviews — stale turns or foreign reports would inflate a perspective's record.
        logic = "review-hog-perspective-logic-correctness"
        blind = "review-hog-blind-spots-general"
        first = self._report(pr_number=1, acting_user=self.user, run_count=2)
        self._finding(first, "2-a", priority=IssuePriority.MUST_FIX, run_index=2, perspective=logic)
        self._finding(first, "2-b", priority=IssuePriority.CONSIDER, run_index=2, is_valid=False, perspective=logic)
        self._finding(first, "1-stale", priority=IssuePriority.MUST_FIX, run_index=1, perspective=logic)
        second = self._report(pr_number=2, acting_user=self.user)
        self._finding(second, "1-c", priority=IssuePriority.SHOULD_FIX, perspective=blind)
        other = User.objects.create_and_join(self.organization, "other-stats@posthog.com", None)
        theirs = self._report(pr_number=3, acting_user=other)
        self._finding(theirs, "1-x", priority=IssuePriority.MUST_FIX, perspective=blind)

        res = self.client.get(f"{self.url}perspective_stats/")

        assert res.status_code == 200
        data = res.json()
        assert data["report_count"] == 2
        assert data["perspectives"] == [
            {"skill_name": logic, "raised": 2, "kept": 1, "dismissed": 1},
            {"skill_name": blind, "raised": 1, "kept": 1, "dismissed": 0},
        ]

    def test_retrieve_scopes_to_the_acting_user(self) -> None:
        # A teammate's report id must 404, not leak their PR's findings; garbage ids must not 500.
        other = User.objects.create_and_join(self.organization, "other-reviews-detail@posthog.com", None)
        theirs = self._report(pr_number=9, acting_user=other)

        assert self.client.get(f"{self.url}{theirs.id}/").status_code == 404
        assert self.client.get(f"{self.url}not-a-uuid/").status_code == 404
