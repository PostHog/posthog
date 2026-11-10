from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.apps import apps
from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.facade.agent_runs import (
    AgentEntity,
    ImplementationState,
    detach_entity,
    get_attached,
    linked_entities,
)
from products.signals.backend.facade.agent_sources import agent_source_registered
from products.signals.backend.models import (
    SignalAgentRun,
    SignalReport,
    SignalReportArtefact,
    SignalReportEntityLink,
    SignalReportPullRequest,
)
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION, append_task_run_artefact

TICKET = "019f9373-1e60-0000-3928-d8b21e6e8cb0"
OTHER_TICKET = "019f9373-1e60-0000-3928-d8b21e6e8cb1"

FIX_RUNS_ENDED: list[tuple[int, AgentEntity, str]] = []


def record_fix_run_ended(team_id: int, entity: AgentEntity, report_id: str) -> None:
    FIX_RUNS_ENDED.append((team_id, entity, report_id))


def unused_handler(*_args: Any) -> None:
    return None


class AgentRunTestBase(BaseTest):
    def _run(self, *, source_id: str = TICKET, pass_number: int = 1, **fields: Any) -> SignalAgentRun:
        return SignalAgentRun.objects.for_team(self.team.id).create(
            team_id=fields.pop("team_id", self.team.id),
            agent=SignalAgentRun.Agent.RESEARCH,
            source_product="conversations",
            source_type="ticket",
            source_id=source_id,
            pass_number=pass_number,
            **fields,
        )

    def _report(self, *, status: str = SignalReport.Status.READY, team: Team | None = None) -> SignalReport:
        return SignalReport.objects.create(team=team or self.team, status=status, title="A report")

    def _link(
        self, report: SignalReport, *, source_id: str = TICKET, relation: str = "created"
    ) -> SignalReportEntityLink:
        return SignalReportEntityLink.objects.for_team(report.team_id).create(
            team_id=report.team_id,
            report=report,
            source_product="conversations",
            source_type="ticket",
            source_id=source_id,
            relation=relation,
        )

    def _fix_run(self, report: SignalReport, *, stage: str = "implementation") -> Any:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="Fix", description="Fix", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        task_run = TaskRun.objects.create(task=task, team=self.team, state={"ai_stage": stage})
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(task.id),
            run_id=str(task_run.id),
        )
        return task_run

    def _attach_pull_request(self, report: SignalReport, *, state: str) -> SignalReportPullRequest:
        pull_request = SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team,
            repository="example/app",
            number=42,
            url="https://github.com/example/app/pull/42",
            state=state,
        )
        artefact = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PullRequestLink(url=pull_request.url),
            attribution=ArtefactAttribution.system(),
        )
        SignalReportArtefact.objects.filter(id=artefact.id).update(pull_request=pull_request)
        return pull_request


class TestAgentRunConstraints(AgentRunTestBase):
    @parameterized.expand(
        [
            ("queued", SignalAgentRun.Status.QUEUED),
            ("running", SignalAgentRun.Status.RUNNING),
        ]
    )
    def test_an_entity_has_one_active_pass_at_most(self, _name: str, active_status: str) -> None:
        self._run(pass_number=1, status=active_status)

        with pytest.raises(IntegrityError), transaction.atomic():
            self._run(pass_number=2)

        self._run(source_id=OTHER_TICKET, pass_number=1)
        SignalAgentRun.objects.for_team(self.team.id).filter(source_id=TICKET).update(status=SignalAgentRun.Status.DONE)
        self._run(pass_number=2)

    def test_a_pass_number_is_used_once_per_entity(self) -> None:
        self._run(pass_number=1, status=SignalAgentRun.Status.DONE)

        with pytest.raises(IntegrityError), transaction.atomic():
            self._run(pass_number=1, status=SignalAgentRun.Status.FAILED)


