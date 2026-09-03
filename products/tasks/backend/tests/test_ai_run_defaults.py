from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Integration, Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.tasks.backend.facade import api as facade
from products.tasks.backend.logic.services.ai_run_defaults import (
    get_team_ai_run_preferences,
    resolve_ai_run_defaults,
    resolve_ai_run_selection,
    update_team_ai_run_preferences,
    update_user_ai_run_preferences,
)
from products.tasks.backend.models import Task, TeamTasksConfig, UserTasksConfig
from products.tasks.backend.presentation.serializers import TaskRunCreateRequestSerializer

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

    # Config rows are keyed on the project root team, so an environment team must read and
    # write the same row as the root — a CRUD path skipping the normalization would silently
    # fork the project default per environment.
    def test_environment_team_shares_the_project_root_config(self):
        env_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="env"
        )
        update_team_ai_run_preferences(env_team.id, **TEAM_TRIPLE)
        assert get_team_ai_run_preferences(self.team.id) == TEAM_TRIPLE
        resolved = resolve_ai_run_defaults(env_team.id, self.user.id)
        assert resolved.source == "team"
        assert resolved.model == "claude-opus-4-8"

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


class TestRunCreateSerializerModeWithoutAdapter(APIBaseTest):
    # A composer that pins nothing must still be able to state the launch mode — the
    # server resolves the runtime from the stored default and clamps the mode to it.
    def test_mode_without_adapter_is_accepted(self):
        serializer = TaskRunCreateRequestSerializer(data={"initial_permission_mode": "plan"})
        assert serializer.is_valid(), serializer.errors

    def test_mode_outside_the_pinned_adapters_vocabulary_is_still_rejected(self):
        serializer = TaskRunCreateRequestSerializer(
            data={"runtime_adapter": "codex", "model": "gpt-5.5", "initial_permission_mode": "acceptEdits"}
        )
        assert not serializer.is_valid()
        assert "initial_permission_mode" in serializer.errors


