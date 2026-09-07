from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User

from products.signals.backend.artefact_schemas import (
    FeatureLifecycle,
    FeatureSource,
    FeatureStage,
    Priority,
    PriorityAssessment,
    QuestionArtefact,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.auto_start import _create_implementation_task_if_absent
from products.signals.backend.features.service import (
    CreatedFeatureDiscovery,
    FeaturePlanningNotReadyError,
    create_feature,
    feature_planning_readiness,
    finish_feature_planning,
    owner_scout_skill_name,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalScoutConfig
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.test.test_signal_report_api import authenticate_as_sandbox_token
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task  # tach-ignore


@pytest.fixture(autouse=True)
def enable_features():
    with patch("products.signals.backend.features.access.posthoganalytics.feature_enabled", return_value=True):
        yield


def _mock_created_task(team: Team, user: User) -> MagicMock:
    # The task_run artefact FKs to posthog_task, so the mocked facade must return a real row's id.
    task = Task.objects.create(
        team=team,
        title="Plan a new feature",
        description="planning",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        created_by=user,
    )
    created = MagicMock()
    created.task_id = task.id
    created.latest_run = MagicMock()
    created.latest_run.id = uuid4()
    return created


def _make_ready_feature(team: Team, user: User, feature_id: UUID | None = None) -> SignalReport:
    report = SignalReport.objects.create(
        **({"id": feature_id} if feature_id else {}),
        team=team,
        status=SignalReport.Status.READY,
        title="Feature: something",
        summary="A summary",
    )
    attribution = ArtefactAttribution.from_user(user.id)
    report_id = str(report.id)
    SignalReportArtefact.append_status(
        team_id=team.id,
        report_id=report_id,
        content=RepoSelectionResult(repository="posthog/posthog", reason="test"),
        attribution=attribution,
        reevaluate_autostart=False,
    )
    SignalReportArtefact.append_status(
        team_id=team.id,
        report_id=report_id,
        content=SuggestedReviewers([SuggestedReviewerEntry(github_login="me", relevant_commits=[])]),
        attribution=attribution,
        reevaluate_autostart=False,
    )
    SignalReportArtefact.append_status(
        team_id=team.id,
        report_id=report_id,
        content=PriorityAssessment(explanation="user feature", priority=Priority.P1),
        attribution=attribution,
        reevaluate_autostart=False,
    )
    return report


class TestFeatureService(APIBaseTest):
    @patch("products.signals.backend.features.service.tasks_facade.create_and_run_task")
    def test_create_feature_creates_report_groundskeeping_note_and_planning_task(self, mock_create):
        mock_create.return_value = _mock_created_task(self.team, self.user)

        created = create_feature(team=self.team, user=self.user, initial_description="Build a widget")

        report = SignalReport.objects.get(id=created.report_id)
        assert report.summary == "Build a widget"
        assert report.title is None
        assert report.status == SignalReport.Status.READY

        artefacts = list(SignalReportArtefact.objects.filter(report_id=report.id).order_by("created_at"))
        assert [a.type for a in artefacts] == ["feature_lifecycle", "note", "task_run"]
        # The groundskeeping note is the full operating contract: it must carry the report id, the
        # MCP write tool, and the owner scout's exact skill name.
        note = artefacts[1].content
        assert "About this feature report" in note
        assert created.report_id in note
        assert "inbox-report-artefacts-create" in note
        assert owner_scout_skill_name(created.report_id) in note
        assert "living overview" in note
        assert "Questions before action" in note
        assert "Prefer asking a question" in note
        assert "starting implementation work" in note

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
        assert "planning agent for a software feature" in first_message
        assert "monitor, and optimize" in first_message
        assert "inspect every outstanding `question` artefact" in first_message
        assert "living overview" in first_message
        assert "feature's first planning session" in first_message
        assert "Build a widget" in first_message

    def test_feature_planning_readiness_lists_missing_pieces(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        readiness = feature_planning_readiness(team_id=self.team.id, report=report)
        assert not readiness.ready
        assert set(readiness.missing) == {"title", "summary", "repository selection", "owners", "priority"}
        assert not readiness.planning_finished

    def test_finish_feature_planning_rejects_unready_feature(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="t", summary="s")
        with self.assertRaises(FeaturePlanningNotReadyError) as ctx:
            finish_feature_planning(team=self.team, user=self.user, report=report)
        assert "owners" in ctx.exception.missing

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_finish_feature_planning_writes_defaults_and_creates_scout_idempotently(self, mock_create_task):
        # Owner "me" must resolve to an org member for the implementation kickoff to attribute the task.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me", extra_data={"login": "me"})
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = _make_ready_feature(self.team, self.user)

        completion = finish_feature_planning(team=self.team, user=self.user, report=report)
        skill_name = completion.scout_skill_name

        assert skill_name == owner_scout_skill_name(str(report.id))
        # The first implementation pass auto-starts when planning finishes (the owner scout only runs daily).
        assert completion.implementation_task_id == str(mock_create_task.return_value.task_id)
        assert mock_create_task.call_args.kwargs["ai_stage"] == "implementation"
        assert mock_create_task.call_args.kwargs["repository"] == "posthog/posthog"
        types = set(SignalReportArtefact.objects.filter(report_id=report.id).values_list("type", flat=True))
        assert "safety_judgment" in types
        assert "actionability_judgment" in types

        skill = LLMSkill.objects.get(team=self.team, name=skill_name, is_latest=True)
        assert skill.allowed_tools == ["edit_report", "start_implementation"]
        assert str(report.id) in skill.body
        assert "Monitor and optimize" in skill.body
        assert "PostHog" in skill.body
        assert "Resolve questions before work" in skill.body
        assert "do not start implementation" in skill.body
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=skill_name)
        assert config.enabled

        # Second planning completion: no duplicate skill/config, no second implementation pass.
        second = finish_feature_planning(team=self.team, user=self.user, report=report)
        assert second.scout_skill_name == skill_name
        assert second.implementation_task_id is None
        assert mock_create_task.call_count == 1
        assert LLMSkill.objects.filter(team=self.team, name=skill_name).count() == 1
        assert SignalReportArtefact.objects.filter(report_id=report.id, type="safety_judgment").count() == 1


class TestFeatureAPI(APIBaseTest):
    @patch("products.signals.backend.features.service.tasks_facade.create_and_run_task")
    def test_create_endpoint_returns_ids(self, mock_create):
        mock_create.return_value = _mock_created_task(self.team, self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/features/",
            {"initial_description": "Build a widget"},
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["report_id"]
        assert body["task_id"]

    @patch("products.signals.backend.features.service.tasks_facade.create_and_run_task")
    def test_list_surfaces_features_in_planning_via_postgres_marker(self, mock_create):
        # The Postgres planning marker is the sole membership source, so a feature appears from the
        # moment of creation without entering the signal grouping pipeline.
        mock_create.return_value = _mock_created_task(self.team, self.user)
        created = create_feature(team=self.team, user=self.user, initial_description="Build a widget")

        response = self.client.get(f"/api/projects/{self.team.id}/signals/features/")
        assert response.status_code == 200, response.content
        rows = response.json()["results"]
        assert [r["id"] for r in rows] == [created.report_id]
        assert rows[0]["is_planning"] is True
        assert rows[0]["feature_stage"] == "planning"

    @patch("products.signals.backend.features.views.start_feature_discovery")
    def test_discover_endpoint_passes_repository_and_focus_to_workflow_launcher(self, mock_start: MagicMock) -> None:
        mock_start.return_value = CreatedFeatureDiscovery(run_id=str(uuid4()))

        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/features/discover/",
            {"repository": "PostHog/posthog", "focus": "Only session replay features"},
        )

        assert response.status_code == 201, response.content
        assert response.json()["run_id"]
        assert mock_start.call_args.kwargs == {
            "team": self.team,
            "user": self.user,
            "repository": "PostHog/posthog",
            "focus": "Only session replay features",
        }

    def test_finish_planning_endpoint_returns_missing_on_unready_feature(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/finish_planning/")
        assert response.status_code == 400, response.content
        assert "title" in response.json()["missing"]

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_finish_planning_converges_divergent_owner_scout_to_template(self, mock_create_task):
        # An agent-authored skill under the deterministic name is overwritten with the canonical
        # body. Feature tailoring belongs in the playbook so monitoring and implementation behavior
        # cannot drift.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me3", extra_data={"login": "me"})
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = _make_ready_feature(self.team, self.user)
        LLMSkill.objects.create(
            team=self.team,
            name=owner_scout_skill_name(str(report.id)),
            description="agent authored",
            body="# my own ideas, no sweep, no protocol",
            allowed_tools=["edit_report"],
        )

        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/finish_planning/")
        assert response.status_code == 200, response.content
        assert response.json()["planning_finished"] is True

        skill = LLMSkill.objects.get(team=self.team, name=response.json()["scout_skill_name"], is_latest=True)
        assert "Owner scout playbook" in skill.body
        assert "associated_report" in skill.body
        assert skill.allowed_tools == ["edit_report", "start_implementation"]

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_start_implementation_endpoint_starts_a_pass(self, mock_create):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-me2", extra_data={"login": "me"})
        mock_create.return_value = _mock_created_task(self.team, self.user)
        report = _make_ready_feature(self.team, self.user)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FeatureLifecycle(feature_stage=FeatureStage.MANAGED, source=FeatureSource.MANUAL),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reevaluate_autostart=False,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/start_implementation/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["task_id"] == str(mock_create.return_value.task_id)
        assert body["repository"] == "posthog/posthog"
        assert mock_create.call_args.kwargs["ai_stage"] == "implementation"
        assert mock_create.call_args.kwargs["user_id"] == self.user.id
        assert mock_create.call_args.kwargs["internal"] is True

    def test_finish_planning_endpoint_404_for_other_team_report(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/finish_planning/")
        assert response.status_code == 404

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_start_planning_keeps_discovered_feature_staged_and_uses_its_repository(
        self, mock_create_task: MagicMock
    ) -> None:
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = _make_ready_feature(self.team, self.user)
        discovery_run_id = str(uuid4())
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FeatureLifecycle(
                feature_stage=FeatureStage.STAGED,
                source=FeatureSource.DISCOVERY,
                discovery_run_id=discovery_run_id,
            ),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reevaluate_autostart=False,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/start_planning/")

        assert response.status_code == 200, response.content
        assert response.json() == {
            "report_id": str(report.id),
            "task_id": str(mock_create_task.return_value.task_id),
            "run_id": str(mock_create_task.return_value.latest_run.id),
        }
        lifecycles = SignalReportArtefact.objects.filter(
            report_id=report.id,
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        )
        assert lifecycles.count() == 1
        parsed_lifecycle = FeatureLifecycle.model_validate_json(lifecycles.get().content)
        assert parsed_lifecycle.feature_stage == FeatureStage.STAGED
        assert parsed_lifecycle.source == FeatureSource.DISCOVERY
        assert parsed_lifecycle.discovery_run_id == discovery_run_id

        kwargs = mock_create_task.call_args.kwargs
        assert kwargs["repository"] == "posthog/posthog"
        assert kwargs["mode"] == "interactive"
        assert kwargs["signal_report_id"] == str(report.id)
        assert kwargs["ai_stage"] == "planning"
        assert kwargs["title"] == "Plan a discovered feature"
        first_message = kwargs["pending_user_message"]
        assert "planning agent for a software feature" in first_message
        assert "has not been promoted into active ownership" in first_message
        assert "ask which future the user wants" in first_message
        assert report.summary in first_message

        artefacts = list(SignalReportArtefact.objects.filter(report_id=report.id).order_by("created_at"))
        planning_runs = [a for a in artefacts if a.type == "task_run" and '"type":"planning"' in a.content]
        assert len(planning_runs) == 1
        assert mock_create_task.call_count == 1
        assert not any(a.type in {"safety_judgment", "actionability_judgment"} for a in artefacts)
        assert not SignalScoutConfig.all_teams.filter(
            team=self.team, skill_name=owner_scout_skill_name(str(report.id))
        ).exists()

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_start_planning_revisits_a_managed_feature_without_replacing_its_owner(
        self, mock_create_task: MagicMock
    ) -> None:
        mock_create_task.return_value = _mock_created_task(self.team, self.user)
        report = _make_ready_feature(self.team, self.user)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FeatureLifecycle(feature_stage=FeatureStage.MANAGED, source=FeatureSource.MANUAL),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reevaluate_autostart=False,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/start_planning/")

        assert response.status_code == 200, response.content
        kwargs = mock_create_task.call_args.kwargs
        assert kwargs["title"] == "Revisit feature planning"
        assert kwargs["repository"] == "posthog/posthog"
        assert "existing feature with an active owner scout" in kwargs["pending_user_message"]
        assert "do not recreate or replace its owner" in kwargs["pending_user_message"]
        lifecycle = SignalReportArtefact.objects.filter(
            report_id=report.id,
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        ).get()
        assert FeatureLifecycle.model_validate_json(lifecycle.content).feature_stage == FeatureStage.MANAGED

    def test_features_are_hidden_when_the_flag_is_disabled(self):
        with patch("products.signals.backend.features.access.posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/features/")
        assert response.status_code == 404

    def test_stage_pagination_does_not_hide_live_features_behind_staged_features(self):
        staged_ids = []
        for stage in [FeatureStage.STAGED, FeatureStage.STAGED, FeatureStage.MANAGED]:
            report = _make_ready_feature(self.team, self.user)
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=FeatureLifecycle(
                    feature_stage=stage, source=FeatureSource.DISCOVERY, discovery_run_id=str(uuid4())
                ),
                attribution=ArtefactAttribution.system(),
                reevaluate_autostart=False,
            )
            if stage == FeatureStage.STAGED:
                staged_ids.append(str(report.id))
        url = f"/api/projects/{self.team.id}/signals/features/"
        live = self.client.get(url, {"stage": "live", "limit": "1"})
        assert live.status_code == 200, live.content
        assert [row["id"] for row in live.json()["results"]] == [str(report.id)]
        first = self.client.get(url, {"stage": "staged", "limit": "1"}).json()
        second = self.client.get(first["next"]).json()
        assert {row["id"] for page in [first, second] for row in page["results"]} == set(staged_ids)
        assert second["next"] is None

    def test_readiness_blocks_unanswered_questions_and_empty_repository(self):
        report = _make_ready_feature(self.team, self.user)
        question = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=QuestionArtefact(question="Which users?", options=["Everyone", "Staff"]),
            attribution=ArtefactAttribution.system(),
        )
        url = f"/api/projects/{self.team.id}/signals/features/{report.id}/planning_readiness/"
        response = self.client.get(url)
        assert response.status_code == 200, response.content
        assert response.json()["missing"] == ["answers to open questions"]
        question.content = QuestionArtefact(
            question="Which users?", options=["Everyone", "Staff"], answered=True, answer="Staff"
        ).model_dump_json()
        question.save(update_fields=["content"])
        assert self.client.get(url).json()["ready"] is True
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=RepoSelectionResult(repository=None, reason="No repository"),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )
        assert self.client.get(url).json()["missing"] == ["repository selection"]

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_batch_promotions_get_distinct_owner_scouts(self, mock_create):
        reports = [
            _make_ready_feature(self.team, self.user, UUID(f"01991688-1234-7000-8000-{index:012d}"))
            for index in range(2)
        ]
        for report in reports:
            mock_create.return_value = _mock_created_task(self.team, self.user)
            finish_feature_planning(team=self.team, user=self.user, report=report)
        names = [owner_scout_skill_name(str(report.id)) for report in reports]
        assert names[0] != names[1]
        assert SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name__in=names, enabled=True).count() == 2
        for report, name in zip(reports, names):
            assert str(report.id) in LLMSkill.objects.get(team=self.team, name=name, is_latest=True).body

    @patch("products.signals.backend.features.views.start_feature_discovery")
    def test_scoped_oauth_can_read_custom_actions_and_start_discovery(self, mock_start):
        authenticate_as_sandbox_token(self)
        mock_start.return_value = CreatedFeatureDiscovery(run_id=str(uuid4()))
        response = self.client.get(f"/api/projects/{self.team.id}/signals/features/discovery_runs/")
        assert response.status_code == 200, response.content
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/features/discover/",
            {"repository": "PostHog/posthog", "focus": "Replay"},
        )
        assert response.status_code == 201, response.content

    @patch("products.signals.backend.auto_start.resolve_agent_runtime")
    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_generic_report_autostart_cannot_bypass_feature_readiness(self, mock_create, mock_runtime):
        report = _make_ready_feature(self.team, self.user)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FeatureLifecycle(feature_stage=FeatureStage.PLANNING, source=FeatureSource.MANUAL),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reevaluate_autostart=False,
        )
        started = _create_implementation_task_if_absent(
            team_id=self.team.id,
            report_id=str(report.id),
            title="Feature",
            description="Implement",
            user_id=self.user.id,
            repository="PostHog/posthog",
            base_branch=None,
        )
        assert not started
        mock_create.assert_not_called()

    @patch("products.tasks.backend.facade.api.create_and_run_task")
    def test_implementation_task_rolls_back_when_recording_its_association_fails(self, mock_create):
        report = _make_ready_feature(self.team, self.user)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FeatureLifecycle(feature_stage=FeatureStage.MANAGED, source=FeatureSource.MANUAL),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reevaluate_autostart=False,
        )
        mock_create.side_effect = lambda **kwargs: _mock_created_task(self.team, self.user)
        task_count = Task.objects.filter(team=self.team).count()
        with patch(
            "products.signals.backend.task_run_artefacts.record_implementation_task",
            side_effect=RuntimeError("Association unavailable"),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/signals/features/{report.id}/start_implementation/")
            assert response.status_code == 500
        assert Task.objects.filter(team=self.team).count() == task_count
