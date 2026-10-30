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
    AwsInspectorResumeConfig,
    aws_inspector_source,
    error_for_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.source import AwsInspectorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import RecordedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import route
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.aws_inspector"
SERVICE_MODEL = Session().get_service_model("inspector2", api_version="2020-06-08")
SCAN_ONE = "arn:aws:inspector2:eu-west-1:111111111111:owner/111111111111/cis-scan/00000000-0000-4000-8000-000000000001"
SCAN_TWO = "arn:aws:inspector2:eu-west-1:111111111111:owner/111111111111/cis-scan/00000000-0000-4000-8000-000000000002"
SCAN_THREE = (
    "arn:aws:inspector2:eu-west-1:111111111111:owner/111111111111/cis-scan/00000000-0000-4000-8000-000000000003"
)
IMAGE_ONE = "arn:aws:ecr:eu-west-1:111111111111:repository/example/sha256:" + "a" * 64
IMAGE_TWO = "arn:aws:ecr:eu-west-1:111111111111:repository/example/sha256:" + "b" * 64


def driver(config: AwsInspectorSourceConfig) -> SourceDriver:
    return SourceDriver(AwsInspectorSource(), config)


def assert_valid_request(request: RecordedRequest) -> dict[str, Any]:
    operation = next(
        SERVICE_MODEL.operation_model(name)
        for name in SERVICE_MODEL.operation_names
        if SERVICE_MODEL.operation_model(name).http["requestUri"] == request.path
    )
    payload = request.json()
    assert operation.input_shape is not None
    validate_parameters(payload, operation.input_shape)
    return payload


