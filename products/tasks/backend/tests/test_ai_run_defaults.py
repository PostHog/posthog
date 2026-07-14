from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Integration, User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.logic.services.ai_run_defaults import (
    resolve_ai_run_defaults,
    resolve_ai_run_selection,
    update_team_ai_run_preferences,
    update_user_ai_run_preferences,
)
from products.tasks.backend.models import Task, TeamTasksConfig, UserTasksConfig

FACADE = "products.tasks.backend.facade.api"

TEAM_TRIPLE = {"runtime_adapter": "claude", "model": "claude-opus-4-8", "reasoning_effort": "high"}
USER_TRIPLE = {"runtime_adapter": "codex", "model": "gpt-5.5", "reasoning_effort": "medium"}


class TestResolveAIRunDefaults(APIBaseTest):
    def _set_team(self, prefs: dict[str, Any]) -> None:
        TeamTasksConfig.objects.update_or_create(team=self.team, defaults={"ai_run_preferences": prefs})

    def _set_user(self, prefs: dict[str, Any], user: User | None = None) -> None:
        UserTasksConfig.objects.for_team(self.team.id).update_or_create(
            team_id=self.team.id, user_id=(user or self.user).id, defaults={"ai_run_preferences": prefs}
        )

    def test_no_preferences_resolves_to_none(self):
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "none"
        assert resolved.model is None

    def test_team_default_applies_when_user_has_none(self):
        self._set_team(TEAM_TRIPLE)
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "team"
        assert (resolved.runtime_adapter, resolved.model, resolved.reasoning_effort) == (
            "claude",
            "claude-opus-4-8",
            "high",
        )

    def test_user_triple_replaces_team_triple_wholesale(self):
        self._set_team(TEAM_TRIPLE)
        self._set_user({"runtime_adapter": "codex", "model": "gpt-5.5"})
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "user"
        # The team's reasoning_effort must not blend into the user's effort-less triple.
        assert (resolved.runtime_adapter, resolved.model, resolved.reasoning_effort) == ("codex", "gpt-5.5", None)

    @parameterized.expand(
        [
            ("empty_payload", {}),
            ("model_without_adapter", {"model": "claude-opus-4-8"}),
            ("unknown_adapter", {"runtime_adapter": "gemini", "model": "gemini-3"}),
        ]
    )
    def test_unusable_user_row_falls_through_to_team(self, _name: str, user_prefs: dict[str, Any]):
        self._set_team(TEAM_TRIPLE)
        self._set_user(user_prefs)
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "team"
        assert resolved.model == "claude-opus-4-8"

    def test_another_users_preference_does_not_leak(self):
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        self._set_user(USER_TRIPLE, user=other)
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "none"

    def test_unsupported_effort_is_dropped_but_model_passes_through(self):
        # claude-sonnet-4-6 caps at high; a stored max effort must not reach the run.
        self._set_team({"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "max"})
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.model == "claude-sonnet-4-6"
        assert resolved.reasoning_effort is None

    def test_unknown_model_id_passes_through(self):
        self._set_team({"runtime_adapter": "claude", "model": "claude-galaxy-9"})
        resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "team"
        assert resolved.model == "claude-galaxy-9"

    @parameterized.expand(
        [
            ("full_pair", "claude", "claude-opus-4-8", None),
            ("model_only_partial_pin", None, "claude-opus-4-8", None),
            ("adapter_only_partial_pin", "claude", None, "low"),
        ]
    )
    def test_selection_treats_any_pin_as_explicit(
        self, _name: str, runtime_adapter: str | None, model: str | None, reasoning_effort: str | None
    ):
        self._set_team(TEAM_TRIPLE)
        selection = resolve_ai_run_selection(
            self.team.id,
            self.user.id,
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        assert selection.source == "explicit"
        assert (selection.runtime_adapter, selection.model, selection.reasoning_effort) == (
            runtime_adapter,
            model,
            reasoning_effort,
        )

    def test_selection_preserves_explicit_effort_over_default_triples_effort(self):
        self._set_team(TEAM_TRIPLE)
        selection = resolve_ai_run_selection(self.team.id, self.user.id, reasoning_effort="low")
        assert selection.source == "team"
        assert (selection.runtime_adapter, selection.model, selection.reasoning_effort) == (
            "claude",
            "claude-opus-4-8",
            "low",
        )


class TestCreateRunAppliesDefaults(APIBaseTest):
    def _task(self, **overrides) -> Task:
        params: dict[str, Any] = {
            "team": self.team,
            "title": "t",
            "description": "d",
            "origin_product": Task.OriginProduct.USER_CREATED,
            "created_by": self.user,
        }
        params.update(overrides)
        return Task.objects.create(**params)

    def test_run_state_carries_default_triple_provider_and_source(self):
        update_team_ai_run_preferences(self.team.id, **TEAM_TRIPLE)
        run = self._task().create_run()
        assert run.state["runtime_adapter"] == "claude"
        assert run.state["model"] == "claude-opus-4-8"
        assert run.state["reasoning_effort"] == "high"
        assert run.state["provider"] == "anthropic"
        assert run.state["ai_defaults_source"] == "team"

    def test_codex_default_sets_auto_permission_mode(self):
        update_team_ai_run_preferences(self.team.id, **USER_TRIPLE)
        run = self._task().create_run()
        assert run.state["runtime_adapter"] == "codex"
        assert run.state["initial_permission_mode"] == "auto"

    def test_explicit_selection_is_untouched(self):
        update_team_ai_run_preferences(self.team.id, **TEAM_TRIPLE)
        run = self._task().create_run(extra_state={"runtime_adapter": "codex", "model": "gpt-5", "provider": "openai"})
        assert run.state["model"] == "gpt-5"
        assert "ai_defaults_source" not in run.state

    def test_internal_task_never_inherits_defaults(self):
        update_team_ai_run_preferences(self.team.id, **TEAM_TRIPLE)
        run = self._task(internal=True).create_run()
        assert "model" not in run.state

    def test_acting_user_preference_wins_over_task_creators(self):
        update_user_ai_run_preferences(self.team.id, self.user.id, **TEAM_TRIPLE)
        actor = User.objects.create_and_join(self.organization, "actor@posthog.com", None)
        update_user_ai_run_preferences(self.team.id, actor.id, **USER_TRIPLE)
        run = self._task().create_run(acting_user_id=actor.id)
        assert run.state["model"] == "gpt-5.5"
        assert run.state["ai_defaults_source"] == "user"


class TestRunTaskWarmMatchingUnderDefaults(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})

    def test_default_carrying_warm_run_is_activated_by_a_pinless_submit(self):
        update_team_ai_run_preferences(self.team.id, **TEAM_TRIPLE)
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            repository="posthog/posthog",
            github_integration=self.integration,
        )
        warm_run = task.create_run(
            mode="interactive", extra_state={"await_user_message": True, "branch": "main"}, branch="main"
        )
        assert warm_run.state["model"] == "claude-opus-4-8"

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "branch": "main", "pending_user_message": "go"},
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 1
        warm_run.refresh_from_db()
        assert "await_user_message" not in warm_run.state


