import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog import (
    aws_glue_data_catalog as glue,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.settings import (
    ENDPOINTS,
    GLUE_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.source import (
    AwsGlueDataCatalogSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsgluedatacatalog import (
    AwsGlueDataCatalogSourceConfig,
)


def config(region: str = "eu-west-1", token: str | None = None) -> AwsGlueDataCatalogSourceConfig:
    return AwsGlueDataCatalogSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token=token,
        aws_region=region,
    )


def response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


def manager(state: glue.AwsGlueDataCatalogResumeConfig | None = None) -> Mock:
    result = Mock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = state
    return result


@pytest.mark.parametrize(
    "region,token,host",
    [
        ("eu-west-1", None, "glue.eu-west-1.amazonaws.com"),
        ("cn-north-1", "example-token", "glue.cn-north-1.amazonaws.com.cn"),
        ("us-gov-west-1", "example-token", "glue.us-gov-west-1.amazonaws.com"),
    ],
)
def test_signed_request_uses_tracked_transport(region: str, token: str | None, host: str) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.return_value = response({"DatabaseList": []})
        client = glue.AwsGlueClient(config(region, token), GLUE_API_VERSION)
        assert client.request("GetDatabases", {"MaxResults": 1}) == {"DatabaseList": []}

    args, kwargs = session.post.call_args
    assert args == (f"https://{host}/",)
    assert json.loads(kwargs["data"]) == {"MaxResults": 1}
    headers = kwargs["headers"]
    assert headers["X-Amz-Target"] == "AWSGlue.GetDatabases"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert f"/{region}/glue/aws4_request" in headers["Authorization"]
    assert "SignedHeaders=content-type;host;x-amz-date" in headers["Authorization"]
    assert headers["X-Amz-Date"]
    assert headers.get("X-Amz-Security-Token") == token
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60
    redacted = factory.call_args.kwargs["redact_values"]
    assert "example-secret" in redacted
    if token:
        assert token in redacted
    retry_policy = factory.call_args.kwargs["retry"]
    assert retry_policy.is_retry("POST", 429)
    assert retry_policy.is_retry("POST", 503)
    assert not retry_policy.is_retry("POST", 403)


@pytest.mark.parametrize(
    "region,version,expected",
    [
        ("eu-west-1.example.com/path", GLUE_API_VERSION, "Enter an AWS region"),
        ("", GLUE_API_VERSION, "Enter an AWS region"),
        ("eu-west-1", "2099-01-01", "Unsupported AWS Glue API version"),
    ],
)
def test_rejects_invalid_region_or_version_before_http(region: str, version: str, expected: str) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        with pytest.raises(ValueError, match=expected):
            glue.AwsGlueClient(config(region), version)
        factory.assert_not_called()


@pytest.mark.parametrize("terminal_token", [None, ""])
def test_pagination_includes_empty_and_terminal_pages(terminal_token: str | None) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.side_effect = [
            response({"DatabaseList": [], "NextToken": "second"}),
            response({"DatabaseList": [{"Name": "analytics"}], "NextToken": terminal_token}),
        ]
        client = glue.AwsGlueClient(config(), GLUE_API_VERSION)
        pages = list(client.pages(ENDPOINTS["databases"], {}))

    assert [page.items for page in pages] == [[], [{"Name": "analytics"}]]
    assert [json.loads(call.kwargs["data"]) for call in session.post.call_args_list] == [
        {"MaxResults": 100},
        {"MaxResults": 100, "NextToken": "second"},
    ]


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"DatabaseList": [], "NextToken": "same"}, "repeated pagination token"),
        ({"DatabaseList": [], "NextToken": 123}, "invalid pagination token"),
        ({"DatabaseList": "bad"}, "invalid list response"),
        ({"DatabaseList": ["bad"]}, "invalid list response"),
    ],
)
def test_rejects_malformed_pages(payload: dict[str, Any], error: str) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        factory.return_value.post.return_value = response(payload)
        client = glue.AwsGlueClient(config(), GLUE_API_VERSION)
        with pytest.raises(ValueError, match=error):
            list(client.pages(ENDPOINTS["databases"], {}, start_token="same"))


