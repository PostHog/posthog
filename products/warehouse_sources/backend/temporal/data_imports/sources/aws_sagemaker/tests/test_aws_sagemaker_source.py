import json

import pytest
from unittest.mock import patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.aws_sagemaker import (
    error_for_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.source import AwsSagemakerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssagemaker import (
    AwsSagemakerSourceConfig,
)


@pytest.mark.parametrize(
    "code,hint",
    [
        ("UnrecognizedClientException", "credentials"),
        ("InvalidClientTokenId", "active access key"),
        ("InvalidSignatureException", "signature"),
        ("SignatureDoesNotMatch", "signature"),
        ("ExpiredTokenException", "expired"),
        ("SubscriptionRequiredException", "Enable SageMaker"),
        ("OptInRequired", "Enable SageMaker"),
        ("AccessDeniedException", "permissions"),
    ],
)
def test_aws_errors_have_actionable_validation_and_sync_messages(code: str, hint: str) -> None:
    response = requests.Response()
    response.status_code = 400
    response._content = json.dumps({"__type": f"com.amazonaws.sagemaker#{code}"}).encode()
    config = AwsSagemakerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="fake-secret", region="us-east-1"
    )
    source = AwsSagemakerSource()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.aws_sagemaker.make_tracked_session"
    ) as factory:
        factory.return_value.post.return_value = response
        valid, message = source.validate_credentials(config, 1, schema_name="models")
    assert valid is False
    assert message
    if code == "AccessDeniedException":
        assert "sagemaker:DescribeModel" in message
    else:
        assert hint in message
    error = str(error_for_response(response))
    matches = [message for pattern, message in source.get_non_retryable_errors().items() if pattern in error]
    assert len(matches) == 1
    assert matches[0] and hint in matches[0]
