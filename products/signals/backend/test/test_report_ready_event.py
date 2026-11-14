import json
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dbrouter import ReplicaRouter

from products.cdp.backend.internal_events import internal_event_read_scope
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.receivers import _is_safety_suppressed
from products.signals.backend.report_ready_event import (
    REPORT_READY_EVENT,
    SOURCE_PRODUCTS_TIMEOUT_SECONDS,
    emit_report_ready_event,
)
from products.signals.backend.signal_metadata import ReportSignalMeta, fetch_source_products_for_reports

S = SignalReport.Status
MODULE = "products.signals.backend.report_ready_event"


def _transition(status: SignalReport.Status, **kwargs: Any) -> Callable[[SignalReport], None]:
    def run(report: SignalReport) -> None:
        report.save(update_fields=report.transition_to(status, **kwargs))

    return run


def _set_status_full_save(status: SignalReport.Status) -> Callable[[SignalReport], None]:
    def run(report: SignalReport) -> None:
        report.status = status
        report.save()

    return run


def _edit_title(report: SignalReport) -> None:
    report.title = "Checkout fails on Safari"
    report.save(update_fields=["title", "updated_at"])


def _full_save(report: SignalReport) -> None:
    report.save()


class TestReportReadyEvent(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        produce_patch = patch(f"{MODULE}.produce_internal_event")
        flag_patch = patch(f"{MODULE}.feature_enabled_or_false", return_value=True)
        source_products_patch = patch(f"{MODULE}.fetch_source_products_for_reports", return_value={})
        self.produce = produce_patch.start()
        self.flag = flag_patch.start()
        self.source_products = source_products_patch.start()
        self.addCleanup(produce_patch.stop)
        self.addCleanup(flag_patch.stop)
        self.addCleanup(source_products_patch.stop)

    def _report(self, status: SignalReport.Status) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=status, title="Checkout fails", summary="Summary")

    def _artefact(self, report: SignalReport, artefact_type: str, content: object) -> None:
        SignalReportArtefact.objects.create(
            team=self.team, report=report, type=artefact_type, content=json.dumps(content)
        )

    def _produced_events(self) -> list[str]:
        return [call.kwargs["event"].event for call in self.produce.call_args_list]

    @parameterized.expand(
        [
            ("in_progress_to_ready", S.IN_PROGRESS, _transition(S.READY, title="Checkout fails", summary="S"), 1),
            ("resolved_reopened_to_ready", S.RESOLVED, _transition(S.READY), 1),
            ("suppressed_restored_to_ready", S.SUPPRESSED, _transition(S.READY), 1),
            ("full_save_into_ready", S.CANDIDATE, _set_status_full_save(S.READY), 1),
            ("no_op_full_save_of_ready", S.READY, _full_save, 0),
            ("title_edit_of_ready", S.READY, _edit_title, 0),
            ("ready_to_resolved", S.READY, _transition(S.RESOLVED), 0),
            ("ready_to_candidate", S.READY, _transition(S.CANDIDATE), 0),
            ("in_progress_to_failed", S.IN_PROGRESS, _transition(S.FAILED, error="boom"), 0),
        ]
    )
    def test_event_fires_once_per_transition_into_ready(
        self, _name: str, start: SignalReport.Status, action: Callable[[SignalReport], None], expected: int
    ) -> None:
        report = self._report(start)

        with self.captureOnCommitCallbacks(execute=True):
            action(report)

        assert self._produced_events() == [REPORT_READY_EVENT] * expected

    @parameterized.expand([(S.READY, 1), (S.IN_PROGRESS, 0), (S.POTENTIAL, 0)])
    def test_event_fires_for_a_report_created_as_ready(self, status: SignalReport.Status, expected: int) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._report(status)

        assert self._produced_events() == [REPORT_READY_EVENT] * expected

    @parameterized.expand(
        [
            ("flag_on_no_verdict", True, None, 1),
            ("flag_on_safe_verdict", True, True, 1),
            ("flag_on_unsafe_verdict", True, False, 0),
            ("flag_off", False, None, 0),
        ]
    )
    def test_event_respects_flag_and_safety_verdict(
        self, _name: str, flag_on: bool, safe: bool | None, expected: int
    ) -> None:
        self.flag.return_value = flag_on

        # A born-visible report gets its verdict in the same transaction as the row.
        with self.captureOnCommitCallbacks(execute=True):
            report = self._report(S.READY)
            if safe is not None:
                self._artefact(report, SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT, {"choice": safe})

        assert self._produced_events() == [REPORT_READY_EVENT] * expected

    @parameterized.expand([("producer", "produce"), ("flag_check", "flag")])
    def test_a_failure_to_emit_does_not_fail_the_save(self, _name: str, failing: str) -> None:
        getattr(self, failing).side_effect = RuntimeError("kafka down")
        report = self._report(S.IN_PROGRESS)

        with self.captureOnCommitCallbacks(execute=True):
            _transition(S.READY, title="Checkout fails", summary="S")(report)

        assert SignalReport.objects.get(id=report.id).status == S.READY

    def test_event_carries_the_report_reference_and_filter_fields(self) -> None:
        report = self._report(S.IN_PROGRESS)
        self._artefact(report, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, {"priority": "P1"})
        self._artefact(
            report,
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            {"actionability": "immediately_actionable"},
        )
        self._artefact(report, SignalReportArtefact.ArtefactType.REPO_SELECTION, {"repository": "posthog/posthog"})
        self._artefact(
            report,
            SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            [{"github_login": "octocat"}, {"user_uuid": str(self.user.uuid)}, {"github_login": "OctoCat"}],
        )
        report_id = str(report.id)
        self.source_products.return_value = {
            report_id: ReportSignalMeta(source_products=["error_tracking", "github"], scout_name=None)
        }

        with self.captureOnCommitCallbacks(execute=True):
            _transition(S.READY, title="Checkout fails", summary="S")(report)

        report.refresh_from_db()
        assert self.produce.call_count == 1
        kwargs = self.produce.call_args.kwargs
        event = kwargs["event"]
        report_url = f"http://localhost:8010/project/{self.team.id}/inbox/reports/{report_id}"
        assert (kwargs["team_id"], event.event, event.distinct_id, event.url) == (
            self.team.id,
            REPORT_READY_EVENT,
            report_id,
            report_url,
        )
        assert event.properties == {
            "report_id": report_id,
            "report_url": report_url,
            "title": "Checkout fails",
            "priority": "P1",
            "actionability": "immediately_actionable",
            "source_products": ["error_tracking", "github"],
            "repo_slug": "posthog/posthog",
            "suggested_reviewers": ["octocat"],
            "updated_at": report.updated_at.isoformat(),
        }

    def test_a_report_without_judgments_sends_empty_filter_fields(self) -> None:
        self.source_products.side_effect = RuntimeError("clickhouse down")

        with self.captureOnCommitCallbacks(execute=True):
            report = self._report(S.READY)

        properties = self.produce.call_args.kwargs["event"].properties
        assert {key: properties[key] for key in ("report_id", "priority", "actionability", "source_products")} == {
            "report_id": str(report.id),
            "priority": None,
            "actionability": None,
            "source_products": [],
        }
        assert (properties["repo_slug"], properties["suggested_reviewers"]) == (None, [])

    def test_a_commit_hook_reads_the_report_from_the_writer(self) -> None:
        report = self._report(S.READY)
        self._artefact(report, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, {"priority": "P1"})
        self._artefact(report, SignalReportArtefact.ArtefactType.REPO_SELECTION, {"repository": "posthog/posthog"})
        self._artefact(report, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS, [{"github_login": "octocat"}])

        # Tests have no replica database, so any read the router sends there fails.
        with self.settings(DATABASE_ROUTERS=[ReplicaRouter(["SignalReport", "SignalReportArtefact"])]):
            emit_report_ready_event(
                team_id=self.team.id, report_id=str(report.id), is_safety_suppressed=_is_safety_suppressed
            )

        properties = self.produce.call_args.kwargs["event"].properties
        assert (properties["priority"], properties["repo_slug"], properties["suggested_reviewers"]) == (
            "P1",
            "posthog/posthog",
            ["octocat"],
        )

    def test_the_source_products_query_has_a_short_time_limit(self) -> None:
        self.source_products.side_effect = fetch_source_products_for_reports
        with patch(
            "products.signals.backend.signal_metadata.execute_hogql_query", return_value=MagicMock(results=[])
        ) as query:
            with self.captureOnCommitCallbacks(execute=True):
                self._report(S.READY)

        assert query.call_args.kwargs["settings"].max_execution_time == SOURCE_PRODUCTS_TIMEOUT_SECONDS


class TestReportReadyEventReadScope(SimpleTestCase):
    def test_destinations_on_the_event_need_inbox_read_access(self) -> None:
        # A rename on either side would let a destination send reports without the inbox read check.
        assert internal_event_read_scope(REPORT_READY_EVENT) == "inbox"
