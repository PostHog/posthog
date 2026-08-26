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

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.messaging import MessagingRecord
from posthog.models.utils import uuid7

from products.access_control.backend.models.access_control import AccessControl
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.temporal.weekly_digest.activities import (
    _get_digest_orgs,
    _load_page_orgs,
    _send_org_digest,
)
from products.error_tracking.backend.temporal.weekly_digest.types import (
    CleanupDigestOrgsInputs,
    GetDigestOrgsInputs,
    GetDigestOrgsResult,
    LoadPageOrgsInputs,
    SendOrgDigestInputs,
    SendOrgDigestResult,
    WeeklyDigestInputs,
    WeeklyDigestResult,
)
from products.error_tracking.backend.temporal.weekly_digest.workflow import (
    FAILED_ORGS_ERROR_TYPE,
    ErrorTrackingWeeklyDigestPageWorkflow,
    ErrorTrackingWeeklyDigestWorkflow,
)
from products.error_tracking.backend.weekly_digest import build_team_digest_data

from ee.clickhouse.materialized_columns.columns import materialize

_WEBHOOK_POST = "products.error_tracking.backend.weekly_digest.requests.post"
_BUILD_TEAM_DIGEST_DATA = "products.error_tracking.backend.weekly_digest.build_team_digest_data"
_IS_CLOUD = "products.error_tracking.backend.temporal.weekly_digest.activities.is_cloud"
_OBJECT_STORAGE = "products.error_tracking.backend.temporal.weekly_digest.activities.object_storage"


def _days_ago(n: int) -> str:
    return (timezone.now() - timedelta(days=n)).isoformat()


@override_settings(CLOUD_DEPLOYMENT="US")
class TestGetDigestOrgs(SimpleTestCase):
    def test_explicit_org_ids_bypass_discovery_and_are_stored_sorted(self):
        with (
            patch("products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions") as mock_discover,
            patch(_OBJECT_STORAGE) as mock_storage,
        ):
            result = _get_digest_orgs(GetDigestOrgsInputs(storage_key="k", org_ids=["org-b", "org-a"]))
            assert result == GetDigestOrgsResult(total_orgs=2)
            mock_discover.assert_not_called()
            # Sorted before storing: page slicing downstream assumes a stable order.
            mock_storage.write.assert_called_once_with("k", json.dumps(["org-a", "org-b"]))

    def test_cloud_scheduled_run_stores_all_orgs_with_exceptions(self):
        with (
            patch(
                "products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions",
                return_value=["org-b", "org-a"],
            ),
            patch(_OBJECT_STORAGE) as mock_storage,
        ):
            assert _get_digest_orgs(GetDigestOrgsInputs(storage_key="k")) == GetDigestOrgsResult(total_orgs=2)
            mock_storage.write.assert_called_once_with("k", json.dumps(["org-a", "org-b"]))

    def test_no_orgs_stores_nothing(self):
        with (
            patch("products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions", return_value=[]),
            patch(_OBJECT_STORAGE) as mock_storage,
        ):
            assert _get_digest_orgs(GetDigestOrgsInputs(storage_key="k")) == GetDigestOrgsResult(total_orgs=0)
            mock_storage.write.assert_not_called()

    @parameterized.expand([("scheduled", None), ("targeted_manual_run", ["org-x"])])
    def test_self_hosted_run_is_a_noop(self, _name, org_ids):
        # Explicit org ids are the manual-run path and must not route around the cloud gate.
        with (
            patch(_IS_CLOUD, return_value=False),
            patch("products.error_tracking.backend.weekly_digest.get_org_ids_with_exceptions") as mock_discover,
            patch(_OBJECT_STORAGE) as mock_storage,
        ):
            assert _get_digest_orgs(GetDigestOrgsInputs(storage_key="k", org_ids=org_ids)) == GetDigestOrgsResult(
                total_orgs=0
            )
            mock_discover.assert_not_called()
            mock_storage.write.assert_not_called()


