from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from products.ai_observability.backend.llm.types import StreamChunk
from products.tasks.backend.logic.services.title_generator import _fallback_title, generate_task_title


class TestTitleGenerator:
    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = [
            StreamChunk(type="text", data={"text": "Fix login bug"}),
        ]

        result = generate_task_title("Users are experiencing login issues on the authentication page")

        assert result == "Fix login bug"
        mock_client_cls.assert_called_once_with(distinct_id="task-title-generator")

    @patch("products.ai_observability.backend.llm.client.Client")
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

    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_falls_back_on_error(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("API error")

        result = generate_task_title("This is a test description that should be used as fallback")

        assert result == "This is a test description that should be used as fallback"

    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_empty_description(self, mock_client_cls):
        result = generate_task_title("")

        assert result == "Untitled Task"
        mock_client_cls.assert_not_called()

    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_whitespace_only(self, mock_client_cls):
        result = generate_task_title("   \n\t  ")

        assert result == "Untitled Task"
        mock_client_cls.assert_not_called()

    @patch("products.ai_observability.backend.llm.client.Client")
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

    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_ignores_non_text_chunks(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = [
            StreamChunk(type="usage", data={"input_tokens": 10, "output_tokens": 5}),
            StreamChunk(type="text", data={"text": "Valid title"}),
        ]

        result = generate_task_title("Description")

        assert result == "Valid title"

    @patch("products.ai_observability.backend.llm.client.Client")
    def test_generate_task_title_empty_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.stream.return_value = []

        result = generate_task_title("This should fall back to description")

        assert result == "This should fall back to description"


class TestTitleGeneratorAIGateway:
    @pytest.mark.parametrize(
        ("gateway_configured", "flag_on", "expect_gateway"),
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    @patch("posthog.llm.gateway_client.build_ai_gateway_anthropic_client")
    @patch("products.tasks.backend.logic.services.title_generator.feature_enabled_or_false")
    @patch("posthog.llm.gateway_client.resolve_ai_gateway_config")
    @patch("products.ai_observability.backend.llm.client.Client")
    def test_routes_by_gateway_config_and_flag(
        self, mock_client_cls, mock_resolve, mock_flag, mock_build, gateway_configured, flag_on, expect_gateway
    ):
        mock_resolve.return_value = MagicMock() if gateway_configured else None
        mock_flag.return_value = flag_on
        gateway = mock_build.return_value.with_options.return_value.__enter__.return_value
        gateway.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Gateway title")]
        )
        mock_client_cls.return_value.stream.return_value = [StreamChunk(type="text", data={"text": "Direct title"})]

        result = generate_task_title("Users are experiencing login issues")

        assert result == ("Gateway title" if expect_gateway else "Direct title")
        assert mock_build.called is expect_gateway
        assert mock_client_cls.called is not expect_gateway

    @pytest.mark.parametrize(
        ("distinct_id", "expected_flag_distinct_id"),
        [
            ("user-distinct-id", "user-distinct-id"),
            ("", "random-id"),
            (None, "random-id"),
        ],
    )
    @patch("products.tasks.backend.logic.services.title_generator.uuid4", return_value="random-id")
    @patch("products.tasks.backend.logic.services.title_generator.feature_enabled_or_false", return_value=False)
    @patch("posthog.llm.gateway_client.resolve_ai_gateway_config", return_value=MagicMock())
    @patch("products.ai_observability.backend.llm.client.Client")
    def test_flag_buckets_by_caller_distinct_id(
        self, mock_client_cls, _mock_resolve, mock_flag, _mock_uuid4, distinct_id, expected_flag_distinct_id
    ):
        mock_client_cls.return_value.stream.return_value = [StreamChunk(type="text", data={"text": "Direct title"})]

        generate_task_title("Users are experiencing login issues", distinct_id=distinct_id)

        assert mock_flag.call_args.args == ("tasks-title-ai-gateway", expected_flag_distinct_id)
        mock_client_cls.assert_called_once_with(distinct_id="task-title-generator")

    @patch("posthog.llm.gateway_client.build_ai_gateway_anthropic_client")
    @patch("products.tasks.backend.logic.services.title_generator.feature_enabled_or_false", return_value=True)
    @patch("posthog.llm.gateway_client.resolve_ai_gateway_config", return_value=MagicMock())
    def test_gateway_request_keeps_model_and_attribution(self, _mock_resolve, _mock_flag, mock_build):
        with_options = mock_build.return_value.with_options
        create = with_options.return_value.__enter__.return_value.messages.create
        create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", text="ignored"),
                SimpleNamespace(type="text", text="Fix "),
                SimpleNamespace(type="text", text="login bug"),
            ]
        )

        result = generate_task_title("Users are experiencing login issues")

        assert result == "Fix login bug"
        mock_build.assert_called_once_with(ai_product="posthog_code", distinct_id="task-title-generator")
        with_options.assert_called_once_with(timeout=30.0, max_retries=1)
        with_options.return_value.__exit__.assert_called_once()
        kwargs = create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5-20251001"
        assert kwargs["max_tokens"] == 50
        assert kwargs["temperature"] == 0.2
        assert kwargs["extra_headers"] == {"X-PostHog-Billable": "false", "X-PostHog-Privacy-Mode": "true"}

    @patch("posthog.llm.gateway_client.build_ai_gateway_anthropic_client")
    @patch("products.tasks.backend.logic.services.title_generator.feature_enabled_or_false", return_value=True)
    @patch("posthog.llm.gateway_client.resolve_ai_gateway_config", return_value=MagicMock())
    def test_gateway_error_falls_back_to_description(self, _mock_resolve, _mock_flag, mock_build):
        with_options = mock_build.return_value.with_options
        with_options.return_value.__enter__.return_value.messages.create.side_effect = Exception("gateway down")

        result = generate_task_title("This is a test description that should be used as fallback")

        assert result == "This is a test description that should be used as fallback"
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
