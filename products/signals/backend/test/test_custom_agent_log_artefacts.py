import json
import uuid

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import CodeReference, Commit, NoteArtefact
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
from products.tasks.backend.models import Task


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

    @parameterized.expand(
        [
            (
                "register_note",
                {"note": "hello", "author": "agent"},
                "note",
                {"note": "hello", "author": "agent"},
            ),
            (
                "register_code_reference",
                {
                    "file_path": "src/a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "contents": "x=1\ny=2",
                    "relevance_note": "r",
                },
                "code_reference",
                {
                    "file_path": "src/a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "contents": "x=1\ny=2",
                    "relevance_note": "r",
                },
            ),
            (
                "register_code_diff",
                {"file_path": "src/a.py", "diff": "--- a\n+++ b", "relevance_note": "r"},
                "code_diff",
                {"file_path": "src/a.py", "diff": "--- a\n+++ b", "relevance_note": "r"},
            ),
            (
                "register_line_reference",
                {"file_path": "src/a.py", "line": 3, "note": "this line"},
                "line_reference",
                {"file_path": "src/a.py", "line": 3, "note": "this line", "contents": None},
            ),
        ]
    )
    def test_typed_helpers_queue_log_artefacts(self, method, kwargs, expected_type, expected_content):
        agent = self._agent()

        getattr(agent, method)(**kwargs)

        assert len(agent._log_artefacts) == 1
        artefact_type, content_json = agent._log_artefacts[0]
        assert artefact_type == expected_type
        assert json.loads(content_json) == expected_content

    def test_register_artefact_accepts_content_models_and_rejects_unregisterable_types(self):
        agent = self._agent()

        agent.register_artefact(NoteArtefact(note="n"))
        assert [artefact_type for artefact_type, _ in agent._log_artefacts] == ["note"]

        commit = Commit(repository="acme/repo", branch="main", commit_sha="a" * 7, message="m")
        with self.assertRaises(TypeError):
            agent.register_artefact(commit)  # type: ignore[arg-type]

    def test_helper_validation_fails_at_the_call_site(self):
        agent = self._agent()

        with self.assertRaises(ValidationError):
            agent.register_note("   ")
        with self.assertRaises(ValidationError):
            agent.register_code_reference(file_path="a.py", start_line=5, end_line=2, contents="x", relevance_note="r")

        assert agent._log_artefacts == []

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
        agent.register_note("first")

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

        assert create_mock.call_args.kwargs["log_artefacts"] == [("note", NoteArtefact(note="first").model_dump_json())]
        assert agent._log_artefacts == []

    def test_create_report_writes_log_artefacts_attributed_to_the_task(self):
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
            log_artefacts=[
                ("note", NoteArtefact(note="hello").model_dump_json()),
                ("code_reference", code_reference.model_dump_json()),
            ],
        )

        rows = SignalReportArtefact.objects.filter(
            report_id=persisted.report_id,
            type__in=[SignalReportArtefact.ArtefactType.NOTE, SignalReportArtefact.ArtefactType.CODE_REFERENCE],
        )
        assert rows.count() == 2
        for row in rows:
            assert str(row.task_id) == str(task.id)
            assert row.created_by_id is None

    def test_create_report_without_task_writes_system_attributed_log_artefacts(self):
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=None,
            agent_identifier=("billing", "anomaly_scan"),
            log_artefacts=[("note", NoteArtefact(note="hello").model_dump_json())],
        )

        row = SignalReportArtefact.objects.get(
            report_id=persisted.report_id, type=SignalReportArtefact.ArtefactType.NOTE
        )
        assert json.loads(row.content) == {"note": "hello", "author": None}
        assert row.task_id is None
        assert row.created_by_id is None
