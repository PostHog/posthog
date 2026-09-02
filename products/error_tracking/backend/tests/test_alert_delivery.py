import time
import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertThread, ErrorTrackingIssue
from products.error_tracking.backend.temporal.alerts.delivery import (
    PENDING_CLAIM_TTL,
    AlertDeliveryError,
    deliver_alert_notifications,
    plan_alert_deliveries,
)
from products.error_tracking.backend.temporal.alerts.dispatch import start_alert_delivery_workflow
from products.error_tracking.backend.temporal.alerts.messages import build_reply_text, build_root_message, issue_url
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.alerts.workflow import ACTIVITY_RETRY_POLICY


class AlertTestMixin(BaseTest):
    def setUp(self):
        super().setUp()
        with team_scope(self.team.id):
            self.integration = Integration.objects.create(
                team=self.team,
                kind=Integration.IntegrationKind.SLACK.value,
                config={"team": {"id": "T123"}},
                sensitive_config={"access_token": "token"},
            )
            self.issue = ErrorTrackingIssue.objects.create(team=self.team)

    def _create_alert(self, *, triggers=None, enabled=True) -> ErrorTrackingAlert:
        with team_scope(self.team.id):
            alert = ErrorTrackingAlert.objects.create(
                team=self.team,
                name="Notify #alerts",
                enabled=enabled,
                triggers=triggers if triggers is not None else ["issue_created"],
            )
            alert.destinations.create(
                team=self.team,
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0123"},
            )
        return alert

    def _inputs(self, event: str, notification_id: str = "notif-1", **overrides) -> AlertDeliveryWorkflowInputs:
        defaults: dict[str, Any] = {
            "notification_id": notification_id,
            "team_id": self.team.id,
            "issue_id": str(self.issue.id),
            "event": event,
            "issue_name": "TypeError",
            "issue_description": "Something failed",
            "status": "Active",
            "actor_email": "dev@example.com",
        }
        defaults.update(overrides)
        return AlertDeliveryWorkflowInputs(**defaults)

    def _mock_slack(self):
        slack_integration = patch("products.error_tracking.backend.temporal.alerts.delivery.SlackIntegration")
        mock = slack_integration.start()
        self.addCleanup(slack_integration.stop)
        client = mock.return_value.client
        client.chat_postMessage.return_value = {"channel": "C0123", "ts": "111.222"}
        return client

    def _thread(self, alert, *, rooted=True) -> ErrorTrackingAlertThread:
        with team_scope(self.team.id):
            return ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=alert.destinations.get(),
                external_ref={"channel": "C0123", "ts": "111.222"} if rooted else {},
                root_headline="🔴 New issue" if rooted else "",
            )


class TestAlertDeliveryPlanning(AlertTestMixin):
    @parameterized.expand(
        [
            ("issue_created", "$error_tracking_issue_created"),
            ("issue_reopened", "$error_tracking_issue_reopened"),
            ("issue_spiking", "$error_tracking_issue_spiking"),
            ("issue_assigned", "$error_tracking_issue_assigned"),
        ]
    )
    def test_subscribed_opener_is_planned(self, trigger, event):
        alert = self._create_alert(triggers=[trigger])

        planned = plan_alert_deliveries(self._inputs(event))

        assert len(planned) == 1
        assert planned[0].alert.id == alert.id
        assert planned[0].is_opener is True
        assert planned[0].thread is None

    @parameterized.expand(
        [
            ("trigger_not_subscribed", {"triggers": ["issue_spiking"]}),
            ("alert_disabled", {"enabled": False}),
        ]
    )
    def test_non_matching_alert_is_not_planned(self, _name, alert_kwargs):
        self._create_alert(**alert_kwargs)

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_created"))

        assert planned == []

    def test_reply_without_thread_is_not_planned(self):
        # Replies never open threads: resolved is not an opener trigger.
        self._create_alert(triggers=["issue_created"])

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))

        assert planned == []

    def test_reply_follows_existing_thread(self):
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            thread = ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=alert.destinations.get(),
            )

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))

        assert len(planned) == 1
        assert planned[0].is_opener is False
        assert planned[0].thread is not None
        assert planned[0].thread.id == thread.id

    def test_repeated_opener_event_with_rooted_thread_is_a_reply(self):
        alert = self._create_alert(triggers=["issue_created", "issue_reopened"])
        with team_scope(self.team.id):
            ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=alert.destinations.get(),
                external_ref={"channel": "C0123", "ts": "111.222"},
            )

        planned = plan_alert_deliveries(self._inputs("$error_tracking_issue_reopened"))

        assert len(planned) == 1
        assert planned[0].is_opener is False
        assert planned[0].thread is not None

    def test_multi_destination_alert_plans_per_destination(self):
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            first_destination = alert.destinations.get()
            second_destination = alert.destinations.create(
                team=self.team,
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0456"},
            )
            # Only the second destination has a rooted thread for this issue.
            thread = ErrorTrackingAlertThread.objects.create(
                team=self.team,
                alert=alert,
                issue=self.issue,
                destination=second_destination,
            )

        opener = plan_alert_deliveries(self._inputs("$error_tracking_issue_created"))
        assert len(opener) == 2
        assert {planned.destination.id for planned in opener} == {first_destination.id, second_destination.id}

        reply = plan_alert_deliveries(self._inputs("$error_tracking_issue_resolved"))
        assert len(reply) == 1
        assert reply[0].destination.id == second_destination.id
        assert reply[0].thread is not None
        assert reply[0].thread.id == thread.id


