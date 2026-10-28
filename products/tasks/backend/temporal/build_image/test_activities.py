from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.temporal.build_image.activities import (
    SCAN_JUDGE_AI_PRODUCT,
    SCAN_JUDGE_MODEL,
    _judge_spec_safety,
    _parse_scan_verdict,
)


class TestParseScanVerdict:
    @parameterized.expand(
        [
            ("missing_findings", '{"passed":true}'),
            ("json_fence", '```json\n{"passed":true}\n```'),
            ("prose_prefix", 'Scan result:\n{"passed":true}'),
        ]
    )
    def test_accepts_valid_verdict_wrappers(self, _name: str, content: str) -> None:
        verdict = _parse_scan_verdict(content)

        assert verdict.passed is True
        assert verdict.findings == []


@patch("posthog.llm.gateway_client.build_ai_gateway_openai_client")
def test_security_scan_uses_glm_json_output(mock_build_client: MagicMock) -> None:
    response = mock_build_client.return_value.chat.completions.create.return_value
    response.choices = [MagicMock()]
    response.choices[
        0
    ].message.content = '{"passed":true,"findings":[{"severity":"low","detail":"Pinned development tool"}]}'

    result = _judge_spec_safety(
        "apt_packages:\n  - git", team_id=42, gateway_token="pha_user_token", repository="posthog/posthog"
    )

    assert result.passed is True
    assert result.findings == [{"severity": "low", "detail": "Pinned development tool"}]
    mock_build_client.assert_called_once_with(
        api_key="pha_user_token",
        ai_product=SCAN_JUDGE_AI_PRODUCT,
        properties={"team_id": "42"},
        distinct_id="team-42",
    )
    request = mock_build_client.return_value.chat.completions.create.call_args.kwargs
    assert request["model"] == SCAN_JUDGE_MODEL == "zai-org/glm-5.2"
    assert request["response_format"] == {"type": "json_object"}