@pytest.mark.parametrize(
    "status,body,headers,code,retryable",
    [
        (
            400,
            {"__type": "com.amazonaws.glue#AccessDeniedException", "Message": "Access denied"},
            {},
            "AccessDeniedException",
            False,
        ),
        (400, {"__type": "ThrottlingException"}, {}, "ThrottlingException", True),
        (400, {"__type": "OperationTimeoutException"}, {}, "OperationTimeoutException", True),
        (500, {"__type": "ThrottlingException"}, {}, "ThrottlingException", False),
        (429, {}, {}, "HTTP 429", False),
        (403, {}, {"x-amzn-ErrorType": "InvalidSignatureException:detail"}, "InvalidSignatureException", False),
        (502, ["unexpected"], {}, "HTTP 502", False),
    ],
)
def test_error_classification(status: int, body: object, headers: dict[str, str], code: str, retryable: bool) -> None:
    error = glue.error_for_response(response(body, status, headers))
    assert error.code == code
    assert isinstance(error, glue.AwsGlueRetryableError) is retryable


@pytest.mark.parametrize("status,attempts", [(400, 2), (429, 1), (500, 1)])
def test_body_retry_does_not_repeat_transport_retries(status: int, attempts: int) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.side_effect = [
            response({"__type": "ThrottlingException"}, status),
            response({"DatabaseList": []}),
        ]
        client = glue.AwsGlueClient(config(), GLUE_API_VERSION)
        request = cast(Any, client.request).retry_with(wait=wait_none())
        if status == 400:
            assert request(client, "GetDatabases", {}) == {"DatabaseList": []}
        else:
            with pytest.raises(glue.AwsGlueError):
                request(client, "GetDatabases", {})
        assert session.post.call_count == attempts


@pytest.mark.parametrize(
    "endpoint,result_key", [("databases", "DatabaseList"), ("jobs", "Jobs"), ("crawlers", "Crawlers")]
)
def test_top_level_resume_checkpoints_before_yield_and_clears_after_completion(endpoint: str, result_key: str) -> None:
    resume = manager(glue.AwsGlueDataCatalogResumeConfig(next_token="saved"))
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.return_value = response({result_key: [{"Name": "example"}]})
        source = glue.aws_glue_data_catalog_source(config(), endpoint, GLUE_API_VERSION, resume)
        batches = iter(cast(Iterable[list[dict[str, Any]]], source.items()))
        assert next(batches)[0]["name"] == "example"
        resume.save_state.assert_called_once_with(glue.AwsGlueDataCatalogResumeConfig(completed=True))
        resume.clear_state.assert_not_called()
        assert list(batches) == []
        session.close.assert_called_once()
        assert json.loads(session.post.call_args.kwargs["data"]) == {"MaxResults": 100, "NextToken": "saved"}
        assert source.on_complete is not None
        source.on_complete()
        resume.clear_state.assert_called_once()


def test_completed_resume_does_not_restart_and_empty_pages_reach_safe_points() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        resume = manager(glue.AwsGlueDataCatalogResumeConfig(completed=True))
        source = glue.aws_glue_data_catalog_source(config(), "databases", GLUE_API_VERSION, resume)
        assert list(cast(Iterable[Any], source.items())) == []
        factory.return_value.post.assert_not_called()

        resume = manager()
        factory.return_value.post.side_effect = [
            response({"DatabaseList": [], "NextToken": "more"}),
            response({"DatabaseList": []}),
        ]
        source = glue.aws_glue_data_catalog_source(config(), "databases", GLUE_API_VERSION, resume)
        assert list(cast(Iterable[Any], source.items())) == []
        assert resume.safe_point.call_count == 2
        assert [call.args[0] for call in resume.save_state.call_args_list] == [
            glue.AwsGlueDataCatalogResumeConfig(next_token="more"),
            glue.AwsGlueDataCatalogResumeConfig(completed=True),
        ]


