from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.report_link_summary import (
    LinkedReportRef,
    LinkPlanStep,
    LinkPlanSummary,
    LinkStripKind,
    PlanStepState,
    choose_link_summary,
    lead_step_id,
    plan_step_state,
)
from products.signals.backend.typed_report_links import ReportEdge


def _ref(report_id: str) -> LinkedReportRef:
    return LinkedReportRef(
        id=report_id, title=report_id, status="ready", implementation_pr_url=None, implementation_pr_state=None
    )


def _plan(plan_id: str, *step_ids: str) -> LinkPlanSummary:
    steps = tuple(LinkPlanStep(id=step_id, title=step_id, state=PlanStepState.WAITING) for step_id in step_ids)
    return LinkPlanSummary(id=plan_id, title=plan_id, steps=steps, lead_step_id=step_ids[0])


class TestChooseLinkSummary(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "plan_step_beats_every_other_link",
                [("recurrence_of", "old"), ("part_of", "plan")],
                LinkStripKind.PART_OF,
                "plan",
                [("recurrence_of", "old")],
            ),
            (
                "recurrence_folds_a_follow_up_to_the_same_report",
                [("follow_up_of", "old"), ("recurrence_of", "old"), ("follow_up_of", "other")],
                LinkStripKind.RECURRENCE_OF,
                "old",
                [("follow_up_of", "other")],
            ),
            (
                "duplicate_beats_dependency_and_follow_up",
                [("follow_up_of", "other"), ("depends_on", "dep"), ("duplicate_of", "dup")],
                LinkStripKind.DUPLICATE_OF,
                "dup",
                [("follow_up_of", "other"), ("depends_on", "dep")],
            ),
            (
                "link_to_a_deleted_report_names_nothing",
                [("recurrence_of", "deleted"), ("follow_up_of", "other")],
                LinkStripKind.FOLLOW_UP_OF,
                "other",
                [],
            ),
        ]
    )
    def test_strip_choice(
        self,
        _name: str,
        edges: list[tuple[str, str]],
        kind: LinkStripKind,
        linked_id: str,
        other_links: list[tuple[str, str]],
    ) -> None:
        summary = choose_link_summary(
            report_id="step-1",
            edges=[ReportEdge(source_id="step-1", kind=ReportLinkKind(k), target_id=t) for k, t in edges],
            references={report_id: _ref(report_id) for report_id in ("plan", "old", "other", "dep", "dup")},
            plans={"plan": _plan("plan", "step-1", "step-2")},
        )

        assert summary is not None
        assert summary.kind == kind
        assert summary.report is not None and summary.report.id == linked_id
        assert [(link.kind.value, link.report.id) for link in summary.other_links] == other_links

    def test_a_step_hides_dependencies_inside_its_plan(self) -> None:
        summary = choose_link_summary(
            report_id="step-2",
            edges=[
                ReportEdge(source_id="step-2", kind=ReportLinkKind.PART_OF, target_id="plan"),
                ReportEdge(source_id="step-2", kind=ReportLinkKind.DEPENDS_ON, target_id="step-1"),
                ReportEdge(source_id="step-2", kind=ReportLinkKind.DEPENDS_ON, target_id="elsewhere"),
            ],
            references={report_id: _ref(report_id) for report_id in ("plan", "step-1", "elsewhere")},
            plans={"plan": _plan("plan", "step-1", "step-2")},
        )

        assert summary is not None
        assert [(link.kind, link.report.id) for link in summary.other_links] == [
            (ReportLinkKind.DEPENDS_ON, "elsewhere")
        ]

    def test_the_plan_itself_gets_a_plan_strip(self) -> None:
        summary = choose_link_summary(
            report_id="plan", edges=[], references={}, plans={"plan": _plan("plan", "step-1", "step-2")}
        )

        assert summary is not None
        assert summary.kind == LinkStripKind.PLAN
        assert summary.report is None

    def test_a_report_with_no_live_link_gets_no_strip(self) -> None:
        assert choose_link_summary(report_id="lonely", edges=[], references={}, plans={}) is None


class TestPlanLead(SimpleTestCase):
    @parameterized.expand(
        [
            ("resolved_step", "resolved", None, PlanStepState.MERGED),
            ("merged_pr_before_the_webhook_resolves", "ready", "merged", PlanStepState.MERGED),
            ("archived_step", "suppressed", "closed", PlanStepState.DISMISSED),
            ("open_pr", "ready", "open", PlanStepState.IN_REVIEW),
            ("closed_pr_on_a_live_step", "ready", "closed", PlanStepState.WAITING),
        ]
    )
    def test_step_state(self, _name: str, status: str, pr_state: str | None, expected: PlanStepState) -> None:
        assert plan_step_state(status=status, pr_state=pr_state) == expected

    @parameterized.expand(
        [
            ("first_step_in_review_leads", ["merged", "waiting", "in_review"], "s3"),
            ("first_waiting_step_leads_without_review", ["merged", "dismissed", "waiting", "waiting"], "s3"),
            ("last_step_leads_when_all_are_closed", ["merged", "dismissed", "merged"], "s3"),
        ]
    )
    def test_lead_step(self, _name: str, states: list[str], expected: str) -> None:
        steps = [
            LinkPlanStep(id=f"s{index}", title=None, state=PlanStepState(state))
            for index, state in enumerate(states, start=1)
        ]

        assert lead_step_id(steps) == expected
