import json

import pytest
from unittest.mock import Mock, patch

from pydantic import BaseModel
from rest_framework import exceptions

from products.surveys.backend.llm.gateway import generate_structured_output


class _Schema(BaseModel):
    greeting: str


def _response(content: str | None) -> Mock:
    message = Mock()
    message.content = content
    choice = Mock()
    choice.message = message
    response = Mock()
    response.choices = [choice]
    return response


def _call(**overrides):
    kwargs = {
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
    client = Mock()
    client.chat.completions.create.return_value = _response('{"greeting": "hello"}')
    mock_get_client.return_value = client

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
def test_drops_gateway_owned_properties_and_stamps_trace_id(mock_get_client: Mock) -> None:
    client = Mock()
    client.chat.completions.create.return_value = _response('{"greeting": "hello"}')
    mock_get_client.return_value = client

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
    assert headers["x-posthog-property-llm_trace_id"] == trace_id


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_omits_user_when_no_distinct_id(mock_get_client: Mock) -> None:
    client = Mock()
    client.chat.completions.create.return_value = _response('{"greeting": "hello"}')
    mock_get_client.return_value = client

    _call(distinct_id=None)

    assert "user" not in client.chat.completions.create.call_args.kwargs


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_empty_content_raises_validation_error(mock_get_client: Mock) -> None:
    client = Mock()
    client.chat.completions.create.return_value = _response(None)
    mock_get_client.return_value = client

    with pytest.raises(exceptions.ValidationError):
        _call()


@patch("products.surveys.backend.llm.gateway.get_llm_client")
def test_provider_failure_surfaces_as_api_exception(mock_get_client: Mock) -> None:
    client = Mock()
    client.chat.completions.create.side_effect = RuntimeError("upstream 401")
    mock_get_client.return_value = client

    with pytest.raises(exceptions.APIException):
        _call()
