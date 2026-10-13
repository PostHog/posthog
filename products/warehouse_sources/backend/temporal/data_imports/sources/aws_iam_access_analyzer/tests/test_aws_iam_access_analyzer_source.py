import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer import (
    aws_iam_access_analyzer as transport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.source import (
    AwsIamAccessAnalyzerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.tests.test_aws_iam_access_analyzer import (
    CONFIG,
    PARENT_A,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)


@pytest.mark.parametrize("incremental", [False, True])
def test_pipeline_does_not_filter_findings_by_a_stored_watermark(incremental: bool) -> None:
    result = SourceDriver(AwsIamAccessAnalyzerSource(), CONFIG).run(
        "findings",
        [
            ScriptedResponse(json={"analyzers": [PARENT_A]}),
            ScriptedResponse(json={"findings": [{"id": "example-finding"}]}),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
        incremental_field="updated_at",
    )
    assert result.raised is None
    assert result.rows[0]["analyzer_arn"] == PARENT_A["arn"]
    assert result.response is not None
    assert result.response.primary_keys == ["analyzer_arn", "id"]
    assert result.requests[-1].json() == {
        "maxResults": 100,
        "analyzerArn": PARENT_A["arn"],
    }


def test_permission_errors_are_scoped_to_each_selected_table() -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"analyzers": [PARENT_A]}),
            ScriptedResponse(json={"analyzers": [PARENT_A]}),
            ScriptedResponse(status=403, json={"__type": "AccessDeniedException"}),
        ]
    ):
        permissions = AwsIamAccessAnalyzerSource().get_endpoint_permissions(CONFIG, 1, ["analyzers", "findings"])
    assert permissions["analyzers"] is None
    assert "access-analyzer:ListFindings" in (permissions["findings"] or "")


@pytest.mark.parametrize(
    "code,terminal",
    [
        ("AccessDeniedException", True),
        ("UnrecognizedClientException", True),
        ("InvalidSignatureException", True),
        ("SubscriptionRequiredException", True),
        ("ValidationException", True),
        ("ThrottlingException", False),
        ("InternalServerException", False),
    ],
)
def test_api_errors_match_the_pipeline_retry_policy(code: str, terminal: bool) -> None:
    with scripted_network(always(ScriptedResponse(status=403 if terminal else 500, json={"__type": code}))):
        with pytest.raises(transport.AwsIamAccessAnalyzerError) as caught:
            transport.AwsIamAccessAnalyzerClient(CONFIG).request("analyzers")
    matches = [
        message
        for pattern, message in AwsIamAccessAnalyzerSource().get_non_retryable_errors().items()
        if pattern in str(caught.value)
    ]
    assert bool(matches) == terminal
    assert all(matches)
