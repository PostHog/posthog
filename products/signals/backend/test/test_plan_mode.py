from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from products.signals.backend.artefact_schemas import (
    Priority,
    PriorityAssessment,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalScoutConfig
from products.signals.backend.plan_mode.service import (
    PlanNotReadyError,
    create_plan,
    finish_plan,
    owner_scout_skill_name,
    plan_readiness,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task  # tach-ignore


def _mock_created_task(team, user):
    # The task_run artefact FKs to posthog_task, so the mocked facade must return a real row's id.
    task = Task.objects.create(
        team=team,
        title="Plan a new project",
        description="planning",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        created_by=user,
    )
    created = MagicMock()
    created.task_id = task.id
    created.latest_run = MagicMock()
    created.latest_run.id = uuid4()
    return created


class TestPlanModeService(APIBaseTest):
    def _make_ready_plan(self) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Plan: something",
            summary="A summary",
        )
        attribution = ArtefactAttribution.from_user(self.user.id)
        common = {"team_id": self.team.id, "report_id": str(report.id), "attribution": attribution}
        SignalReportArtefact.append_status(
            content=RepoSelectionResult(repository="posthog/posthog", reason="test"),
            reevaluate_autostart=False,
            **common,
        )
        SignalReportArtefact.append_status(
            content=SuggestedReviewers([SuggestedReviewerEntry(github_login="me", relevant_commits=[])]),
            reevaluate_autostart=False,
            **common,
        )
        SignalReportArtefact.append_status(
            content=PriorityAssessment(explanation="user plan", priority=Priority.P1),
            reevaluate_autostart=False,
            **common,
        )
        return report

    @patch("products.signals.backend.plan_mode.service.tasks_facade.create_and_run_task")
    def test_create_plan_creates_report_groundskeeping_note_and_planning_task(self, mock_create):
        mock_create.return_value = _mock_created_task(self.team, self.user)

        created = create_plan(team=self.team, user=self.user, initial_description="Build a widget")

        report = SignalReport.objects.get(id=created.report_id)
        assert report.summary == "Build a widget"
        assert report.title is None
        assert report.status == SignalReport.Status.READY

        artefacts = list(SignalReportArtefact.objects.filter(report_id=report.id).order_by("created_at"))
        assert [a.type for a in artefacts] == ["note", "task_run"]
        # The groundskeeping note is the full operating contract: it must carry the report id, the
        # MCP write tool, and the owner scout's exact skill name.
        note = artefacts[0].content
        assert "About this plan report" in note
        assert created.report_id in note
        assert "inbox-report-artefacts-create" in note
        assert owner_scout_skill_name(created.report_id) in note

        kwargs = mock_create.call_args.kwargs
        assert kwargs["mode"] == "interactive"
        assert kwargs["repository"] is None
        assert kwargs["signal_report_id"] == created.report_id
        assert kwargs["ai_stage"] == "planning"
        # Interactive runs only deliver pending_user_message — it's a short bootstrap that names
        # the report, directs the agent to the groundskeeping note, and carries the user's idea.
        first_message = kwargs["pending_user_message"]
        assert created.report_id in first_message
        assert "inbox-report-artefacts-list" in first_message
        assert "system of record" in first_message
        assert "Build a widget" in first_message

    def test_plan_readiness_lists_missing_pieces(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        readiness = plan_readiness(team_id=self.team.id, report=report)
        assert not readiness.ready
        assert set(readiness.missing) == {"title", "summary", "repository selection", "owners", "priority"}
        assert not readiness.finished

    def test_finish_plan_rejects_unready_plan(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="t", summary="s")
        with self.assertRaises(PlanNotReadyError) as ctx:
            finish_plan(team=self.team, user=self.user, report=report)
        assert "owners" in ctx.exception.missing

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_finish_plan_writes_defaults_and_creates_scout_idempotently(self, mock_create_task):
        # Owner "me" must resolve to an org member for the implementation kickoff to attribute the task.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me", extra_data={"login": "me"})
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = self._make_ready_plan()

        finished = finish_plan(team=self.team, user=self.user, report=report)
        skill_name = finished.scout_skill_name

        assert skill_name == owner_scout_skill_name(str(report.id))
        # The first implementation pass auto-starts at finish (the owner scout only runs daily).
        assert finished.implementation_task_id == str(mock_create_task.return_value.task_id)
        assert mock_create_task.call_args.kwargs["ai_stage"] == "implementation"
        assert mock_create_task.call_args.kwargs["repository"] == "posthog/posthog"
        types = set(SignalReportArtefact.objects.filter(report_id=report.id).values_list("type", flat=True))
        assert "safety_judgment" in types
        assert "actionability_judgment" in types

        skill = LLMSkill.objects.get(team=self.team, name=skill_name, is_latest=True)
        assert skill.allowed_tools == ["edit_report", "start_implementation"]
        assert str(report.id) in skill.body
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=skill_name)
        assert config.enabled

        # Second finish: no duplicate skill/config, no second implementation pass.
        second = finish_plan(team=self.team, user=self.user, report=report)
        assert second.scout_skill_name == skill_name
        assert second.implementation_task_id is None
        assert mock_create_task.call_count == 1
        assert LLMSkill.objects.filter(team=self.team, name=skill_name).count() == 1
        assert SignalReportArtefact.objects.filter(report_id=report.id, type="safety_judgment").count() == 1


class TestPlanModeAPI(APIBaseTest):
    @patch("products.signals.backend.plan_mode.service.tasks_facade.create_and_run_task")
    def test_create_endpoint_returns_ids(self, mock_create):
        mock_create.return_value = _mock_created_task(self.team, self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/plans/",
            {"initial_description": "Build a widget"},
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["report_id"]
        assert body["task_id"]

    @patch("products.signals.backend.plan_mode.service.tasks_facade.create_and_run_task")
    def test_list_surfaces_drafts_via_postgres_marker(self, mock_create):
        # Plans have no backing signal — the Postgres planning marker is the sole membership source,
        # so a draft must appear in the list from the moment of creation.
        mock_create.return_value = _mock_created_task(self.team, self.user)
        created = create_plan(team=self.team, user=self.user, initial_description="Build a widget")

        response = self.client.get(f"/api/projects/{self.team.id}/signals/plans/")
        assert response.status_code == 200, response.content
        rows = response.json()["results"]
        assert [r["id"] for r in rows] == [created.report_id]
        assert rows[0]["is_draft"] is True

    def test_finish_endpoint_returns_missing_on_unready_plan(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        response = self.client.post(f"/api/projects/{self.team.id}/signals/plans/{report.id}/finish/")
        assert response.status_code == 400, response.content
        assert "title" in response.json()["missing"]

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_finish_converges_divergent_owner_scout_to_template(self, mock_create_task):
        # An agent-authored skill under the deterministic name is overwritten with the canonical
        # body at finish — plan tailoring belongs in the playbook note, not the skill body, so
        # core scout behaviors (signal sweep, start_implementation protocol) can never drift.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me3", extra_data={"login": "me"})
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = TestPlanModeService._make_ready_plan(self)
        LLMSkill.objects.create(
            team=self.team,
            name=owner_scout_skill_name(str(report.id)),
            description="agent authored",
            body="# my own ideas, no sweep, no protocol",
            allowed_tools=["edit_report"],
        )

        finished = finish_plan(team=self.team, user=self.user, report=report)

        skill = LLMSkill.objects.get(team=self.team, name=finished.scout_skill_name, is_latest=True)
        assert "Owner scout playbook" in skill.body
        assert "associated_report" in skill.body
        assert skill.allowed_tools == ["edit_report", "start_implementation"]

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_start_implementation_endpoint_starts_a_pass(self, mock_create):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me2", extra_data={"login": "me"})
        mock_create.return_value = _mock_created_task(self.team, self.user)
        report = TestPlanModeService._make_ready_plan(self)  # repo + owners + priority, no impl run yet

        response = self.client.post(f"/api/projects/{self.team.id}/signals/plans/{report.id}/start_implementation/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["task_id"] == str(mock_create.return_value.task_id)
        assert body["repository"] == "posthog/posthog"
        assert mock_create.call_args.kwargs["ai_stage"] == "implementation"

    def test_finish_endpoint_404_for_other_team_report(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.post(f"/api/projects/{self.team.id}/signals/plans/{report.id}/finish/")
        assert response.status_code == 404