class TestTasksConfigAPI(APIBaseTest):
    def test_team_config_round_trip(self):
        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.status_code == 200
        assert response.json() == {"ai_run_preferences": {}}

        response = self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE)
        assert response.status_code == 200
        assert response.json()["ai_run_preferences"] == TEAM_TRIPLE

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.json()["ai_run_preferences"] == TEAM_TRIPLE

    @parameterized.expand(
        [
            ("model_without_adapter", {"model": "claude-opus-4-8"}),
            ("unknown_adapter", {"runtime_adapter": "gemini", "model": "gemini-3"}),
            (
                "unsupported_effort",
                {"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "max"},
            ),
        ]
    )
    def test_invalid_triples_are_rejected(self, _name: str, payload: dict[str, Any]):
        response = self.client.post(f"/api/projects/{self.team.id}/tasks/config/", payload)
        assert response.status_code == 400

    def test_my_config_resolved_defaults_reflect_precedence(self):
        self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE)

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/my_config/")
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == {}
        assert body["resolved_ai_run_defaults"]["source"] == "team"
        assert body["resolved_ai_run_defaults"]["model"] == "claude-opus-4-8"

        response = self.client.post(f"/api/projects/{self.team.id}/tasks/my_config/", USER_TRIPLE)
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == USER_TRIPLE
        assert body["resolved_ai_run_defaults"]["source"] == "user"
        assert body["resolved_ai_run_defaults"]["model"] == "gpt-5.5"

        response = self.client.post(
            f"/api/projects/{self.team.id}/tasks/my_config/",
            {"runtime_adapter": None, "model": None, "reasoning_effort": None},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == {}
        assert body["resolved_ai_run_defaults"]["source"] == "team"

    def test_my_config_is_scoped_to_the_requesting_user(self):
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        UserTasksConfig.objects.for_team(self.team.id).update_or_create(
            team_id=self.team.id, user_id=other.id, defaults={"ai_run_preferences": USER_TRIPLE}
        )
        response = self.client.get(f"/api/projects/{self.team.id}/tasks/my_config/")
        assert response.json()["ai_run_preferences"] == {}
