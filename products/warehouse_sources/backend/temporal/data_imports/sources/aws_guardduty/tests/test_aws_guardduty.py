import json
import datetime as dt
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.aws_guardduty import (
    AwsGuarddutyClient,
    AwsGuarddutyError,
    AwsGuarddutyResumeConfig,
    AwsGuarddutyThrottledError,
    error_for_response,
    validate_credentials,
    watermark_milliseconds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.source import AwsGuarddutySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsguardduty import (
    AwsGuarddutySourceConfig,
)

VERSION = "2017-11-28"
UPDATED_AT = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)


def response(
    payload: dict[str, Any] | None = None, status: int = 200, headers: dict[str, str] | None = None
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {}).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def config() -> AwsGuarddutySourceConfig:
    return AwsGuarddutySourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-session-token",
        aws_region="us-east-1",
    )


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize("terminal", [{}, {"nextToken": None}, {"nextToken": ""}])
def test_findings_pages_hydration_and_time_filter(
    config: AwsGuarddutySourceConfig, incremental: bool, terminal: dict[str, Any]
) -> None:
    script = [
        ScriptedResponse(json={"detectorIds": [], "nextToken": "detectors-next"}),
        ScriptedResponse(json={"detectorIds": ["detector-example"]}),
        ScriptedResponse(json={"findingIds": [], "nextToken": "findings-next"}),
        ScriptedResponse(json={"findingIds": ["finding-example"], **terminal}),
        ScriptedResponse(
            json={
                "findings": [
                    {
                        "id": "finding-example",
                        "arn": "arn:aws:guardduty:us-east-1:111111111111:detector/example/finding/example",
                        "createdAt": "2024-12-01T00:00:00Z",
                        "updatedAt": "2025-01-01T00:00:00Z",
                        "resource": {"resourceType": "Instance", "instanceDetails": {"instanceId": "i-example"}},
                    }
                ]
            }
        ),
    ]
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "findings",
        script,
        api_version=VERSION,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=UPDATED_AT,
    )

    assert result.raised is None
    assert len(result.items) == 1
    row = result.items[0][0]
    assert row["updated_at"] == UPDATED_AT
    assert row["created_at"] == dt.datetime(2024, 12, 1, tzinfo=dt.UTC)
    assert row["source_detector_id"] == "detector-example"
    assert row["resource"]["instanceDetails"]["instanceId"] == "i-example"
    requests_made = result.requests
    assert requests_made[1].param("nextToken") == "detectors-next"
    for request in requests_made[2:4]:
        payload = request.json()
        assert payload["maxResults"] == 50
        assert payload["sortCriteria"] == {"attributeName": "updatedAt", "orderBy": "ASC"}
        if incremental:
            assert payload["findingCriteria"] == {"criterion": {"updatedAt": {"greaterThanOrEqual": 1735689600000}}}
        else:
            assert "findingCriteria" not in payload
    assert requests_made[3].json()["nextToken"] == "findings-next"
    assert requests_made[4].json() == {
        "findingIds": ["finding-example"],
        "sortCriteria": {"attributeName": "updatedAt", "orderBy": "ASC"},
    }
    assert len(result.saved_states) == 2
    assert result.saved_states[-1].detector_ids == []
    assert result.final_state == result.saved_states[-1]
    assert result.completed_state is None
    response = result.response
    assert response is not None
    assert response.partition_keys == ["created_at"]
    assert response.sort_mode == "desc"


def test_detector_details(config: AwsGuarddutySourceConfig) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "detectors",
        [
            ScriptedResponse(json={"detectorIds": ["detector-example"]}),
            ScriptedResponse(
                json={"status": "ENABLED", "createdAt": "2025-01-01T00:00:00Z", "tags": {"purpose": "example"}}
            ),
        ],
        api_version=VERSION,
    )
    assert result.raised is None
    assert result.items == [
        [
            {
                "status": "ENABLED",
                "created_at": UPDATED_AT,
                "tags": {"purpose": "example"},
                "region": "us-east-1",
                "source_detector_id": "detector-example",
            }
        ]
    ]
    assert result.paths[-1].endswith("/detector/detector-example")


