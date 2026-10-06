import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import patch

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer import (
    aws_iam_access_analyzer as transport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.source import (
    AwsIamAccessAnalyzerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.tests.test_aws_iam_access_analyzer import (
    CONFIG,
    PARENT_A,
    FakeManager,
    response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs


@pytest.mark.parametrize("incremental", [False, True])
def test_pipeline_does_not_filter_findings_by_a_stored_watermark(incremental: bool) -> None:
    inputs = SourceInputs(
        schema_name="findings",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at",
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.side_effect = [
            response({"analyzers": [PARENT_A]}),
            response({"findings": [{"id": "example-finding"}]}),
        ]
        result = AwsIamAccessAnalyzerSource().source_for_pipeline(CONFIG, FakeManager(), inputs)
        rows = list(cast(Iterable[Any], result.items()))
    assert rows[0][0]["analyzer_arn"] == PARENT_A["arn"]
    assert result.primary_keys == ["analyzer_arn", "id"]
    assert json.loads(factory.return_value.request.call_args.kwargs["data"]) == {
        "maxResults": 100,
        "analyzerArn": PARENT_A["arn"],
    }


@pytest.mark.parametrize(
    "names,expected",
    [(None, ["analyzers", "findings", "archive_rules"]), (["findings"], ["findings"]), (["missing"], [])],
)
def test_schema_selection_does_not_require_credentials(names: list[str] | None, expected: list[str]) -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        schemas = AwsIamAccessAnalyzerSource().get_schemas(CONFIG, 1, names=names)
    assert [schema.name for schema in schemas] == expected
    assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
    factory.assert_not_called()


def test_permission_errors_are_scoped_to_each_selected_table() -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.side_effect = [
            response({"analyzers": [PARENT_A]}),
            response({"analyzers": [PARENT_A]}),
            response({"__type": "AccessDeniedException"}, 403),
        ]
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
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({"__type": code}, 403 if terminal else 500)
        with pytest.raises(transport.AwsIamAccessAnalyzerError) as caught:
            transport.AwsIamAccessAnalyzerClient(CONFIG).request("analyzers")
    matches = [
        message
        for pattern, message in AwsIamAccessAnalyzerSource().get_non_retryable_errors().items()
        if pattern in str(caught.value)
    ]
    assert bool(matches) == terminal
    assert all(matches)