class TestModelAccessGating(APIBaseTest):
    GATED = "claude-opus-4-8"

    def _set_team(self, prefs: dict[str, Any]) -> None:
        TeamTasksConfig.objects.update_or_create(team=self.team, defaults={"ai_run_preferences": prefs})

    def _set_user(self, prefs: dict[str, Any]) -> None:
        UserTasksConfig.objects.for_team(self.team.id).update_or_create(
            team_id=self.team.id, user_id=self.user.id, defaults={"ai_run_preferences": prefs}
        )

    def _gate(self, module: str):
        gated = self.GATED
        return (
            patch(
                f"{module}.get_required_model_flag",
                side_effect=lambda model: "gated-model-flag" if model == gated else None,
            ),
            patch(
                f"{module}.get_model_access_error",
                side_effect=lambda model, *, distinct_id: (
                    f"'{model}' is not available for your account." if model == gated else None
                ),
            ),
        )

    RESOLVER = "products.tasks.backend.logic.services.ai_run_defaults"

    def test_gated_user_default_falls_through_to_team(self):
        self._set_user(TEAM_TRIPLE)  # names the gated model
        self._set_team(USER_TRIPLE)
        flag_patch, access_patch = self._gate(self.RESOLVER)
        with flag_patch, access_patch as access_mock:
            resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "team"
        assert resolved.model == "gpt-5.5"
        access_mock.assert_called_once_with(self.GATED, distinct_id=self.user.distinct_id)

    def test_gated_team_default_resolves_to_none(self):
        self._set_team(TEAM_TRIPLE)
        flag_patch, access_patch = self._gate(self.RESOLVER)
        with flag_patch, access_patch:
            resolved = resolve_ai_run_defaults(self.team.id, self.user.id)
        assert resolved.source == "none"
        assert resolved.model is None

    def test_storing_a_gated_model_as_a_default_is_rejected(self):
        # The API check calls get_model_access_error directly; no flag patch needed.
        _, access_patch = self._gate("products.tasks.backend.presentation.views.config_api")
        with access_patch:
            response = self.client.post(f"/api/projects/{self.team.id}/tasks/@me/config/", TEAM_TRIPLE)
            assert response.status_code == 400
            assert "not available" in str(response.json())
            response = self.client.post(f"/api/projects/{self.team.id}/tasks/@me/config/", USER_TRIPLE)
            assert response.status_code == 200


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

    def test_pi_runtime_task_never_inherits_defaults(self):
        update_team_ai_run_preferences(self.team.id, **TEAM_TRIPLE)
        run = self._task(runtime=Task.Runtime.PI).create_run()
        assert "model" not in run.state
        assert "ai_defaults_source" not in run.state

    # The composer states the launch mode even when it pins no runtime, deferring the
    # model to the stored default — the mode must then be clamped to whichever
    # runtime's vocabulary the default resolves to, not fail the run downstream.
    @parameterized.expand(
        [
            ("claude_mode_on_codex_default", USER_TRIPLE, "acceptEdits", "auto"),
            ("codex_mode_on_claude_default", TEAM_TRIPLE, "read-only", "default"),
            ("shared_mode_survives", TEAM_TRIPLE, "plan", "plan"),
        ]
    )
    def test_permission_mode_clamps_to_the_resolved_runtime(
        self, _name: str, default_triple: dict[str, Any], sent_mode: str, expected_mode: str
    ):
        update_team_ai_run_preferences(self.team.id, **default_triple)
        run = self._task().create_run(extra_state={"initial_permission_mode": sent_mode})
        assert run.state["initial_permission_mode"] == expected_mode

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
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_team_config_round_trip(self):
        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.status_code == 200
        assert response.json() == {
            "ai_run_preferences": {"runtime_adapter": None, "model": None, "reasoning_effort": None},
            "email_inbox_address": None,
        }

        response = self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE)
        assert response.status_code == 200
        assert response.json()["ai_run_preferences"] == TEAM_TRIPLE

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/config/")
        assert response.json()["ai_run_preferences"] == TEAM_TRIPLE

    @parameterized.expand(
        [
            ("model_without_adapter", {"model": "claude-opus-4-8"}),
            ("unknown_effort", {"reasoning_effort": "extreme"}),
            ("unknown_adapter", {"runtime_adapter": "gemini", "model": "gemini-3"}),
            (
                "unsupported_effort",
                {"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "max"},
            ),
        ]
    )
    def test_invalid_triples_are_rejected(self, _name: str, payload: dict[str, Any]):
        # Both endpoints share the validation path; asserting both keeps either from losing it.
        for path in ("config", "@me/config"):
            response = self.client.post(f"/api/projects/{self.team.id}/tasks/{path}/", payload)
            assert response.status_code == 400, (path, response.content)

    def test_clearing_the_team_default(self):
        self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE)
        response = self.client.post(
            f"/api/projects/{self.team.id}/tasks/config/",
            {"runtime_adapter": None, "model": None, "reasoning_effort": None},
        )
        assert response.status_code == 200
        assert response.json() == {
            "ai_run_preferences": {"runtime_adapter": None, "model": None, "reasoning_effort": None},
            "email_inbox_address": None,
        }
        assert self.client.get(f"/api/projects/{self.team.id}/tasks/config/").json() == {
            "ai_run_preferences": {"runtime_adapter": None, "model": None, "reasoning_effort": None},
            "email_inbox_address": None,
        }

    def test_unauthenticated_requests_are_rejected(self):
        self.client.logout()
        for path in ("config", "@me/config"):
            url = f"/api/projects/{self.team.id}/tasks/{path}/"
            # 403, not 401: DRF's SessionAuthentication denies without a WWW-Authenticate challenge.
            assert self.client.get(url).status_code == 403
            assert self.client.post(url, TEAM_TRIPLE).status_code == 403

    def test_an_outsider_cannot_reach_another_projects_config(self):
        outsider = User.objects.create_and_join(Organization.objects.create(name="other"), "out@posthog.com", None)
        self.client.force_login(outsider)
        for path in ("config", "@me/config"):
            url = f"/api/projects/{self.team.id}/tasks/{path}/"
            assert self.client.get(url).status_code == 403, path
            assert self.client.post(url, TEAM_TRIPLE).status_code == 403, path

    def test_me_config_resolved_defaults_reflect_precedence(self):
        self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE)

        response = self.client.get(f"/api/projects/{self.team.id}/tasks/@me/config/")
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == {"runtime_adapter": None, "model": None, "reasoning_effort": None}
        assert body["resolved_ai_run_defaults"]["source"] == "team"
        assert body["resolved_ai_run_defaults"]["model"] == "claude-opus-4-8"

        response = self.client.post(f"/api/projects/{self.team.id}/tasks/@me/config/", USER_TRIPLE)
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == USER_TRIPLE
        assert body["resolved_ai_run_defaults"]["source"] == "user"
        assert body["resolved_ai_run_defaults"]["model"] == "gpt-5.5"

        response = self.client.post(
            f"/api/projects/{self.team.id}/tasks/@me/config/",
            {"runtime_adapter": None, "model": None, "reasoning_effort": None},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ai_run_preferences"] == {"runtime_adapter": None, "model": None, "reasoning_effort": None}
        assert body["resolved_ai_run_defaults"]["source"] == "team"

    # The project default decides what every unpinned run on the project launches with, so a member
    # must not be able to move it for everyone — while still reading it, and owning their own.
    def test_a_member_can_read_the_project_default_but_not_change_it(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        assert self.client.get(f"/api/projects/{self.team.id}/tasks/config/").status_code == 200
        assert self.client.post(f"/api/projects/{self.team.id}/tasks/config/", TEAM_TRIPLE).status_code == 403
        assert self.client.post(f"/api/projects/{self.team.id}/tasks/@me/config/", USER_TRIPLE).status_code == 200

    def test_me_config_is_scoped_to_the_requesting_user(self):
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        UserTasksConfig.objects.for_team(self.team.id).update_or_create(
            team_id=self.team.id, user_id=other.id, defaults={"ai_run_preferences": USER_TRIPLE}
        )
        response = self.client.get(f"/api/projects/{self.team.id}/tasks/@me/config/")
        assert response.json()["ai_run_preferences"] == {
            "runtime_adapter": None,
            "model": None,
            "reasoning_effort": None,
        }


class TestConfigEndpointScopes(APIBaseTest):
    # Both endpoints rely on `scope_object = "task"` to derive their scopes rather than
    # declaring them. PostHog Desktop reads them with a personal API key, so a change to
    # the scope object or the action sets would silently lock it out — or hand a
    # read-only key write access.
    def setUp(self) -> None:
        super().setUp()
        # Scopes are what's under test here, so keep the project-admin requirement on the team
        # endpoint from being what fails the write.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _bearer(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="t", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        self.client.logout()
        return f"Bearer {value}"

    @parameterized.expand(["config", "@me/config"])
    def test_read_scope_reads_but_cannot_write(self, path: str):
        bearer = self._bearer(["task:read"])
        url = f"/api/projects/{self.team.id}/tasks/{path}/"
        assert self.client.get(url, HTTP_AUTHORIZATION=bearer).status_code == 200
        assert self.client.post(url, {}, HTTP_AUTHORIZATION=bearer).status_code == 403

    @parameterized.expand(["config", "@me/config"])
    def test_write_scope_writes(self, path: str):
        response = self.client.post(
            f"/api/projects/{self.team.id}/tasks/{path}/",
            {"runtime_adapter": "claude", "model": "claude-opus-4-8", "reasoning_effort": "high"},
            HTTP_AUTHORIZATION=self._bearer(["task:read", "task:write"]),
        )
        assert response.status_code == 200, response.content
