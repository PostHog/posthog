import json
from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests

from posthog.models import Team, User
from posthog.models.messaging import MessagingRecord
from posthog.models.utils import uuid7
from posthog.tasks.email import send_error_tracking_weekly_digest_for_org

from products.error_tracking.backend.facade import api as error_tracking_facade
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.weekly_digest import send_digest_to_workflow

from ee.clickhouse.materialized_columns.columns import materialize


def _days_ago(n: int) -> str:
    return (timezone.now() - timedelta(days=n)).isoformat()


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSendDigestToWorkflow(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT=None)
    def test_refuses_to_send_from_a_self_hosted_deployment(self):
        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            with pytest.raises(RuntimeError, match="self-hosted"):
                send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")
            assert mock_post.call_count == 0

    def test_raises_on_non_2xx_so_failures_are_not_marked_sent(self):
        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(
                "500", response=mock_post.return_value
            )
            with pytest.raises(requests.HTTPError):
                send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")

    @override_settings(WORKFLOWS_WEBHOOK_SECRET="Bearer test-token")
    def test_sends_secret_as_authorization_header(self):
        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            send_digest_to_workflow({"recipient_email": "a@b.com"}, "distinct-1")
            assert mock_post.call_args.kwargs["headers"] == {"Authorization": "Bearer test-token"}


