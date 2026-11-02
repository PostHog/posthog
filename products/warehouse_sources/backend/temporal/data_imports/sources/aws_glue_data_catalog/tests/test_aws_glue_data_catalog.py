import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog import (
    aws_glue_data_catalog as glue,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.settings import (
    GLUE_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.source import (
    AwsGlueDataCatalogSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver() -> SourceDriver:
    return SourceDriver(AwsGlueDataCatalogSource(), config())


@pytest.mark.parametrize(
    "region,token,host",
    [
        ("eu-west-1", None, "glue.eu-west-1.amazonaws.com"),
        ("cn-north-1", "example-token", "glue.cn-north-1.amazonaws.com.cn"),
        ("us-gov-west-1", "example-token", "glue.us-gov-west-1.amazonaws.com"),
    ],
)
def test_signed_request_uses_tracked_transport(region: str, token: str | None, host: str) -> None:
    with scripted_network([ScriptedResponse(json={"DatabaseList": []})]) as network:
        client = glue.AwsGlueClient(config(region, token), GLUE_API_VERSION)
        try:
            assert client.request("GetDatabases", {"MaxResults": 1}) == {"DatabaseList": []}
        finally:
            client.close()

    request = network.requests_log[0]
    assert request.method == "POST"
    assert request.url == f"https://{host}/"
    assert request.json() == {"MaxResults": 1}
    assert request.headers["x-amz-target"] == "AWSGlue.GetDatabases"
    assert request.headers["content-type"] == "application/x-amz-json-1.1"
    assert f"/{region}/glue/aws4_request" in request.headers["authorization"]
    assert "SignedHeaders=content-type;host;x-amz-date" in request.headers["authorization"]
    assert request.headers["x-amz-date"]
    assert request.headers.get("x-amz-security-token") == token
    assert request.read_timeout == 60
    redacted = network.session_options[0]["redact_values"]
    assert "example-secret" in redacted
    if token:
        assert token in redacted
    retry_policy = network.session_options[0]["retry"]
    assert retry_policy.is_retry("POST", 429)
    assert retry_policy.is_retry("POST", 503)
    assert not retry_policy.is_retry("POST", 403)

    with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]) as redirect:
        client = glue.AwsGlueClient(config(region, token), GLUE_API_VERSION)
        try:
            with pytest.raises(glue.AwsGlueError):
                client.request("GetDatabases", {"MaxResults": 1})
        finally:
            client.close()
    assert len(redirect.requests_log) == 1


@pytest.mark.parametrize(
    "region,version,expected",
    [
        ("eu-west-1.example.com/path", GLUE_API_VERSION, "Enter an AWS region"),
        ("", GLUE_API_VERSION, "Enter an AWS region"),
        ("eu-west-1", "2099-01-01", "Unsupported AWS Glue API version"),
    ],
)
def test_rejects_invalid_region_or_version_before_http(region: str, version: str, expected: str) -> None:
    with scripted_network([]) as network:
        with pytest.raises(ValueError, match=expected):
            glue.AwsGlueClient(config(region), version)
    assert network.requests_log == []
    assert network.session_options == []


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
    result = driver().run(
        "databases",
        [ScriptedResponse(json=payload)],
        resume_state=glue.AwsGlueDataCatalogResumeConfig(next_token="same"),
    )
    assert isinstance(result.raised, ValueError)
    assert error in str(result.raised)
    assert result.requests[0].json() == {"MaxResults": 100, "NextToken": "same"}


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
    failure = ScriptedResponse(status=status, json={"__type": "ThrottlingException"})
    script = [failure, ScriptedResponse(json={"DatabaseList": []})] if status == 400 else always(failure)
    result = driver().run("databases", script)
    if status == 400:
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == attempts
    else:
        assert isinstance(result.raised, glue.AwsGlueError)
        assert len(result.requests) > attempts


@pytest.mark.parametrize(
    "endpoint,result_key",
    [
        ("databases", "DatabaseList"),
        ("jobs", "Jobs"),
        ("crawlers", "Crawlers"),
        ("data_quality_results", "Results"),
        ("data_quality_results_v2", "Results"),
        ("sessions", "Sessions"),
    ],
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
    completed = driver().run("databases", [], resume_state=glue.AwsGlueDataCatalogResumeConfig(completed=True))
    assert completed.raised is None
    assert completed.rows == []
    assert completed.requests == []

    result = driver().run(
        "databases",
        [
            ScriptedResponse(json={"DatabaseList": [], "NextToken": "more"}),
            ScriptedResponse(json={"DatabaseList": []}),
        ],
    )
    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 2
    assert result.requests[1].json() == {"MaxResults": 100, "NextToken": "more"}
    expected = [
        glue.AwsGlueDataCatalogResumeConfig(next_token="more"),
        glue.AwsGlueDataCatalogResumeConfig(completed=True),
    ]
    assert result.saved_states == expected
    assert result.committed_states == expected


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
    result = driver().run(
        "job_runs",
        [
            ScriptedResponse(json={"Jobs": [{"Name": "first"}, {"Name": "second"}]}),
            ScriptedResponse(json={"JobRuns": [{"Id": "run-1", "StartedOn": 1735689600}], "NextToken": "older"}),
            ScriptedResponse(json={"JobRuns": [{"Id": "run-0", "StartedOn": 0}]}),
            ScriptedResponse(json={"JobRuns": [{"Id": "run-1", "StartedOn": 0}]}),
        ],
    )
    assert result.raised is None
    rows = result.rows
    assert [(row["job_name"], row["id"]) for row in rows] == [
        ("first", "run-1"),
        ("first", "run-0"),
        ("second", "run-1"),
    ]
    assert rows[0]["started_on"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert rows[1]["started_on"] == datetime(1970, 1, 1, tzinfo=UTC)
    assert [request.json() for request in result.requests] == [
        {"MaxResults": 100},
        {"MaxResults": 100, "JobName": "first"},
        {"MaxResults": 100, "JobName": "first", "NextToken": "older"},
        {"MaxResults": 100, "JobName": "second"},
    ]


@pytest.mark.parametrize(
    "endpoint,script,expected_requests,expected_keys",
    [
        (
            "crawls",
            [
                {"Crawlers": [{"Name": "first"}, {"Name": "second"}]},
                {"Crawls": [{"CrawlId": "crawl-1", "StartTime": 1735689600, "DPUHour": 0.5}], "NextToken": "older"},
                {"Crawls": [{"CrawlId": "crawl-0"}]},
                {"Crawls": [{"CrawlId": "crawl-1"}]},
            ],
            [
                {"MaxResults": 100},
                {"MaxResults": 100, "CrawlerName": "first"},
                {"MaxResults": 100, "CrawlerName": "first", "NextToken": "older"},
                {"MaxResults": 100, "CrawlerName": "second"},
            ],
            [
                ("eu-west-1", "first", "crawl-1"),
                ("eu-west-1", "first", "crawl-0"),
                ("eu-west-1", "second", "crawl-1"),
            ],
        ),
        (
            "workflow_runs",
            [
                {"Workflows": ["first"], "NextToken": "more"},
                {"Runs": [{"Name": "first", "WorkflowRunId": "run-1"}]},
                {"Workflows": ["second"]},
                {"Runs": [{"Name": "second", "WorkflowRunId": "run-1"}]},
            ],
            [
                {"MaxResults": 25},
                {"MaxResults": 100, "Name": "first", "IncludeGraph": False},
                {"MaxResults": 25, "NextToken": "more"},
                {"MaxResults": 100, "Name": "second", "IncludeGraph": False},
            ],
            [("eu-west-1", "first", "run-1"), ("eu-west-1", "second", "run-1")],
        ),
        (
            "table_versions",
            [
                {"DatabaseList": [{"Name": "analytics", "CatalogId": "123456789012"}]},
                {"TableList": [{"Name": "events"}, {"Name": "users"}]},
                {"TableVersions": [{"VersionId": "1", "Table": {"Name": "events"}}]},
                {"TableVersions": [{"VersionId": "1", "Table": {"Name": "users"}}]},
            ],
            [
                {"MaxResults": 100},
                {"MaxResults": 100, "DatabaseName": "analytics", "CatalogId": "123456789012"},
                {"MaxResults": 100, "DatabaseName": "analytics", "TableName": "events", "CatalogId": "123456789012"},
                {"MaxResults": 100, "DatabaseName": "analytics", "TableName": "users", "CatalogId": "123456789012"},
            ],
            [("eu-west-1", "analytics", "events", "1"), ("eu-west-1", "analytics", "users", "1")],
        ),
    ],
)
def test_history_fan_out_pages_each_parent_and_keys_rows_by_parent(
    endpoint: str,
    script: list[dict[str, Any]],
    expected_requests: list[dict[str, Any]],
    expected_keys: list[tuple[str, ...]],
) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json=body) for body in script])
    assert result.raised is None
    assert [request.json() for request in result.requests] == expected_requests
    primary_keys = glue.ENDPOINTS[endpoint].primary_keys
    assert [tuple(row[key] for key in primary_keys) for row in result.rows] == expected_keys
    if endpoint == "crawls":
        assert result.rows[0]["start_time"] == datetime(2025, 1, 1, tzinfo=UTC)
        assert result.rows[0]["dpu_hour"] == 0.5