class TestAttachedReads(AgentRunTestBase):
    def test_get_attached_returns_the_latest_pass_and_the_live_linked_reports(self) -> None:
        self._run(pass_number=1, status=SignalAgentRun.Status.DONE, result={"outcome": "needs_input"})
        latest = self._run(
            pass_number=2,
            status=SignalAgentRun.Status.FAILED,
            result={"outcome": "failed", "reason_code": "agent_run_failed"},
        )
        created = self._report()
        matched = self._report(status=SignalReport.Status.SUPPRESSED)
        deleted = self._report(status=SignalReport.Status.DELETED)
        self._link(created)
        self._link(matched, relation="matched")
        self._link(deleted)
        self._link(self._report(), source_id=OTHER_TICKET)

        attached = get_attached(
            team_id=self.team.id, product="conversations", type="ticket", ids=[TICKET, "no-such-ticket"]
        )

        assert set(attached) == {TICKET}
        run = attached[TICKET].run
        assert run is not None
        assert (run.run_id, run.pass_number, run.status, run.outcome, run.reason_code) == (
            str(latest.id),
            2,
            "failed",
            "failed",
            "agent_run_failed",
        )
        assert [(report.report_id, report.relation, report.status) for report in attached[TICKET].reports] == [
            (str(created.id), "created", "ready"),
            (str(matched.id), "matched", "suppressed"),
        ]

    def test_get_attached_reads_only_the_asked_project(self) -> None:
        self._run()
        self._link(self._report())
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")

        assert get_attached(team_id=other_team.id, product="conversations", type="ticket", ids=[TICKET]) == {}

    @parameterized.expand(
        [
            ("draft", "draft", ImplementationState.PR_DRAFT),
            ("open", "open", ImplementationState.PR_OPEN),
            ("merged", "merged", ImplementationState.PR_MERGED),
            ("closed", "closed", ImplementationState.PR_CLOSED),
            ("state not known yet", "unknown", ImplementationState.STARTED),
        ]
    )
    def test_get_attached_shows_the_pull_request_state_of_a_linked_report(
        self, _name: str, pr_state: str, expected: ImplementationState
    ) -> None:
        with_fix = self._report()
        without_fix = self._report()
        self._link(with_fix)
        self._link(without_fix)
        pull_request = self._attach_pull_request(with_fix, state=pr_state)

        reports = get_attached(team_id=self.team.id, product="conversations", type="ticket", ids=[TICKET])[
            TICKET
        ].reports

        assert [(report.implementation.state, report.implementation.pr_url) for report in reports] == [
            (expected, pull_request.url),
            (ImplementationState.NONE, None),
        ]

    @parameterized.expand(
        [
            ("the fix run is working", "in_progress", True),
            ("the fix run ended with no pull request", "failed", False),
        ]
    )
    def test_get_attached_says_whether_the_fix_run_of_a_linked_report_is_running(
        self, _name: str, run_status: str, expected_active: bool
    ) -> None:
        report = self._report()
        self._link(report)
        task_run = self._fix_run(report)
        type(task_run).objects.filter(id=task_run.id).update(status=run_status)

        implementation = (
            get_attached(team_id=self.team.id, product="conversations", type="ticket", ids=[TICKET])[TICKET]
            .reports[0]
            .implementation
        )

        assert (implementation.state, implementation.run_active) == (ImplementationState.STARTED, expected_active)

    @parameterized.expand(
        [
            ("the fix run ended", "implementation", "completed", True),
            ("the fix run failed", "implementation", "failed", True),
            ("the fix run still works", "implementation", "in_progress", False),
            ("another kind of run ended", "research", "completed", False),
        ]
    )
    def test_the_owner_of_a_linked_entity_hears_when_the_fix_run_of_the_report_ends(
        self, _name: str, stage: str, run_status: str, expects_notice: bool
    ) -> None:
        report = self._report()
        self._link(report)
        self._link(self._report(), source_id=OTHER_TICKET)
        task_run = self._fix_run(report, stage=stage)
        FIX_RUNS_ENDED.clear()

        with (
            agent_source_registered(
                agent="research",
                product="conversations",
                type="ticket",
                load=f"{__name__}.unused_handler",
                on_result=f"{__name__}.unused_handler",
                on_fix_run_ended=f"{__name__}.record_fix_run_ended",
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            task_run.status = run_status
            task_run.save(update_fields=["status"])

        expected = [(self.team.id, AgentEntity(product="conversations", type="ticket", id=TICKET), str(report.id))]
        assert FIX_RUNS_ENDED == (expected if expects_notice else [])

    def test_linked_entities_lists_every_entity_of_the_report(self) -> None:
        report = self._report()
        self._link(report)
        self._link(report, source_id=OTHER_TICKET, relation="matched")
        self._link(self._report(), source_id="another-report-entity")

        assert linked_entities(team_id=self.team.id, report_id=str(report.id)) == [
            AgentEntity(product="conversations", type="ticket", id=TICKET),
            AgentEntity(product="conversations", type="ticket", id=OTHER_TICKET),
        ]

    def test_detach_entity_removes_links_and_finished_passes_and_stops_the_active_pass(self) -> None:
        report = self._report()
        self._link(report)
        kept_link = self._link(report, source_id=OTHER_TICKET)
        self._run(pass_number=1, status=SignalAgentRun.Status.DONE, result={"outcome": "reports"})
        active = self._run(pass_number=2, status=SignalAgentRun.Status.RUNNING, look_again=True)
        kept_run = self._run(source_id=OTHER_TICKET, status=SignalAgentRun.Status.DONE)

        assert detach_entity(team_id=self.team.id, product="conversations", type="ticket", id=TICKET) == 1

        assert list(SignalReportEntityLink.objects.for_team(self.team.id).values_list("id", flat=True)) == [
            kept_link.id
        ]
        remaining = {
            run.id: run.look_again for run in SignalAgentRun.objects.for_team(self.team.id).order_by("created_at")
        }
        assert remaining == {active.id: False, kept_run.id: False}
