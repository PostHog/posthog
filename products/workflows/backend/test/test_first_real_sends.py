from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import ANY, MagicMock, patch

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models.team.team import Team
from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.tasks import capture_workflow_first_real_sends
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.first_real_sends import FIRST_REAL_SEND_CUTOFF, FirstRealSendCaptureError
from products.workflows.backend.tasks.workflow_email_health import FIRST_REAL_SENDS_LOCK_KEY

SERVICE = "products.workflows.backend.services.first_real_sends"
NOW = FIRST_REAL_SEND_CUTOFF + timedelta(days=3)
ENTRY_ATTEMPT_ID = UUID("6f1c4a52-0d7e-4b8a-9c3d-2e5f8a1b7c90")


def captured_events(scoped_capture: MagicMock) -> list[dict]:
    capture = scoped_capture.return_value.__enter__.return_value
    return [call.kwargs for call in capture.call_args_list]


@time_machine.travel(NOW, tick=False)
class TestCaptureWorkflowFirstRealSends(ClickhouseTestMixin, BaseTest):
    def _flow(
        self, created_at=FIRST_REAL_SEND_CUTOFF + timedelta(minutes=1), entry_attempt_id: UUID | None = None
    ) -> HogFlow:
        flow = HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            created_by=self.user,
            status=HogFlow.State.ACTIVE,
            origin_product="broadcasts",
            entry_attempt_id=entry_attempt_id,
        )
        HogFlow.objects.filter(pk=flow.pk).update(created_at=created_at)
        return flow

    def _metric(
        self,
        flow: HogFlow,
        at,
        metric_name: str = "billable_invocation",
        metric_kind: str = "email",
        app_source: str = "hog_flow",
    ) -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source=app_source,
            app_source_id=str(flow.id),
            metric_kind=metric_kind,
            metric_name=metric_name,
            timestamp=at,
        )

    @parameterized.expand(
        [
            ("with_entry_attempt", ENTRY_ATTEMPT_ID, False),
            ("without_entry_attempt", None, False),
            ("over_the_http_transport", ENTRY_ATTEMPT_ID, True),
        ]
    )
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_first_run_records_the_first_billable_email_and_captures_it_once(
        self, _name: str, entry_attempt_id: UUID | None, use_http: bool, scoped_capture: MagicMock
    ) -> None:
        flow = self._flow(entry_attempt_id=entry_attempt_id)
        first_send = (NOW - timedelta(hours=20)).replace(microsecond=0)
        self._metric(flow, NOW - timedelta(days=2, hours=1))
        self._metric(flow, NOW - timedelta(hours=22), metric_name="succeeded")
        self._metric(flow, NOW - timedelta(hours=22), metric_kind="sms")
        self._metric(flow, NOW - timedelta(hours=22), app_source="hog_function")
        self._metric(flow, first_send)
        self._metric(flow, NOW - timedelta(hours=2))

        test_depth = len(connection.atomic_blocks)
        capture_depths: list[int] = []
        scoped_capture.return_value.__enter__.return_value.side_effect = lambda **_: capture_depths.append(
            len(connection.atomic_blocks)
        )

        with override_settings(CLICKHOUSE_USE_HTTP=use_http):
            capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at == first_send
        assert capture_depths == [test_depth]
        [event] = captured_events(scoped_capture)
        assert event["event"] == "workflow first real send"
        assert event["distinct_id"] == str(self.team.uuid)
        assert event["timestamp"] == first_send
        assert event["groups"]["organization"] == str(self.organization.id)
        assert event["properties"] == {
            "hog_flow_id": str(flow.id),
            "entry_attempt_id": str(entry_attempt_id) if entry_attempt_id else None,
            "origin_product": "broadcasts",
            "first_real_send_at": first_send.isoformat(),
            "$ignore_sent_at": True,
        }

        scoped_capture.reset_mock()
        capture_workflow_first_real_sends()

        assert captured_events(scoped_capture) == []
        flow.refresh_from_db()
        assert flow.first_real_send_at == first_send

    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_one_lookup_reads_the_workflows_of_every_team_and_keeps_each_id_with_its_team(
        self, scoped_capture: MagicMock
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        flow = self._flow()
        other_flow = self._flow()
        unsent_flow = self._flow()
        HogFlow.objects.filter(pk__in=[other_flow.pk, unsent_flow.pk]).update(team=other_team)
        self._metric(flow, NOW - timedelta(hours=2))
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_flow",
            app_source_id=str(unsent_flow.id),
            metric_kind="email",
            metric_name="billable_invocation",
            timestamp=NOW - timedelta(hours=3),
        )
        create_app_metric2(
            team_id=other_team.pk,
            app_source="hog_flow",
            app_source_id=str(other_flow.id),
            metric_kind="email",
            metric_name="billable_invocation",
            timestamp=NOW - timedelta(hours=1),
        )

        with CaptureQueriesContext(connection) as queries:
            capture_workflow_first_real_sends()

        flow.refresh_from_db()
        other_flow.refresh_from_db()
        unsent_flow.refresh_from_db()
        assert flow.first_real_send_at == (NOW - timedelta(hours=2)).replace(microsecond=0)
        assert other_flow.first_real_send_at == (NOW - timedelta(hours=1)).replace(microsecond=0)
        assert unsent_flow.first_real_send_at is None
        assert sorted(event["properties"]["hog_flow_id"] for event in captured_events(scoped_capture)) == sorted(
            [str(flow.id), str(other_flow.id)]
        )
        assert [query["sql"] for query in queries if query["sql"].startswith('SELECT "posthog_hogflow"')] == [ANY]

    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_skips_workflows_created_before_the_cutoff(self, scoped_capture: MagicMock) -> None:
        flow = self._flow(created_at=FIRST_REAL_SEND_CUTOFF - timedelta(minutes=1))
        self._metric(flow, NOW - timedelta(hours=2))

        capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []

    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_run_that_overlaps_another_records_and_captures_nothing(self, scoped_capture: MagicMock) -> None:
        flow = self._flow()
        self._metric(flow, NOW - timedelta(hours=2))
        cache.add(FIRST_REAL_SENDS_LOCK_KEY, "running")

        try:
            capture_workflow_first_real_sends()
        finally:
            cache.delete(FIRST_REAL_SENDS_LOCK_KEY)

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []

    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_clickhouse_failure_leaves_the_column_unset(self, scoped_capture: MagicMock) -> None:
        flow = self._flow()
        self._metric(flow, NOW - timedelta(hours=2))

        with patch(f"{SERVICE}.sync_execute", side_effect=ConnectionError("ClickHouse is down")):
            with self.assertRaises(ConnectionError):
                capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []

    @patch(f"{SERVICE}.CANDIDATE_BATCH_SIZE", 1)
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_failed_flush_leaves_its_workflows_unstamped_and_later_batches_still_capture(
        self, scoped_capture: MagicMock
    ) -> None:
        flows = [self._flow(), self._flow()]
        for flow in flows:
            self._metric(flow, NOW - timedelta(hours=2))
        queued: list[str] = []
        flushes: list[list[str]] = []
        scoped_capture.return_value.__enter__.return_value.side_effect = lambda **event: queued.append(
            event["properties"]["hog_flow_id"]
        )

        def flush(*_) -> None:
            flushes.append(queued.copy())
            queued.clear()
            if len(flushes) == 1:
                raise ConnectionError("capture is down")

        scoped_capture.return_value.__exit__.side_effect = flush

        with self.assertRaises(FirstRealSendCaptureError):
            capture_workflow_first_real_sends()

        [lost, delivered] = flushes
        stamped = {
            str(flow.id)
            for flow in HogFlow.objects.filter(pk__in=[flow.id for flow in flows]).exclude(first_real_send_at=None)
        }
        assert stamped == set(delivered)
        assert sorted(lost + delivered) == sorted(str(flow.id) for flow in flows)

    @patch(f"{SERVICE}.CANDIDATE_BATCH_SIZE", 1)
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_postgres_failure_in_one_batch_fails_the_run_after_the_others(self, scoped_capture: MagicMock) -> None:
        flows = [self._flow(), self._flow()]
        for flow in flows:
            self._metric(flow, NOW - timedelta(hours=2))
            self._metric(flow, NOW + timedelta(hours=20))
        flow_ids = {flow.id for flow in flows}
        with connection.cursor() as cursor:
            cursor.execute("CREATE SEQUENCE first_real_send_test_updates")
            cursor.execute(
                """
                CREATE FUNCTION first_real_send_test_reject_first_update() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF nextval('first_real_send_test_updates') = 1 THEN
                        RAISE EXCEPTION 'Postgres rejected the update';
                    END IF;
                    RETURN NEW;
                END
                $$
                """
            )
            cursor.execute(
                "CREATE TRIGGER first_real_send_test_reject_first_update BEFORE UPDATE OF first_real_send_at"
                " ON posthog_hogflow FOR EACH ROW EXECUTE FUNCTION first_real_send_test_reject_first_update()"
            )

        with self.assertRaises(DatabaseError):
            capture_workflow_first_real_sends()

        stamped = {flow.id for flow in HogFlow.objects.filter(pk__in=flow_ids, first_real_send_at__isnull=False)}
        assert len(stamped) == 1
        first_events = {event["properties"]["hog_flow_id"]: event for event in captured_events(scoped_capture)}
        assert set(first_events) == {str(flow_id) for flow_id in flow_ids}

        scoped_capture.reset_mock()
        with time_machine.travel(NOW + timedelta(days=1), tick=False):
            capture_workflow_first_real_sends()

        assert HogFlow.objects.filter(pk__in=flow_ids, first_real_send_at__isnull=True).count() == 0
        [retried] = captured_events(scoped_capture)
        first_event = first_events[retried["properties"]["hog_flow_id"]]
        assert (retried["uuid"], retried["timestamp"]) == (first_event["uuid"], first_event["timestamp"])