@pytest.mark.parametrize(
    "endpoint,path,items_key,item,timestamp_column,partition_keys",
    [
        (
            "coverage",
            "/detector/detector-example/coverage",
            "resources",
            {
                "resourceId": "i-example",
                "accountId": "111111111111",
                "coverageStatus": "HEALTHY",
                "updatedAt": 1735689600.0,
            },
            "updated_at",
            None,
        ),
        (
            "malware_scans",
            "/detector/detector-example/malware-scans",
            "scans",
            {"scanId": "scan-example", "scanStatus": "COMPLETED", "scanStartTime": 1735689600, "totalBytes": 10},
            "scan_start_time",
            ["scan_start_time"],
        ),
    ],
)
def test_detector_list_endpoints_page_and_parse_epoch_timestamps(
    config: AwsGuarddutySourceConfig,
    endpoint: str,
    path: str,
    items_key: str,
    item: dict[str, Any],
    timestamp_column: str,
    partition_keys: list[str] | None,
) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        endpoint,
        [
            ScriptedResponse(json={"detectorIds": ["detector-example"]}),
            ScriptedResponse(json={items_key: [item], "nextToken": "page-2"}),
            ScriptedResponse(json={items_key: [item]}),
        ],
        api_version=VERSION,
    )
    assert result.raised is None
    assert len(result.items) == 2
    row = result.items[0][0]
    assert row[timestamp_column] == UPDATED_AT
    assert row["source_detector_id"] == "detector-example"
    assert all(request.path.endswith(path) for request in result.requests[1:])
    assert result.requests[1].json() == {"maxResults": 50}
    assert result.requests[2].json() == {"maxResults": 50, "nextToken": "page-2"}
    assert result.saved_states[-1].detector_ids == []
    assert result.response is not None and result.response.partition_keys == partition_keys


def test_usage_statistics_walks_every_statistic_type_per_detector(config: AwsGuarddutySourceConfig) -> None:
    total = {"amount": "1.5", "unit": "USD"}
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "usage_statistics",
        [
            ScriptedResponse(json={"detectorIds": ["detector-a", "detector-b"]}),
            ScriptedResponse(
                json={
                    "usageStatistics": {"sumByAccount": [{"accountId": "111111111111", "total": total}]},
                    "nextToken": "next",
                }
            ),
            ScriptedResponse(
                json={"usageStatistics": {"sumByAccount": [{"accountId": "222222222222", "total": total}]}}
            ),
            ScriptedResponse(json={"usageStatistics": {"sumByFeature": [{"feature": "FLOW_LOGS", "total": total}]}}),
            ScriptedResponse(json={"usageStatistics": {"sumByResource": []}}),
            ScriptedResponse(json={"usageStatistics": {}}),
            ScriptedResponse(json={"usageStatistics": {}}),
            ScriptedResponse(
                json={"usageStatistics": {"sumByResource": [{"resource": "bucket-example", "total": total}]}}
            ),
        ],
        api_version=VERSION,
    )
    assert result.raised is None
    rows = [row for batch in result.items for row in batch]
    assert [(row["source_detector_id"], row["usage_statistic_type"], row["usage_key"]) for row in rows] == [
        ("detector-a", "SUM_BY_ACCOUNT", "111111111111"),
        ("detector-a", "SUM_BY_ACCOUNT", "222222222222"),
        ("detector-a", "SUM_BY_FEATURES", "FLOW_LOGS"),
        ("detector-b", "SUM_BY_RESOURCE", "bucket-example"),
    ]
    assert rows[0]["total"] == total
    payloads = [request.json() for request in result.requests[1:]]
    assert [payload["usageStatisticsType"] for payload in payloads] == [
        "SUM_BY_ACCOUNT",
        "SUM_BY_ACCOUNT",
        "SUM_BY_FEATURES",
        "SUM_BY_RESOURCE",
        "SUM_BY_ACCOUNT",
        "SUM_BY_FEATURES",
        "SUM_BY_RESOURCE",
    ]
    assert payloads[1]["nextToken"] == "next"
    assert "FLOW_LOGS" in payloads[0]["usageCriteria"]["features"]
    assert result.requests[-1].path.endswith("/detector/detector-b/usage/statistics")
    assert result.saved_states[-1].detector_ids == []


