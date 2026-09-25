from concurrent.futures import ThreadPoolExecutor

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, connection, transaction

from parameterized import parameterized

from products.signals.backend.artefact_schemas import PullRequestLink, ReportLink
from products.signals.backend.enums import ReportLinkKind, SignalSourceProduct
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
)
from products.signals.backend.plan_rollup import _rolled_up_status, roll_up_plan_parents
from products.signals.backend.pull_requests import update_pull_request_state
from products.signals.backend.report_links import outgoing_links
from products.signals.backend.temporal.grouping import _link_check_follow_up


class TestPlanRollup(BaseTest):
    def _report(self, title: str, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=status,
            title=title,
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )

    def _part_of(self, child: SignalReport, parent: SignalReport) -> None:
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(child.id),
            content=ReportLink(kind=ReportLinkKind.PART_OF, report_id=str(parent.id)),
            attribution=ArtefactAttribution.system(),
        )

    def _close(self, report: SignalReport, status: str) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            report.save(update_fields=report.transition_to(SignalReport.Status(status)))

    def _attach_pull_request(self, report: SignalReport, number: int, state: str) -> SignalReportPullRequest:
        pr = SignalReportPullRequest.objects.create(
            team_id=self.team.id,
            repository="owner/repo",
            number=number,
            url=f"https://github.com/owner/repo/pull/{number}",
            state=state,
        )
        link = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PullRequestLink(url=pr.url),
            attribution=ArtefactAttribution.system(),
        )
        link.pull_request = pr
        link.save(update_fields=["pull_request"])
        return pr

    @parameterized.expand(
        [
            ("both_resolved", ["resolved", "resolved"], SignalReport.Status.RESOLVED),
            ("mixed_with_a_resolve", ["resolved", "suppressed"], SignalReport.Status.RESOLVED),
            ("all_suppressed", ["suppressed", "suppressed"], SignalReport.Status.SUPPRESSED),
        ]
    )
    def test_a_plan_takes_the_verdict_of_its_steps(self, _name: str, child_statuses: list[str], expected: str):
        parent = self._report("plan")
        children = [self._report(f"step-{index}") for index in range(len(child_statuses))]
        for child in children:
            self._part_of(child, parent)

        for child, status in zip(children, child_statuses):
            self._close(child, status)

        parent.refresh_from_db()
        assert parent.status == expected

    def test_a_plan_stays_open_while_any_step_is(self):
        parent = self._report("plan")
        done, still_open = self._report("done"), self._report("open")
        self._part_of(done, parent)
        self._part_of(still_open, parent)

        self._close(done, SignalReport.Status.RESOLVED)

        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.READY

    def test_a_merged_pull_request_on_the_last_step_closes_the_plan(self):
        parent = self._report("plan")
        child = self._report("step")
        self._part_of(child, parent)
        self._attach_pull_request(child, 11, "open")

        with self.captureOnCommitCallbacks(execute=True):
            update_pull_request_state(team_id=self.team.id, repository="owner/repo", number=11, state="merged")

        child.refresh_from_db()
        parent.refresh_from_db()
        assert child.status == SignalReport.Status.RESOLVED
        assert parent.status == SignalReport.Status.RESOLVED

    @parameterized.expand([("ready",), ("resolved",)])
    def test_the_verdict_rolls_up_through_a_plan_of_plans(self, parent_status):
        grandparent = self._report("programme")
        parent = self._report("plan", status=parent_status)
        child = self._report("step")
        self._part_of(parent, grandparent)
        self._part_of(child, parent)

        self._close(child, SignalReport.Status.RESOLVED)

        parent.refresh_from_db()
        grandparent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED
        assert grandparent.status == SignalReport.Status.RESOLVED

    @parameterized.expand([("delete_first", True), ("delete_last", False)])
    def test_a_deleted_step_is_not_a_verdict(self, _name, delete_first):
        parent = self._report("plan")
        done, removed = self._report("done"), self._report("removed")
        self._part_of(done, parent)
        self._part_of(removed, parent)
        steps = [(removed, SignalReport.Status.DELETED), (done, SignalReport.Status.RESOLVED)]
        for step, status in steps if delete_first else reversed(steps):
            self._close(step, status)

        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED

    def test_an_archived_step_never_undoes_a_resolved_plan(self):
        parent = self._report("plan", status=SignalReport.Status.RESOLVED)
        child = self._report("step")
        self._part_of(child, parent)

        self._close(child, SignalReport.Status.SUPPRESSED)

        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY, "plan", "s", None),
            ("pending_input", SignalReport.Status.PENDING_INPUT, "plan", "s", "e"),
            ("failed", SignalReport.Status.FAILED, None, None, "e"),
        ]
    )
    def test_plan_closes_when_its_own_run_lands_after_its_steps(
        self,
        _name: str,
        landing: SignalReport.Status,
        title: str | None,
        summary: str | None,
        error: str | None,
    ):
        parent = self._report("plan", status=SignalReport.Status.IN_PROGRESS)
        child = self._report("step")
        self._part_of(child, parent)

        self._close(child, SignalReport.Status.RESOLVED)
        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.IN_PROGRESS

        with self.captureOnCommitCallbacks(execute=True):
            parent.save(update_fields=parent.transition_to(landing, title=title, summary=summary, error=error))
        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED

    def test_a_plan_still_settles_when_a_shortcut_edge_reached_it_first(self):
        grandparent = self._report("programme")
        parent = self._report("plan")
        child = self._report("step")
        self._part_of(child, grandparent)
        self._part_of(child, parent)
        self._part_of(parent, grandparent)

        self._close(child, SignalReport.Status.RESOLVED)

        parent.refresh_from_db()
        grandparent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED
        assert grandparent.status == SignalReport.Status.RESOLVED

    def test_a_step_linked_into_a_plan_after_it_closed_still_closes_the_plan(self):
        parent = self._report("plan")
        child = self._report("step")
        self._close(child, SignalReport.Status.RESOLVED)

        with self.captureOnCommitCallbacks(execute=True):
            self._part_of(child, parent)

        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.RESOLVED

    @parameterized.expand(
        [
            ("open", "open", SignalReport.Status.READY),
            ("draft", "draft", SignalReport.Status.READY),
            ("unknown", "unknown", SignalReport.Status.READY),
            ("closed", "closed", SignalReport.Status.RESOLVED),
            ("merged", "merged", SignalReport.Status.RESOLVED),
        ]
    )
    def test_a_plan_waits_for_its_own_pull_request(self, _name: str, pr_state: str, expected: str):
        parent = self._report("plan")
        child = self._report("step")
        self._part_of(child, parent)
        self._attach_pull_request(parent, 21, pr_state)

        self._close(child, SignalReport.Status.RESOLVED)

        parent.refresh_from_db()
        assert parent.status == expected

    def test_archived_steps_leave_a_plan_that_still_has_its_own_pull_request(self):
        parent = self._report("plan")
        child = self._report("step")
        self._part_of(child, parent)
        self._attach_pull_request(parent, 22, "open")

        self._close(child, SignalReport.Status.SUPPRESSED)

        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.READY

    def test_a_report_with_no_plan_rolls_up_nothing(self):
        report = self._report("standalone")

        assert roll_up_plan_parents(team_id=self.team.id, report_id=str(report.id)) == []


