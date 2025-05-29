from unittest.mock import patch

from rest_framework import status

from posthog.test.base import APIBaseTest
from products.editor.backend.api import SUPPORTED_MODELS_WITH_THINKING, LLMProxyViewSet, PersonalAPIKeyAuthentication


@patch("django.conf.settings.MISTRAL_API_KEY", "test_key")
@patch("django.conf.settings.INKEEP_API_KEY", "test_key")
@patch("django.conf.settings.ANTHROPIC_API_KEY", "test_key")
class TestLLMProxyViewSet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        # Mock the authenticate method
        self.patcher = patch.object(PersonalAPIKeyAuthentication, "authenticate")
        self.mock_auth = self.patcher.start()
        self.mock_auth.return_value = (self.user, None)

        # Mock the validate_feature_flag method
        self.feature_patcher = patch.object(LLMProxyViewSet, "validate_feature_flag", return_value=True)
        self.mock_feature = self.feature_patcher.start()

        # Force authenticate the test user
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        super().tearDown()
        self.patcher.stop()
        self.feature_patcher.stop()

    def test_completion_invalid_model(self):
        response = self.client.post(
            "/api/llm_proxy/completion/",
            {"system": "test system", "messages": [{"role": "user", "content": "test"}], "model": "invalid-model"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Unsupported model"})

    @patch("products.editor.backend.providers.anthropic.AnthropicProvider.stream_response")
    def test_completion_success(self, mock_stream):
        mock_stream.return_value = iter(["test response"])
        response = self.client.post(
            "/api/llm_proxy/completion/",
            {
                "system": "test system",
                "messages": [{"role": "user", "content": "test"}],
                "model": "claude-3-5-sonnet-20241022",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        mock_stream.assert_called_once_with(
            system="test system", messages=[{"role": "user", "content": "test"}], thinking=False
        )

    @patch("products.editor.backend.providers.anthropic.AnthropicProvider.stream_response")
    def test_completion_with_thinking(self, mock_stream):
        mock_stream.return_value = iter(["test response"])
        response = self.client.post(
            "/api/llm_proxy/completion/",
            {
                "system": "test system",
                "messages": [{"role": "user", "content": "test"}],
                "model": "claude-3-7-sonnet-20250219",
                "thinking": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_stream.assert_called_once_with(
            system="test system", messages=[{"role": "user", "content": "test"}], thinking=True
        )

    def test_completion_thinking_with_unsupported_model(self):
        # Create a model that doesn't support thinking
        unsupported_model = "claude-3-haiku-20240307"
        self.assertNotIn(unsupported_model, SUPPORTED_MODELS_WITH_THINKING)

        response = self.client.post(
            "/api/llm_proxy/completion/",
            {
                "system": "test system",
                "messages": [{"role": "user", "content": "test"}],
                "model": unsupported_model,
                "thinking": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Thinking is not supported for this model"})

    @patch("products.editor.backend.providers.codestral.CodestralProvider.stream_fim_response")
    def test_fim_completion_success(self, mock_stream):
        mock_stream.return_value = iter(["test response"])
        response = self.client.post(
            "/api/llm_proxy/fim/completion/",
            {"prompt": "test prompt", "suffix": "test suffix", "model": "codestral-latest", "stop": ["stop1", "stop2"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        mock_stream.assert_called_once_with(prompt="test prompt", suffix="test suffix", stop=["stop1", "stop2"])

    def test_fim_completion_invalid_model(self):
        response = self.client.post(
            "/api/llm_proxy/fim/completion/",
            {"prompt": "test prompt", "suffix": "test suffix", "model": "invalid-model", "stop": ["stop1", "stop2"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Unsupported model"})

    @patch("products.editor.backend.providers.inkeep.InkeepProvider.stream_response")
    def test_inkeep_completion_success(self, mock_stream):
        mock_stream.return_value = iter(["test response"])
        response = self.client.post(
            "/api/llm_proxy/completion/",
            {"system": "test system", "messages": [{"role": "user", "content": "test"}], "model": "inkeep-qa-expert"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        mock_stream.assert_called_once_with(
            system="test system", messages=[{"role": "user", "content": "test"}], thinking=False
        )

    def test_completion_missing_required_fields(self):
        response = self.client.post(
            "/api/llm_proxy/completion/",
            {"messages": [{"role": "user", "content": "test"}], "model": "claude-3-5-sonnet-20241022"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("system", str(response.json()))

    def test_fim_completion_missing_required_fields(self):
        response = self.client.post(
            "/api/llm_proxy/fim/completion/",
            {"suffix": "test suffix", "model": "codestral-latest", "stop": ["stop1", "stop2"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prompt", str(response.json()))