DATABASE_PAGE = ScriptedResponse(json={"DatabaseList": [{"Name": "analytics", "CatalogId": "123456789012"}]})
NOT_FOUND = ScriptedResponse(status=400, json={"__type": "EntityNotFoundException", "Message": "Not found"})


def iceberg_table(name: str) -> dict[str, Any]:
    return {"Name": name, "CatalogId": "123456789012", "Parameters": {"table_type": "iceberg"}}


def table_with_columns(name: str, count: int) -> dict[str, Any]:
    return {"Name": name, "StorageDescriptor": {"Columns": [{"Name": f"col_{i}", "Type": "int"} for i in range(count)]}}


@pytest.mark.parametrize(
    "endpoint,script,expected_requests,expected_keys",
    [
        (
            "column_statistics",
            [
                DATABASE_PAGE,
                ScriptedResponse(
                    json={
                        "TableList": [
                            table_with_columns("wide", 101),
                            table_with_columns("view", 0),
                            table_with_columns("events", 1),
                        ]
                    }
                ),
                ScriptedResponse(
                    json={
                        "ColumnStatisticsList": [
                            {
                                "ColumnName": "col_0",
                                "ColumnType": "int",
                                "AnalyzedTime": 1735689600,
                                "StatisticsData": {},
                            }
                        ]
                    }
                ),
                ScriptedResponse(json={"ColumnStatisticsList": [], "Errors": [{"ColumnName": "col_100"}]}),
                ScriptedResponse(json={"ColumnStatisticsList": [{"ColumnName": "col_0", "ColumnType": "int"}]}),
            ],
            [
                {"MaxResults": 100},
                {"MaxResults": 100, "DatabaseName": "analytics", "CatalogId": "123456789012"},
                {
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "wide",
                    "ColumnNames": [f"col_{i}" for i in range(100)],
                },
                {
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "wide",
                    "ColumnNames": ["col_100"],
                },
                {
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "events",
                    "ColumnNames": ["col_0"],
                },
            ],
            [("eu-west-1", "analytics", "wide", "col_0"), ("eu-west-1", "analytics", "events", "col_0")],
        ),
        (
            "table_optimizer_runs",
            [
                DATABASE_PAGE,
                ScriptedResponse(
                    json={
                        "TableList": [
                            iceberg_table("events"),
                            {"Name": "hive", "CatalogId": "123456789012", "Parameters": {"classification": "parquet"}},
                        ]
                    }
                ),
                ScriptedResponse(
                    json={
                        "TableOptimizerRuns": [{"eventType": "completed", "startTimestamp": 1735689600}],
                        "NextToken": "older",
                    }
                ),
                ScriptedResponse(json={"TableOptimizerRuns": [{"eventType": "failed", "startTimestamp": 0}]}),
                NOT_FOUND,
                ScriptedResponse(
                    json={"TableOptimizerRuns": [{"eventType": "completed", "startTimestamp": 1735689600}]}
                ),
            ],
            [
                {"MaxResults": 100},
                {"MaxResults": 100, "DatabaseName": "analytics", "CatalogId": "123456789012"},
                {
                    "MaxResults": 100,
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "events",
                    "Type": "compaction",
                },
                {
                    "MaxResults": 100,
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "events",
                    "Type": "compaction",
                    "NextToken": "older",
                },
                {
                    "MaxResults": 100,
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "events",
                    "Type": "retention",
                },
                {
                    "MaxResults": 100,
                    "DatabaseName": "analytics",
                    "CatalogId": "123456789012",
                    "TableName": "events",
                    "Type": "orphan_file_deletion",
                },
            ],
            [
                ("eu-west-1", "analytics", "events", "compaction", datetime(2025, 1, 1, tzinfo=UTC)),
                ("eu-west-1", "analytics", "events", "compaction", datetime(1970, 1, 1, tzinfo=UTC)),
                ("eu-west-1", "analytics", "events", "orphan_file_deletion", datetime(2025, 1, 1, tzinfo=UTC)),
            ],
        ),
    ],
)
def test_table_fan_out_shapes_requests_for_each_table(
    endpoint: str,
    script: list[ScriptedResponse],
    expected_requests: list[dict[str, Any]],
    expected_keys: list[tuple[Any, ...]],
) -> None:
    result = driver().run(endpoint, script)
    assert result.raised is None
    assert [request.json() for request in result.requests] == expected_requests
    primary_keys = glue.ENDPOINTS[endpoint].primary_keys
    assert [tuple(row[key] for key in primary_keys) for row in result.rows] == expected_keys
    assert all(row["catalog_id"] == "123456789012" for row in result.rows)
    if endpoint == "column_statistics":
        assert result.rows[0]["analyzed_time"] == datetime(2025, 1, 1, tzinfo=UTC)
        assert "column_names" not in result.rows[0]


