import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.signals.backend.models import SignalTeamConfig
from products.tasks.backend.constants import AGENT_INSTRUCTIONS_MAX_LENGTH, AGENT_INSTRUCTIONS_STATE_KEY
from products.tasks.backend.logic.services.agent_instructions import (
    AgentInstructionsResolver,
    AgentInstructionsStore,
    agent_instructions_state_update,
    refresh_agent_instructions_state,
)
from products.tasks.backend.models import Task, TaskRun

TEAM_TRIPLE = {"runtime_adapter": "claude", "model": "claude-opus-4-8", "reasoning_effort": "high"}


class TestAgentInstructionsResolver(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.store = AgentInstructionsStore()
        self.store.set_project(self.team.id, "Use pnpm.")
        self.store.set_personal(self.team.id, self.user.id, "Reply tersely.")

    def _task(self, origin: str = Task.OriginProduct.USER_CREATED, internal: bool = False) -> Task:
        return Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin,
            created_by=self.user,
            internal=internal,
        )

    @parameterized.expand(
        [
            ("person_started", Task.OriginProduct.USER_CREATED, False, True, True),
            ("slack", Task.OriginProduct.SLACK, False, True, True),
            ("loop", Task.OriginProduct.LOOP, False, True, False),
            ("workflow", Task.OriginProduct.WORKFLOW, False, True, False),
            ("signals_scout", Task.OriginProduct.SIGNALS_SCOUT, False, True, False),
            ("internal_signals_scout", Task.OriginProduct.SIGNALS_SCOUT, True, True, False),
            ("scout_suggestions", Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS, False, True, False),
            ("internal_scout_suggestions", Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS, True, True, False),
            ("signal_report", Task.OriginProduct.SIGNAL_REPORT, False, True, False),
            ("internal_signal_report", Task.OriginProduct.SIGNAL_REPORT, True, True, False),
            ("signals_chat", Task.OriginProduct.SIGNALS_CHAT, False, True, True),
            ("internal_signals_chat", Task.OriginProduct.SIGNALS_CHAT, True, True, False),
            ("posthog_ai", Task.OriginProduct.POSTHOG_AI, False, True, True),
            ("internal", Task.OriginProduct.USER_CREATED, True, False, False),
            ("business_knowledge", Task.OriginProduct.BUSINESS_KNOWLEDGE, False, False, False),
            ("image_builder", Task.OriginProduct.IMAGE_BUILDER, False, False, False),
            ("task_analysis", Task.OriginProduct.TASK_ANALYSIS, False, False, False),
        ]
    )
    def test_levels_follow_the_run_origin(
        self, _name: str, origin: str, internal: bool, has_project: bool, has_personal: bool
    ) -> None:
        rendered = AgentInstructionsResolver().resolve(self._task(origin, internal), actor_user=None) or ""
        assert ("Use pnpm." in rendered) is has_project
        assert ("Reply tersely." in rendered) is has_personal

    def test_the_acting_users_instructions_replace_the_creators(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        self.store.set_personal(self.team.id, other.id, "Write in Spanish.")
        rendered = AgentInstructionsResolver().resolve(self._task(), actor_user=other) or ""
        assert "Write in Spanish." in rendered
        assert "Reply tersely." not in rendered

    def test_cleared_instructions_remove_the_state_key(self) -> None:
        self.store.set_project(self.team.id, "  ")
        self.store.set_personal(self.team.id, self.user.id, "")
        assert agent_instructions_state_update(self._task(), actor_user=None) == ({}, [AGENT_INSTRUCTIONS_STATE_KEY])

    @parameterized.expand(
        [
            ("signals_scout", "scout_custom", "scout"),
            ("signal_report", "research", "research"),
            ("signal_report", "implementation", "implementation"),
            ("signal_report", "repo_selection", None),
            ("signal_report", None, None),
            ("scout_suggestions", "research", None),
            ("signals_chat", None, None),
        ]
    )
    def test_internal_signals_receive_project_and_only_their_role(
        self, origin: str, stage: str | None, expected_role: str | None
    ) -> None:
        role_instructions = {
            "scout": "Focus on onboarding failures.",
            "research": "Check whether the behavior is intentional.",
            "implementation": "Open draft pull requests.",
        }
        SignalTeamConfig.objects.update_or_create(
            team=self.team, defaults={f"{role}_instructions": text for role, text in role_instructions.items()}
        )
        updates, removed = agent_instructions_state_update(self._task(origin, internal=True), None, ai_stage=stage)
        rendered = updates[AGENT_INSTRUCTIONS_STATE_KEY]
        assert "Use pnpm." in rendered
        assert "Reply tersely." not in rendered
        assert removed == []
        for role, text in role_instructions.items():
            assert (text in rendered) is (role == expected_role)
        if expected_role:
            assert f"Your role is {expected_role}." in rendered

    def test_resume_refreshes_and_clears_the_runs_role_instructions(self) -> None:
        task = self._task(Task.OriginProduct.SIGNAL_REPORT, internal=True)
        run = TaskRun.objects.create(task=task, team=self.team, state={"ai_stage": "research"})
        config, _ = SignalTeamConfig.objects.update_or_create(
            team=self.team, defaults={"research_instructions": "Inspect session recordings."}
        )
        refresh_agent_instructions_state(run, self.user, reason="test")
        run.refresh_from_db()
        assert "Use pnpm." in run.state[AGENT_INSTRUCTIONS_STATE_KEY]
        assert "Inspect session recordings." in run.state[AGENT_INSTRUCTIONS_STATE_KEY]

        self.store.set_project(self.team.id, "")
        refresh_agent_instructions_state(run, self.user, reason="test")
        run.refresh_from_db()
        assert "Project instructions" not in run.state[AGENT_INSTRUCTIONS_STATE_KEY]
        assert "Inspect session recordings." in run.state[AGENT_INSTRUCTIONS_STATE_KEY]

        config.research_instructions = ""
        config.save(update_fields=["research_instructions"])
        refresh_agent_instructions_state(run, self.user, reason="test")
        run.refresh_from_db()
        assert AGENT_INSTRUCTIONS_STATE_KEY not in run.state
        assert run.state["ai_stage"] == "research"


class TestAgentInstructionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/tasks/{path}/"

    @parameterized.expand(["config", "@me/config"])
    def test_instructions_and_model_preferences_save_independently(self, path: str) -> None:
        response = self.client.post(self._url(f"{path}/agent_instructions"), {"agent_instructions": "Use pnpm."})
        assert response.status_code == 200, response.content
        assert self.client.post(self._url(path), TEAM_TRIPLE).status_code == 200

        body = self.client.get(self._url(path)).json()
        assert body["agent_instructions"] == "Use pnpm."
        assert body["ai_run_preferences"]["model"] == TEAM_TRIPLE["model"]

        assert self.client.post(self._url(f"{path}/agent_instructions"), {"agent_instructions": ""}).status_code == 200
        body = self.client.get(self._url(path)).json()
        assert body["agent_instructions"] == ""
        assert body["ai_run_preferences"]["model"] == TEAM_TRIPLE["model"]

    def test_a_member_can_set_personal_but_not_project_instructions(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        payload = {"agent_instructions": "Use pnpm."}
        assert self.client.post(self._url("config/agent_instructions"), payload).status_code == 403
        assert self.client.post(self._url("@me/config/agent_instructions"), payload).status_code == 200

    @parameterized.expand(["config", "@me/config"])
    def test_instructions_over_the_cap_are_rejected(self, path: str) -> None:
        payload = {"agent_instructions": "x" * (AGENT_INSTRUCTIONS_MAX_LENGTH + 1)}
        assert self.client.post(self._url(f"{path}/agent_instructions"), payload).status_code == 400

    @parameterized.expand(
        [
            ("tasks/config/agent_instructions", "agent_instructions", "agent instructions"),
            ("tasks/@me/config/agent_instructions", "agent_instructions", "agent instructions"),
            (
                "signals/config",
                "research_instructions",
                "steering instructions or implementation repositories",
            ),
            (
                "signals/config",
                "implementation_repositories",
                "steering instructions or implementation repositories",
            ),
        ]
    )
    def test_a_task_agent_cannot_rewrite_instructions(self, path: str, field: str, label: str) -> None:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        application = OAuthApplication.objects.create(
            name="Task agent",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_task_agent_{uuid.uuid4().hex}",
            expires=django_timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task.id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        value: str | list[str] = (
            ["attacker/assets"] if field == "implementation_repositories" else "Change the project rules."
        )
        response = client.post(f"/api/projects/{self.team.id}/{path}/", {field: value}, format="json")
        assert response.status_code == 403, response.content
        assert response.json()["detail"] == f"Task agents cannot modify {label}."
        read_path = path.removesuffix("/agent_instructions")
        assert client.get(f"/api/projects/{self.team.id}/{read_path}/").status_code == 200
