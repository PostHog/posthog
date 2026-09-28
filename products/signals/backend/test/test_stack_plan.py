from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.db import transaction
from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink, SafetyJudgment
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ReportLayer,
    ReportPresentationOutput,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.stack_plan import (
    create_layer_reports,
    dependency_head_branch,
    start_dependent_layers,
    start_unblocked_layers_of_plan,
)
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.signals.backend.typed_report_links import outgoing_links
from products.tasks.backend.models import Task

AUTOSTART = "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts"


class TestReportLayersValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_layer_is_no_plan", [None], []),
            ("too_many_layers_is_no_plan", [None] * 7, []),
            ("stack_keeps_its_order", [None, 0, 1], [None, 0, 1]),
            ("forward_reference_falls_back_to_previous", [2, 5, 1], [None, 0, 1]),
        ]
    )
    def test_layers_form_an_acyclic_plan(self, _name: str, depends_on: list[int | None], expected: list[int | None]):
        output = ReportPresentationOutput.model_validate(
            {
                "title": "feat(x): plan",
                "summary": "s",
                "layers": [
                    {"title": f"layer {index}", "scope": "scope", "depends_on": dep}
                    for index, dep in enumerate(depends_on)
                ],
            }
        )
        assert [layer.depends_on for layer in output.layers] == expected


class TestStackPlan(BaseTest):
    def setUp(self):
        super().setUp()
        self.parent = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="feat(x): the plan", summary="plan"
        )
        for content in (
            SafetyJudgment(choice=True),
            ActionabilityAssessment(
                explanation="clear", actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE, already_addressed=False
            ),
            PriorityAssessment(explanation="important", priority=Priority.P2),
            RepoSelectionResult(repository="example/repo", reason="selected"),
        ):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.parent.id),
                content=content,
                attribution=ArtefactAttribution.system(),
            )

    def _layers(self) -> list[ReportLayer]:
        return [
            ReportLayer(title="feat(x): schema", scope="Add the schema."),
            ReportLayer(title="feat(x): api", scope="Add the API.", depends_on=0),
            ReportLayer(title="feat(x): ui", scope="Add the UI.", depends_on=1),
        ]

    def _create_layers(self) -> list[str]:
        with transaction.atomic():
            return create_layer_reports(
                parent=self.parent, layers=self._layers(), attribution=ArtefactAttribution.system()
            )

    def _start_run(self, report_id: str, branch: str) -> None:
        task = Task.objects.create(
            team=self.team,
            signal_report_id=report_id,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            title="Implementation",
            repository="example/repo",
            internal=True,
        )
        with transaction.atomic():
            record_implementation_task(
                team_id=self.team.id, report_id=report_id, task_id=str(task.id), automation_branch=branch
            )

    def _attach_pull_request(self, report_id: str, number: int, state: str) -> None:
        pr = SignalReportPullRequest.objects.create(
            team_id=self.team.id,
            repository="example/repo",
            number=number,
            url=f"https://github.com/example/repo/pull/{number}",
            state=state,
        )
        link = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=report_id,
            content=PullRequestLink(url=pr.url),
            attribution=ArtefactAttribution.system(),
        )
        link.pull_request = pr
        link.save(update_fields=["pull_request"])

    def test_each_layer_becomes_a_ready_report_linked_into_the_stack(self):
        child_ids = self._create_layers()

        children = {str(r.id): r for r in SignalReport.objects.filter(id__in=child_ids)}
        assert [children[child_id].title for child_id in child_ids] == [
            "feat(x): schema",
            "feat(x): api",
            "feat(x): ui",
        ]
        assert all(child.status == SignalReport.Status.READY for child in children.values())
        for index, child_id in enumerate(child_ids):
            links = outgoing_links(team_id=self.team.id, report_id=child_id)
            assert [(edge.kind, edge.target_id) for edge in links if edge.kind == ReportLinkKind.PART_OF] == [
                (ReportLinkKind.PART_OF, str(self.parent.id))
            ]
            expected_dependency = [child_ids[index - 1]] if index else []
            assert [edge.target_id for edge in links if edge.kind == ReportLinkKind.DEPENDS_ON] == expected_dependency
            # Auto-start reads these on the layer, so the layer can start without its own research.
            assert set(SignalReportArtefact.objects.filter(report_id=child_id).values_list("type", flat=True)) >= {
                "safety_judgment",
                "actionability_judgment",
                "priority_judgment",
                "repo_selection",
            }

    def test_a_plan_that_already_has_layers_keeps_them(self):
        first = self._create_layers()
        second = self._create_layers()

        assert len(first) == 3
        assert second == []
        assert SignalReport.objects.filter(team=self.team).count() == 4

    def test_only_the_first_layer_starts_with_the_plan(self):
        child_ids = self._create_layers()

        with patch(AUTOSTART, new_callable=AsyncMock) as autostart:
            started = start_unblocked_layers_of_plan(team_id=self.team.id, parent_report_id=str(self.parent.id))

        assert started == [child_ids[0]]
        autostart.assert_awaited_once_with(team_id=self.team.id, report_id=child_ids[0])

    def test_the_next_layer_starts_when_its_dependency_opens_a_pull_request(self):
        child_ids = self._create_layers()

        with patch(AUTOSTART, new_callable=AsyncMock) as autostart:
            assert start_dependent_layers(team_id=self.team.id, report_id=child_ids[0]) == []
            self._attach_pull_request(child_ids[0], 1, SignalReportPullRequest.State.OPEN)
            assert start_dependent_layers(team_id=self.team.id, report_id=child_ids[0]) == [child_ids[1]]

        autostart.assert_awaited_once_with(team_id=self.team.id, report_id=child_ids[1])

    def test_a_layer_that_already_started_is_not_started_again(self):
        child_ids = self._create_layers()
        self._attach_pull_request(child_ids[0], 1, SignalReportPullRequest.State.OPEN)
        self._start_run(child_ids[1], "posthog-self-driving/api-abc123")

        with patch(AUTOSTART, new_callable=AsyncMock) as autostart:
            assert start_dependent_layers(team_id=self.team.id, report_id=child_ids[0]) == []

        autostart.assert_not_awaited()

    @parameterized.expand(
        [
            ("open_dependency_is_the_base", SignalReportPullRequest.State.OPEN, "posthog-self-driving/schema-abc123"),
            ("draft_dependency_is_the_base", SignalReportPullRequest.State.DRAFT, "posthog-self-driving/schema-abc123"),
            ("merged_dependency_uses_the_default_base", SignalReportPullRequest.State.MERGED, None),
        ]
    )
    def test_a_layer_stacks_on_its_dependency_head_branch(self, _name: str, state: str, expected: str | None):
        child_ids = self._create_layers()
        self._start_run(child_ids[0], "posthog-self-driving/schema-abc123")
        self._attach_pull_request(child_ids[0], 1, state)

        assert dependency_head_branch(team_id=self.team.id, report_id=child_ids[1]) == expected
        assert dependency_head_branch(team_id=self.team.id, report_id=child_ids[0]) is None