def test_usage_statistics_resumes_at_saved_statistic_type(config: AwsGuarddutySourceConfig) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "usage_statistics",
        [ScriptedResponse(json={"usageStatistics": {"sumByResource": [{"resource": "bucket-example"}]}})],
        api_version=VERSION,
        resume_state=AwsGuarddutyResumeConfig(
            detector_ids=["detector-example"], usage_statistic_types=["SUM_BY_RESOURCE"], next_token="resume-token"
        ),
    )
    assert result.raised is None
    assert result.items[0][0]["usage_key"] == "bucket-example"
    assert len(result.requests) == 1
    assert result.requests[0].json()["usageStatisticsType"] == "SUM_BY_RESOURCE"
    assert result.requests[0].json()["nextToken"] == "resume-token"


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (UPDATED_AT, 1735689600000),
        ("2025-01-01T01:00:00.123+01:00", 1735689600123),
        ("2025-01-01T00:00:00", 1735689600000),
    ],
)
def test_watermark_conversion(value: dt.datetime | str | None, expected: int | None) -> None:
    assert watermark_milliseconds(value) == expected


@pytest.mark.parametrize(
    "status,payload,headers,code,retryable",
    [
        (403, {"message": "Access denied"}, {}, "AccessDenied", False),
        (403, {"__type": "com.amazonaws#AccessDeniedException"}, {}, "AccessDeniedException", False),
        (
            400,
            {"message": "Invalid key"},
            {"x-amzn-ErrorType": "UnrecognizedClientException:example"},
            "UnrecognizedClientException",
            False,
        ),
        (400, {"code": "InvalidSignatureException"}, {}, "InvalidSignatureException", False),
        (400, {"code": "ExpiredTokenException"}, {}, "ExpiredTokenException", False),
        (400, {"message": "AWS subscription is required"}, {}, "SubscriptionRequiredException", False),
        (400, {"message": "The account is not subscribed to the service."}, {}, "SubscriptionRequiredException", False),
        (400, {"__type": "ThrottlingException"}, {}, "ThrottlingException", True),
        (429, {"__type": "ThrottlingException"}, {}, "ThrottlingException", False),
        (500, {"__type": "InternalServerErrorException"}, {}, "InternalServerErrorException", False),
    ],
)
def test_error_mapping(
    status: int, payload: dict[str, Any], headers: dict[str, str], code: str, retryable: bool
) -> None:
    error = error_for_response(response(payload, status, headers))
    assert error.code == code
    assert isinstance(error, AwsGuarddutyThrottledError) == retryable
    if code not in {"ThrottlingException", "InternalServerErrorException"}:
        messages = AwsGuarddutySource().get_non_retryable_errors()
        assert any(pattern in str(error) and message for pattern, message in messages.items())


@pytest.mark.parametrize("status", [403, 502])
def test_non_json_errors(status: int) -> None:
    result = response(status=status)
    result._content = b"upstream error"
    assert error_for_response(result).code == ("AccessDenied" if status == 403 else "HTTP 502")


