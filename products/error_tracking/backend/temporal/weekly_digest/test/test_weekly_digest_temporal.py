import json
import uuid
import asyncio
import dataclasses
from collections import Counter
from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team, User
from posthog.models.messaging import MessagingRecord
from posthog.models.utils import uuid7

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.temporal.weekly_digest.activities import _get_digest_orgs, _send_org_digest
from products.error_tracking.backend.temporal.weekly_digest.types import (
    GetDigestOrgsInputs,
    SendOrgDigestInputs,
    SendOrgDigestResult,
    WeeklyDigestInputs,
    WeeklyDigestResult,
)
from products.error_tracking.backend.temporal.weekly_digest.workflow import (
    FAILED_ORGS_ERROR_TYPE,
    ErrorTrackingWeeklyDigestWorkflow,
)
from products.error_tracking.backend.weekly_digest import build_team_digest_data

from ee.clickhouse.materialized_columns.columns import materialize

_WEBHOOK_POST = "products.error_tracking.backend.weekly_digest.requests.post"
_BUILD_TEAM_DIGEST_DATA = "products.error_tracking.backend.weekly_digest.build_team_digest_data"
_IS_CLOUD = "products.error_tracking.backend.temporal.weekly_digest.activities.is_cloud"


def _days_ago(n: int) -> str:
    return (timezone.now() - timedelta(days=n)).isoformat()


class TestGetDigestOrgs(SimpleTestCase):
    def test_explicit_org_ids_bypass_discovery(self):
        with patch("products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions") as mock_discover:
            assert _get_digest_orgs(GetDigestOrgsInputs(org_ids=["org-x"])) == ["org-x"]
            mock_discover.assert_not_called()

    def test_cloud_scheduled_run_returns_all_orgs_with_exceptions(self):
        with (
            patch(_IS_CLOUD, return_value=True),
            patch(
                "products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions",
                return_value=["org-a", "org-b"],
            ),
        ):
            assert _get_digest_orgs(GetDigestOrgsInputs()) == ["org-a", "org-b"]

    @parameterized.expand(
        [
            ("first_page", None, 2, ["org-a", "org-b"]),
            ("cursor_is_exclusive", "org-b", 2, ["org-c"]),
            ("cursor_between_ids_skips_nothing", "org-aa", 2, ["org-b", "org-c"]),
            ("past_the_end", "org-z", 2, []),
        ]
    )
    def test_keyset_page_bounds(self, _name, after, limit, expected):
        # Unsorted input: paging correctness depends on the activity sorting before slicing.
        inputs = GetDigestOrgsInputs(org_ids=["org-c", "org-a", "org-b"], after=after, limit=limit)
        assert _get_digest_orgs(inputs) == expected

    def test_self_hosted_scheduled_run_is_a_noop(self):
        with (
            patch(_IS_CLOUD, return_value=False),
            patch("products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions") as mock_discover,
        ):
            assert _get_digest_orgs(GetDigestOrgsInputs()) == []
            mock_discover.assert_not_called()