@pytest.mark.parametrize(
    "schema_name,tables,child,expected_requests",
    [
        ("table_optimizer_runs", [iceberg_table("events")], NOT_FOUND, 3),
        ("table_optimizer_runs", [{"Name": "hive", "CatalogId": "123456789012"}], None, 2),
        (
            "column_statistics",
            [table_with_columns("events", 2)],
            ScriptedResponse(json={"ColumnStatisticsList": []}),
            3,
        ),
        ("column_statistics", [table_with_columns("view", 0)], None, 2),
    ],
)
def test_table_fan_out_probe_accepts_tables_without_child_data(
    schema_name: str, tables: list[dict[str, Any]], child: ScriptedResponse | None, expected_requests: int
) -> None:
    script = [DATABASE_PAGE, ScriptedResponse(json={"TableList": tables}), *([child] if child else [])]
    with scripted_network(script) as network:
        assert glue.validate_credentials(config(), GLUE_API_VERSION, schema_name) == (True, None)
    assert len(network.requests_log) == expected_requests
    if schema_name == "column_statistics" and child:
        assert network.requests_log[-1].json() == {
            "DatabaseName": "analytics",
            "CatalogId": "123456789012",
            "TableName": "events",
            "ColumnNames": ["col_0", "col_1"],
        }


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


