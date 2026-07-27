import json
import uuid

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from pydantic import BaseModel

from products.signals.backend.artefact_schemas import ArtefactContentValidationError, CodeReference, NoteArtefact
from products.signals.backend.custom_agent.base import NO_REPO, CustomSignalAgent
from products.signals.backend.custom_agent.persistence import (
    PersistedCustomAgentReport,
    create_custom_agent_ready_report,
)
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult

# Task ORM model needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task  # tach-ignore


class _StubAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("billing", "anomaly_scan")

    async def run(self) -> bool:
        return False


class TestCustomAgentLogArtefacts(BaseTest):
    def _agent(self) -> CustomSignalAgent:
        return _StubAgent(team=self.team, initial_prompt="investigate", repository=NO_REPO)

    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _final_report(self) -> CustomAgentFinalReport:
        return CustomAgentFinalReport(
            title="title",
            description="description",
            actionability=ActionabilityAssessment(
                explanation="e",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            assignees=[],
            priority=PriorityAssessment(explanation="e", priority=Priority.P1),
        )

    def test_register_artefact_queues_any_content_model(self):
        agent = self._agent()

        agent.register_artefact(NoteArtefact(note="hello", author="agent"))
        agent.register_artefact(
            CodeReference(file_path="src/a.py", start_line=1, end_line=2, contents="x=1\ny=2", relevance_note="r")
        )
        # Status types are registerable too — they route through latest-wins on persistence.
        agent.register_artefact(PriorityAssessment(explanation="e", priority=Priority.P1))

        assert [type(a).__name__ for a in agent._registered_artefacts] == [
            "NoteArtefact",
            "CodeReference",
            "PriorityAssessment",
        ]

    def test_register_artefact_rejects_non_content_models(self):
        agent = self._agent()

        class NotAContentModel(BaseModel):
            value: str

        with self.assertRaises(ArtefactContentValidationError):
            agent.register_artefact(NotAContentModel(value="not a content schema"))  # type: ignore[arg-type]

        assert agent._registered_artefacts == []

    def test_report_and_continue_persists_queue_and_clears_it(self):
        agent = self._agent()
        agent._resolved_repository = RepoSelectionResult(repository=None, reason="caller")
        agent.register_title("t")
        agent.register_description("d")
        agent.register_actionability(
            ActionabilityAssessment(
                explanation="e",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            )
        )
        agent.register_priority(PriorityAssessment(explanation="e", priority=Priority.P1))
        agent.register_assignees([])
        agent.register_artefact(NoteArtefact(note="first"))

        with (
            patch(
                "products.signals.backend.custom_agent.base.create_custom_agent_ready_report",
                return_value=PersistedCustomAgentReport(report_id=str(uuid.uuid4()), task_id=None),
            ) as create_mock,
            patch(
                "products.signals.backend.custom_agent.base.maybe_autostart_from_report_artefacts",
                new=AsyncMock(),
            ),
        ):
            async_to_sync(agent.report_and_continue)()

        assert create_mock.call_args.kwargs["registered_artefacts"] == [NoteArtefact(note="first")]
        assert agent._registered_artefacts == []

    def test_create_report_writes_registered_artefacts_attributed_to_the_task(self):
        task = self._task()
        code_reference = CodeReference(
            file_path="src/a.py", start_line=1, end_line=1, contents="x = 1", relevance_note="r"
        )

        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=str(task.id),
            agent_identifier=("billing", "anomaly_scan"),
            registered_artefacts=[NoteArtefact(note="hello"), code_reference],
        )

        rows = SignalReportArtefact.objects.filter(
            report_id=persisted.report_id,
            type__in=[SignalReportArtefact.ArtefactType.NOTE, SignalReportArtefact.ArtefactType.CODE_REFERENCE],
        )
        assert rows.count() == 2
        for row in rows:
            assert str(row.task_id) == str(task.id)
            assert row.created_by_id is None

    def test_create_report_without_task_writes_system_attributed_artefacts(self):
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=None,
            agent_identifier=("billing", "anomaly_scan"),
            registered_artefacts=[NoteArtefact(note="hello")],
        )

        row = SignalReportArtefact.objects.get(
            report_id=persisted.report_id, type=SignalReportArtefact.ArtefactType.NOTE
        )
        assert json.loads(row.content) == {"note": "hello", "author": None}
        assert row.task_id is None
        assert row.created_by_id is None

    def test_create_report_routes_registered_status_artefacts_latest_wins(self):
        # A registered status artefact appends a new version on top of the one the final report
        # itself writes — the registered (later) row is the report's current status.
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=None,
            agent_identifier=("billing", "anomaly_scan"),
            registered_artefacts=[PriorityAssessment(explanation="raised", priority=Priority.P0)],
        )

        rows = list(
            SignalReportArtefact.objects.filter(
                report_id=persisted.report_id, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
            ).order_by("created_at")
        )
        assert len(rows) == 2
        assert json.loads(rows[-1].content)["priority"] == "P0"