@pytest.mark.parametrize(
    "status,code,attempts",
    [(400, "ThrottlingException", 2), (429, "ThrottlingException", 1), (500, "InternalServerErrorException", 1)],
)
def test_only_body_throttles_get_application_retries(
    config: AwsGuarddutySourceConfig, status: int, code: str, attempts: int
) -> None:
    error = ScriptedResponse(status=status, json={"code": code})
    script = [error, ScriptedResponse(json={"detectorIds": []})] if attempts == 2 else always(error)
    with scripted_network(script) as network:
        client = AwsGuarddutyClient(config, VERSION)
        if attempts == 1:
            with pytest.raises(AwsGuarddutyError):
                client.request("ListDetectors", {})
        else:
            assert client.request("ListDetectors", {}) == {"detectorIds": []}
        client.close()
    if attempts == 2:
        assert len(network.requests_log) == 2
    else:
        assert len(network.requests_log) > 1


@pytest.mark.parametrize("schema_name", [None, "findings", "detectors", "members"])
def test_permission_denial_only_accepted_at_create(config: AwsGuarddutySourceConfig, schema_name: str | None) -> None:
    denied = ScriptedResponse(status=403, json={"__type": "AccessDeniedException", "message": "Access denied"})
    with scripted_network([denied]) as network:
        valid, message = validate_credentials(config, VERSION, schema_name)
    assert valid is (schema_name is None)
    if schema_name:
        assert message and "guardduty:ListDetectors" in message
    else:
        assert message is None
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "code",
    [
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
        "SubscriptionRequiredException",
    ],
)
def test_invalid_credentials_rejected(config: AwsGuarddutySourceConfig, code: str) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code})]):
        valid, message = validate_credentials(config, VERSION)
    assert not valid and message
    assert "AWS GuardDuty request failed" not in message


@pytest.mark.parametrize("schema_name", [None, "findings", "detectors", "members"])
def test_no_detector_validation(config: AwsGuarddutySourceConfig, schema_name: str | None) -> None:
    with scripted_network([ScriptedResponse(json={"detectorIds": []})]):
        valid, message = validate_credentials(config, VERSION, schema_name)
    assert valid is (schema_name is None)
    assert (
        message is None
        if schema_name is None
        else message == "Enable GuardDuty in the selected AWS region, then reconnect."
    )


@pytest.mark.parametrize(
    "schema_name,path",
    [
        ("findings", "/findings"),
        ("members", "/member"),
        ("detectors", "/detector/detector-example"),
        ("coverage", "/coverage"),
        ("malware_scans", "/malware-scans"),
        ("usage_statistics", "/usage/statistics"),
    ],
)
def test_endpoint_validation_calls_its_read_operation(
    config: AwsGuarddutySourceConfig, schema_name: str, path: str
) -> None:
    with scripted_network(
        [ScriptedResponse(json={"detectorIds": ["detector-example"]}), ScriptedResponse(json={})]
    ) as network:
        assert validate_credentials(config, VERSION, schema_name) == (True, None)
    assert network.requests_log[-1].path.endswith(path)


def test_findings_validation_checks_hydration_permission(config: AwsGuarddutySourceConfig) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"detectorIds": ["detector-example"]}),
            ScriptedResponse(json={"findingIds": ["finding-example"]}),
            ScriptedResponse(status=403, json={"code": "AccessDeniedException"}),
        ]
    ) as network:
        valid, message = validate_credentials(config, VERSION, "findings")
    assert not valid and message and "guardduty:GetFindings" in message
    assert network.requests_log[-1].path.endswith("/findings/get")


def test_server_errors_report_an_unreachable_vendor(config: AwsGuarddutySourceConfig) -> None:
    with scripted_network(always(ScriptedResponse(status=500, json={"__type": "InternalServerErrorException"}))):
        assert validate_credentials(config, VERSION) == (
            False,
            "Couldn't reach AWS GuardDuty to check your credentials. Try again in a few minutes.",
        )


@pytest.mark.parametrize(
    "field_name,value,message",
    [
        ("aws_region", "us-east-1.example.com/", "valid AWS region"),
        ("aws_region", "us-east-1\n", "valid AWS region"),
        ("aws_access_key_id", "", "Enter both"),
        ("aws_secret_access_key", "", "Enter both"),
    ],
)
def test_invalid_configuration_never_sends_request(
    config: AwsGuarddutySourceConfig, field_name: str, value: str, message: str
) -> None:
    setattr(config, field_name, value)
    with scripted_network([]) as network:
        valid, error = validate_credentials(config, VERSION)
    assert not valid and error and message in error
    assert network.requests_log == []


