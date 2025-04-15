import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.editor.backend.providers.codestral import CodestralConfig, CodestralProvider


@patch("django.conf.settings.MISTRAL_API_KEY", "test_key")
class TestCodestralProvider(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.model_id = "codestral-latest"

    def test_init_validates_model(self):
        # Valid model
        provider = CodestralProvider(self.model_id)
        self.assertEqual(provider.model_id, self.model_id)

        # Invalid model
        with self.assertRaises(ValueError) as cm:
            CodestralProvider("invalid-model")
        self.assertEqual(str(cm.exception), "Model invalid-model is not supported")

    @patch("mistralai.Mistral")
    def test_stream_fim_response_success(self, mock_mistral):
        provider = CodestralProvider(self.model_id)
        mock_stream = MagicMock()
        mock_mistral.return_value.fim.stream.return_value = mock_stream

        # Mock stream chunks
        mock_stream.__iter__.return_value = [
            MagicMock(data=MagicMock(choices=[MagicMock(delta=MagicMock(content="First chunk"))])),
            MagicMock(data=MagicMock(choices=[MagicMock(delta=MagicMock(content=" Second chunk"))])),
        ]

        prompt = "def test_function"
        suffix = "return result"
        stop = ["```"]

        response_stream = provider.stream_fim_response(prompt, suffix, stop)
        responses = list(response_stream)

        # Verify the responses
        self.assertEqual(json.loads(responses[0].split("data: ")[1]), {"type": "text", "text": "First chunk"})
        self.assertEqual(json.loads(responses[1].split("data: ")[1]), {"type": "text", "text": " Second chunk"})

        # Verify Mistral client was called with correct parameters
        mock_mistral.return_value.fim.stream.assert_called_once_with(
            model=self.model_id,
            prompt=prompt,
            suffix=suffix,
            temperature=CodestralConfig.TEMPERATURE,
            top_p=CodestralConfig.TOP_P,
            stop=stop,
        )

    @patch("mistralai.Mistral")
    def test_stream_fim_response_error_handling(self, mock_mistral):
        provider = CodestralProvider(self.model_id)
        mock_mistral.return_value.fim.stream.side_effect = Exception("API Error")

        prompt = "def test_function"
        suffix = "return result"
        stop = ["```"]

        # The provider should handle the error gracefully and yield nothing
        response_stream = provider.stream_fim_response(prompt, suffix, stop)
        responses = list(response_stream)

        # Since the provider doesn't have explicit error handling yet,
        # we expect the error to propagate
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0], 'data: {"type": "error", "error": "Codestral API error"}\n\n')

    @patch("mistralai.Mistral")
    def test_stream_fim_response_empty_response(self, mock_mistral):
        provider = CodestralProvider(self.model_id)
        mock_stream = MagicMock()
        mock_mistral.return_value.fim.stream.return_value = mock_stream

        # Mock empty stream
        mock_stream.__iter__.return_value = []

        prompt = "def test_function"
        suffix = "return result"
        stop = ["```"]

        response_stream = provider.stream_fim_response(prompt, suffix, stop)
        responses = list(response_stream)

        # Verify no responses were generated
        self.assertEqual(len(responses), 0)

        # Verify Mistral client was still called with correct parameters
        mock_mistral.return_value.fim.stream.assert_called_once_with(
            model=self.model_id,
            prompt=prompt,
            suffix=suffix,
            temperature=CodestralConfig.TEMPERATURE,
            top_p=CodestralConfig.TOP_P,
            stop=stop,
        )
