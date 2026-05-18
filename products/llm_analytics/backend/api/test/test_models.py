from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.llm_analytics.backend.api.models import LLMModelInfoSerializer, LLMModelsListResponseSerializer


class TestLLMModelInfoSerializer(APIBaseTest):
    def test_serializes_expected_shape(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini", "posthog_available": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"id": "gpt-4o-mini", "posthog_available": True})

    def test_rejects_missing_fields(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("posthog_available", serializer.errors)


class TestLLMModelsListResponseSerializer(APIBaseTest):
    def test_serializes_nested_models(self):
        serializer = LLMModelsListResponseSerializer(
            data={
                "models": [
                    {"id": "gpt-4o-mini", "posthog_available": True},
                    {"id": "gpt-4o", "posthog_available": False},
                ]
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data["models"]), 2)
        self.assertEqual(serializer.validated_data["models"][0]["id"], "gpt-4o-mini")


class TestLLMModelsViewSet(APIBaseTest):
    def test_requires_provider_query_param(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider", response.data["detail"].lower())

    def test_rejects_invalid_provider(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/models/?provider=not-a-real-provider"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invalid provider", response.data["detail"].lower())

    @patch("products.llm_analytics.backend.api.models.LLMModelConfiguration")
    def test_returns_models_for_valid_provider(self, mock_config_cls):
        mock_config_cls.return_value.get_available_models.return_value = ["gpt-4o-mini", "gpt-4o"]

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("models", response.data)
        returned_ids = [m["id"] for m in response.data["models"]]
        self.assertEqual(returned_ids, ["gpt-4o-mini", "gpt-4o"])
        for entry in response.data["models"]:
            self.assertIn("posthog_available", entry)

    def test_unauthenticated_user_cannot_list_models(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
