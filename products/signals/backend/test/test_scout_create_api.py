from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalScoutConfig
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile


class TestSignalScoutCreateAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/"

    def _payload(self) -> dict:
        return {
            "name": "signals-scout-checkout-failures",
            "description": "Investigates meaningful checkout_failed spikes.",
            "body": "# Checkout failure scout\n\nInvestigate the `checkout_failed` signal and file actionable reports.",
            "files": [
                {
                    "path": "references/checkout.md",
                    "content": "Treat payment_declined as expected unless its reach changes materially.",
                    "content_type": "text/markdown",
                }
            ],
        }

    def test_create_builds_runnable_scout_with_slack_destination(self) -> None:
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        payload = {
            **self._payload(),
            "config": {
                "enabled": False,
                "emit": False,
                "run_cron_schedule": "30 9 * * 1-5",
                "output_destinations": {
                    "slack": {
                        "integration_id": integration.id,
                        "channel": "CSCOUTS|#scout-findings",
                    }
                },
            },
        }

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created"] is True
        skill = LLMSkill.objects.get(team=self.team, name=payload["name"], is_latest=True)
        assert skill.body == payload["body"]
        assert skill.allowed_tools == ["edit_report", "emit_report"]
        assert skill.category == "scout"
        assert list(LLMSkillFile.objects.filter(skill=skill).values_list("path", flat=True)) == [
            "references/checkout.md"
        ]
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.enabled is False
        assert config.emit is False
        assert config.run_cron_schedule == "30 9 * * 1-5"
        assert config.output_destinations == payload["config"]["output_destinations"]
        assert response.json()["config"]["description"] == payload["description"]

    def test_matching_definition_retry_is_idempotent_and_applies_config(self) -> None:
        payload = self._payload()

        first = self.client.post(self._url(), data=payload, format="json")
        second = self.client.post(
            self._url(),
            data={**payload, "config": {"enabled": False, "emit": False}},
            format="json",
        )

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["created"] is False
        assert LLMSkill.objects.filter(team=self.team, name=payload["name"], deleted=False).count() == 1
        assert SignalScoutConfig.all_teams.filter(team=self.team, skill_name=payload["name"]).count() == 1
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.enabled is False
        assert config.emit is False

    def test_conflicting_definition_returns_409_without_changing_scout(self) -> None:
        payload = self._payload()
        self.client.post(self._url(), data=payload, format="json")

        response = self.client.post(
            self._url(),
            data={**payload, "body": "# Different instructions", "config": {"enabled": False}},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        skill = LLMSkill.objects.get(team=self.team, name=payload["name"], is_latest=True)
        assert skill.body == payload["body"]
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.enabled is True

    def test_invalid_slack_destination_does_not_create_skill(self) -> None:
        other_organization = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_organization, name="Other")
        integration = Integration.objects.create(team=other_team, kind=Integration.IntegrationKind.SLACK)
        payload = {
            **self._payload(),
            "config": {
                "output_destinations": {
                    "slack": {
                        "integration_id": integration.id,
                        "channel": "CSCOUTS|#scout-findings",
                    }
                }
            },
        }

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not LLMSkill.objects.filter(team=self.team, name=payload["name"], deleted=False).exists()

    def test_config_failure_rolls_back_skill_creation(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-existing",
            description="Existing scout",
            body="# Existing",
        )
        SignalScoutConfig.all_teams.create(
            team=self.team,
            skill_name="signals-scout-existing",
            enabled=True,
        )
        payload = self._payload()

        with patch("products.signals.backend.scout_harness.views.MAX_ENABLED_SCOUTS_PER_TEAM", 1):
            response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not LLMSkill.objects.filter(team=self.team, name=payload["name"], deleted=False).exists()
        assert not SignalScoutConfig.all_teams.filter(team=self.team, skill_name=payload["name"]).exists()

    @parameterized.expand(
        [
            ("both_scopes", ["llm_skill:write", "signal_scout:write"], status.HTTP_201_CREATED),
            ("missing_scout_scope", ["llm_skill:write"], status.HTTP_403_FORBIDDEN),
            ("missing_skill_scope", ["signal_scout:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_scoped_key_requires_skill_and_scout_write(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        payload = self._payload()

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == expected_status
        assert LLMSkill.objects.filter(team=self.team, name=payload["name"], deleted=False).exists() is (
            expected_status == status.HTTP_201_CREATED
        )

    def test_child_scoped_api_key_cannot_create_parent_scout(self) -> None:
        environment = Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="Child environment",
        )
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Child-scoped key",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["llm_skill:write", "signal_scout:write"],
            scoped_teams=[environment.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        payload = self._payload()

        response = self.client.post(
            f"/api/projects/{environment.id}/signals/scout/",
            data=payload,
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not LLMSkill.objects.filter(team=self.team, name=payload["name"], deleted=False).exists()

    def test_environment_create_requires_skill_editor_access_on_parent(self) -> None:
        environment = Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="Child environment",
        )
        with patch("products.signals.backend.scout_harness.views.UserAccessControl") as user_access_control:
            user_access_control.return_value.check_access_level_for_resource.return_value = False
            response = self.client.post(
                f"/api/projects/{environment.id}/signals/scout/",
                data=self._payload(),
                format="json",
            )

        user_access_control.assert_called_once_with(user=self.user, team=self.team)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not LLMSkill.objects.filter(team=self.team, name=self._payload()["name"], deleted=False).exists()
