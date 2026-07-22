from unittest.mock import MagicMock, patch

from products.ai_observability.backend.llm.types import CompletionResponse
from products.tasks.backend.temporal.build_image.activities import ScanVerdict, _judge_spec_safety


@patch("products.ai_observability.backend.llm.client.Client")
def test_security_scan_uses_structured_output(mock_client_class: MagicMock) -> None:
    verdict = ScanVerdict.model_validate(
        {"passed": True, "findings": [{"severity": "low", "detail": "Pinned development tool"}]}
    )
    mock_client_class.return_value.complete.return_value = CompletionResponse(
        content="free-form text that is not JSON", model="claude-sonnet-4-6", parsed=verdict
    )

    result = _judge_spec_safety("apt_packages:\n  - git", repository="posthog/posthog")

    assert result.passed is True
    assert result.findings == [{"severity": "low", "detail": "Pinned development tool"}]
    request = mock_client_class.return_value.complete.call_args.args[0]
    assert request.response_format is ScanVerdict
