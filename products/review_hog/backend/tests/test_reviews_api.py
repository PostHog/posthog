import json
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import Team, User

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    DroppedFindingArtefact,
    FindingOutcomeArtefact,
    ResolutionRunArtefact,
    ReviewIssueFinding,
    ThreadVerdictArtefact,
    TurnMarkerArtefact,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import DEFAULT_REVIEW_ARM, REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import (
    DropDisposition,
    Issue,
    IssuePriority,
    IssuesReview,
    LineRange,
)
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
from products.review_hog.backend.reviewer.progress import (
    IN_PROGRESS_STALE_AFTER,
    RESOLUTION_RUN_NOTE_AUTHOR,
    record_run_outcome,
)
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.temporal.heartbeat import ReviewActivityHeartbeater
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact


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
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.url = f"/api/projects/{self.team.id}/review_hog/reviews/"

    def _report(
        self,
        *,
        pr_number: int,
        acting_user: User | None,
        completed: bool = True,
        team_id: int | None = None,
        **kwargs,
    ) -> ReviewReport:
        team_id = team_id if team_id is not None else self.team.id
        return ReviewReport.objects.for_team(team_id).create(
            team_id=team_id,
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
        review_mode: str | None = None,
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
                validation_context=json.dumps({"review_mode": review_mode}) if review_mode else None,
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

    def _turn_marker(self, report: ReviewReport, *, run_index: int, review_mode: str, head_sha: str) -> None:
        ReviewReportArtefact.add_turn_marker(
            team_id=self.team.id,
            report_id=str(report.id),
            content=TurnMarkerArtefact(
                head_sha=head_sha,
                run_index=run_index,
                review_mode=review_mode,
                reviewhog_version="v",
                reviewhog_fingerprint="f",
            ),
            attribution=ArtefactAttribution.system(),
        )

    @parameterized.expand([("flash", REVIEW_MODE_FLASH), ("full", REVIEW_MODE_FULL), ("no_marker", None)])
    def test_review_mode_comes_from_the_completed_turns_marker(self, _name: str, review_mode: str | None) -> None:
        # A clean, unpublished Standard turn has no findings to carry its mode, which the findings-based
        # fallback reads as Deep. The marker is the only source that tells the two apart. The older
        # turn's marker and the in-flight turn's marker must not leak onto the completed turn.
        report = self._report(pr_number=1, acting_user=self.user, run_count=2, head_sha="c3")
        self._turn_marker(report, run_index=1, review_mode=REVIEW_MODE_FULL, head_sha="c1")
        if review_mode is not None:
            self._turn_marker(report, run_index=2, review_mode=review_mode, head_sha="c2")
        self._turn_marker(report, run_index=3, review_mode=REVIEW_MODE_FULL, head_sha="c3")

        row = self.client.get(self.url).json()["results"][0]
        detail = self.client.get(f"{self.url}{report.id}/").json()

        assert row["review_mode"] == review_mode
        assert detail["review_mode"] == review_mode

    @parameterized.expand(
        [
            (
                "latest_turn_published",
                {"1": "a", "2": "b"},
                99,
                True,
                "https://github.com/PostHog/posthog/pull/1#issuecomment-99",
            ),
            ("only_an_older_turn_published", {"1": "a"}, None, False, None),
            ("never_published", None, None, False, None),
        ]
    )
    def test_turn_published_and_status_comment_url(
        self,
        _name: str,
        published_head_shas: dict[str, str] | None,
        status_comment_id: int | None,
        turn_published: bool,
        status_comment_url: str | None,
    ) -> None:
        # `published` means "ever", so an agent reading a clean re-review would think the new turn posted.
        self._report(
            pr_number=1,
            acting_user=self.user,
            run_count=2,
            published_head_sha="a" if published_head_shas else None,
            published_head_shas=published_head_shas,
            status_comment_id=status_comment_id,
        )

        row = self.client.get(self.url).json()["results"][0]

        assert row["published"] is bool(published_head_shas)
        assert row["turn_published"] is turn_published
        assert row["status_comment_url"] == status_comment_url

    def test_run_index_reads_an_older_completed_turn(self) -> None:
        # The body is stored for the latest turn only, so an older turn must not return it as its own.
        report = self._report(
            pr_number=1,
            acting_user=self.user,
            run_count=2,
            report_markdown="## Turn 2",
            published_head_shas={"1": "c1"},
            published_urgency_thresholds={"1": "consider"},
            run_urgency_threshold="must_fix",
        )
        self._turn_marker(report, run_index=1, review_mode=REVIEW_MODE_FLASH, head_sha="c1")
        self._finding(report, "1-old", priority=IssuePriority.MUST_FIX, run_index=1)
        self._finding(report, "2-new", priority=IssuePriority.CONSIDER, run_index=2)

        latest = self.client.get(f"{self.url}{report.id}/").json()
        older = self.client.get(f"{self.url}{report.id}/", {"run_index": 1}).json()

        assert (latest["run_index"], latest["report_markdown"], latest["turn_published"]) == (2, "## Turn 2", False)
        assert [f["title"] for f in latest["findings"]] == ["title 2-new"]
        assert (older["run_index"], older["report_markdown"], older["turn_published"]) == (1, None, True)
        assert (older["head_sha"], older["review_mode"], older["run_urgency_threshold"]) == ("c1", "flash", "consider")
        assert [f["title"] for f in older["findings"]] == ["title 1-old"]
        assert older["must_fix_count"] == 1
        for out_of_range in (0, 3):
            assert self.client.get(f"{self.url}{report.id}/", {"run_index": out_of_range}).status_code == 404

    def test_lists_only_my_completed_reviews(self) -> None:
        # The default (mine) scope is "your recent reviews": a teammate's report and an abandoned
        # (stale, never completed) run must not appear — a filter regression would leak other users'
        # review activity or show a dead run as forever in progress.
        mine = self._report(pr_number=1, acting_user=self.user)
        with time_machine.travel(timezone.now() - timedelta(hours=2), tick=False):
            self._report(pr_number=2, acting_user=self.user, completed=False)
        other = User.objects.create_and_join(self.organization, "other-reviews@posthog.com", None)
        self._report(pr_number=3, acting_user=other)

        res = self.client.get(self.url)

        assert res.status_code == 200
        assert res.json()["has_more"] is False
        rows = res.json()["results"]
        assert [r["pr_number"] for r in rows] == [1]
        assert rows[0]["github_url"] == mine.pr_url
        assert rows[0]["published"] is False
        assert "perspective_selection" not in rows[0]  # detail-only payload — the list stays lean

    def test_full_review_published_reads_only_the_full_marker(self) -> None:
        self._report(pr_number=1, acting_user=self.user, published_head_sha="a", published_heads_by_mode={"flash": "a"})
        self._report(pr_number=2, acting_user=self.user, published_head_sha="b", published_heads_by_mode={"full": "b"})

        rows = {row["pr_number"]: row for row in self.client.get(self.url).json()["results"]}

        assert rows[1]["full_review_published"] is False
        assert rows[2]["full_review_published"] is True

    def test_mine_scope_includes_reviews_of_prs_i_authored(self) -> None:
        # The incident this guards: a review a teammate triggers on your PR lands under THEIR
        # acting_user, so without the author_login match it never reaches your "For you" tab — the
        # findings are effectively invisible to you. The match rides the viewer's linked GitHub
        # login (case-insensitively); without a linked login the old acting-user-only behavior holds.
        other = User.objects.create_and_join(self.organization, "other-author-scope@posthog.com", None)
        self._report(pr_number=1, acting_user=other, author_login="OctoCat")
        self._report(pr_number=2, acting_user=other, author_login="someone-else")
        self._report(pr_number=3, acting_user=self.user)

        # No linked GitHub identity: only reviews where I'm the acting user.
        assert {r["pr_number"] for r in self.client.get(self.url).json()["results"]} == {3}

        # Linked identity (stored casing differs from the stamped login): authored PRs join the
        # scope — for the list AND the perspective_stats aggregation, which share the filter.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-1", extra_data={"login": "octocat"})
        assert {r["pr_number"] for r in self.client.get(self.url).json()["results"]} == {1, 3}
        assert self.client.get(f"{self.url}perspective_stats/").json()["report_count"] == 2

    def test_list_scope_everyone_covers_the_whole_project(self) -> None:
        # The "Entire project" switch: everyone-scope must include teammates' reviews but never
        # another team's (tenant isolation), and a bad scope value must 400 — proving the params
        # serializer is actually wired into the view.
        self._report(pr_number=1, acting_user=self.user)
        other = User.objects.create_and_join(self.organization, "other-everyone@posthog.com", None)
        self._report(pr_number=2, acting_user=other)
        cold_team = Team.objects.create(organization=self.organization, name="cold")
        self._report(pr_number=3, acting_user=other, team_id=cold_team.id)

        res = self.client.get(self.url, {"scope": "everyone"})

        assert res.status_code == 200
        assert {r["pr_number"] for r in res.json()["results"]} == {1, 2}
        assert self.client.get(self.url, {"scope": "nonsense"}).status_code == 400

    @parameterized.expand(
        [
            ("review_hog_read_allowed", ["review_hog:read"], 200),
            ("unrelated_scope_denied", ["insight:read"], 403),
        ]
    )
    def test_list_api_key_scope_is_review_hog(self, _name: str, scopes: list[str], expected_status: int) -> None:
        # The list/get/trigger endpoints carry the `review_hog` scope so the MCP tools reach them with a
        # personal API key or OAuth token — a revert to INTERNAL would reject the read-scoped key here and
        # take the MCP review tools down with it.
        self._report(pr_number=1, acting_user=self.user)
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        res = self.client.get(self.url)

        assert res.status_code == expected_status

    def test_list_limit_grows_the_page_and_has_more_flags_the_rest(self) -> None:
        # "Show more" grows `limit` instead of offset-paging. has_more must flip false exactly when
        # the page covers everything (off-by-one here strands or dead-ends the button), and
        # out-of-range limits must 400 — proving the field is wired into the params serializer.
        for pr_number in range(1, 8):
            self._report(pr_number=pr_number, acting_user=self.user)

        default_page = self.client.get(self.url).json()
        assert len(default_page["results"]) == 5
        assert default_page["has_more"] is True

        full_page = self.client.get(self.url, {"limit": 7}).json()
        assert len(full_page["results"]) == 7
        assert full_page["has_more"] is False

        assert self.client.get(self.url, {"limit": 0}).status_code == 400
        assert self.client.get(self.url, {"limit": 101}).status_code == 400

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
        row = res.json()["results"][0]
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
            review_design=REVIEW_DESIGN_SINGLE_AGENT,
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
            review_arm=DEFAULT_REVIEW_ARM,
        )
        persist_perspective_results(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="new-sha",
            results={(1, 1): _issues_review(2), (2, 1): _issues_review(1), (1000, 1): _issues_review(1)},
            review_arm=DEFAULT_REVIEW_ARM,
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
        row = res.json()["results"][0]
        assert row["pr_title"] == "feat: current title"
        assert row["pr_author"] == "skoob13"
        assert (row["additions"], row["deletions"], row["changed_files"]) == (120, 8, 7)
        assert row["files_reviewed"] == 2
        assert row["chunk_count"] == 2
        assert (row["perspective_count"], row["perspective_issue_count"], row["blind_spot_issue_count"]) == (2, 3, 1)
        assert (row["candidate_count"], row["dismissed_count"]) == (3, 1)
        assert "perspective_selection" not in row
        # The old-sha snapshot ran the pipeline; only the reviewed head's design may reach the row.
        assert row["review_design"] == REVIEW_DESIGN_SINGLE_AGENT

        # The detail exposes the head-matched selection per chunk (stale-head one filtered out),
        # joined with the chunk set's files, with skipped lenses computed against the roster.
        detail = self.client.get(f"{self.url}{report.id}/").json()
        assert detail["review_design"] == REVIEW_DESIGN_SINGLE_AGENT
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
        # dismissed ones separately, unjudged ones in neither, the published body verbatim, and the
        # run's stored threshold (what the drawer buckets by — the viewer's setting is only a
        # fallback for pre-column rows).
        report = self._report(
            pr_number=7, acting_user=self.user, report_markdown="## Review body", run_urgency_threshold="should_fix"
        )
        self._finding(report, "1-low", priority=IssuePriority.CONSIDER)
        self._finding(report, "1-high", priority=IssuePriority.MUST_FIX, adjusted=IssuePriority.SHOULD_FIX)
        self._finding(report, "1-noise", priority=IssuePriority.SHOULD_FIX, is_valid=False)
        self._finding(report, "1-unjudged", priority=IssuePriority.MUST_FIX, judged=False)

        res = self.client.get(f"{self.url}{report.id}/")

        assert res.status_code == 200
        detail = res.json()
        assert detail["report_markdown"] == "## Review body"
        assert detail["run_urgency_threshold"] == "should_fix"
        assert [f["title"] for f in detail["findings"]] == ["title 1-high", "title 1-low"]
        high = detail["findings"][0]
        assert (high["effective_priority"], high["reviewer_priority"]) == ("should_fix", "must_fix")
        assert high["lines"] == [{"start": 10, "end": 20}]
        assert high["validator_note"] == "a"
        assert [f["title"] for f in detail["dismissed_findings"]] == ["title 1-noise"]
        assert detail["perspective_selection"] is None  # no selection artefact → the drawer tab shows its empty state

    def _dropped(
        self,
        report: ReviewReport,
        title: str,
        *,
        run_index: int,
        disposition: DropDisposition,
        duplicate_of: str | None = None,
        rank: int | None = None,
    ) -> None:
        ReviewReportArtefact.append_dropped_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=DroppedFindingArtefact(
                head_sha="c",
                finding=ReviewIssueFinding(
                    issue_key=f"{run_index}-{title}",
                    run_index=run_index,
                    title=title,
                    file="f.py",
                    lines=[LineRange(start=3, end=4)],
                    body="b",
                    suggestion="",
                    priority=IssuePriority.CONSIDER,
                    source_perspective="main",
                ),
                pass_number=2000,
                chunk_id=1,
                disposition=disposition,
                duplicate_of=duplicate_of,
                rank=rank,
                cap=5,
                lens_part_count=1,
            ),
            attribution=ArtefactAttribution.system(),
        )

    @parameterized.expand(
        [
            ("old_code", None, None, None),
            ("dedup_prior", "1-f.py-10-main-1", None, None),
            ("dedup_comment", "comment:42", None, "https://github.com/PostHog/posthog/pull/7#discussion_r42"),
            ("dedup_anchor", "2-f.py-3-main-1", None, None),
            ("dedup_sibling", "2-f.py-3-lens-1", None, None),
            ("cap", None, 6, None),
        ]
    )
    def test_retrieve_returns_the_turns_dropped_findings(
        self,
        disposition: DropDisposition,
        duplicate_of: str | None,
        rank: int | None,
        comment_url: str | None,
    ) -> None:
        # Each turn shows only its own drops, and every recorded disposition must map to a served choice.
        report = self._report(pr_number=7, acting_user=self.user, run_count=2)
        self._dropped(report, "older drop", run_index=1, disposition="cap", rank=9)
        self._dropped(report, "latest drop", run_index=2, disposition=disposition, duplicate_of=duplicate_of, rank=rank)

        latest = self.client.get(f"{self.url}{report.id}/").json()
        older = self.client.get(f"{self.url}{report.id}/", {"run_index": 1}).json()

        assert latest["dropped_findings"] == [
            {
                "title": "latest drop",
                "file": "f.py",
                "lines": [{"start": 3, "end": 4}],
                "body": "b",
                "suggestion": "",
                "priority": "consider",
                "source_perspective": "main",
                "disposition": disposition,
                "duplicate_of": duplicate_of,
                "comment_url": comment_url,
                "rank": rank,
            }
        ]
        assert [(f["title"], f["rank"]) for f in older["dropped_findings"]] == [("older drop", 9)]

    def test_in_progress_review_surfaces_with_stage_progress(self) -> None:
        # A visibly running first-turn review must appear first with a stage inferred from the
        # working state (fetching → chunking → selecting → reviewing n/m → deduplicating →
        # validating n/m → finalizing); completed rows never carry progress.
        self._report(pr_number=1, acting_user=self.user)
        running = self._report(pr_number=2, acting_user=self.user, completed=False, run_count=0, head_sha="sha1")
        running_id = str(running.id)

        rows = self.client.get(self.url).json()["results"]
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
        assert self.client.get(self.url).json()["results"][0]["progress"]["review_stage"] == "chunking"

        persist_chunk_set(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            chunks=ChunksList(chunks=[Chunk(chunk_id=i, files=[FileInfo(filename="a.py")]) for i in range(2)]),
        )
        # A chunked turn with no reads and no plan yet is the selector's window.
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "selecting",
            "done": None,
            "total": None,
        }

        persist_perspective_results(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            results={(1, 1): _issues_review(1), (2, 1): _issues_review(0)},
            review_arm=DEFAULT_REVIEW_ARM,
        )
        # No persisted plan (a fallback run): the dense estimate — 2 chunks × (3 canonical
        # perspectives + the blind-spot sweep) = 8 expected reads.
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "reviewing",
            "done": 2,
            "total": 8,
        }

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
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "reviewing",
            "done": 2,
            "total": 3,
        }

        # All planned reads in (1 selected wave unit + 2 blind spots = 3) → the dedup window.
        persist_perspective_results(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            results={(1000, 0): _issues_review(0)},
            review_arm=DEFAULT_REVIEW_ARM,
        )
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "deduplicating",
            "done": 3,
            "total": 3,
        }

        self._finding(running, "1-a", priority=IssuePriority.MUST_FIX)
        self._finding(running, "1-b", priority=IssuePriority.CONSIDER, judged=False)
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "validating",
            "done": 1,
            "total": 2,
        }

        # Every finding judged → the turn is building + publishing, the moments before it completes.
        self._finding(running, "1-b", priority=IssuePriority.CONSIDER, is_valid=False)
        assert self.client.get(self.url).json()["results"][0]["progress"] == {
            "review_stage": "finalizing",
            "done": 2,
            "total": 2,
        }

    def test_single_agent_turn_reports_its_own_stages(self) -> None:
        running = self._report(pr_number=2, acting_user=self.user, completed=False, run_count=0, head_sha="sha1")
        running_id = str(running.id)

        def stage() -> dict:
            return self.client.get(self.url).json()["results"][0]["progress"]

        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=running_id,
            head_sha="sha1",
            pr_metadata=_pr_metadata("sha1", "in flight"),
            pr_comments=[],
            pr_files=[],
            review_design=REVIEW_DESIGN_SINGLE_AGENT,
        )
        assert stage() == {"review_stage": "single_agent_preparing", "done": None, "total": None}

        ReviewReportArtefact.add_turn_marker(
            team_id=self.team.id,
            report_id=running_id,
            content=TurnMarkerArtefact(
                head_sha="sha1",
                run_index=1,
                review_mode=REVIEW_MODE_FLASH,
                reviewhog_version="v",
                reviewhog_fingerprint="f",
            ),
            attribution=ArtefactAttribution.system(),
        )
        assert stage() == {"review_stage": "single_agent_reviewing", "done": None, "total": None}

        self._finding(running, "1-a", priority=IssuePriority.MUST_FIX)
        assert stage() == {"review_stage": "single_agent_finalizing", "done": None, "total": None}

    @parameterized.expand(
        [
            ("active", "sha1", False, True),
            ("idle", "sha1", False, False),
            ("active", "another-head", False, False),
            ("active", "sha1", True, False),
        ]
    )
    def test_activity_heartbeat_keeps_only_its_active_review_visible(
        self, status: str, heartbeat_head: str, another_team: bool, visible: bool
    ) -> None:
        now = timezone.now()
        with time_machine.travel(now - IN_PROGRESS_STALE_AFTER - timedelta(minutes=1), tick=False):
            running = self._report(
                pr_number=2, acting_user=self.user, completed=False, run_count=0, head_sha="sha1", status=status
            )
        heartbeat_team_id = self.team.id
        if another_team:
            heartbeat_team_id = Team.objects.create(organization=self.organization, name="another project").id
        heartbeat = ReviewActivityHeartbeater(
            team_id=heartbeat_team_id, report_id=str(running.id), head_sha=heartbeat_head
        )

        with time_machine.travel(now, tick=False):
            assert self.client.get(self.url).json()["results"] == []
            before_pulse = running.updated_at
            heartbeat.touch_report()
            running.refresh_from_db()
            assert running.updated_at == (now if visible else before_pulse)
            rows = self.client.get(self.url).json()["results"]
            assert bool(rows) is visible
            if visible:
                assert rows[0]["pr_number"] == 2
                assert rows[0]["in_progress"] is True
                assert rows[0]["run_count"] == 0

        with time_machine.travel(now + IN_PROGRESS_STALE_AFTER + timedelta(seconds=1), tick=False):
            assert self.client.get(self.url).json()["results"] == []

    def test_heartbeating_first_turn_outranks_newer_stale_first_turns(self) -> None:
        # Crashed first turns stay ACTIVE. More of them than the probe slice, all newer than a live
        # run, must not push that live run out of the list.
        now = timezone.now()
        with time_machine.travel(now - timedelta(hours=2), tick=False):
            live = self._report(pr_number=1, acting_user=self.user, completed=False, run_count=0, head_sha="sha1")
        with time_machine.travel(now - IN_PROGRESS_STALE_AFTER - timedelta(minutes=1), tick=False):
            for pr_number in range(2, 5):
                self._report(pr_number=pr_number, acting_user=self.user, completed=False, run_count=0)

        with time_machine.travel(now, tick=False):
            ReviewActivityHeartbeater(team_id=self.team.id, report_id=str(live.id), head_sha="sha1").touch_report()
            rows = self.client.get(self.url, {"limit": 1}).json()["results"]

        assert [(row["pr_number"], row["in_progress"]) for row in rows] == [(1, True)]

    def _resolution_run(self, report: ReviewReport, thread_ids: list[str], *, skipped: int = 0) -> None:
        ReviewReportArtefact.append_resolution_run(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ResolutionRunArtefact(total=len(thread_ids), thread_ids=thread_ids, skipped=skipped),
            attribution=ArtefactAttribution.system(),
        )

    def _thread_verdict(
        self,
        report: ReviewReport,
        thread_id: str,
        outcome: str,
        *,
        delivered: bool = True,
        commit_sha: str | None = None,
        commit_verified: bool | None = None,
        commit_restricted: bool | None = None,
    ) -> None:
        ReviewReportArtefact.append_thread_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ThreadVerdictArtefact(
                thread_id=thread_id,
                outcome=outcome,
                reasoning="r",
                reply="reply",
                reply_posted=delivered,
                commit_sha=commit_sha,
                commit_verified=commit_verified,
                commit_restricted=commit_restricted,
            ),
            attribution=ArtefactAttribution.system(),
        )

    def _closing_run_note(self, report: ReviewReport) -> None:
        ReviewReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note="Resolution run on PR #5: done", author=RESOLUTION_RUN_NOTE_AUTHOR),
            attribution=ArtefactAttribution.system(),
        )

    def test_resolving_report_shows_resolution_progress_not_a_review_stage(self) -> None:
        # The prod mislabel this feature fixes: a chained resolution kept the report ACTIVE with
        # fresh artefacts, so the row inferred a review stage from the COMPLETED turn's working
        # state and rendered "Re-reviewing · Merging overlapping findings". A resolving report must
        # carry resolution progress instead, counting only this run's queued threads — not a
        # redelivered foreign verdict, not a previous run's verdict for a re-queued thread, and not
        # a judged thread whose GitHub writes haven't landed.
        report = self._report(pr_number=5, acting_user=self.user, status=ReviewReport.Status.ACTIVE)
        with time_machine.travel(timezone.now() - timedelta(hours=1), tick=False):
            # A previous run already judged PRRT_3; a new comment re-queued it, so only a verdict
            # written during THIS run may count toward its progress.
            self._thread_verdict(report, "PRRT_3", "fixed")
        self._resolution_run(report, ["PRRT_1", "PRRT_2", "PRRT_3"])
        self._thread_verdict(report, "PRRT_1", "fixed")
        self._thread_verdict(report, "PRRT_2", "escalate")
        # A prior run's redelivery (thread not queued this run) also appends a row mid-run.
        self._thread_verdict(report, "PRRT_X", "fixed")
        # Judged but its GitHub reply failed — no reply on the thread yet, so it must not count.
        self._thread_verdict(report, "PRRT_3", "fixed", delivered=False)

        row = self.client.get(self.url).json()["results"][0]

        assert row["in_progress"] is True
        assert row["progress"] is None
        assert row["resolution"] == {
            "resolution_status": "resolving",
            "done": 2,
            "total": 3,
            "fixed": 1,
            "needs_attention": 1,
        }

    @parameterized.expand(
        [
            ("completed_run_via_closing_note", "completed"),
            ("superseded_by_newer_review_turn", "stopped"),
        ]
    )
    def test_finished_or_superseded_resolution_carries_no_state(self, scenario: str, latest_status: str) -> None:
        # A completed run must not render as crashed once it ages past the staleness window (the
        # closing note is the completion marker), and a crashed run must yield the row to a newer
        # review turn's own progress instead of pinning a stale "didn't finish" on it.
        report = self._report(pr_number=5, acting_user=self.user, status=ReviewReport.Status.ACTIVE, head_sha="sha1")
        with time_machine.travel(timezone.now() - timedelta(hours=2), tick=False):
            self._resolution_run(report, ["PRRT_1"])
            self._thread_verdict(report, "PRRT_1", "fixed")
            if scenario == "completed_run_via_closing_note":
                self._closing_run_note(report)
        if scenario == "superseded_by_newer_review_turn":
            persist_pr_snapshot(
                team_id=self.team.id,
                report_id=str(report.id),
                head_sha="sha1",
                pr_metadata=_pr_metadata("sha1", "next turn"),
                pr_comments=[],
                pr_files=[],
            )

        row = self.client.get(self.url).json()["results"][0]

        assert row["resolution"] is None
        # The agent-facing summary keeps the finished run, so a caller can still read what it did.
        assert (row["latest_resolution"]["status"], row["latest_resolution"]["fixed"]) == (latest_status, 1)
        assert (row["latest_resolution"]["completed_at"] is not None) is (latest_status == "completed")

    def test_completed_resolution_lists_only_commits_the_replies_link(self) -> None:
        # A fix commit that failed branch verification or touches protected files gets no public link
        # on GitHub, so the API must not hand its SHA to an agent as a trusted fix either.
        report = self._report(pr_number=5, acting_user=self.user)
        self._resolution_run(report, ["PRRT_1", "PRRT_2", "PRRT_3", "PRRT_4", "PRRT_5"])
        self._thread_verdict(report, "PRRT_1", "fixed", commit_sha="good", commit_verified=True)
        self._thread_verdict(report, "PRRT_2", "fixed", commit_sha="unverified", commit_verified=False)
        self._thread_verdict(
            report, "PRRT_3", "fixed", commit_sha="restricted", commit_verified=True, commit_restricted=True
        )
        self._thread_verdict(report, "PRRT_4", "fixed", commit_sha="unchecked")
        self._thread_verdict(report, "PRRT_5", "escalate")
        self._closing_run_note(report)

        detail = self.client.get(f"{self.url}{report.id}/").json()

        assert detail["resolution"] is None
        latest = detail["latest_resolution"]
        assert (latest["status"], latest["total"], latest["fixed"], latest["needs_attention"]) == ("completed", 5, 4, 1)
        assert latest["commits"] == ["good"]

    @parameterized.expand(
        [
            ("no_later_activity", None, "stopped", 1),
            ("later_run_outcome_note", "outcome_note", "stopped", 1),
            ("later_thread_verdict", "thread_verdict", "resolving", 2),
        ]
    )
    def test_dead_resolution_run_shows_where_it_stopped(
        self, _name: str, later_write: str | None, expected_status: str, expected_done: int
    ) -> None:
        # The silent-death mode: a resolution that dies partway used to leave no trace anywhere.
        # With the run anchor present, no closing note, and activity past the staleness window, the
        # row must say where it stopped instead of nothing. A later run outcome note records that a
        # run ended, so it must not count as activity that revives the dead run. A fresh verdict is
        # real activity, so that run is still resolving.
        with time_machine.travel(timezone.now() - timedelta(hours=2), tick=False):
            report = self._report(pr_number=5, acting_user=self.user, status=ReviewReport.Status.IDLE)
            self._resolution_run(report, ["PRRT_1", "PRRT_2", "PRRT_3"])
            self._thread_verdict(report, "PRRT_1", "fixed")
        if later_write == "outcome_note":
            record_run_outcome(
                self.team.id, str(report.id), stage="resolution", outcome="skipped", reason="no_unresolved_threads"
            )
        elif later_write == "thread_verdict":
            self._thread_verdict(report, "PRRT_2", "fixed")

        row = self.client.get(self.url).json()["results"][0]

        assert row["in_progress"] is (expected_status == "resolving")
        assert row["resolution"] == {
            "resolution_status": expected_status,
            "done": expected_done,
            "total": 3,
            "fixed": expected_done,
            "needs_attention": 0,
        }

    def test_publish_window_stays_in_progress_and_reads_finalizing(self) -> None:
        # On publishing runs finalize bumps run_count but defers the idle write to the publish
        # stage, so the report is briefly ACTIVE with no in-flight findings. The row must keep
        # reading in-progress ("finalizing", not a misread of the finished turn's working state as
        # "deduplicating"), so the UI's poll survives until the published flag is real.
        report = self._report(
            pr_number=3,
            acting_user=self.user,
            status=ReviewReport.Status.ACTIVE,
            head_sha="sha1",
            completed_head_sha="sha1",
        )

        row = self.client.get(self.url).json()["results"][0]
        assert row["pr_number"] == 3
        assert row["in_progress"] is True
        assert row["published"] is False
        assert row["progress"] == {"review_stage": "finalizing", "done": None, "total": None}

        # A resolution run holds the same ACTIVE-at-completed-head shape but with the head already
        # published — that window keeps its pre-existing label until the run's `resolution_run`
        # artefact lands, at which point the row carries `resolution` instead.
        ReviewReport.objects.for_team(self.team.id).filter(id=report.id).update(published_head_sha="sha1")
        row = self.client.get(self.url).json()["results"][0]
        assert row["in_progress"] is True
        assert row["progress"]["review_stage"] != "finalizing"

    def test_row_and_detail_anchor_to_the_completed_turn_during_a_re_review(self) -> None:
        # A re-review advances the live head_sha at turn START while run_count still points at the
        # previous turn — row stats and the detail's link-anchoring head must describe the COMPLETED
        # turn (same one as the findings), not splice in the in-flight commit's metadata. Only the
        # progress payload reads the live head.
        report = self._report(
            pr_number=5,
            acting_user=self.user,
            status=ReviewReport.Status.ACTIVE,
            head_sha="def",
            completed_head_sha="abc",
        )
        report_id = str(report.id)
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="abc",
            pr_metadata=_pr_metadata("abc", "completed title"),
            pr_comments=[],
            pr_files=[],
        )
        persist_chunk_set(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="abc",
            chunks=ChunksList(chunks=[Chunk(chunk_id=i, files=[FileInfo(filename="a.py")]) for i in range(3)]),
        )
        self._finding(report, "1-a", priority=IssuePriority.MUST_FIX)
        # The in-flight turn's snapshot at the new head — must not leak into the row/detail payload.
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="def",
            pr_metadata=_pr_metadata("def", "in flight title"),
            pr_comments=[],
            pr_files=[],
        )

        row = self.client.get(self.url).json()["results"][0]
        assert (row["pr_title"], row["chunk_count"], row["must_fix_count"]) == ("completed title", 3, 1)
        assert row["in_progress"] is True
        assert row["progress"]["review_stage"] == "chunking"  # live head: snapshot yes, chunks not yet

        detail = self.client.get(f"{self.url}{report_id}/").json()
        assert detail["head_sha"] == "abc"
        assert detail["pr_title"] == "completed title"
        # The detail must report the running re-review like the row does, not read as idle.
        assert detail["in_progress"] is True
        assert detail["progress"] == row["progress"]

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

        rows = self.client.get(self.url).json()["results"]

        assert len(rows) == 5
        assert rows[0]["pr_number"] == 99
        assert rows[0]["in_progress"] is True
        assert {r["pr_number"] for r in rows[1:]} <= set(range(1, 6))

    @parameterized.expand([("finding_outcome", False), ("turn_artefact", True)])
    def test_only_turn_artefacts_keep_the_in_progress_spinner(self, later_write: str, expected: bool) -> None:
        # `finding_outcome` is the one artefact written outside a turn: the sweep appends it after the
        # PR merges, which can be long after the run ended. Status only leaves ACTIVE on a successful
        # finalize, so a run that crashed before finalize stays ACTIVE forever and the staleness
        # window is the only thing that retires its spinner. Counting the sweep's write as liveness
        # would restart that window and show a live row for a report with nothing running. A fresh
        # turn-written artefact is real progress and must still keep the row live.
        # ACTIVE with a completed turn behind it (the dormant re-review shape): a first-turn ACTIVE
        # report is listed only while it is in progress, so it could not show the difference.
        report = self._report(pr_number=7, acting_user=self.user, status=ReviewReport.Status.ACTIVE)
        ReviewReport.objects.for_team(self.team.id).filter(id=report.id).update(
            updated_at=timezone.now() - IN_PROGRESS_STALE_AFTER - timedelta(minutes=5)
        )
        if later_write == "finding_outcome":
            ReviewReportArtefact.add_finding_outcome(
                team_id=self.team.id,
                report_id=str(report.id),
                content=FindingOutcomeArtefact(
                    issue_key="r1:f.py:10:logic",
                    run_index=1,
                    outcome="ignored",
                    method="no_signal",
                    reviewed_head="base_sha",
                    final_head="head_sha",
                ),
                attribution=ArtefactAttribution.system(),
            )
        else:
            self._thread_verdict(report, "PRRT_1", "fixed")

        row = next(r for r in self.client.get(self.url).json()["results"] if r["pr_number"] == 7)
        assert row["in_progress"] is expected

    def test_perspective_stats_aggregate_latest_turns_per_scope(self) -> None:
        # Effectiveness must aggregate each report's LATEST turn only and, on the default scope,
        # never mix in a teammate's reviews — stale turns or foreign reports would inflate a
        # perspective's record.
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

        # scope=everyone folds the teammate's reviews in — the page-level "Entire project" switch;
        # a filter regression here would keep project-wide stats silently personal.
        res = self.client.get(f"{self.url}perspective_stats/?scope=everyone")

        assert res.status_code == 200
        data = res.json()
        assert data["report_count"] == 3
        assert data["perspectives"] == [
            {"skill_name": blind, "raised": 2, "kept": 2, "dismissed": 0},
            {"skill_name": logic, "raised": 2, "kept": 1, "dismissed": 1},
        ]
        assert self.client.get(f"{self.url}perspective_stats/?scope=everything").status_code == 400

        # The settings read own_deep: a Standard turn reads none of the user's skills, and a teammate's
        # Deep review uses the teammate's skills, so neither may count.
        standard = self._report(pr_number=4, acting_user=self.user)
        self._finding(standard, "1-s", priority=IssuePriority.MUST_FIX, perspective=logic, review_mode="flash")
        ReviewReport.objects.for_team(self.team.id).filter(id=standard.id).update(
            last_run_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        # A clean Standard turn has no findings to carry its mode, so only the publish watermark tells.
        # It is the newest report, and it must not take a slot from the Deep reviews under the report limit.
        clean_standard = self._report(
            pr_number=5, acting_user=self.user, head_sha="c1ea2", published_heads_by_mode={"flash": "c1ea2"}
        )
        ReviewReport.objects.for_team(self.team.id).filter(id=clean_standard.id).update(
            last_run_at=datetime(2026, 8, 1, tzinfo=UTC)
        )

        with patch("products.review_hog.backend.api.reviews.PERSPECTIVE_STATS_REPORT_LIMIT", 2):
            res = self.client.get(f"{self.url}perspective_stats/?scope=own_deep")

        assert res.status_code == 200
        data = res.json()
        assert data["report_count"] == 2
        assert data["perspectives"] == [
            {"skill_name": logic, "raised": 2, "kept": 1, "dismissed": 1},
            {"skill_name": blind, "raised": 1, "kept": 1, "dismissed": 0},
        ]

    def test_retrieve_is_project_wide_but_never_cross_team(self) -> None:
        # Opening a teammate's review from the everyone-scope list must work, but another team's
        # report id must still 404 (tenant isolation), and garbage ids must not 500.
        other = User.objects.create_and_join(self.organization, "other-reviews-detail@posthog.com", None)
        theirs = self._report(pr_number=9, acting_user=other)
        cold_team = Team.objects.create(organization=self.organization, name="cold")
        foreign = self._report(pr_number=10, acting_user=other, team_id=cold_team.id)

        assert self.client.get(f"{self.url}{theirs.id}/").status_code == 200
        assert self.client.get(f"{self.url}{foreign.id}/").status_code == 404
        assert self.client.get(f"{self.url}not-a-uuid/").status_code == 404
