import pytest
from unittest.mock import MagicMock, patch

from modal.exception import ImageBuildError
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from products.tasks.backend.temporal.build_image.activities import (
    SCAN_JUDGE_MODEL,
    SCAN_JUDGE_PRODUCT,
    ImageBuildActivityInput,
    _judge_spec_safety,
    _parse_scan_verdict,
    build_and_publish_image,
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
    mock_get_llm_client.assert_called_once_with(product=SCAN_JUDGE_PRODUCT, team_id=42, api_key=None)
    request = mock_get_llm_client.return_value.chat.completions.create.call_args.kwargs
    assert request["model"] == SCAN_JUDGE_MODEL
    assert request["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@patch("products.tasks.backend.temporal.build_image.activities.parse_image_spec_json")
@patch("products.tasks.backend.temporal.build_image.activities._get_image")
@patch("products.tasks.backend.temporal.build_image.activities._compose_modal_image")
async def test_image_build_failure_is_not_retried(
    mock_compose: MagicMock, _mock_get_image: MagicMock, _mock_parse_spec: MagicMock
) -> None:
    modal_image = MagicMock()
    modal_image.build.side_effect = ImageBuildError("Image build for im-123 failed", image_id="im-123")
    mock_compose.return_value = (modal_image, MagicMock(), None)

    with pytest.raises(ApplicationError) as exc_info:
        await build_and_publish_image(ImageBuildActivityInput(image_id="image-id", team_id=1))

    assert exc_info.value.non_retryable is True
    assert exc_info.value.type == "ImageBuildError"
    assert exc_info.value.message == "Image build for im-123 failed"