def test_partition_walk_pages_each_parent_and_preserves_table_wide_keys() -> None:
    resume = manager(glue.AwsGlueDataCatalogResumeConfig(next_token="irrelevant"))
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.side_effect = [
            response({"DatabaseList": [{"Name": "first", "CatalogId": "123456789012"}], "NextToken": "db-page"}),
            response({"TableList": [{"Name": "events"}], "NextToken": "table-page"}),
            response({"Partitions": [{"Values": ["a,b", "c"]}], "NextToken": "partition-page"}),
            response({"Partitions": [{"Values": ["a", "b,c"]}]}),
            response({"TableList": [{"Name": "users"}]}),
            response({"Partitions": []}),
            response({"DatabaseList": [{"Name": "second", "CatalogId": "123456789012"}]}),
            response({"TableList": [{"Name": "events"}]}),
            response({"Partitions": [{"Values": ["a,b", "c"]}]}),
        ]
        source = glue.aws_glue_data_catalog_source(config(), "partitions", GLUE_API_VERSION, resume)
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], source.items()) for row in batch]

    assert len(rows) == 3
    assert source.primary_keys is not None
    assert len({tuple(row[key] for key in source.primary_keys) for row in rows}) == 3
    assert all(row["catalog_id"] == "123456789012" and row["region"] == "eu-west-1" for row in rows)
    payloads = [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]
    assert payloads[0] == {"MaxResults": 100}
    assert payloads[1] == {"MaxResults": 100, "DatabaseName": "first", "CatalogId": "123456789012"}
    assert payloads[3] == {
        "MaxResults": 100,
        "DatabaseName": "first",
        "TableName": "events",
        "CatalogId": "123456789012",
        "NextToken": "partition-page",
    }
    assert payloads[4]["NextToken"] == "table-page"
    assert payloads[6] == {"MaxResults": 100, "NextToken": "db-page"}
    assert payloads[8]["DatabaseName"] == "second"
    assert "NextToken" not in payloads[8]
    assert not source.supports_resume
    resume.can_resume.assert_not_called()
    resume.save_state.assert_not_called()
    session.close.assert_called_once()