def test_unknown_version_and_table(config: AwsGuarddutySourceConfig) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, "2099-01-01")[0] is False
        assert validate_credentials(config, VERSION, "unknown") == (False, "Unknown GuardDuty table: unknown")
        result = SourceDriver(AwsGuarddutySource(), config).run("unknown", [], api_version=VERSION)
    assert isinstance(result.raised, UnknownResourceError)
    assert network.requests_log == []
    assert result.requests == []


def test_hydration_failure_keeps_checkpoint(config: AwsGuarddutySourceConfig) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/findings/get"):
            return ScriptedResponse(status=500, json={"code": "InternalServerErrorException"})
        if request.path.endswith("/findings"):
            return ScriptedResponse(json={"findingIds": ["finding-example"], "nextToken": "next-page"})
        return ScriptedResponse(json={"detectorIds": ["detector-example"]})

    result = SourceDriver(AwsGuarddutySource(), config).run("findings", answer, api_version=VERSION)
    assert isinstance(result.raised, AwsGuarddutyError)
    assert result.saved_states == []
    assert result.final_state is None


@pytest.mark.parametrize("endpoint", ["findings", "members"])
def test_repeated_token_fails_without_looping(config: AwsGuarddutySourceConfig, endpoint: str) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        endpoint,
        [ScriptedResponse(json={"nextToken": "same-token"})],
        api_version=VERSION,
        resume_state=AwsGuarddutyResumeConfig(detector_ids=["detector-example"], next_token="same-token"),
    )
    assert isinstance(result.raised, ValueError) and "repeated a page token" in str(result.raised)
    assert len(result.requests) == 1


def test_repeated_detector_token_fails_without_looping(config: AwsGuarddutySourceConfig) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "detectors", always(ScriptedResponse(json={"detectorIds": [], "nextToken": "same-token"})), api_version=VERSION
    )
    assert isinstance(result.raised, ValueError) and "repeated a page token" in str(result.raised)
    assert len(result.requests) == 2


@pytest.mark.parametrize("endpoint", ["findings", "members"])
def test_cyclic_token_fails_without_looping(config: AwsGuarddutySourceConfig, endpoint: str) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        endpoint,
        [
            ScriptedResponse(json={"nextToken": "token-a"}),
            ScriptedResponse(json={"nextToken": "token-b"}),
            ScriptedResponse(json={"nextToken": "token-a"}),
        ],
        api_version=VERSION,
        resume_state=AwsGuarddutyResumeConfig(detector_ids=["detector-example"]),
    )
    assert isinstance(result.raised, ValueError) and "repeated a page token" in str(result.raised)
    assert result.saved_states[-1].next_token == "token-b"
    assert len(result.requests) == 3


def test_cyclic_detector_token_fails_without_looping(config: AwsGuarddutySourceConfig) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "detectors",
        [
            ScriptedResponse(json={"detectorIds": [], "nextToken": "token-a"}),
            ScriptedResponse(json={"detectorIds": [], "nextToken": "token-b"}),
            ScriptedResponse(json={"detectorIds": [], "nextToken": "token-a"}),
        ],
        api_version=VERSION,
    )
    assert isinstance(result.raised, ValueError) and "repeated a page token" in str(result.raised)
    assert len(result.requests) == 3


def test_invalid_response_fails_instead_of_silently_finishing(config: AwsGuarddutySourceConfig) -> None:
    result = SourceDriver(AwsGuarddutySource(), config).run(
        "findings", [ScriptedResponse(body=b"[]")], api_version=VERSION
    )
    assert isinstance(result.raised, ValueError) and "invalid response" in str(result.raised)
