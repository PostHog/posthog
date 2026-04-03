import pytest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from products.llm_analytics.backend.llm.errors import StructuredOutputParseError
from products.llm_analytics.backend.llm.providers.anthropic import AnthropicAdapter
from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest


class BooleanEvalResult(BaseModel):
    result: bool
    reason: str


class ScoreEvalResult(BaseModel):
    score: float
    explanation: str
    tags: list[str]


class ModelWithDefault(BaseModel):
    name: str
    verdict: bool | None = None


class TestBuildOutputSchema:
    def test_schema_contains_properties(self):
        schema = AnthropicAdapter._build_output_schema(BooleanEvalResult)

        assert schema["type"] == "object"
        assert "result" in schema["properties"]
        assert "reason" in schema["properties"]

    def test_schema_sets_additional_properties_false(self):
        schema = AnthropicAdapter._build_output_schema(BooleanEvalResult)

        assert schema["additionalProperties"] is False

    def test_schema_preserves_field_types(self):
        schema = AnthropicAdapter._build_output_schema(ScoreEvalResult)

        assert schema["properties"]["score"]["type"] == "number"
        assert schema["properties"]["explanation"]["type"] == "string"
        assert schema["properties"]["tags"]["type"] == "array"

    def test_schema_strips_default_keyword(self):
        schema = AnthropicAdapter._build_output_schema(ModelWithDefault)

        verdict_schema = schema["properties"]["verdict"]
        assert "default" not in verdict_schema


class TestStructuredOutputComplete:
    def _make_request(self, response_format=None, system="You are a judge."):
        return CompletionRequest(
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "Is the sky blue?"}],
            provider="anthropic",
            system=system,
            response_format=response_format,
        )

    def _make_mock_response(self, text: str):
        mock_block = MagicMock()
        mock_block.text = text
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        return mock_response

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_structured_output_passes_output_config(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response(
            '{"result": true, "reason": "The sky is blue"}'
        )

        adapter = AnthropicAdapter()
        adapter.complete(
            self._make_request(response_format=BooleanEvalResult),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "output_config" in call_kwargs
        assert call_kwargs["output_config"]["format"]["type"] == "json_schema"
        schema = call_kwargs["output_config"]["format"]["schema"]
        assert "result" in schema["properties"]
        assert "reason" in schema["properties"]

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_structured_output_parses_valid_json(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response(
            '{"result": true, "reason": "The sky is blue"}'
        )

        adapter = AnthropicAdapter()
        result = adapter.complete(
            self._make_request(response_format=BooleanEvalResult),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        assert result.parsed is not None
        assert isinstance(result.parsed, BooleanEvalResult)
        assert result.parsed.result is True
        assert result.parsed.reason == "The sky is blue"

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_structured_output_raises_on_invalid_json(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response("not valid json at all")

        adapter = AnthropicAdapter()
        with pytest.raises(StructuredOutputParseError, match="Failed to parse structured output"):
            adapter.complete(
                self._make_request(response_format=BooleanEvalResult),
                api_key="sk-ant-test",
                analytics=AnalyticsContext(capture=False),
            )

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_structured_output_raises_on_schema_mismatch(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response('{"wrong_field": 123}')

        adapter = AnthropicAdapter()
        with pytest.raises(StructuredOutputParseError):
            adapter.complete(
                self._make_request(response_format=BooleanEvalResult),
                api_key="sk-ant-test",
                analytics=AnalyticsContext(capture=False),
            )

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_non_structured_output_returns_text(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response("The sky is blue.")

        adapter = AnthropicAdapter()
        result = adapter.complete(
            self._make_request(response_format=None),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        assert result.content == "The sky is blue."
        assert result.parsed is None

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_non_structured_output_does_not_pass_output_config(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response("The sky is blue.")

        adapter = AnthropicAdapter()
        adapter.complete(
            self._make_request(response_format=None),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "output_config" not in call_kwargs

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_system_prompt_not_modified_for_structured_output(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_response('{"result": true, "reason": "yes"}')

        adapter = AnthropicAdapter()
        adapter.complete(
            self._make_request(response_format=BooleanEvalResult, system="You are a judge."),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are a judge."
        assert "JSON" not in call_kwargs["system"]
        assert "schema" not in call_kwargs["system"]

    @patch("products.llm_analytics.backend.llm.providers.anthropic.settings")
    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_structured_output_preserves_content_in_response(self, mock_anthropic_cls, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        raw_json = '{"result": false, "reason": "It is night"}'
        mock_client.messages.create.return_value = self._make_mock_response(raw_json)

        adapter = AnthropicAdapter()
        result = adapter.complete(
            self._make_request(response_format=BooleanEvalResult),
            api_key="sk-ant-test",
            analytics=AnalyticsContext(capture=False),
        )

        assert result.content == raw_json
        assert result.parsed is not None
        assert isinstance(result.parsed, BooleanEvalResult)
        assert result.parsed.result is False
