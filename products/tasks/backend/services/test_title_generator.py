import pytest
from unittest.mock import MagicMock, patch

from products.llm_analytics.backend.llm.types import StreamChunk
from products.tasks.backend.services.title_generator import (
    _fallback_title,
    _normalize_mention_tags,
    generate_task_title,
)


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

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_normalizes_mention_tags_before_llm(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.stream.return_value = [
            StreamChunk(type="text", data={"text": "Audit agentic_tests product"}),
        ]

        generate_task_title('Does the <folder path="products/agentic_tests" /> product still work after the rewrite?')

        request = mock_client.stream.call_args.args[0]
        user_content = request.messages[0]["content"]
        assert '<folder path="products/agentic_tests" />' not in user_content
        assert "products/agentic_tests" in user_content

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_strips_mention_tags_from_llm_output(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.stream.return_value = [
            StreamChunk(
                type="text",
                data={"text": 'Audit <folder path="products/agentic_tests" /> product'},
            ),
        ]

        result = generate_task_title("Audit the agentic tests product")

        assert result == "Audit products/agentic_tests product"

    @patch("products.tasks.backend.services.title_generator.Client")
    def test_generate_task_title_falls_back_after_mention_only_description(self, mock_client_cls):
        result = generate_task_title('<folder path="" />')

        assert result == "Untitled Task"
        mock_client_cls.assert_not_called()


class TestNormalizeMentionTags:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (
                'Does the <folder path="products/agentic_tests" /> product work?',
                "Does the products/agentic_tests product work?",
            ),
            (
                'Check <file path="src/foo.py" /> and <folder path="src/utils" />',
                "Check src/foo.py and src/utils",
            ),
            ("No tags here at all", "No tags here at all"),
            ('<folder path="products/foo" />', "products/foo"),
            ("Drop unknown <something />", "Drop unknown "),
            ('<symbol path="Foo.bar" name="bar" />', "Foo.bar"),
            ("", ""),
        ],
    )
    def test_normalize_mention_tags(self, text, expected):
        assert _normalize_mention_tags(text) == expected


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