@override_settings(CLOUD_DEPLOYMENT="US")
class TestWeeklyDigestWorkflowDelivery(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_task_posts_json_safe_digest_and_dedupes_on_retry(self):
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name="TestError"
        )
        fingerprint = str(uuid4())
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        _create_event(
            distinct_id="user_1",
            event="$exception",
            team=self.team,
            properties={"$exception_issue_id": str(issue.id), "$exception_fingerprint": fingerprint},
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
            assert url == "https://webhooks.us.posthog.com/public/webhooks/019f2754-aeff-0000-6a0d-5d3933a94b08"

            payload = mock_post.call_args.kwargs["json"]
            json.dumps(payload)  # the workflow webhook only accepts JSON-serializable payloads
            assert payload["event"] == "error_tracking_weekly_digest"
            assert payload["distinct_id"] == self.user.distinct_id

            digest = payload["digest"]
            assert digest["recipient_email"] == self.user.email
            assert digest["org_name"] == self.organization.name
            section = digest["project_sections"][0]
            assert section["team_name"] == self.team.name
            assert section["exception_count"] == "1"
            assert section["top_issues"][0]["id"] == str(issue.id)
            assert section["top_issues"][0]["occurrence_count"] == "1"
            # The email template branches on `ingestion_failure_count > 0`, so it
            # must stay numeric; the formatted value ships as the display twin.
            assert section["ingestion_failure_count"] == 0
            assert section["ingestion_failure_count_display"] == "0"
            assert "team" not in section

            # Retry of the org task must not send the same campaign twice (MessagingRecord dedupe)
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))
            assert mock_post.call_count == 1

    def _create_second_team_with_exception(self, name: str = "Team B") -> Team:
        team_b = Team.objects.create(organization=self.organization, name=name)
        _create_event(
            distinct_id="user_b",
            event="$exception",
            team=team_b,
            properties={},
            timestamp=_days_ago(1),
        )
        return team_b

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_auto_select_uses_filtered_counts(self):
        # Team A has more raw exceptions, but all from internal users; team B has one real exception.
        # A first-time user must be enrolled onto B, not onto A whose digest builds empty.
        self.team.test_account_filters = [
            {"key": "email", "type": "person", "operator": "not_icontains", "value": "@internal.com"}
        ]
        self.team.save()
        _create_person(distinct_ids=["internal_user"], properties={"email": "bot@internal.com"}, team=self.team)
        for _ in range(5):
            _create_event(
                distinct_id="internal_user", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1)
            )
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.role_at_organization = "engineering"
        self.user.save()

        with patch("products.error_tracking.backend.weekly_digest.requests.post"):
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))

        self.user.refresh_from_db()
        project_enabled = (self.user.partial_notification_settings or {}).get(
            "error_tracking_weekly_digest_project_enabled", {}
        )
        assert project_enabled == {str(team_b.pk): True}

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_recipient_missing_a_failed_team_is_deferred_while_others_send(self):
        # self.team's build fails this run; team_b's succeeds.
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        # Subscribed to both teams: their digest is incomplete this run, so it must be held for the retry
        # rather than shipped as a partial that gets stamped and never completed.
        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): True}
        }
        self.user.save()

        # Subscribed to the healthy team only: unaffected by the unrelated failure, sends immediately.
        other = User.objects.create_and_join(self.organization, "healthy-team-only@posthog.com", None)
        other.partial_notification_settings = {"error_tracking_weekly_digest_project_enabled": {str(team_b.pk): True}}
        other.save()

        real_build = error_tracking_facade.build_team_digest_data

        def build_or_fail(team):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return real_build(team)

        with (
            patch("posthog.tasks.email.error_tracking_api.build_team_digest_data", side_effect=build_or_fail),
            patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post,
        ):
            with pytest.raises(Exception, match="team builds"):
                send_error_tracking_weekly_digest_for_org(str(self.organization.id))

        # Only the healthy-team-only recipient was sent; the incomplete recipient was deferred, not sent a partial.
        recipients = [c.kwargs["json"]["digest"]["recipient_email"] for c in mock_post.call_args_list]
        assert recipients == [other.email]
        # The deferred recipient must not be stamped, so the retry can still deliver their complete digest.
        assert not MessagingRecord.objects.filter(
            campaign_key__contains=str(self.user.uuid), sent_at__isnull=False
        ).exists()

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_deferred_recipient_gets_full_digest_when_build_recovers_on_retry(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): True}
        }
        self.user.save()

        real_build = error_tracking_facade.build_team_digest_data
        fail_team_a = {"on": True}

        def build_or_recover(team):
            if team.pk == self.team.pk and fail_team_a["on"]:
                raise Exception("ClickHouse query failed")
            return real_build(team)

        with (
            patch("posthog.tasks.email.error_tracking_api.build_team_digest_data", side_effect=build_or_recover),
            patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post,
        ):
            # Attempt 1: team A build fails, so the recipient is deferred and the task raises to retry.
            with pytest.raises(Exception, match="team builds"):
                send_error_tracking_weekly_digest_for_org(str(self.organization.id))
            assert mock_post.call_count == 0

            # Attempt 2 (retry): team A now builds. Because attempt 1 never stamped the recipient, they
            # are not deduped away and receive their complete digest — the whole point of the fix.
            fail_team_a["on"] = False
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))

        assert mock_post.call_count == 1
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert {s["team_name"] for s in sections} == {self.team.name, team_b.name}

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_final_attempt_sends_partial_to_recipient_with_permanently_failing_team(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): True}
        }
        self.user.save()

        real_build = error_tracking_facade.build_team_digest_data

        def build_or_fail(team):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return real_build(team)

        with (
            patch("posthog.tasks.email.error_tracking_api.build_team_digest_data", side_effect=build_or_fail),
            patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post,
        ):
            # Retries exhausted (retries == max_retries): fall back to delivering the healthy teams rather
            # than starving the recipient of a digest entirely. throw=False keeps the terminal raise eager.
            send_error_tracking_weekly_digest_for_org.apply(args=[str(self.organization.id)], retries=5, throw=False)

        assert mock_post.call_count == 1
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert [s["team_name"] for s in sections] == [team_b.name]

    @override_settings(ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS=["*"])
    def test_disabled_team_not_counted_as_excluded(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): False}
        }
        self.user.save()

        with patch("products.error_tracking.backend.weekly_digest.requests.post") as mock_post:
            send_error_tracking_weekly_digest_for_org(str(self.organization.id))

        digest = mock_post.call_args.kwargs["json"]["digest"]
        assert digest["disabled_project_names"] == [team_b.name]
        assert digest["excluded_project_count"] == 0
