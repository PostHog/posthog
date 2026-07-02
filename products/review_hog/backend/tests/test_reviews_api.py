from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from posthog.models import User

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.signals.backend.artefact_attribution import ArtefactAttribution


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
    ) -> None:
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ReviewIssueFinding(
                issue_key=key, run_index=run_index, title="t", file="f.py", body="b", suggestion="s", priority=priority
            ),
            attribution=ArtefactAttribution.system(),
        )
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ValidationVerdict(issue_key=key, is_valid=is_valid, argumentation="a", adjusted_priority=adjusted),
            attribution=ArtefactAttribution.system(),
        )

    def test_lists_only_my_completed_reviews(self) -> None:
        # The block is "your recent reviews": a teammate's report and a report with no completed turn
        # must not appear — a filter regression would leak other users' review activity into the list.
        mine = self._report(pr_number=1, acting_user=self.user)
        self._report(pr_number=2, acting_user=self.user, completed=False)
        other = User.objects.create_and_join(self.organization, "other-reviews@posthog.com", None)
        self._report(pr_number=3, acting_user=other)

        res = self.client.get(self.url)

        assert res.status_code == 200
        rows = res.json()
        assert [r["pr_number"] for r in rows] == [1]
        assert rows[0]["github_url"] == mine.pr_url
        assert rows[0]["published"] is False

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