class TestLoadPageOrgs(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_page", 1, ["org-0", "org-1"]),
            ("middle_page", 2, ["org-2", "org-3"]),
            ("last_partial_page", 3, ["org-4"]),
            ("past_the_end", 4, []),
        ]
    )
    def test_page_slicing(self, _name, page_number, expected):
        # Off-by-one here silently drops or double-sends whole orgs; pages must tile the
        # stored list exactly.
        stored = json.dumps([f"org-{i}" for i in range(5)])
        with patch(_OBJECT_STORAGE) as mock_storage:
            mock_storage.read.return_value = stored
            inputs = LoadPageOrgsInputs(storage_key="k", page_number=page_number, page_size=2)
            assert _load_page_orgs(inputs) == expected

    def test_missing_object_raises_for_retry(self):
        with patch(_OBJECT_STORAGE) as mock_storage:
            mock_storage.read.return_value = None
            with pytest.raises(ApplicationError):
                _load_page_orgs(LoadPageOrgsInputs(storage_key="k", page_number=1, page_size=2))


# send_digest_to_workflow refuses to send outside Cloud, so the send path needs cloud mode.
@override_settings(CLOUD_DEPLOYMENT="US")
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

            # Retry of the org activity must not send the same campaign twice (MessagingRecord dedupe),
            # but it still reports what attempt 1 sent, since only the last attempt's result is surfaced.
            retry_result = self._run(attempt=2)
            assert mock_post.call_count == 1
            assert retry_result == SendOrgDigestResult(sent=1, teams_built=1)

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

    @parameterized.expand([("eligible_role", "engineering", 1), ("ineligible_role", "marketing", 0)])
    def test_dry_run_simulates_auto_select_without_enrolling(self, _name, role, expected_sent):
        # Auto-select is one-shot, so a dry run that wrote it would change what the next real run sends.
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        flush_persons_and_events()

        self.user.role_at_organization = role
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            result = self._run(dry_run=True)

        assert mock_post.call_count == 0
        assert result.sent == expected_sent

        self.user.refresh_from_db()
        assert "error_tracking_weekly_digest_project_enabled" not in (self.user.partial_notification_settings or {})

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

    def test_auto_select_skips_the_busiest_project_the_user_cannot_access(self):
        # self.team is the busiest but private to a plain member. Enrolling them onto it would leave every
        # other project disabled-by-omission, and auto-select is one-shot, so their digest would stop for good.
        for _ in range(5):
            _create_event(
                distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1)
            )
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )

        self.user.role_at_organization = "engineering"
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            self._run()

        self.user.refresh_from_db()
        project_enabled = (self.user.partial_notification_settings or {}).get(
            "error_tracking_weekly_digest_project_enabled", {}
        )
        assert project_enabled == {str(team_b.pk): True}
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert [s["team_name"] for s in sections] == [team_b.name]

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

        def build_or_fail(team, daily_rows=None):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team, daily_rows)

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

        def build_or_recover(team, daily_rows=None):
            if team.pk == self.team.pk and fail_team_a["on"]:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team, daily_rows)

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

        # Fails with and without test account filters, like a timeout: the unfiltered
        # fallback on the last attempts must not rescue it.
        def build_or_fail(team, daily_rows=None, filter_test_accounts=True):
            if team.pk == self.team.pk:
                raise Exception("ClickHouse query failed")
            return build_team_digest_data(team, daily_rows)

        with (
            patch(_BUILD_TEAM_DIGEST_DATA, side_effect=build_or_fail),
            patch(_WEBHOOK_POST) as mock_post,
        ):
            # Final attempt (attempt == max_attempts): fall back to delivering the healthy teams rather
            # than starving the recipient of a digest entirely. The activity still raises for visibility.
            with pytest.raises(ApplicationError, match="team builds") as exc_info:
                self._run(attempt=6)

        assert mock_post.call_count == 1
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert [s["team_name"] for s in sections] == [team_b.name]
        # A raising activity returns no result, so the count only reaches the workflow via details.
        assert list(exc_info.value.details) == [1]

    @parameterized.expand(
        [
            ("before_last_two_attempts_no_fallback", 4, 0),
            ("second_to_last_attempt_falls_back", 5, 1),
            ("final_attempt_falls_back", 6, 1),
        ]
    )
    def test_broken_test_account_filter_falls_back_to_unfiltered_on_last_two_attempts(
        self, _name, attempt, expected_sends
    ):
        # RE2 rejects negative lookahead, so every filtered digest query for this team raises during
        # HogQL preparation (the failure shape seen in production). Only the unfiltered rebuild on the
        # last two attempts can ever deliver this team's digest, and it must disclose itself via
        # test_account_filters_skipped; falling back any earlier would mean a transient error could
        # ship an unfiltered digest for a team whose filters work.
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "operator": "regex", "value": "^(?!.*localhost).*$"}
        ]
        self.team.save()
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        flush_persons_and_events()

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True}
        }
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            if expected_sends:
                result = self._run(attempt=attempt)
                assert result == SendOrgDigestResult(sent=1, teams_built=1)
            else:
                with pytest.raises(ApplicationError, match="team builds"):
                    self._run(attempt=attempt)

        assert mock_post.call_count == expected_sends
        if expected_sends:
            section = mock_post.call_args.kwargs["json"]["digest"]["project_sections"][0]
            assert section["test_account_filters_skipped"] is True
            assert section["exception_count"] == "1"

    def test_first_time_user_auto_select_survives_broken_filter_team(self):
        # The auto-select ranking pass queries every team with exceptions. A broken-filter team
        # raising there used to fail the whole activity before the build loop could defer or fall
        # back, so no one in the org got any digest. The healthy team must still rank, enroll, and send.
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "operator": "regex", "value": "^(?!.*localhost).*$"}
        ]
        self.team.save()
        _create_event(distinct_id="user_a", event="$exception", team=self.team, properties={}, timestamp=_days_ago(1))
        team_b = self._create_second_team_with_exception()
        flush_persons_and_events()

        self.user.role_at_organization = "engineering"
        self.user.save()

        with patch(_WEBHOOK_POST) as mock_post:
            result = self._run(attempt=1)

        # The broken team goes unranked, so enrollment lands on the healthy team and its digest
        # sends. The broken team isn't enabled for anyone, so nothing needs its build and the
        # activity completes instead of raising.
        assert result == SendOrgDigestResult(sent=1, teams_built=1)
        self.user.refresh_from_db()
        project_enabled = (self.user.partial_notification_settings or {}).get(
            "error_tracking_weekly_digest_project_enabled", {}
        )
        assert project_enabled == {str(team_b.pk): True}
        sections = mock_post.call_args.kwargs["json"]["digest"]["project_sections"]
        assert [s["team_name"] for s in sections] == [team_b.name]
        assert sections[0]["test_account_filters_skipped"] is False

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