class TestAlertMessages(SimpleTestCase):
    def _inputs(self, **extra: str) -> AlertDeliveryWorkflowInputs:
        return AlertDeliveryWorkflowInputs(
            notification_id="notif-1",
            team_id=1,
            issue_id="issue-1",
            event="$error_tracking_issue_spiking",
            issue_name="TypeError",
            extra=extra or None,
        )

    @parameterized.expand(
        [
            ("with_baseline", {"current_bucket_value": "600", "computed_baseline": "12.5"}, "vs baseline 12.5"),
            # A zero baseline means the issue has no history, not a real comparison.
            ("zero_baseline", {"current_bucket_value": "600", "computed_baseline": "0.0"}, "no baseline yet"),
            ("missing_baseline", {"current_bucket_value": "600"}, "no baseline yet"),
        ]
    )
    def test_spike_summary_describes_the_baseline_honestly(self, _name, extra, expected):
        reply = build_reply_text(self._inputs(**extra))
        assert reply is not None
        assert reply.startswith("📈 Spiking again: 600 events")
        assert expected in reply

    def test_spiking_root_carries_the_measurements(self):
        # A spiking-only alert opens the thread with the spike, so the root must say how big it is.
        blocks = build_root_message(self._inputs(current_bucket_value="600", computed_baseline="12.5"))["blocks"]
        context_texts = [el["text"] for block in blocks if block["type"] == "context" for el in block["elements"]]
        assert "600 events in the last window vs baseline 12.5" in context_texts

    def test_spiking_reply_without_measurements_stays_short(self):
        assert build_reply_text(self._inputs()) == "📈 Spiking again"

    def test_issue_link_follows_the_fingerprint_when_known(self):
        # A merge deletes the source issue; the fingerprint route redirects to the survivor.
        inputs = AlertDeliveryWorkflowInputs(
            notification_id="notif-1", team_id=1, issue_id="issue-1", event="$error_tracking_issue_created"
        )
        assert issue_url(inputs).endswith("/project/1/error_tracking/issue-1")
        assert issue_url(dataclasses.replace(inputs, fingerprint="")).endswith("/project/1/error_tracking/issue-1")
        with_fingerprint = dataclasses.replace(inputs, fingerprint="a/b c")
        assert issue_url(with_fingerprint).endswith("/project/1/error_tracking/fingerprint/a%2Fb%20c")


