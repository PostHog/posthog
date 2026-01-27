from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.llm_analytics.backend.models.evaluation_config import EvaluationConfig
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, f"test-provider-keys-{uuid4()}@posthog.com", "testpassword123")
    return team


class TestLLMProviderKeyViewSet(APIBaseTest):
    def test_unauthenticated_user_cannot_access_provider_keys(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_create_provider_key(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
            {"provider": "openai", "name": "My Key", "api_key": "sk-test-key-12345"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(LLMProviderKey.objects.count(), 1)

        key = LLMProviderKey.objects.first()
        assert key is not None
        self.assertEqual(key.name, "My Key")
        self.assertEqual(key.provider, "openai")
        self.assertEqual(key.state, LLMProviderKey.State.OK)
        self.assertEqual(key.team, self.team)
        self.assertEqual(key.created_by, self.user)

        self.assertEqual(response.data["api_key_masked"], "sk-t...2345")
        self.assertNotIn("api_key", response.data)
        mock_validate.assert_called_once_with("openai", "sk-test-key-12345")

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_create_provider_key_with_set_as_active(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
            {"provider": "openai", "name": "My Key", "api_key": "sk-test-key-12345", "set_as_active": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        key = LLMProviderKey.objects.first()
        assert key is not None

        config = EvaluationConfig.objects.get(team=self.team)
        self.assertEqual(config.active_provider_key, key)

    def test_api_key_required_on_create(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
            {"provider": "openai", "name": "My Key"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("api_key", str(response.data))

    def test_invalid_api_key_format_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
            {"provider": "openai", "name": "My Key", "api_key": "invalid-key"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("api_key", str(response.data))

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_validation_failure_rejects_key(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.INVALID, "Invalid API key")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
            {"provider": "openai", "name": "My Key", "api_key": "sk-test-invalid"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid API key", str(response.data))
        self.assertEqual(LLMProviderKey.objects.count(), 0)

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_list_provider_keys(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key 1",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key1"},
            created_by=self.user,
        )
        LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key 2",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key2"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        names = [k["name"] for k in response.data["results"]]
        self.assertIn("Key 1", names)
        self.assertIn("Key 2", names)

    def test_can_retrieve_single_provider_key(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test-key-12345"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "My Key")
        self.assertEqual(response.data["provider"], "openai")
        self.assertEqual(response.data["api_key_masked"], "sk-t...2345")

    def test_can_update_provider_key_name(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Original Name",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test-key"},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/",
            {"name": "Updated Name"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        key.refresh_from_db()
        self.assertEqual(key.name, "Updated Name")

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_update_provider_key_api_key(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-old-key"},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/",
            {"api_key": "sk-new-key-12345"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        key.refresh_from_db()
        self.assertEqual(key.encrypted_config["api_key"], "sk-new-key-12345")
        mock_validate.assert_called_once_with("openai", "sk-new-key-12345")

    def test_can_delete_provider_key(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test-key"},
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(LLMProviderKey.objects.count(), 0)

    def test_cannot_access_other_teams_provider_keys(self):
        other_team = _setup_team()
        other_key = LLMProviderKey.objects.create(
            team=other_team,
            provider="openai",
            name="Other Team Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-other-key"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{other_key.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_cannot_delete_other_teams_provider_keys(self):
        other_team = _setup_team()
        other_key = LLMProviderKey.objects.create(
            team=other_team,
            provider="openai",
            name="Other Team Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-other-key"},
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{other_key.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(LLMProviderKey.objects.filter(id=other_key.id).count(), 1)

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_validate_existing_key(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.UNKNOWN,
            encrypted_config={"api_key": "sk-test-key"},
            created_by=self.user,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/validate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "ok")

        key.refresh_from_db()
        self.assertEqual(key.state, LLMProviderKey.State.OK)

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_validate_updates_state_on_failure(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.INVALID, "Invalid API key")

        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test-key"},
            created_by=self.user,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/validate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "invalid")
        self.assertEqual(response.data["error_message"], "Invalid API key")

        key.refresh_from_db()
        self.assertEqual(key.state, LLMProviderKey.State.INVALID)
        self.assertEqual(key.error_message, "Invalid API key")

    def test_validate_without_api_key_returns_error(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.UNKNOWN,
            encrypted_config={},
            created_by=self.user,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/validate/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_keys_ordered_by_created_at_descending(self):
        key1 = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="First Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key1"},
            created_by=self.user,
        )
        key2 = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Second Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key2"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["id"], str(key2.id))
        self.assertEqual(response.data["results"][1]["id"], str(key1.id))


class TestLLMProviderKeyValidationViewSet(APIBaseTest):
    def test_unauthenticated_user_cannot_validate(self):
        self.client.logout()
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_key_validations/",
            {"api_key": "sk-test"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_can_pre_validate_api_key(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.OK, None)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_key_validations/",
            {"api_key": "sk-test-key"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "ok")
        self.assertIsNone(response.data["error_message"])
        mock_validate.assert_called_once_with("openai", "sk-test-key")

    @patch("products.llm_analytics.backend.api.provider_keys.validate_provider_key")
    def test_pre_validate_returns_error_state(self, mock_validate):
        mock_validate.return_value = (LLMProviderKey.State.INVALID, "Invalid API key")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_key_validations/",
            {"api_key": "sk-invalid-key"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "invalid")
        self.assertEqual(response.data["error_message"], "Invalid API key")

    def test_pre_validate_requires_api_key(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_key_validations/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