def _storage_stubs(
    org_ids: list[str],
    cleanup_keys: list[str] | None = None,
    load_calls: list[LoadPageOrgsInputs] | None = None,
    fail_page: int | None = None,
    fail_cleanup: bool = False,
):
    # In-memory stand-in for object storage, keyed by storage_key rather than closing over
    # the org list, so a page reading a key discovery never wrote — or reading one cleanup
    # already deleted — fails here the way it would against S3.
    store: dict[str, list[str]] = {}

    @activity.defn(name="get_digest_orgs_activity")
    async def _get_orgs(inputs: GetDigestOrgsInputs) -> GetDigestOrgsResult:
        if org_ids:
            store[inputs.storage_key] = sorted(org_ids)
        return GetDigestOrgsResult(total_orgs=len(org_ids))

    @activity.defn(name="load_page_orgs_activity")
    async def _load_page(inputs: LoadPageOrgsInputs) -> list[str]:
        if load_calls is not None:
            load_calls.append(inputs)
        if inputs.page_number == fail_page:
            raise ApplicationError(f"object storage unavailable for page {fail_page}", non_retryable=True)
        if inputs.storage_key not in store:
            raise ApplicationError(f"Digest org list not found in object storage at {inputs.storage_key}")
        start = (inputs.page_number - 1) * inputs.page_size
        return store[inputs.storage_key][start : start + inputs.page_size]

    @activity.defn(name="cleanup_digest_orgs_activity")
    async def _cleanup(inputs: CleanupDigestOrgsInputs) -> None:
        if fail_cleanup:
            raise ApplicationError("object storage unavailable for cleanup", non_retryable=True)
        store.pop(inputs.storage_key, None)
        if cleanup_keys is not None:
            cleanup_keys.append(inputs.storage_key)

    return [_get_orgs, _load_page, _cleanup]


