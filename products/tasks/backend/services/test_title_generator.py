import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.services.title_generator import _fallback_title, generate_task_title


class TestTitleGenerator:
    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_success(self, mock_anthropic_provider):
        mock_provider_instance = MagicMock()
        mock_anthropic_provider.return_value = mock_provider_instance

        mock_provider_instance.stream_response.return_value = [
            'data: {"type": "text", "text": "Fix login bug"}',
        ]

        result = generate_task_title("Users are experiencing login issues on the authentication page")

        assert result == "Fix login bug"
        mock_anthropic_provider.assert_called_once_with(model_id="claude-haiku-4-5-20251001")

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_multipart_response(self, mock_anthropic_provider):
        mock_provider_instance = MagicMock()
        mock_anthropic_provider.return_value = mock_provider_instance

        mock_provider_instance.stream_response.return_value = [
            'data: {"type": "text", "text": "Add "}',
            'data: {"type": "text", "text": "dashboard "}',
            'data: {"type": "text", "text": "metrics"}',
        ]

        result = generate_task_title("Need to add metrics to the dashboard")

        assert result == "Add dashboard metrics"

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_falls_back_on_error(self, mock_anthropic_provider):
        mock_anthropic_provider.side_effect = Exception("API error")

        result = generate_task_title("This is a test description that should be used as fallback")

        assert result == "This is a test description that should be used as fallback"

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_empty_description(self, mock_anthropic_provider):
        result = generate_task_title("")

        assert result == "Untitled Task"
        mock_anthropic_provider.assert_not_called()

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_whitespace_only(self, mock_anthropic_provider):
        result = generate_task_title("   \n\t  ")

        assert result == "Untitled Task"
        mock_anthropic_provider.assert_not_called()

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_truncates_long_response(self, mock_anthropic_provider):
        mock_provider_instance = MagicMock()
        mock_anthropic_provider.return_value = mock_provider_instance

        long_title = "A" * 300
        mock_provider_instance.stream_response.return_value = [
            f'data: {{"type": "text", "text": "{long_title}"}}',
        ]

        result = generate_task_title("Some description")

        assert len(result) == 60
        assert result == "A" * 60

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_handles_json_errors(self, mock_anthropic_provider):
        mock_provider_instance = MagicMock()
        mock_anthropic_provider.return_value = mock_provider_instance

        mock_provider_instance.stream_response.return_value = [
            "data: invalid json",
            'data: {"type": "text", "text": "Valid title"}',
        ]

        result = generate_task_title("Description")

        assert result == "Valid title"

    @patch("products.tasks.backend.services.title_generator.AnthropicProvider")
    def test_generate_task_title_empty_response(self, mock_anthropic_provider):
        mock_provider_instance = MagicMock()
        mock_anthropic_provider.return_value = mock_provider_instance

        mock_provider_instance.stream_response.return_value = []

        result = generate_task_title("This should fall back to description")

        assert result == "This should fall back to description"


class TestFallbackTitle:
    @pytest.mark.parametrize(
        ("description", "expected"),
        [
            ("Short description", "Short description"),
            ("A" * 50, "A" * 50),
            ("A" * 60, "A" * 60),
            ("A" * 61, "A" * 57 + "..."),
            ("First line\nSecond line", "First line"),
            (
                "This is a very long first line that exceeds sixty characters total",
                "This is a very long first line that exceeds sixty charact...",
            ),
            ("", "Untitled Task"),
            ("   ", "Untitled Task"),
        ],
    )
    def test_fallback_title_various_inputs(self, description, expected):
        assert _fallback_title(description) == expected
