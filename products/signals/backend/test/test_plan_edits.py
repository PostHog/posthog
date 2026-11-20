import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ArtefactContentValidationError, ReportLink
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.plan_edits import PlanEditConflict, add_plan_step, remove_plan_step, set_step_dependencies
from products.signals.backend.report_plan import report_plan
from products.signals.backend.typed_report_links import outgoing_links


class TestPlanEdits(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.attribution = ArtefactAttribution.from_user(self.user.id)

    def _report(self, title: str, status: str = SignalReport.Status.READY, team: Team | None = None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team, status=status, title=title, summary="s", signal_count=1, total_weight=1.0
        )

    def _add(self, plan: SignalReport, step: SignalReport, depends_on: list[SignalReport] | None = None) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            add_plan_step(
                team_id=self.team.id,
                plan_id=str(plan.id),
                step_id=str(step.id),
                depends_on=[str(report.id) for report in depends_on or []],
                reason=None,
                attribution=self.attribution,
            )

    def _remove(self, plan: SignalReport, step: SignalReport, reason: str | None = None) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            remove_plan_step(
                team_id=self.team.id,
                plan_id=str(plan.id),
                step_id=str(step.id),
                reason=reason,
                attribution=self.attribution,
            )

    def _steps(self, report: SignalReport) -> list[tuple[str, tuple[str, ...]]]:
        plan = report_plan(team_id=self.team.id, report_id=str(report.id))
        return [] if plan is None else [(step.title or "", step.depends_on) for step in plan.steps]

    def _notes(self, report: SignalReport) -> list[str]:
        return list(SignalReportArtefact.objects.filter(report=report, type="note").values_list("content", flat=True))

    def test_added_steps_show_on_every_report_of_the_plan_in_order(self) -> None:
        plan, first, second = self._report("plan"), self._report("first"), self._report("second")

        self._add(plan, first)
        self._add(plan, second, depends_on=[first])

        expected = [("first", ()), ("second", (str(first.id),))]
        assert self._steps(plan) == expected
        assert self._steps(second) == expected
        link = SignalReportArtefact.objects.get(report=second, type="report_link", link_target_id=str(plan.id))
        assert (link.actor_kind, link.created_by_id) == ("user", self.user.id)

    @parameterized.expand(
        [
            ("open_step_left", SignalReport.Status.READY, SignalReport.Status.READY),
            ("every_step_left_resolved", SignalReport.Status.RESOLVED, SignalReport.Status.RESOLVED),
        ]
    )
    def test_removing_a_step_rolls_up_the_steps_that_remain(
        self, _name: str, other_status: str, expected_plan_status: str
    ) -> None:
        plan = self._report("plan")
        open_step = self._report("open")
        other = self._report("other")
        self._add(plan, open_step)
        self._add(plan, other)
        if other_status != SignalReport.Status.READY:
            other.save(update_fields=other.transition_to(SignalReport.Status(other_status)))

        self._remove(plan, open_step)

        plan.refresh_from_db()
        open_step.refresh_from_db()
        assert plan.status == expected_plan_status
        assert open_step.status == SignalReport.Status.READY

    def test_removing_a_step_drops_its_plan_dependencies_and_records_the_removal(self) -> None:
        plan, first, middle, last = (self._report(title) for title in ("plan", "first", "middle", "last"))
        outside = self._report("outside")
        self._add(plan, first)
        self._add(plan, middle, depends_on=[first])
        self._add(plan, last, depends_on=[middle])
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(middle.id),
            content=ReportLink(kind=ReportLinkKind.DEPENDS_ON, report_id=str(outside.id)),
            attribution=self.attribution,
        )

        self._remove(plan, middle, reason="split out")

        assert self._steps(plan) == [("first", ()), ("last", ())]
        assert report_plan(team_id=self.team.id, report_id=str(middle.id)) is None
        assert [edge.target_id for edge in outgoing_links(team_id=self.team.id, report_id=str(middle.id))] == [
            str(outside.id)
        ]
        assert any(f"Removed step {middle.id}" in note and "split out" in note for note in self._notes(plan))
        assert any(f"from plan {plan.id}" in note for note in self._notes(middle))

    def test_replacing_dependencies_keeps_links_outside_the_plan(self) -> None:
        plan, first, second, third = (self._report(title) for title in ("plan", "first", "second", "third"))
        outside = self._report("outside")
        self._add(plan, first)
        self._add(plan, second)
        self._add(plan, third, depends_on=[first])
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(third.id),
            content=ReportLink(kind=ReportLinkKind.DEPENDS_ON, report_id=str(outside.id)),
            attribution=self.attribution,
        )

        set_step_dependencies(
            team_id=self.team.id,
            plan_id=str(plan.id),
            step_id=str(third.id),
            depends_on=[str(second.id)],
            reason=None,
            attribution=self.attribution,
        )

        assert self._steps(plan)[2] == ("third", (str(second.id),))
        targets = {
            edge.target_id
            for edge in outgoing_links(
                team_id=self.team.id, report_id=str(third.id), kinds=(ReportLinkKind.DEPENDS_ON,)
            )
        }
        assert targets == {str(second.id), str(outside.id)}
        assert any(f"no longer builds on {first.id}" in note for note in self._notes(third))

    def test_a_dependency_loop_is_rejected_and_nothing_changes(self) -> None:
        plan, first, second = self._report("plan"), self._report("first"), self._report("second")
        self._add(plan, first)
        self._add(plan, second, depends_on=[first])

        with pytest.raises(ArtefactContentValidationError, match="would close a cycle"):
            set_step_dependencies(
                team_id=self.team.id,
                plan_id=str(plan.id),
                step_id=str(first.id),
                depends_on=[str(second.id)],
                reason=None,
                attribution=self.attribution,
            )

        assert self._steps(plan) == [("first", ()), ("second", (str(first.id),))]

    def test_a_step_of_a_deleted_plan_can_join_another_plan(self) -> None:
        deleted_plan, plan, step = self._report("deleted plan"), self._report("plan"), self._report("step")
        self._add(deleted_plan, step)
        deleted_plan.save(update_fields=deleted_plan.transition_to(SignalReport.Status.DELETED))

        self._add(plan, step)

        assert self._steps(step) == [("step", ())]
        step_plan = report_plan(team_id=self.team.id, report_id=str(step.id))
        assert step_plan is not None and step_plan.id == str(plan.id)

    def _other_team_report(self) -> SignalReport:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        return self._report("elsewhere", team=other_team)

    @parameterized.expand(
        [
            ("the_plan_itself", "plan", [], ArtefactContentValidationError, "cannot be its own step"),
            ("another_project", "other_team", [], ArtefactContentValidationError, "was not found in this project"),
            ("dependency_outside_the_plan", "fresh", ["outside"], ArtefactContentValidationError, "not a step of plan"),
            ("already_a_step", "member", [], PlanEditConflict, "already a step of this plan"),
            ("step_of_another_plan", "other_member", [], PlanEditConflict, "Remove it from that plan first"),
            ("the_plan_of_this_plan", "parent", [], ArtefactContentValidationError, "would close a cycle"),
        ]
    )
    def test_add_rejects_a_step_that_breaks_the_plan(
        self, _name: str, step_key: str, depends_on_keys: list[str], error: type[Exception], message: str
    ) -> None:
        plan, member = self._report("plan"), self._report("member")
        other_plan, other_member = self._report("other plan"), self._report("other member")
        parent = self._report("parent")
        self._add(plan, member)
        self._add(other_plan, other_member)
        self._add(parent, plan)
        reports = {
            "plan": plan,
            "member": member,
            "other_member": other_member,
            "parent": parent,
            "fresh": self._report("fresh"),
            "outside": self._report("outside"),
            "other_team": self._other_team_report() if step_key == "other_team" else plan,
        }

        with pytest.raises(error, match=message):
            add_plan_step(
                team_id=self.team.id,
                plan_id=str(plan.id),
                step_id=str(reports[step_key].id),
                depends_on=[str(reports[key].id) for key in depends_on_keys],
                reason=None,
                attribution=self.attribution,
            )

        assert self._steps(plan) == [("member", ())]
