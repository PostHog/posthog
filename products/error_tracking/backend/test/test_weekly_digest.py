from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models.utils import uuid7

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2
from products.error_tracking.backend.weekly_digest import (
    get_crash_free_sessions,
    get_daily_exception_counts,
    get_exception_counts,
    get_new_issues_for_team,
    get_top_issues_for_team,
)

from ee.clickhouse.materialized_columns.columns import materialize


def _days_ago(n: int) -> str:
    return (timezone.now() - timedelta(days=n)).isoformat()


class TestWeeklyDigest(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    def _create_issue(self, name: str = "TestError", description: str = "something broke") -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(),
            team=self.team,
            status=ErrorTrackingIssue.Status.ACTIVE,
            name=name,
            description=description,
        )
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team,
            issue=issue,
            fingerprint=str(uuid4()),
        )
        return issue

    def _create_exception_event(
        self,
        issue_id: str | None = None,
        distinct_id: str = "user_1",
        timestamp: str | None = None,
        session_id: str | None = None,
    ) -> None:
        props: dict = {}
        if issue_id:
            props["$exception_issue_id"] = str(issue_id)
        if session_id:
            props["$session_id"] = session_id

        _create_event(
            distinct_id=distinct_id,
            event="$exception",
            team=self.team,
            properties=props,
            timestamp=timestamp or _days_ago(1),
        )

    def _create_pageview(
        self,
        distinct_id: str = "user_1",
        timestamp: str | None = None,
        session_id: str | None = None,
    ) -> None:
        props: dict = {}
        if session_id:
            props["$session_id"] = session_id

        _create_event(
            distinct_id=distinct_id,
            event="$pageview",
            team=self.team,
            properties=props,
            timestamp=timestamp or _days_ago(1),
        )

    def test_get_exception_counts_returns_counts_per_team(self):
        issue = self._create_issue()
        for _ in range(3):
            self._create_exception_event(issue_id=issue.id)
        self._create_exception_event(issue_id=None)
        flush_persons_and_events()

        results = get_exception_counts(team_ids=[self.team.pk])

        assert len(results) == 1
        team_id, exception_count, ingestion_failure_count = results[0]
        assert team_id == self.team.pk
        assert exception_count == 4
        assert ingestion_failure_count == 1

    def test_get_exception_counts_excludes_old_events(self):
        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(10))
        flush_persons_and_events()

        results = get_exception_counts(team_ids=[self.team.pk])
        assert results == []

    def test_get_crash_free_sessions(self):
        s1, s2, s3 = str(uuid7()), str(uuid7()), str(uuid7())
        self._create_pageview(session_id=s1)
        self._create_pageview(session_id=s2)
        self._create_pageview(session_id=s3)
        self._create_exception_event(session_id=s3)
        flush_persons_and_events()

        result = get_crash_free_sessions(self.team)

        assert result["total_sessions"] == 3
        assert result["crash_sessions"] == 1
        assert result["crash_free_rate"] == 66.67

    def test_get_crash_free_sessions_empty_when_no_sessions(self):
        result = get_crash_free_sessions(self.team)
        assert result == {}

    def test_get_daily_exception_counts_returns_7_days(self):
        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(3))
        flush_persons_and_events()

        result = get_daily_exception_counts(self.team.pk)

        assert len(result) == 7

        today = timezone.now().date()
        day_1_ago = (today - timedelta(days=1)).strftime("%a")
        day_3_ago = (today - timedelta(days=3)).strftime("%a")

        counts = {d["day"]: d["count"] for d in result}
        assert counts[day_1_ago] == 2
        assert counts[day_3_ago] == 1

        pcts = {d["day"]: d["height_percent"] for d in result}
        assert pcts[day_1_ago] == 100
        assert pcts[day_3_ago] == 50

    def test_get_daily_exception_counts_empty(self):
        result = get_daily_exception_counts(self.team.pk)

        assert len(result) == 7
        assert all(d["count"] == 0 for d in result)

    def test_get_top_issues_for_team(self):
        issue_a = self._create_issue(name="FrequentError", description="happens a lot")
        issue_b = self._create_issue(name="RareError", description="happens rarely")

        for _ in range(5):
            self._create_exception_event(issue_id=issue_a.id)
        for _ in range(2):
            self._create_exception_event(issue_id=issue_b.id)
        flush_persons_and_events()

        result = get_top_issues_for_team(self.team)

        assert len(result) == 2
        assert result[0]["name"] == "FrequentError"
        assert result[0]["occurrence_count"] == 5
        assert result[1]["name"] == "RareError"
        assert result[1]["occurrence_count"] == 2
        assert "/error_tracking/" in result[0]["url"]

    def test_get_top_issues_sparkline_is_chronological(self):
        issue = self._create_issue(name="SparklineTest")
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(5))
        for _ in range(3):
            self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(3))
        for _ in range(2):
            self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        flush_persons_and_events()

        result = get_top_issues_for_team(self.team)

        assert len(result) == 1
        sparkline = result[0]["sparkline"]
        heights = [bar["height_percent"] for bar in sparkline]
        # day -5 had 1 event, day -3 had 3 (max), day -1 had 2; others had 0
        # chronological order means the peak (100) must come after the first nonzero value
        nonzero = [(i, h) for i, h in enumerate(heights) if h > 0]
        assert len(nonzero) == 3
        assert nonzero[0][0] < nonzero[1][0] < nonzero[2][0]
        assert nonzero[1][1] == 100  # day -3 is the max

    def test_get_top_issues_limits_to_5(self):
        for i in range(7):
            issue = self._create_issue(name=f"Error{i}")
            self._create_exception_event(issue_id=issue.id)
        flush_persons_and_events()

        result = get_top_issues_for_team(self.team)
        assert len(result) == 5

    def test_get_new_issues_for_team(self):
        new_issue = self._create_issue(name="NewBug")
        for _ in range(3):
            self._create_exception_event(issue_id=new_issue.id)

        old_issue = ErrorTrackingIssue.objects.create(
            id=uuid7(),
            team=self.team,
            status=ErrorTrackingIssue.Status.ACTIVE,
            name="OldBug",
        )
        ErrorTrackingIssue.objects.filter(id=old_issue.id).update(created_at=timezone.now() - timedelta(days=14))
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=old_issue, fingerprint=str(uuid4()))
        for _ in range(10):
            self._create_exception_event(issue_id=old_issue.id)
        flush_persons_and_events()

        result = get_new_issues_for_team(self.team)

        names = [r["name"] for r in result]
        assert "NewBug" in names
        assert "OldBug" not in names

    def test_get_new_issues_empty_when_none(self):
        result = get_new_issues_for_team(self.team)
        assert result == []
