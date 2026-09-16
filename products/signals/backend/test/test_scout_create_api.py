from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.serializers import SignalScoutCreateSerializer
from products.skills.backend.api.skill_serializers import SPEC_DESCRIPTION_MAX_LENGTH
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
        assert config.output_destinations == {
            "slack": {**payload["config"]["output_destinations"]["slack"], "thread_reports": True}
        }
        assert response.json()["config"]["description"] == payload["description"]

    def test_create_stores_normalized_tags_from_the_config_block(self) -> None:
        # Tagging at authoring time is the point — a scout the agent creates should land in the
        # right group without a follow-up PATCH.
        payload = {**self._payload(), "config": {"tags": ["Revenue", "on call", "revenue"]}}

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["config"]["tags"] == ["on-call", "revenue"]
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.tags == ["on-call", "revenue"]

    @parameterized.expand([("prefixed", "signals-scout-checkout-failures"), ("bare", "my-churn-watch")])
    def test_matching_definition_retry_is_idempotent_and_applies_config(self, _name: str, skill_name: str) -> None:
        payload = {**self._payload(), "name": skill_name}

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

    def test_matching_definition_retry_preserves_omitted_slack_thread_opt_out(self) -> None:
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        payload = self._payload()
        first = self.client.post(
            self._url(),
            data={
                **payload,
                "config": {
                    "output_destinations": {
                        "slack": {
                            "integration_id": integration.id,
                            "channel": "COLD|#old",
                            "thread_reports": False,
                        }
                    }
                },
            },
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        response = self.client.post(
            self._url(),
            data={
                **payload,
                "config": {
                    "output_destinations": {"slack": {"integration_id": integration.id, "channel": "CNEW|#new"}}
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.output_destinations["slack"]["thread_reports"] is False

    @parameterized.expand(
        [
            # The create form sends an empty list by default, so a repeat of someone else's scout
            # would silently revoke its grant if an empty list skipped the gate.
            ("empty_list_revokes", [], status.HTTP_403_FORBIDDEN),
            ("resent_grant_is_not_a_change", ["dashboard:write"], status.HTTP_200_OK),
        ]
    )
    def test_repeating_a_definition_may_not_change_the_grant_without_the_authors_claim(
        self, _name: str, resent_scopes: list[str], expected: int
    ) -> None:
        payload = self._payload()
        first = self.client.post(
            self._url(), data={**payload, "config": {"write_scopes": ["dashboard:write"]}}, format="json"
        )
        assert first.status_code == status.HTTP_201_CREATED, first.json()
        self.client.force_login(User.objects.create_and_join(self.organization, "other@example.com", None))

        response = self.client.post(
            self._url(), data={**payload, "config": {"write_scopes": resent_scopes}}, format="json"
        )

        assert response.status_code == expected, response.json()
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name=payload["name"])
        assert config.write_scopes == ["dashboard:write"]

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

    def test_create_accepts_a_name_without_the_scout_prefix(self) -> None:
        # The config row created alongside the skill is what makes it a scout, so the name only
        # has to pass the ordinary skill-name rules.
        payload = {**self._payload(), "name": "my-churn-watch"}

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert SignalScoutConfig.all_teams.filter(team=self.team, skill_name="my-churn-watch").exists()
        # `category` is derived from the name prefix on skill creation, so a bare-named scout only
        # reaches the skills UI's Scouts tab if the endpoint stamps it.
        skill = LLMSkill.objects.get(team=self.team, name="my-churn-watch", deleted=False)
        assert skill.category == "scout"

    @parameterized.expand([("scratchpad",), ("findings",), ("runs",)])
    def test_create_rejects_a_name_the_inbox_reserves(self, name: str) -> None:
        # `/inbox/scouts/<name>` reads these as sub-pages, so a scout under one could never be
        # opened. They stay valid as ordinary skill names.
        response = self.client.post(self._url(), data={**self._payload(), "name": name}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not LLMSkill.objects.filter(team=self.team, name=name, deleted=False).exists()

    def test_create_rejects_a_name_another_product_owns(self) -> None:
        # `review-hog-` names carry that product's category, which its own sync re-stamps. A scout
        # under one would sit on the Code review tab and flip between tabs on every sync.
        response = self.client.post(self._url(), data={**self._payload(), "name": "review-hog-security"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not LLMSkill.objects.filter(team=self.team, name="review-hog-security", deleted=False).exists()

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


class TestSignalScoutCreateDisplayNameAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/"

    def _payload(self, **overrides: object) -> dict:
        return {
            "description": "Investigates meaningful checkout_failed spikes.",
            "body": "# Checkout failure scout\n\nInvestigate the `checkout_failed` signal.",
            **overrides,
        }

    def _create(self, **overrides: object):
        return self.client.post(self._url(), data=self._payload(**overrides), format="json")

    def test_display_name_is_stored_verbatim_under_a_generated_slug(self) -> None:
        response = self._create(display_name="  My APM scout  ")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["config"]["display_name"] == "My APM scout"
        assert body["skill"]["name"] == "my-apm-scout"
        config = SignalScoutConfig.all_teams.get(team=self.team, skill_name="my-apm-scout")
        assert config.display_name == "My APM scout"

    def test_a_second_scout_of_the_same_name_gets_its_own_identity(self) -> None:
        # Duplicate labels are allowed, so the slug is what has to stay unique. The first scout's
        # skill, config, and body must be untouched — attaching to it would silently hand the
        # second author someone else's scout.
        first = self._create(display_name="Checkout failures")
        second = self._create(display_name="Checkout failures", body="# A different scout\n\nWatch refunds.")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert first.json()["skill"]["name"] == "checkout-failures"
        assert second.json()["skill"]["name"] == "checkout-failures-2"
        assert second.json()["config"]["display_name"] == "Checkout failures"
        assert (
            LLMSkill.objects.get(team=self.team, name="checkout-failures", is_latest=True).body
            == (self._payload()["body"])
        )

    def test_repeating_a_whole_definition_still_mints_a_second_scout(self) -> None:
        # A generated identity cannot be recovered from the display name, so this route is not the
        # idempotent one an explicit `name` gets: the repeat allocates past the slug it already
        # took. Worth pinning, because the sibling create endpoint answers 200 for the same body
        # and a reader is entitled to expect the same here.
        first = self._create(display_name="Checkout failures")
        second = self._create(display_name="Checkout failures")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert [first.json()["skill"]["name"], second.json()["skill"]["name"]] == [
            "checkout-failures",
            "checkout-failures-2",
        ]
        assert SignalScoutConfig.all_teams.filter(team=self.team, display_name="Checkout failures").count() == 2

    def test_a_name_that_slugifies_to_nothing_still_creates_a_scout(self) -> None:
        # A name in a script that does not transliterate leaves no slug to derive. Falling back to
        # a generated one keeps the scout creatable under the name its author wrote.
        response = self._create(display_name="監視")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["config"]["display_name"] == "監視"
        assert response.json()["skill"]["name"].startswith("scout-")

    def test_an_explicit_name_is_kept_alongside_the_display_name(self) -> None:
        # The identifier a caller picks is the one it gets, so a client that stored the name
        # before display names existed keeps working, display name or not.
        response = self._create(name="signals-scout-checkout-failures", display_name="Checkout failures")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["skill"]["name"] == "signals-scout-checkout-failures"
        assert response.json()["config"]["display_name"] == "Checkout failures"


class TestSignalScoutCreateSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("neither name is given", {}, False),
            ("the display name is blank", {"display_name": "   "}, False),
            ("a display name alone", {"display_name": "My APM scout"}, True),
            ("a skill name alone", {"name": "signals-scout-checkout-failures"}, True),
        ]
    )
    def test_a_scout_must_be_called_something(self, _name: str, names: dict, expected_valid: bool) -> None:
        serializer = SignalScoutCreateSerializer(data={"description": "Watches checkout.", "body": "# Body", **names})

        assert serializer.is_valid() is expected_valid
        if not expected_valid:
            assert "display_name" in serializer.errors

    @parameterized.expand(
        [
            ("over the spec cap is rejected", SPEC_DESCRIPTION_MAX_LENGTH + 1, False),
            ("at the spec cap is accepted", SPEC_DESCRIPTION_MAX_LENGTH, True),
        ]
    )
    def test_description_capped_at_spec_limit(self, _name: str, length: int, expected_valid: bool) -> None:
        # A scout is an LLMSkill, so its description must clear the same spec cap the store enforces,
        # or the scout later fails export and community publish.
        serializer = SignalScoutCreateSerializer(
            data={
                "name": "signals-scout-checkout-failures",
                "description": "x" * length,
                "body": "# Body",
            }
        )
        assert serializer.is_valid() is expected_valid
        if not expected_valid:
            assert serializer.errors["description"][0].code == "max_length"