class TestSendOrgDigest(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    def _run(self, attempt: int = 1, dry_run: bool = False) -> SendOrgDigestResult:
        return _send_org_digest(SendOrgDigestInputs(org_id=str(self.organization.id), dry_run=dry_run), attempt=attempt)

    def test_activity_posts_json_safe_digest_and_dedupes_on_retry(self):
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

        with patch(_WEBHOOK_POST) as mock_post:
            result = self._run()

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
            assert result == SendOrgDigestResult(sent=1, teams_built=1)

            # Retry of the org activity must not send the same campaign twice (MessagingRecord dedupe)
            retry_result = self._run(attempt=2)
            assert mock_post.call_count == 1
            assert retry_result == SendOrgDigestResult(sent=0, teams_built=1)

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

    def test_dry_run_builds_but_sends_nothing(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True}
        }
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            result = self._run(dry_run=True)

        assert mock_post.call_count == 0
        assert result == SendOrgDigestResult(sent=1, teams_built=1)
        assert not MessagingRecord.objects.filter(sent_at__isnull=False).exists()

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

        with patch(_WEBHOOK_POST):
            self._run()

        self.user.refresh_from_db()
        project_enabled = (self.user.partial_notification_settings or {}).get(
            "error_tracking_weekly_digest_project_enabled", {}
        )
        assert project_enabled == {str(team_b.pk): True}

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

        def build_or_fail(team):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team)

        with (
            patch(_BUILD_TEAM_DIGEST_DATA, side_effect=build_or_fail),
            patch(_WEBHOOK_POST) as mock_post,
        ):
            with pytest.raises(Exception, match="team builds"):
                self._run()

        # Only the healthy-team-only recipient was sent; the incomplete recipient was deferred, not sent a partial.
        recipients = [c.kwargs["json"]["digest"]["recipient_email"] for c in mock_post.call_args_list]
        assert recipients == [other.email]
        # The deferred recipient must not be stamped, so the retry can still deliver their complete digest.
        assert not MessagingRecord.objects.filter(
            campaign_key__contains=str(self.user.uuid), sent_at__isnull=False
        ).exists()

    def test_deferred_recipient_gets_full_digest_when_build_recovers_on_retry(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): True}
        }
        self.user.save()

        fail_team_a = {"on": True}

        def build_or_recover(team):
            if team.pk == self.team.pk and fail_team_a["on"]:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team)

        with (
            patch(_BUILD_TEAM_DIGEST_DATA, side_effect=build_or_recover),
            patch(_WEBHOOK_POST) as mock_post,
        ):
            # Attempt 1: team A build fails, so the recipient is deferred and the activity raises to retry.
            with pytest.raises(Exception, match="team builds"):
                self._run(attempt=1)
            assert mock_post.call_count == 0

            # Attempt 2 (retry): team A now builds. Because attempt 1 never stamped the recipient, they
            # are not deduped away and receive their complete digest — the whole point of the deferral.
            fail_team_a["on"] = False
            self._run(attempt=2)

        assert mock_post.call_count == 1
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert {s["team_name"] for s in sections} == {self.team.name, team_b.name}

    def test_final_attempt_sends_partial_to_recipient_with_permanently_failing_team(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): True}
        }
        self.user.save()

        def build_or_fail(team):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team)

        with (
            patch(_BUILD_TEAM_DIGEST_DATA, side_effect=build_or_fail),
            patch(_WEBHOOK_POST) as mock_post,
        ):
            # Final attempt (attempt == max_attempts): fall back to delivering the healthy teams rather
            # than starving the recipient of a digest entirely. The activity still raises for visibility.
            with pytest.raises(Exception, match="team builds"):
                self._run(attempt=6)

        assert mock_post.call_count == 1
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert [s["team_name"] for s in sections] == [team_b.name]

    def test_disabled_team_not_counted_as_excluded(self):
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.pk): True, str(team_b.pk): False}
        }
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            self._run()

        digest = mock_post.call_args.kwargs["json"]["digest"]
        assert digest["disabled_project_names"] == [team_b.name]
        assert digest["excluded_project_count"] == 0


@dataclasses.dataclass
class _FanOutTracker:
    in_flight: int = 0
    max_in_flight: int = 0
    inputs_seen: list[SendOrgDigestInputs] = dataclasses.field(default_factory=list)


