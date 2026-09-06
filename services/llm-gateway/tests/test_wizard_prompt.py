from copy import deepcopy
from typing import Any, Literal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from llm_gateway.products.wizard_prompt import WIZARD_PURPOSE_PROMPT, prepend_wizard_purpose


@pytest.mark.parametrize(
    "system", [None, "runtime", [{"type": "text", "text": "runtime", "cache_control": {"type": "ephemeral"}}]]
)
def test_anthropic_preserves_system_blocks_and_thinking(system: Any) -> None:
    messages = [{"role": "assistant", "content": [{"type": "thinking", "thinking": "inspect", "signature": "opaque"}]}]
    data = {"system": deepcopy(system), "messages": deepcopy(messages), "stream": True}
    prepend_wizard_purpose(data, "wizard", "anthropic")

    assert data["system"][0] == {"type": "text", "text": WIZARD_PURPOSE_PROMPT}
    expected = [{"type": "text", "text": system}] if isinstance(system, str) else system or []
    assert data["system"][1:] == expected
    assert data["messages"] == messages
    assert data["stream"] is True


def test_chat_preserves_existing_instructions_and_tool_results() -> None:
    messages = [
        {"role": "system", "content": "runtime"},
        {"role": "developer", "content": "format"},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]
    data = {"messages": deepcopy(messages)}
    prepend_wizard_purpose(data, "wizard", "chat")
    assert data["messages"] == [{"role": "system", "content": WIZARD_PURPOSE_PROMPT}, *messages]


@pytest.mark.parametrize("instructions", [None, "", "runtime"])
def test_responses_preserves_continuation(instructions: str | None) -> None:
    data = {"instructions": instructions, "input": "next", "previous_response_id": "resp_1"}
    prepend_wizard_purpose(data, "wizard", "responses")
    assert data == {
        "instructions": WIZARD_PURPOSE_PROMPT + "\n\n" + (instructions or ""),
        "input": "next",
        "previous_response_id": "resp_1",
    }


@pytest.mark.parametrize("shape", ["anthropic", "chat", "responses"])
def test_other_products_unchanged(shape: Literal["anthropic", "chat", "responses"]) -> None:
    data = {"messages": [], "system": "runtime", "instructions": "runtime"}
    original = deepcopy(data)
    prepend_wizard_purpose(data, "llm_gateway", shape)
    assert data == original


@pytest.mark.parametrize(
    "shape,data",
    [("anthropic", {"system": 42}), ("anthropic", {"System": "override"}), ("responses", {"instructions": []})],
)
def test_invalid_instruction_fields_rejected(
    shape: Literal["anthropic", "chat", "responses"], data: dict[str, Any]
) -> None:
    with pytest.raises(HTTPException) as exc:
        prepend_wizard_purpose(data, "wizard", shape)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "path,body,target,field",
    [
        (
            "/wizard/v1/messages",
            {"model": "claude-sonnet-4-6", "messages": []},
            "anthropic.handle_llm_request",
            "system",
        ),
        ("/wizard/v1/chat/completions", {"model": "gpt-4", "messages": []}, "openai.handle_llm_request", "messages"),
        ("/wizard/v1/responses", {"model": "gpt-4", "input": "detect"}, "openai.handle_llm_request", "instructions"),
    ],
)
def test_wizard_routes_inject_before_dispatch(
    authenticated_client: TestClient, path: str, body: dict[str, Any], target: str, field: str
) -> None:
    with patch(f"llm_gateway.api.{target}", new_callable=AsyncMock, return_value={}) as dispatch:
        response = authenticated_client.post(path, json=body, headers={"Authorization": "Bearer phx_test_key"})
    assert response.status_code == 200, response.text
    data = dispatch.call_args.kwargs["request_data"]
    assert WIZARD_PURPOSE_PROMPT in str(data[field])


def test_bedrock_fallback_gets_the_prompt_once(authenticated_client: TestClient) -> None:
    with (
        patch(
            "llm_gateway.api.anthropic.handle_llm_request",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=503),
        ),
        patch("llm_gateway.api.anthropic._send_bedrock_messages", new_callable=AsyncMock, return_value={}) as bedrock,
    ):
        response = authenticated_client.post(
            "/wizard/v1/messages",
            json={"model": "claude-sonnet-4-6", "messages": [], "system": "runtime"},
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Use-Bedrock-Fallback": "true"},
        )
    assert response.status_code == 200, response.text
    assert bedrock.call_args.args[0]["system"] == [
        {"type": "text", "text": WIZARD_PURPOSE_PROMPT},
        {"type": "text", "text": "runtime"},
    ]
