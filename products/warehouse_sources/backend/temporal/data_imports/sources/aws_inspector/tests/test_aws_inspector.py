import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from botocore.session import Session
from botocore.validate import validate_parameters

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.aws_inspector import (
    AwsInspectorClient,
    AwsInspectorError,
    AwsInspectorResumeConfig,
    aws_inspector_source,
    error_for_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.source import AwsInspectorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.aws_inspector"


def response(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def config() -> AwsInspectorSourceConfig:
    return AwsInspectorSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-session",
        region="eu-west-1",
    )


@pytest.fixture
def http() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.make_tracked_session") as factory:
        factory.return_value.post.return_value = response({})
        yield factory.return_value


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize(
    "endpoint,operation,result_key,path,page_size",
    [
        ("findings", "ListFindings", "findings", "/findings/list", 25),
        ("coverage", "ListCoverage", "coveredResources", "/coverage/list", 200),
        ("coverage_statistics", "ListCoverageStatistics", "countsByGroup", "/coverage/statistics/list", None),
    ],
)
def test_signed_requests_and_pagination(
    config: AwsInspectorSourceConfig,
    http: MagicMock,
    manager: MagicMock,
    endpoint: str,
    operation: str,
    result_key: str,
    path: str,
    page_size: int | None,
) -> None:
    http.post.side_effect = [
        response({result_key: [{"resourceId": "example-one"}], "nextToken": "page-2"}),
        response({result_key: [], "nextToken": "page-3"}),
        response({result_key: [{"resourceId": "example-two"}], "nextToken": ""}),
    ]
    resource = aws_inspector_source(config, endpoint, manager, False, None)
    batches = list(cast(Iterable[Any], resource.items()))
    assert batches == [
        [{"resource_id": "example-one", "region": "eu-west-1"}],
        [{"resource_id": "example-two", "region": "eu-west-1"}],
    ]
    model = Session().get_service_model("inspector2", api_version="2020-06-08").operation_model(operation)
    for index, call in enumerate(http.post.call_args_list):
        assert call.args == (f"https://inspector2.eu-west-1.amazonaws.com{path}",)
        assert path == model.http["requestUri"]
        payload = json.loads(call.kwargs["data"])
        assert model.input_shape is not None
        validate_parameters(payload, model.input_shape)
        assert payload.get("maxResults") == page_size
        assert payload.get("nextToken") == [None, "page-2", "page-3"][index]
        assert "filterCriteria" not in payload
        if endpoint == "coverage_statistics":
            assert payload["groupBy"] == "RESOURCE_TYPE"
        headers = call.kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert "X-Amz-Target" not in headers
        assert headers["X-Amz-Security-Token"] == "example-session"
        assert "/eu-west-1/inspector2/aws4_request" in headers["Authorization"]
        assert headers["X-Amz-Date"]
        assert call.kwargs["allow_redirects"] is False
    assert manager.safe_point.call_count == 3
    assert manager.save_state.call_args.args[0].completed
    manager.clear_state.assert_not_called()
    assert resource.on_complete is not None
    resource.on_complete()
    manager.clear_state.assert_called_once()
    http.close.assert_called_once()


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize("endpoint", ["findings", "coverage", "coverage_statistics"])
def test_incremental_filter_survives_pagination_and_full_refresh_omits_it(
    config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock, incremental: bool, endpoint: str
) -> None:
    http.post.side_effect = [response({"nextToken": "page-2"}), response({})]
    resource = aws_inspector_source(config, endpoint, manager, incremental, "2025-01-01T00:00:00Z")
    list(cast(Iterable[Any], resource.items()))
    for call in http.post.call_args_list:
        payload = json.loads(call.kwargs["data"])
        if incremental and endpoint == "findings":
            assert payload["filterCriteria"] == {"updatedAt": [{"startInclusive": 1735689600.0}]}
        else:
            assert "filterCriteria" not in payload
        assert "sortCriteria" not in payload
    assert resource.sort_mode == "desc"


@pytest.mark.parametrize("completed", [False, True])
def test_resume_retains_original_filter_and_stages_before_yield(
    config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock, completed: bool
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsInspectorResumeConfig(
        next_token="saved-page", updated_after=1735689600.0, completed=completed
    )
    http.post.return_value = response(
        {"findings": [{"findingArn": "arn:aws:inspector2:eu-west-1:111111111111:finding/example"}]}
    )
    resource = aws_inspector_source(config, "findings", manager, True, "2025-02-01T00:00:00Z")
    rows = iter(cast(Iterable[Any], resource.items()))
    if completed:
        assert list(rows) == []
        http.post.assert_not_called()
    else:
        next(rows)
        assert json.loads(http.post.call_args.kwargs["data"]) == {
            "maxResults": 25,
            "nextToken": "saved-page",
            "filterCriteria": {"updatedAt": [{"startInclusive": 1735689600.0}]},
        }
        manager.save_state.assert_called_once_with(AwsInspectorResumeConfig(updated_after=1735689600.0, completed=True))
        assert list(rows) == []
    manager.clear_state.assert_not_called()


@pytest.mark.parametrize("value", [1735689600, 1735689600.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00"])
def test_timestamps_and_nested_details(
    config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock, value: str | int | float
) -> None:
    details = {"vulnerabilityId": "CVE-2025-0001", "vulnerablePackages": [{"name": "example"}]}
    http.post.return_value = response(
        {
            "findings": [
                {
                    "findingArn": "example",
                    "firstObservedAt": value,
                    "updatedAt": value,
                    "packageVulnerabilityDetails": details,
                }
            ]
        }
    )
    resource = aws_inspector_source(config, "findings", manager, True, value)
    row = next(iter(cast(Iterable[Any], resource.items())))[0]
    assert row["updated_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert row["first_observed_at"] == row["updated_at"]
    assert row["package_vulnerability_details"] == details
    assert resource.primary_keys == ["finding_arn"]
    assert resource.partition_keys == ["first_observed_at"]


@pytest.mark.parametrize("token", ["same", 42])
def test_invalid_pagination_does_not_complete(
    config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock, token: str | int
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsInspectorResumeConfig(next_token="same")
    http.post.return_value = response({"nextToken": token})
    with pytest.raises(ValueError, match="invalid pagination token"):
        list(cast(Iterable[Any], aws_inspector_source(config, "findings", manager, False, None).items()))
    manager.save_state.assert_not_called()
    manager.clear_state.assert_not_called()
    http.close.assert_called_once()


@pytest.mark.parametrize(
    "code,status,schema,success,message",
    [
        ("AccessDeniedException", 403, None, True, None),
        ("AccessDeniedException", 403, "coverage", False, "inspector2:ListCoverage"),
        ("AccessDenied", 403, "findings", False, "inspector2:ListFindings"),
        ("UnrecognizedClientException", 403, None, False, "AWS rejected the credentials"),
        ("InvalidClientTokenId", 403, None, False, "access key ID"),
        ("InvalidSignatureException", 403, None, False, "signature"),
        ("SignatureDoesNotMatch", 403, None, False, "signature"),
        ("ExpiredTokenException", 403, None, False, "expired"),
        ("SubscriptionRequiredException", 400, None, False, "Enable Amazon Inspector"),
        ("OptInRequired", 403, None, False, "Enable Amazon Inspector"),
    ],
)
def test_credential_errors(
    config: AwsInspectorSourceConfig,
    http: MagicMock,
    code: str,
    status: int,
    schema: str | None,
    success: bool,
    message: str | None,
) -> None:
    http.post.return_value = response({"message": "example error"}, status, {"x-amzn-ErrorType": f"{code}:details"})
    valid, reason = validate_credentials(config, schema)
    assert valid is success
    if message:
        assert reason is not None and message in reason
    else:
        assert reason is None
    error = error_for_response(http.post.return_value)
    matches = [
        text for pattern, text in AwsInspectorSource().get_non_retryable_errors().items() if pattern in str(error)
    ]
    assert matches
    assert all(matches)
    http.close.assert_called_once()


@pytest.mark.parametrize(
    "status,code", [(429, "ThrottlingException"), (500, "InternalServerException"), (503, "HTTP 503")]
)
def test_transient_errors_propagate(config: AwsInspectorSourceConfig, http: MagicMock, status: int, code: str) -> None:
    http.post.return_value = response({"__type": code}, status)
    with pytest.raises(AwsInspectorError, match=code):
        validate_credentials(config)
    assert not any(
        pattern in f"AWS Inspector request failed: {code}"
        for pattern in AwsInspectorSource().get_non_retryable_errors()
    )


@pytest.mark.parametrize(
    "schema,expected", [(None, {"maxResults": 1}), ("coverage_statistics", {"groupBy": "RESOURCE_TYPE"})]
)
def test_credential_probe_is_one_small_request(
    config: AwsInspectorSourceConfig, http: MagicMock, schema: str | None, expected: dict[str, Any]
) -> None:
    assert validate_credentials(config, schema) == (True, None)
    http.post.assert_called_once()
    assert json.loads(http.post.call_args.kwargs["data"]) == expected


@pytest.mark.parametrize("region", ["https://example.com", "us-east-1.example.com", "us-east-1/", "", "US-EAST-1"])
def test_invalid_region_never_sends_credentials(config: AwsInspectorSourceConfig, http: MagicMock, region: str) -> None:
    config.region = region
    valid, reason = validate_credentials(config)
    assert not valid
    assert reason and "region code" in reason
    http.post.assert_not_called()


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials(config: AwsInspectorSourceConfig, http: MagicMock, field: str) -> None:
    setattr(config, field, "")
    assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    http.post.assert_not_called()


def test_unknown_schema_and_version(config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock) -> None:
    assert validate_credentials(config, "unknown") == (False, "Unknown AWS Inspector table: unknown")
    assert validate_credentials(config, api_version="1999-01-01") == (
        False,
        "Unsupported AWS Inspector API version: 1999-01-01",
    )
    with pytest.raises(ValueError, match="Unknown AWS Inspector table"):
        aws_inspector_source(config, "unknown", manager, False, None)
    http.post.assert_not_called()


@pytest.mark.parametrize("region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com")])
def test_regional_signing_without_session_token(
    config: AwsInspectorSourceConfig, http: MagicMock, region: str, suffix: str
) -> None:
    config.region = region
    config.aws_session_token = None
    assert validate_credentials(config) == (True, None)
    assert http.post.call_args.args == (f"https://inspector2.{region}.{suffix}/findings/list",)
    headers = http.post.call_args.kwargs["headers"]
    assert "X-Amz-Security-Token" not in headers
    assert f"/{region}/inspector2/aws4_request" in headers["Authorization"]


@pytest.mark.parametrize(
    "payload,headers,status,code",
    [
        ({"__type": "com.amazonaws#UnrecognizedClientException"}, {}, 400, "UnrecognizedClientException"),
        ({"code": "InvalidSignatureException"}, {}, 400, "InvalidSignatureException"),
        ({"message": "Amazon Inspector is not enabled for this account"}, {}, 403, "SubscriptionRequiredException"),
        ([], {}, 503, "HTTP 503"),
        ({}, {}, 401, "HTTP 401"),
    ],
)
def test_error_shapes(payload: object, headers: dict[str, str], status: int, code: str) -> None:
    assert error_for_response(response(payload, status, headers)).code == code


def test_transport_retries_read_only_posts_and_redacts_credentials(config: AwsInspectorSourceConfig) -> None:
    with patch(f"{MODULE}.make_tracked_session") as factory:
        AwsInspectorClient(config)
    retry = factory.call_args.kwargs["retry"]
    assert retry.is_retry("POST", 429, has_retry_after=True)
    assert retry.is_retry("POST", 500)
    assert not retry.is_retry("POST", 403)
    assert not retry.is_retry("POST", 400)
    assert factory.call_args.kwargs["redact_values"] == ("AKIAEXAMPLE", "example-secret", "example-session")


def test_coverage_keys_keep_scan_types_distinct(
    config: AwsInspectorSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    resource_fields = {"accountId": "111111111111", "resourceId": "i-example", "resourceType": "AWS_EC2_INSTANCE"}
    http.post.return_value = response(
        {
            "coveredResources": [
                {**resource_fields, "scanType": "PACKAGE", "lastScannedAt": 1735689600},
                {**resource_fields, "scanType": "NETWORK", "lastScannedAt": None},
            ]
        }
    )
    resource = aws_inspector_source(config, "coverage", manager, False, None)
    rows = next(iter(cast(Iterable[Any], resource.items())))
    assert resource.primary_keys is not None
    assert len({tuple(row[key] for key in resource.primary_keys) for row in rows}) == 2
    assert rows[0]["last_scanned_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert rows[1]["last_scanned_at"] is None


@pytest.mark.parametrize("status", [200, 503])
def test_malformed_response(config: AwsInspectorSourceConfig, http: MagicMock, status: int) -> None:
    http.post.return_value = response([], status)
    if status == 200:
        with pytest.raises(ValueError, match="invalid response"):
            validate_credentials(config)
    else:
        http.post.return_value._content = b"not JSON"
        with pytest.raises(AwsInspectorError, match="HTTP 503"):
            validate_credentials(config)
    http.close.assert_called_once()
