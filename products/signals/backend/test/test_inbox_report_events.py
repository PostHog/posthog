from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.inbox_report_events import emit_inbox_report_ready_event, reconcile_stranded_ready_events
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.test.inbox_report_events_recorder import (
    inbox_report_ready_events,
    recorded_internal_events,
)


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

    def test_a_settled_plan_sends_each_of_its_layers_once(self):
        plan = self._report()
        layer_ids = create_layer_reports(
            parent=plan,
            layers=[
                ReportLayer(title="feat(x): schema", scope="Add the schema."),
                ReportLayer(title="feat(x): api", scope="Add the API.", depends_on=0),
            ],
            attribution=ArtefactAttribution.system(),
        )

        with recorded_internal_events() as (sent, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(plan.id), source_products=["scout"])
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(plan.id), source_products=["scout"])

        assert [(event["report_id"], event["source_products"]) for event in inbox_report_ready_events(sent)] == [
            (str(plan.id), ["scout"]),
            (layer_ids[0], ["scout"]),
            (layer_ids[1], ["scout"]),
        ]

    @parameterized.expand(
        [
            ("flag off", SignalReport.Status.READY, False),
            ("not ready", SignalReport.Status.IN_PROGRESS, True),
        ]
    )
    def test_nothing_is_sent(self, _name: str, status: str, flag_enabled: bool):
        report = self._report(status)

        with recorded_internal_events(flag_enabled=flag_enabled) as (sent, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])

        assert sent == []

    def test_the_flag_is_checked_for_the_reports_project(self):
        report = self._report()

        with recorded_internal_events() as (_, flag):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=[])

        assert flag.call_args.kwargs["groups"] == {
            "organization": str(self.organization.id),
            "project": str(self.team.id),
        }

    def test_the_sweep_resends_a_stale_unconfirmed_claim_with_the_same_uuid(self):
        report = self._report()
        with recorded_internal_events() as (first, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])
        SignalReport.objects.filter(id=report.id).update(
            ready_event_emitted_at=timezone.now() - timedelta(hours=1), ready_event_delivered_at=None
        )

        with recorded_internal_events() as (resent, _):
            reconcile_stranded_ready_events()
            reconcile_stranded_ready_events()

        assert [event["event"]["uuid"] for event in resent] == [first[0]["event"]["uuid"]]
        assert resent[0]["event"]["properties"]["source_products"] == ["scout"]

    def test_the_sweep_releases_a_claim_whose_report_is_no_longer_ready(self):
        report = self._report()
        SignalReport.objects.filter(id=report.id).update(
            status=SignalReport.Status.IN_PROGRESS,
            ready_event_emitted_at=timezone.now() - timedelta(hours=1),
            ready_event_source_products=["scout"],
        )

        with recorded_internal_events() as (swept, _):
            reconcile_stranded_ready_events()
        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.READY)
        with recorded_internal_events() as (settled, _):
            emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(report.id), source_products=["scout"])

        assert swept == []
        assert len(settled) == 1
