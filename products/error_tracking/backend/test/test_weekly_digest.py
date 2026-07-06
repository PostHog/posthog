import json
from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests
from parameterized import parameterized

from posthog.models import Team
from posthog.models.organization import Organization
from posthog.models.utils import uuid7
from posthog.tasks.email import send_error_tracking_weekly_digest_for_org
from posthog.tasks.email_utils import compute_week_over_week_change

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRecommendation,
)
from products.error_tracking.backend.weekly_digest import (
    auto_select_project_for_user,
    get_crash_free_sessions,
    get_daily_exception_counts,
    get_exception_counts,
    get_exception_summary_for_team,
    get_new_issues_for_team,
    get_org_ids_with_exceptions,
    get_source_maps_recommendation_for_team,
    get_top_issues_for_team,
    send_digest_to_workflow,
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

    def _create_person_with_email(self, distinct_id: str, email: str) -> None:
        _create_person(distinct_ids=[distinct_id], properties={"email": email}, team=self.team)

    def _set_internal_user_filter(self) -> None:
        self.team.test_account_filters = [
            {"key": "email", "type": "person", "operator": "not_icontains", "value": "@internal.com"}
        ]
        self.team.save()

    def test_get_exception_counts_returns_teams_with_exceptions(self):
        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id)
        flush_persons_and_events()

        results = get_exception_counts(team_ids=[self.team.pk])

        assert len(results) == 1
        assert results[0][0] == self.team.pk

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
        assert result["crash_free_rate"] == 66.67

    def test_get_crash_free_sessions_empty_when_no_sessions(self):
        result = get_crash_free_sessions(self.team)
        assert result == {}

    def test_get_crash_free_sessions_includes_previous_week_comparison(self):
        s1, s2, s3 = str(uuid7()), str(uuid7()), str(uuid7())
        self._create_pageview(session_id=s1, timestamp=_days_ago(1))
        self._create_pageview(session_id=s2, timestamp=_days_ago(1))
        self._create_exception_event(session_id=s2, timestamp=_days_ago(1))

        self._create_pageview(session_id=s3, timestamp=_days_ago(10))
        self._create_exception_event(session_id=s3, timestamp=_days_ago(10))
        flush_persons_and_events()

        result = get_crash_free_sessions(self.team)

        assert result["total_sessions"] == 2
        assert result["crash_free_rate"] == 50.0
        assert result["total_sessions_change"] is not None

    def test_get_daily_exception_counts_returns_7_days(self):
        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(3))
        flush_persons_and_events()

        result = get_daily_exception_counts(self.team)

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
        result = get_daily_exception_counts(self.team)

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

    def test_get_org_ids_with_exceptions(self):
        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id)
        flush_persons_and_events()

        org_ids = get_org_ids_with_exceptions()

        assert self.team.organization_id in org_ids

    def test_get_org_ids_with_exceptions_empty(self):
        org_ids = get_org_ids_with_exceptions()
        assert org_ids == []

    def test_get_exception_summary_for_team(self):
        issue = self._create_issue()
        for _ in range(3):
            self._create_exception_event(issue_id=issue.id)
        self._create_exception_event(issue_id=None)  # ingestion failure
        flush_persons_and_events()

        result = get_exception_summary_for_team(self.team)

        assert result["exception_count"] == 4
        assert result["ingestion_failure_count"] == 1
        assert result["prev_exception_count"] == 0

    def test_get_exception_summary_for_team_includes_previous_week(self):
        issue = self._create_issue()
        for _ in range(3):
            self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(1))
        for _ in range(5):
            self._create_exception_event(issue_id=issue.id, timestamp=_days_ago(10))
        flush_persons_and_events()

        result = get_exception_summary_for_team(self.team)

        assert result["exception_count"] == 3
        assert result["prev_exception_count"] == 5

    def test_get_exception_summary_for_team_excludes_other_teams(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        issue = self._create_issue()
        self._create_exception_event(issue_id=issue.id)
        flush_persons_and_events()

        result = get_exception_summary_for_team(other_team)

        assert result == {} or result["exception_count"] == 0

    @parameterized.expand(["engineering", "data", "founder", "Engineering", "DATA", "Founder"])
    def test_auto_select_project_enrolls_eligible_roles(self, role):
        self.user.role_at_organization = role
        self.user.save()

        team_exception_counts = {
            self.team.pk: {"exception_count": 10, "ingestion_failure_count": 0, "prev_exception_count": 0},
        }

        auto_select_project_for_user(self.user, self.organization.id, team_exception_counts)
        self.user.refresh_from_db()

        settings = self.user.notification_settings or {}
        project_enabled = settings.get("error_tracking_weekly_digest_project_enabled", {})
        assert project_enabled[str(self.team.pk)] is True

    @parameterized.expand(["marketing", "sales", "leadership", "product", "other", None])
    def test_auto_select_project_sets_empty_for_ineligible_roles(self, role):
        self.user.role_at_organization = role
        self.user.save()

        team_exception_counts = {
            self.team.pk: {"exception_count": 10, "ingestion_failure_count": 0, "prev_exception_count": 0},
        }

        auto_select_project_for_user(self.user, self.organization.id, team_exception_counts)
        self.user.refresh_from_db()

        settings = self.user.notification_settings or {}
        project_enabled = settings.get("error_tracking_weekly_digest_project_enabled", {})
        assert project_enabled == {}

    def test_auto_select_project_skips_if_already_configured(self):
        self.user.role_at_organization = "engineering"
        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True},
        }
        self.user.save()

        team_exception_counts = {
            self.team.pk: {"exception_count": 5, "ingestion_failure_count": 0, "prev_exception_count": 0},
        }

        auto_select_project_for_user(self.user, self.organization.id, team_exception_counts)
        self.user.refresh_from_db()

        settings = self.user.notification_settings or {}
        assert settings["error_tracking_weekly_digest_project_enabled"] == {str(self.team.pk): True}

    def test_auto_select_project_noop_when_no_exceptions(self):
        auto_select_project_for_user(self.user, self.organization.id, {})
        self.user.refresh_from_db()

        assert "error_tracking_weekly_digest_project_enabled" not in (self.user.partial_notification_settings or {})

    def test_get_exception_summary_filters_internal_users(self):
        self._set_internal_user_filter()
        issue = self._create_issue()
        self._create_person_with_email("regular_user", "user@external.com")
        self._create_person_with_email("internal_user", "bot@internal.com")
        self._create_exception_event(issue_id=issue.id, distinct_id="regular_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="regular_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        flush_persons_and_events()

        result = get_exception_summary_for_team(self.team)

        assert result["exception_count"] == 2

    def test_get_daily_exception_counts_filters_internal_users(self):
        self._set_internal_user_filter()
        issue = self._create_issue()
        self._create_person_with_email("regular_user", "user@external.com")
        self._create_person_with_email("internal_user", "bot@internal.com")
        self._create_exception_event(issue_id=issue.id, distinct_id="regular_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        flush_persons_and_events()

        result = get_daily_exception_counts(self.team)

        assert sum(d["count"] for d in result) == 1

    def test_get_top_issues_filters_internal_users(self):
        self._set_internal_user_filter()
        issue = self._create_issue()
        self._create_person_with_email("regular_user", "user@external.com")
        self._create_person_with_email("internal_user", "bot@internal.com")
        self._create_exception_event(issue_id=issue.id, distinct_id="regular_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        flush_persons_and_events()

        result = get_top_issues_for_team(self.team)

        assert len(result) == 1
        assert result[0]["occurrence_count"] == 1

    def test_get_new_issues_filters_internal_users(self):
        self._set_internal_user_filter()
        issue = self._create_issue()
        self._create_person_with_email("regular_user", "user@external.com")
        self._create_person_with_email("internal_user", "bot@internal.com")
        self._create_exception_event(issue_id=issue.id, distinct_id="regular_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        self._create_exception_event(issue_id=issue.id, distinct_id="internal_user")
        flush_persons_and_events()

        result = get_new_issues_for_team(self.team)

        assert len(result) == 1
        assert result[0]["occurrence_count"] == 1

    def test_get_crash_free_sessions_filters_internal_users(self):
        self._set_internal_user_filter()
        s1, s2 = str(uuid7()), str(uuid7())
        self._create_person_with_email("regular_user", "user@external.com")
        self._create_person_with_email("internal_user", "bot@internal.com")
        self._create_pageview(distinct_id="regular_user", session_id=s1)
        self._create_pageview(distinct_id="internal_user", session_id=s2)
        self._create_exception_event(distinct_id="internal_user", session_id=s2)
        flush_persons_and_events()

        result = get_crash_free_sessions(self.team)

        assert result["total_sessions"] == 1
        assert result["crash_free_rate"] == 100.0


class TestComputeWeekOverWeekChange:
    def test_increase_when_higher_is_better(self):
        result = compute_week_over_week_change(150, 100, higher_is_better=True)
        assert result is not None
        assert result["percent"] == 50
        assert result["direction"] == "Up"
        assert result["color"] == "#2f7d4f"
        assert result["text"] == "Up 50%"
        assert result["long_text"] == "Up 50% from previous week"

    def test_decrease_when_higher_is_better(self):
        result = compute_week_over_week_change(50, 100, higher_is_better=True)
        assert result is not None
        assert result["percent"] == 50
        assert result["direction"] == "Down"
        assert result["color"] == "#a13232"

    def test_increase_when_lower_is_better(self):
        result = compute_week_over_week_change(150, 100, higher_is_better=False)
        assert result is not None
        assert result["color"] == "#a13232"
        assert result["direction"] == "Up"

    def test_decrease_when_lower_is_better(self):
        result = compute_week_over_week_change(50, 100, higher_is_better=False)
        assert result is not None
        assert result["color"] == "#2f7d4f"
        assert result["direction"] == "Down"

    def test_rounds_to_whole_number(self):
        result = compute_week_over_week_change(113, 100, higher_is_better=True)
        assert result is not None
        assert result["percent"] == 13

    def test_returns_none_when_previous_is_zero(self):
        assert compute_week_over_week_change(100, 0, higher_is_better=True) is None

    def test_returns_none_when_previous_is_none(self):
        assert compute_week_over_week_change(100, None, higher_is_better=True) is None

    def test_returns_none_when_no_change(self):
        assert compute_week_over_week_change(100, 100, higher_is_better=True) is None


# total_frames >= 20 and unresolved_pct > 0.30 => an active (not completed) recommendation
_ACTIVE_META = {
    "total_frames": 100,
    "unresolved_frames": 72,
    "unresolved_pct": 0.72,
    "threshold_pct": 0.30,
    "min_sample_frames": 20,
    "lookback_hours": 24,
}


class TestSourceMapsRecommendationForDigest(APIBaseTest):
    def _create_recommendation(
        self, *, meta: dict, computed: bool = True, dismissed: bool = False
    ) -> ErrorTrackingRecommendation:
        now = timezone.now()
        return ErrorTrackingRecommendation.objects.create(
            team=self.team,
            type="source_maps",
            meta=meta,
            computed_at=now if computed else None,
            dismissed_at=now if dismissed else None,
        )

    def test_returns_none_when_no_recommendation(self):
        assert get_source_maps_recommendation_for_team(self.team) is None

    def test_returns_none_when_not_yet_computed(self):
        self._create_recommendation(meta=_ACTIVE_META, computed=False)
        assert get_source_maps_recommendation_for_team(self.team) is None

    def test_returns_none_when_dismissed(self):
        self._create_recommendation(meta=_ACTIVE_META, dismissed=True)
        assert get_source_maps_recommendation_for_team(self.team) is None

    def test_returns_none_when_completed_below_threshold(self):
        self._create_recommendation(meta={**_ACTIVE_META, "unresolved_frames": 5, "unresolved_pct": 0.05})
        assert get_source_maps_recommendation_for_team(self.team) is None

    def test_returns_none_when_completed_too_few_frames(self):
        self._create_recommendation(meta={**_ACTIVE_META, "total_frames": 5})
        assert get_source_maps_recommendation_for_team(self.team) is None

    def test_returns_data_when_active(self):
        self._create_recommendation(meta=_ACTIVE_META)
        result = get_source_maps_recommendation_for_team(self.team)
        assert result is not None
        assert result["unresolved_percent"] == 72
        assert result["lookback_hours"] == 24
        assert result["wizard_command"] == "npx -y @posthog/wizard@latest upload-source-maps"
        assert result["docs_url"].startswith("https://posthog.com/docs/error-tracking/upload-source-maps")

    @override_settings(CLOUD_DEPLOYMENT="EU")
    def test_wizard_command_appends_region_eu_on_eu_cloud(self):
        self._create_recommendation(meta=_ACTIVE_META)
        result = get_source_maps_recommendation_for_team(self.team)
        assert result is not None
        assert result["wizard_command"] == "npx -y @posthog/wizard@latest upload-source-maps --region eu"

    def test_only_returns_recommendation_for_the_given_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._create_recommendation(meta=_ACTIVE_META)
        assert get_source_maps_recommendation_for_team(other_team) is None


class TestSendDigestToWorkflow(SimpleTestCase):
    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID="")
    def test_raises_when_workflow_not_configured(self):
        with pytest.raises(ValueError):
            send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID="wf-123", CLOUD_DEPLOYMENT=None)
    def test_raises_on_non_2xx_so_failures_are_not_marked_sent(self):
        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("500")
            with pytest.raises(requests.HTTPError):
                send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")

    @override_settings(
        ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID="wf-123",
        ERROR_TRACKING_WEEKLY_DIGEST_WEBHOOK_SECRET="Bearer test-token",
        CLOUD_DEPLOYMENT=None,
    )
    def test_sends_secret_as_authorization_header(self):
        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")
            assert mock_post.call_args.kwargs["headers"] == {"Authorization": "Bearer test-token"}


class TestWeeklyDigestWorkflowDelivery(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    @override_settings(
        ERROR_TRACKING_WEEKLY_DIGEST_WORKFLOW_ID="wf-123",
        ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"],
        CLOUD_DEPLOYMENT=None,
    )
    def test_task_posts_json_safe_digest_and_dedupes_on_retry(self):
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name="TestError"
        )
        _create_event(
            distinct_id="user_1",
            event="$exception",
            team=self.team,
            properties={"$exception_issue_id": str(issue.id)},
            timestamp=_days_ago(1),
        )
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True}
        }
        self.user.save()

        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))

            assert mock_post.call_count == 1
            url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs["url"]
            assert url == f"{settings.SITE_URL}/public/webhooks/wf-123"

            payload = mock_post.call_args.kwargs["json"]
            json.dumps(payload)  # the workflow webhook only accepts JSON-serializable payloads
            assert payload["event"] == "error_tracking_weekly_digest"
            assert payload["distinct_id"] == self.user.distinct_id

            digest = payload["digest"]
            assert digest["recipient_email"] == self.user.email
            assert digest["org_name"] == self.organization.name
            section = digest["project_sections"][0]
            assert section["team_name"] == self.team.name
            assert section["exception_count"] == 1
            assert section["top_issues"][0]["id"] == str(issue.id)
            assert "team" not in section

            # Retry of the org task must not send the same campaign twice (MessagingRecord dedupe)
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))
            assert mock_post.call_count == 1
