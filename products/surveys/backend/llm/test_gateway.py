import json
from typing import Any

import pytest
from unittest.mock import Mock, patch

from pydantic import BaseModel
from rest_framework import exceptions

from products.surveys.backend.llm.gateway import MAX_RETRIES, generate_structured_output


class _Schema(BaseModel):
    greeting: str


def _response(content: str | None, *, choices: bool = True) -> Mock:
    message = Mock()
    message.content = content
    choice = Mock()
    choice.message = message
    response = Mock()
    response.choices = [choice] if choices else []
    return response


def _client(mock_get_client: Mock, response: Mock | None = None, error: Exception | None = None) -> Mock:
    client = Mock()
    # The helper calls `.with_options(...)` before `.chat`, so the configured copy
    # has to be the same mock the assertions read.
    client.with_options.return_value = client
    if error is not None:
        client.chat.completions.create.side_effect = error
    else:
        client.chat.completions.create.return_value = response
    mock_get_client.return_value = client
    return client


def _call(**overrides):
    kwargs: dict[str, Any] = {
        "product": "survey_translation",
        "model": "claude-haiku-4-5",
        "system_prompt": "Translate.",
        "user_prompt": "hola",
        "response_schema": _Schema,
        "team_id": 7,
        "distinct_id": "user-1",
    }
    kwargs.update(overrides)
    return generate_structured_output(**kwargs)


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_routes_through_gateway_and_returns_validated_schema(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    result, trace_id = _call()

    assert result == _Schema(greeting="hello")
    assert trace_id

    # The product route and per-team attribution are what make the gateway bill
    # and tag this call correctly; a wrong product silently mis-bills.
    mock_get_client.assert_called_once_with("survey_translation", team_id=7)

    sent = client.chat.completions.create.call_args.kwargs
    assert sent["model"] == "claude-haiku-4-5"
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["user"] == "user-1"
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][0]["content"].startswith("Translate.")
    assert sent["messages"][1] == {"role": "user", "content": "hola"}
    # The schema has to reach the model somehow: json_object mode enforces valid
    # JSON but not our shape, so dropping the schema text yields unparseable output.
    assert json.dumps(_Schema.model_json_schema()) in sent["messages"][0]["content"]


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_bounds_timeout_tokens_and_retries(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _call(timeout_seconds=12.5, max_tokens=321)

    # Unbounded, these run on a DRF worker with the SDK's 600s default and retry a
    # billable generation twice.
    client.with_options.assert_called_once_with(max_retries=MAX_RETRIES)
    sent = client.chat.completions.create.call_args.kwargs
    assert sent["timeout"] == 12.5
    assert sent["max_tokens"] == 321


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_drops_gateway_owned_properties_and_stamps_trace_id(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _result, trace_id = _call(
        posthog_properties={
            "ai_product": "surveys",
            "$ai_billable": True,
            "ai_feature": "survey_translation",
        }
    )

    headers = client.chat.completions.create.call_args.kwargs["extra_headers"]
    assert "x-posthog-property-ai_product" not in headers
    assert "x-posthog-property-$ai_billable" not in headers
    assert headers["x-posthog-property-ai_feature"] == "survey_translation"
    # The gateway stamps this as the generation's $ai_trace_id, so the id handed
    # back to callers is the one ratings and trace links join on.
    assert headers["x-posthog-trace-id"] == trace_id


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_omits_none_properties_rather_than_stringifying_them(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _call(posthog_properties={"question_id": None, "response_count": 3})

    headers = client.chat.completions.create.call_args.kwargs["extra_headers"]
    # `str(None)` would capture the literal "None" and break isNull filters.
    assert "x-posthog-property-question_id" not in headers
    assert headers["x-posthog-property-response_count"] == "3"


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_sanitizes_non_ascii_property_values(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _call(posthog_properties={"target_language": "日本語", "note": "a\r\nb"})

    headers = client.chat.completions.create.call_args.kwargs["extra_headers"]
    # Header values are ASCII on the wire; unsanitized these raise inside the SDK
    # and surface as a 500 on a user-supplied language name.
    for value in headers.values():
        value.encode("ascii")
    assert "\r" not in headers["x-posthog-property-note"]
    assert "\n" not in headers["x-posthog-property-note"]


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_truncates_overlong_property_values(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _call(posthog_properties={"target_language": "x" * 5000})

    headers = client.chat.completions.create.call_args.kwargs["extra_headers"]
    assert len(headers["x-posthog-property-target_language"]) <= 200


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_falls_back_to_product_when_no_distinct_id(mock_get_client: Mock) -> None:
    client = _client(mock_get_client, _response('{"greeting": "hello"}'))

    _call(distinct_id=None)

    assert client.chat.completions.create.call_args.kwargs["user"] == "survey_translation"


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"greeting": "hello"}\n```',
        'Here you go:\n{"greeting": "hello"}',
        '```\n{"greeting": "hello"}\n```',
    ],
)
@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_tolerates_fenced_or_prefixed_json(mock_get_client: Mock, content: str) -> None:
    _client(mock_get_client, _response(content))

    # json_object is not reliably honoured on the gateway's Anthropic route, so a
    # raw json.loads would turn a good generation into a 500.
    result, _trace_id = _call()

    assert result == _Schema(greeting="hello")


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_schema_violating_json_raises_api_exception(mock_get_client: Mock) -> None:
    _client(mock_get_client, _response('{"unexpected": 1}'))

    # json_object guarantees valid JSON, not our shape; pydantic is the only gate.
    with pytest.raises(exceptions.APIException):
        _call()


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_unparseable_content_raises_api_exception(mock_get_client: Mock) -> None:
    _client(mock_get_client, _response("I cannot help with that."))

    with pytest.raises(exceptions.APIException):
        _call()


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_empty_content_raises_validation_error(mock_get_client: Mock) -> None:
    _client(mock_get_client, _response(None))

    with pytest.raises(exceptions.ValidationError):
        _call()


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_no_choices_raises_validation_error(mock_get_client: Mock) -> None:
    _client(mock_get_client, _response('{"greeting": "hello"}', choices=False))

    with pytest.raises(exceptions.ValidationError):
        _call()


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_provider_failure_surfaces_as_api_exception(mock_get_client: Mock) -> None:
    _client(mock_get_client, error=RuntimeError("upstream 401"))

    with pytest.raises(exceptions.APIException):
        _call()