class TestSlackThreadDelivery(AlertTestMixin):
    def test_opener_posts_root_and_stores_thread_state(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 1
        client.chat_postMessage.assert_called_once()
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C0123"
        assert "TypeError" in kwargs["text"]
        with team_scope(self.team.id):
            thread = ErrorTrackingAlertThread.objects.get(alert=alert, issue=self.issue)
        assert thread.external_ref == {"channel": "C0123", "ts": "111.222"}
        assert thread.root_headline == "🔴 New issue"
        assert thread.delivered_notification_ids == ["notif-1"]

    def test_reply_posts_into_thread_and_edits_root_on_status_change(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        self._thread(alert)

        delivered = deliver_alert_notifications(
            self._inputs("$error_tracking_issue_resolved", notification_id="notif-2", status="Resolved")
        )

        assert delivered == 1
        reply_kwargs = client.chat_postMessage.call_args.kwargs
        assert reply_kwargs["channel"] == "C0123"
        assert reply_kwargs["thread_ts"] == "111.222"
        assert "Resolved by dev@example.com" in reply_kwargs["text"]
        edit_kwargs = client.chat_update.call_args.kwargs
        assert edit_kwargs["ts"] == "111.222"
        # The headline is the thread's identity: a status edit never changes it.
        assert edit_kwargs["text"].startswith("🔴 New issue")

    def test_redelivered_notification_is_not_posted_twice(self):
        client = self._mock_slack()
        self._create_alert(triggers=["issue_created"])
        inputs = self._inputs("$error_tracking_issue_created")

        assert deliver_alert_notifications(inputs) == 1
        assert deliver_alert_notifications(inputs) == 0

        client.chat_postMessage.assert_called_once()

    def test_unrooted_thread_leaves_reply_unclaimed(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        thread = self._thread(alert, rooted=False)

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_resolved"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()
        thread.refresh_from_db()
        assert thread.delivered_notification_ids == []

    def test_concurrent_opener_waits_for_the_holder_then_replies(self):
        # Two openers for the same issue race into the Slack call. The second must
        # not post a second root: it fails fast while the first holds the claim, and
        # its retry lands as a reply in the first one's thread.
        client = self._mock_slack()
        self._create_alert(triggers=["issue_created", "issue_reopened"])
        first = self._inputs("$error_tracking_issue_created", notification_id="notif-1")
        second = self._inputs("$error_tracking_issue_reopened", notification_id="notif-2")

        def post_while_holding_claim(**kwargs):
            client.chat_postMessage.side_effect = None
            with self.assertRaises(AlertDeliveryError):
                deliver_alert_notifications(second)
            return {"channel": "C0123", "ts": "111.222"}

        client.chat_postMessage.side_effect = post_while_holding_claim
        assert deliver_alert_notifications(first) == 1
        assert deliver_alert_notifications(second) == 1

        assert client.chat_postMessage.call_count == 2
        assert client.chat_postMessage.call_args_list[1].kwargs["thread_ts"] == "111.222"
        with team_scope(self.team.id):
            thread = ErrorTrackingAlertThread.objects.get(issue=self.issue)
        assert thread.delivered_notification_ids == ["notif-1", "notif-2"]
        assert thread.pending_notification_id is None

    @parameterized.expand(
        [
            ("own_live_claim", "notif-1", timedelta(seconds=0), False),
            ("other_live_claim", "notif-other", timedelta(seconds=0), False),
            ("stale_claim", "notif-dead", PENDING_CLAIM_TTL + timedelta(seconds=1), True),
        ]
    )
    def test_live_claims_block_everyone_until_stale(self, _name, holder, age, proceeds):
        # Even this notification's own retry waits: a timed-out attempt may still be
        # mid-post when Temporal starts the retry.
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        thread = self._thread(alert, rooted=False)
        thread.pending_notification_id = holder
        thread.pending_claimed_at = timezone.now() - age
        thread.save()

        if proceeds:
            assert deliver_alert_notifications(self._inputs("$error_tracking_issue_created")) == 1
            client.chat_postMessage.assert_called_once()
            thread.refresh_from_db()
            assert thread.pending_notification_id is None
            assert thread.delivered_notification_ids == ["notif-1"]
        else:
            with self.assertRaises(AlertDeliveryError):
                deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))
            client.chat_postMessage.assert_not_called()
            thread.refresh_from_db()
            assert thread.pending_notification_id == holder

    def test_superseded_holder_does_not_overwrite_the_successor(self):
        # A holder that stalls past the TTL loses the claim; when it resumes and
        # finishes posting, its save must not clobber whatever the successor wrote.
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        thread = self._thread(alert, rooted=False)

        def takeover_during_post(**kwargs):
            with team_scope(self.team.id):
                ErrorTrackingAlertThread.objects.filter(id=thread.id).update(
                    pending_notification_id="notif-successor", pending_claimed_at=timezone.now()
                )
            return {"channel": "C0123", "ts": "111.222"}

        client.chat_postMessage.side_effect = takeover_during_post
        assert deliver_alert_notifications(self._inputs("$error_tracking_issue_created")) == 1

        thread.refresh_from_db()
        assert thread.pending_notification_id == "notif-successor"
        assert thread.external_ref == {}
        assert thread.delivered_notification_ids == []

    def test_retry_schedule_outlasts_the_claim_ttl(self):
        # A busy loser must still be retrying when a dead holder's claim goes stale,
        # otherwise the notification is dropped for good.
        policy = ACTIVITY_RETRY_POLICY
        assert policy.maximum_interval is not None
        interval = policy.initial_interval
        total = timedelta(0)
        for _ in range(policy.maximum_attempts - 1):
            total += interval
            interval = min(interval * policy.backoff_coefficient, policy.maximum_interval)
        assert total > PENDING_CLAIM_TTL

    def test_failed_post_releases_the_claim(self):
        client = self._mock_slack()
        client.chat_postMessage.side_effect = RuntimeError("slack down")
        alert = self._create_alert(triggers=["issue_created"])

        with self.assertRaises(AlertDeliveryError):
            deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        with team_scope(self.team.id):
            thread = ErrorTrackingAlertThread.objects.get(alert=alert, issue=self.issue)
        assert thread.pending_notification_id is None
        assert thread.external_ref == {}

    def test_retry_after_failed_root_post_roots_the_thread(self):
        # A crash between the thread insert and the root post must not wedge the
        # destination: the next opener attempt roots the existing row.
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        thread = self._thread(alert, rooted=False)

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 1
        assert client.chat_postMessage.call_args.kwargs["channel"] == "C0123"
        thread.refresh_from_db()
        assert thread.external_ref == {"channel": "C0123", "ts": "111.222"}
        assert thread.delivered_notification_ids == ["notif-1"]

    def test_root_header_stays_within_slack_limit(self):
        client = self._mock_slack()
        self._create_alert(triggers=["issue_created"])

        deliver_alert_notifications(self._inputs("$error_tracking_issue_created", issue_name="x" * 400))

        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        header = next(block for block in blocks if block["type"] == "header")
        assert len(header["text"]["text"]) <= 150

    def test_repointed_destination_replies_in_original_channel(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        self._thread(alert)
        with team_scope(self.team.id):
            destination = alert.destinations.get()
            destination.config = {"channel": "C0456"}
            destination.save()

        deliver_alert_notifications(self._inputs("$error_tracking_issue_resolved", notification_id="notif-2"))

        # A provider thread cannot move: replies stay in the thread's own channel.
        assert client.chat_postMessage.call_args.kwargs["channel"] == "C0123"

    def test_missing_integration_skips_without_raising(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            alert.destinations.update(integration=None)

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()

    def test_failed_destination_does_not_block_others_and_surfaces_for_retry(self):
        client = self._mock_slack()
        alert = self._create_alert(triggers=["issue_created"])
        with team_scope(self.team.id):
            alert.destinations.create(
                team=self.team,
                channel_type="slack",
                integration=self.integration,
                config={"channel": "C0456"},
            )
        client.chat_postMessage.side_effect = [Exception("channel archived"), {"channel": "C0456", "ts": "333.444"}]

        with self.assertRaises(AlertDeliveryError):
            deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert client.chat_postMessage.call_count == 2
        with team_scope(self.team.id):
            rooted = [t for t in ErrorTrackingAlertThread.objects.filter(issue=self.issue) if t.external_ref.get("ts")]
        assert len(rooted) == 1


class TestAlertFilterEvaluation(AlertTestMixin):
    def _create_filtered_alert(self, filters: dict, *, triggers=None) -> ErrorTrackingAlert:
        compiled = compile_filters_bytecode(dict(filters), self.team)
        assert not compiled.get("bytecode_error"), compiled
        with team_scope(self.team.id):
            alert = ErrorTrackingAlert.objects.create(
                team=self.team,
                name="Filtered",
                triggers=triggers if triggers is not None else ["issue_created"],
                filters=compiled,
            )
            alert.destinations.create(
                team=self.team, channel_type="slack", integration=self.integration, config={"channel": "C0123"}
            )
        return alert

    def _patch_exception_properties(self, properties: dict):
        fetcher = patch(
            "products.error_tracking.backend.temporal.alerts.delivery.fetch_exception_properties",
            return_value=properties,
        )
        mock = fetcher.start()
        self.addCleanup(fetcher.stop)
        return mock

    ENVIRONMENT_FILTER = {"properties": [{"key": "environment", "value": "production", "type": "event"}]}

    def test_matching_event_property_filter_opens_a_thread(self):
        client = self._mock_slack()
        self._create_filtered_alert(self.ENVIRONMENT_FILTER)
        self._patch_exception_properties({"environment": "production"})

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 1
        client.chat_postMessage.assert_called_once()

    def test_non_matching_filter_skips_the_opener_and_leaves_no_thread(self):
        client = self._mock_slack()
        self._create_filtered_alert(self.ENVIRONMENT_FILTER)
        self._patch_exception_properties({"environment": "staging"})

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()
        with team_scope(self.team.id):
            assert not ErrorTrackingAlertThread.objects.filter(issue=self.issue).exists()

    def test_exception_timestamp_filter_sees_the_lifecycle_value(self):
        # Spiking carries the detection time as exception_timestamp on the lifecycle
        # event; the exception's own time is only the fetch anchor. Filters must see
        # the same value the CDP path sees.
        client = self._mock_slack()
        self._create_filtered_alert(
            {"properties": [{"key": "exception_timestamp", "value": "2026-07-21T15:00:00+00:00", "type": "event"}]},
            triggers=["issue_spiking"],
        )
        self._patch_exception_properties({})

        delivered = deliver_alert_notifications(
            self._inputs(
                "$error_tracking_issue_spiking",
                event_timestamp="2026-07-21T14:00:00+00:00",
                lifecycle_timestamp="2026-07-21T15:00:00+00:00",
            )
        )

        assert delivered == 1
        client.chat_postMessage.assert_called_once()

    def test_exception_timestamp_filter_falls_back_to_the_event_time(self):
        # Payloads from before lifecycle_timestamp existed still evaluate the filter.
        client = self._mock_slack()
        self._create_filtered_alert(
            {"properties": [{"key": "exception_timestamp", "value": "2026-07-21T14:00:00+00:00", "type": "event"}]}
        )
        self._patch_exception_properties({})

        delivered = deliver_alert_notifications(
            self._inputs("$error_tracking_issue_created", event_timestamp="2026-07-21T14:00:00+00:00")
        )

        assert delivered == 1
        client.chat_postMessage.assert_called_once()

    def test_property_fetch_failure_does_not_block_unfiltered_alerts(self):
        client = self._mock_slack()
        self._create_alert(triggers=["issue_created"])
        self._create_filtered_alert(self.ENVIRONMENT_FILTER)
        fetcher = self._patch_exception_properties({"environment": "production"})
        fetcher.side_effect = RuntimeError("clickhouse unavailable")
        inputs = self._inputs("$error_tracking_issue_created")

        # The unfiltered alert posts now; the activity still fails so the filtered one is retried.
        with self.assertRaises(AlertDeliveryError):
            deliver_alert_notifications(inputs)
        assert client.chat_postMessage.call_count == 1

        fetcher.side_effect = None
        assert deliver_alert_notifications(inputs) == 1
        assert client.chat_postMessage.call_count == 2

    def test_issue_field_filter_evaluates_from_the_lifecycle_snapshot(self):
        client = self._mock_slack()
        self._create_filtered_alert({"properties": [{"key": "severity", "value": "critical", "type": "event"}]})
        fetcher = self._patch_exception_properties({})

        skipped = deliver_alert_notifications(self._inputs("$error_tracking_issue_created", severity="low"))
        delivered = deliver_alert_notifications(
            self._inputs("$error_tracking_issue_created", notification_id="notif-2", severity="critical")
        )

        assert (skipped, delivered) == (0, 1)
        client.chat_postMessage.assert_called_once()
        assert fetcher.call_count == 2

    def test_lifecycle_only_properties_are_filterable(self):
        client = self._mock_slack()
        self._create_filtered_alert(
            {"properties": [{"key": "computed_baseline", "value": "10", "type": "event"}]},
            triggers=["issue_spiking"],
        )
        self._patch_exception_properties({})

        skipped = deliver_alert_notifications(
            self._inputs("$error_tracking_issue_spiking", extra={"computed_baseline": "99"})
        )
        delivered = deliver_alert_notifications(
            self._inputs("$error_tracking_issue_spiking", notification_id="n-2", extra={"computed_baseline": "10"})
        )

        assert (skipped, delivered) == (0, 1)
        client.chat_postMessage.assert_called_once()

    def test_replies_are_never_filtered(self):
        client = self._mock_slack()
        alert = self._create_filtered_alert(self.ENVIRONMENT_FILTER)
        self._thread(alert)
        fetcher = self._patch_exception_properties({"environment": "staging"})

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_resolved"))

        assert delivered == 1
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "111.222"
        # Replies follow the thread: no opener planned, so nothing was fetched.
        fetcher.assert_not_called()

    def test_unfiltered_alerts_never_fetch_event_properties(self):
        client = self._mock_slack()
        self._create_alert(triggers=["issue_created"])
        fetcher = self._patch_exception_properties({})

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 1
        client.chat_postMessage.assert_called_once()
        fetcher.assert_not_called()

    def test_broken_bytecode_fails_closed(self):
        client = self._mock_slack()
        alert = self._create_filtered_alert(self.ENVIRONMENT_FILTER)
        with team_scope(self.team.id):
            alert.filters = {**alert.filters, "bytecode": ["not-bytecode"]}
            alert.save()
        self._patch_exception_properties({"environment": "production"})

        delivered = deliver_alert_notifications(self._inputs("$error_tracking_issue_created"))

        assert delivered == 0
        client.chat_postMessage.assert_not_called()


class TestAlertDeliveryDispatch(AlertTestMixin):
    def _dispatch(self) -> None:
        start_alert_delivery_workflow(
            team_id=self.team.id,
            event="$error_tracking_issue_created",
            issue_id=str(self.issue.id),
            notification_id="notif-1",
        )

    def test_dispatch_skips_teams_without_enabled_alerts(self):
        self._create_alert(enabled=False)
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True) as flag,
        ):
            self._dispatch()
        connect.assert_not_called()
        # The row gate runs first, so teams without alerts never evaluate the flag.
        flag.assert_not_called()

    def test_dispatch_skips_teams_outside_the_flag(self):
        self._create_alert()
        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect") as connect,
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=False),
        ):
            self._dispatch()
        connect.assert_not_called()

    def test_dispatch_starts_idempotent_workflow(self):
        self._create_alert()
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                new_callable=AsyncMock,
                return_value=client,
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            self._dispatch()

        client.start_workflow.assert_called_once()
        args, kwargs = client.start_workflow.call_args
        assert args[0] == "error-tracking-alert-delivery"
        assert args[1].notification_id == "notif-1"
        assert kwargs["id"] == "error-tracking-alert-delivery-notif-1"
        # Delivery must never ride the lifecycle fleet: slow Slack retries would starve issue-state work.
        assert kwargs["task_queue"] == settings.ERROR_TRACKING_TASK_QUEUE
        # A redelivered start after completion must be rejected, not rerun.
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY

    def test_dispatch_gives_up_on_a_stalled_temporal(self):
        self._create_alert()

        async def hang() -> None:
            await asyncio.sleep(5)

        with (
            patch("products.error_tracking.backend.temporal.alerts.dispatch.async_connect", side_effect=hang),
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.DISPATCH_TIMEOUT", timedelta(milliseconds=50)
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            started = time.monotonic()
            self._dispatch()

        # The web worker gets its thread back well before the stalled connect would return.
        assert time.monotonic() - started < 2

    def test_dispatch_swallows_temporal_errors(self):
        self._create_alert()
        with (
            patch(
                "products.error_tracking.backend.temporal.alerts.dispatch.async_connect",
                side_effect=RuntimeError("temporal down"),
            ),
            patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True),
        ):
            self._dispatch()