class TestCheckFollowUpLink(BaseTest):
    def _report(self, title: str) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title=title,
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )

    def test_a_check_failure_report_points_at_the_report_the_check_was_written_on(self):
        origin, fresh = self._report("origin"), self._report("fresh")

        _link_check_follow_up(
            team_id=self.team.id,
            report_id=str(fresh.id),
            source_product=SignalSourceProduct.SIGNALS_CHECK,
            extra={"report_id": str(origin.id), "explanation": "Error rate is back above the baseline."},
        )

        edges = outgoing_links(team_id=self.team.id, report_id=fresh.id)
        assert [(edge.kind, edge.target_id, edge.reason) for edge in edges] == [
            (ReportLinkKind.FOLLOW_UP_OF, str(origin.id), "Error rate is back above the baseline.")
        ]

    @parameterized.expand(
        [
            ("another_source_product", SignalSourceProduct.ERROR_TRACKING, True),
            ("no_origin_report", SignalSourceProduct.SIGNALS_CHECK, False),
        ]
    )
    def test_no_edge_is_written_without_a_check_origin(
        self, _name: str, source_product: str, include_origin: bool
    ) -> None:
        origin, fresh = self._report("origin"), self._report("fresh")
        extra = {"report_id": str(origin.id)} if include_origin else {}

        _link_check_follow_up(
            team_id=self.team.id,
            report_id=str(fresh.id),
            source_product=source_product,
            extra=extra,
        )

        assert outgoing_links(team_id=self.team.id, report_id=fresh.id) == []

    def test_a_check_signal_that_landed_on_its_own_origin_writes_no_self_link(self):
        report = self._report("origin")

        _link_check_follow_up(
            team_id=self.team.id,
            report_id=str(report.id),
            source_product=SignalSourceProduct.SIGNALS_CHECK,
            extra={"report_id": str(report.id)},
        )

        assert outgoing_links(team_id=self.team.id, report_id=report.id) == []


@pytest.mark.django_db(transaction=True)
def test_plan_status_decision_holds_parent_lock(team):
    parent = SignalReport.objects.create(team=team, status=SignalReport.Status.READY)
    child = SignalReport.objects.create(team=team, status=SignalReport.Status.SUPPRESSED)
    SignalReportArtefact.add_log(
        team_id=team.id,
        report_id=str(child.id),
        content=ReportLink(kind=ReportLinkKind.PART_OF, report_id=str(parent.id)),
        attribution=ArtefactAttribution.system(),
    )

    def try_concurrent_parent_change():
        try:
            with transaction.atomic():
                report = SignalReport.objects.select_for_update(nowait=True).get(team_id=team.id, id=parent.id)
                report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
        finally:
            connection.close()

    def status_with_concurrent_change(**kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(OperationalError, match="could not obtain lock"):
                executor.submit(try_concurrent_parent_change).result(timeout=10)
        return _rolled_up_status(**kwargs)

    with patch("products.signals.backend.plan_rollup._rolled_up_status", side_effect=status_with_concurrent_change):
        roll_up_plan_parents(team_id=team.id, report_id=str(child.id))

    parent.refresh_from_db()
    assert parent.status == SignalReport.Status.SUPPRESSED