def details_script() -> dict[str, list[ScriptedResponse]]:
    scans = [
        {"scanArn": SCAN_TWO, "scanConfigurationArn": "example", "status": "COMPLETED", "scanDate": 1735776000},
        {"scanArn": SCAN_THREE, "scanConfigurationArn": "example", "status": "IN_PROGRESS", "scanDate": 1735862400},
    ]
    return {
        "/cis/scan/list": [
            ScriptedResponse(
                json={
                    "scans": [
                        {
                            "scanArn": SCAN_ONE,
                            "scanConfigurationArn": "example",
                            "status": "COMPLETED",
                            "scanDate": 1735689600,
                        }
                    ],
                    "nextToken": "scans-2",
                }
            ),
            ScriptedResponse(json={"scans": scans}),
        ],
        "/cis/scan-result/resource/list": [
            ScriptedResponse(
                json={
                    "targetResourceAggregations": [
                        {"scanArn": SCAN_ONE, "accountId": "111111111111", "targetResourceId": "i-0000000000000001"}
                    ],
                    "nextToken": "targets-2",
                }
            ),
            ScriptedResponse(
                json={
                    "targetResourceAggregations": [
                        {"scanArn": SCAN_ONE, "accountId": "111111111111", "targetResourceId": "i-0000000000000002"}
                    ]
                }
            ),
            ScriptedResponse(
                json={
                    "targetResourceAggregations": [
                        {"scanArn": SCAN_TWO, "accountId": "222222222222", "targetResourceId": "i-0000000000000001"}
                    ]
                }
            ),
            ScriptedResponse(
                json={
                    "targetResourceAggregations": [
                        {"scanArn": SCAN_THREE, "accountId": "222222222222", "targetResourceId": "i-0000000000000001"}
                    ]
                }
            ),
        ],
        "/cis/scan-result/details/get": [
            ScriptedResponse(json={"scanResultDetails": [{"scanArn": SCAN_ONE, "checkId": "1.1"}], "nextToken": "d-2"}),
            ScriptedResponse(json={"scanResultDetails": [{"scanArn": SCAN_ONE, "checkId": "1.2", "status": "FAILED"}]}),
            ScriptedResponse(json={"scanResultDetails": []}),
            ScriptedResponse(json={"scanResultDetails": [{"scanArn": SCAN_TWO, "checkId": "1.1"}]}),
            ScriptedResponse(json={"scanResultDetails": [{"scanArn": SCAN_THREE, "checkId": "1.1"}]}),
        ],
    }


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
        ("members", "ListMembers", "members", "/members/list", 50),
        ("cis_scans", "ListCisScans", "scans", "/cis/scan/list", 100),
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
    config: AwsInspectorSourceConfig, incremental: bool, endpoint: str
) -> None:
    result = driver(config).run(
        endpoint,
        [ScriptedResponse(json={"nextToken": "page-2"}), ScriptedResponse(json={})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
    )
    assert result.raised is None
    assert len(result.requests) == 2
    for request in result.requests:
        payload = request.json()
        if incremental and endpoint == "findings":
            assert payload["filterCriteria"] == {"updatedAt": [{"startInclusive": 1735689600.0}]}
        else:
            assert "filterCriteria" not in payload
        assert "sortCriteria" not in payload
    assert result.response is not None
    assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("completed", [False, True])
def test_resume_retains_original_filter_and_stages_before_yield(
    config: AwsInspectorSourceConfig, completed: bool
) -> None:
    resume_state = AwsInspectorResumeConfig(next_token="saved-page", updated_after=1735689600.0, completed=completed)
    result = driver(config).run(
        "findings",
        [
            ScriptedResponse(
                json={"findings": [{"findingArn": "arn:aws:inspector2:eu-west-1:111111111111:finding/example"}]}
            )
        ]
        if not completed
        else [],
        resume_state=resume_state,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-02-01T00:00:00Z",
    )
    assert result.raised is None
    if completed:
        assert result.items == []
        assert result.requests == []
        assert result.saved_states == []
        assert result.final_state == resume_state
    else:
        assert result.items == [
            [{"finding_arn": "arn:aws:inspector2:eu-west-1:111111111111:finding/example", "region": "eu-west-1"}]
        ]
        assert result.requests[0].json() == {
            "maxResults": 25,
            "nextToken": "saved-page",
            "filterCriteria": {"updatedAt": [{"startInclusive": 1735689600.0}]},
        }
        completed_state = AwsInspectorResumeConfig(updated_after=1735689600.0, completed=True)
        assert result.saved_states == [completed_state]
        assert result.committed_states == [completed_state]
        assert result.final_state == completed_state


@pytest.mark.parametrize("value", [1735689600, 1735689600.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00"])
def test_timestamps_and_nested_details(config: AwsInspectorSourceConfig, value: str | int | float) -> None:
    details = {"vulnerabilityId": "CVE-2025-0001", "vulnerablePackages": [{"name": "example"}]}
    result = driver(config).run(
        "findings",
        [
            ScriptedResponse(
                json={
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
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value=value,
    )
    assert result.raised is None
    row = result.rows[0]
    assert row["updated_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert row["first_observed_at"] == row["updated_at"]
    assert row["package_vulnerability_details"] == details
    assert result.response is not None
    assert result.response.primary_keys == ["finding_arn"]
    assert result.response.partition_keys == ["first_observed_at"]


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
        ("AccessDeniedException", 403, "cis_scan_result_details", False, "inspector2:GetCisScanResultDetails"),
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
def test_transient_errors_report_an_unreachable_vendor(
    config: AwsInspectorSourceConfig, status: int, code: str
) -> None:
    script = [ScriptedResponse(json={"__type": code}, status=status) for _ in range(4)]
    with scripted_network(script):
        assert validate_credentials(config) == (
            False,
            "Couldn't reach AWS Inspector to check your credentials. Try again in a few minutes.",
        )
    assert not any(
        pattern in f"AWS Inspector request failed: {code}"
        for pattern in AwsInspectorSource().get_non_retryable_errors()
    )


@pytest.mark.parametrize(
    "schema,expected",
    [
        (None, {"maxResults": 1}),
        ("coverage_statistics", {"groupBy": "RESOURCE_TYPE"}),
        ("cis_scan_result_details", {"maxResults": 1, "sortBy": "SCAN_START_DATE", "sortOrder": "ASC"}),
        ("clusters_for_image", {"maxResults": 1}),
    ],
)
def test_credential_probe_is_one_small_request(
    config: AwsInspectorSourceConfig, schema: str | None, expected: dict[str, Any]
) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        assert validate_credentials(config, schema) == (True, None)
    assert len(network.requests_log) == 1
    assert network.requests_log[0].json() == expected


@pytest.mark.parametrize("region", ["https://example.com", "us-east-1.example.com", "us-east-1/", "", "US-EAST-1"])
def test_invalid_region_never_sends_credentials(config: AwsInspectorSourceConfig, region: str) -> None:
    config.region = region
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config)
    assert not valid
    assert reason and "region code" in reason
    assert network.requests_log == []


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials(config: AwsInspectorSourceConfig, field: str) -> None:
    setattr(config, field, "")
    with scripted_network([]) as network:
        assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    assert network.requests_log == []


def test_unknown_schema_and_version(config: AwsInspectorSourceConfig) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, "unknown") == (False, "Unknown AWS Inspector table: unknown")
        assert validate_credentials(config, api_version="1999-01-01") == (
            False,
            "Unsupported AWS Inspector API version: 1999-01-01",
        )
    assert network.requests_log == []
    result = driver(config).run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Inspector table" in str(result.raised)
    assert result.requests == []


@pytest.mark.parametrize("region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com")])
def test_regional_signing_without_session_token(config: AwsInspectorSourceConfig, region: str, suffix: str) -> None:
    config.region = region
    config.aws_session_token = None
    with scripted_network([ScriptedResponse(json={})]) as network:
        assert validate_credentials(config) == (True, None)
    assert [request.url for request in network.requests_log] == [f"https://inspector2.{region}.{suffix}/findings/list"]
    headers = network.requests_log[0].headers
    assert "x-amz-security-token" not in headers
    assert f"/{region}/inspector2/aws4_request" in headers["authorization"]


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
    with scripted_network([]) as network:
        client = AwsInspectorClient(config)
        client.close()
    assert len(network.session_options) == 1
    retry = network.session_options[0]["retry"]
    assert retry.is_retry("POST", 429, has_retry_after=True)
    assert retry.is_retry("POST", 500)
    assert not retry.is_retry("POST", 403)
    assert not retry.is_retry("POST", 400)
    assert network.session_options[0]["redact_values"] == ("AKIAEXAMPLE", "example-secret", "example-session")


def test_coverage_keys_keep_scan_types_distinct(
    config: AwsInspectorSourceConfig,
) -> None:
    resource_fields = {"accountId": "111111111111", "resourceId": "i-example", "resourceType": "AWS_EC2_INSTANCE"}
    result = driver(config).run(
        "coverage",
        [
            ScriptedResponse(
                json={
                    "coveredResources": [
                        {**resource_fields, "scanType": "PACKAGE", "lastScannedAt": 1735689600},
                        {**resource_fields, "scanType": "NETWORK", "lastScannedAt": None},
                    ]
                }
            )
        ],
    )
    assert result.raised is None
    rows = result.rows
    assert result.response is not None
    assert result.response.primary_keys is not None
    assert len({tuple(row[key] for key in result.response.primary_keys) for row in rows}) == 2
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
        assert validate_credentials(config) == (
            False,
            "Couldn't reach AWS Inspector to check your credentials. Try again in a few minutes.",
        )
    http.close.assert_called_once()


@pytest.mark.parametrize("incremental", [False, True])
def test_cis_scan_result_details_walk_every_scan_target_and_page(
    config: AwsInspectorSourceConfig, incremental: bool
) -> None:
    result = driver(config).run(
        "cis_scan_result_details",
        route(details_script()),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01T00:00:00Z" if incremental else None,
    )
    assert result.raised is None
    payloads = [(request.path, assert_valid_request(request)) for request in result.requests]
    scan_lists = [payload for path, payload in payloads if path == "/cis/scan/list"]
    assert [payload.get("filterCriteria") for payload in scan_lists] == [
        {"scanAtFilters": [{"earliestScanStartTime": 1735689600.0}]} if incremental else None
    ] * 2
    detail_calls = [
        (payload["scanArn"], payload["accountId"], payload["targetResourceId"], payload.get("nextToken"))
        for path, payload in payloads
        if path == "/cis/scan-result/details/get"
    ]
    expected_calls = [
        (SCAN_ONE, "111111111111", "i-0000000000000001", None),
        (SCAN_ONE, "111111111111", "i-0000000000000001", "d-2"),
        (SCAN_ONE, "111111111111", "i-0000000000000002", None),
        (SCAN_TWO, "222222222222", "i-0000000000000001", None),
    ]
    # Incremental runs stop before an unfinished scan, so the watermark cannot pass it.
    assert detail_calls == (
        expected_calls if incremental else [*expected_calls, (SCAN_THREE, "222222222222", "i-0000000000000001", None)]
    )
    expected_rows = [
        (SCAN_ONE, "i-0000000000000001", "1.1"),
        (SCAN_ONE, "i-0000000000000001", "1.2"),
        (SCAN_TWO, "i-0000000000000001", "1.1"),
    ]
    assert [(row["scan_arn"], row["target_resource_id"], row["check_id"]) for row in result.rows] == (
        expected_rows if incremental else [*expected_rows, (SCAN_THREE, "i-0000000000000001", "1.1")]
    )
    first = result.rows[0]
    assert first["account_id"] == "111111111111"
    assert first["scan_date"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert first["region"] == "eu-west-1"
    assert result.final_state == AwsInspectorResumeConfig(
        updated_after=1735689600.0 if incremental else None, completed=True
    )


def test_cis_scan_result_details_resume_from_saved_position(config: AwsInspectorSourceConfig) -> None:
    script = details_script()
    script["/cis/scan-result/resource/list"] = script["/cis/scan-result/resource/list"][1:]
    script["/cis/scan-result/details/get"] = [
        ScriptedResponse(json={"scanResultDetails": [{"scanArn": SCAN_ONE, "checkId": "1.3"}]}),
        *script["/cis/scan-result/details/get"][3:],
    ]
    result = driver(config).run(
        "cis_scan_result_details",
        route(script),
        resume_state=AwsInspectorResumeConfig(
            scan_arn=SCAN_ONE, parent_token="targets-2", parent_key="111111111111/i-0000000000000002", next_token="d-3"
        ),
    )
    assert result.raised is None
    calls = [(request.path, request.json()) for request in result.requests]
    assert calls[2] == ("/cis/scan-result/resource/list", {**calls[2][1], "nextToken": "targets-2"})
    assert calls[3][1]["targetResourceId"] == "i-0000000000000002"
    assert calls[3][1]["nextToken"] == "d-3"
    assert [row["check_id"] for row in result.rows] == ["1.3", "1.1", "1.1"]
    assert result.saved_states[0] == AwsInspectorResumeConfig(scan_arn=SCAN_TWO)


def test_clusters_for_image_fan_out(config: AwsInspectorSourceConfig) -> None:
    images = [{"resourceId": IMAGE_ONE, "resourceType": "AWS_ECR_CONTAINER_IMAGE"}]
    result = driver(config).run(
        "clusters_for_image",
        route(
            {
                "/coverage/list": [
                    ScriptedResponse(json={"coveredResources": images, "nextToken": "images-2"}),
                    ScriptedResponse(json={"coveredResources": [{**images[0], "resourceId": IMAGE_TWO}]}),
                ],
                "/cluster/get": [
                    ScriptedResponse(
                        json={
                            "cluster": [{"clusterArn": "arn:aws:ecs:eu-west-1:111111111111:cluster/one"}],
                            "nextToken": "clusters-2",
                        }
                    ),
                    ScriptedResponse(
                        json={"cluster": [{"clusterArn": "arn:aws:ecs:eu-west-1:111111111111:cluster/two"}]}
                    ),
                    ScriptedResponse(json={"cluster": []}),
                ],
            }
        ),
    )
    assert result.raised is None
    payloads = [(request.path, assert_valid_request(request)) for request in result.requests]
    assert [path for path, _ in payloads] == [
        "/coverage/list",
        "/cluster/get",
        "/cluster/get",
        "/coverage/list",
        "/cluster/get",
    ]
    assert payloads[0][1]["filterCriteria"]["resourceType"] == [
        {"comparison": "EQUALS", "value": "AWS_ECR_CONTAINER_IMAGE"}
    ]
    assert [payload["filter"]["resourceId"] for path, payload in payloads if path == "/cluster/get"] == [
        IMAGE_ONE,
        IMAGE_ONE,
        IMAGE_TWO,
    ]
    assert [(row["resource_id"], row["cluster_arn"]) for row in result.rows] == [
        (IMAGE_ONE, "arn:aws:ecs:eu-west-1:111111111111:cluster/one"),
        (IMAGE_ONE, "arn:aws:ecs:eu-west-1:111111111111:cluster/two"),
    ]
    assert result.saved_states == [
        AwsInspectorResumeConfig(parent_key=IMAGE_ONE, next_token="clusters-2"),
        AwsInspectorResumeConfig(parent_token="images-2"),
        AwsInspectorResumeConfig(completed=True),
    ]
