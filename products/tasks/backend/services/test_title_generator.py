import pytest
from unittest.mock import MagicMock, patch

from products.llm_analytics.backend.llm.types import StreamChunk
from products.tasks.backend.services.title_generator import _fallback_title, generate_task_title


class TestTitleGenerator:
    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = [
            StreamChunk(type="text", data={"text": "Fix login bug"}),
        ]

        result = generate_task_title("Users are experiencing login issues on the authentication page")

        assert result == "Fix login bug"
        mock_client_cls.assert_called_once_with(distinct_id="task-title-generator")

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_multipart_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = [
            StreamChunk(type="text", data={"text": "Add "}),
            StreamChunk(type="text", data={"text": "dashboard "}),
            StreamChunk(type="text", data={"text": "metrics"}),
        ]

        result = generate_task_title("Need to add metrics to the dashboard")

        assert result == "Add dashboard metrics"

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_falls_back_on_error(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("API error")

        result = generate_task_title("This is a test description that should be used as fallback")

        assert result == "This is a test description that should be used as fallback"

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_empty_description(self, mock_client_cls):
        result = generate_task_title("")

        assert result == "Untitled Task"
        mock_client_cls.assert_not_called()

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_whitespace_only(self, mock_client_cls):
        result = generate_task_title("   \n\t  ")

        assert result == "Untitled Task"
        mock_client_cls.assert_not_called()

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_truncates_long_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        long_title = "A" * 300
        mock_client.stream.return_value = [
            StreamChunk(type="text", data={"text": long_title}),
        ]

        result = generate_task_title("Some description")

        assert len(result) == 60
        assert result == "A" * 60

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_ignores_non_text_chunks(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = [
            StreamChunk(type="usage", data={"input_tokens": 10, "output_tokens": 5}),
            StreamChunk(type="text", data={"text": "Valid title"}),
        ]

        result = generate_task_title("Description")

        assert result == "Valid title"

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_empty_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = []

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
