import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.aws_config import AwsConfigError
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.source import AwsConfigSource


@pytest.mark.parametrize(
    "code,expected",
    [
        ("AccessDeniedException", "Grant"),
        ("UnrecognizedClientException", "Check"),
        ("InvalidSignatureException", "signature"),
        ("ExpiredTokenException", "expired"),
        ("SubscriptionRequiredException", "Enable AWS Config"),
        ("ThrottlingException", None),
        ("HTTP 503", None),
    ],
)
def test_sync_errors_match_actionable_terminal_messages(code: str, expected: str | None) -> None:
    error = str(AwsConfigError(code, "Example AWS response"))
    messages = [
        message for pattern, message in AwsConfigSource().get_non_retryable_errors().items() if pattern in error
    ]
    if expected is None:
        assert messages == []
    else:
        assert messages
        assert all(expected in (message or "") for message in messages)