def test_job_run_full_refresh_keeps_old_runs_and_namespaces_ids_by_job() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.side_effect = [
            response({"Jobs": [{"Name": "first"}, {"Name": "second"}]}),
            response({"JobRuns": [{"Id": "run-1", "StartedOn": 1735689600}], "NextToken": "older"}),
            response({"JobRuns": [{"Id": "run-0", "StartedOn": 0}]}),
            response({"JobRuns": [{"Id": "run-1", "StartedOn": 0}]}),
        ]
        source = glue.aws_glue_data_catalog_source(config(), "job_runs", GLUE_API_VERSION, manager())
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], source.items()) for row in batch]
    assert [(row["job_name"], row["id"]) for row in rows] == [
        ("first", "run-1"),
        ("first", "run-0"),
        ("second", "run-1"),
    ]
    assert rows[0]["started_on"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert rows[1]["started_on"] == datetime(1970, 1, 1, tzinfo=UTC)
    assert [json.loads(call.kwargs["data"]) for call in session.post.call_args_list] == [
        {"MaxResults": 100},
        {"MaxResults": 100, "JobName": "first"},
        {"MaxResults": 100, "JobName": "first", "NextToken": "older"},
        {"MaxResults": 100, "JobName": "second"},
    ]


@pytest.mark.parametrize("value", [None, False, "2025-01-01T00:00:00Z", 1735689600])
def test_normalization_preserves_nested_columns_and_handles_optional_timestamps(value: object) -> None:
    descriptor = {"Columns": [{"Name": "event_name", "Type": "string"}]}
    row = glue.normalize_row(
        "tables",
        {"Name": "events", "CreateTime": value, "StorageDescriptor": descriptor},
        "eu-west-1",
        {"DatabaseName": "analytics"},
    )
    assert row["storage_descriptor"] == descriptor
    assert row["database_name"] == "analytics"
    assert row["create_time"] == (datetime(2025, 1, 1, tzinfo=UTC) if value == 1735689600 else value)


@pytest.mark.parametrize("schema_name", [None, "databases"])
@pytest.mark.parametrize(
    "code",
    [
        "AccessDenied",
        "AccessDeniedException",
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
        "SubscriptionRequiredException",
    ],
)
def test_validation_maps_errors_and_accepts_create_time_permission_denials(schema_name: str | None, code: str) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        factory.return_value.post.return_value = response({"__type": code, "Message": "Request denied"}, 403)
        valid, reason = glue.validate_credentials(config(), GLUE_API_VERSION, schema_name)
    accepted = schema_name is None and code in {"AccessDenied", "AccessDeniedException"}
    assert valid is accepted
    if accepted:
        assert reason is None
    else:
        assert reason
        error = glue.error_for_response(response({"__type": code}, 403))
        mappings = AwsGlueDataCatalogSource().get_non_retryable_errors()
        assert any(pattern in str(error) and message == reason for pattern, message in mappings.items())
    factory.return_value.close.assert_called_once()


def test_creation_probes_once_and_selected_child_checks_parent_and_child() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.return_value = response({"DatabaseList": []})
        assert glue.validate_credentials(config(), GLUE_API_VERSION) == (True, None)
        assert session.post.call_count == 1
        assert json.loads(session.post.call_args.kwargs["data"]) == {"MaxResults": 1}

        session.reset_mock()
        session.post.side_effect = [
            response({"Jobs": [{"Name": "example"}]}),
            response({"__type": "AccessDeniedException"}, 403),
        ]
        valid, reason = glue.validate_credentials(config(), GLUE_API_VERSION, "job_runs")
        assert not valid and reason
        assert json.loads(session.post.call_args.kwargs["data"]) == {"MaxResults": 1, "JobName": "example"}


@pytest.mark.parametrize("endpoint", ["tables", "partitions", "job_runs"])
def test_probe_with_no_parents_makes_no_child_request(endpoint: str) -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        factory.return_value.post.return_value = response({"Jobs": [], "DatabaseList": []})
        assert glue.validate_credentials(config(), GLUE_API_VERSION, endpoint) == (True, None)
        assert factory.return_value.post.call_count == 1


def test_invalid_config_and_unknown_tables_fail_without_requests() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        invalid = config()
        invalid.aws_secret_access_key = ""
        assert glue.validate_credentials(invalid, GLUE_API_VERSION) == (
            False,
            "Enter both an AWS access key ID and a secret access key.",
        )
        assert glue.validate_credentials(config(), GLUE_API_VERSION, "unknown") == (
            False,
            "Unknown AWS Glue table: unknown",
        )
        with pytest.raises(ValueError, match="Unknown AWS Glue table"):
            glue.aws_glue_data_catalog_source(config(), "unknown", GLUE_API_VERSION, manager())
        factory.assert_not_called()


def test_network_validation_error_and_failed_iteration_close_session() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.side_effect = requests.Timeout("example timeout")
        assert glue.validate_credentials(config(), GLUE_API_VERSION) == (
            False,
            "Could not connect to AWS Glue. Check the region and try again.",
        )
        session.close.assert_called_once()
        session.reset_mock()
        source = glue.aws_glue_data_catalog_source(config(), "databases", GLUE_API_VERSION, manager())
        with pytest.raises(requests.Timeout):
            list(cast(Iterable[Any], source.items()))
        session.close.assert_called_once()


@pytest.mark.parametrize(
    "error", [glue.AwsGlueError("InternalServiceException", "example"), requests.Timeout("example")]
)
def test_permission_probes_do_not_hide_tables_on_transient_failures(error: Exception) -> None:
    with patch.object(glue, "make_tracked_session"), patch.object(glue.AwsGlueClient, "request", side_effect=error):
        assert glue.probe_endpoint_permissions(config(), GLUE_API_VERSION, ["databases", "unknown"]) == {
            "databases": None
        }


def test_permission_probe_reports_denial_and_invalid_config() -> None:
    with patch.object(glue, "make_tracked_session") as factory:
        factory.return_value.post.return_value = response({"__type": "AccessDeniedException"}, 403)
        permissions = glue.probe_endpoint_permissions(config(), GLUE_API_VERSION, ["databases"])
        assert permissions["databases"] and "Grant" in permissions["databases"]
    assert glue.probe_endpoint_permissions(config("bad"), GLUE_API_VERSION, ["jobs"]) == {
        "jobs": "Enter an AWS region such as us-east-1."
    }