class TestErrorTrackingWeeklyDigestWorkflow:
    async def _execute(self, workflow_inputs, activities, max_concurrent_activities: int = 16):
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ErrorTrackingWeeklyDigestWorkflow, ErrorTrackingWeeklyDigestPageWorkflow],
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
        cleanup_keys: list[str] = []

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            raise AssertionError("should not fan out when there are no orgs")

        result = await self._execute(WeeklyDigestInputs(), [*_storage_stubs([], cleanup_keys), _send])
        assert result == WeeklyDigestResult(orgs=0, orgs_failed=0, sent=0)
        # Nothing was stored, so there must be nothing to clean up.
        assert cleanup_keys == []

    @pytest.mark.asyncio
    async def test_fans_out_with_concurrency_cap_and_plumbs_inputs(self):
        org_ids = [f"org-{i}" for i in range(10)]
        tracker = _FanOutTracker()
        state_lock = asyncio.Lock()

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
            [*_storage_stubs(org_ids), _send],
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

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            inputs_seen.append(inputs)
            if inputs.org_id == "org-b":
                raise ApplicationError("org exhausted retries", 3, non_retryable=True)
            sent_orgs.add(inputs.org_id)
            return SendOrgDigestResult(sent=1, teams_built=1)

        # No input at all — the shape of a manual Temporal UI run. It must fall back to
        # defaults, and those defaults must be a dry run.
        with pytest.raises(Exception) as exc_info:
            await self._execute(None, [*_storage_stubs(org_ids), _send])

        # Workflow raises ApplicationError(type=FAILED_ORGS_ERROR_TYPE). Temporal wraps it
        # in WorkflowFailureError; the cause carries the ApplicationError.
        cause = exc_info.value.__cause__
        assert cause is not None and getattr(cause, "type", None) == FAILED_ORGS_ERROR_TYPE
        # org-a and org-c sent 1 each, org-b sent 3 before exhausting its retries. Dropping the
        # failed org's count would report 2.
        assert "5 digests sent" in str(cause)
        # The failed org must not prevent the other orgs from being processed.
        assert sent_orgs == {"org-a", "org-c"}
        # An input-less run can never send for real; only the schedule passes dry_run=False.
        assert all(i.dry_run for i in inputs_seen)

    @pytest.mark.asyncio
    async def test_pages_through_all_orgs_via_child_workflows(self):
        org_ids = sorted(f"org-{i}" for i in range(25))
        cleanup_keys: list[str] = []
        load_calls: list[LoadPageOrgsInputs] = []
        seen: list[str] = []

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            seen.append(inputs.org_id)
            return SendOrgDigestResult(sent=1, teams_built=1)

        result = await self._execute(
            WeeklyDigestInputs(page_size=10), [*_storage_stubs(org_ids, cleanup_keys, load_calls), _send]
        )

        # Every org is processed exactly once across the page children (25 orgs at
        # page_size 10 = pages of 10/10/5), and the stored list is cleaned up after.
        assert Counter(seen) == Counter(org_ids)
        assert result == WeeklyDigestResult(orgs=25, orgs_failed=0, sent=25)
        assert len(cleanup_keys) == 1
        # Each child must request its own page at the parent's page_size: a child that
        # ignores page_size pulls the whole list into one activity payload, which is the
        # payload-cap failure the storage handoff exists to avoid.
        assert sorted((call.page_number, call.page_size) for call in load_calls) == [(1, 10), (2, 10), (3, 10)]
        # The key written, read, and deleted must all be the same one.
        assert {call.storage_key for call in load_calls} == set(cleanup_keys)

    @pytest.mark.asyncio
    async def test_failure_in_early_page_is_reported_by_the_parent(self):
        # Exact multiple of page_size: page math must not add an empty trailing page
        # or drop failures or totals.
        org_ids = sorted(f"org-{i}" for i in range(20))
        load_calls: list[LoadPageOrgsInputs] = []
        seen: list[str] = []

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            seen.append(inputs.org_id)
            if inputs.org_id == "org-3":
                raise ApplicationError("org exhausted retries", non_retryable=True)
            return SendOrgDigestResult(sent=1, teams_built=1)

        with pytest.raises(Exception) as exc_info:
            await self._execute(
                WeeklyDigestInputs(page_size=10), [*_storage_stubs(org_ids, load_calls=load_calls), _send]
            )

        cause = exc_info.value.__cause__
        assert cause is not None and getattr(cause, "type", None) == FAILED_ORGS_ERROR_TYPE
        # A failure in page 1 must not stop later pages: every page drains and the
        # parent reports the failure once at the end.
        assert Counter(seen) == Counter(org_ids)
        # 20 orgs at page_size 10 is exactly two pages. A ceil that rounds up unconditionally
        # would add a third child that loads nothing.
        assert sorted(call.page_number for call in load_calls) == [1, 2]

    @pytest.mark.asyncio
    async def test_page_that_cannot_load_its_orgs_is_attributed_as_a_whole_page(self):
        # A child that never gets its org ids reports nothing back, so the parent has to
        # attribute the page from its own math. Counting it as one org would tell an
        # operator a storage outage cost 1 org when it cost the whole page.
        org_ids = sorted(f"org-{i}" for i in range(25))
        sent_orgs: list[str] = []

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            sent_orgs.append(inputs.org_id)
            return SendOrgDigestResult(sent=1, teams_built=1)

        with pytest.raises(Exception) as exc_info:
            await self._execute(WeeklyDigestInputs(page_size=10), [*_storage_stubs(org_ids, fail_page=1), _send])

        cause = exc_info.value.__cause__
        assert cause is not None and getattr(cause, "type", None) == FAILED_ORGS_ERROR_TYPE
        assert "10/25 orgs" in str(cause)
        # The other pages still drain: only page 1's orgs go unsent.
        assert Counter(sent_orgs) == Counter(org_ids[10:])

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_fail_an_otherwise_successful_run(self):
        # Cleanup runs after every digest has already gone out, so a storage hiccup there
        # must stay best-effort: failing the run would page someone over a leftover object.
        org_ids = sorted(f"org-{i}" for i in range(5))

        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            return SendOrgDigestResult(sent=1, teams_built=1)

        result = await self._execute(
            WeeklyDigestInputs(page_size=10), [*_storage_stubs(org_ids, fail_cleanup=True), _send]
        )

        assert result == WeeklyDigestResult(orgs=5, orgs_failed=0, sent=5)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_size", [0, -5])
    async def test_non_positive_page_size_fails_the_run(self, page_size):
        # 0 used to raise ZeroDivisionError from the page arithmetic, which Temporal retries
        # as a workflow task forever rather than failing; a negative value produced an empty
        # page range and reported a successful run that sent nothing.
        @activity.defn(name="send_org_digest_activity")
        async def _send(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
            raise AssertionError("should not fan out for an invalid page_size")

        with pytest.raises(Exception) as exc_info:
            await self._execute(WeeklyDigestInputs(page_size=page_size), [*_storage_stubs(["org-a"]), _send])

        cause = exc_info.value.__cause__
        assert cause is not None and "page_size" in str(cause)
