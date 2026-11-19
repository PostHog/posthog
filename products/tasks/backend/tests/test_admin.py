from posthog.test.base import BaseTest

from django.contrib import admin
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin import register_all_admin
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team

from products.tasks.backend.models import TeamTasksConfig, UserTasksConfig

register_all_admin()


class TestTasksConfigAdminForms(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        request = RequestFactory().get("/")
        request.user = self.user
        self.team_form_class = admin.site._registry[TeamTasksConfig].get_form(request)
        self.user_form_class = admin.site._registry[UserTasksConfig].get_form(request)

    @parameterized.expand(
        [
            ("model_without_adapter", {"model": "claude-opus-4-8"}),
            ("unknown_key", {"runtime_adapter": "claude", "model": "claude-opus-4-8", "profile": "max"}),
            ("non_string_value", {"runtime_adapter": "claude", "model": 7}),
            ("pi_with_an_adapter", {"runtime": "pi", "runtime_adapter": "claude", "model": "gpt-5.6-terra"}),
            ("unknown_runtime", {"runtime": "acp2", "runtime_adapter": "claude", "model": "claude-opus-4-8"}),
        ]
    )
    def test_rejects_invalid_preference_payloads(self, _name: str, payload: dict) -> None:
        form = self.team_form_class(data={"team": self.team.pk, "ai_run_preferences": payload})
        assert not form.is_valid()
        assert "ai_run_preferences" in form.errors

    def test_accepts_a_valid_payload_on_both_admin_forms(self) -> None:
        # Pass an existing row so that the admin flow is a change form.
        team_form = self.team_form_class(
            instance=get_or_create_team_extension(self.team, TeamTasksConfig),
            data={
                "team": self.team.pk,
                "ai_run_preferences": {"runtime_adapter": "claude", "model": "claude-opus-4-8"},
            },
        )
        assert team_form.is_valid(), team_form.errors
        user_form = self.user_form_class(data={"team": self.team.pk, "user": self.user.pk, "ai_run_preferences": {}})
        assert user_form.is_valid(), user_form.errors

    def test_accepts_a_pi_payload(self) -> None:
        form = self.user_form_class(
            data={
                "team": self.team.pk,
                "user": self.user.pk,
                "ai_run_preferences": {"runtime": "pi", "model": "gpt-5.6-terra", "reasoning_effort": "off"},
            }
        )
        assert form.is_valid(), form.errors

    def test_rejects_a_row_keyed_on_an_environment_team(self) -> None:
        env_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="env"
        )
        form = self.team_form_class(data={"team": env_team.pk, "ai_run_preferences": None})
        assert not form.is_valid()
        assert "project root team" in str(form.errors["team"])
