from types import SimpleNamespace

import pytest
from unittest.mock import patch

from products.tasks.backend.logic.services.title_generator import _fallback_title, generate_task_title

BUILDER = "posthog.llm.gateway_client.build_ai_gateway_anthropic_client"


def _blocks(*blocks: tuple[str, str]) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type=kind, text=text) for kind, text in blocks])


class TestTitleGenerator:
    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (_blocks(("text", "Fix login bug")), "Fix login bug"),
            (_blocks(("text", "Add "), ("text", "dashboard "), ("text", "metrics")), "Add dashboard metrics"),
            (_blocks(("thinking", "ignored"), ("text", "Valid title")), "Valid title"),
            (_blocks(("text", "A" * 300)), "A" * 60),
            (_blocks(), "Users are experiencing login issues"),
        ],
    )
    @patch(BUILDER)
    def test_generate_task_title_from_gateway_response(self, mock_build, response, expected):
        create = mock_build.return_value.with_options.return_value.__enter__.return_value.messages.create
        create.return_value = response

        assert generate_task_title("Users are experiencing login issues") == expected

    @pytest.mark.parametrize("description", ["", "   \n\t  "])
    @patch(BUILDER)
    def test_generate_task_title_blank_description(self, mock_build, description):
        assert generate_task_title(description) == "Untitled Task"
        mock_build.assert_not_called()

    @patch(BUILDER)
    def test_gateway_request_keeps_model_and_attribution(self, mock_build):
        with_options = mock_build.return_value.with_options
        create = with_options.return_value.__enter__.return_value.messages.create
        create.return_value = _blocks(("text", "Fix login bug"))

        generate_task_title("Users are experiencing login issues")

        mock_build.assert_called_once_with(ai_product="tasks_title", distinct_id="task-title-generator")
        with_options.assert_called_once_with(timeout=30.0, max_retries=1)
        kwargs = create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5-20251001"
        assert kwargs["max_tokens"] == 50
        assert kwargs["temperature"] == 0.2
        assert kwargs["extra_headers"] == {"X-PostHog-Billable": "false"}

    @pytest.mark.parametrize("failure", ["build", "create"])
    @patch(BUILDER)
    def test_gateway_error_falls_back_to_description(self, mock_build, failure):
        with_options = mock_build.return_value.with_options
        if failure == "build":
            mock_build.side_effect = ValueError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
        else:
            with_options.return_value.__enter__.return_value.messages.create.side_effect = Exception("gateway down")

        result = generate_task_title("This is a test description that should be used as fallback")

        assert result == "This is a test description that should be used as fallback"
        if failure == "create":
            with_options.return_value.__exit__.assert_called_once()


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