class TestErrorTrackingWeeklyDigestWorkflow:
    async def _execute(self, workflow_inputs, activities, max_concurrent_activities: int = 16):
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ErrorTrackingWeeklyDigestWorkflow],
                activities=activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                max_concurrent_activities=max_concurrent_activities,
            ):
                return await env.client.execute_workflow(
                    ErrorTrackingWeeklyDigestWorkflow.run,
                    workflow_inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    @pytest.mark.asyncio
    async def test_completes_without_fanout_when_no_orgs(self):
        @activity.defn(name="get_digest_orgs_activity")
        async def _get_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
            return []

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            raise AssertionError("should not fan out when there are no orgs")

        result = await self._execute(WeeklyDigestInputs(), [_get_orgs, _send])
        assert result == WeeklyDigestResult(orgs=0, orgs_failed=0, sent=0)

    @pytest.mark.asyncio
    async def test_fans_out_with_concurrency_cap_and_plumbs_inputs(self):
        org_ids = [f"org-{i}" for i in range(10)]
        tracker = _FanOutTracker()
        state_lock = asyncio.Lock()

        @activity.defn(name="get_digest_orgs_activity")
        async def _get_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
            return org_ids

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            async with state_lock:
                tracker.in_flight += 1
                tracker.max_in_flight = max(tracker.max_in_flight, tracker.in_flight)
                tracker.inputs_seen.append(inputs)
            try:
                await asyncio.sleep(0.01)
            finally:
                async with state_lock:
                    tracker.in_flight -= 1
            return SendOrgDigestResult(sent=2, teams_built=1)

        result = await self._execute(
            WeeklyDigestInputs(dry_run=True, max_concurrent=3, max_attempts=4),
            [_get_orgs, _send],
            max_concurrent_activities=len(org_ids),
        )

        assert {i.org_id for i in tracker.inputs_seen} == set(org_ids)
        assert all(i.dry_run and i.max_attempts == 4 for i in tracker.inputs_seen)
        assert tracker.max_in_flight <= 3, (
            f"workflow scheduled {tracker.max_in_flight} org activities concurrently "
            f"but max_concurrent=3 — semaphore fan-out guard is missing"
        )
        assert result == WeeklyDigestResult(orgs=10, orgs_failed=0, sent=20)

    @pytest.mark.asyncio
    async def test_raises_after_processing_all_orgs_when_one_fails(self):
        org_ids = ["org-a", "org-b", "org-c"]
        sent_orgs: set[str] = set()
        inputs_seen: list[SendOrgDigestInputs] = []

        @activity.defn(name="get_digest_orgs_activity")
        async def _get_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
            return org_ids

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            inputs_seen.append(inputs)
            if inputs.org_id == "org-b":
                raise ApplicationError("org exhausted retries", non_retryable=True)
            sent_orgs.add(inputs.org_id)
            return SendOrgDigestResult(sent=1, teams_built=1)

        # No input at all — the shape of a manual Temporal UI run. It must fall back to
        # defaults, and those defaults must be a dry run.
        with pytest.raises(Exception) as exc_info:
            await self._execute(None, [_get_orgs, _send])

        # Workflow raises ApplicationError(type=FAILED_ORGS_ERROR_TYPE). Temporal wraps it
        # in WorkflowFailureError; the cause carries the ApplicationError.
        cause = exc_info.value.__cause__
        assert cause is not None and getattr(cause, "type", None) == FAILED_ORGS_ERROR_TYPE
        # The failed org must not prevent the other orgs from being processed.
        assert sent_orgs == {"org-a", "org-c"}
        # An input-less run can never send for real; only the schedule passes dry_run=False.
        assert all(i.dry_run for i in inputs_seen)

    @pytest.mark.asyncio
    async def test_pages_through_all_orgs_via_continue_as_new(self):
        org_ids = sorted(f"org-{i}" for i in range(25))
        cursors_seen: list[str | None] = []
        seen: list[str] = []

        @activity.defn(name="get_digest_orgs_activity")
        async def _get_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
            cursors_seen.append(inputs.after)
            candidates = org_ids if inputs.after is None else [o for o in org_ids if o > inputs.after]
            return candidates[: inputs.limit]

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            seen.append(inputs.org_id)
            return SendOrgDigestResult(sent=1, teams_built=1)

        result = await self._execute(WeeklyDigestInputs(page_size=10), [_get_orgs, _send])

        # One discovery call per page, each carrying the previous page's last org id as
        # the cursor; every org is processed exactly once across the continued executions.
        assert cursors_seen == [None, org_ids[9], org_ids[19]]
        assert Counter(seen) == Counter(org_ids)
        assert result == WeeklyDigestResult(orgs=25, orgs_failed=0, sent=25)

    @pytest.mark.asyncio
    async def test_failure_in_early_page_is_carried_to_the_final_execution(self):
        # Exact multiple of page_size: the chain must end via the empty trailing page
        # without dropping carried failures or totals.
        org_ids = sorted(f"org-{i}" for i in range(20))
        seen: list[str] = []

        @activity.defn(name="get_digest_orgs_activity")
        async def _get_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
            candidates = org_ids if inputs.after is None else [o for o in org_ids if o > inputs.after]
            return candidates[: inputs.limit]

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            seen.append(inputs.org_id)
            if inputs.org_id == "org-3":
                raise ApplicationError("org exhausted retries", non_retryable=True)
            return SendOrgDigestResult(sent=1, teams_built=1)

        with pytest.raises(Exception) as exc_info:
            await self._execute(WeeklyDigestInputs(page_size=10), [_get_orgs, _send])

        cause = exc_info.value.__cause__
        assert cause is not None and getattr(cause, "type", None) == FAILED_ORGS_ERROR_TYPE
        # A failure in page 1 must not stop later pages: the chain drains fully and
        # only the final execution reports the carried failure.
        assert Counter(seen) == Counter(org_ids)
