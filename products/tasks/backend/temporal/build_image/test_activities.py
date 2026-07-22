from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.build_image.activities import SCAN_JUDGE_MODEL, _judge_spec_safety


@patch("posthog.llm.gateway_client.get_llm_client")
def test_security_scan_uses_glm_json_output(mock_get_llm_client: MagicMock) -> None:
    response = mock_get_llm_client.return_value.chat.completions.create.return_value
    response.choices = [MagicMock()]
    response.choices[
        0
    ].message.content = '{"passed":true,"findings":[{"severity":"low","detail":"Pinned development tool"}]}'

    result = _judge_spec_safety("apt_packages:\n  - git", team_id=42, repository="posthog/posthog")

    assert result.passed is True
    assert result.findings == [{"severity": "low", "detail": "Pinned development tool"}]
    mock_get_llm_client.assert_called_once_with(product="posthog_code", team_id=42)
    request = mock_get_llm_client.return_value.chat.completions.create.call_args.kwargs
    assert request["model"] == SCAN_JUDGE_MODEL
    assert request["response_format"] == {"type": "json_object"}