def test_creation_probes_once() -> None:
    with scripted_network([ScriptedResponse(json={"DatabaseList": []})]) as creation:
        assert glue.validate_credentials(config(), GLUE_API_VERSION) == (True, None)
    assert len(creation.requests_log) == 1
    assert creation.requests_log[0].json() == {"MaxResults": 1}


@pytest.mark.parametrize(
    "schema_name,parent_body,child_payload",
    [
        ("job_runs", {"Jobs": [{"Name": "example"}]}, {"MaxResults": 1, "JobName": "example"}),
        ("workflow_runs", {"Workflows": ["example"]}, {"MaxResults": 1, "Name": "example", "IncludeGraph": False}),
    ],
)
def test_selected_child_checks_parent_and_child(
    schema_name: str, parent_body: dict[str, Any], child_payload: dict[str, Any]
) -> None:
    with scripted_network(
        [
            ScriptedResponse(json=parent_body),
            ScriptedResponse(status=403, json={"__type": "AccessDeniedException"}),
        ]
    ) as selected:
        valid, reason = glue.validate_credentials(config(), GLUE_API_VERSION, schema_name)
    assert not valid and reason
    assert len(selected.requests_log) == 2
    assert selected.requests_log[1].json() == child_payload


@pytest.mark.parametrize("endpoint", ["tables", "partitions", "job_runs"])
def test_probe_with_no_parents_makes_no_child_request(endpoint: str) -> None:
    with scripted_network([ScriptedResponse(json={"Jobs": [], "DatabaseList": []})]) as network:
        assert glue.validate_credentials(config(), GLUE_API_VERSION, endpoint) == (True, None)
    assert len(network.requests_log) == 1


def test_invalid_config_and_unknown_tables_fail_without_requests() -> None:
    with scripted_network([]) as network:
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
    result = driver().run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Glue table" in str(result.raised)
    assert result.requests == []
    assert result.session_options == []
    assert network.requests_log == []
    assert network.session_options == []


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
    script = (
        [ScriptedResponse(status=400, json={"__type": error.code, "Message": "example"})]
        if isinstance(error, glue.AwsGlueError)
        else always(error)
    )
    with scripted_network(script):
        assert glue.probe_endpoint_permissions(config(), GLUE_API_VERSION, ["databases", "unknown"]) == {
            "databases": None
        }


def test_permission_probe_reports_denial_and_invalid_config() -> None:
    with scripted_network([ScriptedResponse(status=403, json={"__type": "AccessDeniedException"})]) as network:
        permissions = glue.probe_endpoint_permissions(config(), GLUE_API_VERSION, ["databases"])
        assert permissions["databases"] and "Grant" in permissions["databases"]
    assert len(network.requests_log) == 1
    assert glue.probe_endpoint_permissions(config("bad"), GLUE_API_VERSION, ["jobs"]) == {
        "jobs": "Enter an AWS region such as us-east-1."
    }
