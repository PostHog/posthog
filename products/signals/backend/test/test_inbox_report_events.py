from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import OperationalError, connection
from django.test import override_settings
from django.utils import timezone

from confluent_kafka import KafkaError, KafkaException
from parameterized import parameterized

from posthog.kafka_client.client import KafkaProducerForTests
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CDP_INTERNAL_EVENTS
from posthog.models.team.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.inbox_report_events import (
    emit_inbox_report_ready_event,
    reconcile_stranded_ready_events,
    send_inbox_report_ready_events,
)
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.tasks import retry_inbox_report_ready_event
from products.signals.backend.test.inbox_report_events_recorder import (
    inbox_report_ready_events,
    recorded_internal_events,
)


@contextmanager
def celery_runs_every_retry() -> Iterator[None]:
    conf = retry_inbox_report_ready_event.app.conf
    propagates = conf["task_eager_propagates"]
    conf["task_eager_propagates"] = False
    try:
        yield
    finally:
        conf["task_eager_propagates"] = propagates


class TestInboxReportReadyEvent(BaseTest):
    def _report(self, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=status, title="Checkout errors", summary="Summary")

    @override_settings(SITE_URL="https://app.example.com")
    def test_a_settled_report_reaches_destinations_once(self):
        report = self._report()

        with recorded_internal_events() as (sent, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])

        assert len(sent) == 1
        assert sent[0]["team_id"] == self.team.id
        assert sent[0]["event"]["event"] == "$inbox_report_ready"
        assert sent[0]["event"]["properties"] == {
            "report_id": str(report.id),
            "title": "Checkout errors",
            "summary": "Summary",
            "priority": None,
            "source_products": ["scout"],
            "report_url": f"https://app.example.com/project/{self.team.id}/inbox/reports/{report.id}?link_source=destination",
        }
        report.refresh_from_db()
        assert report.ready_event_delivered_at is not None

    @parameterized.expand(
        [("nothing hidden", None), ("a layer its scout hid from the inbox", 2), ("a plan its scout hid", 0)]
    )
    def test_a_settled_plan_sends_each_of_its_layers_once(self, _name: str, hidden: int | None):
        plan = self._report()
        layer_ids = create_layer_reports(
            parent=plan,
            layers=[
                ReportLayer(title="feat(x): schema", scope="Add the schema."),
                ReportLayer(title="feat(x): api", scope="Add the API.", depends_on=0),
            ],
            attribution=ArtefactAttribution.system(),
        )
        report_ids = [str(plan.id), *layer_ids]
        if hidden is not None:
            self._hide_from_inbox(SignalReport.objects.get(id=report_ids[hidden]))

        with recorded_internal_events() as (sent, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(plan.id), source_products=["scout"])
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(plan.id), source_products=["scout"])

        assert [(event["report_id"], event["source_products"]) for event in inbox_report_ready_events(sent)] == [
            (report_id, ["scout"]) for index, report_id in enumerate(report_ids) if hidden not in (0, index)
        ]

    def _hide_from_inbox(self, report: SignalReport) -> None:
        config = SignalScoutConfig.objects.create(
            team=self.team, skill_name="signals-scout-digest", output_destinations={"inbox": False}
        )
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, title="scout", description="d")
        SignalScoutRun.objects.create(
            team=self.team,
            task_run=apps.get_model("tasks", "TaskRun").objects.create(team=self.team, task=task),
            scout_config=config,
            skill_name=config.skill_name,
            skill_version=1,
            emitted_report_ids=[str(report.id)],
        )

    @parameterized.expand(
        [
            ("flag off", SignalReport.Status.READY, False, False, False),
            ("not ready", SignalReport.Status.IN_PROGRESS, True, False, False),
            ("scout keeps its reports out of the inbox", SignalReport.Status.READY, True, True, False),
            ("instance opted out of PostHog's analytics", SignalReport.Status.READY, None, False, True),
        ]
    )
    def test_nothing_is_sent(
        self, _name: str, status: str, flag_enabled: bool | None, hidden_from_inbox: bool, analytics_disabled: bool
    ):
        report = self._report(status)
        if hidden_from_inbox:
            self._hide_from_inbox(report)

        with (
            recorded_internal_events(flag_enabled=flag_enabled) as (sent, _),
            patch("posthoganalytics.disabled", analytics_disabled),
        ):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])

        report.refresh_from_db()
        assert sent == []
        assert report.ready_event_emitted_at is None

    def test_a_report_that_could_not_be_claimed_is_left_to_the_callers_retry(self):
        with recorded_internal_events() as (sent, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id="not-a-report-id", source_products=[])
            with pytest.raises(ValidationError):
                send_inbox_report_ready_events(team_id=self.team.id, report_id="not-a-report-id", source_products=[])

        assert sent == []

    @parameterized.expand([("one failed read", 1), ("an outage across many retries", 20)])
    def test_a_report_the_database_failed_to_claim_is_sent_by_the_retry(self, _name: str, failed_reads: int):
        report = self._report()
        failed: list[str] = []

        def database_is_down_for_a_while(execute, sql, params, many, context):
            if len(failed) < failed_reads and SignalScoutRun._meta.db_table in sql:
                failed.append(sql)
                raise OperationalError("server closed the connection unexpectedly")
            return execute(sql, params, many, context)

        with (
            recorded_internal_events() as (sent, _),
            connection.execute_wrapper(database_is_down_for_a_while),
            celery_runs_every_retry(),
        ):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])

        assert len(failed) == failed_reads
        assert [(event["report_id"], event["source_products"]) for event in inbox_report_ready_events(sent)] == [
            (str(report.id), ["scout"])
        ]
        report.refresh_from_db()
        assert report.ready_event_delivered_at is not None

    def test_only_the_project_the_flag_is_on_for_sends_its_reports(self):
        other_team = Team.objects.create(organization=self.organization)
        report = self._report()
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY, title="t")

        with recorded_internal_events() as (sent, flag):
            flag.side_effect = lambda *args, groups, **kwargs: groups["project"] == str(self.team.id)
            for team_id, report_id in [(self.team.id, report.id), (other_team.id, other_report.id)]:
                emit_inbox_report_ready_event(team_id=team_id, report_id=str(report_id), source_products=[])

        assert [event["report_id"] for event in inbox_report_ready_events(sent)] == [str(report.id)]

    @parameterized.expand([("rejects it",), ("never confirms it",), ("refuses it",), ("fails to flush",)])
    def test_the_sweep_sends_again_an_event_the_broker(self, fault: str):
        report = self._report()
        accept = KafkaProducerForTests.produce

        def faulty_produce(producer, topic, value, key=None, headers=None, on_delivery=None):
            if fault == "refuses it":
                raise BufferError("Local: Queue full")
            if fault == "rejects it" and on_delivery:
                on_delivery(KafkaError(KafkaError._MSG_TIMED_OUT), None)  # type: ignore[attr-defined]
            elif fault != "never confirms it":
                accept(producer, topic, value, key=key, headers=headers, on_delivery=on_delivery)

        def faulty_flush(producer, timeout=None):
            if fault == "fails to flush":
                raise KafkaException(KafkaError(KafkaError._TRANSPORT))  # type: ignore[attr-defined]
            return 0

        with (
            patch.object(get_producer(topic=KAFKA_CDP_INTERNAL_EVENTS), "_test", False),
            patch.object(KafkaProducerForTests, "produce", faulty_produce),
            patch.object(KafkaProducerForTests, "flush", faulty_flush),
            recorded_internal_events() as (first, _),
        ):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])
        report.refresh_from_db()
        assert report.ready_event_delivered_at is None
        SignalReport.objects.filter(id=report.id).update(ready_event_emitted_at=timezone.now() - timedelta(hours=1))

        with recorded_internal_events() as (resent, _):
            reconcile_stranded_ready_events()
            reconcile_stranded_ready_events()

        assert [event["event"]["uuid"] for event in resent] == [first[0]["event"]["uuid"]]
        assert resent[0]["event"]["properties"]["source_products"] == ["scout"]
        report.refresh_from_db()
        assert report.ready_event_delivered_at is not None

    @parameterized.expand(
        [
            ("report no longer ready", SignalReport.Status.IN_PROGRESS, True, False),
            ("destinations turned off", SignalReport.Status.READY, False, False),
            ("scout hid the report from the inbox", SignalReport.Status.READY, True, True),
        ]
    )
    def test_the_sweep_releases_a_claim_it_must_not_send(
        self, _name: str, status: str, flag_enabled: bool, hidden_from_inbox: bool
    ):
        report = self._report()
        if hidden_from_inbox:
            self._hide_from_inbox(report)
        SignalReport.objects.filter(id=report.id).update(
            status=status,
            ready_event_emitted_at=timezone.now() - timedelta(hours=1),
            ready_event_source_products=["scout"],
        )

        with recorded_internal_events(flag_enabled=flag_enabled) as (swept, _):
            reconcile_stranded_ready_events()

        report.refresh_from_db()
        assert swept == []
        assert report.ready_event_emitted_at is None

    def test_a_report_settled_while_its_flag_could_not_be_evaluated_is_sent_once_the_flag_answers(self):
        report = self._report()
        stale = timezone.now() - timedelta(hours=1)

        with recorded_internal_events(flag_enabled=None) as (unknown, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])
            SignalReport.objects.filter(id=report.id).update(ready_event_emitted_at=stale)
            reconcile_stranded_ready_events()
        report.refresh_from_db()
        assert report.ready_event_emitted_at is not None and report.ready_event_emitted_at > stale
        SignalReport.objects.filter(id=report.id).update(ready_event_emitted_at=stale)
        with recorded_internal_events() as (recovered, _):
            reconcile_stranded_ready_events()

        assert unknown == []
        assert [(event["report_id"], event["source_products"]) for event in inbox_report_ready_events(recovered)] == [
            (str(report.id), ["scout"])
        ]

    def test_the_sweep_stops_checking_projects_once_its_time_runs_out(self):
        other_team = Team.objects.create(organization=self.organization)
        first = self._report()
        later = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY, title="t", summary="s")
        stale = timezone.now() - timedelta(hours=1)
        SignalReport.objects.filter(id=first.id).update(ready_event_emitted_at=stale - timedelta(minutes=1))
        SignalReport.objects.filter(id=later.id).update(ready_event_emitted_at=stale)
        clock = [0.0]

        def slow_flag_check(*args, **kwargs) -> bool:
            clock[0] += timedelta(hours=1).total_seconds()
            return True

        with (
            patch("products.signals.backend.inbox_report_events.time") as fake_time,
            recorded_internal_events() as (sent, flag),
        ):
            fake_time.monotonic.side_effect = lambda: clock[0]
            flag.side_effect = slow_flag_check
            reconcile_stranded_ready_events()

        later.refresh_from_db()
        assert [event["report_id"] for event in inbox_report_ready_events(sent)] == [str(first.id)]
        assert later.ready_event_emitted_at == stale
